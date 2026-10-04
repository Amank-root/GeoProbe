"""Main-content extraction: adaptive trafilatura (ADR-016).

The Milestone 0 spike measured a 33x difference between `favor_precision` and
`favor_recall` on the same client-rendered HTML, so a fixed setting is wrong:
precision alone reported an empty crawler view for pages that did contain
readable text. We run recall first, fall back to precision, and keep whichever
extracts more — and we record which setting won, because a recall-built crawler
view is a looser approximation of what a real crawler would treat as content.
"""

from __future__ import annotations

from dataclasses import dataclass

# Below this, we treat an extraction as failed and retry with the other setting.
RECALL_CHAR_FLOOR = 200

# Framework markers that suggest a client-rendered app shell.
FRAMEWORK_MARKERS: dict[str, tuple[str, ...]] = {
    "next": ("__NEXT_DATA__", "/_next/static/", "self.__next_f"),
    "nuxt": ("__NUXT__", "/_nuxt/", "__nuxt"),
    "react_root": ('<div id="root"', "<div id='root'", "data-reactroot"),
    "vue_app": ("data-v-app", 'id="app"', "__VUE__"),
    "angular": ("ng-version", "<app-root", "ng-app"),
    "svelte": ("__sveltekit", "data-svelte", "svelte-"),
    "sveltekit": ("__sveltekit",),
    "astro": ("astro-island", "astro-"),
}

# Markers of an empty shell that JS is expected to fill.
SHELL_MARKERS: dict[str, tuple[str, ...]] = {
    "noscript_warning": ("<noscript>", "enable javascript", "turn on javascript"),
    "root_div_only": ('<div id="root"></div>', '<div id="app"></div>'),
    "empty_body_class": ('class="loading"', 'data-loading="true"'),
}


@dataclass
class Extraction:
    text: str
    mode: str  # "recall" | "precision" | "none"
    html_chars: int
    ratio: float
    framework_markers: list[str]
    shell_markers: list[str]

    @property
    def chars(self) -> int:
        return len(self.text)


def _run(html: str, **kwargs: object) -> str:
    try:
        import trafilatura
    except ImportError:  # pragma: no cover - trafilatura is a hard dependency
        return ""
    try:
        out = trafilatura.extract(html, output_format="markdown", **kwargs)  # type: ignore[arg-type]
    except Exception:
        return ""
    return out or ""


def extract_main(html: str | None) -> Extraction:
    """Adaptive main-content extraction with markers reported as evidence."""
    html = html or ""
    html_chars = len(html)

    recall = _run(html, favor_recall=True)
    mode = "recall"
    text = recall

    if len(recall) < RECALL_CHAR_FLOOR:
        precision = _run(html, favor_precision=True)
        # Keep whichever extracted more. Never report an empty view while either
        # setting yields text: a missing span is indistinguishable from a bad score.
        if len(precision) > len(recall):
            text, mode = precision, "precision"
        elif not recall and not precision:
            mode = "none"

    lowered = html.lower()
    framework = [
        name
        for name, needles in FRAMEWORK_MARKERS.items()
        if any(n.lower() in lowered for n in needles)
    ]
    shell = [
        name
        for name, needles in SHELL_MARKERS.items()
        if any(n.lower() in lowered for n in needles)
    ]

    return Extraction(
        text=text,
        mode=mode,
        html_chars=html_chars,
        ratio=round(len(text) / html_chars, 5) if html_chars else 0.0,
        framework_markers=framework,
        shell_markers=shell,
    )


def extract_text(html: str | None) -> str:
    return extract_main(html).text


def looks_like_shell(html: str | None) -> bool:
    """True when the HTML looks like an app shell rather than content."""
    ext = extract_main(html)
    if ext.shell_markers:
        return True
    return bool(ext.framework_markers) and ext.chars < RECALL_CHAR_FLOOR
