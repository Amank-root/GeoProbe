"""LiteLLM wrapper: retries, timeouts, usage accounting, disk caching (ADR-002).

Two properties matter and are enforced here rather than hoped for:

- Every call is cached by (model, params, prompt hash), so re-running an audit
  with unchanged inputs returns identical results at zero cost.
- Usage and cost are accumulated and always labelled as *estimates*. LiteLLM
  cost figures have not been verified against billing (ADR-015), so the report
  says "estimate" and this module never presents them as an invoice.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from ..cache import NS_LLM, Cache
from ..util import content_hash

# Per-call timeout. Long enough for a judge on a large context, short enough
# that a hung provider does not stall an audit.
CALL_TIMEOUT = 60.0
MAX_RETRIES = 3
BACKOFF_BASE = 1.5

# Last-resort price table in USD per 1M tokens, used only when LiteLLM has no
# entry for a model. Every figure is an estimate by policy (ADR-015).
FALLBACK_PRICING: dict[str, tuple[float, float]] = {
    # model prefix: (input per 1M, output per 1M)
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "o4-mini": (1.10, 4.40),
    "claude-3-5-haiku": (0.80, 4.00),
    "claude-sonnet-4": (3.00, 15.00),
    "gemini-2.0-flash": (0.10, 0.40),
}


class ProviderError(Exception):
    """Exit code 4: missing or rejected provider credentials."""


class CostLimitExceeded(Exception):
    """Exit code 5."""


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    cache_hits: int = 0
    calls: int = 0

    def add(self, other: Usage) -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cost_usd += other.cost_usd
        self.cache_hits += other.cache_hits
        self.calls += other.calls


@dataclass
class LLMClient:
    """A cached, retrying, usage-accounting chat client."""

    model: str
    temperature: float = 0.0
    seed: int | None = 7
    cache: Cache | None = None
    use_cache: bool = True
    usage: Usage = field(default_factory=Usage)
    _recorded_cost: dict[str, float] = field(default_factory=dict)

    # ---------------------------------------------------------------- calls

    def complete(self, prompt: str, *, system: str | None = None,
                 max_tokens: int | None = None, model: str | None = None,
                 expect_json: bool = False) -> str:
        """One completion, cached. Returns the assistant's text."""
        target = model or self.model
        key = (target, self.temperature, self.seed, max_tokens, system, prompt)
        cached = self.cache.get(NS_LLM, *key) if (self.use_cache and self.cache) else None
        if isinstance(cached, dict) and "text" in cached:
            replay = Usage(
                input_tokens=cached.get("input_tokens", 0),
                output_tokens=cached.get("output_tokens", 0),
                cost_usd=cached.get("cost_usd", 0.0),
                cache_hits=1,
            )
            self.usage.add(replay)
            return str(cached["text"])

        text, call_usage = self._call(target, prompt, system=system,
                                      max_tokens=max_tokens, expect_json=expect_json)
        self.usage.add(call_usage)
        if self.use_cache and self.cache:
            self.cache.set(
                NS_LLM,
                {
                    "text": text,
                    "input_tokens": call_usage.input_tokens,
                    "output_tokens": call_usage.output_tokens,
                    "cost_usd": call_usage.cost_usd,
                },
                *key,
            )
        return text

    def _call(self, model: str, prompt: str, *, system: str | None,
              max_tokens: int | None, expect_json: bool) -> tuple[str, Usage]:
        try:
            import litellm
        except ImportError as exc:  # pragma: no cover - litellm is a hard dependency
            raise ProviderError("litellm is not installed") from exc

        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        last_error: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                kwargs: dict[str, Any] = {
                    "model": model,
                    "messages": messages,
                    "temperature": self.temperature,
                    "timeout": CALL_TIMEOUT,
                }
                if self.seed is not None:
                    kwargs["seed"] = self.seed
                if max_tokens:
                    kwargs["max_tokens"] = max_tokens
                if expect_json:
                    kwargs["response_format"] = {"type": "json_object"}
                response = litellm.completion(**kwargs)
                text = _message_text(response)
                usage = _usage_from(response, model)
                return text, usage
            except Exception as exc:
                last_error = exc
                if attempt < MAX_RETRIES - 1:
                    time.sleep(BACKOFF_BASE ** attempt)
        raise ProviderError(_classify(last_error))


def _message_text(response: Any) -> str:
    try:
        content = response.choices[0].message.content
    except (AttributeError, IndexError, KeyError) as exc:
        raise ProviderError(f"unexpected response shape: {type(response).__name__}") from exc
    return str(content or "").strip()


def _usage_from(response: Any, model: str) -> Usage:
    input_tokens = 0
    output_tokens = 0
    raw = getattr(response, "usage", None)
    if raw is not None:
        input_tokens = int(getattr(raw, "prompt_tokens", 0) or 0)
        output_tokens = int(getattr(raw, "completion_tokens", 0) or 0)
    return Usage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=estimate_cost(model, input_tokens, output_tokens),
    )


def _classify(exc: Exception | None) -> str:
    if exc is None:  # pragma: no cover - unreachable in practice
        return "unknown provider error"
    text = str(exc).lower()
    name = type(exc).__name__
    if any(k in text for k in ("api key", "authentication", "unauthorized", "401",
                               "invalid_api_key", "permission")):
        return f"authentication failed ({name}): {exc}"
    if any(k in text for k in ("rate limit", "429", "too many requests")):
        return f"rate limited after {MAX_RETRIES} attempts: {exc}"
    if any(k in text for k in ("context length", "too long", "maximum context")):
        return f"context too long: {exc}"
    return f"provider error after {MAX_RETRIES} attempts: {name}: {exc}"


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimated USD. Never presented as billing (ADR-015).

    Prefers LiteLLM's own model map; falls back to a small local table.
    """
    if not input_tokens and not output_tokens:
        return 0.0
    try:
        import litellm

        in_cost, out_cost = litellm.cost_per_token(model=model,
                                                  prompt_tokens=input_tokens,
                                                  completion_tokens=output_tokens)
        total = float(in_cost or 0.0) + float(out_cost or 0.0)
        if total > 0:
            return round(total, 6)
    except Exception:
        pass

    short = model.split("/")[-1].lower()
    for prefix, (in_rate, out_rate) in FALLBACK_PRICING.items():
        if short.startswith(prefix):
            return round(
                (input_tokens / 1e6) * in_rate + (output_tokens / 1e6) * out_rate, 6
            )
    return 0.0


def count_tokens(text: str, model: str = "gpt-4o-mini") -> int:
    """Approximate token count for --dry-run, where no API call may happen."""
    try:
        import litellm

        return int(litellm.token_counter(model=model, text=text))
    except Exception:
        # ~4 chars per token is the standard rough approximation.
        return max(1, len(text) // 4)


def cache_key(model: str, prompt: str, **params: Any) -> str:
    return content_hash(model, prompt, params)