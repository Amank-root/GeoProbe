"""Scoring: weights to category and overall scores (ARCHITECTURE §9).

Rules, all of which the output schema depends on:

- A check's `points` is a fraction of its `weight`.
- Skips are excluded from the denominator, so an inapplicable check does not
  silently lower the score.
- Informational checks have weight 0 and contribute nothing.
- The eval score is never blended into the deterministic score; they are
  reported side by side so the user can see which signal moved.
"""

from __future__ import annotations

from .models import CheckResult, ScoreCategory, ScoreReport

# Scored categories only. Informational categories never appear here: giving
# them a nonzero max would imply they affect the score (OUTPUT_SCHEMA §4.3).
SCORED_CATEGORIES = ("access", "rendering", "discovery")

# Denominator when a category's checks are all skipped.
_EMPTY_CATEGORY_MAX = 0.0

COUNTED = ("pass", "warn", "fail", "error")


def score_checks(checks: list[CheckResult]) -> ScoreReport:
    report = ScoreReport()
    per_category: dict[str, list[CheckResult]] = {}
    for check in checks:
        per_category.setdefault(check.category, []).append(check)

    totals: list[tuple[float, float]] = []
    for category, items in sorted(per_category.items()):
        counted = [c for c in items if c.status in COUNTED]
        # Skips are excluded from the denominator, so an inapplicable check does
        # not silently lower the score.
        max_points = float(sum(c.weight for c in counted))
        points = float(sum(c.points for c in counted))
        if category in SCORED_CATEGORIES:
            report.categories[category] = ScoreCategory(
                points=round(points, 2), max=round(max_points, 2)
            )
            totals.append((points, max_points))

    earned = sum(p for p, _ in totals)
    possible = sum(m for _, m in totals)
    if possible > 0:
        report.overall = round(100.0 * earned / possible, 1)
    report.max = 100.0
    return report


def score_for(checks: list[CheckResult], check_id: str) -> float | None:
    for check in checks:
        if check.id == check_id:
            return check.points
    return None


def status_counts(checks: list[CheckResult]) -> dict[str, dict[str, int]]:
    """pass/warn/fail counts by category, for the terminal hygiene summary."""
    out: dict[str, dict[str, int]] = {}
    for check in checks:
        if check.weight > 0:
            continue
        bucket = out.setdefault(check.category, {"pass": 0, "warn": 0, "fail": 0,
                                                "skip": 0, "error": 0})
        bucket[check.status] = bucket.get(check.status, 0) + 1
    return out


def top_findings(checks: list[CheckResult], limit: int = 10) -> list[CheckResult]:
    """Failures before warnings, heaviest weight first, so the report leads with
    what is most worth fixing."""
    priority = {"fail": 0, "error": 1, "warn": 2}
    relevant = [c for c in checks if c.status in priority]
    return sorted(relevant, key=lambda c: (priority[c.status], -c.weight))[:limit]