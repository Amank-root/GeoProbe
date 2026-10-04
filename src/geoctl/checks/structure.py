"""STR-* checks: heading and meta hygiene (CHECKS §3.1). All informational.

These are standard SEO signals that Lighthouse, axe-core, and every commercial
checker already report. They are printed because one place to look is useful;
they are not scored because none is specific to AI crawler access (ADR-010).
"""

from __future__ import annotations

from typing import Any

from ..extract.structure import is_generic_title, is_valid_lang
from ..models import CheckResult
from .base import AuditContext, result, skip

TITLE_MIN, TITLE_MAX = 10, 70
DESC_MIN, DESC_MAX = 50, 160


def _per_page(ctx: AuditContext) -> list[tuple[str, Any]]:
    out = []
    for bundle in ctx.browser_pages():
        if bundle.structure:
            out.append((bundle.url, bundle.structure))
    return out


class STR001Title:
    id = "STR-001"
    category = "structure"
    title = "Title present and specific"
    weight = 0
    tier = "informational"

    def run(self, ctx: AuditContext) -> CheckResult:
        rows = []
        for url, structure in _per_page(ctx):
            t = structure.meta.title
            rows.append(
                {
                    "url": url,
                    "title": t,
                    "length": len(t) if t else 0,
                    "in_range": bool(t) and TITLE_MIN <= len(t) <= TITLE_MAX,
                    "generic": is_generic_title(t, ctx.final_url or ctx.start_url),
                }
            )
        if not rows:
            return skip(self, "no pages were fetched successfully")

        missing = [r for r in rows if not r["title"]]
        evidence = {"pages": rows, "thresholds": {"min": TITLE_MIN, "max": TITLE_MAX}}

        by_title: dict[str, list[str]] = {}
        for r in rows:
            if r["title"]:
                by_title.setdefault(r["title"], []).append(r["url"])
        duplicates = {t: urls for t, urls in by_title.items() if len(urls) > 1}
        evidence["duplicate_titles"] = duplicates

        if len(missing) == len(rows):
            return result(
                self,
                "fail",
                "No page has a <title>.",
                fix="Add a descriptive <title> to every page.",
                evidence=evidence,
            )
        out_of_range = [r for r in rows if r["title"] and not r["in_range"]]
        generic = [r for r in rows if r["generic"]]
        problems = []
        if missing:
            problems.append(f"{len(missing)} page(s) missing a title")
        if out_of_range:
            problems.append(f"{len(out_of_range)} outside {TITLE_MIN}-{TITLE_MAX} chars")
        if generic:
            problems.append(f"{len(generic)} generic or placeholder")
        if duplicates:
            problems.append(f"{len(duplicates)} title(s) duplicated across pages")
        if problems:
            return result(
                self,
                "warn",
                "Titles need work: " + "; ".join(problems) + ".",
                fix="Give each page a unique 10-70 character title. Titles are used as "
                "the citation label and are frequently truncated in AI answers.",
                evidence=evidence,
            )
        return result(self, "pass", "Every sampled page has a specific title.", evidence=evidence)


class STR002Description:
    id = "STR-002"
    category = "structure"
    title = "Meta description present"
    weight = 0
    tier = "informational"

    def run(self, ctx: AuditContext) -> CheckResult:
        rows = []
        for url, structure in _per_page(ctx):
            d = structure.meta.description
            rows.append(
                {
                    "url": url,
                    "description": d,
                    "length": len(d) if d else 0,
                    "in_range": bool(d) and DESC_MIN <= len(d) <= DESC_MAX,
                }
            )
        if not rows:
            return skip(self, "no pages were fetched successfully")
        missing = [r for r in rows if not r["description"]]
        out_of_range = [r for r in rows if r["description"] and not r["in_range"]]
        evidence = {"pages": rows, "thresholds": {"min": DESC_MIN, "max": DESC_MAX}}
        if len(missing) == len(rows):
            return result(
                self,
                "fail",
                "No page has a meta description.",
                fix='Add a <meta name="description"> to every page.',
                evidence=evidence,
            )
        if missing or out_of_range:
            problems = []
            if missing:
                problems.append(f"{len(missing)} page(s) missing")
            if out_of_range:
                problems.append(f"{len(out_of_range)} outside {DESC_MIN}-{DESC_MAX} chars")
            return result(
                self,
                "warn",
                "Meta descriptions: " + "; ".join(problems) + ".",
                fix="Write a 50-160 character description per page.",
                evidence=evidence,
            )
        return result(self, "pass", "Every sampled page has a meta description.", evidence=evidence)


class STR003Canonical:
    id = "STR-003"
    category = "structure"
    title = "Canonical URL"
    weight = 0
    tier = "informational"

    def run(self, ctx: AuditContext) -> CheckResult:
        rows = []
        for url, structure in _per_page(ctx):
            canonical = structure.meta.canonical
            rows.append(
                {
                    "url": url,
                    "final_url": url,
                    "canonical": canonical,
                    "canonical_count": structure.canonical_count,
                    "self_referencing": bool(canonical)
                    and canonical.rstrip("/") == url.rstrip("/"),
                    "absolute": bool(canonical) and canonical.startswith(("http://", "https://")),
                }
            )
        if not rows:
            return skip(self, "no pages were fetched successfully")
        absent = [r for r in rows if not r["canonical"]]
        evidence = {"pages": rows}
        if len(absent) == len(rows):
            return result(
                self,
                "fail",
                "No page declares a canonical URL.",
                fix='Add a self-referencing <link rel="canonical"> to each page.',
                evidence=evidence,
            )
        odd = [
            r
            for r in rows
            if r["canonical"]
            and (not r["self_referencing"] or not r["absolute"] or r["canonical_count"] != 1)
        ]
        if absent or odd:
            problems = []
            if absent:
                problems.append(f"{len(absent)} page(s) missing")
            if odd:
                problems.append(f"{len(odd)} non-self-referencing, relative, or duplicated")
            return result(
                self,
                "warn",
                "Canonical URLs: " + "; ".join(problems) + ".",
                fix="One absolute, self-referencing canonical per page. A canonical pointing "
                "elsewhere is a redirect signal a crawler will honour.",
                evidence=evidence,
            )
        return result(
            self,
            "pass",
            "Every page has one self-referencing absolute canonical.",
            evidence=evidence,
        )


