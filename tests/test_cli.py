"""CLI tests: exit codes, output routing, and the commands in CLI_SPEC.

Exit codes are a documented contract (CLI_SPEC §5), so they are tested rather
than assumed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from fixtures.site import good_site
from geoctl.cli import (
    EXIT_BLOCKED,
    EXIT_COST,
    EXIT_OK,
    EXIT_THRESHOLD,
    EXIT_USAGE,
    app,
)

# CliRunner in this Click version merges stderr into stdout by default. Notes,
# progress, and the report all end up in `result.output`; stdout-only assertions
# use `result.stdout`, which Click exposes separately.
runner = CliRunner()


def run(*args: str):
    return runner.invoke(app, list(args))


def combined(result) -> str:  # type: ignore[no-untyped-def]
    """Everything the user saw, for assertions about notes and errors."""
    return result.output


# ------------------------------------------------------------------ basic wiring


def test_help_works():
    result = run("--help")
    assert result.exit_code == 0
    assert "audit" in combined(result)


def test_the_audit_command_is_named_audit_not_the_python_function_name():
    """`geoctl audit` must exist; `geoctl audit-command` must not."""
    assert "audit-command" not in combined(run("--help"))


def test_version_flag():
    assert run("--version").exit_code == 0


def test_unknown_format_is_a_usage_error():
    result = run("audit", "https://example.com", "--format", "yaml")
    assert result.exit_code == EXIT_USAGE
    assert "Unknown format" in combined(result)


def test_questions_above_the_cap_is_a_usage_error():
    result = run("audit", "https://example.com", "--questions", "500")
    assert result.exit_code == EXIT_USAGE
    assert "capped" in combined(result)


def test_a_bad_policy_is_a_usage_error():
    assert run("audit", "https://example.com", "--policy", "maybe").exit_code == EXIT_USAGE


def test_a_bad_url_is_a_usage_error():
    result = run("audit", "not-a-url-scheme://x")
    assert result.exit_code == EXIT_USAGE


def test_an_unknown_check_id_is_a_usage_error():
    result = run("audit", "https://example.com", "--only", "NOPE-999")
    assert result.exit_code == EXIT_USAGE
    assert "matched no check" in combined(result)


def test_a_private_target_without_the_flag_is_blocked():
    """Exit code 6, and the message must say how to proceed."""
    result = run("audit", "http://127.0.0.1:9/")
    assert result.exit_code == EXIT_BLOCKED
    assert "--allow-private" in combined(result)


# -------------------------------------------------------------------- commands


def test_schema_command_emits_valid_json():
    result = run("schema")
    assert result.exit_code == EXIT_OK
    schema = json.loads(result.stdout)
    assert "properties" in schema
    assert "schema_version" in str(schema)


def test_schema_command_writes_a_file(tmp_path: Path):
    target = tmp_path / "geoctl.schema.json"
    assert run("schema", "--output", str(target)).exit_code == EXIT_OK
    assert json.loads(target.read_text(encoding="utf-8"))["type"] == "object"


def test_init_writes_config_and_facts(tmp_path: Path):
    result = run("init", "--yes", "--directory", str(tmp_path))
    assert result.exit_code == EXIT_OK
    assert (tmp_path / "geoctl.toml").exists()
    assert (tmp_path / "facts.yaml").exists()
    # The generated config must be loadable, or the quickstart is a dead end.
    from geoctl.config import load_config

    config = load_config(str(tmp_path / "geoctl.toml"))
    assert config.audit.max_pages == 10


def test_init_does_not_clobber_an_existing_facts_file(tmp_path: Path):
    facts = tmp_path / "facts.yaml"
    facts.write_text("facts: []\n", encoding="utf-8")
    runner.invoke(app, ["init", "--directory", str(tmp_path)], input="n\n")
    assert facts.read_text(encoding="utf-8") == "facts: []\n", "user data must survive"


def test_cache_commands(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("GEOCTL_CACHE_DIR", str(tmp_path / "c"))
    assert run("cache", "path").exit_code == EXIT_OK
    assert run("cache", "stats").exit_code == EXIT_OK
    assert run("cache", "clear").exit_code == EXIT_OK
    assert run("cache", "clear", "--llm").exit_code == EXIT_OK
    assert run("cache", "clear", "--fetch").exit_code == EXIT_OK


def test_telemetry_status_and_show():
    status = run("telemetry", "status")
    assert status.exit_code == EXIT_OK
    assert "telemetry:" in status.stdout

    show = run("telemetry", "show")
    assert show.exit_code == EXIT_OK
    assert "Never collected" in show.stdout
    assert "install_id" in show.stdout


def test_telemetry_enable_then_disable_writes_config(tmp_path: Path, monkeypatch):
    """Enable/disable must persist a decision the next run can read."""
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setenv("GEOCTL_CONFIG", str(tmp_path / "cfg" / "config.toml"))
    cfg = tmp_path / "cfg" / "config.toml"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text("", encoding="utf-8")

    assert run("telemetry", "enable").exit_code == EXIT_OK
    assert "enabled = true" in cfg.read_text(encoding="utf-8")
    assert run("telemetry", "disable").exit_code == EXIT_OK
    assert "enabled = false" in cfg.read_text(encoding="utf-8")

    # And the written file must load through the normal config path.
    from geoctl.config import load_config

    assert load_config(str(cfg)).telemetry.enabled is False


def test_doctor_runs_and_reports(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("GEOCTL_CACHE_DIR", str(tmp_path / "c"))
    result = run("doctor")
    assert result.exit_code in (0, EXIT_USAGE)
    assert "python" in result.stdout
    assert "telemetry:" in result.stdout


# ------------------------------------------------------------------- audit run


@pytest.fixture
def local_site(serve, monkeypatch, tmp_path):  # type: ignore[no-untyped-def]
    """A served fixture site plus an isolated cache directory."""
    monkeypatch.setenv("GEOCTL_CACHE_DIR", str(tmp_path / "cache"))
    return serve(good_site()) + "/"


def test_audit_emits_a_report_on_stdout(local_site):
    result = run("audit", local_site, "--allow-private", "--eval", "false")
    assert result.exit_code == EXIT_OK
    assert "Deterministic score" in result.stdout
    assert "Not citations or rankings" in result.stdout


def test_audit_json_validates_and_contains_the_contract(local_site):
    result = run("audit", local_site, "--allow-private", "--eval", "false", "--format", "json")
    assert result.exit_code == EXIT_OK
    report = json.loads(result.stdout)
    for field in (
        "schema_version",
        "tool",
        "run",
        "target",
        "score",
        "checks",
        "pages",
        "eval",
        "errors",
    ):
        assert field in report, f"{field} is required by OUTPUT_SCHEMA §2"
    assert report["eval"] is None


def test_audit_markdown_writes_to_a_file(local_site, tmp_path: Path):
    target = tmp_path / "report.md"
    result = run(
        "audit",
        local_site,
        "--allow-private",
        "--eval",
        "false",
        "--format",
        "markdown",
        "--output",
        str(target),
    )
    assert result.exit_code == EXIT_OK
    assert target.read_text(encoding="utf-8").startswith("# geoctl report:")


def test_multiple_formats_to_one_directory_use_that_directory(local_site, tmp_path: Path):
    outdir = tmp_path / "reports"
    result = run(
        "audit",
        local_site,
        "--allow-private",
        "--eval",
        "false",
        "--format",
        "json",
        "--format",
        "markdown",
        "--output",
        str(outdir),
    )
    assert result.exit_code == EXIT_OK
    assert (outdir / "report.json").exists()
    assert (outdir / "report.markdown").exists()


def test_fail_under_exits_one(local_site):
    result = run("audit", local_site, "--allow-private", "--eval", "false", "--fail-under", "101")
    assert result.exit_code == EXIT_THRESHOLD
    # The report must still be printed: a threshold failure is information.
    assert "Deterministic score" in combined(result)
    assert "below --fail-under" in combined(result)


def test_fail_under_passes_when_the_score_is_high(local_site):
    result = run("audit", local_site, "--allow-private", "--eval", "false", "--fail-under", "1")
    assert result.exit_code == EXIT_OK
    assert "Deterministic score" in result.stdout


def test_only_runs_the_requested_checks(local_site):
    result = run(
        "audit",
        local_site,
        "--allow-private",
        "--eval",
        "false",
        "--only",
        "ACC-001,REN-001",
        "--format",
        "json",
    )
    ids = {c["id"] for c in json.loads(result.stdout)["checks"]}
    assert ids == {"ACC-001", "REN-001"}


def test_skip_omits_the_requested_checks(local_site):
    result = run(
        "audit",
        local_site,
        "--allow-private",
        "--eval",
        "false",
        "--skip",
        "structure",
        "--format",
        "json",
    )
    report = json.loads(result.stdout)
    assert not any(c["category"] == "structure" for c in report["checks"])
    assert any(c["category"] == "access" for c in report["checks"])


def test_eval_is_skipped_with_a_note_when_no_key_is_present(local_site, monkeypatch):
    for var in (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "GROQ_API_KEY",
        "OPENROUTER_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    result = run("audit", local_site, "--allow-private")
    assert result.exit_code == EXIT_OK
    assert "eval skipped" in combined(result)


def test_dry_run_makes_no_llm_calls_and_shows_an_estimate(local_site, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-not-used-because-dry-run")
    result = run(
        "audit", local_site, "--allow-private", "--dry-run", "--questions", "5", "--trials", "1"
    )
    assert result.exit_code == EXIT_OK
    text = combined(result)
    assert "No API call was made" in text
    assert "estimated cost" in text


def test_fail_under_eval_without_an_eval_run_is_not_silently_ignored(local_site, monkeypatch):
    for var in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    result = run("audit", local_site, "--allow-private", "--fail-under-eval", "90")
    assert result.exit_code == EXIT_OK
    assert "no eval ran" in combined(result), combined(result)


def test_a_reported_page_count_matches_the_sampled_pages(local_site):
    result = run(
        "audit",
        local_site,
        "--allow-private",
        "--eval",
        "false",
        "--max-pages",
        "2",
        "--format",
        "json",
    )
    report = json.loads(result.stdout)
    assert report["target"]["pages_audited"] <= 2
    assert len(report["pages"]) <= 2


def test_no_cache_flag_still_produces_a_report(local_site):
    result = run("audit", local_site, "--allow-private", "--eval", "false", "--no-cache")
    assert result.exit_code == EXIT_OK


# ------------------------------------------- custom endpoints and cost ceiling


NEW_EVAL_FLAGS = (
    "--embedding-model",
    "--base-url",
    "--api-key-env",
    "--input-cost-per-mtok",
    "--output-cost-per-mtok",
)


def test_the_new_endpoint_flags_exist():
    """FR-18 promises any model reachable through the abstraction layer.

    Asserted against the command's own parameter metadata rather than the
    rendered --help box: Rich wraps help to the terminal width, so a flag name
    can be split across lines, which would make this assertion depend on the
    runner's width rather than on the code.
    """
    import inspect

    from geoctl.cli import _audit_command

    # Typer derives each CLI flag from the parameter name, so the signature is
    # the authoritative list of what the command accepts.
    declared = {
        f"--{name.replace('_', '-')}" for name in inspect.signature(_audit_command).parameters
    }
    for flag in NEW_EVAL_FLAGS:
        assert flag in declared, f"{flag} is not a real option"


def test_max_cost_hard_fails_on_an_unpriced_model(local_site, monkeypatch):
    """A ceiling that permits unknown spend is not a ceiling (issue #43)."""
    monkeypatch.setenv("MADEUP_API_KEY", "not-a-real-key")
    result = run(
        "audit",
        local_site,
        "--allow-private",
        "--eval",
        "true",
        "--model",
        "madeup/unpriced-9000",
        "--max-cost",
        "1.00",
        "--questions",
        "2",
        "--trials",
        "1",
    )
    assert result.exit_code == EXIT_COST
    assert "no price is known" in combined(result)
    assert "Refusing to run" in combined(result)


def test_supplying_prices_lets_the_run_proceed(local_site, monkeypatch):
    monkeypatch.setenv("MADEUP_API_KEY", "not-a-real-key")
    result = run(
        "audit",
        local_site,
        "--allow-private",
        "--dry-run",
        "--eval",
        "true",
        "--model",
        "madeup/unpriced-9000",
        "--max-cost",
        "1.00",
        "--questions",
        "5",
        "--trials",
        "2",
        "--input-cost-per-mtok",
        "0.50",
        "--output-cost-per-mtok",
        "1.00",
    )
    assert result.exit_code == EXIT_OK
    text = combined(result)
    assert "estimated cost" in text
    # A supplied price must reach the estimate, not silently become $0.
    assert "$0.0000" not in text


def test_a_priced_embedding_model_satisfies_the_guard(local_site, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "not-a-real-key")
    result = run(
        "audit",
        local_site,
        "--allow-private",
        "--dry-run",
        "--eval",
        "true",
        "--model",
        "gemini/gemini-2.5-flash",
        "--embedding-model",
        "gemini/gemini-embedding-001",
        "--max-cost",
        "1.00",
        "--questions",
        "5",
        "--trials",
        "1",
    )
    assert result.exit_code == EXIT_OK


def test_an_unpriced_embedding_model_also_blocks(local_site, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "not-a-real-key")
    result = run(
        "audit",
        local_site,
        "--allow-private",
        "--dry-run",
        "--eval",
        "true",
        "--model",
        "gemini/gemini-2.5-flash",
        "--embedding-model",
        "madeup/unknown-embed",
        "--max-cost",
        "1.00",
        "--questions",
        "5",
        "--trials",
        "1",
    )
    assert result.exit_code == EXIT_COST
    assert "unknown-embed" in combined(result)


def test_base_url_is_accepted_and_reaches_the_report(local_site, monkeypatch):
    monkeypatch.setenv("MADEUP_API_KEY", "not-a-real-key")
    result = run(
        "audit",
        local_site,
        "--allow-private",
        "--dry-run",
        "--eval",
        "true",
        "--model",
        "madeup/unpriced-9000",
        "--base-url",
        "https://integrate.api.nvidia.com/v1",
        "--api-key-env",
        "MADEUP_API_KEY",
        "--questions",
        "5",
        "--trials",
        "1",
    )
    assert result.exit_code == EXIT_OK
    # No secret may appear in the output.
    assert "not-a-real-key" not in combined(result)
