"""Sitemap discovery and parsing, including sitemap indexes (FR-4).

A sitemap is worth 1 point, but it is also the cheapest way to enumerate pages
for the crawl and for the eval's sampling (FR-5), so its absence has a concrete
downstream cost rather than being cosmetic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from xml.etree import ElementTree

from ..models import SitemapReport

DEFAULT_SITEMAP_PATHS = ("/sitemap.xml", "/sitemap_index.xml", "/sitemap-index.xml")

_NS = {
    "sm": "http://www.sitemaps.org/schemas/sitemap/0.9",
    "loc": "http://www.sitemaps.org/schemas/sitemap/0.9",
}

# lastmod far in the future is a real and common defect: it tells crawlers a page
# changed when it did not (CHECKS TRU-001).
_FUTURE_TOLERANCE_DAYS = timedelta(days=2)
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


@dataclass
class SitemapEntry:
    loc: str
    lastmod: str | None = None
    is_index: bool = False


@dataclass
class ParsedSitemap:
    entries: list[SitemapEntry] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    child_sitemaps: list[str] = field(default_factory=list)


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_sitemap(xml: str | bytes) -> ParsedSitemap:
    """Parse a sitemap or sitemap index. Malformed XML yields errors, not an exception."""
    out = ParsedSitemap()
    try:
        if isinstance(xml, str):
            xml = xml.encode("utf-8", "replace")
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as exc:
        out.errors.append(f"XML parse error: {exc}")
        return out

    root_name = _localname(root.tag)
    for node in root.iter():
        name = _localname(node.tag)
        if root_name == "sitemapindex" and name == "sitemap":
            loc = _text_of(node, "loc")
            if loc:
                out.child_sitemaps.append(loc)
        elif name == "url":
            loc = _text_of(node, "loc")
            if loc:
                out.entries.append(SitemapEntry(loc=loc, lastmod=_text_of(node, "lastmod")))
    return out


def _text_of(node: ElementTree.Element, child_name: str) -> str | None:
    for child in node:
        if _localname(child.tag) == child_name and child.text:
            return child.text.strip()
    return None


def looks_like_sitemap(body: bytes | None, content_type: str | None) -> bool:
    if not body:
        return False
    head = body[:400].lstrip().lower()
    return head.startswith(b"<?xml") or b"<urlset" in head or b"<sitemapindex" in head


def same_origin(url: str, base: str) -> bool:
    a, b = urlparse(url), urlparse(base)
    return (a.scheme, a.netloc) == (b.scheme, b.netloc)


def is_stale(lastmod: str | None, now: datetime | None = None) -> bool:
    """True when a lastmod is unparseable, epoch-0, or in the future."""
    if not lastmod:
        return False
    now = now or datetime.now(timezone.utc)
    parsed = parse_date(lastmod)
    if parsed is None:
        return True
    if parsed <= _EPOCH:
        return True
    return parsed > now.replace(microsecond=0) + _FUTURE_TOLERANCE_DAYS


_DATE_PATTERNS = (
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%S.%f%z",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%d %b %Y",
    "%b %d, %Y",
    "%a, %d %b %Y %H:%M:%S %z",
)


def parse_date(value: str | None) -> datetime | None:
    """Parse the date formats sites actually emit, as UTC."""
    if not value:
        return None
    value = value.strip()
    for pattern in _DATE_PATTERNS:
        try:
            parsed = datetime.strptime(value, pattern)
        except ValueError:
            continue
        return (
            parsed.replace(tzinfo=timezone.utc)
            if parsed.tzinfo is None
            else parsed.astimezone(timezone.utc)
        )
    match = re.match(r"(\d{4})-(\d{2})-(\d{2})", value)
    if match:
        try:
            return datetime(int(match[1]), int(match[2]), int(match[3]), tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def sample_urls(
    urls: list[str], start_url: str, max_pages: int, *, path_prefix: str | None = None
) -> list[str]:
    """Pick the pages to audit: the start URL first, then a spread of the rest.

    Sampling is spread across the URL list rather than taking a prefix, because a
    prefix of a sitemap tends to be one section of the site.
    """
    seen: list[str] = []
    start_norm = start_url.rstrip("/")
    others = [
        u
        for u in urls
        if u.rstrip("/") != start_norm
        and (path_prefix is None or urlparse(u).path.startswith(path_prefix))
    ]
    remaining = max_pages - 1
    if remaining <= 0 or not others:
        return [start_url] if start_url else []
    step = max(1, len(others) // remaining)
    picked = others[::step][:remaining]
    seen = [start_url, *picked]
    return seen


def build_report(
    parsed: list[ParsedSitemap],
    found_urls: list[str],
    start_url: str,
    *,
    start_candidates: list[str] | None = None,
) -> SitemapReport:
    """Assemble the DIS-001 evidence from every sitemap that was read."""
    entries = [e for p in parsed for e in p.entries]
    errors = [err for p in parsed for err in p.errors]
    on_origin = [e.loc for e in entries if same_origin(e.loc, start_url)]
    cross = [e.loc for e in entries if not same_origin(e.loc, start_url)]
    if cross:
        errors.append(f"{len(cross)} sitemap URLs are on another origin and were ignored")
    start_norm = start_url.rstrip("/")
    includes = any(u.rstrip("/") == start_norm for u in on_origin)
    stale = [e.loc for e in entries if is_stale(e.lastmod)]
    if stale:
        errors.append(f"{len(stale)} URLs have an unparseable or future lastmod")
    return SitemapReport(
        found=bool(found_urls),
        urls=on_origin,
        sitemap_urls=found_urls,
        parse_errors=errors,
        includes_start_url=includes,
        stale_lastmod=stale,
    )


def candidate_urls(base: str, robots_sitemaps: list[str]) -> list[str]:
    """Sitemap URLs to try, robots.txt declarations first."""
    parsed = urlparse(base)
    root = f"{parsed.scheme}://{parsed.netloc}"
    out = [u for u in robots_sitemaps if same_origin(u, base)]
    out.extend(f"{root}{p}" for p in DEFAULT_SITEMAP_PATHS)
    seen: list[str] = []
    for u in out:
        if u not in seen:
            seen.append(u)
    return seen
