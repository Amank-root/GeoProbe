"""Provider detection and model resolution (issue #45).

The eval defaults to auto: it runs when a key is present. That promise was broken
for every provider except OpenAI — the model was hardcoded to `openai/gpt-4o-mini`,
so a user with only `NVIDIA_API_KEY` set got an authentication error from the
headline feature. These tests pin the detection, the model each key resolves to,
and the base URL for the OpenAI-compatible hosts LiteLLM cannot route on its own.
"""

from __future__ import annotations

import pytest

from geoctl.config import Config, EvalConfig, has_provider_key
from geoctl.evals.engine import (
    infer_api_key_env,
    resolve_embedding_model,
    resolve_endpoint,
    resolve_model,
)
from geoctl.llm import providers
from geoctl.llm.providers import NVIDIA_BASE_URL


@pytest.fixture(autouse=True)
def _clean(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in list(providers.known_key_vars()):
        monkeypatch.delenv(name, raising=False)
    for name in ("GEMINI_API_KEY_1", "GEMINI_API_KEY_2"):
        monkeypatch.delenv(name, raising=False)


def set_key(monkeypatch: pytest.MonkeyPatch, name: str, value: str = "k") -> None:
    monkeypatch.setenv(name, value)


# ------------------------------------------------------------------- detection


def test_a_non_openai_key_still_counts_as_a_key_present(monkeypatch):
    """The whole point: a key is a key, whoever owns it."""
    set_key(monkeypatch, "NVIDIA_API_KEY")
    assert has_provider_key()


@pytest.mark.parametrize(
    "key_env",
    [
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "GROQ_API_KEY",
        "MISTRAL_API_KEY",
        "DEEPSEEK_API_KEY",
        "PERPLEXITYAI_API_KEY",
        "TOGETHERAI_API_KEY",
        "OPENROUTER_API_KEY",
        "NVIDIA_API_KEY",
    ],
)
def test_every_known_provider_key_enables_the_eval(monkeypatch, key_env):
    """`--eval auto` must fire for every provider we document, not just OpenAI."""
    set_key(monkeypatch, key_env)
    assert has_provider_key()
    assert providers.detect() is not None


def test_no_key_means_no_eval():
    assert not has_provider_key()
    assert providers.detect() is None


def test_a_suffixed_key_counts(monkeypatch):
    """Two keys for one provider are normally stored as NAME_1 and NAME_2.

    Treating those as absent made the auto-eval skip for exactly the users who
    had a provider configured.
    """
    set_key(monkeypatch, "GEMINI_API_KEY_1")
    assert has_provider_key()
    detected = providers.detect()
    assert detected is not None
    assert detected.key_env == "GEMINI_API_KEY"


def test_an_unrelated_key_is_not_a_provider_key(monkeypatch):
    set_key(monkeypatch, "SOMETHING_ELSE_API_KEY")
    assert not has_provider_key()


def test_key_matching_does_not_over_match():
    """`MY_OPENAI_API_KEY` is somebody else's variable, not OpenAI's."""
    assert providers.key_matches("OPENAI_API_KEY", "OPENAI_API_KEY")
    assert providers.key_matches("OPENAI_API_KEY_2", "OPENAI_API_KEY")
    assert not providers.key_matches("MY_OPENAI_API_KEY", "OPENAI_API_KEY")
    assert not providers.key_matches("OPENAI_API_KEY", "GROQ_API_KEY")


def test_present_keys_reports_the_names_actually_set(monkeypatch):
    set_key(monkeypatch, "NVIDIA_API_KEY")
    set_key(monkeypatch, "GEMINI_API_KEY_1")
    assert providers.present_key_vars() == ["GEMINI_API_KEY_1", "NVIDIA_API_KEY"]


# ------------------------------------------------------------- model resolution


def test_a_non_openai_key_resolves_to_a_model_that_key_can_call(monkeypatch):
    """The regression: this used to resolve to openai/gpt-4o-mini regardless."""
    set_key(monkeypatch, "NVIDIA_API_KEY")
    assert resolve_model(EvalConfig()) == "nvidia/nemotron-3.5-lightning-30b-a3b"


def test_every_provider_model_is_routable():
    """Each model must carry a `provider/model` form LiteLLM can route.

    Not a case check on the key name: LiteLLM prefixes are lowercased and do not
    always equal the variable suffix (`TOGETHERAI_API_KEY` serves `together_ai/`).
    What matters is that the prefix is present and non-empty.
    """
    for provider in providers.PROVIDERS:
        assert "/" in provider.model, provider
        prefix = provider.model.split("/")[0]
        assert prefix and prefix == prefix.lower(), provider.model


def test_an_explicit_model_still_wins(monkeypatch):
    set_key(monkeypatch, "NVIDIA_API_KEY")
    assert resolve_model(EvalConfig(model="groq/llama-3.3-70b-versatile")) == (
        "groq/llama-3.3-70b-versatile"
    )


def test_no_key_still_resolves_to_a_default():
    """The documented default is kept when there is nothing to detect."""
    assert resolve_model(EvalConfig()) == "openai/gpt-4o-mini"


def test_a_model_without_a_provider_prefix_is_a_usage_error():
    from geoctl.evals.engine import EvalConfigError

    with pytest.raises(EvalConfigError, match="provider/model"):
        resolve_model(EvalConfig(model="gpt-4o-mini"))


# ------------------------------------------------------------ endpoint inference


def test_nvidia_gets_its_base_url_and_key_automatically(monkeypatch):
    """LiteLLM has no first-class NVIDIA provider, so api_base is required."""
    set_key(monkeypatch, "NVIDIA_API_KEY", "secret-nvidia")
    endpoint = resolve_endpoint(EvalConfig())
    assert endpoint.base_url == NVIDIA_BASE_URL
    assert endpoint.api_key == "secret-nvidia"


def test_a_first_party_provider_needs_no_base_url(monkeypatch):
    set_key(monkeypatch, "OPENAI_API_KEY", "secret-openai")
    endpoint = resolve_endpoint(EvalConfig())
    assert endpoint.base_url is None
    assert endpoint.api_key == "secret-openai"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://integrate.api.nvidia.com/v1", "NVIDIA_API_KEY"),
        ("https://api.groq.com/openai/v1", "GROQ_API_KEY"),
        ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
        ("http://localhost:8000/v1", "OPENAI_API_KEY"),
    ],
)
def test_a_base_url_alone_infers_its_key_variable(url, expected):
    """Passing --base-url without --api-key-env forwarded no key at all."""
    assert infer_api_key_env(url) == expected


