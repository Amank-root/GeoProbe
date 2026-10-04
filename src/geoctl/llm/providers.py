"""Which model to use when the user named none (ADR-012, issue #45).

The eval defaults to auto: it runs when a key is present. But "a key is present"
is not the same as "the default model is reachable". The default answerer was
hardcoded to `openai/gpt-4o-mini`, so a user with only `NVIDIA_API_KEY` in their
environment got an authentication failure instead of an eval — the headline
feature failed closed for every non-OpenAI provider.

This module is the single place that maps a key environment variable to a model
that key can actually call, plus the base URL when the provider needs one. The
config layer, `doctor`, and the eval's model resolution all read it, so the
"which provider am I talking to" answer cannot drift between them.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"


@dataclass(frozen=True)
class Provider:
    """A key we can detect, and a model that key can call.

    `base_url` is set for OpenAI-compatible hosts LiteLLM has no first-class
    provider for. Without it, naming the key is not enough: `nvidia/...` routes
    nowhere, and the user gets a provider error rather than an eval.
    """

    key_env: str
    model: str
    base_url: str | None = None
    embedding_model: str | None = None


# Order is preference order: the strongest general-purpose model we can reach
# with a single key comes first, and the OpenAI-compatible hosts that need an
# explicit base_url come later. A user with several keys set gets the first
# match, and can always override with --model.
PROVIDERS: tuple[Provider, ...] = (
    Provider(
        "OPENAI_API_KEY", "openai/gpt-4o-mini", embedding_model="openai/text-embedding-3-small"
    ),
    Provider(
        "ANTHROPIC_API_KEY",
        "anthropic/claude-haiku-4-5",
        embedding_model="gemini/gemini-embedding-001",
    ),
    Provider(
        "GEMINI_API_KEY", "gemini/gemini-2.5-flash", embedding_model="gemini/gemini-embedding-001"
    ),
    Provider(
        "GOOGLE_API_KEY",
        "gemini/gemini-2.5-flash",
        embedding_model="gemini/gemini-embedding-001",
    ),
    Provider("GROQ_API_KEY", "groq/llama-3.3-70b-versatile"),
    Provider("MISTRAL_API_KEY", "mistral/mistral-large-latest"),
    Provider("DEEPSEEK_API_KEY", "deepseek/deepseek-chat"),
    Provider("PERPLEXITYAI_API_KEY", "perplexity/sonar"),
    Provider("TOGETHERAI_API_KEY", "together_ai/Llama-3.3-70B-Instruct-Turbo"),
    Provider("OPENROUTER_API_KEY", "openrouter/openai/gpt-4o-mini"),
    Provider(
        "NVIDIA_API_KEY",
        "nvidia/nemotron-3.5-lightning-30b-a3b",
        base_url=NVIDIA_BASE_URL,
        embedding_model="nvidia/nemotron-3-embed-1b",
    ),
)


def key_matches(candidate: str, key_env: str) -> bool:
    """Does an environment variable name count as this provider's key?

    Exact match, or the documented key with a numeric suffix. `GEMINI_API_KEY_1`
    and `GEMINI_API_KEY_2` are how anyone holding two Gemini keys actually stores
    them, and treating those as "no key present" made the auto-eval silently skip
    for exactly the users who had configured a provider.
    """
    return candidate == key_env or candidate.startswith(f"{key_env}_")


def present_key_vars() -> list[str]:
    """Every set variable that names a provider key we recognise.

    Matched by the *base* name rather than a `endswith("_API_KEY")` test, because
    a suffixed key (`GEMINI_API_KEY_1`) does not end in `_API_KEY` — so filtering
    on the suffix silently excluded every second key a user owns, which is what
    made the auto-eval skip for them.
    """
    bases = [p.key_env for p in PROVIDERS]
    return sorted(
        name for name in os.environ if name and any(key_matches(name, base) for base in bases)
    )


def provider_for_key_var(name: str) -> Provider | None:
    for provider in PROVIDERS:
        if key_matches(name, provider.key_env):
            return provider
    return None


def detect() -> Provider | None:
    """The provider to use for an unconfigured run, or None when no key is set.

    Preference order is PROVIDERS order, so the answer does not depend on the
    order the user's shell happens to export variables in.
    """
    for provider in PROVIDERS:
        if os.environ.get(provider.key_env):
            return provider
    # Fall back to a suffixed key (`GEMINI_API_KEY_1`) so the first-party
    # providers still work when the canonical variable name is not used.
    for provider in PROVIDERS:
        if any(
            os.environ.get(name)
            for name in present_key_vars()
            if key_matches(name, provider.key_env)
        ):
            return provider
    return None


def known_key_vars() -> list[str]:
    """Canonical key variable names, for `doctor` and the config layer."""
    return [p.key_env for p in PROVIDERS]


def embedding_model_for(provider: Provider) -> str | None:
    return provider.embedding_model


__all__ = [
    "NVIDIA_BASE_URL",
    "PROVIDERS",
    "Provider",
    "detect",
    "embedding_model_for",
    "key_matches",
    "known_key_vars",
    "present_key_vars",
    "provider_for_key_var",
]
