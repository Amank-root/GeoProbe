"""CLI surface of `geoctl generate` (ROADMAP M2, CLI_SPEC §2.6).

The generators themselves are covered in `test_generate.py`. What matters here is
the CLI contract: the three subcommands exist, produce files, and — the one
property worth an exit-code test — refuse to overwrite an existing file without
`--force`. Silently clobbering a hand-edited robots.txt would be data loss.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from fixtures.site import good_site
from geoctl.cli import EXIT_BLOCKED, EXIT_OK, EXIT_USAGE, app

# This Click version merges stderr into stdout, so `output` is everything the
# user saw and `stdout` is the report only. Matches tests/test_cli.py.
runner = CliRunner()


def run(*args: str):  # type: ignore[no-untyped-def]
    return runner.invoke(app, list(args))


def combined(result) -> str:  # type: ignore[no-untyped-def]
    return result.output


@pytest.fixture
def local_site(serve, monkeypatch, tmp_path):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("GEOCTL_CACHE_DIR", str(tmp_path / "cache"))
    return serve(good_site()) + "/"


def test_generate_lists_all_three_subcommands():
    result = run("generate", "--help")
    assert result.exit_code == EXIT_OK
    for name in ("llms-txt", "robots", "jsonld"):
        assert name in result.output


def test_generate_robots_writes_a_file(local_site, tmp_path: Path):
    target = tmp_path / "robots.txt"
    result = run("generate", "robots", local_site, "--allow-private", "--output", str(target))
    assert result.exit_code == EXIT_OK
    body = target.read_text(encoding="utf-8")
    assert "User-agent:" in body
    assert "GPTBot" in body


def test_generate_llms_txt_writes_a_file(local_site, tmp_path: Path):
    target = tmp_path / "llms.txt"
    result = run("generate", "llms-txt", local_site, "--allow-private", "--output", str(target))
    assert result.exit_code == EXIT_OK
    assert "# " in target.read_text(encoding="utf-8")


def test_generate_jsonld_writes_valid_json(local_site, tmp_path: Path):
    target = tmp_path / "site.jsonld"
    result = run(
        "generate",
        "jsonld",
        local_site,
        "--allow-private",
        "--output",
        str(target),
    )
    assert result.exit_code == EXIT_OK
    parsed = json.loads(target.read_text(encoding="utf-8"))
    assert parsed["@type"] == "Organization"


@pytest.mark.parametrize("subcommand", ["robots", "llms-txt", "jsonld"])
def test_an_existing_file_is_never_clobbered_without_force(local_site, tmp_path: Path, subcommand):
    """The safety property: a proposal must not destroy a real file."""
    target = tmp_path / f"{subcommand}.txt"
    target.write_text("HAND EDITED — do not lose this", encoding="utf-8")

    result = run("generate", subcommand, local_site, "--allow-private", "--output", str(target))

    assert result.exit_code == EXIT_USAGE
    assert target.read_text(encoding="utf-8") == "HAND EDITED — do not lose this"
    assert "--force" in combined(result)


@pytest.mark.parametrize("subcommand", ["robots", "llms-txt", "jsonld"])
def test_force_overwrites(local_site, tmp_path: Path, subcommand):
    target = tmp_path / f"{subcommand}.txt"
    target.write_text("old", encoding="utf-8")
    result = run(
        "generate", subcommand, local_site, "--allow-private", "--output", str(target), "--force"
    )
    assert result.exit_code == EXIT_OK
    assert target.read_text(encoding="utf-8") != "old"


def test_an_unknown_policy_is_a_usage_error(local_site, tmp_path: Path):
    result = run(
        "generate",
        "robots",
        local_site,
        "--allow-private",
        "--policy",
        "block-everything",
        "--output",
        str(tmp_path / "r.txt"),
    )
    assert result.exit_code == EXIT_USAGE
    assert "allow-all" in combined(result)


def test_an_unknown_jsonld_type_is_a_usage_error(local_site, tmp_path: Path):
    result = run(
        "generate",
        "jsonld",
        local_site,
        "--allow-private",
        "--type",
        "Product",
        "--output",
        str(tmp_path / "o.json"),
    )
    assert result.exit_code == EXIT_USAGE


def test_a_loopback_target_is_refused_without_allow_private(local_site, tmp_path: Path):
    """The SSRF guard still applies to generate, which fetches the site.

    Exit 6, the documented code for a safety refusal — not 1 (which reads as a
    threshold failure) and not 3 (which reads as the site being down).
    """
    result = run("generate", "robots", local_site, "--output", str(tmp_path / "r.txt"))
    assert result.exit_code == EXIT_BLOCKED
    assert not (tmp_path / "r.txt").exists()
    assert "allow-private" in combined(result)


def test_generated_output_says_it_is_a_proposal(local_site, tmp_path: Path):
    """The project's honesty commitment, at the point of generation."""
    result = run(
        "generate", "robots", local_site, "--allow-private", "--output", str(tmp_path / "r.txt")
    )
    lowered = result.stdout.lower()
    assert "proposal" in lowered
    assert "nothing here is verified" in lowered


def test_the_default_output_path_is_relative_not_absolute():
    """Default paths must not try to write at the filesystem root."""
    from geoctl.generate import generate_jsonld, generate_llms_txt, generate_robots

    paths = [
        generate_robots(site_url="https://x.test/").path,
        generate_llms_txt([], site_url="https://x.test/").path,
        generate_jsonld("Organization", site_url="https://x.test/").path,
    ]
    for path in paths:
        assert not path.startswith("/"), path
