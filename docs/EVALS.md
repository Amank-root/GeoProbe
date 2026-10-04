# Answerability Eval

Part of the [geoprobe PRD](PRD.md). Working name; see PRD.

## 1. What it measures

> If an assistant is given **only what a retrieval pipeline could plausibly pull from your
> page** — the crawler view, chunked, embedded, and top-k retrieved — how often can it
> correctly answer questions a real user would ask about your site?

It measures **retrievability and readability for language models**. It does **not** measure
whether ChatGPT, Perplexity, Google, or any specific product will cite or recommend your
site. Those depend on retrieval, ranking, and vendor policy the tool cannot observe.
Reports and docs must say this plainly.

This is the project's differentiator. See [ADR-010](DECISIONS.md) for why the check
catalog was narrowed to make room for it.

## 2. Why a separate eval

Artifact checks (robots.txt, schema, headings) are proxies. They report whether signals are
present, not whether the content is usable. The eval tests the outcome directly: can the
information be recovered from what a crawler actually gets?

Whole-page context is **not** the test. Handing a frontier model the entire cleaned page
measures whether the model is smart, not whether your site is retrievable. A pricing table
buried in the middle of a long page and one placed first are equally available to a model
given the whole document, yet they behave nothing alike inside a real retrieval stack. So
the eval retrieves, it does not paste. See §3.3 and
[ADR-011](DECISIONS.md#adr-011-the-crawler-view-is-a-retrieval-simulation-not-a-whole-page-prompt).

## 3. Method

```
ground truth ──► questions + reference answers + source spans
                         │
crawler view ──► chunk ──► embed ──► retrieve top-k ──► context
                                                          │
                              answerer (sees ONLY context) ──► candidate answers
                                                          │
                                       judge (vs reference) ──► verdicts
                                                          │
                              aggregate over N trials ──► score ± CI
```

### 3.1 Views

| View | Definition | Used for |
|---|---|---|
| **Crawler view** | No-JS HTTP fetch, main-content extraction to markdown (optionally per-bot) | The corpus that gets chunked, embedded, and retrieved |
| **Ground truth** | (a) user-supplied `facts.yaml`, and/or (b) JS-rendered text from Playwright (`--render`) | Where questions, reference answers, and source spans come from |

**Avoiding circularity.** If questions were generated from the crawler view and answered
from the crawler view, nearly every question would be answerable and the score would say
nothing. Questions must come from a **richer or independent source** than what the answerer
sees:

- With `facts.yaml`: questions and answers are the user's own facts. Strongest signal.
- With rendering: questions come from rendered text; the answerer only ever sees no-JS
  text that survived chunking and retrieval. Score reflects content lost to
  client-side rendering.
- With neither: the tool falls back to generating questions from the crawler view and
  **labels the result low-confidence** — it tests clarity, not loss, and must not be used
  to gate CI (see §4.2).

### 3.2 Question generation

- The generator asks for questions a real visitor or an AI-assistant user would plausibly
  ask, covering a mix of types: factual lookup (prices, dates, names), definitional
  ("what does X do"), procedural ("how do I..."), and comparison.
- Each question carries a **reference answer** and a **source span** from the ground
  truth. The span is what makes context recall measurable (§3.6).
- Questions are deduplicated and filtered for answerability *against ground truth* — a
  question the ground truth itself cannot answer is discarded.
- Generation runs **once** per page and is cached; trials reuse the same question set so
  variance reflects the answerer, not the questions.

### 3.3 Retrieval (the important part)

This is the stage that makes the eval discriminative. Implemented in
`evals/retrieval.py`.

1. **Chunk** the crawler-view markdown into overlapping passages. Defaults: target ~400
   tokens, ~10% overlap, split on heading and paragraph boundaries, never mid-sentence
   where avoidable. Chunking parameters are recorded in the report.
2. **Embed** chunks with the configured embedding model (default: the answerer
   provider's small embedding model). Recorded in the report.
3. **Retrieve** top-k by cosine similarity to the question (**k** default 5). `k` is a
   flag (`--top-k`) and is recorded.
4. **Fallback:** if the target site is too small for chunking to mean anything (under
   `retrieval.min_chunks`, default 3 chunks), the eval **skips retrieval** and passes the
   whole page, recording `retrieval.mode: "whole_page"`. This is reported explicitly,
   because it is the case where the metric loses its resolution.

Chunking and embedding models are approximations of any given vendor's pipeline, and no
local tool can match them exactly. What matters is that the eval is *harsher* than
whole-page context and *stable* run to run — a property we can verify and a user can rely
on. §7 and [ADR-011](DECISIONS.md) record this honestly.

**Cost note:** embedding is one cheap batch call per page. `--dry-run` includes it. Only
the answering step scales with questions × trials.

### 3.4 Answering

- The answerer receives the question and **only the retrieved context**, with instructions
  to answer strictly from that context and reply `NOT_FOUND` if the answer is absent.
- Abstention is a valid, measured outcome, distinct from a wrong answer. It is the signal
  that most often turns out to be the useful one.
- Temperature 0 by default; seed passed where the provider supports it.

### 3.5 Judging

- The judge compares the candidate answer to the reference answer and returns one of:
  - `correct`
  - `partially_correct`
  - `incorrect` (wrong information; counts toward hallucination rate)
  - `abstained` (said not found)
- A different model family from the answerer is recommended, to reduce self-preference
  bias.
- Judge output is structured JSON with a short rationale, validated by Pydantic.

### 3.6 Aggregation

Per page and overall:

| Metric | Definition |
|---|---|
| **Answerability** | (correct + 0.5 × partial) / total questions, scaled to 0–100 |
| **Context recall** | fraction of questions where the source span was among the retrieved chunks |
| **Retrieval gap** | context_recall − answerability/100 — the part of the loss caused by retrieval rather than by the answerer or the writing |
| **Abstention rate** | abstained / total |
| **Hallucination rate** | incorrect / total |
| **Coverage loss** (if rendered) | questions answerable from ground truth but abstained/incorrect from the crawler view |
| **Standard error** | binomial SE of the mean across questions, ±95% CI on the mean |

**Context recall is the diagnostic that justifies the whole design.** A question can fail
because the span was never retrieved (fix your extraction or chunking) or because it was
retrieved and the model still got it wrong (fix your writing). Without the split, users
chase the wrong problem. With it, the tool tells them which one they have:

- Low recall, decent answerability → extraction problem. Usually client-side rendering;
  see [REN-001](CHECKS.md#ren-001-text-available-without-javascript-20).
- High recall, low answerability → the content is retrievable but badly written for
  extraction: buried, ambiguous, unspecific, or contradicted elsewhere on the page.

The report highlights *which questions failed*, whether their span was retrieved, and what
was missing from the crawler view. That list is the actionable output.

## 4. Reproducibility, noise, and resolution

### 4.1 Controls

- Fixed model, parameters, prompts, chunking parameters, and prompt version, all recorded
  in the report.
- Default **3 trials**; the report shows the mean with a 95% confidence interval.
  Single-trial results are flagged unreliable.
- Disk cache keyed by `(model, params, prompt hash, input hash)`, so identical re-runs
  return identical results at zero cost.
- Prompt templates and the retrieval configuration are versioned (`eval_version`);
  comparing scores across `eval_version` values is discouraged and the tool warns.
- Do not compare scores across different models. A score is meaningful relative to its own
  model and prior runs.

### 4.2 Resolution: why the default is 50 questions, not 10

Sampling noise dominates at small question counts. At a true rate of 0.6, the binomial
standard error is roughly:

| Questions per page | Standard error | Approx. 95% CI on the mean |
|---|---|---|
| 10 | 0.155 | ± 15 points |
| 25 | 0.098 | ± 10 points |
| **50** | **0.069** | **± 7 points** |
| 100 | 0.049 | ± 5 points |

The previous draft targeted a standard deviation of ≤ 0.10 while defaulting to 10
questions per page. That target was unreachable by roughly an order of magnitude, and it
made `--fail-under-eval` gate CI on a number whose noise band was wider than any fix one
could ship. Three decisions follow, and they apply to the PRD's success metrics too:

- **`--questions` defaults to 50**, and the hard cap rises from 30 to 200. Users who want a
  faster, cheaper run can lower it, and the report then prints the resulting CI so the
  noise is visible rather than hidden.
- **Targets are stated as CIs on the mean, not as standard deviations of per-trial scores.**
  Per-trial variation (answerer temperature, provider nondeterminism) is reported as
  `per_trial_stddev` and is a *different quantity* from sampling error. Conflating them is
  what produced the earlier implausible target.
- **`--fail-under-eval` refuses to gate on a low-confidence eval.** A CI of ±20 points
  cannot support a threshold decision. When the run is low-confidence (`crawler_only`
  ground truth) or the CI is wider than a configured `--fail-under-eval-margin` (default
  10), the tool prints a warning and **exits 0** rather than failing the build on noise.
  Opt in to strict behavior with `--strict-eval`.

Interpreting the earlier targets: "eval stddev ≤ 0.10" in the PRD meant 0.10 as a
*fraction* of the score (i.e. ±10 points), not 0.10 points. The docs never said which, and
the distinction is exactly an order of magnitude. It is now stated explicitly in both
places.

## 5. Cost control

- `--dry-run` estimates tokens and cost from page sizes, chunk counts, and settings
  without any API call.
- `--max-cost` aborts before exceeding the limit.
- Defaults: **50 questions per page**, **3 trials**, **3 pages evaluated** (set by
  `--eval-pages`, independent of `--max-pages`), small inexpensive answering model.
- Prefer small models for answering; the answer step is the volume driver, since it scales
  with questions × trials. Use a stronger model for judging if budget allows.
- Rough cost model (illustrative):
  `embedding (1 call/page) + generation (1 call/page) + answering (questions × trials) +
  judging (questions × trials)`. The exact estimate is computed by the tool and shown by
  `--dry-run`.
- Worked example at defaults, 3 pages, a small model: roughly 50 × 3 × 3 = 450 answer calls
  plus 450 judge calls. That is not free — `--dry-run` exists so nobody discovers this by
  accident. Lower `--questions` or `--trials` for a cheaper first look.

## 6. Prompts (summary)

Full templates live in `src/geoprobe/evals/prompts/` and are versioned. Design constraints:

- **Generator:** produce N questions; each with a reference answer and verbatim source
  span from the ground truth; no questions that depend on information outside it.
- **Answerer:** answer using only the provided retrieved context; quote the passage used;
  reply `NOT_FOUND` if absent; no outside knowledge, no inference from world knowledge.
- **Judge:** given question, reference answer, and candidate answer, return JSON
  `{verdict, rationale}`; strict about factual equivalence, lenient about wording.

## 7. Known limitations (to be stated in the README)

1. It is a **proxy** for AI retrievability, not for citation or ranking in any specific
   product.
2. The retrieval simulation is an approximation. Real vendors differ in chunking,
   embedding, top-k, reranking, and JavaScript handling, and we cannot match any of them
   exactly. We can only guarantee the eval is harsher than whole-page context and stable
   across runs.
3. LLM judges can be wrong or biased; spot-check the failure list.
4. Generated questions may not match real user queries. A facts file or user-supplied
   question list is better.
5. Scores depend on the chosen model and are not comparable across models.
6. On small pages the eval falls back to whole-page context, which loses the resolution
   that makes it useful. The report says when this happened.
7. Retrieval-based numbers are sensitive to chunk size, top-k, and the embedding model.
   Treat them as comparable only within the same `eval_version` and retrieval config,
   which the report records.

## 8. Validating the eval itself

Before relying on it, the project must show the eval behaves sensibly. These are release
gates, not aspirations:

- **Sanity fixtures:** a page with all content in static HTML scores high; the same
  content rendered only via JS scores low with rendering enabled.
- **Discrimination:** pages differing only in where key facts sit (top vs. buried vs. in a
  client-rendered component) produce materially different scores. If they do not, the
  retrieval stage is not doing its job and the eval is not worth shipping.
- **Judge agreement:** hand-label ~100 answers and report judge accuracy.
- **Stability:** report the 95% CI across repeated runs on fixtures; the CI width should be
  consistent with §4.2's table, not wildly wider.
- **Sensitivity:** known fixes (server-rendering a pricing table, moving a key fact to a
  clear section heading) must raise the score on the affected questions.

Results are published alongside the methodology. A methodology nobody can reproduce is
marketing.

## 9. Future extensions

- Multi-model panels: run the same eval across several answerer models and report spread.
- Reranking stage, to approximate vendors that rerank retrieved chunks.
- User-provided question lists (CSV/YAML) beyond `facts.yaml`.
- Live citation snapshots against real providers (v0.4), reported separately from this
  eval, never blended into the answerability score.
