"""Eval engine tests. No network, no API key — responses are recorded."""

from __future__ import annotations

import pytest

from fixtures.cassettes import (
    ANSWERABLE,
    NOT_FOUND,
    REFERENCE,
    SubstringScriptedLLM,
    answer_uses_context,
    generated_questions,
    judge_says,
)
from geoctl.evals import questions as q_mod
from geoctl.evals import retrieval as r_mod
from geoctl.evals import runner as runner_mod
from geoctl.evals.answer import build_prompt
from geoctl.evals.answer import parse as parse_answer
from geoctl.evals.judge import parse as parse_judge
from geoctl.util import binomial_ci95

# ------------------------------------------------------------------- retrieval


def test_chunking_splits_on_heading_boundaries():
    text = "\n\n".join(
        [f"# Section {i}\n\n" + (f"Body sentence {i}. " * 40) for i in range(6)]
    )
    chunks = r_mod.chunk_text(text, target_tokens=100, overlap_pct=0)
    assert len(chunks) > 1
    assert all(c.text.strip() for c in chunks)
    assert all(c.tokens <= 400 for c in chunks), "a chunk blew far past the target"


def test_chunking_keeps_heading_path():
    text = "# Pricing\n\n" + ("The Starter plan costs $19 per month. " * 60)
    chunks = r_mod.chunk_text(text, target_tokens=60)
    assert any("Pricing" in c.heading_path for c in chunks)


def test_small_page_falls_back_to_whole_page():
    """A page too small to chunk loses the metric's resolution, and the result
    has to say so (EVALS §3.3)."""
    prepared, vectors = r_mod.prepare("A tiny page about widgets.", top_k=5, embed_fn=None)
    assert prepared.mode == "whole_page"
    assert prepared.chunk_count == 1
    assert vectors is None
    assert "lexical" in prepared.embedding_model


def test_large_page_stays_chunked():
    text = "\n\n".join(f"# H{i}\n\n" + (f"Sentence {i} about widgets. " * 80) for i in range(5))
    prepared, _ = r_mod.prepare(text, top_k=5, embed_fn=None)
    assert prepared.mode == "chunked"
    assert prepared.chunk_count >= 3


def test_span_retrieved_detects_a_present_span():
    chunks = r_mod.chunk_text("# Pricing\n\nThe Starter plan costs $19 per month. " * 30,
                              target_tokens=60)
    assert r_mod.span_retrieved("The Starter plan costs $19 per month.", chunks)


def test_span_retrieved_is_false_for_absent_span():
    chunks = r_mod.chunk_text("# Docs\n\nDocumentation lives at /docs. " * 30, target_tokens=60)
    assert not r_mod.span_retrieved("The Starter plan costs $19 per month.", chunks)


def test_retrieval_is_deterministic_without_an_embedder():
    chunks = r_mod.chunk_text("# A\n\nalpha beta gamma delta\n\n# B\n\nepsilon zeta eta theta",
                              target_tokens=10)
    first = r_mod.retrieve("alpha beta", chunks, top_k=2)
    second = r_mod.retrieve("alpha beta", chunks, top_k=2)
    assert [c.index for c, _ in first] == [c.index for c, _ in second]


def test_top_k_is_respected():
    text = "\n\n".join(f"# H{i}\n\nword{i} body text here" for i in range(10))
    chunks = r_mod.chunk_text(text, target_tokens=10)
    assert len(r_mod.retrieve("body", chunks, top_k=3)) == 3


def test_answerer_sees_only_retrieved_context():
    chunks = [(_ChunkLike("alpha beta"), 0.9)]
    prompt = build_prompt("What is alpha?", chunks)
    assert "alpha beta" in prompt
    # The answerer must never be handed the whole page or the reference answer.
    assert REFERENCE not in prompt
    assert "no context was retrieved" in build_prompt("q?", [])


class _ChunkLike:
    def __init__(self, text: str) -> None:
        self.text = text


# --------------------------------------------------------------- answer parsing


def test_not_found_is_an_abstention_not_a_wrong_answer():
    candidate = parse_answer(NOT_FOUND)
    assert candidate.abstained is True
    assert candidate.answer == NOT_FOUND


def test_quoted_passage_is_separated_from_the_answer():
    candidate = parse_answer(answer_uses_context())
    assert candidate.abstained is False
    assert candidate.answer == ANSWERABLE
    assert "Starter plan" in candidate.quoted


def test_a_preamble_is_stripped():
    assert parse_answer("The answer is: $19 per month").answer == "$19 per month"


def test_an_empty_answer_counts_as_abstention():
    assert parse_answer("").abstained is True


