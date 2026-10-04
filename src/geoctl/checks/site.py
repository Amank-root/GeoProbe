"""SITE-001: HTTPS, HSTS, redirect chain sanity (CHECKS §3.5). Informational.

HTTPS is table stakes for any crawler and it costs one check to verify, so it is
reported — but confirming a baseline does not distinguish sites, so it is not
scored (ADR-010).
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from ..models import CheckResult
from .base import AuditContext, result, skip

HSTS_HEADER = "strict-transport-security"


class SITE001Transport:
    id = "SITE-001"
    category = "site"
    title = "HTTPS, HSTS, redirect chain sanity"
    weight = 0
    tier = "informational"

    MAX_HOPS = 1

    def run(self, ctx: AuditContext) -> CheckResult:
        bundle = ctx.start_bundle
        if bundle is None:
            return skip(self, "the start URL was not fetched")

        browser = bundle.fetches.get("browser")
        if browser is None:
            return skip(self, "no browser fetch of the start URL")

        chain = list(browser.redirect_chain)
        hops = len(chain)
        looped = _has_loop(chain)
        start_https = urlparse(ctx.start_url).scheme == "https"
        final_https = urlparse(browser.final_url).scheme == "https"
        hsts = browser.headers.get(HSTS_HEADER)

        evidence: dict[str, Any] = {
            "start_url": ctx.start_url,
            "final_url": browser.final_url,
            "redirect_chain": chain,
            "hop_count": hops,
            "loop_detected": looped,
            "start_https": start_https,
            "final_https": final_https,
            "hsts": hsts,
            "hsts_max_age": _max_age(hsts) if hsts else None,
            "max_hops": self.MAX_HOPS,
        }

        if browser.error and browser.status is None:
            return result(
                self, "error", f"Could not fetch the start URL: {browser.error}", evidence=evidence
            )

        if not final_https:
            return result(
                self,
                "fail",
                "The site is not served over HTTPS.",
                fix="Serve every page over HTTPS and redirect HTTP to HTTPS.",
                evidence=evidence,
            )
        if looped:
            return result(
                self,
                "fail",
                f"The redirect chain loops ({hops} hops).",
                fix="Fix the redirect loop; a crawler will give up and treat the "
                "page as unreachable.",
                evidence=evidence,
            )
        if not hsts:
            return result(
                self,
                "warn",
                "HTTPS, but no Strict-Transport-Security header.",
                fix="Add Strict-Transport-Security, for example "
                "`max-age=63072000; includeSubDomains`.",
                evidence=evidence,
            )
        if hops > self.MAX_HOPS:
            return result(
                self,
                "warn",
                f"HTTPS with HSTS, but the redirect chain is {hops} hops.",
                fix="Point the entry URL at the final URL directly; every extra hop "
                "is a fetch a crawler has to make.",
                evidence=evidence,
            )
        return result(
            self,
            "pass",
            f"HTTPS with HSTS ({hsts}) and at most {self.MAX_HOPS} redirect hop.",
            evidence=evidence,
        )


def _has_loop(chain: list[dict[str, Any]]) -> bool:
    seen = set()
    for hop in chain:
        key = (hop.get("from"), hop.get("to"))
        if key in seen:
            return True
        seen.add(key)
    return False


def _max_age(hsts: str) -> int | None:
    for part in hsts.split(";"):
        part = part.strip()
        if part.lower().startswith("max-age="):
            try:
                return int(part.split("=", 1)[1])
            except ValueError:
                return None
    return None


SITE001 = SITE001Transport()

__all__ = ["SITE001"]
