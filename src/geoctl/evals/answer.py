"""Answering from retrieved context only (EVALS §3.4).

Abstention is a valid, measured outcome, distinct from a wrong answer, and it is
usually the most useful signal the eval produces: it says the information was not
recoverable from what a crawler receives.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

NOT_FOUND = "NOT_FOUND"

# Reasoning models emit a chain of thought before the answer and count it
# against max_tokens. With the 300-token budget the answerer used, a reasoning
# model spends the whole budget thinking, returns finish_reason="length" with
# the trace as its content, and never produces an answer — so a fully answered
# question was scored as a miss (issue #46). Measured against
# nvidia/nemotron-3.5-lightning-30b-a3b: 300 tokens truncated, 800 completed.
#
# Raising the budget costs nothing on non-reasoning models, which stop early and
# bill only what they emit.
ANSWERER_MAX_TOKENS = 4000
JUDGE_MAX_TOKENS = 4000

ANSWERER_SYSTEM = f"""You answer questions using ONLY the retrieved context provided.

Rules, in priority order:
1. If the context does not contain the answer, reply exactly {NOT_FOUND}.
2. Otherwise answer in one sentence, using the context's wording where you can.
3. Quote the sentence from the context you used, after your answer, on a new line
   prefixed with "Used: ".
4. Do not use outside knowledge, and do not infer from what you know about the
   world. If it is not in the context, it is {NOT_FOUND}.
5. Never guess a number, date, or name.

Your whole output is read by an automated judge, so keep it short."""


@dataclass
class Candidate:
    question: str
    answer: str
    abstained: bool
    quoted: str = ""
    error: str | None = None


def build_prompt(question: str, chunks: list[tuple[Any, float]]) -> str:
    """The answerer sees only retrieved context — never the page, never the world."""
    blocks = []
    for index, (chunk, score) in enumerate(chunks, start=1):
        text = getattr(chunk, "text", chunk)
        blocks.append(f"[{index}] (relevance {score:.3f})\n{text}")
    context = "\n\n".join(blocks) if blocks else "(no context was retrieved)"
    return (
        f"Retrieved context:\n<<<\n{context}\n>>>\n\n"
        f"Question: {question}\n\n"
        f"Answer from the context alone."
    )


def parse(raw: str) -> Candidate:
    text = (raw or "").strip()
    quoted = ""
    match = re.search(r"^\s*Used:\s*(.+)$", text, re.MULTILINE)
    if match:
        quoted = match.group(1).strip()
        text = text[: match.start()].strip()

    if NOT_FOUND in text.upper():
        return Candidate(question="", answer=NOT_FOUND, abstained=True, quoted=quoted)

    # Strip any preamble the model added despite the instructions.
    answer = re.sub(r"^(answer|the answer is)\s*[:\-]\s*", "", text, flags=re.IGNORECASE)
    answer = answer.strip().strip('"').strip()
    return Candidate(question="", answer=answer, abstained=not answer, quoted=quoted)


def answer(llm: Any, question: str, chunks: list[tuple[Any, float]]) -> Candidate:
    """One answer from the retrieved context. Failures become abstentions-with-error."""
    prompt = build_prompt(question, chunks)
    try:
        completion = llm.complete(prompt, system=ANSWERER_SYSTEM, max_tokens=ANSWERER_MAX_TOKENS)
    except Exception as exc:
        return Candidate(
            question=question,
            answer=NOT_FOUND,
            abstained=True,
            error=f"{type(exc).__name__}: {exc}",
        )

    # A truncated response is not an answer. Recording it as a plain abstention
    # would blame the site for the model's token budget, so it is reported as an
    # error the runner counts separately (issue #46).
    if getattr(completion, "truncated", False):
        return Candidate(
            question=question,
            answer=NOT_FOUND,
            abstained=True,
            error=(
                f"answerer response hit the {ANSWERER_MAX_TOKENS}-token limit "
                "before producing an answer (finish_reason=length)"
            ),
        )

    candidate = parse(completion.text)
    candidate.question = question
    return candidate
