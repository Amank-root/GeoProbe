# geoctl calibration report

- Fixtures: 38 (16 known-good, 42%)
- Check comparisons: 760

## How to read this report

Expectations in `tests/fixtures/expected/*.yaml` were **recorded from actual runs** (`scripts/generate-expectations.py`), not hand-authored. A zero mismatch count therefore means the checks are *reproducible and stable*, not that they are correct: a check that is consistently wrong is consistently wrong in its expectation file too.

What this run does establish, and what has to happen next:

- Established: every fixture reproduces the same statuses on every run, across all 20 checks. That is the precondition for measuring a rate at all.
- Not established: that the recorded statuses are the *correct* ones. Before release, a human must review the expectation files against CHECKS.md criteria. Any expectation file edited by hand makes this report meaningful, because a mismatch then signals a real behaviour change.
- The `no-hsts` and `known-good-no-llms-txt` fixtures exist specifically to pin judgement calls that are easy to get backwards.

## False positives on known-good fixtures

**Rate: 0.00%** (target: < 5%)

None.

### Excluded from the rate

- **SITE-001**: the fixture server is plain HTTP, so this measures the harness

## False negatives

A false negative is a fixture that failed to reproduce the defect it was built for. Any entry means that fixture has stopped testing anything. As with false positives, a zero here is only meaningful once the expectations have been reviewed against CHECKS.md.

None.

## Per-check

| Check | Compared | False pos | False neg |
|---|---:|---:|---:|
| ACC-001 | 38 | 0 | 0 |
| ACC-002 | 38 | 0 | 0 |
| ACC-003 | 38 | 0 | 0 |
| REN-001 | 38 | 0 | 0 |
| REN-002 | 38 | 0 | 0 |
| DIS-001 | 38 | 0 | 0 |
| DIS-002 | 38 | 0 | 0 |
| DIS-003 | 38 | 0 | 0 |
| SD-001 | 38 | 0 | 0 |
| SD-002 | 38 | 0 | 0 |
| SD-003 | 38 | 0 | 0 |
| SITE-001 | 38 | 0 | 0 |
| STR-001 | 38 | 0 | 0 |
| STR-002 | 38 | 0 | 0 |
| STR-003 | 38 | 0 | 0 |
| STR-004 | 38 | 0 | 0 |
| STR-005 | 38 | 0 | 0 |
| STR-006 | 38 | 0 | 0 |
| TRU-001 | 38 | 0 | 0 |
| TRU-002 | 38 | 0 | 0 |
