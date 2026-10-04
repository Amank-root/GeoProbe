# Decision Log (ADRs)

Part of the [geoprobe PRD](PRD.md). Working name; see PRD.

Format: **Status** (Proposed / Accepted / Open / Superseded), **Context**, **Decision**, **Consequences**. Add new ADRs at the bottom; never rewrite history, supersede instead.

---

## ADR-001: Implementation language is Python

**Status:** Proposed

**Context.** The core work is HTTP fetching, HTML extraction, structured-data parsing, and LLM evals. TypeScript would give `npx` distribution and closeness to Next.js repos, which matter for the v0.3 fix agent.

**Decision.** Python 3.10+, distributed via PyPI and runnable with `uvx` / `pipx`.

**Consequences.**
- Strongest ecosystem for extraction (trafilatura), LLM access (LiteLLM), and agent frameworks (LangGraph).
- One-line install is available via `uvx`, comparable to `npx`.
- The fix agent inspects JS/TS projects as plain files; it does not need to run in Node.
- Revisit only if the fix agent needs deep AST tooling that is much better in the JS ecosystem (then consider a small Node helper, not a rewrite).

---

## ADR-002: Bring-your-own keys via an LLM abstraction layer

**Status:** Proposed

**Context.** The eval needs many LLM calls. The project should not carry usage costs, and users should choose their provider (including local models).

**Decision.** Use LiteLLM as the abstraction. API keys come from environment variables or the OS keyring. The project operates no proxy in the OSS CLI.

**Consequences.**
- Zero marginal cost to maintainers; users control spend (`--dry-run`, `--max-cost`).
- Dependency on LiteLLM's provider coverage and cost data accuracy; verify in Milestone 0.
- The wrapper must isolate LiteLLM so it can be replaced.
- Never write keys to config files, reports, logs, or telemetry.

---

## ADR-003: Deterministic checks and LLM eval are separate layers with separate scores

**Status:** Proposed

**Context.** Blending a rule-based score and an LLM-based score hides which moved and makes the number hard to interpret. The deterministic layer must work without keys.

**Decision.** Report a deterministic score (0–100) and an answerability score (0–100 with variance) side by side. Do not blend them.

**Consequences.**
- Users can gate CI on either (`--fail-under`, `--fail-under-eval`).
- Slightly more complex report, but clearer meaning.
- Easier to calibrate and test each layer independently.

---

## ADR-004: License

**Status:** Open

**Context.** The planned business model is open-core with a hosted tier selling recurring monitoring, alerts, and team features. A permissive license lets anyone host the code commercially; a strong copyleft license (AGPL) deters that but reduces adoption by some companies and contributors.

**Options.**

| Option | Pros | Cons |
|---|---|---|
| Apache-2.0 | Maximum adoption; patent grant; easy for CI/Action use | Competitors may host it |
| MIT | Simplest, most familiar | No patent grant; same hosting risk |
| AGPL-3.0 | Discourages closed hosted forks | Many companies avoid AGPL; can limit contributions and Action adoption |
| Source-available (e.g. BSL/FSL) | Protects against hosted competitors | Not "open source" by OSI definition; may reduce community trust |

**Leaning.** Apache-2.0 for the CLI, on the reasoning that the hosted tier's value is recurring infrastructure and history rather than the engine, and that adoption (especially CI usage) matters most early. This is **not final**; decide in Milestone 0 and record the reasoning.

**Consequences (if Apache-2.0).**
- Add a contributor policy (DCO or CLA decision; DCO is lighter).
- The hosted tier must not rely on the engine being exclusive; differentiate on service features.
- Trademark the name separately from the code license if the name matters commercially.

---

## ADR-005: Telemetry is opt-in, allow-list only

**Status:** Proposed

**Context.** A tool that crawls sites and may read repos is sensitive. Early-project trust is more valuable than the extra data opt-out would give.

**Decision.** Opt-in with a default-No prompt on interactive first run; off in CI and non-interactive contexts unless explicitly enabled; `DO_NOT_TRACK` always honored; allow-listed payload fields only; no URLs or content, ever. Full policy in [TELEMETRY](TELEMETRY.md).

**Consequences.**
- Lower event volume; rely on PyPI / GitHub signals as supplements.
- Simple, defensible privacy story.
- Changing to opt-out later would require announcement and a major version bump.

---

## ADR-006: Crawler view is a no-JS fetch; JS rendering is optional

**Status:** Proposed

**Context.** Many AI crawlers do not execute JavaScript, and the most common readability failure is content that only exists after JS runs. Playwright adds a heavy dependency.

**Decision.** The default "crawler view" is a no-JS HTTP fetch plus main-content extraction. Playwright is an optional extra used only to build the rendered view for comparison and ground truth.

