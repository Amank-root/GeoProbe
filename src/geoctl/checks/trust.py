"""TRU-* checks: authorship and dates (CHECKS §3.4). All informational."""

from __future__ import annotations

import re
from typing import Any

from ..extract.structured_data import first_value, names
from ..fetch.sitemap import parse_date
from ..models import CheckResult
from .base import AuditContext, result, skip

_META_DATE_KEYS = (
    "article:published_time",
    "article:modified_time",
    "og:updated_time",
    "date",
    "datepublished",
    "publish_date",
)

# Human-readable date text like "March 4, 2026" — present but not machine-readable.
_LOOSE_DATE = re.compile(
    r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?"
    r"|aug(?:ust)?|sep(?:t)?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
    r"\s+\d{1,2},?\s+\d{4}\b",
    re.IGNORECASE,
)


class TRU001Dates:
    id = "TRU-001"
    category = "trust"
    title = "Publish / modified dates"
    weight = 0
    tier = "informational"

    def run(self, ctx: AuditContext) -> CheckResult:
        rows: list[dict[str, Any]] = []
        for bundle in ctx.browser_pages():
            found, sources, bogus = self._dates_for(bundle)
            rows.append(
                {
                    "url": bundle.url,
                    "dates": found,
                    "sources": sources,
                    "unparseable": bogus,
                    "machine_readable": bool(sources),
                }
            )
        if not rows:
            return skip(self, "no pages were fetched successfully")

        none = [r for r in rows if not r["dates"]]
        unparseable = [r for r in rows if r["unparseable"]]
        stale = self._sitemap_stale(ctx)
        evidence = {"pages": rows, "stale_lastmod": stale}

        if len(none) == len(rows):
            return result(
                self,
                "fail",
                "No machine-readable publish or modified date was found.",
                fix="Add article:published_time and article:modified_time meta tags, or "
                "datePublished and dateModified in JSON-LD.",
                evidence=evidence,
            )
        if unparseable or stale or len(none) < len(rows):
            problems = []
            if unparseable:
                problems.append(f"{len(unparseable)} page(s) with an unparseable date")
            if stale:
                problems.append(f"{len(stale)} sitemap URL(s) with a stale or future lastmod")
            if len(none) < len(rows):
                problems.append(f"{len(none)} page(s) with no date at all")
            return result(
                self,
                "warn",
                "Dates need work: " + "; ".join(problems) + ".",
                fix="Publish machine-readable dates. A lastmod in the future is a "
                "common sitemap defect and misleads crawlers.",
                evidence=evidence,
            )
        return result(
            self, "pass", "Every sampled page carries a machine-readable date.", evidence=evidence
        )

    def _dates_for(self, bundle: Any) -> tuple[list[str], list[str], list[str]]:
        """Return (values found, machine-readable sources, unparseable values)."""
        found: list[str] = []
        sources: list[str] = []
        bogus: list[str] = []

        structure = bundle.structure
        if structure:
            for key in _META_DATE_KEYS:
                value = structure.meta_tags.get(key)
                if value:
                    found.append(value)
                    sources.append(f"meta:{key}")
                    if parse_date(value) is None:
                        bogus.append(f"meta:{key}={value}")
            for value in structure.time_datetimes:
                found.append(value)
                sources.append("time[datetime]")
                if parse_date(value) is None:
                    bogus.append(f"time[datetime]={value}")

        sd = bundle.structured_data
        if sd:
            for item in sd.items:
                for key in ("datePublished", "dateModified", "dateCreated", "uploadDate"):
                    value = item.get(key)
                    if isinstance(value, str) and value:
                        found.append(value)
                        sources.append(f"jsonld:{key}")
                        if parse_date(value) is None:
                            bogus.append(f"jsonld:{key}={value}")

        # Visible prose dates count as "present but not machine-readable", which
        # CHECKS TRU-001 puts in the warn band rather than failing.
        visible = _LOOSE_DATE.findall(structure.body_text if structure else "")
        if visible and not sources:
            found.extend(visible[:3])
        return found, sources, bogus

    def _sitemap_stale(self, ctx: AuditContext) -> list[str]:
        # The sitemap report already classified these, so re-checking them here
        # would need the raw lastmod values it does not keep.
        return list(ctx.sitemap.stale_lastmod) if ctx.sitemap else []


class TRU002Author:
    id = "TRU-002"
    category = "trust"
    title = "Author or organization identified"
    weight = 0
    tier = "informational"

    def run(self, ctx: AuditContext) -> CheckResult:
        rows: list[dict[str, Any]] = []
        for bundle in ctx.browser_pages():
            source, value = self._identify(bundle)
            rows.append(
                {"url": bundle.url, "source": source, "value": value, "found": bool(source)}
            )
        if not rows:
            return skip(self, "no pages were fetched successfully")

        none = [r for r in rows if not r["found"]]
        org_only = [r for r in rows if r["found"] and r["source"] == "jsonld:publisher"]
        evidence = {"pages": rows}
        if len(none) == len(rows):
            return result(
                self,
                "fail",
                "No author or organization signal was found.",
                fix="Add an Organization or Person entity to your JSON-LD, or an author byline "
                "on content pages.",
                evidence=evidence,
            )
        if org_only:
            return result(
                self,
                "warn",
                f"An organization is named on {len(org_only)} page(s) but no author is "
                "identified on content pages.",
                fix="Name an author on posts and documentation pages. Trust signals are what "
                "let a reader (or a model) attribute a claim.",
                evidence=evidence,
            )
        return result(self, "pass", "An author or organization is identifiable.", evidence=evidence)

    def _identify(self, bundle: Any) -> tuple[str | None, str | None]:
        sd = bundle.structured_data
        if sd:
            for item in sd.items:
                for key in ("author", "publisher", "creator"):
                    value = first_value(item, key)
                    if isinstance(value, str) and value.strip():
                        return f"jsonld:{key}", value.strip()
                    if isinstance(value, dict):
                        inner = value.get("name")
                        if isinstance(inner, str) and inner.strip():
                            return f"jsonld:{key}.name", inner.strip()
                    if isinstance(value, list) and value:
                        first = value[0]
                        if isinstance(first, dict) and isinstance(first.get("name"), str):
                            return f"jsonld:{key}[].name", first["name"]
            if names(sd):
                return "jsonld:name", names(sd)[0]
        structure = bundle.structure
        if structure:
            for key in ("author", "article:author", "og:site_name"):
                node = structure.meta.og.get(key)
                if node:
                    return f"meta:{key}", node
            for h in structure.headings:
                if h.level <= 2 and "author" in h.text.lower():
                    return "visible:heading", h.text
        return None, None


TRU001 = TRU001Dates()
TRU002 = TRU002Author()

__all__ = ["TRU001", "TRU002"]
