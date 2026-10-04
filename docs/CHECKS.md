# Check Catalog

Part of the [geoprobe PRD](PRD.md). Working name; see PRD.

This is the v0.1 catalog. Two tiers:

- **Scored checks** (6 of them, 100 points) — signals specific to how AI crawlers fetch
  and read a page. These produce the deterministic score.
- **Informational checks** (14) — general SEO/site-quality hygiene. Reported with status,
  evidence, and a fix hint, but contributing **0 points**. They do not move the score.

The split is deliberate and is the main scoping decision in this project. See
[ADR-010](DECISIONS.md). Roughly a dozen open-source tools already ship broad artifact
checkers well — including per-crawler robots verdicts, no-JS vs rendered comparison, and
CI baselines. Competing with them on breadth means shipping a worse version of their
product. We ship the small set of checks genuinely specific to AI crawler access, and put
the differentiating effort into the [answerability eval](EVALS.md).

Weights are **initial values to be calibrated** against a labeled fixture set; treat them
as a starting point, not a claim about what any AI product rewards.

## 1. Conventions

- **Status:** `pass`, `warn`, `fail`, `skip` (not applicable or prerequisite missing),
  `error` (the check itself failed).
- **Score:** a fraction of the check's weight (`pass` = 1.0, `warn` = typically 0.5,
  `fail` = 0.0). Skips are excluded from the denominator.
- **Evidence:** every result includes the measured values and URLs behind it.
- **Fix:** every `warn`/`fail` includes a short, concrete fix hint; later versions attach
  machine-readable fixes for the fix agent.
- **Policy-aware:** a deliberate block of an AI bot is not automatically a failure. See
  `--policy` in [CLI_SPEC](CLI_SPEC.md).
- **Informational checks** report `status`, `evidence`, and `fix`, and always
  `points: 0`, `weight: 0`.

## 2. Scored checks — summary

| ID | Category | Check | Weight |
|---|---|---|---|
| ACC-002 | Access | Bot vs browser fetch parity | 30 |
| ACC-001 | Access | robots.txt rules per AI bot | 25 |
| ACC-003 | Access | No blocking status or challenge page | 20 |
| REN-001 | Rendering | Text available without JavaScript | 20 |
| REN-002 | Rendering | Main content extractable | 4 |
| DIS-001 | Discovery | Sitemap present and valid | 1 |
| | | **Total** | **100** |

Why these weights: parity is weighted highest because it is the only check that observes
what a crawler *actually receives* rather than what the site *declares*. robots.txt is
next, because it is the one control surface AI crawler operators document and honor.
`DIS-001` sits at 1 because a missing sitemap is near-universal among real sites and
carries almost no discriminative signal. It is scored rather than informational because a
valid sitemap is the cheapest way to enumerate pages for the crawl and the eval's sampling
(`FR-5`), so its absence has a concrete downstream cost — not because its absence needs to
be visible in the report, which §3 gives every check regardless of tier.

## 3. Informational checks — summary

Reported, never scored. Grouped for display under `hygiene` in the terminal report and
present in `checks[]` with `weight: 0` in JSON.

| ID | Group | Check |
|---|---|---|
| STR-001 | Structure | Title present and specific |
| STR-002 | Structure | Meta description present |
| STR-003 | Structure | Canonical URL |
| STR-004 | Structure | Exactly one H1 |
| STR-005 | Structure | Heading hierarchy |
| STR-006 | Structure | `lang` attribute |
| SD-001 | Structured data | JSON-LD present and parses |
| SD-002 | Structured data | Appropriate entity types |
| SD-003 | Structured data | Open Graph basics |
| DIS-002 | Discovery | Indexing / snippet directives |
| DIS-003 | Discovery | llms.txt presence and shape |
| TRU-001 | Trust | Publish / modified dates |
| TRU-002 | Trust | Author or organization identified |
| SITE-001 | Site | HTTPS, HSTS, redirect chain sanity |

Pass/warn/fail criteria for each are given below, in this document. Per-check detail and
fixtures live alongside the implementation in `src/geoprobe/checks/` and
`tests/fixtures/checks/`. Rationale for informational status, by group:

- **Structure / Structured data / Trust:** standard SEO hygiene. Real value, but
  Lighthouse, axe-core, and every commercial checker already report them, and none is
  specific to AI crawlers. A user who wants them scored should run Lighthouse in the same
  CI step. `geoprobe` prints them so there is one place to look, and explicitly declines
  to have a weighted opinion about them.
