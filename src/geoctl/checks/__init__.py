"""The check catalog: an explicit registration list (ARCHITECTURE §5.3).

Registration is a list rather than import magic so the catalog is auditable in
one place and testable — a test asserts the catalog matches the IDs and weights
documented in docs/CHECKS.md.
"""

from __future__ import annotations

from collections.abc import Iterable

from ..models import CheckResult
from .access import ACC001, ACC002, ACC003
from .base import AuditContext, Check
from .discovery import DIS001, DIS002, DIS003
from .render import REN001, REN002
from .schema import SD001, SD002, SD003
from .site import SITE001
from .structure import STR001, STR002, STR003, STR004, STR005, STR006
from .trust import TRU001, TRU002

# Catalog order: scored checks first, heaviest weight first, so the report and
# the docs read in the same order.
CATALOG: tuple[Check, ...] = (
    ACC002,
    ACC001,
    ACC003,
    REN001,
    REN002,
    DIS001,
    STR001,
    STR002,
    STR003,
    STR004,
    STR005,
    STR006,
    SD001,
    SD002,
    SD003,
    DIS002,
    DIS003,
    TRU001,
    TRU002,
    SITE001,
)

SCORED = tuple(c for c in CATALOG if c.tier == "scored")
INFORMATIONAL = tuple(c for c in CATALOG if c.tier == "informational")

TOTAL_WEIGHT = sum(c.weight for c in SCORED)


class UnknownCheck(ValueError):
    """Usage error: exit code 2."""


def by_id(check_id: str) -> Check:
    needle = check_id.strip().upper()
    for check in CATALOG:
        if check.id == needle:
            return check
    raise UnknownCheck(f"Unknown check id {check_id!r}")


def _matches(token: str, check: Check) -> bool:
    needle = token.strip().lower()
    return needle in (check.id.lower(), check.category.lower())


def select(only: Iterable[str] | None = None,
           skip: Iterable[str] | None = None) -> list[Check]:
    """Apply --only / --skip, which accept check IDs and category names."""
    only_list = [t for t in (only or []) if t.strip()]
    skip_list = [t for t in (skip or []) if t.strip()]

    chosen = list(CATALOG)
    if only_list:
        chosen = [c for c in chosen if any(_matches(t, c) for t in only_list)]
        if not chosen:
            raise UnknownCheck(
                f"--only {only_list} matched no check. Known ids: "
                f"{', '.join(c.id for c in CATALOG)}"
            )
    if skip_list:
        chosen = [c for c in chosen if not any(_matches(t, c) for t in skip_list)]
    return chosen


def run_all(ctx: AuditContext,
            only: Iterable[str] | None = None,
            skip: Iterable[str] | None = None) -> list[CheckResult]:
    """Run the selected checks. One check failing never aborts the run."""
    results: list[CheckResult] = []
    for check in select(only, skip):
        try:
            results.append(check.run(ctx))
        except Exception as exc:
            results.append(
                CheckResult(
                    id=check.id,
                    category=check.category,
                    title=check.title,
                    status="error",
                    weight=0 if check.tier == "informational" else check.weight,
                    points=0.0,
                    message=f"Check raised {type(exc).__name__}: {exc}",
                    evidence={"exception": type(exc).__name__},
                )
            )
    return results


__all__ = [
    "ACC001",
    "ACC002",
    "ACC003",
    "CATALOG",
    "DIS001",
    "DIS002",
    "DIS003",
    "INFORMATIONAL",
    "REN001",
    "REN002",
    "SCORED",
    "SD001",
    "SD002",
    "SD003",
    "SITE001",
    "STR001",
    "STR002",
    "STR003",
    "STR004",
    "STR005",
    "STR006",
    "TOTAL_WEIGHT",
    "TRU001",
    "TRU002",
    "UnknownCheck",
    "by_id",
    "run_all",
    "select",
]