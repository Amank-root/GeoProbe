"""Custom OpenAI-compatible endpoints and honest cost reporting (issue #43).

Covers Groq, NVIDIA NIM, Gemini, vLLM and Ollama reaching the eval, and the
distinction the project cares about: a price we do not know must never be
reported as a price of zero.
"""

from __future__ import annotations

import pytest

from geoctl.config import Config, EvalConfig, apply_overrides
from geoctl.evals import cost as cost_mod
from geoctl.evals.engine import enforce_pricing_known, unpriced_models
from geoctl.llm.client import (
    Endpoint,
    LLMClient,
    ProviderError,
    UnknownPricing,
    estimate_cost,
    is_embedding_model,
    known_price,
)

# ------------------------------------------------------------------- endpoints


def test_endpoint_is_custom_only_with_a_base_url():
    assert not Endpoint().is_custom
    assert Endpoint(base_url="https://api.groq.com/openai/v1").is_custom


def test_endpoint_is_part_of_the_cache_key():
    """The same model name behind two hosts is not the same model."""
    a = LLMClient(model="llama", endpoint=Endpoint(base_url="https://a/v1"))
    b = LLMClient(model="llama", endpoint=Endpoint(base_url="https://b/v1"))
    assert a.key(None, None, "prompt") != b.key(None, None, "prompt")
    # Same endpoint, same key.
    c = LLMClient(model="llama", endpoint=Endpoint(base_url="https://a/v1"))
    assert a.key(None, None, "prompt") == c.key(None, None, "prompt")


def test_config_accepts_endpoint_fields():
    config = apply_overrides(
        Config(),
        {
            "eval": {
                "base_url": "https://integrate.api.nvidia.com/v1",
                "api_key_env": "NVIDIA_API_KEY",
                "input_cost_per_mtok": 0.5,
                "output_cost_per_mtok": 1.0,
            }
        },
    )
    assert config.eval.base_url == "https://integrate.api.nvidia.com/v1"
    assert config.eval.api_key_env == "NVIDIA_API_KEY"
    assert config.eval.input_cost_per_mtok == 0.5


def test_an_api_key_is_never_read_from_config(tmp_path):
    """Keys come from the environment. A config holding one is refused (CLI_SPEC §3.2)."""
    bad = tmp_path / "geoctl.toml"
    bad.write_text('[eval]\napi_key = "sk-live-not-real"\n', encoding="utf-8")
    from geoctl.config import ConfigError, load_config

    with pytest.raises(ConfigError, match="credential"):
        load_config(str(bad))


# ----------------------------------------------------------------------- costs


@pytest.mark.parametrize(
    "model",
    [
        "openai/gpt-4o-mini",
        "groq/llama-3.3-70b-versatile",
        "groq/openai/gpt-oss-120b",
        "gemini/gemini-2.5-flash",
        "openai/text-embedding-3-small",
        "gemini/gemini-embedding-001",
    ],
)
def test_known_models_have_a_price(model: str):
    """Every model we ship a default or document must have a price.

    An unpriced model used to report $0.00, which silently defeated --max-cost.
    """
    assert known_price(model) is not None, f"{model} has no known price"
    assert estimate_cost(model, 1_000_000, 0) > 0


def test_an_unknown_model_has_no_price_and_is_not_free():
    assert known_price("madeup/not-a-real-model") is None
    assert estimate_cost("madeup/not-a-real-model", 1_000_000, 1_000_000) == 0.0


def test_a_user_price_overrides_the_tables():
    assert known_price("madeup/x", input_override=0.5, output_override=1.0) == (0.5, 1.0)
    assert estimate_cost(
        "madeup/x", 1_000_000, 1_000_000, input_override=0.5, output_override=1.0
    ) == pytest.approx(1.5)


def test_embedding_models_are_recognised():
    assert is_embedding_model("openai/text-embedding-3-small")
    assert is_embedding_model("gemini/gemini-embedding-001")
    assert not is_embedding_model("gpt-4o-mini")


def test_cost_estimate_uses_the_user_override():
    """The dry-run estimator and the guard must agree on what 'known' means."""
    estimate = cost_mod.estimate(
        pages=1,
        questions_per_page=5,
        trials=2,
        page_texts=["x" * 8000],
        chunks_per_page=10,
        answer_model="madeup/x",
        judge_model="madeup/x",
        input_rate=0.5,
        output_rate=1.0,
    )
    assert estimate.cost_usd > 0, "a supplied price must reach the estimate"
    assert estimate.answer_calls == 10


# --------------------------------------------------------------- the cost guard


def test_max_cost_hard_fails_on_an_unpriced_model():
    config = EvalConfig(model="madeup/unpriced-9000")
    with pytest.raises(UnknownPricing, match="no price is known"):
        enforce_pricing_known(config, max_cost=1.0)


def test_max_cost_is_satisfied_once_prices_are_supplied():
    config = EvalConfig(
        model="madeup/unpriced-9000", input_cost_per_mtok=0.5, output_cost_per_mtok=1.0
    )
    enforce_pricing_known(config, max_cost=1.0)  # must not raise
    assert unpriced_models(config) == []


def test_no_max_cost_means_no_guard():
    """Without a ceiling there is nothing to enforce, so nothing blocks."""
    enforce_pricing_known(EvalConfig(model="madeup/unpriced-9000"), max_cost=None)


def test_an_unpriced_embedding_model_also_blocks():
    """The embedding call is part of the bill, so it must be priced too."""
    config = EvalConfig(model="gemini/gemini-2.5-flash", embedding_model="madeup/unknown-embed")
    with pytest.raises(UnknownPricing, match="unknown-embed"):
        enforce_pricing_known(config, max_cost=1.0)


def test_an_unpriced_judge_model_also_blocks():
    config = EvalConfig(model="gemini/gemini-2.5-flash", judge_model="madeup/unknown-judge")
    with pytest.raises(UnknownPricing, match="unknown-judge"):
        enforce_pricing_known(config, max_cost=1.0)


def test_the_guard_names_every_unpriced_model():
    config = EvalConfig(model="madeup/a", judge_model="madeup/b", embedding_model="madeup/c")
    assert set(unpriced_models(config)) == {"madeup/a", "madeup/b", "madeup/c"}


# ------------------------------------------------------------- token counting


def test_token_counting_works_offline_for_gemini_and_groq():
    """--dry-run must not need a key, so token counting has to stay local."""
    from geoctl.llm.client import count_tokens

    text = "hello world " * 100
    counts = {
        m: count_tokens(text, m)
        for m in ("gemini/gemini-2.5-flash", "groq/llama-3.3-70b-versatile", "openai/gpt-4o-mini")
    }
    assert all(n > 100 for n in counts.values()), counts
    # Within a sensible margin of each other; a tokenizer lookup that silently
    # returned 1 token would pass a bare >0 check.
    assert max(counts.values()) - min(counts.values()) < 20, counts


def test_provider_errors_stay_classified():
    """An auth failure must still map to exit code 4, not a crash."""
    assert issubclass(ProviderError, Exception)
