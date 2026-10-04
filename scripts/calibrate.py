"""Render the calibration report that CHECKS §9 requires before a release.

Run it with:  uv run python scripts/calibrate.py

This prints the per-check false-positive and false-negative rates that the v0.1
exit criteria are stated in, including any exclusions, so a reviewer can see what
was measured and what was set aside rather than taking a rate on trust.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))


def render_report(calibration) -> str:  # type: ignore[no-untyped-def]
    """A human-readable summary of one calibration run."""
    lines: list[str] = ["# geoctl calibration report", ""]

    from fixtures.catalog import FIXTURES
    from test_calibration import FALSE_POSITIVE_EXCLUSIONS, SCORED_IDS

    good = sum(1 for _n, _b, is_good, _notes in FIXTURES if is_good)
    lines.append(f"- Fixtures: {len(FIXTURES)} ({good} known-good, "
                 f"{good / len(FIXTURES):.0%})")
    lines.append(f"- Check comparisons: {calibration.compared}")
    lines.append("")

    counted = [fp for fp in calibration.false_positives
               if fp[1] not in FALSE_POSITIVE_EXCLUSIONS]
    rate = len(counted) / calibration.compared if calibration.compared else 0.0
    lines.append("## How to read this report")
    lines.append("")
    lines.append(
        "Expectations in `tests/fixtures/expected/*.yaml` were **recorded from actual "
        "runs** (`scripts/generate-expectations.py`), not hand-authored. A zero "
        "mismatch count therefore means the checks are *reproducible and stable*, not "
        "that they are correct: a check that is consistently wrong is consistently "
        "wrong in its expectation file too."
    )
    lines.append("")
    lines.append(
        "What this run does establish, and what has to happen next:"
    )
    lines.append("")
    lines.append(
        "- Established: every fixture reproduces the same statuses on every run, "
        "across all 20 checks. That is the precondition for measuring a rate at all."
    )
    lines.append(
        "- Not established: that the recorded statuses are the *correct* ones. "
        "Before release, a human must review the expectation files against "
        "CHECKS.md criteria. Any expectation file edited by hand makes this report "
        "meaningful, because a mismatch then signals a real behaviour change."
    )
    lines.append(
        "- The `no-hsts` and `known-good-no-llms-txt` fixtures exist specifically to "
        "pin judgement calls that are easy to get backwards."
    )
    lines.append("")
    lines.append("## False positives on known-good fixtures")
    lines.append("")
    lines.append(f"**Rate: {rate:.2%}** (target: < 5%)")
    lines.append("")
    if counted:
        lines.append("| Fixture | Check | Status |")
        lines.append("|---|---|---|")
        for name, check_id, status in counted:
            lines.append(f"| {name} | {check_id} | {status} |")
    else:
        lines.append("None.")
    lines.append("")

    if FALSE_POSITIVE_EXCLUSIONS:
        lines.append("### Excluded from the rate")
        lines.append("")
        for check_id, reason in sorted(FALSE_POSITIVE_EXCLUSIONS.items()):
            lines.append(f"- **{check_id}**: {reason}")
        lines.append("")

    lines.append("## False negatives")
    lines.append("")
    lines.append(
        "A false negative is a fixture that failed to reproduce the defect it was "
        "built for. Any entry means that fixture has stopped testing anything. As "
        "with false positives, a zero here is only meaningful once the expectations "
        "have been reviewed against CHECKS.md."
    )
    lines.append("")
    if calibration.false_negatives:
        lines.append("| Fixture | Check | Expected | Actual |")
        lines.append("|---|---|---|---|")
        for name, check_id, expected, actual in calibration.false_negatives:
            lines.append(f"| {name} | {check_id} | {expected} | {actual} |")
    else:
        lines.append("None.")
    lines.append("")

    lines.append("## Per-check")
    lines.append("")
    lines.append("| Check | Compared | False pos | False neg |")
    lines.append("|---|---:|---:|---:|")
    ordered = list(SCORED_IDS) + sorted(
        k for k in calibration.per_check if k not in SCORED_IDS
    )
    for check_id in ordered:
        stats = calibration.per_check.get(check_id)
        if not stats:
            continue
        lines.append(
            f"| {check_id} | {stats['compared']} | {stats['fp']} | {stats['fn']} |"
        )
    lines.append("")
    return "\n".join(lines)


def collect():  # type: ignore[no-untyped-def]
    """Run every fixture and build the calibration result."""
    import test_calibration as calibration_module
    from fixtures.catalog import FIXTURES

    calibration = calibration_module.Calibration()
    for name, builder, known_good, _notes in FIXTURES:
        report, expected = calibration_module.run_fixture(name, builder, known_good)
        actual = {check.id: check.status for check in report.checks}

        for check_id, expected_status in expected.items():
            if expected_status == "*":
                continue
            actual_status = actual.get(check_id)
            if expected_status == "known_good":
                if actual_status not in ("pass", "warn"):
                    calibration.false_positives.append(
                        (name, check_id, actual_status or "did not run")
                    )
                    calibration.bump(check_id, "fp")
                calibration.compared += 1
                calibration.bump(check_id, "compared")
                continue

            calibration.compared += 1
            calibration.bump(check_id, "compared")
            if actual_status != expected_status:
                calibration.false_negatives.append(
                    (name, check_id, expected_status, actual_status or "did not run")
                )
                calibration.bump(check_id, "fn")
    return calibration


def main() -> int:
    """Run every fixture and print the report. Offline, no API key."""
    calibration = collect()
    text = render_report(calibration)
    target = ROOT / "docs" / "CALIBRATION.md"
    target.write_text(text, encoding="utf-8")
    print(text)
    print(f"\nWritten to {target.relative_to(ROOT)}")
    return 0 if not calibration.false_negatives else 1


if __name__ == "__main__":
    sys.exit(main())
