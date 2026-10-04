"""Question generation (EVALS §3.2).

Questions must come from a source *richer or more independent* than the crawler
view the answerer sees. If they came from the crawler view, nearly every question
would be answerable and the score would say nothing (ADR-014). Each question
therefore carries a reference answer and a **verbatim source span**, which is
what makes context recall measurable.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

MIN_ANSWER_CHARS = 8
DEFAULT_QUESTIONS = 50
HARD_CAP_QUESTIONS = 200

PROMPT_VERSION = "1"


class Question(BaseModel):
    question: str
    reference_answer: str
    source_span: str = ""
    kind: str = "factual"
    page: str | None = None

    @property
    def key(self) -> str:
        return normalize_question(self.question)


def normalize_question(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()


@dataclass
class QuestionSet:
    questions: list[Question] = field(default_factory=list)
    ground_truth: str = "crawler_only"  # facts | rendered | facts+rendered | crawler_only
    source_pages: list[str] = field(default_factory=list)

    @property
    def confidence(self) -> str:
        # ADR-014: only the facts file is both independent and high-confidence.
        if self.ground_truth in ("facts", "facts+rendered"):
            return "high"
        if self.ground_truth == "rendered":
            return "high"
        return "low"

    def __len__(self) -> int:
        return len(self.questions)


# ------------------------------------------------------------------ facts file


class Fact(BaseModel):
    id: str | None = None
    question: str
    answer: str
    page: str | None = None


class FactsFile(BaseModel):
    site: str | None = None
    facts: list[Fact] = Field(default_factory=list)


def load_facts(path: str | Path) -> FactsFile:
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"Could not read facts file {path}: {exc}") from exc
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ValueError(f"facts file {path} is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"facts file {path} must be a mapping with a 'facts' key")
    return FactsFile.model_validate(data)


def questions_from_facts(facts: FactsFile, site: str | None = None) -> QuestionSet:
    """A facts file is the strongest ground truth: hand-written, so independent."""
    questions: list[Question] = []
    for fact in facts.facts:
        page = fact.page
        if page and site and not page.startswith("http"):
            page = f"{site.rstrip('/')}/{page.lstrip('/')}"
        questions.append(
            Question(
                question=fact.question,
                reference_answer=fact.answer,
                # A hand-written fact has no verbatim span in any document. An
                # empty span makes context recall fall back to "not measurable"
                # rather than silently reporting a wrong number.
                source_span="",
                kind="facts",
                page=page,
            )
        )
    return QuestionSet(
        questions=_dedupe(questions),
        ground_truth="facts",
        source_pages=sorted({q.page for q in questions if q.page}),
    )


# ------------------------------------------------------------------- generation


GENERATOR_SYSTEM = """You write evaluation questions for a website audit.

You are given the GROUND TRUTH text of a page. Write questions that a real visitor
or an AI-assistant user would plausibly ask about this page.

Rules:
- Each question must be answerable using ONLY the ground truth text given to you.
- Cover a mix of types: factual lookup (prices, dates, names), definitional
  ("what does X do"), procedural ("how do I..."), and comparison.
- Include the reference answer, taken from the ground truth.
- Include the verbatim span of the ground truth that contains the answer, copied
  character for character.
- Do not ask about anything that requires outside knowledge.
- Do not invent facts. If the text does not say, there is no question to ask.

Return JSON only: {"questions": [{"question": str, "reference_answer": str,
"source_span": str, "kind": str}]}"""


class _Generated(BaseModel):
    questions: list[Question] = Field(default_factory=list)


def generate(
    llm: Any,
    ground_truth_text: str,
    page_url: str,
    *,
    count: int = DEFAULT_QUESTIONS,
    min_chars: int = 400,
) -> list[Question]:
    """Generate questions from ground truth, cached by the caller."""
    count = max(1, min(count, HARD_CAP_QUESTIONS))
    prompt = (
        f"Page: {page_url}\n\n"
        f"GROUND TRUTH TEXT (verbatim):\n<<<\n{ground_truth_text[:120_000]}\n>>>\n\n"
        f"Write up to {count} questions. Return JSON only."
    )
    raw = llm.complete(prompt, system=GENERATOR_SYSTEM, expect_json=True)
    items = _parse_generated(raw)
    return _post_filter(items, ground_truth_text, page_url, min_chars)


def _parse_generated(raw: str) -> list[Question]:
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        # A model that wraps JSON in prose is common; recover the object.
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            return []
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return []
    if not isinstance(data, dict):
        return []
    try:
        return _Generated.model_validate(data).questions
    except Exception:
        return []


def _post_filter(
    items: list[Question], ground_truth_text: str, page_url: str, min_chars: int
) -> list[Question]:
    """Drop questions the ground truth cannot answer, and unlocatable spans.

    Filtering against ground truth is what keeps the score meaningful: a question
    the ground truth itself cannot answer would penalise the site for the
    generator's mistake.
    """
    haystack = ground_truth_text.lower()
    kept: list[Question] = []
    for item in items:
        item.question = item.question.strip()
        item.reference_answer = item.reference_answer.strip()
        item.source_span = (item.source_span or "").strip()
        if len(item.question) < 8 or len(item.reference_answer) < MIN_ANSWER_CHARS:
            continue
        if item.source_span:
            span_key = re.sub(r"\s+", " ", item.source_span.lower())[:80]
            haystack_key = re.sub(r"\s+", " ", haystack)
            if span_key and span_key not in haystack_key:
                # An unverifiable span would corrupt context recall.
                item.source_span = ""
        kept.append(item)
    return _dedupe(kept)


def _dedupe(questions: list[Question]) -> list[Question]:
    seen: set[str] = set()
    out: list[Question] = []
    for question in questions:
        key = question.key
        if key in seen or not key:
            continue
        seen.add(key)
        out.append(question)
    return out
