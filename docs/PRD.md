# PRD: geoprobe

> **Working name.** `geoprobe` is a placeholder and **cannot be used as-is**: the name is
> taken on PyPI by a dormant, unrelated seismic-data library, and an operating commercial
> product with heavily overlapping scope already runs at `geoprobe.ai`. The collision check
> is complete and the replacement name is open — see
> [#4](https://github.com/Amank-root/GeoProbe/issues/4). Milestone 1's PyPI release cannot
> proceed under this name.

| | |
|---|---|
| **Status** | Draft v0.1 |
| **Scope of this document** | Open-source CLI only (hosted tier is out of scope, see §10) |
| **Companion docs** | [ARCHITECTURE](ARCHITECTURE.md) · [CLI_SPEC](CLI_SPEC.md) · [CHECKS](CHECKS.md) · [EVALS](EVALS.md) · [OUTPUT_SCHEMA](OUTPUT_SCHEMA.md) · [TELEMETRY](TELEMETRY.md) · [ROADMAP](ROADMAP.md) · [DECISIONS](DECISIONS.md) |

---

## 1. Summary

`geoprobe` is a command-line tool that takes a website URL and tells you, with evidence, whether AI systems (ChatGPT, Claude, Perplexity, Gemini, Google AI Overviews, and agentic browsers) can **reach**, **read**, and **correctly answer questions from** your content. It then helps you fix what is broken.

It is bring-your-own: the user installs it, supplies their own LLM keys if they want the LLM-based evaluation, runs it locally or in CI, and gets a report. No account, no server.

## 2. Problem

People increasingly ask AI assistants instead of searching. Site owners want to know whether their site works for those systems. Existing tools mostly:

1. **Check for the presence of artifacts** (robots.txt rules, llms.txt, JSON-LD, sitemap) and roll them into a 0–100 score.
2. **Do not verify that the artifacts matter.** Some checked artifacts (notably `llms.txt`) are rarely requested by crawlers, so a score built on them can be misleading.
3. **Stop at advice.** The real problems are often in code (client-only rendering, broken heading hierarchy, missing structured data in a layout), and generated files do not fix them.

## 3. Product vision

> Measure whether AI can actually read and answer from your site, then fix it in your codebase.

Two ideas differentiate the product:

- **Answerability evaluation.** Instead of only counting artifacts, test whether an LLM given *only what a crawler sees* can correctly answer questions about the site.
- **Fixes as code changes.** Later versions open pull requests with framework-aware fixes instead of dropping generated files.

## 4. Goals and non-goals

### Goals (v0.1)

- G1. One command audits a URL and produces a clear report with prioritized, evidence-backed findings.
- G2. Useful with **zero API keys** (deterministic checks only).
- G3. With a key, runs an **answerability eval** that is reproducible and reports variance.
- G4. Output is machine-readable (stable JSON) and CI-friendly (exit codes, `--fail-under`).
- G5. Safe by default: respects limits, blocks SSRF, never sends site content anywhere except the LLM provider the user configured.
- G6. Easy to install and run: a single `uvx` or `pipx` command.

### Non-goals (v0.1)

- Guaranteeing citations or rankings in any AI product. The tool measures readiness, not outcomes.
- Tracking real citation rates in live AI products (planned later, see ROADMAP).
- Automatic code changes or PR generation (v0.3).
- A web UI, dashboard, accounts, or hosted service.
- Full-site SEO auditing (Lighthouse, Core Web Vitals, backlink analysis).
- Content rewriting at scale.

## 5. Target users

| Persona | Need | How they use it |
|---|---|---|
| **Indie dev / founder** | "Is my landing page and docs readable by AI?" | `uvx geoprobe audit https://mysite.com` |
| **Frontend / platform engineer** | Catch regressions on deploy | GitHub Action with `--fail-under` |
| **Agency / consultant** | Baseline audits for clients | CLI + JSON/Markdown reports |
| **Docs / DevRel owner** | Make docs quotable by assistants | Answerability eval with a facts file |

Primary persona for v0.1: **developer who owns the site's code**.

## 6. Positioning

| Capability | Typical existing tools | geoprobe |
|---|---|---|
| Artifact checks (robots, sitemap, llms.txt, schema) | ✅ | ✅ (llms.txt deliberately low-weighted) |
| Per-bot fetch simulation | Some | ✅ (compares bot view to browser view) |
| No-JS content ratio | Some | ✅ |
| **LLM answerability eval with variance** | Rare | ✅ (core differentiator) |
| Honest scoring with evidence per finding | Rare | ✅ |
| Framework-aware code fixes via PR | Rare | Planned (v0.3) |
| Runs fully local, BYO keys | Some | ✅ |

Do not compete on breadth of checks or visual polish.

## 7. User stories

- **US-1.** As a developer, I run one command and see which AI bots are blocked or served different content than a browser, so I can fix access problems.
- **US-2.** As a developer, I see how much of my page's text exists before JavaScript runs, so I know whether client-side rendering is hiding content.
- **US-3.** As a site owner, I provide an LLM key and get an answerability score ("the model correctly answered 14 of 20 questions from what a crawler sees"), so I have a measurable target.
- **US-4.** As a CI owner, I fail the build if the score drops below a threshold, so regressions are caught.
- **US-5.** As a consultant, I export JSON and Markdown reports, so I can share results with clients.
- **US-6.** As a cost-conscious user, I run `--dry-run` to see the estimated LLM cost before spending anything.
- **US-7.** As a privacy-conscious user, I can see exactly what telemetry is sent and turn it off with one setting.

## 8. Functional requirements

Priority: **P0** = required for v0.1, **P1** = v0.1 if time allows, **P2** = later.

### 8.1 Fetching and crawling

| ID | Requirement | Priority |
|---|---|---|
| FR-1 | Fetch the target URL with a normal browser user-agent (baseline). | P0 |
| FR-2 | Fetch the same URL with each configured AI bot user-agent and compare status, size, and extracted text to baseline. | P0 |
| FR-3 | Fetch and parse `robots.txt`, evaluating allow/block rules per AI bot token. | P0 |
| FR-4 | Discover and parse `sitemap.xml` (including sitemap indexes). | P0 |
| FR-5 | Crawl up to `--max-pages` (default 10) pages: the start URL plus sitemap-sampled pages on the same origin. | P0 |
| FR-6 | Optional JS-rendered fetch via Playwright for comparison with the no-JS view. | P1 |
| FR-7 | Honor timeouts, redirects limits, response-size limits, and concurrency limits. | P0 |
| FR-8 | Block requests to private/loopback/link-local addresses unless `--allow-private` is set. | P0 |

### 8.2 Checks

| ID | Requirement | Priority |
|---|---|---|
| FR-9 | Run the deterministic check catalog in [CHECKS](CHECKS.md). Each check returns pass/warn/fail/skip/error with evidence and a fix hint. | P0 |
| FR-10 | Compute category and overall scores from check weights. | P0 |
| FR-11 | Every finding includes the evidence used (URL, header, snippet, measured value). | P0 |

### 8.3 Answerability eval

| ID | Requirement | Priority |
|---|---|---|
| FR-12 | Build a "crawler view" of each page (what a non-JS fetch yields after main-content extraction). | P0 |
| FR-13 | Build a "ground truth view" (JS-rendered text and/or user-supplied facts file). | P0 for facts file, P1 for JS-rendered |
| FR-14 | Generate questions from ground truth, answer them from crawler view only, judge against ground truth. | P0 |
| FR-15 | Run N trials (default 3) and report mean, standard deviation, abstention rate, and hallucination rate. | P0 |
| FR-16 | Cache all LLM calls on disk keyed by a content hash. | P0 |
| FR-17 | `--dry-run` prints estimated token usage and cost without calling a model. | P0 |
| FR-18 | Support any model reachable through the LLM abstraction layer (OpenAI, Anthropic, Gemini, local). | P0 |

See [EVALS](EVALS.md) for method and caveats.

### 8.4 Output

| ID | Requirement | Priority |
|---|---|---|
| FR-19 | Terminal report with summary, category scores, and prioritized findings. | P0 |
| FR-20 | JSON report conforming to [OUTPUT_SCHEMA](OUTPUT_SCHEMA.md), with a `schema_version`. | P0 |
| FR-21 | Markdown report suitable for pasting into an issue or sharing with a client. | P0 |
| FR-22 | Exit codes: 0 success, 1 score below `--fail-under`, other codes for errors (see [CLI_SPEC](CLI_SPEC.md)). | P0 |

### 8.5 Configuration and operations

| ID | Requirement | Priority |
|---|---|---|
| FR-23 | Config via flags, environment variables, and `geoprobe.toml` (precedence in CLI_SPEC). | P0 |
| FR-24 | `geoprobe doctor` verifies environment, network, and key configuration. | P1 |
| FR-25 | Telemetry is opt-in per [TELEMETRY](TELEMETRY.md). | P0 |
| FR-26 | `geoprobe generate llms-txt` and `generate robots` produce starter files from the crawl. | P1 (v0.2 if cut) |

## 9. Non-functional requirements

- **Performance.** A 10-page deterministic audit completes in under 30 seconds on a typical connection. Eval time depends on the model.
- **Reproducibility.** Same inputs, same config, and cached LLM responses produce identical results.
- **Cost transparency.** Eval always reports tokens used and estimated cost.
- **Portability.** Python 3.10+; Linux, macOS, Windows.
- **Security.** SSRF protection, no execution of fetched content, secrets read from env or keyring and never written to reports or logs.
- **Privacy.** No site content leaves the machine except to the user's chosen LLM provider.
- **Accessibility of output.** Terminal output readable without color (`NO_COLOR` respected).
- **Quality.** Tests run in CI without network or API access (recorded fixtures).

## 10. Open-core boundary (principles)

The CLI is **fully capable**, not a crippled demo. The paid hosted tier (not part of this PRD) will sell things that only make sense as a service:

- Scheduled runs and persistent history
- Alerts and regression notifications
- Multi-site and team features
- Managed keys and managed query sets

Rules:

1. A feature present in the OSS CLI is never later moved to paid.
2. The OSS roadmap is public; the boundary is documented in the README from day one.
3. Local single-run capability stays in OSS; recurring and collaborative capability may be paid.

See [DECISIONS](DECISIONS.md) ADR-007.

## 11. Success metrics

**Adoption (6 months post-release; targets are initial guesses to be revised)**

- PyPI weekly installs and GitHub stars trend (directional only)
- Number of external issues and PRs (signal of real use)
- GitHub Action usages (if public usage is visible)

**Product quality**

- Eval stability: the 95% confidence interval on the answerability mean is narrow enough
  to be useful as a regression signal. Target: **CI width ≤ 0.20 (±10 points)** on a fixed
  fixture set at the default `--questions 50`. Per-trial variation is reported separately
  as `per_trial_stddev` and is a different quantity; see [EVALS §4.2](EVALS.md#42-resolution-why-the-default-is-50-questions-not-10)
  for why the two must not be conflated.
- False-positive rate of checks on a curated set of known-good sites (target: < 5%)
- Time-to-first-report for a new user under 2 minutes

**Credibility**

- A published methodology and small open benchmark (see ROADMAP)

## 12. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| LLM eval is noisy | Users distrust scores | Multiple trials, report variance, cache, fixed settings, separate judge model |
| Eval is circular (questions generated from the same text it answers from) | Scores meaningless | Ground truth view differs from crawler view; facts-file option; documented in EVALS |
| Scores imply guarantees about real AI products | Misleading claims | Plain language in README and reports: measures readiness, not citations |
| Check catalog drifts as bots and guidance change | Stale advice | Data-driven bot list, versioned check catalog, public changelog |
| Spoofed bot user-agents used against third-party sites | Ethical / abuse concerns | Document intended use on sites you control; rate limits; honest `X-Geoprobe-Test` header; no stealth |
| LLM costs surprise users | Bad first experience | `--dry-run`, default small question count, cost shown in report |
| Telemetry backlash | Trust loss | Opt-in, minimal, inspectable, documented |
| Existing OSS tool adds the same features | Reduced differentiation | Keep focus on eval + code fixes; consider upstream contributions where overlap is high |

## 13. Release plan

| Release | Theme |
|---|---|
| **v0.1** | Audit + deterministic checks + answerability eval + reports |
| **v0.2** | `generate` commands + GitHub Action |
| **v0.3** | Framework-aware fix PRs (Next.js first) |
| **v0.4** | Local citation snapshots and diffs |

Details and exit criteria in [ROADMAP](ROADMAP.md).

## 14. Open questions

1. Final name and license (ADR-004).
2. Should the default bot list include search-engine bots (Googlebot) or only AI-specific tokens?
3. How should the score treat sites that deliberately block AI bots? (Proposed: separate "policy" status instead of failing the check.)
4. Is a facts file (`facts.yaml`) enough ground truth, or is JS-rendered text needed in v0.1?
5. Which LLM provider to use for the maintainers' own CI evals, given cost?
6. Should the tool ship a built-in default question set for common site types (docs, SaaS landing, e-commerce)?
