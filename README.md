# geoctl

> **Status: pre-release.** v0.1 is in development. This README describes the intended
> behavior; the check catalog and scoring are still being calibrated.

**geoctl** — *Generative Engine Optimization control*. An open-source CLI that tells you
whether AI systems can **reach**, **read**, and **correctly answer questions from** your
website, and helps you fix what's broken. Bring your own LLM keys. Runs locally or in CI.
No account, no server.

> **On the name.** `geoctl` was chosen after a collision check found the earlier working
> name (`geoprobe`) unusable: taken on PyPI by an unrelated project, and in active use by
> a commercial product at `geoprobe.ai`. `geoctl` is free on PyPI, npm, and GitHub. The
> expansion is spelled out above because "geo" alone reads as *geospatial* to many
> developers. See [#4](https://github.com/Amank-root/GeoProbe/issues/4).

## Why this exists

Most GEO/AEO tools count artifacts — robots.txt rules, `llms.txt`, JSON-LD, sitemap —
and roll them into a 0–100 score. There are a dozen good open-source tools that already
do that, well. `geoctl` deliberately keeps only the checks that are specific to AI
crawler access, and spends its effort on the part that isn't commodity:

> **The answerability eval.** Give an LLM only what a *retrieval-style* text crawler
> would extract from your page — chunked, embedded, top-k retrieved, not the whole
> document pasted in — then ask it questions a real visitor would ask, and measure how
> many it gets right, with variance and with context recall reported separately.

That distinction matters. If you hand a frontier model the entire cleaned page, you are
measuring whether the model is smart, not whether your site is retrievable. Retrieving
the right span is the actual failure mode for AI answers, so the eval measures it.

## Install

```bash
uvx geoctl audit https://example.com     # one-off, no install
pipx install geoctl                      # installed
geoctl audit https://example.com
```

Optional JS rendering (adds Playwright):

```bash
pipx install "geoctl[render]"
```

## Quickstart

```bash
# Deterministic checks only — no API key needed
geoctl audit https://example.com

# With the answerability eval (uses your own key, e.g. OPENAI_API_KEY)
export OPENAI_API_KEY=...
geoctl audit https://example.com --eval

# Best signal: supply your own facts as ground truth
geoctl init                               # writes geoctl.toml + facts.yaml
geoctl audit https://example.com --eval --facts facts.yaml

# Gate CI
geoctl audit https://example.com --eval --fail-under-eval 70
```

## What it does and does not measure

It measures **readiness and retrievability**. It does **not** measure or promise
citations, rankings, or traffic from any AI product. Those depend on retrieval
pipelines, ranking, and vendor policy decisions that no local tool can observe. Treat
the score as a readiness indicator with published methodology, never as a forecast.

Two scores are reported side by side and are deliberately **not blended** into one
number, so you can always see which signal moved:

- a deterministic **access / rendering / discovery score**, and
- an **answerability score** with variance, abstention and hallucination rates, and
  context recall.

## Documentation

| Document | Contents |
|---|---|
| [docs/PRD.md](docs/PRD.md) | Problem, goals, users, requirements, metrics, risks |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Stack, module layout, interfaces, data flow |
| [docs/CLI_SPEC.md](docs/CLI_SPEC.md) | Commands, flags, config, exit codes |
| [docs/CHECKS.md](docs/CHECKS.md) | The scored check catalog and calibration plan |
| [docs/EVALS.md](docs/EVALS.md) | Answerability eval method and limitations |
| [docs/OUTPUT_SCHEMA.md](docs/OUTPUT_SCHEMA.md) | JSON report contract and versioning |
| [docs/TELEMETRY.md](docs/TELEMETRY.md) | Telemetry design and public policy |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Milestones and exit criteria |
| [docs/DECISIONS.md](docs/DECISIONS.md) | ADRs |

## Privacy and safety

- Site content never leaves your machine except to the LLM provider you configured.
- Telemetry is **opt-in**, allow-listed, and never contains URLs, page content, file
  paths, or keys. See [docs/TELEMETRY.md](docs/TELEMETRY.md).
- Simulated bot requests send an `X-Geoctl-Test: 1` header. Intended for sites you
  own or have permission to test.
- Private and loopback addresses are blocked unless you pass `--allow-private`.

## Open core

The CLI is fully capable, not a crippled demo. A hosted tier may sell only things that
require a service: scheduled runs, persistent history, alerts, multi-site and team
workspaces, managed keys. **A feature released in the OSS CLI is never moved to paid.**

## License

**AGPL-3.0-only.** It is a free, OSI-approved open source license.

The practical effect: if you fork this and distribute it, or run your modified version as a
service, you must offer your source under AGPL-3.0. You cannot take the free CLI, close it,
and charge for it. That is the point of choosing it over MIT or Apache-2.0.

It does not stop someone reimplementing the same ideas from scratch, or from using the name
in their trademark sense — [register the name](docs/DECISIONS.md#adr-004-license-is-agpl-30-only)
if that matters commercially. Reasoning in [ADR-004](docs/DECISIONS.md#adr-004-license-is-agpl-30-only).

## Won't do

- No guarantees of citations or rankings.
- No stealth crawling, IP rotation, or evading bot protection.
- No collection of site content by telemetry.
- No feature moved from OSS to paid.
