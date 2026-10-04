"""Configuration: CLI flags > env > project toml > user toml > defaults (CLI_SPEC §3).

Secrets never come from a toml file. If one is found, it is reported as an
error rather than quietly used (CLI_SPEC §3.2).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import tomllib
from pydantic import BaseModel, Field, ValidationError

CONFIG_ENV = "GEOCTL_CONFIG"
DEFAULT_USER_CONFIG = Path.home() / ".config" / "geoctl" / "config.toml"
PROJECT_CONFIG_NAME = "geoctl.toml"

PolicyMode = Literal["report", "fail", "ignore"]
EvalMode = Literal["auto", "true", "false"]


class AuditConfig(BaseModel):
    max_pages: int = 10
    bots: list[str] = Field(default_factory=list)  # empty = built-in registry
    policy: PolicyMode = "report"
    fail_under: float | None = None
    only: list[str] = Field(default_factory=list)
    skip: list[str] = Field(default_factory=list)


class FetchConfig(BaseModel):
    concurrency: int = 4
    timeout: float = 15.0
    max_bytes: int = 5_000_000
    max_redirects: int = 5
    allow_private: bool = False
    user_agent: str | None = None


class EvalConfig(BaseModel):
    enabled: EvalMode = "auto"
    model: str | None = None
    judge_model: str | None = None
    eval_pages: int = 3
    questions: int = 50
    trials: int = 3
    top_k: int = 5
    facts: str | None = None
    max_cost: float | None = None
    fail_under_eval: float | None = None
    fail_under_eval_margin: float = 15.0
    strict_eval: bool = False
    embedding_model: str | None = None


class TelemetryConfig(BaseModel):
    enabled: bool = False


class Config(BaseModel):
    audit: AuditConfig = Field(default_factory=AuditConfig)
    fetch: FetchConfig = Field(default_factory=FetchConfig)
    eval: EvalConfig = Field(default_factory=EvalConfig)
    telemetry: TelemetryConfig = Field(default_factory=TelemetryConfig)
    cache_dir: str | None = None
    sources: list[str] = Field(default_factory=list)
    # Not config-file keys: --render and --dry-run arrive only as flags, and the
    # pipeline reads them from here rather than threading them separately.
    render: bool = False
    dry_run: bool = False

    def public_dict(self) -> dict[str, Any]:
        """The effective settings, with no secrets (OUTPUT_SCHEMA §5)."""
        return {
            "max_pages": self.audit.max_pages,
            "bots": self.audit.bots,
            "policy": self.audit.policy,
            "fail_under": self.audit.fail_under,
            "only": self.audit.only,
            "skip": self.audit.skip,
            "concurrency": self.fetch.concurrency,
            "timeout": self.fetch.timeout,
            "max_bytes": self.fetch.max_bytes,
            "render": False,
        }


class ConfigError(Exception):
    """Usage error: exit code 2."""


# Anything that looks like a provider credential. Deliberately broad: a false
# positive costs one warning line, a missed key in a committed file is a leak.
_KEY_PATTERNS = (
    "api_key",
    "apikey",
    "secret",
    "token",
    "password",
    "passwd",
    "credential",
    "bearer",
    "sk-",
)

# Environment variables that supply provider keys. Read for presence only.
PROVIDER_KEY_VARS = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "MISTRAL_API_KEY",
    "GROQ_API_KEY",
    "TOGETHERAI_API_KEY",
    "OPENROUTER_API_KEY",
    "DEEPSEEK_API_KEY",
    "PERPLEXITYAI_API_KEY",
)


def _scan_for_keys(path: Path) -> list[str]:
    try:
        raw = path.read_text(encoding="utf-8", errors="replace").lower()
    except OSError:
        return []
    hits = []
    for line in raw.splitlines():
        for pattern in _KEY_PATTERNS:
            if pattern in line and "=" in line:
                value = line.split("=", 1)[1].strip().strip('"').strip("'")
                if value and value not in {"", "none", "null"} and not value.startswith("$"):
                    hits.append(line.split("=", 1)[0].strip())
                break
    return hits


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except FileNotFoundError:
        return {}
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"Could not read config {path}: {exc}") from exc
    leaked = _scan_for_keys(path)
    if leaked:
        raise ConfigError(
            f"{path} contains what look like credentials ({', '.join(sorted(set(leaked)))}). "
            "API keys do not belong in geoctl.toml — move them to environment variables "
            "or your OS keyring and commit only the config."
        )
    return data


def _coerce_env() -> dict[str, Any]:
    """Environment overrides, limited to GEOCTL_-prefixed names plus the
    documented provider keys (whose presence is what decides auto-eval)."""
    import os

    out: dict[str, Any] = {}
    if v := os.environ.get("GEOCTL_CACHE_DIR"):
        out["cache_dir"] = v
    if v := os.environ.get("GEOCTL_MAX_PAGES"):
        out.setdefault("audit", {})["max_pages"] = int(v)
    if v := os.environ.get("GEOCTL_CONCURRENCY"):
        out.setdefault("fetch", {})["concurrency"] = int(v)
    if v := os.environ.get("GEOCTL_TIMEOUT"):
        out.setdefault("fetch", {})["timeout"] = float(v)
    if v := os.environ.get("GEOCTL_MAX_BYTES"):
        out.setdefault("fetch", {})["max_bytes"] = int(v)
    if v := os.environ.get("GEOCTL_ALLOW_PRIVATE"):
        out.setdefault("fetch", {})["allow_private"] = v.lower() in {"1", "true", "yes"}
    if v := os.environ.get("GEOCTL_MODEL"):
        out.setdefault("eval", {})["model"] = v
    if v := os.environ.get("GEOCTL_JUDGE_MODEL"):
        out.setdefault("eval", {})["judge_model"] = v
    if v := os.environ.get("GEOCTL_QUESTIONS"):
        out.setdefault("eval", {})["questions"] = int(v)
    if v := os.environ.get("GEOCTL_TRIALS"):
        out.setdefault("eval", {})["trials"] = int(v)
    return out


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config(explicit: str | None = None) -> Config:
    """Merge every layer in precedence order. Invalid values raise ConfigError."""
    import os

    data: dict[str, Any] = {}
    sources: list[str] = ["defaults"]

    paths: list[Path] = []
    if explicit:
        paths.append(Path(explicit))
    elif os.environ.get(CONFIG_ENV):
        paths.append(Path(os.environ[CONFIG_ENV]))
    else:
        paths.append(Path.cwd() / PROJECT_CONFIG_NAME)
        paths.append(DEFAULT_USER_CONFIG)

    for path in paths:
        layer = _read_toml(path)
        if layer:
            data = _deep_merge(data, layer)
            sources.append(str(path))

    env_layer = _coerce_env()
    if env_layer:
        data = _deep_merge(data, env_layer)
        sources.append("env")

    data["sources"] = sources
    try:
        return Config.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"Invalid configuration: {exc}") from exc


def _strip_nested_none(data: dict[str, Any]) -> dict[str, Any]:
    """Drop None values at every depth.

    Typer passes None for any flag the user did not give, including inside nested
    sections, and a None cannot be validated into a typed model. "Not given" has
    to mean "leave the existing value alone", not "set it to nothing".
    """
    out: dict[str, Any] = {}
    for key, value in data.items():
        if value is None:
            continue
        if isinstance(value, dict):
            nested = _strip_nested_none(value)
            if nested:
                out[key] = nested
        else:
            out[key] = value
    return out


def apply_overrides(cfg: Config, overrides: dict[str, Any]) -> Config:
    """Apply CLI-flag overrides. `None` values mean "flag not given" and are ignored."""
    clean = _strip_nested_none(overrides)
    if not clean:
        return cfg
    return Config.model_validate(_deep_merge(cfg.model_dump(), clean))


def has_provider_key() -> bool:
    import os

    return any(os.environ.get(v) for v in PROVIDER_KEY_VARS)


def detected_provider_family() -> str | None:
    """Provider prefix only. Telemetry never carries a model string, because a
    model string can contain a custom endpoint and therefore a hostname."""
    import os

    for var in PROVIDER_KEY_VARS:
        if os.environ.get(var):
            return var.removesuffix("_API_KEY").lower()
    return None