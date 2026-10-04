"""Optional Playwright render (FR-6, ADR-006).

Rendering is an extra, not a dependency: `geoctl` must stay `uvx`-installable
and light. Every entry point degrades to None when Playwright or its browser is
absent, so `--render` on a plain install reports low confidence rather than
crashing.
"""

# The two Playwright imports below are the only unresolvable names in this
# project: Playwright is an optional extra (ADR-006) and is deliberately absent
# from the dev and CI environments. Both are guarded by `try/except ImportError`.
# The suppression is per-file so a missing import anywhere else is still an error.
# pyright: reportMissingImports=false

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RenderResult:
    url: str
    html: bytes | None
    status: int | None
    error: str | None = None


def is_available() -> bool:
    try:
        import playwright  # noqa: F401
    except ImportError:
        return False
    return True


def render_urls(urls: list[str], timeout_ms: int = 20_000) -> list[RenderResult]:
    """Fetch each URL with a real browser. Returns one result per URL, in order."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return [
            RenderResult(url=u, html=None, status=None, error="playwright not installed")
            for u in urls
        ]

    out: list[RenderResult] = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(args=["--no-sandbox"])
            try:
                # Same non-fingerprinted UA as the browser baseline, so a
                # no-JS-versus-rendered comparison is not skewed by one side
                # being refused for its user-agent alone (issue #40).
                from .bots import BROWSER_UA

                context = browser.new_context(user_agent=BROWSER_UA)
                for url in urls:
                    page = context.new_page()
                    try:
                        response = page.goto(url, timeout=timeout_ms, wait_until="networkidle")
                        html = page.content().encode("utf-8", "replace")
                        out.append(
                            RenderResult(
                                url=url, html=html, status=response.status if response else None
                            )
                        )
                    except Exception as exc:
                        out.append(
                            RenderResult(
                                url=url,
                                html=None,
                                status=None,
                                error=f"{type(exc).__name__}: {exc}",
                            )
                        )
                    finally:
                        page.close()
            finally:
                browser.close()
    except Exception as exc:
        for url in urls:
            out.append(
                RenderResult(url=url, html=None, status=None, error=f"render unavailable: {exc}")
            )
    return out
