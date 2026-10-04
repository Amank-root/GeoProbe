"""Cost estimation for --dry-run and --max-cost (EVALS §5, ADR-015).

--dry-run makes no API call, so it cannot settle whether LiteLLM's cost reporting
matches billing — which is exactly why the Milestone 0 spike was deferred. Every
figure this module produces is an **estimate** and is labelled as one everywhere
it appears.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..llm.client import count_tokens, estimate_cost

# Answerer and judge prompt overhead, in tokens, beyond the context itself.
ANSWER_OVERHEAD_TOKENS = 260
JUDGE_OVERHEAD_TOKENS = 200
# Context is sent on every answer call, so it scales with questions x trials.
_GENERATION_SYSTEM_TOKENS = 700


@dataclass
class CostEstimate:
    pages: int = 0
    questions_per_page: int = 0
    trials: int = 0
    chunks: int = 0
    tokens_per_chunk: int = 400
    top_k: int = 5
    answer_model: str = ""
    judge_model: str = ""
    embed_model: str = ""

    answer_calls: int = 0
    judge_calls: int = 0
    embed_calls: int = 0
    generation_calls: int = 0

    input_tokens: int = 0
    output_tokens: int = 0
    embed_tokens: int = 0
    cost_usd: float = 0.0

    def line(self) -> str:
        """A human-readable breakdown, for --dry-run."""
        return "\n".join(
            [
                "Estimated cost (estimate only, not billing — ADR-015)",
                f"  pages                {self.pages}",
                f"  questions/page       {self.questions_per_page}",
                f"  trials               {self.trials}",
                f"  chunks/page          {self.chunks} (top-k {self.top_k})",
                f"  embedding calls      {self.embed_calls}",
                f"  generation calls     {self.generation_calls}",
                f"  answer calls         {self.answer_calls}",
                f"  judge calls          {self.judge_calls}",
                f"  input tokens         ~{self.input_tokens + self.embed_tokens:,}",
                f"  output tokens        ~{self.output_tokens:,}",
                f"  estimated cost       ~${self.cost_usd:.4f}",
                f"  answerer model       {self.answer_model}",
                f"  judge model          {self.judge_model}",
                "  No API call was made.",
            ]
        )


def estimate(
    *,
    pages: int,
    questions_per_page: int,
    trials: int,
    page_texts: list[str],
    chunks_per_page: int,
    top_k: int = 5,
    answer_model: str = "",
    judge_model: str = "",
    embed_model: str = "",
    whole_page: bool = False,
) -> CostEstimate:
    """Estimate tokens and cost for an eval run without calling any model.

    Cost model (EVALS §5): embedding + generation, one batch each per page, plus
    answering and judging at questions x trials. Only the answering step really
    scales, which is why it dominates the estimate.
    """
    total = CostEstimate(
        pages=pages,
        questions_per_page=questions_per_page,
        trials=trials,
        chunks=chunks_per_page,
        top_k=top_k,
        answer_model=answer_model,
        judge_model=judge_model,
        embed_model=embed_model,
    )
    question_trials = questions_per_page * trials

    for text in page_texts[:pages]:
        page_tokens = count_tokens(text)
        # Context per answer call: top-k chunks, or the whole page when the eval
        # fell back to whole_page because the page was too small to chunk. Never
        # more than the page itself, which is the hard upper bound.
        if whole_page:
            context_tokens = page_tokens
        else:
            context_tokens = min(chunks_per_page * total.tokens_per_chunk, page_tokens)

        total.embed_calls += 1
        total.embed_tokens += chunks_per_page * 200

        if questions_per_page:
            total.generation_calls += 1
            gen_input = min(page_tokens, 120_000) + _GENERATION_SYSTEM_TOKENS
            total.input_tokens += gen_input
            total.output_tokens += questions_per_page * 120
            total.cost_usd += estimate_cost(answer_model, gen_input, questions_per_page * 120)

        total.answer_calls += question_trials
        answer_input = question_trials * (context_tokens + ANSWER_OVERHEAD_TOKENS)
        answer_output = question_trials * 120
        total.input_tokens += answer_input
        total.output_tokens += answer_output
        total.cost_usd += estimate_cost(answer_model, answer_input, answer_output)

        total.judge_calls += question_trials
        judge_input = question_trials * 200
        judge_output = question_trials * 40
        total.input_tokens += judge_input
        total.output_tokens += judge_output
        total.cost_usd += estimate_cost(judge_model or answer_model, judge_input, judge_output)

    total.cost_usd = round(total.cost_usd, 6)
    return total


def exceeds(estimate_cost_usd: float, max_cost: float | None) -> bool:
    return max_cost is not None and estimate_cost_usd > max_cost
