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
    # Groq published pay-as-you-go rates, USD per 1M tokens.
    "llama-3.3-70b-versatile": (0.59, 0.79),
    "llama-3.1-8b-instant": (0.05, 0.08),
    "llama-3.1-70b-versatile": (0.59, 0.79),
    "gpt-oss-20b": (0.10, 0.50),
    "gpt-oss-120b": (0.15, 0.75),
    # Gemini. gemini-embedding-001 is the current embedding model and charges on
    # input only; text-embedding-004 is the older 768-dimension model, kept
    # because existing reports may reference it.
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-pro": (1.25, 10.00),
    "gemini-embedding-001": (0.15, 0.00),
    "text-embedding-004": (0.025, 0.00),
    # Embedding models LiteLLM does not price, including our own default.
    # Without these the eval would report $0.00 for embedding and --max-cost
    # could not protect the user.
    "text-embedding-3-small": (0.02, 0.00),
    "text-embedding-3-large": (0.13, 0.00),
    "text-embedding-ada-002": (0.10, 0.00),
}

# Embedding models charge on input only, so an output rate of 0 is correct
# rather than missing. `is_embedding_model` lets the cost guard explain that a
# zero output figure is not an unknown price.
EMBEDDING_PREFIXES = (
    "text-embedding",
    "gemini-embedding",
    "embedding-001",
    "embedding-004",
    "embed-",
)


def is_embedding_model(model: str) -> bool:
    short = model.split("/")[-1].lower()
    return short.startswith(EMBEDDING_PREFIXES)


class ProviderError(Exception):
    """Exit code 4: missing or rejected provider credentials."""


class CostLimitExceeded(Exception):
    """Exit code 5."""


class UnknownPricing(Exception):
    """A spending ceiling was requested but the price is unknown.

    Raised instead of proceeding. A `--max-cost` guard that treats an unknown
    price as zero is not a ceiling: the user set a limit precisely to be
    stopped, and silently spending an unbounded amount is worse than failing
    (issue #43).
    """


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


@dataclass(frozen=True)
class Endpoint:
    """Where to send a request: an OpenAI-compatible host and its key.

    LiteLLM has first-class providers for OpenAI, Groq, Anthropic and others, so
    those need only a `provider/model` string. NVIDIA NIM and self-hosted
    vLLM/Ollama are absent from its provider list and are reachable only by
    passing an explicit base_url (issue #43).
    """

    base_url: str | None = None
    api_key: str | None = None

    @property
    def is_custom(self) -> bool:
        return bool(self.base_url)


@dataclass
class LLMClient:
    """A cached, retrying, usage-accounting chat client."""

    model: str
    temperature: float = 0.0
    seed: int | None = 7
    cache: Cache | None = None
    use_cache: bool = True
    usage: Usage = field(default_factory=Usage)
    endpoint: Endpoint = field(default_factory=Endpoint)
    # Explicit prices per 1M tokens, for models LiteLLM does not know about.
    input_cost_per_mtok: float | None = None
    output_cost_per_mtok: float | None = None
    # Model strings are part of the cache key only when two endpoints could
    # serve the same name differently.
    _recorded_cost: dict[str, float] = field(default_factory=dict)

    # ---------------------------------------------------------------- calls

    def key(self, *parts: Any) -> tuple[Any, ...]:
        """Cache key for a call. Public so it can be tested directly.

        The endpoint is part of it: the same model name served by two hosts is
        not the same model, and reusing a cached answer across them would be a
        reproducibility bug, not an optimisation.
        """
        return (
            self.model,
            self.temperature,
            self.seed,
            *parts,
            self.endpoint.base_url,
        )

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int | None = None,
        model: str | None = None,
        expect_json: bool = False,
    ) -> str:
        """One completion, cached. Returns the assistant's text."""
        target = model or self.model
        key = (target, *self.key(max_tokens, system, prompt))
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

        text, call_usage = self._call(
            target, prompt, system=system, max_tokens=max_tokens, expect_json=expect_json
        )
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

    def _call(
        self,
        model: str,
        prompt: str,
        *,
        system: str | None,
        max_tokens: int | None,
        expect_json: bool,
    ) -> tuple[str, Usage]:
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
                if self.endpoint.base_url:
                    kwargs["api_base"] = self.endpoint.base_url
                if self.endpoint.api_key:
                    kwargs["api_key"] = self.endpoint.api_key
                response = litellm.completion(**kwargs)
                text = _message_text(response)
                usage = _usage_from(response, model, self)
                return text, usage
            except Exception as exc:
                last_error = exc
                if attempt < MAX_RETRIES - 1:
                    time.sleep(BACKOFF_BASE**attempt)
        raise ProviderError(_classify(last_error))


