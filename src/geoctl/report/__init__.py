"""Reporters: terminal, JSON, Markdown. One model, many renderers."""

from __future__ import annotations

from . import json as json_report
from . import markdown as markdown_report
from . import terminal as terminal_report

FORMATS = ("terminal", "json", "markdown")

RENDERERS = {
    "terminal": terminal_report.render,
    "json": json_report.dumps,
    "markdown": markdown_report.render,
}


def render(fmt: str, report):  # type: ignore[no-untyped-def]
    if fmt not in RENDERERS:
        raise ValueError(f"Unknown format {fmt!r}; choose from {', '.join(FORMATS)}")
    return RENDERERS[fmt](report)


__all__ = ["FORMATS", "RENDERERS", "json_report", "markdown_report", "render", "terminal_report"]