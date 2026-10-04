"""Calibration: per-check false-positive and false-negative rates (CHECKS §9).

Two release targets are measured here, and both are per-check rather than
aggregate, because a weight-1 check that is always wrong is still noise in the
report:

- **False positives** on known-good fixtures must stay below 5%.
- **False negatives** on the defect each fixture was built to reproduce.

One check is deliberately excluded from the false-positive count:
``SITE-001``. The fixture server is plain HTTP by necessity (it must bind an
ephemeral localhost port), so every fixture reports "not served over HTTPS".
Counting that would measure the harness, not the check. SITE-001 is instead
verified by unit tests in `test_infrastructure.py` and by the `no-hsts` fixture's
recorded expectation, and the gap is recorded in CALIBRATION.md rather than
hidden.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from http.server import ThreadingHTTPServer

import pytest

from conftest import _Handler
from fixtures.catalog import FIXTURES
from fixtures.expectations import EXPECTED_DIR, load_expectations

# The deterministic checks whose thresholds the release target is about.
SCORED_IDS = ("ACC-001", "ACC-002", "ACC-003", "REN-001", "REN-002", "DIS-001")

# Excluded from the false-positive count, with the reason recorded in the report.
FALSE_POSITIVE_EXCLUSIONS = {
    "SITE-001": "the fixture server is plain HTTP, so this measures the harness",
}


@dataclass
class Calibration:
    false_positives: list[tuple[str, str, str]] = field(default_factory=list)
    false_negatives: list[tuple[str, str, str, str]] = field(default_factory=list)
    compared: int = 0
    per_check: dict[str, dict[str, int]] = field(default_factory=dict)

    @property
    def false_positive_rate(self) -> float:
        return len(self.false_positives) / self.compared if self.compared else 0.0

    def bump(self, check_id: str, field_name: str) -> None:
        self.per_check.setdefault(check_id, {"fp": 0, "fn": 0, "compared": 0})
        self.per_check[check_id][field_name] += 1


def _serve(builder) -> tuple[ThreadingHTTPServer, str]:  # type: ignore[no-untyped-def]
    handler = type("H", (_Handler,), {"site": builder()})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/"


def run_fixture(name: str, builder, known_good: bool, max_pages: int = 1):  # type: ignore[no-untyped-def]
    """Run one fixture end to end and return (report, expectations)."""
    import asyncio

    from geoctl.audit import audit, build_report
    from geoctl.config import Config

    config = Config()
    config.fetch.allow_private = True
    config.fetch.timeout = 5.0
    config.audit.max_pages = max_pages
    config.eval.enabled = "false"

    server, url = _serve(builder)
    try:
        state = asyncio.run(audit(config, url, cache=None, use_cache=False))
        return build_report(state, config), load_expectations(name)
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture(scope="module")
def calibration() -> Calibration:
    """Run every fixture once and compare against its recorded expectations."""
    result = Calibration()
    for name, builder, known_good, _notes in FIXTURES:
        report, expected = run_fixture(name, builder, known_good)
        actual = {check.id: check.status for check in report.checks}

        for check_id, expected_status in expected.items():
            if expected_status == "*":
                continue
            actual_status = actual.get(check_id)
            assert actual_status is not None, f"{name}: {check_id} did not run"

            if expected_status == "known_good":
                # A known-good fixture expects pass or warn for this check.
                if actual_status not in ("pass", "warn"):
                    result.false_positives.append((name, check_id, actual_status))
                    result.bump(check_id, "fp")
                result.compared += 1
                result.bump(check_id, "compared")
                continue

            result.compared += 1
            result.bump(check_id, "compared")
            if actual_status != expected_status:
                result.false_negatives.append(
                    (name, check_id, expected_status, actual_status or "did not run")
                )
                result.bump(check_id, "fn")
    return result


def test_every_fixture_has_an_expectation_file():
    assert EXPECTED_DIR.exists(), "run scripts/generate-expectations.py"
    for name, _builder, _good, _notes in FIXTURES:
        assert (EXPECTED_DIR / f"{name}.yaml").exists(), f"{name} has no expectation file"


def test_the_known_good_set_is_at_least_forty_percent(calibration: Calibration):
    """A set of mostly-broken sites cannot measure a false-positive rate."""
    total = len(FIXTURES)
    good = sum(1 for _n, _b, is_good, _notes in FIXTURES if is_good)
    assert good / total >= 0.40, (
        f"only {good}/{total} fixtures are known-good; FIXTURES.md requires at least 40%"
    )


def test_false_positive_rate_is_under_five_percent(calibration: Calibration):
    """The v0.1 release gate (ROADMAP M1, CHECKS §9)."""
    counted = [fp for fp in calibration.false_positives
               if fp[1] not in FALSE_POSITIVE_EXCLUSIONS]
    rate = len(counted) / calibration.compared if calibration.compared else 0.0
    assert rate < 0.05, (
        f"false-positive rate {rate:.1%} exceeds the 5% target. "
        f"Offenders: {counted}"
    )


def test_no_false_negatives_on_the_defects_under_test(calibration: Calibration):
    """Every fixture built to reproduce a defect must actually show it.

    This is the other half of calibration: a check that never fires is as broken
    as one that always fires, and a defect fixture that passes is a fixture that
    stopped testing anything.
    """
    assert not calibration.false_negatives, (
        "fixtures did not reproduce the defects they were built for: "
        f"{calibration.false_negatives}"
    )


def test_low_weight_checks_are_not_silently_wrong(calibration: Calibration):
    """CHECKS §9: attention to the low-weight checks specifically.

    DIS-001 carries 1 point. It barely moves the score, so a false positive there
    would be easy to miss and expensive in trust.
    """
    dis = calibration.per_check.get("DIS-001", {})
    assert dis.get("fp", 0) == 0, (
        f"DIS-001 produced {dis['fp']} false positive(s) on known-good fixtures"
    )


def test_the_calibration_report_is_renderable(calibration: Calibration):
    """A measurement nobody can read is not a result. See scripts/calibrate.py."""
    from scripts.calibrate import render_report

    text = render_report(calibration)
    assert "false positives" in text.lower()
    assert "SITE-001" in text, "exclusions must be visible, not silent"
    assert "target: < 5%" in text, "the release target must be stated in the report"
    for check_id in SCORED_IDS:
        assert check_id in text