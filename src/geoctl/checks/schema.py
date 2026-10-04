"""SD-* checks: structured data (CHECKS §3.2). All informational."""

from __future__ import annotations

from ..extract.structure import og_tags
from ..extract.structured_data import entity_types, expected_types, infer_role
from ..models import CheckResult
from .base import AuditContext, result, skip

# Organization is the one type SD-002 treats as mandatory on the home page: it
# is what tells a system who the site belongs to.
HOME_MANDATORY = "Organization"


class SD001JsonLd:
    id = "SD-001"
    category = "structured_data"
    title = "JSON-LD present and parses"
    weight = 0
    tier = "informational"

    def run(self, ctx: AuditContext) -> CheckResult:
        rows = []
        for bundle in ctx.browser_pages():
            sd = bundle.structured_data
            if sd is None:
                continue
            rows.append(
                {
                    "url": bundle.url,
                    "blocks": sd.block_count,
                    "parsed": sd.parsed_count,
                    "types": sd.types,
                    "errors": sd.parse_errors,
                }
            )
        if not rows:
            return skip(self, "no pages were fetched successfully")

        no_blocks = [r for r in rows if r["blocks"] == 0]
        unparsed = [r for r in rows if r["blocks"] > 0 and r["parsed"] == 0]
        no_types = [r for r in rows if r["parsed"] > 0 and not r["types"]]
        evidence = {"pages": rows}

        if len(no_blocks) == len(rows):
            return result(self, "fail", "No page has a JSON-LD block.",
                          fix="Add a <script type=\"application/ld+json\"> block to each page "
                              "template.",
                          evidence=evidence)
        if unparsed or no_types:
            problems = []
            if unparsed:
                problems.append(
                    f"{len(unparsed)} page(s) where no block parses "
                    f"(errors: {unparsed[0]['errors'][:1]})"
                )
            if no_types:
                problems.append(f"{len(no_types)} page(s) parse but declare no @type")
            return result(self, "warn", "JSON-LD needs work: " + "; ".join(problems) + ".",
                          fix="Each block must be valid JSON with a recognized @type.",
                          evidence=evidence)
        return result(self, "pass", "JSON-LD is present and parses on every sampled page.",
                      evidence=evidence)


class SD002EntityTypes:
    id = "SD-002"
    category = "structured_data"
    title = "Appropriate entity types"
    weight = 0
    tier = "informational"

    def run(self, ctx: AuditContext) -> CheckResult:
        rows = []
        for bundle in ctx.browser_pages():
            sd = bundle.structured_data
            if sd is None:
                continue
            types = entity_types(sd)
            role = infer_role(bundle.path, bundle.title, types)
            expected = expected_types(role)
            missing = sorted(t for t in expected if t not in types) if expected else []
            rows.append(
                {
                    "url": bundle.url,
                    "role": role,
                    "types": sorted(types),
                    "expected_any_of": sorted(expected),
                    "missing": missing,
                }
            )
        if not rows:
            return skip(self, "no pages were fetched successfully")

        no_jsonld = [r for r in rows if not r["types"]]
        evidence = {"pages": rows, "home_mandatory": HOME_MANDATORY}

        if len(no_jsonld) == len(rows):
            return result(self, "fail", "No page declares any structured data entity type.",
                          fix="Add Organization and WebSite JSON-LD to the home page, and the "
                              "matching type (Article, Product, FAQPage) elsewhere.",
                          evidence=evidence)

        start = ctx.start_bundle
        start_home = start is not None and start.path in ("/", "", "/index.html")
        start_sd = start.structured_data if start else None
        home_missing_org = (
            start_home and start_sd is not None
            and HOME_MANDATORY not in entity_types(start_sd)
        )
        if home_missing_org:
            return result(
                self, "fail",
                f"No {HOME_MANDATORY} JSON-LD on the home page.",
                fix=f"Add {HOME_MANDATORY} JSON-LD to your layout or home page template.",
                evidence=evidence,
            )

        mismatched = [r for r in rows if r["missing"]]
        if mismatched:
            return result(
                self, "warn",
                f"{len(mismatched)} page(s) have JSON-LD that does not match the page's role "
                f"({mismatched[0]['role']} expected one of {mismatched[0]['expected_any_of']}).",
                fix="Match the JSON-LD @type to the page role: Article for posts, Product for "
                    "product pages, FAQPage for FAQ pages.",
                evidence=evidence,
            )
        return result(self, "pass", "Structured data types match every inferred page role.",
                      evidence=evidence)


class SD003OpenGraph:
    id = "SD-003"
    category = "structured_data"
    title = "Open Graph basics"
    weight = 0
    tier = "informational"

    def run(self, ctx: AuditContext) -> CheckResult:
        rows = []
        for bundle in ctx.browser_pages():
            if not bundle.structure:
                continue
            tags = og_tags(bundle.structure.meta.og)
            is_home = bundle.path in ("/", "", "/index.html")
            rows.append({"url": bundle.url, "is_home": is_home,
                         "tags": {k: bool(v) for k, v in tags.items()}})
        if not rows:
            return skip(self, "no pages were fetched successfully")

        no_og = [r for r in rows if not any(r["tags"].values())]
        evidence = {"pages": rows, "home_tags": ["og:title", "og:description", "og:url",
                                                 "og:image"]}
        if len(no_og) == len(rows):
            return result(self, "fail", "No page declares Open Graph tags.",
                          fix="Add og:title and og:description to every page, plus og:url and "
                              "og:image on the home page.",
                          evidence=evidence)

        problems: list[str] = []
        for row in rows:
            t = row["tags"]
            if not t["og:title"]:
                problems.append(f"{row['url']}: no og:title")
            elif not t["og:description"]:
                problems.append(f"{row['url']}: no og:description")
            elif row["is_home"] and (not t["og:url"] or not t["og:image"]):
                problems.append(f"{row['url']}: home page missing og:url or og:image")
            elif not row["is_home"] and not t["og:image"]:
                problems.append(f"{row['url']}: no og:image")
        if problems:
            return result(self, "warn",
                          f"Open Graph incomplete on {len(problems)} point(s).",
                          fix="og:title and og:description everywhere; og:url and og:image on "
                              "the home page.",
                          evidence={**evidence, "problems": problems[:20]})
        return result(self, "pass", "Open Graph basics are complete.", evidence=evidence)


SD001 = SD001JsonLd()
SD002 = SD002EntityTypes()
SD003 = SD003OpenGraph()

__all__ = ["SD001", "SD002", "SD003"]