# --------------------------------------------------------------- judge parsing


def test_judge_verdicts_map_to_points():
    assert parse_judge(judge_says("correct")).points == 1.0
    assert parse_judge(judge_says("partially_correct")).points == 0.5
    assert parse_judge(judge_says("incorrect")).points == 0.0
    assert parse_judge(judge_says("abstained")).points == 0.0


def test_judge_recovers_json_wrapped_in_prose():
    raw = 'Sure! Here you go: {"verdict": "correct", "rationale": "matches"} done'
    assert parse_judge(raw).verdict == "correct"


def test_unparseable_judge_never_scores_as_correct():
    """A broken judge must not inflate the score."""
    assert parse_judge("I think it's fine really").verdict != "correct"


def test_candidate_saying_not_found_is_abstained_without_a_judge_call():
    from geoctl.evals.judge import judge

    class Exploding:
        def complete(self, *a, **k):  # pragma: no cover - must never be called
            raise AssertionError("judge must not be called for an abstention")

    assert judge(Exploding(), "q", REFERENCE, NOT_FOUND).verdict == "abstained"


# ------------------------------------------------------------- question loading


def test_facts_file_becomes_high_confidence_questions(tmp_path):
    path = tmp_path / "facts.yaml"
    path.write_text(
        "site: https://example.com\n"
        "facts:\n"
        "  - id: pricing\n"
        '    question: "How much is Starter?"\n'
        '    answer: "$19 per month"\n'
        "    page: /pricing\n"
        '  - question: "When founded?"\n'
        '    answer: "2019"\n',
        encoding="utf-8",
    )
    facts = q_mod.load_facts(path)
    qset = q_mod.questions_from_facts(facts, facts.site)

    assert len(qset.questions) == 2
    assert qset.ground_truth == "facts"
    assert qset.confidence == "high", "a hand-written facts file is the strongest tier"
    assert qset.questions[0].page == "https://example.com/pricing"


def test_duplicate_facts_are_deduplicated(tmp_path):
    path = tmp_path / "facts.yaml"
    path.write_text(
        "facts:\n"
        '  - question: "How much is Starter?"\n'
        '    answer: "$19 per month"\n'
        '  - question: "how much is starter?"\n'
        '    answer: "$19 per month"\n',
        encoding="utf-8",
    )
    assert len(q_mod.questions_from_facts(q_mod.load_facts(path)).questions) == 1


def test_a_bad_facts_file_raises_a_readable_error(tmp_path):
    path = tmp_path / "facts.yaml"
    path.write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(ValueError, match="mapping"):
        q_mod.load_facts(path)


def test_generated_questions_are_filtered_against_ground_truth():
    """A question the ground truth cannot answer would penalise the site for the
    generator's mistake (EVALS §3.2)."""
    llm = SubstringScriptedLLM().on(
        "GROUND TRUTH TEXT",
        generated_questions(
            [
                ("How much is Starter?", "$19 per month", "The Starter plan costs $19 per month."),
                ("What is the CEO's name?", "Ada van Dijk", "Ada van Dijk is the founder."),
                ("What colour is the logo?", "purple", "The logo is purple."),
            ]
        ),
    )
    truth = "The Starter plan costs $19 per month. Ada van Dijk is the founder."
    items = q_mod.generate(llm, truth, "https://example.com", count=10)

    assert len(items) == 2, "the logo question is not in the ground truth"
    assert all("purple" not in q.question for q in items)
    # The unverifiable span is dropped rather than trusted.
    logo = [q for q in items if "logo" in q.question]
    assert all(q.source_span == "" for q in logo)


# ------------------------------------------------------------------ aggregation


def test_binomial_ci_narrows_with_more_questions():
    """The whole resolution argument of EVALS §4.2 depends on this.

    At a true rate of 0.6 the true 95% half-width is about ±14 points at the
    default 50 questions per page, and about ±30 at 10 questions — which is why
    50 is the default and 10 is not. (EVALS §4.2 tabulates the 1-SE figures;
    this test uses the 95% ones the code actually reports.)
    """
    half = {n: (binomial_ci95(0.6, n)[1] - binomial_ci95(0.6, n)[0]) / 2
            for n in (10, 50, 100)}
    assert half[10] > half[50] > half[100]
    assert round(half[50] * 100) == 14
    assert round(half[10] * 100) == 30


def test_ci_is_bounded():
    low, high = binomial_ci95(0.0, 50)
    assert low == 0.0 and 0.0 <= high <= 1.0
    assert binomial_ci95(0.5, 0) == (0.0, 0.0)


