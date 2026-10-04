"""Eval orchestration: questions -> retrieve -> answer -> judge -> aggregate.

This is the project's differentiator, and the stage that must respect one rule
above all: the answerer sees **only** what retrieval handed it. It never sees the
ground truth, the whole page, or the reference answer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..cache import Cache
from ..config import EvalConfig
from ..llm.client import CostLimitExceeded, LLMClient
from ..models import EvalUsage
from ..util import content_hash
from . import cost as cost_mod
from . import questions as q_mod
from . import retrieval as retrieval_mod
from . import runner as runner_mod

# A facts-file eval is the only tier that may gate CI (ADR-014).
DEFAULT_ANSWERER = "openai/gpt-4o-mini"


class EvalConfigError(Exception):
    """Usage error: exit code 2."""


class EvalSkipped(Exception):
    """The eval could not run. Carries the one-line reason to print."""


@dataclass
class EvalPlan:
    """What the eval would run, and what it would cost, with no API calls."""

    estimate: cost_mod.CostEstimate
    pages: list[str]
    questions_per_page: int
    note: str = ""


@dataclass
class EvalOutcome:
    result: Any  # EvalResult
    usage: EvalUsage
    dry_run_line: str = ""


def resolve_model(config: EvalConfig) -> str:
    model = config.model or DEFAULT_ANSWERER
    if "/" not in model:
        raise EvalConfigError(
            f"Model {model!r} must use the LiteLLM provider/model form, "
            "for example openai/gpt-4o-mini"
        )
    return model


def embed_fn_for(config: EvalConfig) -> Any | None:
    """Return a callable, or None when no embedding provider is configured.

    Returning None makes retrieval fall back to deterministic lexical scoring,
    which the report names explicitly, so scores are never compared across
    incomparable retrieval configurations.
    """
    if not config.embedding_model:
        return None
    return retrieval_mod.embed


def plan(
    config: EvalConfig,
    corpora: list[runner_mod.PageCorpus],
    *,
    facts_questions: int | None = None,
    rendered_available: bool = False,
) -> EvalPlan:
    """Estimate a run without making a single API call (--dry-run).

    `facts_questions` is the count of questions a facts file supplies, which
    replaces --questions entirely for the estimate.
    """
    model = resolve_model(config)
    judge_model = config.judge_model or model
    texts = [c.crawler_text for c in corpora]
    chunks = 0
    whole_page = False
    for text in texts:
        prepared, _ = retrieval_mod.prepare(text, top_k=config.top_k,
                                             embed_fn=None)
        chunks = max(chunks, prepared.chunk_count)
        whole_page = whole_page or prepared.mode == "whole_page"

    per_page = config.questions if facts_questions is None else facts_questions
    estimate = cost_mod.estimate(
        pages=len(corpora),
        questions_per_page=per_page,
        trials=config.trials,
        page_texts=texts,
        chunks_per_page=chunks,
        top_k=config.top_k,
        answer_model=model,
        judge_model=judge_model,
        embed_model=config.embedding_model or "lexical",
        whole_page=whole_page,
    )
    note = ""
    if facts_questions is None and not rendered_available:
        note = (
            "No facts file and no --render: questions would be generated from the "
            "crawler view itself, which is circular. This run would be labelled "
            "low confidence and must not gate CI (ADR-014)."
        )
    return EvalPlan(estimate=estimate, pages=[c.url for c in corpora],
                    questions_per_page=per_page, note=note)


def run(
    config: EvalConfig,
    corpora: list[runner_mod.PageCorpus],
    *,
    cache: Cache | None = None,
    facts: q_mod.FactsFile | None = None,
    rendered_available: bool = False,
    use_cache: bool = True,
) -> EvalOutcome:
    """Run the eval end to end and return the merged result."""
    if not corpora:
        raise EvalSkipped("no pages were available to evaluate")

    model = resolve_model(config)
    judge_model = config.judge_model or model
    if judge_model.split("/")[0] == model.split("/")[0] and config.judge_model is None:
        # Not an error, but self-preference bias is a real risk worth naming.
        judge_note = (
            f"Judge model defaults to the answerer ({model}). A different family "
            "reduces self-preference bias; pass --judge-model to change it."
        )
    else:
        judge_note = ""

    answerer = LLMClient(model=model, cache=cache, use_cache=use_cache)
    judge = LLMClient(model=judge_model, cache=cache, use_cache=use_cache)
    embed_fn = embed_fn_for(config)

    page_results: list[runner_mod.PageResult] = []
    notes: list[str] = [n for n in (judge_note,) if n]
    ground_truth = "crawler_only"

    for corpus in corpora:
        question_set = _questions_for(config, cache, corpus, facts, answerer)
        if question_set.ground_truth in ("facts", "facts+rendered"):
            ground_truth = question_set.ground_truth
        elif rendered_available and ground_truth == "crawler_only":
            ground_truth = "rendered"
        if not question_set.questions:
            continue

        page_result = runner_mod.run_page(
            answerer, judge, corpus, question_set.questions,
            trials=config.trials, top_k=config.top_k, embed_fn=embed_fn,
            embedding_model=config.embedding_model or retrieval_mod.DEFAULT_EMBEDDING,
        )
        page_results.append(page_result)

    if not page_results:
        raise EvalSkipped(
            "no questions could be produced, so there was nothing to evaluate. "
            "Supply a facts file (--facts facts.yaml) for a high-confidence run."
        )

    result = runner_mod.merge_page_results(page_results)

    # The facts tier is the only one that is both independent and high-confidence.
    result.confidence = "high" if ground_truth in ("facts", "rendered", "facts+rendered") else "low"
    result.ground_truth = ground_truth  # type: ignore[assignment]
    result.answerer_model = model
    result.judge_model = judge_model
    result.trials = config.trials
    result.questions_per_page = max(p.question_count for p in page_results)
    result.usage = EvalUsage(
        input_tokens=answerer.usage.input_tokens + judge.usage.input_tokens,
        output_tokens=answerer.usage.output_tokens + judge.usage.output_tokens,
        estimated_cost_usd=round(answerer.usage.cost_usd + judge.usage.cost_usd, 6),
        cache_hits=answerer.usage.cache_hits + judge.usage.cache_hits,
    )
    result.notes = notes
    if any(p.retrieval and p.retrieval.mode == "whole_page" for p in page_results):
        notes.append(
            "At least one page was too small to chunk, so the whole page was passed. "
            "That case loses the resolution that makes the eval useful (EVALS §3.3)."
        )
    if result.usage.cache_hits:
        notes.append(
            f"{result.usage.cache_hits} LLM call(s) were served from cache, so this run "
            "is reproducible rather than a fresh measurement."
        )
    return EvalOutcome(result=result, usage=result.usage)


def _questions_for(
    config: EvalConfig,
    cache: Cache | None,
    corpus: runner_mod.PageCorpus,
    facts: q_mod.FactsFile | None,
    answerer: LLMClient,
) -> q_mod.QuestionSet:
    """Choose the strongest available ground-truth tier (ADR-014).

    Order: hand-written facts, then JS-rendered text, then the crawler view. Only
    the last is circular, and it is labelled low confidence wherever it surfaces.
    """
    if facts is not None:
        site = facts.site or corpus.url
        page_filter = facts.facts[0].page if facts.facts else None
        selected = q_mod.questions_from_facts(facts, site)
        if page_filter:
            filtered = [q for q in selected.questions
                        if q.page is None or _same_page(q.page, page_filter)]
            if filtered:
                selected = q_mod.QuestionSet(questions=filtered,
                                             ground_truth=selected.ground_truth,
                                             source_pages=selected.source_pages)
        return selected

    ground_truth_text = corpus.ground_truth_text or corpus.crawler_text
    generated = q_mod.generate(
        answerer, ground_truth_text, corpus.url, count=config.questions
    )
    tier = "rendered" if corpus.ground_truth_text.strip() else "crawler_only"
    return q_mod.QuestionSet(questions=generated, ground_truth=tier,  # type: ignore[arg-type]
                             source_pages=[corpus.url])


def _same_page(a: str, b: str) -> bool:
    return a.rstrip("/") == b.rstrip("/")


def cache_namespace(config: EvalConfig) -> str:
    """Stable namespace so two configs do not share cached generations."""
    return content_hash("eval", config.model, config.questions, config.trials)[:12]


def check_budget(estimate: cost_mod.CostEstimate, max_cost: float | None) -> None:
    if cost_mod.exceeds(estimate.cost_usd, max_cost):
        raise CostLimitExceeded(
            f"Estimated cost ${estimate.cost_usd:.4f} exceeds --max-cost "
            f"${max_cost:.2f}. Lower --questions, --trials, or --eval-pages."
        )


__all__ = [
    "DEFAULT_ANSWERER",
    "EvalConfigError",
    "EvalOutcome",
    "EvalPlan",
    "EvalSkipped",
    "check_budget",
    "plan",
    "resolve_model",
    "run",
]