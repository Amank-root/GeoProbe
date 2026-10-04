"""Eval runner: trials, aggregation, variance (EVALS §3.6, §4).

Two quantities are kept strictly apart, because conflating them is what made an
earlier version of this project's targets unreachable:

- `per_trial_stddev` — variation *across trials* (answerer nondeterminism).
- `ci95` — binomial sampling error *across questions*.

The threshold gate refuses to fire when the CI is too wide to justify a decision,
unless the user opts into --strict-eval.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from ..models import EvalFailure, EvalResult, EvalUsage, RetrievalReport
from ..util import binomial_ci95
from . import answer as answer_mod
from . import judge as judge_mod
from . import retrieval as retrieval_mod
from .questions import Question

EVAL_VERSION = "1"

LikelyCause = Literal[
    "content_not_in_crawler_view", "content_ambiguous", "answerer_error", "unknown"
]

# Half-width of the 95% CI, in score points, beyond which a threshold decision is
# not supported. At the default --questions 50 the true 95% half-width is about
# 14 points (see EVALS §4.2), so the default margin is set just above it: a user
# who wants to gate at defaults should not have to raise it.
DEFAULT_FAIL_UNDER_MARGIN = 15.0


@dataclass
class PageCorpus:
    """One page's two views: what the answerer sees, and where questions came from."""

    url: str
    crawler_text: str
    ground_truth_text: str


@dataclass
class TrialOutcome:
    verdicts: list[str] = field(default_factory=list)
    abstentions: int = 0
    hallucinations: int = 0
    span_hits: int = 0
    spans_available: int = 0
    retrievable: int = 0


@dataclass
class PageResult:
    url: str
    question_count: int = 0
    outcomes: list[TrialOutcome] = field(default_factory=list)
    failures: list[EvalFailure] = field(default_factory=list)
    retrieval: RetrievalReport | None = None
    coverage_loss: float | None = None


def aggregate(page: PageResult, total_questions: int) -> dict[str, Any]:
    """Per-trial and pooled metrics for one page.

    Answerability is the mean over all question-trials, so a page with more
    questions contributes proportionally more evidence, which is what the
    binomial CI is computed over.
    """
    if not page.outcomes:
        return {
            "mean": 0.0, "per_trial_stddev": 0.0, "per_trial": [], "ci95": [0.0, 0.0],
            "questions": 0, "question_trials": 0,
        }

    per_trial: list[float] = []
    pooled_correctish = 0.0
    pooled_total = 0
    abstentions = hallucinations = span_hits = spans_available = 0

    for outcome in page.outcomes:
        if not outcome.verdicts:
            continue
        score = 100.0 * sum(_points(v) for v in outcome.verdicts) / len(outcome.verdicts)
        per_trial.append(round(score, 4))
        pooled_correctish += sum(_points(v) for v in outcome.verdicts)
        pooled_total += len(outcome.verdicts)
        abstentions += outcome.abstentions
        hallucinations += outcome.hallucinations
        span_hits += outcome.span_hits
        spans_available += outcome.spans_available

    mean_rate = pooled_correctish / pooled_total if pooled_total else 0.0
    lo, hi = binomial_ci95(mean_rate, pooled_total)
    stddev = _stddev(per_trial)

    return {
        "mean": round(100.0 * mean_rate, 4),
        "per_trial_stddev": round(stddev, 4),
        "per_trial": per_trial,
        # Sampling error across questions, not across trials.
        "ci95": [round(100.0 * lo, 2), round(100.0 * hi, 2)],
        "questions": page.question_count or total_questions,
        "question_trials": pooled_total,
        "abstention_rate": round(abstentions / pooled_total, 4) if pooled_total else 0.0,
        "hallucination_rate": round(hallucinations / pooled_total, 4) if pooled_total else 0.0,
        # None, not 0.0, when no question carried a source span: a missing
        # measurement must not be reported as a zero score.
        "context_recall": round(span_hits / spans_available, 4) if spans_available else None,
    }


def _points(verdict: str) -> float:
    if verdict == judge_mod.CORRECT:
        return 1.0
    if verdict == judge_mod.PARTIAL:
        return 0.5
    return 0.0


def _stddev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return variance**0.5


