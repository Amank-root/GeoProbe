# Changelog

All notable changes to `geoctl`. Format follows [Keep a Changelog](https://keepachangelog.com/);
versions follow [Semantic Versioning](https://semver.org/).

The JSON report is a public contract. `schema_version` follows semver for the
schema, independently of the tool version: additive changes bump the minor,
breaking changes bump the major and are called out here
([OUTPUT_SCHEMA §1](docs/OUTPUT_SCHEMA.md)).

## [Unreleased]

### Added

- **`geoctl generate llms-txt | robots | jsonld`** (Milestone 2). Each writes a proposal
  derived only from what the crawl observed, refuses to overwrite an existing file without
  `--force`, and states its own limits at the point of generation. See
  [ADR-018](docs/DECISIONS.md).
- **The provider key now selects the model.** When `--model` is omitted, geoctl detects which
  key is set and picks a model that key can call, including the base URL for
  OpenAI-compatible hosts LiteLLM cannot route on its own. The embedding model follows the
  same provider instead of defaulting to OpenAI's, so retrieval no longer silently degrades
  to lexical scoring for non-OpenAI users. A suffixed key such as `GEMINI_API_KEY_1` counts.
- **Any OpenAI-compatible endpoint** for the eval: `--base-url`, `--api-key-env`. Groq,
  NVIDIA NIM, Together, OpenRouter, vLLM and Ollama are now reachable. Groq and Gemini
  additionally work as first-class LiteLLM providers with no `base_url` needed.
- **`--embedding-model`** flag. Embeddings previously had a config key but no CLI flag,
  so switching embedding provider required hand-editing a file.
- **Known prices for 18 models**, including Gemini and Groq rates and the OpenAI
  embedding models.

### Fixed

- **The eval only worked with an OpenAI key.** `--eval auto` fired on any provider key but
  then used a hardcoded `openai/gpt-4o-mini`, so every other provider got an authentication
  failure from the headline feature. `doctor --test-keys` had the same hardcoding and
  reported working NVIDIA and Groq keys as broken. A suffixed key (`GEMINI_API_KEY_1`) was
  not counted as a key at all, and `--base-url` without `--api-key-env` sent no key.
  [#45](https://github.com/Amank-root/GeoProbe/issues/45)
- **Reasoning models were scored on their reasoning trace.** A reasoning model counts its
  chain of thought against `max_tokens`; the answerer's 300-token budget was spent entirely
  thinking, and the resulting trace was parsed as the answer, so a correctly answered
  question scored `NOT_FOUND` / 0. Budgets are now sized to the work and `finish_reason` is
  part of the response contract — a truncated response is recorded as an answerer *error*, so
  it no longer inflates the hallucination rate or blames the website. The judge had the same
  defect at 200 tokens, and question generation had no limit at all, which made a long page
  report "no questions could be produced". [#46](https://github.com/Amank-root/GeoProbe/issues/46)
- **A skipped eval reported "internal error … please report" and exited 70.**
  `EvalSkipped` was never caught, so every skip told users to file a bug against their own
  website. It is now a note, and exit 0.
- **`generate` returned exit 1 for an SSRF refusal**, which reads as a threshold failure
  rather than a safety refusal. It now exits 6, as `audit` does.
- **An unknown model price reported `$0.00`.** LiteLLM's cost table is missing many
  current models — including `openai/gpt-4o-mini`, our own default, and
  `openai/text-embedding-3-small`, our default embedding model — so cost estimation
  silently fell through to zero and `--max-cost` could not protect the user.
  `known_price()` now distinguishes "free" from "unknown", and prices are resolved
  from the local table, then LiteLLM, then a user override.
- **`--max-cost` now hard-fails on an unknown price** instead of treating it as within
  budget. A spending ceiling cannot be enforced against an unknown cost. Supply prices
  with `--input-cost-per-mtok` / `--output-cost-per-mtok`, or drop the flag to accept an
  unknown cost. Checked before `--dry-run` returns too, since that is where someone goes
  to find out what a run will cost.
- The cache key now includes the endpoint, so the same model name behind two different
  hosts can no longer share cached answers.

## [0.1.0] — 2026-10-04

First implementation of the v0.1 "Audit" milestone ([ROADMAP](docs/ROADMAP.md)).

### Added

- **Deterministic audit** — 20 checks (6 scored to 100 points, 14 informational at
  0 points), fetched per simulated AI bot with parity comparison against a
  browser request.
- **Answerability eval** — question generation, chunk/embed/top-k retrieval,
  answerer, judge, multi-trial aggregation with a binomial 95% CI, context recall
  and retrieval gap. Runs automatically when a provider key is present
  ([ADR-012](docs/DECISIONS.md)).
- **Ground-truth tiers** — `facts.yaml`, JS-rendered text, or the crawler view.
  The circular tier is labelled low-confidence and cannot gate CI
  ([ADR-014](docs/DECISIONS.md)).
- **Reporters** — terminal, JSON, and Markdown, all rendering one shared result
  model.
- **JSON Schema** — `geoctl.schema.json`, generated from the Pydantic models, with
  a committed golden report that CI validates against it.
- **Config** — precedence of flags over env over project toml over user toml;
  secrets are rejected from toml files.
- **Commands** — `audit`, `init`, `doctor`, `cache`, `telemetry`, `schema`.
- **Opt-in telemetry** — allow-listed payload, hard off-switches, and
  `geoctl telemetry show` ([TELEMETRY](docs/TELEMETRY.md)).
- **Safety** — SSRF guard validating every redirect hop, response-size and
  redirect limits, per-host delays, and an `X-Geoctl-Test: 1` header on simulated
  requests ([ADR-008](docs/DECISIONS.md)).
- **Fixtures and calibration** — 38 offline fixtures covering all 28 categories
  in [FIXTURES](docs/FIXTURES.md), 16 of them known-good, with a per-check
  false-positive report in [CALIBRATION](docs/CALIBRATION.md).
- **CI** — lint, typecheck, tests on Python 3.11–3.13 with no network and no API
  key, schema-drift detection, package build, and a docs build.

### Fixed

- `docs/EVALS.md` §4.2 tabulated the 1-SE figure under a "95% CI" heading, which
  understated the interval by 2×. The table now reports true 95% half-widths, and
  `--fail-under-eval-margin` defaults to ±15 points — just above the real
  resolution at the default sample size of 50 questions — instead of ±10, which
  would have made the threshold gate unreachable at defaults.
- Documented that `per_trial_stddev` (variation across trials) and `ci95`
  (sampling error across questions) are different quantities and are never
  combined.

### Known limitations

See [METHODOLOGY § Known limitations](docs/METHODOLOGY.md). The most consequential:
the retrieval simulation is an approximation of real vendor pipelines; scores are
not comparable across models; and `SITE-001` cannot be calibrated by the offline
suite because the fixture server is plain HTTP by necessity.

[Unreleased]: https://github.com/Amank-root/GeoProbe/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Amank-root/GeoProbe/releases/tag/v0.1.0