- **DIS-002** (indexing directives): a `noindex` on a page in the sitemap is a real
  contradiction worth surfacing loudly, but it is a contradiction about search indexing,
  not about AI retrieval.
- **DIS-003** (`llms.txt`): see §7. The reason is stronger than "we could not find a good
  signal" — current public evidence says crawlers essentially never fetch it.
- **SITE-001:** transport-level basics, added because HTTPS and HSTS are table stakes for
  any crawler and cost one check to verify.

### 3.1 Structure

**STR-001: Title present and specific**
- **Pass:** Non-empty `<title>`, 10–70 characters, and not a bare domain name or
  `Home | <brand>`-style placeholder on a non-home page.
- **Warn:** Present but outside 10–70 characters, or duplicated verbatim across sampled
  pages.
- **Fail:** Missing or empty.
- **Evidence:** title text, length, per-page, plus duplicate-title grouping.
- **Note:** Titles are frequently truncated in AI answers and used as the citation label,
  so a vague title measurably weakens how a page is surfaced.

**STR-002: Meta description present**
- **Pass:** Non-empty `<meta name="description">` of 50–160 characters on every sampled page.
- **Warn:** Missing on some sampled pages, or present but outside the length range.
- **Fail:** Missing on all sampled pages.
- **Evidence:** description text and length per page.

**STR-003: Canonical URL**
- **Pass:** Exactly one `<link rel="canonical">` per page, absolute, and self-referencing.
- **Warn:** Present but relative, non-self-referencing, or multiple canonical tags.
- **Fail:** Absent.
- **Evidence:** declared canonical vs final URL after redirects.
- **Note:** A canonical pointing elsewhere is a redirect signal a crawler will honour, so
  it is reported as evidence even when it is not an error.

**STR-004: Exactly one H1**
- **Pass:** Exactly one `<h1>`, non-empty.
- **Warn:** Multiple H1s, or an H1 that is empty.
- **Fail:** No H1.
- **Evidence:** H1 count and texts per page.
- **Note:** The H1 is the strongest single signal of what a page is about and is commonly
  used as a retrieval anchor.

**STR-005: Heading hierarchy**
- **Pass:** No level is skipped (e.g. `h2 → h4`), exactly one H1, and no empty headings.
- **Warn:** One skipped level, or a single empty heading.
- **Fail:** Multiple H1s combined with skipped levels, or headings absent entirely.
- **Evidence:** heading outline per page with the flagged transitions.
- **Note:** Heading structure is what chunking splits on, so a broken hierarchy directly
  degrades retrieval.

**STR-006: `lang` attribute**
- **Pass:** `<html lang="...">` present and a syntactically valid BCP-47 tag.
- **Warn:** Present but malformed or an unusual tag (e.g. `en_US` with an underscore).
- **Fail:** Absent.
- **Evidence:** raw attribute value.

### 3.2 Structured data

**SD-001: JSON-LD present and parses**
- **Pass:** At least one `<script type="application/ld+json">` block parses as valid JSON.
- **Warn:** Blocks present but none parse (strict mode off), or JSON parses but contains no
  recognized `@type`.
- **Fail:** No JSON-LD blocks.
- **Evidence:** block count, parse errors, per-block `@type`.
- **Note:** Parsing is lenient (duplicate keys tolerated) to match how real crawlers
  behave; strict validation is out of scope for v0.1.

**SD-002: Appropriate entity types**
- **Pass:** JSON-LD includes at least one type matching the page's role (home →
  `Organization` and/or `WebSite`; article → `Article`; product → `Product`; FAQ →
  `FAQPage`).
- **Warn:** JSON-LD present but types do not match the inferred page role.
- **Fail:** No JSON-LD, or `Organization` missing on the home page.
- **Evidence:** detected types, inferred page role, missing expected types.

**SD-003: Open Graph basics**
- **Pass:** `og:title` and `og:description` present; `og:url` and `og:image` present on the
  home page.
- **Warn:** `og:title` present but `og:description` missing, or `og:image` missing on a
  non-home page.
- **Fail:** No Open Graph tags.
- **Evidence:** tags found with their content values.

### 3.3 Discovery