**Consequences.**
- Default install stays light and fast.
- Without `--render`, the no-JS ratio check uses heuristics and reports lower confidence.
- Documentation must state that the crawler view approximates real crawlers and that behavior varies by bot.

---

## ADR-007: Open-core boundary principles

**Status:** Proposed

**Context.** Users and contributors lose trust when free features are later paywalled or when the free version is deliberately limited.

**Decision.**
1. The OSS CLI is fully capable for single-run, local use: audit, eval, generate, and (when built) fix.
2. Paid offerings are things that require a service: scheduling, persistent history, alerts, multi-site/team workspaces, managed keys/query sets.
3. A feature released in OSS is never moved to paid. Moving paid → OSS is allowed.
4. The boundary and the "won't do" list are published in the README from the first release.

**Consequences.**
- Some feature requests (e.g. a built-in scheduler) will be declined or redirected; say so publicly.
- Contributions that overlap hosted-tier territory need a documented policy (default: accept if useful standalone and local).
- Keeps the commercial path honest and the community trust intact.

---

## ADR-008: Simulated bot requests are honest and rate-limited

**Status:** Proposed

**Context.** Fetching with AI-bot user-agents is necessary to detect user-agent-based blocking, but could be misused against third-party sites or look like evasion.

**Decision.** Simulated-bot requests include an `X-Geoprobe-Test: 1` header; default concurrency is low with per-host delay; documentation states the tool is intended for sites the user owns or has permission to test; the tool does not rotate IPs, evade challenges, or solve CAPTCHAs.

**Consequences.**
- Some WAFs may treat spoofed UAs as hostile; the check reports what happens rather than working around it.
- A clear acceptable-use statement in README and docs.

---

## ADR-009: Score weights are provisional until calibrated

**Status:** Proposed

**Context.** There is limited public evidence for how much each signal affects real AI systems. Presenting weights as authoritative would be misleading.

**Decision.** Ship v0.1 weights as provisional, calibrated on a labeled fixture set for false-positive/negative behavior (not for "what AI rewards"). Version the check catalog (`checks_version`), note weight changes in the changelog, and report `llms.txt` (`DIS-003`) as an **informational** check with weight 0 — it earns points by being AI-crawler-specific, and current evidence says it is not (see ADR-010 and CHECKS §7).

**Consequences.**
- Scores can change between versions; reports include `checks_version`.
- README explains that the score is a readiness indicator, not a ranking predictor.
- Future measured evidence (Milestone 4 benchmark) may justify reweighting.

---

## ADR-010: The check catalog is narrow and mostly unscored

**Status:** Proposed

**Context.** The GEO/AEO category already contains roughly a dozen open-source tools that
check for the presence of artifacts — `robots.txt` rules, `llms.txt`, JSON-LD, sitemaps,
heading structure — and roll them into a 0–100 score. They do it well. Several of the
signals this project originally planned to score are also not specific to AI crawlers at
all: heading hierarchy, meta descriptions, Open Graph, HTTPS/HSTS, and publish dates are
reported by Lighthouse, axe-core, and every commercial checker.

Scoring those signals would put `geoprobe` in direct competition with better-resourced
tools on their strongest ground, and would produce a number that looks authoritative while
encoding opinions the project cannot justify with evidence. It would also consume the
engineering effort that the differentiating feature needs.

**Decision.** Ship a deliberately narrow catalog in two tiers:

- **6 scored checks (100 points)** — signals specific to how AI crawlers fetch and read a
  page: bot-vs-browser fetch parity (`ACC-002`, 30), `robots.txt` rules per AI bot
  (`ACC-001`, 25), blocking status or challenge pages (`ACC-003`, 20), text available
  without JavaScript (`REN-001`, 20), main content extractable (`REN-002`, 4), sitemap
  present and valid (`DIS-001`, 1).
- **14 informational checks (0 points)** — standard SEO and site-quality hygiene, reported
  with status, evidence, and a fix hint, but never moving the score. They use
  `weight: 0, points: 0` in JSON.

The default for any new check is **informational**. A check earns scored status by being
specific to AI crawler access *and* by discriminating between sites that real crawlers can
and cannot use. Breadth is not a qualification. See CHECKS.md §2–§3 and §8.

**Consequences.**
- The score is small enough to be explainable: every point traces to a signal observed by
  fetching the site, not to a style opinion.
- The report loses "completeness" relative to broad audit tools. This is intentional and
  must be stated plainly in the README, along with the recommendation to run Lighthouse in
  the same CI step for the hygiene tier.
- Informational checks still need pass/warn/fail criteria and fixtures; they are not free
  work, they are simply unweighted.