def test_an_unknown_host_infers_nothing():
    """Guessing a variable name for an arbitrary host would send the wrong
    credential to a third party."""
    assert infer_api_key_env("https://llm.internal.example.com/v1") is None
    assert infer_api_key_env(None) is None


def test_an_explicit_api_key_env_is_never_overridden(monkeypatch):
    set_key(monkeypatch, "NVIDIA_API_KEY", "from-nvidia")
    set_key(monkeypatch, "MY_LLM_KEY", "from-mine")
    endpoint = resolve_endpoint(EvalConfig(api_key_env="MY_LLM_KEY"))
    assert endpoint.api_key == "from-mine"


# --------------------------------------------------------- embedding resolution


def test_the_embedding_model_follows_the_detected_provider(monkeypatch):
    """Otherwise retrieval silently degraded to lexical for non-OpenAI users."""
    set_key(monkeypatch, "NVIDIA_API_KEY")
    assert resolve_embedding_model(EvalConfig()) == "nvidia/nemotron-3-embed-1b"


def test_an_explicit_embedding_model_still_wins(monkeypatch):
    set_key(monkeypatch, "OPENAI_API_KEY")
    assert resolve_embedding_model(EvalConfig(embedding_model="gemini/gemini-embedding-001")) == (
        "gemini/gemini-embedding-001"
    )


def test_no_provider_means_no_embedding_model_and_no_key():
    """Nothing detected: retrieval falls back to lexical, which the report says."""
    assert resolve_embedding_model(EvalConfig()) is None


def test_every_provider_embedding_model_is_a_real_embedding_name():
    """Guards the `-embed` infix matcher from swallowing a chat model."""
    from geoctl.llm.client import is_embedding_model

    for provider in providers.PROVIDERS:
        if provider.embedding_model:
            assert is_embedding_model(provider.embedding_model), provider.embedding_model
        assert not is_embedding_model(provider.model), provider.model


# --------------------------------------------------------------- pricing layers


def test_nvidia_models_have_no_price_and_are_not_reported_as_free():
    """Free today, unknown to us. The difference is what --max-cost relies on."""
    from geoctl.llm.client import known_price

    for model in ("nvidia/nemotron-3.5-lightning-30b-a3b", "nvidia/nemotron-3-embed-1b"):
        assert known_price(model) is None, model


def test_the_cost_guard_refuses_an_nvidia_run_with_max_cost():
    from geoctl.evals.engine import enforce_pricing_known
    from geoctl.llm.client import UnknownPricing

    with pytest.raises(UnknownPricing, match="nvidia/nemotron"):
        enforce_pricing_known(EvalConfig(model="nvidia/nemotron-3.5-lightning-30b-a3b"), 1.0)


def test_glm_has_a_published_price():
    from geoctl.llm.client import known_price

    assert known_price("z-ai/glm-5.3-flash") == (0.15, 0.50)


def test_the_nvidia_embedding_model_is_recognised_as_an_embedding_model():
    """The guard labels unpriced models "(embedding)"; mislabelling misleads."""
    from geoctl.llm.client import is_embedding_model

    assert is_embedding_model("nvidia/nemotron-3-embed-1b")
    assert not is_embedding_model("nvidia/nemotron-3.5-lightning-30b-a3b")


# ---------------------------------------------------------------- config layer


def test_config_and_registry_agree_on_provider_keys():
    from geoctl.config import PROVIDER_KEY_VARS

    assert list(PROVIDER_KEY_VARS) == providers.known_key_vars()


def test_the_public_config_never_carries_a_key():
    cfg = Config()
    cfg.eval.api_key_env = "NVIDIA_API_KEY"
    dumped = repr(cfg.public_dict())
    assert "NVIDIA_API_KEY" not in dumped
