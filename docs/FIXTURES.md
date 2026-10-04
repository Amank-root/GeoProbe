# Fixture Sites for Calibration

Part of the [geoprobe PRD](PRD.md). Supporting the Milestone 0 exit criterion and the
Milestone 1 calibration run described in [ROADMAP](ROADMAP.md) and [CHECKS §9](CHECKS.md).

## Purpose

The catalog has **20 checks** — 6 scored (100 points) and 14 informational (0 points) — and
their thresholds are currently *provisional* values, not measured ones. Calibration means
running every check against sites whose correct answers are known by construction, and
measuring false positives and false negatives **per check**.

Two targets gate the v0.1 release ([ROADMAP](ROADMAP.md) Milestone 1):

- False-positive rate **< 5%** on known-good sites.
- Attention to low-weight checks: a weight-1 check that is always wrong is still noise in
  the report even though it barely moves the score.

## Why fixtures must be self-hosted, not scraped

A calibration set that points at live third-party sites is wrong for this project:

- It is **unreproducible**. Sites change, go down, or start blocking, so a calibration run
  cannot be re-run to verify a threshold change — and `CHECKS §9` requires re-running
  calibration whenever a check or weight changes.
- It is **unethical by our own rules**. [ADR-008](DECISIONS.md) commits to only sending test
  traffic to sites the user controls. A maintainer running the fixture suite against
  uninvolved third parties would break that.
- It cannot produce **known** expected outcomes. A labelled fixture needs a ground truth we
  control; a live site's correct answer is whatever it currently does.

So the set is **local, deterministic HTML fixtures plus optionally a handful of live sites
the maintainer owns**. Every fixture is a directory of saved HTML (and `robots.txt`,
`sitemap.xml`, headers) served locally, with a hand-labelled expectation file.

## Required coverage

Each row is a category that must exist in the set. `geoctl` fetches with a normal browser
user-agent plus each AI bot, so a fixture must be able to vary its response per user-agent
to exercise ACC-002.

| # | Category | What it must exercise | Primary checks |
|---|---|---|---|
| 1 | Static HTML, content-rich | Baseline: everything passes | all |
| 2 | Client-rendered SPA (empty shell + JS bundle) | The most common real defect | REN-001, ACC-002 |
| 3 | Hybrid / partial SSR | Ratio between 1 and 2 — the `warn` band | REN-001 |
| 4 | SSR (e.g. Next.js) | Content present in raw HTML | REN-001 |
| 5 | AI bot blocked by `robots.txt` `Disallow` | Deliberate policy vs. accident | ACC-001, ACC-003 |
| 6 | Bot blocked by WAF/UA cloaking (403 to named bots, 200 to browser) | Invisible to a robots.txt parse | ACC-002, ACC-003 |
| 7 | Bot challenge page returned with **200** | Status alone would read as success | ACC-003 |
| 8 | `robots.txt` with wildcards, `$`, `Allow` overrides | Edge-case parser behaviour | ACC-001 (see [ADR-013](DECISIONS.md)) |
| 9 | `robots.txt` missing (404) | Must **pass** as default-allow | ACC-001 |
| 10 | Sitemap index → child sitemaps | Multi-level sitemap handling | DIS-001 |
| 11 | Sitemap present but stale / URL errors | `warn` band | DIS-001 |
| 12 | Sitemap missing | `fail`, weight 1 | DIS-001 |
| 13 | Sitemap lists a `noindex` page | Real contradiction | DIS-002 |
| 14 | Clean JSON-LD: Organization, WebSite, Article | Correct-entity case | SD-001, SD-002 |
| 15 | JSON-LD malformed / unparseable | Lenient-parse path | SD-001 |
| 16 | No structured data at all | `fail` for SD-001/002 | SD-001, SD-002 |
| 17 | Complete heading hierarchy | `pass` case | STR-004, STR-005 |
| 18 | Skipped heading level (`h2` → `h4`), multiple H1s | `warn`/`fail` bands | STR-004, STR-005 |
| 19 | Boilerplate-heavy page (nav, cookie banner, footer) | Extraction quality | REN-002 |
| 20 | Multi-URL site (10+ pages) for crawl sampling | `--max-pages` behaviour | DIS-001, ACC-002 |
| 21 | Docs site | Persona from PRD §5 (DevRel owner) | eval, DIS-001 |
| 22 | E-commerce product page | Product role for JSON-LD | SD-002, eval |
| 23 | Blog with visible byline and dates | Trust signals | TRU-001, TRU-002 |
| 24 | HTTPS → HTTP redirect chain, or no HSTS | Transport sanity | SITE-001 |
| 25 | Content only in an iframe | Extraction edge case | REN-002 |
| 26 | Very small page (< 3 chunks) | Forces `retrieval.mode: "whole_page"` | eval (§3.3) |
| 27 | Large page, key facts buried deep | Retrieval discrimination | eval, EVALS §8 |
| 28 | Key facts in a client-rendered component | The case eval must catch | eval, REN-001 |

## Target shape

- **30–50 fixtures** across the 28 categories above; some rows need more than one instance
  (several distinct `robots.txt` edge cases, at least two SPAs, at least one
  WAF-protected pattern).
- **At least 40% must be known-good** — sites where every check should pass or warn — since
  the < 5% false-positive target is measured against those. A set of mostly-broken sites
  cannot measure false positives at all.
- **Every fixture carries a labelled expectation file**: expected status per check ID.
  Calibration compares actual vs. expected per check.
- Fixtures must be **tiny and deterministic** — a few KB of HTML each, no external assets,
  no network fetches, so the suite runs offline in CI. That also satisfies the ROADMAP exit
  criterion "no network or paid API use in CI".
- LLM-dependent eval fixtures additionally need **recorded cassettes** (see
  [ARCHITECTURE §12](ARCHITECTURE.md)) so eval behaviour is testable without a provider.

## Sourcing

- Categories 1–20 and 25–28 are synthesised locally: hand-written HTML reproducing the
  specific defect. Cheap, deterministic, and license-clean.
- Categories 21–23 (docs, e-commerce, blog) are best taken as **real archived pages** the
  maintainer has permission to store, saved with `wget`-style archival so a later change to
  the live site cannot alter calibration.
- Categories 5–7 (blocking, WAF, challenge) are the awkward ones: they need a server that
  varies its response by user-agent, which a static file cannot do. These become a small
  local test server with per-route rules — still offline, still deterministic.

## Status

Checklist drafted; fixtures not yet written. This document defines the target so fixture
work in Milestone 1 has a spec rather than starting from a blank directory.

Remaining decisions for whoever builds them:

- Where the expectation schema lives (proposed: `tests/fixtures/expected/*.yaml`)
- Whether the per-user-agent fixture server is pytest fixtures or a standalone module
- Which real pages to archive for categories 21–23