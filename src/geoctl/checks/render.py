"""REN-* checks: what a text-only crawler can read (CHECKS §5).

REN-001 is the check that matters most in practice. Most AI retrieval crawlers do
not execute JavaScript, so content that only exists after hydration is content
they never see, which is why it carries 20 of the 100 points.
"""

from __future__ import annotations

from typing import Any

from ..models import CheckResult
from .base import AuditContext, result, skip

PASS_RATIO = 0.8
FAIL_RATIO = 0.4
PASS_CHARS = 1200
LOW_TEXT_CHARS = 300
MIN_RENDER_CHARS = 400


class REN001NoJs:
    id = "REN-001"
    category = "rendering"
    title = "Text available without JavaScript"
    weight = 20
    tier = "scored"

    def run(self, ctx: AuditContext) -> CheckResult:
        pages: list[dict[str, Any]] = []
        for bundle in ctx.browser_pages():
            view = bundle.views["browser-nojs"]
            rendered = ctx.rendered.get(bundle.url)
            rendered_chars = 0
            if rendered is not None:
                rendered_view = bundle.views.get("rendered")
                rendered_chars = rendered_view.text_chars if rendered_view else 0
            row = {
                "url": bundle.url,
                "nojs_chars": view.text_chars,
                "rendered_chars": rendered_chars,
                "html_chars": view.html_chars,
                "extraction_ratio": view.extraction_ratio,
                "framework_markers": view.framework_markers,
                "shell_markers": view.shell_markers,
            }
            if rendered_chars:
                row["ratio"] = round(view.text_chars / rendered_chars, 4)
            pages.append(row)

        if not pages:
            return skip(self, "no pages were fetched successfully")

        has_render = any(p["rendered_chars"] for p in pages)
        markers: list[str] = sorted({m for p in pages for m in p["framework_markers"]})
        shells = sorted({m for p in pages for m in p["shell_markers"]})

        evidence = {
            "pages": pages,
            "framework_markers": markers,
            "shell_markers": shells,
            "render_compared": has_render,
            "method": "render-comparison" if has_render else "absolute-threshold+shell-heuristics",
            "thresholds": {
                "pass_ratio": PASS_RATIO,
                "fail_ratio": FAIL_RATIO,
                "pass_chars": PASS_CHARS,
                "min_render_chars": MIN_RENDER_CHARS,
            },
        }

        if has_render:
            compared = [p for p in pages if p["rendered_chars"] >= MIN_RENDER_CHARS]
            if not compared:
                return skip(self, "rendered text was too short on every page to compare",
                            evidence=evidence)
            ratios = [p["ratio"] for p in compared]
            mean_ratio = sum(ratios) / len(ratios)
            worst = min(compared, key=lambda p: p["ratio"])
            evidence["mean_ratio"] = round(mean_ratio, 4)
            evidence["worst_page"] = worst

            if mean_ratio >= PASS_RATIO:
                return result(self, "pass",
                              f"{mean_ratio:.0%} of page text is available without JavaScript.",
                              evidence=evidence)
            if mean_ratio >= FAIL_RATIO:
                return result(
                    self, "warn",
                    f"{mean_ratio:.0%} of page text is available without JavaScript.",
                    fix="Server-render or pre-render the affected content. A crawler that does "
                        "not run JavaScript sees only what is in the HTML.",
                    evidence=evidence,
                )
            return result(
                self, "fail",
                f"Only {mean_ratio:.0%} of page text is present without JavaScript "
                f"(worst: {worst['url']}, {worst['nojs_chars']} chars before JS vs "
                f"{worst['rendered_chars']} after).",
                fix="Server-render or pre-render the affected content.",
                evidence=evidence,
            )

        # No render data. Shell heuristics plus an absolute floor, and the report
        # says so rather than implying a measured ratio.
        empty_pages = [p for p in pages if p["nojs_chars"] < LOW_TEXT_CHARS]

        if empty_pages and shells:
            return result(
                self, "fail",
                f"Main content is empty without JavaScript on {len(empty_pages)} of "
                f"{len(pages)} pages, with app-shell markers present.",
                fix="Server-render or pre-render the affected content.",
                evidence=evidence,
            )
        if shells:
            return result(
                self, "warn",
                f"App-shell markers present ({', '.join(shells)}). Without --render this "
                "cannot be measured, so this is low confidence.",
                fix="Re-run with --render for a measured comparison, and server-render the "
                    "content if the shell is the only thing a crawler receives.",
                confidence="low",
                evidence=evidence,
            )
        small = [p for p in pages if p["nojs_chars"] < PASS_CHARS]
        if small:
            return result(
                self, "warn",
                f"{len(small)} of {len(pages)} pages yield under {PASS_CHARS} characters of "
                "main text before JavaScript.",
                fix="Re-run with --render to measure the ratio, and check whether the content "
                    "is client-rendered.",
                confidence="medium",
                evidence=evidence,
            )
        return result(
            self, "pass",
            f"Every sampled page yields over {PASS_CHARS} characters of main text without "
            "JavaScript (no render comparison available).",
            confidence="medium",
            evidence=evidence,
        )


