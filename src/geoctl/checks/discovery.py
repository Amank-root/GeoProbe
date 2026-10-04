"""DIS-* checks: discovery (CHECKS §3.3, §6). DIS-001 scored at 1, rest informational."""

from __future__ import annotations

from typing import Any

from ..models import CheckResult
from .base import AuditContext, result, skip

LLMS_TXT_PATH = "/llms.txt"


class DIS001Sitemap:
    id = "DIS-001"
    category = "discovery"
    title = "Sitemap present and valid"
    weight = 1
    tier = "scored"

    def run(self, ctx: AuditContext) -> CheckResult:
        sitemap = ctx.sitemap
        if sitemap is None:
            return skip(self, "no sitemap was discovered")

        evidence: dict[str, Any] = {
            "found": sitemap.found,
            "sitemap_urls": sitemap.sitemap_urls,
            "url_count": len(sitemap.urls),
            "parse_errors": sitemap.parse_errors,
            "includes_start_url": sitemap.includes_start_url,
            "stale_lastmod": sitemap.stale_lastmod[:20],
            "sample": sitemap.urls[:10],
        }

        if not sitemap.found:
            return result(
                self, "fail",
                "No sitemap found (checked robots.txt Sitemap: directives and /sitemap.xml).",
                fix="Publish a sitemap.xml and reference it from robots.txt. It is the cheapest "
                    "way for a crawler to enumerate your pages.",
                evidence=evidence,
            )
        if sitemap.parse_errors or not sitemap.includes_start_url:
            problems = []
            if sitemap.parse_errors:
                problems.append(f"{len(sitemap.parse_errors)} parse problem(s)")
            if not sitemap.includes_start_url:
                problems.append("the start URL is not listed")
            return result(self, "warn", "Sitemap found but: " + "; ".join(problems) + ".",
                          fix="Fix the parse errors and list the page you are auditing.",
                          evidence=evidence)
        return result(self, "pass",
                      f"Sitemap found with {len(sitemap.urls)} same-origin URLs, including "
                      "the start URL.",
                      evidence=evidence)


class DIS002Indexing:
    id = "DIS-002"
    category = "discovery"
    title = "Indexing / snippet directives"
    weight = 0
    tier = "informational"

    CONFLICTING = ("noindex", "nosnippet", "noarchive", "none")

    def run(self, ctx: AuditContext) -> CheckResult:
        rows = []
        sitemap_urls = set(ctx.sitemap.urls) if ctx.sitemap else set()
        for bundle in ctx.browser_pages():
            if not bundle.structure:
                continue
            directives = (bundle.structure.meta.robots_meta or "").lower()
            found = [d for d in self.CONFLICTING if d in directives]
            rows.append(
                {
                    "url": bundle.url,
                    "robots_meta": bundle.structure.meta.robots_meta,
                    "directives": found,
                    "in_sitemap": bundle.url in sitemap_urls,
                }
            )
        if not rows:
            return skip(self, "no pages were fetched successfully")

        start = rows[0]
        contradictions = [r for r in rows if r["directives"] and r["in_sitemap"]]
        evidence = {"pages": rows, "contradictions": contradictions}

        if "noindex" in start["directives"]:
            return result(
                self, "fail",
                "The start URL carries a noindex directive.",
                fix="Remove the noindex meta tag. It tells crawlers not to index this page, "
                    "which silently defeats your own crawl strategy.",
                evidence=evidence,
            )
        if contradictions:
            return result(
                self, "warn",
                f"{len(contradictions)} page(s) are listed in the sitemap but declare "
                f"{', '.join(sorted({d for r in contradictions for d in r['directives']}))}.",
                fix="Remove the page from the sitemap or drop the directive. A sitemap is a "
                    "request to index, so the two contradict each other.",
                evidence=evidence,
            )
        clean = [r for r in rows if not r["directives"]]
        if len(clean) == len(rows):
            return result(self, "pass", "No conflicting indexing directives found.",
                          evidence=evidence)
        return result(
            self, "warn",
            f"{len(rows) - len(clean)} page(s) declare indexing directives that are not in the "
            "sitemap.",
            fix="Intentional? A nosnippet or noarchive directive can suppress how a result is "
                "surfaced.",
            evidence=evidence,
        )


class DIS003LlmsTxt:
    id = "DIS-003"
    category = "discovery"
    title = "llms.txt presence and shape"
    weight = 0
    tier = "informational"

    def run(self, ctx: AuditContext) -> CheckResult:
        fetch = ctx.llms_txt
        if fetch is None:
            return skip(self, "/llms.txt was not fetched")
        evidence: dict[str, Any] = {
            "url": fetch.url,
            "status": fetch.status,
            "content_type": fetch.headers.get("content-type"),
        }

        if fetch.status == 404 or (fetch.error and fetch.status is None):
            # Explicitly not a penalty: current public evidence says crawlers
            # essentially never fetch this file (CHECKS §7).
            return result(
                self, "fail",
                "/llms.txt is not present.",
                evidence=evidence,
            )
        if not fetch.ok:
            return result(self, "warn", f"/llms.txt returned HTTP {fetch.status}.",
                          evidence=evidence)

        body = (fetch.body or b"").decode("utf-8", "replace")
        has_h1 = any(line.startswith("# ") for line in body.splitlines())
        links = [line for line in body.splitlines() if "](" in line]
        summary_lines = [
            line for line in body.splitlines()
            if line.strip() and not line.startswith(("#", "-", "["))
        ]
        evidence.update(
            {"bytes": len(body), "has_h1": has_h1, "link_count": len(links),
             "has_summary": bool(summary_lines)}
        )
        content_type = (fetch.headers.get("content-type") or "")
        evidence["is_markdown"] = "text/plain" in content_type or "text/markdown" in content_type

        problems = []
        if not has_h1:
            problems.append("no H1")
        if not links:
            problems.append("no link sections")
        if not summary_lines:
            problems.append("no summary text")
        if problems:
            return result(self, "warn",
                          "/llms.txt exists but is malformed (" + ", ".join(problems) + ").",
                          evidence=evidence)
        return result(self, "pass", "/llms.txt is present and well-formed.", evidence=evidence)


DIS001 = DIS001Sitemap()
DIS002 = DIS002Indexing()
DIS003 = DIS003LlmsTxt()

__all__ = ["DIS001", "DIS002", "DIS003", "LLMS_TXT_PATH"]