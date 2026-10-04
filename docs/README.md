# geoctl: Product Documentation

**geoctl** — *Generative Engine Optimization control*. An open-source CLI that tells you whether AI systems can **reach**, **read**, and **correctly answer questions from** your website, then helps you fix what's broken. Bring your own LLM keys; runs locally or in CI; no account.

> **On the name.** Chosen after a collision check found `geoprobe` unusable (taken on PyPI
> by an unrelated project; in active use by a commercial product at `geoprobe.ai`).
> `geoctl` is free on PyPI, npm, and GitHub. The expansion is given because "geo" alone
> reads as *geospatial* to many developers. See [#4](https://github.com/Amank-root/GeoProbe/issues/4).

## Reading order

| # | Document | What it covers |
|---|---|---|
| 1 | [PRD.md](PRD.md) | Problem, goals, users, requirements, metrics, risks. **Start here.** |
| 2 | [ARCHITECTURE.md](ARCHITECTURE.md) | Tech stack, module layout, interfaces, data flow, testing |
| 3 | [CLI_SPEC.md](CLI_SPEC.md) | Commands, flags, config, exit codes, example output |
| 4 | [CHECKS.md](CHECKS.md) | Deterministic check catalog, criteria, weights, calibration plan |
| 5 | [EVALS.md](EVALS.md) | Answerability eval method, noise controls, limitations |
| 6 | [OUTPUT_SCHEMA.md](OUTPUT_SCHEMA.md) | JSON report contract and versioning |
| 7 | [TELEMETRY.md](TELEMETRY.md) | Opt-in telemetry design and draft public policy |
| 8 | [ROADMAP.md](ROADMAP.md) | Milestones, deliverables, exit criteria |
| 9 | [DECISIONS.md](DECISIONS.md) | ADRs: language, license, telemetry, open-core boundary, etc. |
| 10 | [FIXTURES.md](FIXTURES.md) | Fixture-site coverage spec for calibration and CI |
| 11 | [METHODOLOGY.md](METHODOLOGY.md) | How the numbers are produced, and precisely what they do not establish |
| 12 | [CALIBRATION.md](CALIBRATION.md) | Latest per-check false-positive and false-negative run |
| 13 | [../CONTRIBUTING.md](../CONTRIBUTING.md) | How to contribute: setup, adding checks and fixtures, expectations |

## One-paragraph pitch

Most GEO/AEO tools count artifacts (robots.txt rules, llms.txt, schema) and produce a score. `geoctl` does that too, but adds an **answerability eval**: give an LLM only what a text crawler sees, ask it questions about your site, and measure how many it gets right, with variance. Later versions turn findings into **framework-aware pull requests**.

## Status of decisions

| Item | Status |
|---|---|
| Name | Settled: `geoctl` (#4, #7) |
| License | Settled: AGPL-3.0-only (ADR-004) |
| Language / stack | Settled: Python (ADR-001) |
| Telemetry | Settled: opt-in (ADR-005), implemented |
| Check weights | Provisional: initial calibration done, weights not yet tuned against a labeled set (ADR-009) |

## Suggested first contribution

Milestone 0 and the Milestone 1 implementation are done. The highest-value work
now is **reviewing the recorded check expectations against
[CHECKS](CHECKS.md) criteria** — see [CALIBRATION](CALIBRATION.md) for why that
matters — and reporting any check that fires wrongly. A false positive on a
known-good site counts directly against the < 5% release target.

## Conventions used across these docs

- **Requirement IDs:** `FR-n` in the PRD; **check IDs:** `ACC-`, `REN-`, `STR-`, `SD-`, `DIS-`, `TRU-` in CHECKS.
- **Priority:** P0 required for v0.1, P1 if time allows, P2 later.
- Weights, thresholds, and targets are initial values to be validated, not claims about how any AI product behaves.
