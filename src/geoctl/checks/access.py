"""ACC-* checks: what a crawler actually receives (CHECKS §4).

These carry 75 of the 100 scored points, because they are the only checks that
observe reality rather than declarations. A robots.txt parse cannot see WAF
rules or user-agent cloaking; ACC-002 can.
"""

from __future__ import annotations

from typing import Any

from ..fetch.bots import Bot, resolve
from ..fetch.client import compare_parity
from ..models import CheckResult
from .base import AuditContext, result, skip

# Similarity bands from CHECKS ACC-002.
PASS_SIMILARITY = 0.9
WARN_SIMILARITY = 0.6
# A minority of pages differing is a warn; a majority is a fail.
MINORITY_PAGE_RATIO = 0.5


class ACC001Robots:
    id = "ACC-001"
    category = "access"
    title = "robots.txt rules per AI bot"
    weight = 25
    tier = "scored"

    def run(self, ctx: AuditContext) -> CheckResult:
        robots = ctx.robots
        if robots is None:
            return skip(self, "robots.txt was not fetched")
        if robots.parse_failed:
            return result(self, "warn", "robots.txt could not be parsed; treated as no rules",
                          evidence={"robots_url": robots.url, "parse_error": True})

        blocked = sorted(
            name for name, v in robots.verdicts.items() if v["verdict"] == "blocked"
        )
        # A missing robots.txt is default-allow and is a pass, with the absence
        # itself reported so the user can tell the difference (CHECKS ACC-001).
        if not blocked:
            message = (
                "No robots.txt; all configured bots are allowed by default."
                if not robots.found
                else f"All {len(robots.verdicts)} configured bots are allowed."
            )
            return result(self, "pass", message, evidence=self._evidence(ctx))

        if ctx.policy == "ignore":
            return result(
                self, "pass",
                f"{len(blocked)} bots are blocked; --policy ignore treats this as a decision",
                          evidence=self._evidence(ctx))
        if ctx.policy == "report":
            return result(
                self, "warn",
                f"{len(blocked)} of {len(robots.verdicts)} bots are blocked by robots.txt "
                f"({', '.join(blocked)}). Reported as policy, not failure.",
                fix="Confirm this block is deliberate. Blocking training bots while allowing "
                    "search bots is a legitimate policy; blocking search or user-triggered "
                    "bots usually is not.",
                evidence=self._evidence(ctx),
            )
        return result(
            self, "fail",
            f"{len(blocked)} of {len(robots.verdicts)} bots are blocked by robots.txt "
            f"({', '.join(blocked)}).",
            fix="Relax the robots.txt rules for the bots you want to reach, or accept the "
                "block with --policy report.",
            evidence=self._evidence(ctx),
        )

    def _evidence(self, ctx: AuditContext) -> dict[str, Any]:
        robots = ctx.robots
        if robots is None:  # pragma: no cover - run() returns before this
            return {}
        blocked = sorted(n for n, v in robots.verdicts.items() if v["verdict"] == "blocked")
        bots = resolve(ctx.bot_names)
        purposes = {b.name: b.purpose for b in bots}
        return {
            "robots_url": robots.url,
            "robots_present": robots.found,
            "policy": ctx.policy,
            "bots": [
                {
                    "bot": name,
                    "purpose": purposes.get(name),
                    "verdict": v["verdict"],
                    "token": v.get("token"),
                    "matched_rule": v.get("matched_rule"),
                }
                for name, v in sorted(robots.verdicts.items())
            ],
            "blocked": blocked,
            "blocked_by_purpose": _by_purpose(blocked, ctx),
        }


