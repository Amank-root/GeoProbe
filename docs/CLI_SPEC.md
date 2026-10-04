# CLI Specification

Part of the [geoctl PRD](PRD.md). Working name; see PRD. This spec is the contract; breaking changes after v1.0 require a major version bump.

## 1. Invocation

```bash
# one-off, no install
uvx geoctl audit https://example.com

# installed
pipx install geoctl
geoctl audit https://example.com
```

Global flags (available on every command):

| Flag | Description |
|---|---|
| `--config PATH` | Use a specific config file |
| `--no-color` | Disable color (also honors `NO_COLOR`) |
| `-v, --verbose` | More logging (repeatable) |
| `-q, --quiet` | Errors only |
| `--version` | Print version and exit |
| `--help` | Help for the command |

## 2. Commands

### 2.1 `geoctl audit <url>` (v0.1)

Runs the deterministic checks and the answerability eval.

```bash
# Deterministic only — no key needed
geoctl audit https://example.com

# Deterministic + eval (auto-enabled when a key is present; see below)
geoctl audit https://example.com --eval --model openai/gpt-4o-mini

geoctl audit https://example.com --format json --output report.json
geoctl audit https://example.com --fail-under 70
```

**Eval is the headline, not an opt-in extra.** `--eval` defaults to **auto**: it runs when
an LLM key is present and is skipped with a one-line note when none is found. The
deterministic checks are the secondary, always-free layer. Rationale in
[ADR-012](DECISIONS.md#adr-012-the-eval-is-on-by-default-when-a-key-is-present).

| Flag | Default | Description |
|---|---|---|
| `--max-pages N` | 10 | Pages to audit for deterministic checks (start URL + sitemap sample) |
| `--bots LIST` | built-in set | Comma list of bot names to simulate (e.g. `GPTBot,ClaudeBot,PerplexityBot`) |
| `--format FORMAT` | `terminal` | `terminal`, `json`, `markdown` (repeatable) |
| `--output PATH` | stdout | Write report to a file; with multiple formats, use a directory |
| `--fail-under N` | off | Exit 1 if deterministic score < N |
| `--fail-under-eval N` | off | Exit 1 if answerability score < N (requires an eval run) |
| `--render / --no-render` | `--no-render` | Also fetch with Playwright for no-JS vs rendered comparison |
| `--allow-private` | off | Allow private / loopback targets (e.g. `localhost:3000`) |
| `--concurrency N` | 4 | Max concurrent requests |
| `--timeout SECONDS` | 15 | Per-request timeout |
| `--max-bytes N` | 5000000 | Max response size |
| `--no-cache` | off | Ignore cache reads (still writes) |
| `--only IDS` | all | Run only these check IDs or categories |
| `--skip IDS` | none | Skip these check IDs or categories |
| `--policy MODE` | `report` | How deliberate AI-bot blocks are treated: `report` (note only), `fail`, `ignore` |

Eval flags:

| Flag | Default | Description |
|---|---|---|
| `--eval / --no-eval / --eval-auto` | `--eval-auto` | Run the eval. `auto` = run it if a key is present, else skip with a note |
| `--model NAME` | from config | Answerer model (LiteLLM format, e.g. `anthropic/claude-sonnet-4-5`) |
| `--judge-model NAME` | same as `--model` | Judge model (different model recommended) |
| `--eval-pages N` | 3 | Pages evaluated. **Independent of `--max-pages`** — the deterministic audit covers 10 pages, the eval 3 |
| `--questions N` | 50 | Questions per page (hard cap 200). See [EVALS §4.2](EVALS.md#42-resolution-why-the-default-is-50-questions-not-10) for why |
| `--trials N` | 3 | Repeated trials; reported as mean with 95% CI |
| `--top-k N` | 5 | Chunks retrieved per question |
| `--facts PATH` | none | Facts file used as ground truth (YAML). Strongest signal — prefer it |
| `--dry-run` | off | Print estimated tokens and cost; make no LLM calls |
| `--max-cost USD` | none | Abort before exceeding this estimated cost. **Hard-fails if any selected model's price is unknown** |
| `--embedding-model NAME` | `openai/text-embedding-3-small` | Embedding model for retrieval. `gemini/gemini-embedding-001` is the cheap alternative |
| `--base-url URL` | none | Any OpenAI-compatible endpoint: Groq, NVIDIA NIM, Together, OpenRouter, vLLM, Ollama |
| `--api-key-env NAME` | provider default | Environment variable holding the key. The key is never read from config |
| `--input-cost-per-mtok N` | none | Price per 1M input tokens, for a model LiteLLM does not price |
| `--output-cost-per-mtok N` | none | Price per 1M output tokens, likewise |
| `--fail-under-eval-margin N` | 15 | Do not fail the build when the eval's 95% CI half-width exceeds this (points) |
| `--strict-eval` | off | Fail on a threshold even when the CI is too wide to justify it |

### 2.2 `geoctl init` (v0.1)

Creates a `geoctl.toml` and optional `facts.yaml` template in the current directory. Interactive on a TTY; accepts `--yes` for defaults.

### 2.3 `geoctl doctor` (v0.1, P1)

Checks Python version, optional extras (Playwright browsers), network reachability, LLM key presence (not validity unless `--test-keys`), cache directory, and telemetry status. Exit 0 if healthy.

### 2.4 `geoctl cache` (v0.1)

```bash
geoctl cache path
geoctl cache stats
geoctl cache clear [--llm] [--fetch]
```

### 2.5 `geoctl telemetry` (v0.1)

```bash
geoctl telemetry status     # enabled / disabled and why
geoctl telemetry enable
geoctl telemetry disable
geoctl telemetry show       # print the exact payload that would be sent
```

### 2.6 `geoctl generate ...` (v0.2)

```bash
geoctl generate llms-txt https://example.com --output public/llms.txt
geoctl generate robots   https://example.com --policy allow-search-block-training
geoctl generate jsonld   https://example.com --type Organization
```

Generates starter files from the crawl. Output is a proposal: never overwrites an existing file without `--force`.

### 2.7 `geoctl fix` (v0.3)

Planned: analyze a local repo, propose framework-aware changes, optionally open a PR. Out of scope for v0.1; interface to be specified when the fix agent is designed.

## 3. Configuration

### 3.1 Precedence

`CLI flags` > `environment variables` > project `geoctl.toml` > user config (`~/.config/geoctl/config.toml`) > defaults.

### 3.2 `geoctl.toml` example

```toml
[audit]
max_pages = 10
bots = ["GPTBot", "ClaudeBot", "PerplexityBot", "Google-Extended"]
policy = "report"          # report | fail | ignore
fail_under = 70

[fetch]
concurrency = 4
timeout = 15
max_bytes = 5000000

[eval]
enabled = "auto"           # auto | true | false  (auto = run if a key is present)
model = "openai/gpt-4o-mini"
judge_model = "anthropic/claude-sonnet-4-5"
eval_pages = 3
questions = 50
trials = 3
top_k = 5
max_cost = 1.00

[telemetry]
enabled = false
```

API keys do **not** go in this file. The tool warns if it detects key-like values in it.

### 3.3 Environment variables

| Variable | Purpose |
|---|---|
| `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, ... | Provider keys (standard LiteLLM names) |
| `GEOCTL_CONFIG` | Path to config file |
| `GEOCTL_CACHE_DIR` | Override cache location |
| `GEOCTL_TELEMETRY` | `0` / `1` |
| `DO_NOT_TRACK` | `1` disables telemetry regardless of other settings |
| `NO_COLOR` | Disable color output |

## 4. Facts file (`facts.yaml`)

Optional ground truth for the eval. Use it when you know what the site *should* be able to answer.

```yaml
# facts.yaml
site: https://example.com
facts:
  - id: pricing-starter
    question: "How much does the Starter plan cost per month?"
    answer: "$19 per month"
    page: /pricing            # optional: restrict to this page
  - id: founded
    question: "When was the company founded?"
    answer: "2019"
```

When present, these facts are used as the question set and ground truth, in addition to (or instead of, with `--facts-only`) generated questions.

A facts file is the **strongest** ground truth available, and the cheapest: it is
hand-written, so it is independent of both the crawler view and the rendered view, and it
makes the eval high-confidence. Prefer it whenever you know what your site should be able
to answer. `geoctl init` writes a commented template.

## 5. Exit codes

| Code | Meaning |
|---|---|
| 0 | Success (and any thresholds met) |
| 1 | Score below `--fail-under` or `--fail-under-eval` || 2 | Usage error (bad flags, invalid URL, bad config) |
| 3 | Target unreachable (DNS, connection, all fetches failed) |
| 4 | Authentication / provider error (missing or rejected API key) with `--eval` |
| 5 | Cost limit would be exceeded (`--max-cost`) |
| 6 | Blocked by safety rule (e.g. private address without `--allow-private`) |
| 70 | Internal error (bug); please report |

## 6. Output behavior

- **stdout** carries the report only (terminal, JSON, or Markdown) so it can be piped. Logs and progress go to **stderr**.
- When stdout is not a TTY, progress bars are disabled and color is off.
- `--format json` output validates against [OUTPUT_SCHEMA](OUTPUT_SCHEMA.md).

## 7. Example terminal output (illustrative)

```
geoctl 0.1.0 · https://example.com · 10 pages · 4.2s

Deterministic score  40 / 100

  Access        ███████████░░░░░░░░░░░  35/75
  Rendering     █░░░░░░░░░░░░░░░░░░░░░░   4/24
  Discovery     ███████████████████████   1/1

Hygiene (informational, not scored)
  Structure  5 pass · 1 warn    Structured data  2 pass · 1 fail
  Discovery  2 pass            Trust            1 pass · 1 warn

Top findings
  FAIL  REN-001  Only 9% of page text is present without JavaScript
        /pricing: 412 chars before JS vs 4,380 after (render with --render)
        Fix: server-render or pre-render the pricing content
  FAIL  SD-002   No Organization JSON-LD on home page
        Fix: add Organization JSON-LD to your layout or home page template
  WARN  ACC-002  ClaudeBot receives 403 on 3 of 10 pages (browser gets 200)
        Fix: check WAF / bot-protection rules for this user-agent

Answerability (openai/gpt-4o-mini, 3 trials, 50 questions/page)
  Mean 62 ± 7   Context recall 71%   Retrieval gap 9%
  Abstained 21%   Hallucinated 6%   Cost ≈ $0.04
  34 chunks · top-k 5 · embedding text-embedding-3-small

Full report: --format json | --format markdown
```

Only the three scored categories carry points; the hygiene tier is reported for
completeness and cannot move the score (ADR-010).