**DIS-002: Indexing / snippet directives**
- **Pass:** No conflicting directives on sampled pages.
- **Warn:** `noindex` or `nosnippet` present on a page that is also listed in the sitemap.
- **Fail:** `noindex` on the start URL.
- **Evidence:** per-page meta robots directives, sitemap membership, the contradiction
  called out explicitly.
- **Note:** Informational because it is a contradiction about *search* indexing. Reported
  loudly because it silently defeats the site's own crawl strategy.

**DIS-003: `llms.txt` presence and shape**
- **Pass:** `/llms.txt` returns 200 with an H1, a non-empty summary, and at least one link
  section.
- **Warn:** Present but malformed (no H1, no links, or non-markdown content).
- **Fail:** Not present.
- **Evidence:** status, content type, detected structure.
- **Note:** Never scored and never penalized — see §7 for why. **Fail is not a penalty;
  it means the file is absent, which for this check is the expected and acceptable state.**

### 3.4 Trust

**TRU-001: Publish / modified dates**
- **Pass:** At least one machine-readable date (`article:published_time`,
  `datePublished`, JSON-LD `datePublished`, or `<time datetime>`) on every sampled page.
- **Warn:** Dates present only in human-readable form, or missing on some pages.
- **Fail:** No dates found on the start URL.
- **Evidence:** raw values, the attribute they came from, and parse failures.
- **Note:** Unparseable or obviously bogus dates (epoch 0, dates in 1970, `lastmod` in the
  future) count as failures and are flagged, since stale `lastmod` is a common sitemap
  defect.

**TRU-002: Author or organization identified**
- **Pass:** A named author or organization is identifiable, via JSON-LD (`author`,
  `publisher`), meta tags, or visible byline markup.
- **Warn:** Organization named but no author on content pages.
- **Fail:** No author or organization signal.
- **Evidence:** the source that identified it, and the extracted value.

### 3.5 Site

**SITE-001: HTTPS, HSTS, redirect chain sanity**
- **Pass:** Final URL is HTTPS, `Strict-Transport-Security` is present, and the redirect
  chain to the final URL is at most one hop with no redirect loops.
- **Warn:** HTTPS with no HSTS, or a chain of two or more hops.
- **Fail:** Start URL is not served over HTTPS, or the redirect chain errors or loops.
- **Evidence:** redirect chain with per-hop status and location, HSTS header value and
  `max-age`.
- **Note:** Scored as informational because HTTPS is table stakes for any crawler; this
  check confirms it rather than distinguishing sites.

## 4. Access

### ACC-002: Bot vs browser fetch parity (30)

- **What:** Fetch each sampled page as `browser` and as each simulated AI bot. Compare
  status code, response size ratio, and extracted-text similarity.
- **Pass:** Same status and text similarity ≥ 0.9 for all bots on all pages.
- **Warn:** Similarity 0.6–0.9, or a status difference on a minority of pages.
- **Fail:** A bot receives an error status, an empty body, or substantially different
  content than the browser on a majority of pages.
- **Evidence:** per-bot status, size ratio, and text similarity per page.
- **Notes:** Catches WAF/CDN rules and user-agent cloaking, which a robots.txt parse
  cannot see. Simulated requests send `X-Geoprobe-Test: 1`. This is the most valuable
  thing the deterministic layer does, which is why it carries the largest weight.

### ACC-001: robots.txt rules per AI bot (25)

- **What:** Parse `robots.txt` and evaluate the start URL for each configured bot token
  (e.g. GPTBot, OAI-SearchBot, ChatGPT-User, ClaudeBot, PerplexityBot, Google-Extended,
  CCBot).
- **Pass:** All configured bots allowed, or blocked deliberately under
  `--policy report|ignore`.
- **Warn:** Some bots allowed and some blocked, or rules ambiguous.
- **Fail:** Start URL blocked for bots the config says should be allowed, or a wildcard
  `Disallow: /` unintentionally catching them.
- **Missing robots.txt (404):** pass (default allow), noted in evidence.
- **Evidence:** matched rule line per bot, per-bot verdict (`allowed`, `blocked`,
  `partial`, `unmentioned`).
- **Notes:** Bot purposes differ (training vs search vs user-triggered). Verdict tables are
  reported grouped by purpose, because blocking training bots while allowing search bots
  is a legitimate and common policy — published surveys put roughly a fifth of top sites
  blocking at least one major AI bot.

### ACC-003: No blocking status or challenge page (20)

- **What:** Detect 401/403/429/5xx for any lens, and bot-challenge or interstitial pages
  returned with 200.
