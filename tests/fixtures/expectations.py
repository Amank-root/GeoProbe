"""Per-fixture expectations, read by the calibration runner.

Every fixture declares the status each check is expected to produce. `*` accepts
any status, which keeps a fixture honest about the checks it is meant to exercise
without forcing it to predict checks it does not care about.

A check that fires on a known-good fixture is a false positive and counts
directly against the < 5% release target (CHECKS §9).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

EXPECTED_DIR = Path(__file__).parent / "expected"

# Fixtures whose every check should pass or warn: the known-good set that the
# false-positive target is measured against.
KNOWN_GOOD = {
    "static-content-rich",
    "static-content-rich-2",
    "ssr-content",
    "docs-site",
    "blog-with-byline",
    "robots-missing",
    "multi-url-site",
    "jsonld-clean",
    "headings-complete",
    "known-good-no-llms-txt",
    "known-good-multi-page",
    "known-good-docs-index",
    "known-good-sitemap-index",
    "known-good-long-content",
    "known-good-hybrid",
    "known-good-article",
}


def load_expectations(name: str) -> dict[str, str]:
    path = EXPECTED_DIR / f"{name}.yaml"
    if not path.exists():
        raise AssertionError(f"no expectation file for fixture {name!r} at {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data.get("checks", {})


def known_good_names() -> list[str]:
    return sorted(p.stem for p in EXPECTED_DIR.glob("*.yaml") if p.stem in KNOWN_GOOD)


def all_names() -> list[str]:
    return sorted(p.stem for p in EXPECTED_DIR.glob("*.yaml"))


@pytest.fixture(scope="session")
def expectations_dir() -> Path:
    if not EXPECTED_DIR.exists():
        pytest.skip(f"no expectation files at {EXPECTED_DIR}")
    return EXPECTED_DIR