def merge_page_results(pages: list[PageResult]) -> EvalResult:
    """Pool every page into one EvalResult, weighting by question-trials."""
    usable = [p for p in pages if p.outcomes]
    if not usable:
        raise ValueError("no eval results to merge")

    pooled_correctish = 0.0
    pooled_total = 0
    abstentions = hallucinations = 0
    span_hits = spans_available = 0
    all_trials: list[float] = []

    for page in usable:
        for outcome in page.outcomes:
            if not outcome.verdicts:
                continue
            pooled_correctish += sum(_points(v) for v in outcome.verdicts)
            pooled_total += len(outcome.verdicts)
            abstentions += outcome.abstentions
            hallucinations += outcome.hallucinations
            span_hits += outcome.span_hits
            spans_available += outcome.spans_available
        for score in aggregate(page, page.question_count)["per_trial"]:
            all_trials.append(score)

    mean_rate = pooled_correctish / pooled_total if pooled_total else 0.0
    lo, hi = binomial_ci95(mean_rate, pooled_total)
    answerability = {
        "mean": round(100.0 * mean_rate, 4),
        "per_trial_stddev": round(_stddev(all_trials), 4),
        "per_trial": all_trials,
        "ci95": [round(100.0 * lo, 2), round(100.0 * hi, 2)],
        "question_trials": pooled_total,
    }
    context_recall = span_hits / spans_available if spans_available else 0.0

    retrievals = [p.retrieval for p in usable if p.retrieval]
    first = retrievals[0] if retrievals else RetrievalReport(
        mode="whole_page", top_k=5,
        chunk_target_tokens=retrieval_mod.CHUNK_TARGET_TOKENS,
        chunk_overlap_pct=retrieval_mod.CHUNK_OVERLAP_PCT,
        embedding_model="none", chunk_count=0,
    )
    first.chunk_count = sum(r.chunk_count for r in retrievals) or first.chunk_count
    if any(r.mode == "whole_page" for r in retrievals):
        first.mode = "whole_page"

    coverage = [p.coverage_loss for p in usable if p.coverage_loss is not None]
    failures = [f for page in usable for f in page.failures]

    return EvalResult(
        eval_version=EVAL_VERSION,
        confidence="high",  # replaced by the caller from the question set
        ground_truth="crawler_only",
        answerer_model="",
        judge_model="",
        trials=max(len(p.outcomes) for p in usable),
        questions_per_page=max(p.question_count for p in usable),
        pages_evaluated=len(usable),
        answerability=answerability,
        context_recall=round(context_recall, 4),
        # The share of the loss that retrieval, rather than the answerer or the
        # writing, is responsible for.
        retrieval_gap=round(context_recall - mean_rate, 4),
        retrieval=first,
        abstention_rate=round(abstentions / pooled_total, 4) if pooled_total else 0.0,
        hallucination_rate=round(hallucinations / pooled_total, 4) if pooled_total else 0.0,
        coverage_loss=round(sum(coverage) / len(coverage), 4) if coverage else None,
        usage=EvalUsage(),
        failures=failures[:100],
    )


