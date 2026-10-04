# Methodology

How `geoctl` produces its numbers, what they mean, and what they do not. This
page exists because a methodology nobody can reproduce is marketing.

## What is measured

Two independent scores, never blended:

1. **The deterministic score** (0–100) — from 6 scored checks. Every check is a
   pure function of fetched data, and every finding carries the evidence that
   produced it. No API key is required, and CI runs with no network.
2. **The answerability eval** (0–100) — from the retrieval simulation described
   in [EVALS](EVALS.md). Requires your own provider key. Reported separately with
   a confidence interval, because a single number that silently blended two very
   different signals would tell you nothing about which one moved.

The remaining 14 checks are **informational**: reported with evidence and a fix
hint, contributing 0 points. See [ADR-010](DECISIONS.md#adr-010-the-check-catalog-is-narrow-and-mostly-unscored)
for why most "AI readiness" signals are not scored.

## The retrieval simulation, and why it is harsher than whole-page context

The eval does not paste your page into a model. It chunks the no-JS crawler view,
embeds the chunks, retrieves the top-k for each question, and answers from *only*
those chunks. This matters because a fact at the top of a page and the same fact
buried mid-page are equally available to a model handed the whole document, and
behave nothing alike inside a real retrieval stack.

We can therefore promise two things and not a third:

- The eval is **harsher than whole-page context**. It will not flatter a site.
- The eval is **stable run to run**: fixed prompts, fixed temperature, fixed seed
  where supported, and every LLM call cached by content hash.

We cannot promise it matches any vendor's pipeline. Real systems differ in
chunking, embedding, top-k, reranking, and JavaScript handling. This is an
approximation, stated as one.

## Avoiding circularity

If questions were generated from the crawler view and answered from the crawler
view, nearly every question would be answerable and the score would say nothing.
Ground truth is therefore chosen in descending order of strength
([ADR-014](DECISIONS.md#adr-014-ground-truth-for-the-eval-prefers-an-independent-facts-file)):

| Ground truth | Independence | Reported confidence | May gate CI |
|---|---|---|---|
| `facts.yaml` you wrote | Independent of both views | high | yes |
| JS-rendered text (`--render`) | Independent of the no-JS view | high | yes |
| The crawler view itself | **Circular** | low | **no** |

A low-confidence run is labelled as such everywhere it appears, and
`--fail-under-eval` refuses to gate on it unless you pass `--strict-eval`.

## Context recall is the diagnostic that justifies the design

`context_recall` is the share of questions whose source span was among the
retrieved chunks. `retrieval_gap = context_recall − answerability/100`.

| Reading | Meaning | Where to look |
|---|---|---|
| Low recall, decent answerability | Extraction problem | [REN-001](CHECKS.md#ren-001-text-available-without-javascript-20) |
| High recall, low answerability | Writing problem | Buried, ambiguous, or contradicted content |
| High recall, low answerability, high hallucination | Contradictions on the page | Trust and structured-data checks |

Without that split, users chase the wrong problem — which is the failure mode
this project is trying to avoid.

## Resolution, stated honestly

Targets are confidence intervals on the mean, not standard deviations of
per-trial scores. Those are different quantities and are never combined into one
number. At a true rate of 0.6:

| Questions/page | True 95% CI half-width |
|---|---|
| 10 | ± 30 points |
| **50** (default) | **± 14 points** |
| 100 | ± 10 points |

So `--fail-under-eval-margin` defaults to ±15 points: just above the real
resolution at the default sample size. **A ±14 point interval cannot support a
10-point threshold decision.** If you need a tighter gate, raise `--questions`
rather than lowering the margin and failing on noise. See
[EVALS §4.2](EVALS.md#42-resolution-why-the-default-is-50-questions-not-10).

## Cost figures are estimates

Every cost in the output is labelled an estimate and never presented as billing.
LiteLLM's cost reporting has not been verified against provider invoices
([ADR-015](DECISIONS.md#adr-015-litelm-cost-figures-are-reported-as-estimates-never-as-billing)),
so billing accuracy is an open question deferred to a funded-account test.
`--dry-run` estimates without making any API call.

## Calibration

38 offline fixtures covering the 28 categories in [FIXTURES](FIXTURES.md), of
which 16 are known-good. The current run reports a **0.00% false-positive rate**
and no false negatives — see [CALIBRATION](CALIBRATION.md) for what that does and
does not establish, and why the expectations were recorded rather than
hand-written.

## Known limitations

1. A **proxy** for AI retrievability, not a prediction of citations or rankings.
2. The retrieval simulation is an approximation of real vendor pipelines.
3. LLM judges can be wrong or biased. Spot-check the failure list.
4. Generated questions may not match real user queries. A facts file is better.
5. Scores depend on the chosen model and are **not comparable across models**.
6. On very small pages the eval falls back to whole-page context, which loses the
   resolution that makes it useful. The report says when this happened.
7. Retrieval numbers are sensitive to chunk size, top-k, and embedding model;
   compare only within the same `eval_version` and retrieval config.
8. `SITE-001` cannot be calibrated by the offline suite, because the fixture
   server is plain HTTP by necessity. This is recorded rather than hidden.

## Reproducing a score

```bash
uv sync --group dev
uv run pytest                       # offline, no API key
uv run python scripts/calibrate.py  # writes docs/CALIBRATION.md
```

Both are deterministic. Neither touches the network.