def test_per_trial_stddev_and_ci_are_separate_quantities():
    """Conflating these is what made the original targets unreachable."""
    page = runner_mod.PageResult(url="u", question_count=4)
    page.outcomes = [
        runner_mod.TrialOutcome(verdicts=["correct"] * 4),
        runner_mod.TrialOutcome(verdicts=["abstained"] * 4),
        runner_mod.TrialOutcome(verdicts=["correct"] * 4),
    ]
    stats = runner_mod.aggregate(page, 4)
    assert stats["per_trial_stddev"] > 0, "trial variation must be reported"
    assert stats["ci95"][1] - stats["ci95"][0] > 0, "sampling error must be reported"
    # Two of three trials were fully correct: 8 correct of 12 question-trials.
    assert stats["mean"] == pytest.approx(66.667, abs=0.01)
    # The two quantities are not the same number and must not be substituted.
    assert stats["per_trial_stddev"] != pytest.approx(
        (stats["ci95"][1] - stats["ci95"][0]) / 2, abs=0.01
    )


def test_answerability_weights_partial_credit_at_half():
    page = runner_mod.PageResult(url="u", question_count=4)
    page.outcomes = [runner_mod.TrialOutcome(
        verdicts=["correct", "partially_correct", "incorrect", "abstained"])]
    stats = runner_mod.aggregate(page, 4)
    assert stats["mean"] == 37.5  # (1 + 0.5) / 4


def test_retrieval_gap_separates_extraction_from_writing():
    page = runner_mod.PageResult(url="u", question_count=4)
    page.outcomes = [runner_mod.TrialOutcome(
        verdicts=["correct", "incorrect", "incorrect", "incorrect"], span_hits=4,
        spans_available=4)]
    result = runner_mod.merge_page_results([page])
    # Every span was retrieved, yet the score is low: a writing problem.
    assert result.context_recall == 1.0
    assert result.retrieval_gap > 0.3


def test_missing_spans_do_not_report_zero_recall():
    """No span means unmeasurable, not zero."""
    page = runner_mod.PageResult(url="u", question_count=2)
    page.outcomes = [runner_mod.TrialOutcome(verdicts=["correct", "correct"])]
    assert runner_mod.aggregate(page, 2)["context_recall"] is None


# ------------------------------------------------------------- threshold gating


def _eval_result(mean: float, low: str = "high",
                 ci: tuple[float, float] = (55.0, 69.0)):  # type: ignore[no-untyped-def]
    from geoctl.models import Confidence, EvalResult, RetrievalReport

    confidence: Confidence = "low" if low == "low" else "high"
    return EvalResult(
        confidence=confidence,
        ground_truth="facts" if confidence == "high" else "crawler_only",
        answerer_model="openai/gpt-4o-mini",
        judge_model="anthropic/claude-sonnet-4-5",
        trials=3,
        questions_per_page=50,
        pages_evaluated=1,
        answerability={"mean": mean, "ci95": list(ci)},
        retrieval=RetrievalReport(mode="chunked", top_k=5, chunk_target_tokens=400,
                                   chunk_overlap_pct=10, embedding_model="x", chunk_count=12),
    )


def test_threshold_fires_on_a_narrow_ci_below_target():
    # ci95 55-69 is ±7 points, inside the default margin, so the gate applies.
    fail, note = runner_mod.decide_threshold(_eval_result(62.0), fail_under=70)
    assert fail is True
    assert note == ""


def test_threshold_gates_at_the_documented_default_resolution():
    """The default --questions 50 gives about ±14 points, which must still gate.

    Comparing the full CI width against the margin would make the gate silently
    unreachable at defaults, so the comparison is against the half-width.
    """
    from geoctl.evals.runner import DEFAULT_FAIL_UNDER_MARGIN
    from geoctl.util import binomial_ci95

    lo, hi = binomial_ci95(0.6, 50)
    result = _eval_result(62.0, ci=(round(lo * 100, 2), round(hi * 100, 2)))
    fail, note = runner_mod.decide_threshold(
        result, fail_under=70, margin=DEFAULT_FAIL_UNDER_MARGIN
    )
    assert fail is True, note


def test_threshold_passes_above_target():
    fail, _ = runner_mod.decide_threshold(_eval_result(80.0), fail_under=70)
    assert fail is False


def test_threshold_refuses_to_gate_on_a_wide_ci():
    """A ±20 point CI cannot support a decision, so the build must not fail on it."""
    fail, note = runner_mod.decide_threshold(
        _eval_result(62.0, ci=(42.0, 82.0)), fail_under=70, margin=10.0
    )
    assert fail is False
    assert "wider" in note
    assert "±20" in note


