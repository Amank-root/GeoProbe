"""Config precedence, cache, SSRF guard, telemetry, and scoring invariants."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from geoctl import scoring, telemetry
from geoctl.cache import NS_LLM, Cache
from geoctl.config import ConfigError, apply_overrides, load_config
from geoctl.fetch import bots
from geoctl.fetch.ssrf import BlockedTarget, check_url, is_blocked_ip
from geoctl.models import CheckResult, CheckStatus

# ------------------------------------------------------------------- config


def test_defaults_match_the_cli_spec(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GEOCTL_CONFIG", raising=False)
    config = load_config()
    assert config.audit.max_pages == 10
    assert config.audit.policy == "report"
    assert config.fetch.concurrency == 4
    assert config.fetch.timeout == 15.0
    assert config.fetch.max_bytes == 5_000_000
    assert config.eval.enabled == "auto"
    assert config.eval.questions == 50
    assert config.eval.trials == 3
    assert config.eval.eval_pages == 3
    assert config.eval.top_k == 5
    assert config.eval.max_cost is None


def test_project_toml_is_read(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "geoctl.toml").write_text(
        "[audit]\nmax_pages = 3\npolicy = 'ignore'\n", encoding="utf-8"
    )
    config = load_config()
    assert config.audit.max_pages == 3
    assert config.audit.policy == "ignore"


def test_env_overrides_toml(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "geoctl.toml").write_text("[audit]\nmax_pages = 3\n", encoding="utf-8")
    monkeypatch.setenv("GEOCTL_MAX_PAGES", "7")
    assert load_config().audit.max_pages == 7


def test_flags_override_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GEOCTL_MAX_PAGES", "7")
    base = load_config()
    config = apply_overrides(base, {"audit": {"max_pages": 99}})
    assert config.audit.max_pages == 99


def test_unset_flags_do_not_override(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GEOCTL_MAX_PAGES", "7")
    base = load_config()
    # Typer passes None for flags the user did not give.
    assert apply_overrides(base, {"audit": {"max_pages": None}}).audit.max_pages == 7


def test_a_key_in_the_config_file_is_refused(tmp_path, monkeypatch):
    """CLI_SPEC §3.2: keys never come from a committed toml."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "geoctl.toml").write_text(
        '[eval]\nmodel = "openai/gpt-4o-mini"\napi_key = "sk-live-realsecret"\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="credential"):
        load_config()


def test_a_toml_pointing_at_an_env_var_is_allowed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "geoctl.toml").write_text(
        'token = "$OPENAI_API_KEY"\n', encoding="utf-8"
    )
    load_config()  # must not raise


