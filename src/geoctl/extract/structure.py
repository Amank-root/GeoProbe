"""Headings, meta tags, canonical, lang (selectolax).

Heading structure is what retrieval chunking splits on, so the outline is
reported in full rather than reduced to a boolean: a user fixing STR-005 needs
to know which transition broke.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any

from ..models import Heading, MetaInfo

_LANG_RE = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$")

# Framework/shell attributes that make a title generic rather than specific.
_PLACEHOLDER_TITLES = {"home", "index", "untitled", "page"}


@dataclass
class DocumentStructure:
    headings: list[Heading] = field(default_factory=list)
    meta: MetaInfo = field(default_factory=MetaInfo)
    h1_texts: list[str] = field(default_factory=list)
    empty_headings: list[int] = field(default_factory=list)
    skipped_levels: list[dict[str, Any]] = field(default_factory=list)
    canonical_count: int = 0
    has_main_landmark: bool = False
    # Every <meta name=...> and <meta property=...> value, so checks can read
    # arbitrary tags without re-parsing the document.
    meta_tags: dict[str, str] = field(default_factory=dict)
    # Visible <time datetime="..."> values, the machine-readable date form.
    time_datetimes: list[str] = field(default_factory=list)
    body_text: str = ""

    @property
    def lang(self) -> str | None:
        return self.meta.lang


def parse(html: str | None) -> DocumentStructure:
    if not html:
        return DocumentStructure()
    from selectolax.lexbor import LexborHTMLParser as HTMLParser

    tree = HTMLParser(html)
    out = DocumentStructure()

    for level in range(1, 7):
        for node in tree.css(f"h{level}"):
            text = (node.text(strip=True) or "").strip()
            out.headings.append(Heading(level=level, text=text))
            if not text:
                out.empty_headings.append(level)
    out.h1_texts = [h.text for h in out.headings if h.level == 1 and h.text]

    # Outline transitions are computed over non-empty headings only; an empty
    # heading is its own finding (STR-005) and would otherwise mask the level skip.
    outline = [h.level for h in out.headings if h.text]
    for prev, current in pairwise(outline):
        if current > prev + 1:
            out.skipped_levels.append({"from": prev, "to": current})

    title_node = tree.css_first("title")
    title = title_node.text(strip=True) if title_node else None

    description = _meta_content(tree, "description")
    robots_meta = _meta_content(tree, "robots")
    lang_node = tree.css_first("html")
    lang = lang_node.attributes.get("lang") if lang_node else None

    canonicals = tree.css('link[rel="canonical"]')
    canonical = canonicals[0].attributes.get("href") if canonicals else None
    out.canonical_count = len(canonicals)

    og: dict[str, str] = {}
    meta_tags: dict[str, str] = {}
    for node in tree.css("meta"):
        key = node.attributes.get("name") or node.attributes.get("property") or ""
        content = (node.attributes.get("content") or "").strip()
        if key and content:
            meta_tags[key] = content
    og = {k: v for k, v in meta_tags.items() if k.startswith("og:")}

    time_datetimes = [
        value
        for value in ((n.attributes.get("datetime") or "").strip() for n in tree.css("time"))
        if value
    ]

    out.meta = MetaInfo(
        title=title,
        description=description,
        canonical=canonical,
        lang=lang,
        robots_meta=robots_meta,
        og=og,
        html_chars=len(html),
    )
    out.has_main_landmark = (
        tree.css_first("main") is not None or tree.css_first('div[role="main"]') is not None
    )
    out.meta_tags = meta_tags
    out.time_datetimes = time_datetimes
    body = tree.body
    out.body_text = (body.text(separator=" ", strip=True) if body else "") or ""
    return out


def _meta_content(tree: Any, name: str) -> str | None:
    node = tree.css_first(f'meta[name="{name}"]')
    if not node:
        return None
    content = node.attributes.get("content", "").strip()
    return content or None


def is_valid_lang(value: str | None) -> bool:
    """A BCP-47 tag, and specifically not `en_US` with an underscore."""
    return bool(value) and bool(_LANG_RE.match(value))


def is_generic_title(title: str | None, path: str) -> bool:
    """Bare domain, 'Home', or 'Home | Brand' on a non-home page."""
    if not title:
        return False
    stripped = title.strip().lower()
    if stripped in _PLACEHOLDER_TITLES:
        return True
    first = re.split(r"\s*[|\u2013\u2014-]\s*", stripped)[0].strip()
    return path not in ("/", "") and first in _PLACEHOLDER_TITLES


def og_tags(og: dict[str, str]) -> dict[str, str | None]:
    """The four tags SD-003 cares about, with plain names for evidence."""
    return {
        "og:title": og.get("og:title"),
        "og:description": og.get("og:description"),
        "og:url": og.get("og:url"),
        "og:image": og.get("og:image"),
    }