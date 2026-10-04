"""A recorded LLM, so eval tests run with no API key and no network.

Responses are scripted by a substring of the prompt rather than by a hash of the
whole prompt. Keying on a hash would make every recorded test break on an
innocuous prompt-template edit; a substring keeps the recording meaningful while
tolerating rewording.

An unscripted prompt raises. That matters: if the eval silently skipped a stage,
the test must fail rather than pass vacuously.
"""

from __future__ import annotations

import json

from geoctl.llm.client import Completion


class SubstringScriptedLLM:
    """Matches scripted responses by substring of the prompt.

    Keying on the whole prompt hash makes a test brittle: any change to a prompt
    template would break every recorded test for no real reason. Substring
    matching keeps the recording meaningful while tolerating prompt edits.
    """

    def __init__(self) -> None:
        self.rules: list[tuple[str, str]] = []
        self.calls: list[tuple[str, str]] = []
        # Set to "length" to script a truncated (reasoning-trace) response, which
        # is how a real reasoning model behaves when its budget runs out.
        self.finish_reason = "stop"
        # Recorded max_tokens per call, so a test can assert the budget the
        # answerer and judge actually request.
        self.requested_budgets: list[int | None] = []

    def on(self, needle: str, response: str) -> SubstringScriptedLLM:
        self.rules.append((needle, response))
        return self

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int | None = None,
        model: str | None = None,
        expect_json: bool = False,
    ) -> Completion:
        self.calls.append((system or "", prompt))
        self.requested_budgets.append(max_tokens)
        for needle, response in self.rules:
            if needle in prompt:
                return Completion(text=response, finish_reason=self.finish_reason)
        raise AssertionError(f"No recorded response matched prompt containing {prompt[:120]!r}")

    def complete_text(self, prompt: str, **kwargs: object) -> str:
        return self.complete(prompt, **kwargs).text  # type: ignore[arg-type]


def generated_questions(rows: list[tuple[str, str, str]]) -> str:
    """A well-formed generator response: question, reference answer, verbatim span."""
    return json.dumps(
        {
            "questions": [
                {"question": q, "reference_answer": a, "source_span": s, "kind": "factual"}
                for q, a, s in rows
            ]
        }
    )


def judge_says(verdict: str, rationale: str = "graded") -> str:
    return json.dumps({"verdict": verdict, "rationale": rationale})


ANSWERABLE = "The Starter plan costs $19 per month."
REFERENCE = "$19 per month"
NOT_FOUND = "NOT_FOUND"


def answer_uses_context(text: str = ANSWERABLE) -> str:
    return f"{text}\nUsed: The Starter plan costs $19 per month."