def test_strict_eval_opts_into_gating_on_noise():
    fail, note = runner_mod.decide_threshold(
        _eval_result(62.0, ci=(42.0, 82.0)), fail_under=70, margin=10.0, strict=True
    )
    assert fail is True
    assert note


def test_low_confidence_eval_never_gates_ci():
    fail, note = runner_mod.decide_threshold(
        _eval_result(20.0, low="low"), fail_under=70
    )
    assert fail is False
    assert "circular" in note


def test_no_threshold_configured_means_no_failure():
    assert runner_mod.decide_threshold(_eval_result(0.0), fail_under=None) == (False, "")


# ------------------------------------------------------------------- end to end


def test_run_page_produces_a_result_with_a_recorded_llm():
    llm = SubstringScriptedLLM()
    llm.on("GROUND TRUTH", generated_questions(
        [("How much is Starter?", "$19 per month", "The Starter plan costs $19 per month.")]
    ))
    llm.on("Retrieved context", answer_uses_context())
    llm.on("Grade the candidate", judge_says("correct"))

    corpus = runner_mod.PageCorpus(
        url="https://example.com/pricing",
        crawler_text=("# Pricing\n\nThe Starter plan costs $19 per month. "
                      + ("Filler content about widgets and delivery. " * 200)),
        ground_truth_text="# Pricing\n\nThe Starter plan costs $19 per month.",
    )
    result = runner_mod.run_page(llm, llm, corpus, [
        q_mod.Question(question="How much is Starter?",
                       reference_answer=REFERENCE,
                       source_span="The Starter plan costs $19 per month.")
    ], trials=2, top_k=3, embed_fn=None)

    merged = runner_mod.merge_page_results([result])
    assert merged.answerability["mean"] == 100.0
    assert merged.context_recall == 1.0
    assert merged.retrieval.mode == "chunked"
    assert merged.failures == []


def test_retrieval_loss_is_reported_as_content_not_in_crawler_view():
    llm = SubstringScriptedLLM()
    llm.on("Retrieved context", NOT_FOUND)
    llm.on("Grade the candidate", judge_says("abstained"))

    corpus = runner_mod.PageCorpus(
        url="https://example.com/pricing",
        # The crawler view genuinely lacks the fact the question asks about.
        crawler_text="# Shipping\n\n" + ("We ship from Rotterdam. " * 400),
        ground_truth_text="The Starter plan costs $19 per month.",
    )
    result = runner_mod.run_page(llm, llm, corpus, [
        q_mod.Question(question="How much is Starter?", reference_answer=REFERENCE,
                       source_span="The Starter plan costs $19 per month.")
    ], trials=1, top_k=3, embed_fn=None)

    assert result.failures
    assert result.failures[0].span_retrieved is False
    assert result.failures[0].likely_cause == "content_not_in_crawler_view"


def test_cost_estimate_scales_with_questions_and_trials():
    from geoctl.evals.cost import estimate

    texts = ["x" * 20_000] * 3
    small = estimate(pages=3, questions_per_page=10, trials=1, page_texts=texts,
                     chunks_per_page=20, answer_model="openai/gpt-4o-mini",
                     judge_model="openai/gpt-4o-mini")
    large = estimate(pages=3, questions_per_page=100, trials=3, page_texts=texts,
                     chunks_per_page=20, answer_model="openai/gpt-4o-mini",
                     judge_model="openai/gpt-4o-mini")

    assert large.cost_usd > small.cost_usd
    assert large.answer_calls == 3 * 100 * 3
    assert large.judge_calls == 3 * 100 * 3
    # Answering dominates, which is why the docs say to lower questions or trials.
    assert "estimated" in small.line().lower()


def test_max_cost_guard():
    from geoctl.evals.cost import estimate
    from geoctl.evals.engine import check_budget
    from geoctl.llm.client import CostLimitExceeded

    est = estimate(pages=3, questions_per_page=100, trials=3, page_texts=["x" * 20_000] * 3,
                   chunks_per_page=20, answer_model="openai/gpt-4o-mini",
                   judge_model="openai/gpt-4o-mini")
    with pytest.raises(CostLimitExceeded, match="exceeds"):
        check_budget(est, max_cost=0.0000001)
    check_budget(est, max_cost=100.0)  # does not raise


def test_provider_key_presence_drives_auto_mode(monkeypatch):
    """ADR-012: the eval runs by default when a key is present."""
    from geoctl.config import has_provider_key

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    for var in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GROQ_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    assert has_provider_key() is False

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert has_provider_key() is True