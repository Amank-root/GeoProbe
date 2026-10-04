"""JSON-LD extraction and lenient validation.

Parsing is deliberately lenient: duplicate keys are tolerated, because real
pages ship them and a strict parser would report a healthy page as having no
structured data. Strict schema validation is out of scope for v0.1 (CHECKS SD-001).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

# Types that mean "the page described itself with structured data" but are not
# an entity a reader would cite.
_CONTAINER_TYPES = {"BreadcrumbList", "WebPage", "ItemList", "CollectionPage"}

# Expected JSON-LD types per inferred page role (CHECKS SD-002).
ROLE_EXPECTATIONS: dict[str, set[str]] = {
    "home": {"Organization", "WebSite", "Corporation", "LocalBusiness", "Person"},
    "article": {"Article", "NewsArticle", "BlogPosting", "TechArticle"},
    "product": {"Product", "Offer", "ProductGroup"},
    "faq": {"FAQPage", "QAPage"},
    "docs": {"TechArticle", "Article", "WebPage", "SoftwareApplication", "APIReference"},
    "about": {"Organization", "AboutPage", "Corporation", "Person"},
}


@dataclass
class StructuredData:
    items: list[dict[str, Any]] = field(default_factory=list)
    block_count: int = 0
    parse_errors: list[str] = field(default_factory=list)
    types: list[str] = field(default_factory=list)

    @property
    def parsed_count(self) -> int:
        return len(self.items)


def _pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Last duplicate key wins, as most lenient JSON parsers behave."""
    out: dict[str, Any] = {}
    for key, value in pairs:
        out[key] = value
    return out


def extract_json_ld(html: str | None) -> StructuredData:
    out = StructuredData()
    if not html:
        return out
    from selectolax.lexbor import LexborHTMLParser as HTMLParser

    tree = HTMLParser(html)
    scripts = tree.css('script[type="application/ld+json"]')
    out.block_count = len(scripts)

    for index, node in enumerate(scripts):
        raw = node.text() or ""
        if not raw.strip():
            out.parse_errors.append(f"block {index}: empty")
            continue
        try:
            data = json.loads(raw, object_pairs_hook=_pairs_hook)
        except (json.JSONDecodeError, ValueError) as exc:
            out.parse_errors.append(f"block {index}: {exc}")
            continue
        for item in _flatten(data):
            if isinstance(item, dict):
                out.items.append(item)
                t = item.get("@type")
                if isinstance(t, str):
                    out.types.append(t)
                elif isinstance(t, list):
                    out.types.extend(x for x in t if isinstance(x, str))
    return out


def _flatten(data: Any) -> list[Any]:
    """Unwrap @graph and lists, which is where most real JSON-LD hides its types."""
    out: list[Any] = []
    if isinstance(data, list):
        for entry in data:
            out.extend(_flatten(entry))
    elif isinstance(data, dict):
        if "@graph" in data and isinstance(data["@graph"], list):
            out.extend(_flatten(data["@graph"]))
        else:
            out.append(data)
    return out


def entity_types(sd: StructuredData) -> set[str]:
    """Types excluding pure containers, for the SD-002 role comparison."""
    return {t for t in sd.types if t not in _CONTAINER_TYPES}


def infer_role(path: str, title: str | None = None, types: set[str] | None = None) -> str:
    """Infer the page's role from its path, then from types already present."""
    lowered = (path or "/").lower()
    if any(k in lowered for k in ("/docs", "/doc", "/guide", "/reference", "/api")):
        return "docs"
    if any(k in lowered for k in ("/faq", "/support", "/help")):
        return "faq"
    if any(k in lowered for k in ("/product", "/products/", "/shop", "/pricing", "/item")):
        return "product"
    if any(k in lowered for k in ("/blog", "/news", "/post", "/article", "/posts/")):
        return "article"
    if any(k in lowered for k in ("/about", "/team", "/company")):
        return "about"
    if lowered in ("/", "", "/index.html"):
        return "home"
    if types:
        if types & {"FAQPage", "QAPage"}:
            return "faq"
        if types & {"Product", "Offer"}:
            return "product"
        if types & {"Article", "NewsArticle", "BlogPosting"}:
            return "article"
    if title:
        lowered_title = title.lower()
        if any(k in lowered_title for k in ("pricing", "plans", "buy")):
            return "product"
        if any(k in lowered_title for k in ("faq", "questions")):
            return "faq"
    return "article"


def expected_types(role: str) -> set[str]:
    return ROLE_EXPECTATIONS.get(role, set())


def first_value(item: dict[str, Any], key: str) -> Any:
    value = item.get(key)
    if isinstance(value, list):
        return value[0] if value else None
    return value


def find_items_with(sd: StructuredData, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    return [item for item in sd.items if any(k in item for k in keys)]


def names(sd: StructuredData) -> list[str]:
    """Human-readable entity names, used by TRU-002 evidence."""
    out: list[str] = []
    for item in sd.items:
        for key in ("name", "legalName"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                out.append(value.strip())
    return out