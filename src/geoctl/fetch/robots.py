"""robots.txt parsing and per-bot evaluation (Protego, ADR-013).

The stdlib parser mishandles wildcards, `$`, and `Allow` precedence, and getting
those wrong would make ACC-001 lie about a site. Missing robots.txt is 200-OK
for everyone by convention, so it is a pass.
"""

from __future__ import annotations

from typing import Any

from protego import Protego

from ..models import RobotsReport

Verdict = str  # allowed | blocked | partial | unmentioned

ROBOTS_PATH = "/robots.txt"


def robots_url(base: str) -> str:
    from urllib.parse import urlparse

    p = urlparse(base)
    return f"{p.scheme}://{p.netloc}{ROBOTS_PATH}"


def parse_robots(text: str) -> Protego | None:
    """Parse robots.txt, tolerating the malformed files real sites serve.

    Protego raises on some malformed inputs; a parser crash must not abort an
    audit, so failure degrades to "no rules" and is flagged in evidence.
    """
    try:
        return Protego.parse(text)
    except Exception:
        return None


def evaluate(robot: Protego | None, path: str, token: str) -> tuple[Verdict, str | None]:
    """Evaluate one path for one bot token. Returns (verdict, matched_rule).

    Protego's signature is can_fetch(url, user_agent) — URL first. Passing them
    the other way round silently returns True for every bot, which would make
    ACC-001 report "allowed" on every site ever audited.
    """
    if robot is None:
        return ("allowed", None)
    url = path if path.startswith("http") else f"/{path.lstrip('/')}"
    allowed = robot.can_fetch(url, str(token))
    return ("allowed" if allowed else "blocked", _rule_evidence(token, allowed))


def _rule_evidence(token: str, allowed: bool) -> str:
    # Protego exposes only the decision, not the winning rule line. Recording
    # the decision is honest; reconstructing a rule string would be fiction.
    return f"can_fetch({token}) -> {'allow' if allowed else 'disallow'}"


def evaluate_all(
    text: str | None,
    path: str,
    tokens: dict[str, str],
    base_url: str,
) -> RobotsReport:
    """Evaluate every (bot name -> robots token) pair against one path.

    `text` is None when robots.txt was absent (404/410/5xx), which is
    default-allow and reported as `found: false`.
    """
    report = RobotsReport(url=robots_url(base_url), found=text is not None)
    if text is None:
        for name, token in tokens.items():
            report.verdicts[name] = {
                "verdict": "allowed",
                "token": token,
                "matched_rule": None,
                "robots_present": False,
            }
        return report

    robot = parse_robots(text)
    report.parse_failed = robot is None
    report.sitemaps = _sitemaps(robot)
    for name, token in tokens.items():
        verdict, rule = evaluate(robot, path, token)
        report.verdicts[name] = {
            "verdict": verdict,
            "token": token,
            "matched_rule": rule,
            "robots_present": True,
        }
    return report


def _sitemaps(robot: Protego | None) -> list[str]:
    if robot is None:
        return []
    try:
        entries = list(robot.sitemaps)
    except Exception:
        return []
    out = []
    for entry in entries:
        url = getattr(entry, "url", entry)
        if url:
            out.append(str(url))
    return out


def classify_verdict_list(verdicts: dict[str, dict[str, Any]]) -> Verdict:
    """Overall robots posture across bots."""
    values = [v.get("verdict") for v in verdicts.values()]
    if not values:
        return "unmentioned"
    if all(v == "blocked" for v in values):
        return "blocked"
    if any(v == "blocked" for v in values):
        return "partial"
    return "allowed"