def run_page(
    llm_answerer: Any,
    llm_judge: Any,
    corpus: PageCorpus,
    questions: list[Question],
    *,
    trials: int = 3,
    top_k: int = 5,
    embed_fn: Any | None = None,
    embedding_model: str = retrieval_mod.DEFAULT_EMBEDDING,
) -> PageResult:
    """Run the eval for one page: retrieve, answer, judge — repeated per trial."""
    result = PageResult(url=corpus.url, question_count=len(questions))
    if not questions:
        return result

    prepared, vectors = retrieval_mod.prepare(
        corpus.crawler_text, top_k=top_k, embedding_model=embedding_model,
        embed_fn=embed_fn,
    )
    result.retrieval = RetrievalReport(
        mode=prepared.mode,
        top_k=prepared.top_k,
        chunk_target_tokens=prepared.chunk_target_tokens,
        chunk_overlap_pct=prepared.chunk_overlap_pct,
        embedding_model=prepared.embedding_model,
        chunk_count=prepared.chunk_count,
    )

    # Embed each question once and reuse across trials, so trial variance
    # reflects the answerer rather than the retrieval step.
    question_vectors: list[list[float]] | None = None
    if vectors is not None and questions and embed_fn is not None:
        try:
            question_vectors = embed_fn([q.question for q in questions], embedding_model)
        except Exception:
            question_vectors = None

    per_question_outcomes: list[list[str]] = [[] for _ in questions]
    per_question_span: list[bool] = []
    per_question_abstain = 0
    per_question_halluc = 0

    for trial in range(max(1, trials)):
        outcome = TrialOutcome()
        first_trial = trial == 0
        for index, question in enumerate(questions):
            query_vector = question_vectors[index] if question_vectors else None
            top = retrieval_mod.retrieve(
                question.question, prepared.chunks, top_k=top_k,
                vectors=vectors, query_vector=query_vector,
            )
            retrieved_chunks = [chunk for chunk, _ in top]
            hit = retrieval_mod.span_retrieved(question.source_span, retrieved_chunks)
            if first_trial:
                per_question_span.append(hit)
            if question.source_span:
                # Only questions with a real span can contribute to recall.
                outcome.spans_available += 1
                outcome.span_hits += 1 if hit else 0
                outcome.retrievable += 1 if hit else 0

            candidate = answer_mod.answer(llm_answerer, question.question, top)
            verdict = judge_mod.judge(
                llm_judge, question.question, question.reference_answer,
                candidate.answer, abstained=candidate.abstained,
            )
            outcome.verdicts.append(verdict.verdict)
            per_question_outcomes[index].append(verdict.verdict)

            if first_trial:
                per_question_abstain += 1 if verdict.verdict == judge_mod.ABSTAINED else 0
                per_question_halluc += 1 if verdict.verdict == judge_mod.INCORRECT else 0
            # An answerer error is recorded as such, not counted as a
            # hallucination: the model did not invent anything.
            if candidate.error:
                continue
            if verdict.verdict == judge_mod.ABSTAINED:
                outcome.abstentions += 1
            elif verdict.verdict == judge_mod.INCORRECT:
                outcome.hallucinations += 1
        result.outcomes.append(outcome)

    # A question that failed in a majority of trials is the actionable output.
    majority = max(1, trials // 2 + 1)
    for index, question in enumerate(questions):
        outcomes = per_question_outcomes[index]
        if not outcomes:
            continue
        if outcomes.count(judge_mod.CORRECT) >= majority:
            continue
        span_hit = per_question_span[index] if index < len(per_question_span) else False
        result.failures.append(
            EvalFailure(
                page=corpus.url,
                question=question.question,
                reference_answer=question.reference_answer,
                outcomes=outcomes,
                span_retrieved=span_hit,
                likely_cause=_likely_cause(span_hit, outcomes, corpus),
            )
        )

    result.coverage_loss = _coverage_loss(per_question_outcomes, len(questions))
    return result


def _likely_cause(span_hit: bool, outcomes: list[str], corpus: PageCorpus) -> LikelyCause:
    """The actionable part of the report: what kind of problem is this?

    Separating retrieval loss from a writing problem is the entire reason context
    recall exists (EVALS §3.6). If the span never made it into the context, the
    problem is upstream of the model.
    """
    if not span_hit:
        return "content_not_in_crawler_view"
    if any(v == judge_mod.INCORRECT for v in outcomes):
        # Retrieved but contradicted: the page is ambiguous or the model erred.
        return "answerer_error"
    if len(set(outcomes)) > 1:
        return "answerer_error"
    return "content_ambiguous"


def _coverage_loss(outcomes: list[list[str]], total: int) -> float | None:
    """Questions answerable from ground truth that failed from the crawler view."""
    if not total:
        return None
    losses = [
        1.0 if v and judge_mod.CORRECT not in v else 0.0 for v in outcomes
    ]
    return round(sum(losses) / len(losses), 4) if losses else None


def decide_threshold(
    result: EvalResult,
    *,
    fail_under: float | None,
    margin: float = DEFAULT_FAIL_UNDER_MARGIN,
    strict: bool = False,
) -> tuple[bool, str]:
    """Whether to fail the build, and why.

    A threshold cannot support a decision on a ±20 point CI, so a low-confidence
    or wide-CI run exits 0 with a warning instead (EVALS §4.2). --strict-eval
    overrides that, because some users would rather have the noisy signal.
    """
    if fail_under is None:
        return False, ""

    mean = float(result.answerability.get("mean", 0.0))
    ci = result.answerability.get("ci95") or [0.0, 0.0]
    # Half-width, so it reads as the ±N points the docs and the flag both use.
    # Comparing the full width against a ±N margin would refuse to gate at the
    # documented default of 50 questions, where the half-width is about ±7.
    half_width = (float(ci[1]) - float(ci[0])) / 2.0

    if result.confidence == "low":
        note = (
            "ground truth was the crawler view itself, so this eval is circular and "
            "measures clarity rather than content loss; --fail-under-eval is not applied"
        )
        return (mean < fail_under, note) if strict else (False, note)

    if half_width > margin:
        note = (
            f"95% CI is ±{half_width:.0f} points, wider than the "
            f"--fail-under-eval-margin of ±{margin:g}; not failing on noise"
        )
        return (mean < fail_under, note) if strict else (False, note)

    return mean < fail_under, ""