class STR004H1:
    id = "STR-004"
    category = "structure"
    title = "Exactly one H1"
    weight = 0
    tier = "informational"

    def run(self, ctx: AuditContext) -> CheckResult:
        rows = []
        for url, structure in _per_page(ctx):
            h1s = [h.text for h in structure.headings if h.level == 1]
            rows.append(
                {
                    "url": url,
                    "h1_count": len(h1s),
                    "h1_texts": h1s,
                    "empty": bool(h1s) and not any(h1s),
                }
            )
        if not rows:
            return skip(self, "no pages were fetched successfully")
        none = [r for r in rows if r["h1_count"] == 0]
        multiple = [r for r in rows if r["h1_count"] > 1]
        empty = [r for r in rows if r["empty"]]
        evidence = {"pages": rows}
        if len(none) == len(rows):
            return result(
                self,
                "fail",
                "No page has an H1.",
                fix="Add one H1 per page stating what the page is about.",
                evidence=evidence,
            )
        if multiple or empty:
            problems = []
            if multiple:
                problems.append(f"{len(multiple)} page(s) with multiple H1s")
            if empty:
                problems.append(f"{len(empty)} with an empty H1")
            return result(
                self,
                "warn",
                "H1 usage: " + "; ".join(problems) + ".",
                fix="One non-empty H1 per page. The H1 is the strongest single signal of "
                "what a page is about, and is commonly a retrieval anchor.",
                evidence=evidence,
            )
        return result(self, "pass", "Every page has exactly one non-empty H1.", evidence=evidence)


class STR005Hierarchy:
    id = "STR-005"
    category = "structure"
    title = "Heading hierarchy"
    weight = 0
    tier = "informational"

    def run(self, ctx: AuditContext) -> CheckResult:
        rows = []
        for url, structure in _per_page(ctx):
            rows.append(
                {
                    "url": url,
                    "outline": [(h.level, h.text) for h in structure.headings if h.text],
                    "skipped": structure.skipped_levels,
                    "empty_headings": structure.empty_headings,
                    "h1_count": sum(1 for h in structure.headings if h.level == 1),
                }
            )
        if not rows:
            return skip(self, "no pages were fetched successfully")
        no_headings = [r for r in rows if not r["outline"]]
        bad = [r for r in rows if r["skipped"] or r["empty_headings"]]
        evidence = {"pages": rows}
        if len(no_headings) == len(rows):
            return result(
                self,
                "fail",
                "No page has any headings.",
                fix="Structure the page with headings; chunking splits on them.",
                evidence=evidence,
            )
        failing = [
            r
            for r in bad
            if r["h1_count"] > 1 or len(r["skipped"]) > 1 or len(r["empty_headings"]) > 1
        ]
        if failing:
            return result(
                self,
                "fail",
                f"{len(failing)} page(s) combine multiple H1s with skipped levels.",
                fix="Use a single H1 and never skip a level: h2 to h4 is wrong, h2 to h3 is right.",
                evidence=evidence,
            )
        if bad:
            return result(
                self,
                "warn",
                f"{len(bad)} page(s) skip a heading level or have an empty heading.",
                fix="Never skip a level. Chunking splits on headings, so a broken "
                "hierarchy directly degrades retrieval.",
                evidence=evidence,
            )
        return result(
            self, "pass", "Heading hierarchy is clean on every sampled page.", evidence=evidence
        )


class STR006Lang:
    id = "STR-006"
    category = "structure"
    title = "lang attribute"
    weight = 0
    tier = "informational"

    def run(self, ctx: AuditContext) -> CheckResult:
        rows = [
            {"url": url, "lang": s.meta.lang, "valid": is_valid_lang(s.meta.lang)}
            for url, s in _per_page(ctx)
        ]
        if not rows:
            return skip(self, "no pages were fetched successfully")
        absent = [r for r in rows if not r["lang"]]
        invalid = [r for r in rows if r["lang"] and not r["valid"]]
        evidence = {"pages": rows}
        if len(absent) == len(rows):
            return result(
                self,
                "fail",
                "No page declares a lang attribute.",
                fix='Set <html lang="en"> (BCP-47, hyphenated).',
                evidence=evidence,
            )
        if absent or invalid:
            problems = []
            if absent:
                problems.append(f"{len(absent)} page(s) missing lang")
            if invalid:
                bad = ", ".join(sorted({r["lang"] for r in invalid if r["lang"]}))
                problems.append(f"malformed: {bad}")
            return result(
                self,
                "warn",
                "lang attribute: " + "; ".join(problems) + ".",
                fix="Use a BCP-47 tag such as en or en-GB, not en_US.",
                evidence=evidence,
            )
        return result(self, "pass", "Every page declares a valid BCP-47 lang.", evidence=evidence)


STR001 = STR001Title()
STR002 = STR002Description()
STR003 = STR003Canonical()
STR004 = STR004H1()
STR005 = STR005Hierarchy()
STR006 = STR006Lang()

__all__ = ["STR001", "STR002", "STR003", "STR004", "STR005", "STR006"]
