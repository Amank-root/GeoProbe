# geoctl

> **Status: v0.1 implemented, weights still provisional.** Every command below works
> and the test suite runs offline with no API key. The 6 scored checks are calibrated
> against 38 local fixtures ([docs/CALIBRATION.md](docs/CALIBRATION.md)); the weights
> are initial values, not a claim about what any AI product rewards.

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

A report with no API key takes well under two minutes:

```bash
geoctl audit https://example.com
```

```
geoctl 0.1.0 · https://example.com · 10 pages · 4.2s

Deterministic score  40 / 100

  Access        ███████████░░░░░░░░░░░  35/75
  Rendering     █░░░░░░░░░░░░░░░░░░░░░░   4/24
  Discovery     ███████████████████████   1/1

Top findings
  FAIL  REN-001  Only 9% of page text is present without JavaScript.
        /pricing: 412 chars before JS vs 4,380 after (render with --render)
        Fix: server-render or pre-render the pricing content

Measures AI readiness — reach, read, answerability. Not citations or rankings.
```

Adding the answerability eval, which uses your own key:

```bash
export OPENAI_API_KEY=...
geoctl audit https://example.com --eval --judge-model anthropic/claude-sonnet-4-5
```

The strongest and cheapest eval input is a **facts file** you write yourself — it is
independent of both the crawler view and the rendered view, so it cannot be inflated
by extraction luck ([ADR-014](docs/DECISIONS.md)):

```bash
geoctl init                                        # writes geoctl.toml + facts.yaml
$EDITOR facts.yaml
geoctl audit https://example.com --facts facts.yaml
```

Any OpenAI-compatible provider works — Groq, NVIDIA NIM, Gemini, Together, OpenRouter,
or a self-hosted vLLM or Ollama:

```bash
# Gemini end to end. gemini-embedding-001 is $0.15/1M tokens and charges on input only.
export GEMINI_API_KEY=...
geoctl audit https://example.com --model gemini/gemini-2.5-flash \
    --judge-model gemini/gemini-2.5-pro \
    --embedding-model gemini/gemini-embedding-001

# A host LiteLLM has no provider for, via an explicit endpoint
export NVIDIA_API_KEY=...
geoctl audit https://example.com \
    --base-url https://integrate.api.nvidia.com/v1 --api-key-env NVIDIA_API_KEY
```

Cost control, because at the defaults this is not a free operation:

```bash
geoctl audit https://example.com --dry-run          # estimate only, no API calls
geoctl audit https://example.com --max-cost 0.50   # abort before exceeding
```

Gate CI. `--fail-under` is deterministic and always applicable; `--fail-under-eval`
needs an eval and refuses to gate on noise:

```bash
geoctl audit https://example.com --fail-under 70
geoctl audit https://example.com --facts facts.yaml --fail-under-eval 70
```

Other useful commands:

```bash
geoctl audit https://example.com --format json --output report.json
geoctl audit https://example.com --render           # needs geoctl[render]
geoctl doctor                                     # check keys, cache, extras
geoctl telemetry show                              # exactly what would be sent
geoctl cache stats
```

One thing worth knowing before you gate on the eval: at the default 50 questions the
95% confidence interval is about **±14 points**, so the threshold gate defaults to a
±15 margin and will decline to fail on a wide interval. To gate more tightly, raise
`--questions`; lowering the margin just fails on noise. The arithmetic is in
[docs/EVALS.md §4.2](docs/EVALS.md#42-resolution-why-the-default-is-50-questions-not-10).

Full flag reference: [docs/CLI_SPEC.md](docs/CLI_SPEC.md).

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
| [docs/FIXTURES.md](docs/FIXTURES.md) | Fixture-site coverage spec for calibration |
| [docs/METHODOLOGY.md](docs/METHODOLOGY.md) | How the numbers are produced, and their limits |
| [docs/CALIBRATION.md](docs/CALIBRATION.md) | Latest per-check false-positive run |
| [CHANGELOG.md](CHANGELOG.md) | Release notes |

Docs site: `mkdocs serve` (see [mkdocs.yml](mkdocs.yml)).

## Privacy and safety

- Site content never leaves your machine except to the LLM provider you configured.
- Telemetry is **opt-in**, allow-listed, and never contains URLs, page content, file
  paths, or keys. See [docs/TELEMETRY.md](docs/TELEMETRY.md).
- Simulated bot requests send an `X-Geoctl-Test: 1` header. Intended for sites you
  own or have permission to test.
- Private and loopback addresses are blocked unless you pass `--allow-private`.
- API keys are read from the environment only. `geoctl` refuses to start if it finds
  key-like values in `geoctl.toml`, so a credential cannot be committed by accident.

## Open core

The CLI is fully capable, not a crippled demo. A hosted tier may sell only things that
require a service: scheduled runs, persistent history, alerts, multi-site and team
workspaces, managed keys. **A feature released in the OSS CLI is never moved to paid.**

## License

**AGPL-3.0-only.** It is a free, OSI-approved open source license.

The practical effect: if you fork this and distribute it, or run your modified version as a
service, you must offer your source under AGPL-3.0. You cannot take the free CLI, close it,
and charge for it. That is the point of choosing it over MIT or Apache-2.0.

It does not stop someone reimplementing the same ideas from scratch — that is a deliberate,
accepted limit, and the name is not being trademarked. A fork must rename and cannot pass
itself off as `geoctl`. Reasoning in [ADR-004](docs/DECISIONS.md#adr-004-license-is-agpl-30-only).

## Contributing

Contributions are welcome, including first-time ones. See [CONTRIBUTING.md](CONTRIBUTING.md) —
there is a table of ways to help ranked by effort, from reporting a false positive
(about 30 minutes) to adding a check. No CLA or DCO sign-off required.

## Won't do

- No guarantees of citations or rankings.
- No scores presented as comparable across different LLM models.
- No stealth crawling, IP rotation, or evading bot protection.
- No collection of site content by telemetry.
- No feature moved from OSS to paid.