class REN002Extractable:
    id = "REN-002"
    category = "rendering"
    title = "Main content extractable"
    weight = 4
    tier = "scored"

    PASS_CHARS = 300
    FAIL_CHARS = 100
    # Share of the raw text that extraction kept. A very low ratio on a large
    # page means navigation and chrome dominated (ADR-016).
    LOW_RATIO = 0.01

    def run(self, ctx: AuditContext) -> CheckResult:
        pages = []
        for bundle in ctx.browser_pages():
            view = bundle.views["browser-nojs"]
            pages.append(
                {
                    "url": bundle.url,
                    "chars": view.text_chars,
                    "html_chars": view.html_chars,
                    "extraction_ratio": view.extraction_ratio,
                    "extraction_mode": view.extraction_mode,
                }
            )
        if not pages:
            return skip(self, "no pages were fetched successfully")

        thin = [p for p in pages if p["chars"] < self.FAIL_CHARS]
        weak = [p for p in pages if self.FAIL_CHARS <= p["chars"] < self.PASS_CHARS]
        boilerplate = [
            p for p in pages
            if p["html_chars"] > 20_000 and p["extraction_ratio"] < self.LOW_RATIO
        ]
        modes = sorted({p["extraction_mode"] for p in pages if p["extraction_mode"]})
        evidence = {
            "pages": pages,
            "extraction_modes": modes,
            "thresholds": {
                "pass_chars": self.PASS_CHARS,
                "fail_chars": self.FAIL_CHARS,
                "low_ratio": self.LOW_RATIO,
            },
            "median_chars": sorted(p["chars"] for p in pages)[len(pages) // 2],
        }

        if thin:
            return result(
                self, "fail",
                f"Extraction yielded under {self.FAIL_CHARS} characters on {len(thin)} of "
                f"{len(pages)} pages.",
                fix="The page's main content may be client-rendered, or inside an "
                    "element extractors skip (an iframe, for instance). Serve the "
                    "content in the server-rendered HTML.",
                evidence=evidence,
            )
        if weak or boilerplate:
            reasons = []
            if weak:
                reasons.append(
                    f"{len(weak)} page(s) between {self.FAIL_CHARS} and "
                    f"{self.PASS_CHARS} chars"
                )
            if boilerplate:
                reasons.append(
                    f"{len(boilerplate)} page(s) where extraction kept under 1% of a "
                    "large HTML body"
                )
            return result(self, "warn", "Thin extraction: " + "; ".join(reasons) + ".",
                          fix="Check that the main content is in the server-rendered HTML and "
                              "not wrapped in navigation or a frame.",
                          evidence=evidence)
        return result(self, "pass",
                      f"Main content extracts cleanly on all {len(pages)} pages.",
                      evidence=evidence)


REN001 = REN001NoJs()
REN002 = REN002Extractable()

__all__ = ["REN001", "REN002"]