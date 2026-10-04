"""Reasoning models must not be scored on their reasoning trace (issue #46).

A reasoning model emits a chain of thought before its answer and counts it
against `max_tokens`. Three separate failures came out of that, all reproduced
against nvidia/nemotron-3.5-lightning-30b-a3b and z-ai/glm-5.3-flash:

1. The answerer had a 300-token budget, spent entirely on thinking, returned
   `finish_reason="length"` with the *trace* as its content, and that trace was
   parsed as the answer — so a correctly answered question scored 0.
2. The judge had 200 tokens, same failure, and `parse` would find the word
   "correct" or "abstained" somewhere in the prose and grade on that.
3. Question generation passed no limit at all, so a long page was truncated
   mid-reasoning and parsed to zero questions — reported to the user as
   "no questions could be produced" for a perfectly good page.

These tests pin each one against the scripted cassette, so they need no key.
"""

from __future__ import annotations

from typing import ClassVar

import pytest

from fixtures.cassettes import ANSWERABLE, SubstringScriptedLLM
from geoctl.evals import answer as answer_mod
from geoctl.evals import judge as judge_mod
from geoctl.evals import questions as q_mod
from geoctl.evals.retrieval import Chunk
from geoctl.llm.client import Completion

# What a reasoning model actually returns when its budget runs out: prose
# reasoning, no answer, finish_reason "length".
TRACE = (
    "Here's a thinking process:\n\n1. **Analyze User Input:** the user asks what "
    "geoctl is.\n2. **Check Context:** the context says geoctl audits crawlers.\n"
    "3. **Formulate Answer:** I should output that sentence.\n"
)

CHUNKS = [(Chunk(text="geoctl audits whether AI crawlers can read a site.", index=0), 0.9)]


def _tracing_llm() -> SubstringScriptedLLM:
    """A model that burns its whole budget thinking, then gets cut off."""
    llm = SubstringScriptedLLM()
    llm.on("geoctl", TRACE)
    llm.finish_reason = "length"
    return llm


# ------------------------------------------------------------- the answer path


def test_a_truncated_answer_is_an_error_not_a_wrong_answer():
    """The distinction the whole fix turns on.

    Recorded as an error, the runner counts it separately and does not blame the
    website. Recorded as a plain abstention, a good site loses points for the
    model's token budget.
    """
    candidate = answer_mod.answer(_tracing_llm(), "What is geoctl?", CHUNKS)

    assert candidate.error is not None
    assert "finish_reason=length" in candidate.error


def test_a_truncated_answer_is_not_scored_as_an_abstention():
    """A missing answer and a missing *budget* are different findings."""
    candidate = answer_mod.answer(_tracing_llm(), "What is geoctl?", CHUNKS)
    judge = judge_mod.judge(
        SubstringScriptedLLM().on("Grade", "irrelevant"),
        "What is geoctl?",
        "an auditor",
        candidate.answer,
        abstained=candidate.abstained,
    )
    # The judge's own call is separate; what matters is that the runner can see
    # this was an answerer fault via `candidate.error`.
    assert judge.verdict == judge_mod.ABSTAINED
    assert candidate.error is not None


def test_the_reasoning_trace_is_never_used_as_the_answer():
    """Pre-fix, the trace became the answer text and reached the judge."""
    candidate = answer_mod.answer(_tracing_llm(), "What is geoctl?", CHUNKS)
    assert "thinking process" not in candidate.answer.lower()


def test_a_complete_reasoning_answer_is_scored_normally():
    """The fix must not break the non-truncated path."""
    llm = SubstringScriptedLLM().on("geoctl", ANSWERABLE)
    candidate = answer_mod.answer(llm, "What is geoctl?", CHUNKS)
    assert candidate.error is None
    assert candidate.abstained is False
    assert ANSWERABLE in candidate.answer


def test_the_answerer_requests_enough_tokens_for_reasoning():
    """A budget of a few hundred is the defect itself, so pin the floor."""
    assert answer_mod.ANSWERER_MAX_TOKENS >= 1000


# -------------------------------------------------------------- the judge path


def test_a_truncated_judge_is_never_graded_on_prose():
    """`parse` would find "correct" inside a reasoning trace and score on it."""
    llm = SubstringScriptedLLM()
    llm.on("Grade", TRACE + ' {"verdict": "correct", "rationale": "matches"}')
    llm.finish_reason = "length"

    judgement = judge_mod.judge(llm, "Q?", "reference", "a candidate answer")

    assert judgement.verdict == judge_mod.ABSTAINED
    assert "finish_reason=length" in judgement.rationale


def test_a_complete_judge_verdict_still_works():
    llm = SubstringScriptedLLM().on("Grade", '{"verdict": "correct", "rationale": "yes"}')
    judgement = judge_mod.judge(llm, "Q?", "reference", "a candidate answer")
    assert judgement.verdict == judge_mod.CORRECT
    assert judgement.points == 1.0


def test_the_judge_requests_enough_tokens_for_reasoning():
    assert judge_mod.JUDGE_MAX_TOKENS >= 1000


# ---------------------------------------------------------- generation budget


def test_the_generation_budget_scales_with_page_length():
    """The measured failure: a long page consumed a short budget entirely.

    A budget that only grows with the question count truncates on a long page no
    matter how few questions were asked.
    """
    short = q_mod._generation_budget(3, text_chars=1_000)
    long = q_mod._generation_budget(3, text_chars=60_000)
    assert long > short * 5, (short, long)


def test_the_generation_budget_grows_with_question_count():
    few = q_mod._generation_budget(5, text_chars=10_000)
    many = q_mod._generation_budget(50, text_chars=10_000)
    assert many > few