- Calibration (`CHECKS.md §9`) concentrates on the 6 scored checks, with attention to the
  low-weight ones — a weight-1 check that is always wrong is still noise in the report.
- If users ask for hygiene checks to be scored, that is an explicit scope change, not a
  default; it would need its own ADR.

---

## ADR-011: The crawler view is a retrieval simulation, not a whole-page prompt

**Status:** Proposed

**Context.** The answerability eval is the project's differentiator, and its result is only
meaningful if it measures the *site* rather than the *model*. Handing a frontier model the
entire cleaned page and asking it questions measures whether the model is smart: a pricing
table buried in the middle of a long page and the same table placed first are equally
available to any model given the whole document. But inside a real retrieval stack they
behave nothing alike, and that difference — retrieving the right span — is the actual
failure mode for AI answers.

The failure mode this project actually needs to detect is content that never reaches the
answerer: text that exists only after JavaScript runs, sits outside the extracted main
content, or is phrased so vaguely that the retriever cannot match it to a question.

**Decision.** The answerer sees **only** top-k retrieved chunks of the no-JS crawler view
— never the whole page. The pipeline is `chunk → embed → retrieve top-k → answer`, with
questions and reference answers drawn from an independent ground truth (a user-supplied
`facts.yaml`, and/or JS-rendered text). Chunking parameters, embedding model, and `k` are
recorded in the report. When a page is too small for chunking to be meaningful (under
`retrieval.min_chunks`, default 3), the eval falls back to whole-page context and reports
`retrieval.mode: "whole_page"` explicitly, because that is the case where the metric loses
its resolution.

**Context recall** — the fraction of questions whose source span was among the retrieved
chunks — is reported alongside answerability, separately. This is the diagnostic that
makes the score actionable: low recall with decent answerability means an extraction problem
(usually client-side rendering), while high recall with low answerability means the content
is retrievable but badly written for extraction. Without the split, users chase the wrong
problem.

**Consequences.**
- The eval is deliberately harsher than whole-page context, which is the point: it is
  stable run to run and it discriminates between sites.
- It remains an **approximation**. Real vendors differ in chunking, embedding, top-k,
  reranking, and JS handling, and no local tool can match any of them exactly. The
  defensible claim is that the eval is harsher than whole-page context and stable — not
  that it reproduces any vendor's pipeline.
- Retrieval-based numbers are sensitive to chunk size, `k`, and the embedding model. Scores
  are comparable only within the same `eval_version` and retrieval config, and the tool
  warns when comparing across them.
- Small pages degrade to whole-page context and lose resolution; the report must say when
  that happened rather than presenting a confident number.
- Requires an embedding step (`evals/retrieval.py`), which is one cheap batch call per page
  and is included in `--dry-run` estimates.

---

## ADR-012: The eval is on by default when a key is present

**Status:** Proposed

**Context.** Two defensible defaults pull in opposite directions. Making `--eval` opt-in
(`--eval` to enable) protects users from surprise LLM spend and keeps the first run fast
and deterministic. Making it the default path showcases the project's differentiator, which
is otherwise invisible in the common no-key case and easy to forget exists.

The deciding factor is that the deterministic layer alone cannot answer the question users
actually have. Artifact checks are proxies; a site can score 100 and still be unanswerable.
If the eval is buried behind a flag, most users will never see the part of the tool that
distinguishes it — and the risk is highest for exactly the users who provided a key, having
already accepted the cost.

**Decision.** `--eval` defaults to **`auto`**: the eval runs when an LLM key is present in
the environment (or keyring) and is skipped with a one-line note when none is found. Users
can force either way with `--eval` or `--no-eval`. Non-interactive contexts follow the same
rule — the presence of a key is the signal, not the TTY.

**Consequences.**
- A user who has exported a key gets the headline metric without asking for it, so the
  first-run experience matches the project's positioning.
- Cost is bounded and disclosed: `--dry-run` estimates tokens and cost without any call,
  `--max-cost` aborts before exceeding a limit, and the report always shows tokens used
  and estimated cost. Defaults (50 questions × 3 pages × 3 trials) are sized to be a small
  fraction of a cent, and `--dry-run` exists precisely so nobody discovers spend by
  accident.
- The deterministic layer remains fully usable with zero keys, and is the secondary,
  always-free layer. This does not weaken goal G2 (useful with no API key).
- When no key is found, the skip must be stated explicitly in the report — a silently
  absent eval section reads as a broken feature.
- `--fail-under-eval` will not gate CI on a low-confidence run (crawler-only ground truth,
  or a CI wider than `--fail-under-eval-margin`); it warns and exits 0 unless
  `--strict-eval` is passed. See EVALS §4.2.