- **Pass:** No such responses.
- **Warn:** Intermittent (some pages, or only on retry).
- **Fail:** Start URL or a majority of sampled pages blocked or challenged.
- **Evidence:** status, matched challenge marker, response headers of interest.

## 5. Rendering

### REN-001: Text available without JavaScript (20)

- **What:** Ratio of main-content text characters in the no-JS fetch to those in the
  JS-rendered fetch (needs `--render`). Without rendering, fall back to absolute
  thresholds and shell heuristics (empty app shell, `<noscript>` warnings, tiny body with
  a large script payload).
- **Pass:** Ratio ≥ 0.8, or no-JS main text above threshold when render is unavailable and
  no shell markers are present.
- **Warn:** 0.4–0.8, or shell markers present without render data (marked low confidence).
- **Fail:** < 0.4, or essentially empty main content with only a framework root element.
- **Evidence:** char counts per page, detected framework markers, confidence level.
- **Notes:** Most AI retrieval crawlers do not execute JavaScript. In practice this is the
  most common real defect, and the one that most lowers the answerability eval. It carries
  weight accordingly.

### REN-002: Main content extractable (4)

- **What:** Extraction yields substantive main content rather than mostly navigation,
  cookie banners, or boilerplate.
- **Pass:** Main text ≥ 300 chars and a plausible content-to-boilerplate ratio.
- **Warn:** 100–300 chars, or high boilerplate share.
- **Fail:** < 100 chars on pages expected to have content.
- **Evidence:** extracted length, extractor confidence if available, boilerplate share.
- **Notes:** Low weight on purpose. Whole-page extraction quality is not the bottleneck for
  AI answers — retrieval over that extraction is, and the eval measures that directly as
  context recall. This check stays as a cheap guard against total extraction failure.

## 6. Discovery

### DIS-001: Sitemap present and valid (1)

- **What:** Sitemap found via robots.txt `Sitemap:` or `/sitemap.xml`, parses, URLs on the
  same origin, and includes the start URL.
- **Pass:** Found, valid, includes the start URL.
- **Warn:** Found but with errors, stale-looking `lastmod`, or sampled URLs erroring.
- **Fail:** Not found.
- **Evidence:** sitemap URL(s), URL count, parse errors, start-URL membership.
- **Notes:** Weight 1 reflects low discriminative power — most real sites have one. Kept
  scored so its absence is visible, and because a valid sitemap is the cheapest way to
  enumerate pages for the eval's sampling.

## 7. `llms.txt` (DIS-003, informational)

- **What:** Whether `/llms.txt` exists and is structurally well-formed (H1, summary,
  sections of links).
- **Reported as:** informational, 0 points, always visible in the report.
- **Reasoning:** `llms.txt` is an emerging community proposal. No major AI platform has
  documented consuming it from third-party sites; their crawler docs name `robots.txt` as
  the control file. Large-scale published analyses of AI crawler traffic, and of the July
  2026 Common Crawl archive, find the file essentially never fetched in practice, and
  observational studies find no citation-rate difference for domains that publish one.
- **Consequence:** the report states this in plain language rather than implying the file
  is required, and the tool does **not** penalize its absence. `geoprobe generate llms-txt`
  (v0.2) exists for users who want one anyway.

## 8. Adding or changing checks

1. Add a new ID; never reuse an ID for a different meaning.
2. State up front which tier a check belongs in and why. The default for a new check is
   **informational** — a check earns scored status by being specific to AI crawler access
   *and* by discriminating between sites that real crawlers can and cannot use. Breadth is
   not a reason to add a scored check.
3. Document pass/warn/fail criteria and evidence here **before** implementing.
4. Include fixture-based unit tests (positive, negative, edge).
5. Changing a weight or criterion is noted in the changelog because it changes scores
   across versions. Reports include `checks_version`.

## 9. Calibration plan

Before v0.1 release:

- Assemble 30–50 fixture sites (static, SPA, SSR, docs, blog, e-commerce,
  WAF-protected) with hand-labeled expected outcomes.
- Measure false-positive and false-negative rates **per check**, with particular attention
  to the low-weight ones — a weight-1 check that is always wrong is still noise in the
  report even though it barely moves the score.
- Adjust thresholds and weights; record the rationale in [DECISIONS](DECISIONS.md).
- Re-run calibration whenever a check or weight changes.