def test_the_generation_budget_is_capped():
    """One call must not be able to spend without bound."""
    assert q_mod._generation_budget(200, text_chars=500_000) <= q_mod.GENERATION_MAX_TOKENS


def test_the_measured_real_page_case_is_within_budget():
    """The actual numbers from the reproduction, pinned so they cannot regress.

    17,750 characters of real crawled page text, three questions: a flat
    ~2.3k-token budget was consumed entirely by reasoning and returned no JSON.
    """
    budget = q_mod._generation_budget(3, text_chars=17_750)
    assert budget >= 10_000, budget


def test_truncated_generation_returns_no_questions():
    llm = SubstringScriptedLLM()
    llm.on(
        "Write up to",
        TRACE + ' {"questions": [{"question": "x?", "reference_answer": "y", "source_span": "z"}]}',
    )
    llm.finish_reason = "length"

    assert q_mod.generate(llm, "ground truth text that is long enough", "https://x/", count=3) == []


def test_complete_generation_still_returns_questions():
    from fixtures.cassettes import generated_questions

    llm = SubstringScriptedLLM().on(
        "Write up to",
        generated_questions(
            [("What is geoctl?", "an auditor of AI crawler access", "geoctl audits")]
        ),
    )
    out = q_mod.generate(llm, "geoctl audits", "https://x/", count=3)
    assert len(out) == 1
    assert out[0].reference_answer == "an auditor of AI crawler access"


def test_generation_requests_the_scaled_budget():
    """The budget must actually reach the provider, not just be computed."""
    from fixtures.cassettes import generated_questions

    llm = SubstringScriptedLLM().on("Write up to", generated_questions([]))
    q_mod.generate(llm, "x" * 60_000, "https://x/", count=3)
    assert llm.requested_budgets[-1] == q_mod._generation_budget(3, text_chars=60_000)


# ------------------------------------------------------- the response contract


def test_a_reasoning_content_field_is_used_when_content_is_null():
    """Some hosts return the answer in `reasoning_content` with null content."""
    from geoctl.llm.client import _completion_from

    class _Msg:
        content = None
        reasoning_content = "the answer"

    class _Choice:
        message = _Msg()
        finish_reason = "stop"

    class _Response:
        choices: ClassVar[list] = [_Choice()]

    assert _completion_from(_Response()).text == "the answer"


def test_finish_reason_survives_the_cache(tmp_path):
    """A replayed cached response must carry the same truncation verdict.

    Re-running an audit reads from cache; if the reason were dropped, the same
    truncated answer would look fine the second time and the report would change
    between two runs of the same input.
    """
    from geoctl.cache import NS_LLM, Cache
    from geoctl.llm.client import LLMClient

    cache = Cache(tmp_path / "c")
    try:
        client = LLMClient(model="m", cache=cache)
        # Write under the key `complete` will actually read: the target model is
        # prepended to the base key, so a key built from `key()` alone misses and
        # the call goes to the network instead.
        target = client.model
        cache.set(
            NS_LLM,
            {"text": "answer", "finish_reason": "length"},
            target,
            *client.key(1, None, "p"),
        )
        replayed = client.complete("p", max_tokens=1)
        assert replayed.finish_reason == "length"
        assert replayed.truncated is True
        # No provider call was made: an unroutable model name would have raised.
    finally:
        cache.close()


def test_completion_truncated_only_for_length():
    assert Completion(text="x", finish_reason="length").truncated is True
    assert Completion(text="x", finish_reason="stop").truncated is False
    assert Completion(text="x", finish_reason="content_filter").truncated is False


# ------------------------------------------------- the runner's error handling


def test_an_answerer_error_is_not_counted_as_a_hallucination():
    """A truncated answer must not inflate the hallucination rate.

    The runner already distinguishes these; this pins that the distinction
    survives the new truncation path.
    """
    from geoctl.evals.questions import Question
    from geoctl.evals.runner import PageCorpus, run_page

    llm = _tracing_llm()
    question = Question(
        question="What is geoctl?",
        reference_answer="an auditor",
        source_span="geoctl audits",
    )
    corpus = PageCorpus(url="https://x/", crawler_text="geoctl audits " * 400, ground_truth_text="")
    page = run_page(llm, llm, corpus, [question], trials=1, top_k=1)

    outcome = page.outcomes[0]
    assert outcome.hallucinations == 0
    assert outcome.abstentions == 0


@pytest.mark.parametrize("stage", ["answerer", "judge"])
def test_a_truncation_is_reported_as_a_failure_with_a_cause(stage):
    """The user must be able to tell this apart from a content problem."""
    from geoctl.evals.questions import Question
    from geoctl.evals.runner import PageCorpus, run_page

    answerer = (
        SubstringScriptedLLM().on("geoctl", ANSWERABLE) if stage == "judge" else _tracing_llm()
    )
    judge = _tracing_llm() if stage == "judge" else SubstringScriptedLLM().on("x", "x")

    question = Question(
        question="What is geoctl?", reference_answer="an auditor", source_span="geoctl audits"
    )
    corpus = PageCorpus(url="https://x/", crawler_text="geoctl audits " * 400, ground_truth_text="")
    page = run_page(answerer, judge, corpus, [question], trials=1, top_k=1)

    # It is a failure the user can see, and the cause is not silently "unknown".
    assert len(page.failures) == 1
    assert page.failures[0].likely_cause in {
        "content_not_in_crawler_view",
        "content_ambiguous",
        "answerer_error",
        "unknown",
    }