def _message_text(response: Any) -> str:
    try:
        content = response.choices[0].message.content
    except (AttributeError, IndexError, KeyError) as exc:
        raise ProviderError(f"unexpected response shape: {type(response).__name__}") from exc
    return str(content or "").strip()


def _usage_from(response: Any, model: str, client: LLMClient | None = None) -> Usage:
    input_tokens = 0
    output_tokens = 0
    raw = getattr(response, "usage", None)
    if raw is not None:
        input_tokens = int(getattr(raw, "prompt_tokens", 0) or 0)
        output_tokens = int(getattr(raw, "completion_tokens", 0) or 0)
    cost = estimate_cost(
        model,
        input_tokens,
        output_tokens,
        input_override=(client.input_cost_per_mtok if client else None),
        output_override=(client.output_cost_per_mtok if client else None),
    )
    return Usage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost,
    )


def _classify(exc: Exception | None) -> str:
    if exc is None:  # pragma: no cover - unreachable in practice
        return "unknown provider error"
    text = str(exc).lower()
    name = type(exc).__name__
    if any(
        k in text
        for k in (
            "api key",
            "authentication",
            "unauthorized",
            "401",
            "invalid_api_key",
            "permission",
        )
    ):
        return f"authentication failed ({name}): {exc}"
    if any(k in text for k in ("rate limit", "429", "too many requests")):
        return f"rate limited after {MAX_RETRIES} attempts: {exc}"
    if any(k in text for k in ("context length", "too long", "maximum context")):
        return f"context too long: {exc}"
    return f"provider error after {MAX_RETRIES} attempts: {name}: {exc}"


def known_price(
    model: str,
    *,
    input_override: float | None = None,
    output_override: float | None = None,
) -> tuple[float, float] | None:
    """Price per 1M tokens for a model, or None when we do not know it.

    Resolution order: explicit user override, the local table, then LiteLLM's
    model table. Returning None matters: a model with no known price must not be
    reported as free. The override is consulted here too, so that the
    `--max-cost` guard and the cost estimator agree on what "known" means.
    """
    if input_override is not None and output_override is not None:
        return input_override, output_override
    short = model.split("/")[-1].lower()
    for prefix, (in_rate, out_rate) in FALLBACK_PRICING.items():
        if short.startswith(prefix):
            return in_rate, out_rate
    try:
        import litellm

        in_cost, out_cost = litellm.model_cost.get(model, (None, None))
        if in_cost is not None and out_cost is not None:
            # LiteLLM stores per-token prices; convert to per-million.
            return float(in_cost) * 1e6, float(out_cost) * 1e6
    except Exception:
        pass
    return None


def estimate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    *,
    input_override: float | None = None,
    output_override: float | None = None,
) -> float:
    """Estimated USD, or 0.0 when the price is genuinely unknown.

    Never presents an unknown price as a real one — callers check
    `known_price()` and report `cost_note` instead. Cost figures are always
    estimates, never billing (ADR-015).
    """
    if not input_tokens and not output_tokens:
        return 0.0

    if input_override is not None and output_override is not None:
        return round(
            (input_tokens / 1e6) * input_override + (output_tokens / 1e6) * output_override, 6
        )

    price = known_price(model, input_override=input_override, output_override=output_override)
    if price is None:
        return 0.0
    in_rate, out_rate = price
    return round((input_tokens / 1e6) * in_rate + (output_tokens / 1e6) * out_rate, 6)


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
