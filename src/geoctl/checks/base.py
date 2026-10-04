"""Check protocol, AuditContext, and the registry.

A check is a pure function of an AuditContext: it reads data the context already
holds and never performs its own network requests. That is what makes the whole
catalog testable against fixtures and runnable in CI with no network
(ARCHITECTURE §5.4, CONTRIBUTING).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from ..extract.view import PageBundle
from ..models import (
    CheckResult,
    FetchResult,
    FixHint,
    RobotsReport,
    SitemapReport,
)
from ..util import similarity

DOCS_BASE = "https://github.com/Amank-root/GeoProbe/blob/main/docs/CHECKS.md"


@dataclass
class AuditContext:
    """Everything the checks may read. Nothing they may fetch."""

    start_url: str
    final_url: str = ""
    policy: str = "report"
    # Empty means "use the built-in registry default", resolved by the runner so
    # that every check sees the same list.
    bot_names: list[str] = field(default_factory=list)
    pages: list[PageBundle] = field(default_factory=list)
    robots: RobotsReport | None = None
    sitemap: SitemapReport | None = None
    llms_txt: FetchResult | None = None
    rendered: dict[str, FetchResult] = field(default_factory=dict)
    render_available: bool = False
    errors: list[dict[str, Any]] = field(default_factory=list)

    @property
    def start_bundle(self) -> PageBundle | None:
        return self.pages[0] if self.pages else None

    def browser_pages(self) -> list[PageBundle]:
        return [p for p in self.pages if "browser-nojs" in p.views]

    def statuses_by_bot(self) -> dict[str, int | None]:
        out: dict[str, int | None] = {}
        for bundle in self.pages:
            for name, fetch in bundle.fetches.items():
                out.setdefault(name, fetch.status)
        return out


@runtime_checkable
class Check(Protocol):
    id: str
    category: str
    title: str
    weight: int
    tier: str  # "scored" | "informational"

    def run(self, ctx: AuditContext) -> CheckResult: ...


def result(
    check: Check,
    status: str,
    message: str,
    *,
    evidence: dict[str, Any] | None = None,
    fix: str | None = None,
    confidence: str = "high",
    points: float | None = None,
) -> CheckResult:
    """Build a CheckResult, applying the weight rules of CHECKS §1.

    Informational checks are hard-locked to 0 points and weight 0, so a bug in a
    single check implementation can never move the score.
    """
    weight = 0 if check.tier == "informational" else check.weight
    if check.tier == "informational":
        awarded = 0.0
    elif points is not None:
        awarded = float(points)
    elif status == "pass":
        awarded = float(weight)
    elif status == "warn":
        awarded = weight * 0.5
    elif status in ("fail", "error"):
        awarded = 0.0
    else:
        awarded = 0.0

    return CheckResult(
        id=check.id,
        category=check.category,
        title=check.title,
        status=status,  # type: ignore[arg-type]
        weight=weight,
        points=awarded,
        confidence=confidence,  # type: ignore[arg-type]
        message=message,
        evidence=evidence or {},
        fix=FixHint(summary=fix, docs_url=f"{DOCS_BASE}#{check.id.lower()}") if fix else None,
    )


def skip(check: Check, message: str, evidence: dict[str, Any] | None = None) -> CheckResult:
    return result(check, "skip", message, evidence=evidence)


def err(check: Check, message: str, evidence: dict[str, Any] | None = None) -> CheckResult:
    return result(check, "error", message, evidence=evidence)


def docs_url(check: Check) -> str:
    return f"{DOCS_BASE}#{check.id.lower()}"


def text_similarity(a: str, b: str) -> float:
    return similarity(a, b)