class ACC002Parity:
    id = "ACC-002"
    category = "access"
    title = "Bot vs browser fetch parity"
    weight = 30
    tier = "scored"

    def run(self, ctx: AuditContext) -> CheckResult:
        bots = resolve(ctx.bot_names)
        comparisons: list[dict[str, Any]] = []
        for bundle in ctx.pages:
            browser = bundle.fetches.get("browser")
            if not browser or not browser.ok:
                continue
            browser_text = bundle.browser_text
            for bot in bots:
                bot_fetch = bundle.fetches.get(bot.name)
                if bot_fetch is None:
                    continue
                bot_view = bundle.views.get(bot.name)
                row = compare_parity(
                    browser, bot_fetch, browser_text, (bot_view.text if bot_view else "")
                )
                row["url"] = bundle.url
                row["bot"] = bot.name
                comparisons.append(row)

        if not comparisons:
            return skip(self, "no page returned a successful browser fetch to compare against")

        by_bot: dict[str, list[dict[str, Any]]] = {}
        for row in comparisons:
            by_bot.setdefault(row["bot"], []).append(row)

        diverged: list[dict[str, Any]] = []
        for bot, rows in by_bot.items():
            blocked_rows = [
                r for r in rows
                if not r["status_match"]
                or (r["bot_error"] and r["bot_blocked_by"] in ("waf", "challenge"))
                or (r["text_similarity"] is not None and r["text_similarity"] < PASS_SIMILARITY)
                or (r["bot_chars"] == 0)
            ]
            if blocked_rows:
                diverged.append(
                    {
                        "bot": bot,
                        "diverged_pages": len(blocked_rows),
                        "total_pages": len(rows),
                        "share": round(len(blocked_rows) / len(rows), 4),
                        "samples": blocked_rows[:5],
                    }
                )

        evidence = {
            "pages_compared": len(comparisons),
            "bots": [b.name for b in bots],
            "divergence": diverged,
            "thresholds": {
                "pass_similarity": PASS_SIMILARITY,
                "warn_similarity": WARN_SIMILARITY,
            },
            "per_page": comparisons,
        }

        if not diverged:
            return result(self, "pass",
                          f"All {len(bots)} bots receive the same content as a browser on "
                          f"{len(comparisons)} fetches.",
                          evidence=evidence)

        majority = [d for d in diverged if d["share"] > MINORITY_PAGE_RATIO]
        if majority:
            names = ", ".join(d["bot"] for d in majority)
            return result(
                self, "fail",
                f"{names} receive different content than a browser on a majority of pages.",
                fix="Check WAF / bot-protection rules for these user-agents. A robots.txt "
                    "parse cannot see this, which is why the fetch comparison exists.",
                evidence=evidence,
            )
        names = ", ".join(d["bot"] for d in diverged)
        return result(
            self, "warn",
            f"{names} differ from the browser view on a minority of pages.",
            fix="Check WAF / bot-protection rules for these user-agents.",
            evidence=evidence,
        )


class ACC003NoBlock:
    id = "ACC-003"
    category = "access"
    title = "No blocking status or challenge page"
    weight = 20
    tier = "scored"

    BLOCKING: frozenset[str] = frozenset({"waf", "challenge"})

    def run(self, ctx: AuditContext) -> CheckResult:
        blocked: list[dict[str, Any]] = []
        total = 0
        for bundle in ctx.pages:
            for name, fetch in bundle.fetches.items():
                if fetch.error is None and fetch.status is None:
                    continue
                total += 1
                if fetch.blocked_by in self.BLOCKING or (
                    fetch.status is not None and fetch.status >= 400
                ):
                    blocked.append(
                        {
                            "url": bundle.url,
                            "lens": name,
                            "status": fetch.status,
                            "blocked_by": fetch.blocked_by,
                            "challenge": fetch.challenge_marker,
                            "error": fetch.error,
                        }
                    )

        start = ctx.start_bundle
        start_blocked = bool(start) and any(
            row["url"] == ctx.start_url and row["lens"] == "browser" for row in blocked
        )

        evidence = {
            "responses_examined": total,
            "blocked_responses": len(blocked),
            "details": blocked[:20],
            "policy": ctx.policy,
        }

        if not blocked:
            return result(self, "pass", "No blocking status or challenge page observed.",
                          evidence=evidence)

        if start_blocked and ctx.policy != "ignore":
            return result(
                self, "fail",
                f"The start URL is blocked ({blocked[0]['blocked_by'] or blocked[0]['status']}).",
                fix="Your own site is refusing the simulated crawlers. geoctl sends an "
                    "X-Geoctl-Test header and aims to audit sites you control.",
                evidence=evidence,
            )

        share = len(blocked) / total if total else 1.0
        if share > MINORITY_PAGE_RATIO and ctx.policy == "fail":
            return result(self, "fail",
                          f"{len(blocked)} of {total} responses were blocked or challenged.",
                          evidence=evidence)
        return result(
            self, "warn",
            f"{len(blocked)} of {total} responses were blocked or challenged, "
            "including at least one challenge page returned with 200.",
            fix="A 200 challenge page reads as success on status alone. Check bot-protection "
                "configuration for the affected paths.",
            evidence=evidence,
        )


def _by_purpose(blocked: list[str], ctx: AuditContext) -> dict[str, list[str]]:
    purposes = {b.name: b.purpose for b in resolve(ctx.bot_names)}
    out: dict[str, list[str]] = {}
    for name in blocked:
        out.setdefault(purposes.get(name, "other"), []).append(name)
    return out


# Module-level singletons: registration is an explicit list, so checks are
# stateless objects.
ACC001 = ACC001Robots()
ACC002 = ACC002Parity()
ACC003 = ACC003NoBlock()

__all__ = ["ACC001", "ACC002", "ACC003", "Bot"]