"""Build PageView objects: one page, one lens (ARCHITECTURE §5.2)."""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlparse

from ..cache import NS_EXTRACT, Cache
from ..models import FetchResult, PageView
from . import content as content_mod
from . import structure as structure_mod
from . import structured_data as sd_mod


@dataclass
class PageBundle:
    """A page seen through every lens that was fetched, plus derived structure.

    Checks read from this; they never fetch (ARCHITECTURE §5.4).
    """

    url: str
    final_url: str
    fetches: dict[str, FetchResult] = field(default_factory=dict)
    views: dict[str, PageView] = field(default_factory=dict)
    structure: structure_mod.DocumentStructure | None = None
    structured_data: sd_mod.StructuredData | None = None
    status: int | None = None

    @property
    def path(self) -> str:
        return urlparse(self.final_url or self.url).path or "/"

    def view(self, lens: str = "browser-nojs") -> PageView | None:
        return self.views.get(lens)

    @property
    def browser_text(self) -> str:
        view = self.views.get("browser-nojs")
        return view.text if view else ""

    @property
    def title(self) -> str | None:
        return self.structure.meta.title if self.structure else None


def build_view(
    fetch: FetchResult,
    lens: str,
    *,
    cache: Cache | None = None,
    use_cache: bool = True,
) -> PageView:
    """Extract one PageView from one FetchResult.

    Extraction is cached by (url, lens, content hash) so repeated lenses over
    identical bytes cost one extraction.
    """
    html = fetch.body.decode("utf-8", "replace") if fetch.body else ""
    key = (fetch.final_url, lens, len(html), hash(html))

    if use_cache and cache:
        cached = cache.get(NS_EXTRACT, *key)
        if isinstance(cached, PageView):
            return cached

    extraction = content_mod.extract_main(html)
    structure = structure_mod.parse(html)
    structured = sd_mod.extract_json_ld(html)

    view = PageView(
        url=fetch.final_url,
        lens=lens,
        text=extraction.text,
        text_chars=extraction.chars,
        headings=structure.headings,
        meta=structure.meta,
        structured_data=structured.items,
        html_chars=extraction.html_chars,
        extraction_ratio=extraction.ratio,
        extraction_mode=extraction.mode,
        framework_markers=extraction.framework_markers,
        shell_markers=extraction.shell_markers,
    )
    if use_cache and cache:
        cache.set(NS_EXTRACT, view, *key)
    return view


def build_bundle(
    url: str,
    fetches: dict[str, FetchResult],
    *,
    cache: Cache | None = None,
    use_cache: bool = True,
) -> PageBundle:
    """Assemble the per-page bundle from every lens fetched for it."""
    bundle = PageBundle(url=url, final_url=url, fetches=fetches)
    browser = fetches.get("browser")
    if browser:
        bundle.status = browser.status
        bundle.final_url = browser.final_url
        bundle.views["browser-nojs"] = build_view(
            browser, "browser-nojs", cache=cache, use_cache=use_cache
        )
        bundle.structure = structure_mod.parse(
            browser.body.decode("utf-8", "replace") if browser.body else ""
        )
        bundle.structured_data = sd_mod.extract_json_ld(
            browser.body.decode("utf-8", "replace") if browser.body else ""
        )

    for name, fetch in fetches.items():
        if name == "browser":
            continue
        lens = "rendered" if name == "__rendered__" else name
        bundle.views[lens] = build_view(fetch, lens, cache=cache, use_cache=use_cache)

    if browser and not browser.final_url:
        bundle.final_url = url
    return bundle


def add_rendered_view(bundle: PageBundle, html: bytes | None, lens: str = "rendered") -> None:
    """Attach a JS-rendered view produced outside the fetch layer."""
    if html is None:
        return
    pseudo = FetchResult(
        url=bundle.url,
        final_url=bundle.final_url,
        bot="__rendered__",
        status=200,
        body=html,
    )
    bundle.fetches[lens] = pseudo
    bundle.views[lens] = build_view(pseudo, lens)