def test_malformed_toml_is_a_usage_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "geoctl.toml").write_text("[audit\nmax_pages = 3\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config()


def test_public_dict_contains_no_secrets(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")
    public = json.dumps(load_config().public_dict())
    assert "sk-test" not in public
    assert "api_key" not in public


# -------------------------------------------------------------------- cache


def test_cache_round_trips(tmp_path):
    store = Cache(tmp_path)
    assert store.get(NS_LLM, "a", 1) is None
    store.set(NS_LLM, {"text": "hi"}, "a", 1)
    assert store.get(NS_LLM, "a", 1) == {"text": "hi"}
    store.close()


def test_cache_is_content_addressed(tmp_path):
    store = Cache(tmp_path)
    store.set(NS_LLM, "one", "same", "args")
    store.set(NS_LLM, "two", "same", "args")
    # Same key, so the second write wins. Reproducibility depends on this.
    assert store.get(NS_LLM, "same", "args") == "two"
    assert store.get(NS_LLM, "same", "other") is None
    store.close()


def test_namespaces_are_isolated(tmp_path):
    store = Cache(tmp_path)
    store.set(NS_LLM, "llm-value", "k")
    store.set("fetch", "fetch-value", "k")
    assert store.get(NS_LLM, "k") == "llm-value"
    assert store.clear(NS_LLM) == 1
    assert store.get(NS_LLM, "k") is None
    assert store.get("fetch", "k") == "fetch-value", "clearing llm must not drop fetches"
    store.close()


def test_a_broken_cache_degrades_to_misses(tmp_path):
    store = Cache(tmp_path / "cache", enabled=False)
    store.set(NS_LLM, "value", "k")
    assert store.get(NS_LLM, "k") is None
    assert store.stats()["enabled"] is False
    store.close()


def test_cache_reports_its_directory(tmp_path):
    store = Cache(tmp_path / "geoctl-cache")
    assert Path(store.stats()["directory"]).name == "geoctl-cache"
    store.close()


# --------------------------------------------------------------------- SSRF


@pytest.mark.parametrize(
    "ip",
    ["127.0.0.1", "10.1.2.3", "192.168.1.1", "172.16.5.5", "169.254.169.254",
     "0.0.0.0", "100.64.0.1", "::1", "fe80::1", "fc00::1"],
)
def test_private_and_reserved_addresses_are_blocked(ip):
    assert is_blocked_ip(ip)


@pytest.mark.parametrize("ip", ["8.8.8.8", "1.1.1.1", "93.184.216.34", "2606:4700::1"])
def test_public_addresses_are_allowed(ip):
    assert not is_blocked_ip(ip)


def test_loopback_is_refused_by_default():
    with pytest.raises(BlockedTarget, match="allow-private"):
        check_url("http://127.0.0.1:8000/")
    assert check_url("http://127.0.0.1:8000/", allow_private=True)


def test_the_metadata_endpoint_is_refused_explicitly():
    with pytest.raises(BlockedTarget):
        check_url("http://169.254.169.254/latest/meta-data/")


def test_non_http_schemes_are_refused():
    for url in ("file:///etc/passwd", "ftp://example.com/", "gopher://example.com/"):
        with pytest.raises(BlockedTarget):
            check_url(url)


def test_a_url_with_no_host_is_refused():
    with pytest.raises(BlockedTarget):
        check_url("http:///path")


# ---------------------------------------------------------------- bot registry


def test_bot_registry_has_no_duplicate_tokens():
    tokens = [b.robots_token for b in bots.BOTS]
    assert len(tokens) == len(set(tokens))


def test_default_bots_all_resolve():
    for name in bots.DEFAULT_BOT_NAMES:
        assert bots.known(name)
        assert bots.get(name).robots_token


def test_bot_lookup_is_case_insensitive_by_name_and_token():
    assert bots.get("gptbot").name == "GPTBot"
    assert bots.get("GPTBOT").name == "GPTBot"


def test_an_unknown_bot_name_is_an_error_not_a_silent_skip():
    """Silently dropping a typo would understate the problem being audited."""
    with pytest.raises(KeyError, match="Unknown bot"):
        bots.get("NotABot")


def test_every_bot_declares_a_purpose_and_docs_url():
    purposes = {"training", "search", "user_triggered", "other"}
    for bot in bots.BOTS:
        assert bot.purpose in purposes
        assert bot.docs_url.startswith("https://")


# -------------------------------------------------------------------- scoring


def _check(check_id: str, status: CheckStatus, weight: int, points: float = 0.0) -> CheckResult:
    return CheckResult(id=check_id, category="access", status=status, weight=weight,
                       points=points)


def test_score_is_bounded_zero_to_one_hundred():
    checks = [
        _check("ACC-002", "pass", 30, 30),
        _check("ACC-001", "pass", 25, 25),
        _check("ACC-003", "pass", 20, 20),
    ]
    report = scoring.score_checks(checks)
    assert report.overall == 100.0
    assert report.max == 100.0


def test_all_failures_score_zero():
    checks = [_check("ACC-002", "fail", 30), _check("ACC-001", "fail", 25)]
    assert scoring.score_checks(checks).overall == 0.0


def test_skipped_checks_leave_the_denominator():
    """An inapplicable check must not silently lower the score."""
    with_skip = scoring.score_checks(
        [_check("ACC-002", "pass", 30, 30), _check("ACC-001", "skip", 25)]
    )
    without = scoring.score_checks([_check("ACC-002", "pass", 30, 30)])
    assert with_skip.overall == without.overall == 100.0
    assert with_skip.categories["access"].max == 30.0


def test_informational_checks_cannot_move_the_score():
    checks = [_check("STR-001", "fail", 0), _check("ACC-002", "pass", 30, 30)]
    report = scoring.score_checks(checks)
    assert report.overall == 100.0
    assert "structure" not in report.categories


def test_a_partially_failing_site_lands_between_the_bounds():
    checks = [_check("ACC-002", "pass", 30, 30), _check("ACC-001", "fail", 25)]
    assert 50.0 < scoring.score_checks(checks).overall < 60.0


def test_top_findings_leads_with_failures():
    checks = [
        _check("STR-001", "warn", 0),
        _check("REN-001", "fail", 20),
        _check("ACC-002", "fail", 30),
    ]
    assert [c.id for c in scoring.top_findings(checks)] == ["ACC-002", "REN-001", "STR-001"]


# ------------------------------------------------------------------ telemetry


def test_payload_contains_only_allow_listed_fields():
    event = telemetry.Event(
        command="audit", tool_version="0.1.0", install_id="abc",
        flags_used=["--eval", "--format=json"], pages=10, duration_ms=4200,
    )
    payload = event.payload()
    assert set(payload) <= telemetry.ALLOWED_FIELDS
    assert "format=json" not in payload["flags_used"], "flag values can be URLs"
    assert payload["flags_used"] == ["--eval", "--format"]


def test_payload_carries_no_content_or_identifiers():
    import socket

    event = telemetry.Event(command="audit", tool_version="0.1.0", install_id="abc")
    blob = json.dumps(event.payload())
    assert socket.gethostname() not in blob
    for banned in ("http://", "https://", ".com", "path", "OPENAI", "sk-"):
        assert banned not in blob


def test_do_not_track_wins_over_everything(monkeypatch):
    monkeypatch.setenv("DO_NOT_TRACK", "1")
    monkeypatch.setenv("GEOCTL_TELEMETRY", "1")
    state = telemetry.status(config_enabled=True)
    assert state["enabled"] is False
    assert "DO_NOT_TRACK" in state["reason"]


def test_telemetry_is_off_in_ci_without_an_explicit_opt_in(monkeypatch):
    monkeypatch.delenv("DO_NOT_TRACK", raising=False)
    monkeypatch.delenv("GEOCTL_TELEMETRY", raising=False)
    monkeypatch.setenv("CI", "true")
    state = telemetry.status(config_enabled=True)
    assert state["enabled"] is False
    assert "CI" in state["reason"]


def test_explicit_env_opt_in_enables_it(monkeypatch):
    monkeypatch.delenv("DO_NOT_TRACK", raising=False)
    monkeypatch.setenv("GEOCTL_TELEMETRY", "1")
    monkeypatch.setenv("GEOCTL_TELEMETRY_ENDPOINT", "https://example.invalid/collect")
    assert telemetry.status(config_enabled=False)["enabled"] is True


def test_off_by_default():
    assert telemetry.status(config_enabled=None)["enabled"] is False


def test_debug_mode_prints_instead_of_sending(monkeypatch, capsys):
    monkeypatch.setenv("GEOCTL_TELEMETRY_DEBUG", "1")
    event = telemetry.Event(command="audit", tool_version="0.1.0", install_id="abc")
    assert telemetry.send(event, enabled=True) is False
    assert "telemetry payload" in capsys.readouterr().err


def test_send_is_silent_when_disabled():
    event = telemetry.Event(command="audit", tool_version="0.1.0", install_id="abc")
    assert telemetry.send(event, enabled=False) is False


def test_install_id_is_stable_and_rotatable(tmp_path):
    first = telemetry.load_install_id(tmp_path, create=True)
    assert first
    assert telemetry.load_install_id(tmp_path) == first
    second = telemetry.rotate_install_id(tmp_path)
    assert second != first, "rotation is how a user requests deletion"


def test_sample_payload_validates_against_the_allow_list():
    assert set(json.loads(telemetry.sample_payload())) <= telemetry.ALLOWED_FIELDS


def test_telemetry_module_imports_no_audit_models():
    """The module must be structurally unable to carry audit content."""
    source = Path(telemetry.__file__).read_text(encoding="utf-8")
    assert "from .models" not in source
    assert "from .extract" not in source
    assert "from .checks" not in source


def test_buckets_are_coarse():
    event = telemetry.Event(command="audit", tool_version="0.1.0", install_id="a", pages=7)
    assert event.payload()["pages_bucket"] == "6-10"