"""Judging candidate answers against the reference (EVALS §3.5).

A different model family from the answerer is recommended, to reduce
self-preference bias. Verdicts are strict about factual equivalence and lenient
about wording.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .answer import NOT_FOUND

CORRECT = "correct"
PARTIAL = "partially_correct"
INCORRECT = "incorrect"
ABSTAINED = "abstained"
VERDICTS = (CORRECT, PARTIAL, INCORRECT, ABSTAINED)

JUDGE_SYSTEM = """You grade answers to questions about a website.

You are given a question, a reference answer, and a candidate answer produced by
another model using only retrieved excerpts.

Return JSON only:
{"verdict": "correct" | "partially_correct" | "incorrect" | "abstained",
 "rationale": "<one short sentence>"}

Rules:
- "correct": factually equivalent to the reference. Wording may differ freely.
- "partially_correct": some of the key information, but missing or wrong on a
  material part (a wrong number alongside a right one is partial only if the
  rest holds).
- "incorrect": contradicts the reference, or invents information. Counts as a
  hallucination.
- "abstained": the candidate said the answer was not found.

Be strict about facts and numbers. Be lenient about phrasing and extra
explanation. Judge only against the reference, never against your own knowledge
of the world."""


@dataclass
class Judgement:
    verdict: str
    rationale: str = ""

    @property
    def points(self) -> float:
        if self.verdict == CORRECT:
            return 1.0
        if self.verdict == PARTIAL:
            return 0.5
        return 0.0


def build_prompt(question: str, reference: str, candidate: str) -> str:
    return (
        f"Question: {question}\n\n"
        f"Reference answer: {reference}\n\n"
        f"Candidate answer: {candidate}\n\n"
        f"Grade the candidate. Return JSON only."
    )


def parse(raw: str, *, candidate_abstained: bool = False) -> Judgement:
    """Parse a judgement, defaulting conservatively when the model is unusable."""
    text = (raw or "").strip()

    verdict: str | None = None
    rationale = ""
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(0))
            except json.JSONDecodeError:
                data = None
        else:
            data = None
    if isinstance(data, dict):
        raw_verdict = str(data.get("verdict", "")).strip().lower().replace(" ", "_")
        if raw_verdict in VERDICTS:
            verdict = raw_verdict
        rationale = str(data.get("rationale", ""))[:400]

    if verdict is None:
        lowered = text.lower()
        for word in ("partially_correct", "partially correct"):
            if word in lowered:
                verdict = PARTIAL
                break
        else:
            for word in VERDICTS:
                if re.search(rf"\b{word}\b", lowered):
                    verdict = word
                    break

    if verdict is None:
        # An unparseable judge response must not be scored as correct.
        verdict = ABSTAINED if candidate_abstained else INCORRECT
        rationale = rationale or "judge output could not be parsed"
    return Judgement(verdict=verdict, rationale=rationale)


def judge(llm: object, question: str, reference: str, candidate: str,
          *, abstained: bool = False) -> Judgement:
    if candidate.strip().upper() == NOT_FOUND:
        return Judgement(verdict=ABSTAINED, rationale="candidate reported not found")
    prompt = build_prompt(question, reference, candidate)
    try:
        raw = llm.complete(prompt, system=JUDGE_SYSTEM, max_tokens=200, expect_json=True)  # type: ignore[attr-defined]
    except Exception as exc:
        return Judgement(verdict=ABSTAINED,
                         rationale=f"judge error: {type(exc).__name__}: {exc}")
    return parse(raw, candidate_abstained=abstained)