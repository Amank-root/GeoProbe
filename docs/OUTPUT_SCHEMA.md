# JSON Output Schema

Part of the [geoctl PRD](PRD.md). Working name; see PRD.

`geoctl audit --format json` emits one JSON document. This is a public contract: consumers (CI, dashboards, the future hosted service) depend on it.

## 1. Versioning rules

- `schema_version` follows semver for the **schema**, independent of the tool version.
- **Additive changes** (new optional fields) bump the minor version.
- **Breaking changes** (removing/renaming fields, changing types or meaning) bump the major version and are listed in the changelog.
- Consumers should ignore unknown fields.
- The tool publishes a JSON Schema file (`geoctl.schema.json`) generated from the Pydantic models, and CI verifies that example outputs validate against it.

## 2. Top-level structure

```json
{
  "schema_version": "1.0.0",
  "tool": { "name": "geoctl", "version": "0.1.0" },
  "run": { },
  "target": { },
  "score": { },
  "checks": [ ],
  "pages": [ ],
  "eval": { },
  "errors": [ ]
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `schema_version` | string | yes | Schema semver |
| `tool` | object | yes | Tool name and version |
| `run` | object | yes | Run metadata and settings |
| `target` | object | yes | What was audited |
| `score` | object | yes | Deterministic scores |
| `checks` | array | yes | One entry per check executed |
| `pages` | array | yes | Per-page summaries |
| `eval` | object \| null | yes | `null` if eval did not run |
| `errors` | array | yes | Non-fatal errors and warnings (may be empty) |

## 3. Full example

```json
{
  "schema_version": "1.0.0",
  "tool": { "name": "geoctl", "version": "0.1.0" },
  "run": {
    "id": "01J9ZK3Q8V6M2R4T7W1XH5N0AB",
    "started_at": "2026-10-04T10:15:02Z",
    "duration_ms": 4210,
    "checks_version": "2026.10.0",
    "eval_version": null,
    "config": {
      "max_pages": 10,
      "bots": ["GPTBot", "ClaudeBot", "PerplexityBot"],
      "policy": "report",
      "render": false
    }
  },
  "target": {
    "url": "https://example.com",
    "final_url": "https://www.example.com/",
    "pages_audited": 10,
    "sitemap_found": true
  },
  "score": {
    "overall": 40,
    "max": 100,
    "categories": {
      "access":    { "points": 35, "max": 75 },
      "rendering": { "points": 4,  "max": 24 },
      "discovery": { "points": 1,  "max": 1 }
    }
  },
  "checks": [
    {
      "id": "REN-001",
      "category": "rendering",
      "title": "Text available without JavaScript",
      "status": "fail",
      "weight": 20,
      "points": 0,
      "confidence": "high",
      "message": "Only 9% of page text is present without JavaScript.",
      "evidence": {
        "pages": [
          { "url": "https://www.example.com/pricing", "nojs_chars": 412, "rendered_chars": 4380, "ratio": 0.094 }
        ],
        "framework_markers": ["__next"]
      },
      "fix": {
        "summary": "Server-render or pre-render the pricing content.",
        "docs_url": "https://github.com/Amank-root/GeoProbe/blob/main/docs/CHECKS.md#ren-001-text-available-without-javascript-20",
        "machine": null
      }
    },
    {
      "id": "ACC-001",
      "category": "access",
      "title": "robots.txt rules per AI bot",
      "status": "pass",
      "weight": 25,
      "points": 25,
      "confidence": "high",
      "message": "All configured bots are allowed.",
      "evidence": {
        "robots_url": "https://www.example.com/robots.txt",
        "bots": [
          { "bot": "GPTBot", "verdict": "allowed", "matched_rule": null },
          { "bot": "ClaudeBot", "verdict": "allowed", "matched_rule": null }
        ]
      },
      "fix": null
    }
  ],
  "pages": [
    {
      "url": "https://www.example.com/pricing",
      "status_by_bot": { "browser": 200, "GPTBot": 200, "ClaudeBot": 403 },
      "text_chars": { "browser-nojs": 412, "rendered": 4380 },
      "title": "Pricing | Example",
      "h1_count": 1,
      "json_ld_types": []
    }
  ],
  "eval": {
    "eval_version": "1",
    "confidence": "high",
    "ground_truth": "facts+rendered",
    "answerer_model": "openai/gpt-4o-mini",
    "judge_model": "anthropic/claude-sonnet-4-5",
    "trials": 3,
    "questions_per_page": 50,
    "pages_evaluated": 3,
    "answerability": { "mean": 62.0, "per_trial_stddev": 7.1, "per_trial": [58.5, 63.0, 64.5], "ci95": [55.0, 69.0] },
    "context_recall": 0.71,
    "retrieval_gap": 0.09,
    "retrieval": {
      "mode": "chunked",
      "top_k": 5,
      "chunk_target_tokens": 400,
      "chunk_overlap_pct": 10,
      "embedding_model": "openai/text-embedding-3-small",
      "chunk_count": 34
    },
    "abstention_rate": 0.21,
    "hallucination_rate": 0.06,
    "coverage_loss": 0.19,
    "usage": { "input_tokens": 182340, "output_tokens": 9410, "estimated_cost_usd": 0.04, "cache_hits": 0 },
    "failures": [
      {
        "page": "https://www.example.com/pricing",
        "question": "How much does the Starter plan cost per month?",
        "reference_answer": "$19 per month",
        "outcomes": ["abstained", "abstained", "abstained"],
        "span_retrieved": false,
        "likely_cause": "content_not_in_crawler_view"
      }
    ]
  },
  "errors": [
    { "code": "FETCH_TIMEOUT", "severity": "warning", "message": "Timed out fetching /blog/old-post", "url": "https://www.example.com/blog/old-post" }
  ]
}
```

## 4. Field reference

### 4.1 `run`

| Field | Type | Notes |
|---|---|---|
| `id` | string | Unique run ID (ULID) |
| `started_at` | string | ISO 8601 UTC |
| `duration_ms` | integer | Total wall time |
| `checks_version` | string | Version of the check catalog / weights |
| `eval_version` | string \| null | Prompt/method version; `null` if no eval |
| `config` | object | Effective configuration (no secrets) |

### 4.2 `target`

| Field | Type | Notes |
|---|---|---|
| `url` | string | URL as provided |
| `final_url` | string | After redirects |
| `pages_audited` | integer | |
| `sitemap_found` | boolean | |

### 4.3 `score`

| Field | Type | Notes |
|---|---|---|
| `overall` | integer 0–100 | Weighted deterministic score. Derived **only** from scored checks; informational checks contribute 0 and cannot move it. |
| `max` | integer | Always 100 in schema 1.x |
| `categories` | object | Map of category → `{points, max}` for the **scored** categories only (`access`, `rendering`, `discovery` in v0.1). Skipped checks reduce `max`. Informational categories (`structure`, `structured_data`, `trust`, `site`) are **not** present here — their status is reported in `checks[]` with `weight: 0, points: 0`, and including them with a nonzero `max` would imply they affect the score. |

### 4.4 `checks[]`

| Field | Type | Notes |
|---|---|---|
| `id` | string | e.g. `REN-001`; stable |
| `category` | string | `access`, `rendering`, `structure`, `structured_data`, `discovery`, `trust` |
| `title` | string | Human-readable |
| `status` | enum | `pass`, `warn`, `fail`, `skip`, `error` |
| `weight` | number | Maximum points |
| `points` | number | Points awarded |
| `confidence` | enum | `high`, `medium`, `low` (e.g. `low` when rendering data is unavailable) |
| `message` | string | One-line summary |
| `evidence` | object | Check-specific; documented in CHECKS |
| `fix` | object \| null | `summary`, `docs_url`, `machine` (reserved for v0.3 machine-readable patches) |

### 4.5 `pages[]`

Light per-page summary for quick inspection. Full per-page data may be added in later minor versions.

### 4.6 `eval`

| Field | Type | Notes |
|---|---|---|
| `eval_version` | string | Method/prompt version |
| `confidence` | enum | `high` (facts or rendered ground truth), `low` (generated from crawler view only) |
| `ground_truth` | string | `facts`, `rendered`, `facts+rendered`, `crawler_only` |
| `answerer_model` / `judge_model` | string | LiteLLM-style identifiers |
| `trials` | integer | |
| `answerability` | object | `mean`, `per_trial_stddev`, `per_trial`, `ci95` (0–100). `per_trial_stddev` is variation **across trials**; `ci95` is sampling error **across questions**. These are different quantities and are never combined into one "stddev". |
| `context_recall` | number 0–1 | Fraction of questions whose source span was among the retrieved chunks. The primary diagnostic: separates extraction failures from writing failures. |
| `retrieval_gap` | number −1..1 | `context_recall − answerability/100`. The share of loss attributable to retrieval rather than to the answerer or the writing. |
| `retrieval` | object | `mode` (`chunked` \| `whole_page`), `top_k`, `chunk_target_tokens`, `chunk_overlap_pct`, `embedding_model`, `chunk_count`. Recorded so scores are comparable only within the same config. `mode: "whole_page"` means the page was too small to chunk and **the metric lost resolution** — consumers should treat the result as low-confidence. |
| `abstention_rate`, `hallucination_rate` | number 0–1 | |
| `coverage_loss` | number 0–1 | Questions answerable from ground truth but abstained or incorrect from the crawler view. `null` when no rendered ground truth is available. |
| `usage` | object | Tokens, estimated cost, cache hits |
| `failures[]` | array | Questions that failed in a majority of trials; `span_retrieved` says whether the source span made it into the context, and `likely_cause` is a heuristic enum: `content_not_in_crawler_view`, `content_ambiguous`, `answerer_error`, `unknown` |

### 4.7 `errors[]`

| Field | Type | Notes |
|---|---|---|
| `code` | string | Stable machine code |
| `severity` | enum | `warning`, `error` |
| `message` | string | |
| `url` | string \| null | |

## 5. Privacy of the report

- No API keys or environment variables appear in the output.
- `config` contains only effective audit settings.
- Reports contain URLs and extracted-text *metrics* by default, not full page text. A `--include-content` flag (not in v0.1) would be required to embed extracted text.
- Reports are written locally; nothing is uploaded.

## 6. Stability promises

For `schema_version` 1.x: field names and meanings above are stable; enum values may gain new members (consumers must handle unknown values); `evidence` shapes are documented per check and may gain fields.
