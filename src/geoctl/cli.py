"""geoctl CLI: Typer wiring only (CLI_SPEC).

Exit codes are the contract (CLI_SPEC §5), so they are defined once here and
every command returns them rather than raising SystemExit from deep in the
stack.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any

import typer
from rich.console import Console

from . import __version__
from . import report as report_mod
from . import telemetry as telemetry_mod
from .audit import (
    BlockedTarget,
    InvalidUrl,
    Unreachable,
    audit,
    build_corpora,
    build_corpora_crawler_only,
    build_report,
    normalize_url,
)
from .cache import NS_EMBED, NS_EXTRACT, NS_FETCH, NS_LLM, Cache
from .checks import UnknownCheck
from .config import ConfigError, apply_overrides, has_provider_key, load_config
from .evals import engine as eval_engine
from .evals import load_facts
from .fetch.ssrf import BlockedTarget as SSRFBlocked
from .llm.client import CostLimitExceeded, ProviderError

EXIT_OK = 0
EXIT_THRESHOLD = 1
EXIT_USAGE = 2
EXIT_UNREACHABLE = 3
EXIT_AUTH = 4
EXIT_COST = 5
EXIT_BLOCKED = 6
EXIT_INTERNAL = 70

app = typer.Typer(
    name="geoctl",
    help="Audit whether AI systems can reach, read, and answer from your website.",
    no_args_is_help=True,
    add_completion=False,
)

# Rich handles all human-facing output. The report itself goes to stdout through
# plain writes, never through Rich: Rich would wrap long lines, interpret square
# brackets as markup, and emit ANSI codes, any of which would corrupt JSON.
# CLI_SPEC §6 requires stdout to carry the report and nothing else.
_NO_COLOR = os.environ.get("NO_COLOR") is not None


def emit(text: str) -> None:
    """Write report or command output to stdout, unmodified."""
    sys.stdout.write(text)
    if not text.endswith("\n"):
        sys.stdout.write("\n")
    sys.stdout.flush()


def _version_callback(value: bool) -> None:
    if value:
        emit(__version__)
        raise typer.Exit(EXIT_OK)


# Runtime values of the global flags, set by the callback below. These start as
# plain defaults rather than Typer OptionInfo sentinels: an unconsumed OptionInfo
# is truthy, so `if not _quiet` would suppress every note in the CLI.
SETTINGS: dict[str, Any] = {"config": None, "verbose": 0, "quiet": False}


@app.callback(context_settings={"help_option_names": ["-h", "--help"]})
def global_options(
    config: Path | None = typer.Option(None, "--config", help="Use a specific config file"),
    verbose: int = typer.Option(0, "-v", "--verbose", count=True),
    quiet: bool = typer.Option(False, "-q", "--quiet", help="Errors only"),
    version: bool | None = typer.Option(
        None,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Print the version and exit",
    ),
) -> None:
    """Audit whether AI systems can reach, read, and answer from your website."""
    SETTINGS["config"] = config
    SETTINGS["verbose"] = verbose
    SETTINGS["quiet"] = quiet


def _err_console() -> Console:
    """A Console bound to the stderr in effect right now."""
    return Console(stderr=True, no_color=_NO_COLOR)


def _err(message: str) -> None:
    _err_console().print(f"[red]error:[/red] {message}")


def _config_file() -> str | None:
    value = SETTINGS.get("config")
    return str(value) if value else None


def _note(message: str) -> None:
    if not SETTINGS["quiet"]:
        _err_console().print(f"[dim]{message}[/dim]")


def _write_report(report: Any, formats: list[str], output: str | None) -> None:
    """Emit the report on stdout (or to a file/dir) and nowhere else.

    stdout carries the report only, so logs and progress must stay on stderr
    (CLI_SPEC §6).
    """
    if output and len(formats) > 1:
        base = Path(output)
        base.mkdir(parents=True, exist_ok=True)
        for fmt in formats:
            path = base / f"report.{fmt}"
            path.write_text(report_mod.render(fmt, report), encoding="utf-8")
            _note(f"wrote {path}")
        return
    for fmt in formats:
        text = report_mod.render(fmt, report)
        if output:
            Path(output).write_text(text, encoding="utf-8")
            _note(f"wrote {output}")
        else:
            emit(text)


def _audit_command(
    url: str = typer.Argument(..., help="The site to audit"),
    max_pages: int = typer.Option(None, help="Pages to audit (default 10)"),
    bots: str = typer.Option(None, help="Comma-separated bot names to simulate"),
    format: list[str] = typer.Option(
        ["terminal"], "--format", "-f", help="terminal | json | markdown (repeatable)"
    ),
    output: str = typer.Option(None, "--output", "-o", help="Write the report to a file"),
    fail_under: float = typer.Option(None, help="Exit 1 if the deterministic score < N"),
    fail_under_eval: float = typer.Option(None, help="Exit 1 if answerability < N (needs an eval)"),
    render: bool = typer.Option(
        False, "--render/--no-render", help="Also fetch with a browser for no-JS vs rendered"
    ),
    allow_private: bool = typer.Option(
        False, "--allow-private", help="Allow private/loopback targets"
    ),
    concurrency: int = typer.Option(None, help="Max concurrent requests (default 4)"),
    timeout: float = typer.Option(None, help="Per-request timeout in seconds (default 15)"),
    max_bytes: int = typer.Option(None, help="Max response size (default 5000000)"),
    no_cache: bool = typer.Option(False, "--no-cache", help="Ignore cache reads"),
    only: str = typer.Option(None, help="Run only these check IDs or categories"),
    skip: str = typer.Option(None, help="Skip these check IDs or categories"),
    policy: str = typer.Option(
        None, help="How deliberate AI-bot blocks are treated: report | fail | ignore"
    ),
    # eval
    eval_mode: str = typer.Option("auto", "--eval", help="auto | true | false"),
    model: str = typer.Option(None, help="Answerer model (LiteLLM format)"),
    judge_model: str = typer.Option(None, help="Judge model"),
    eval_pages: int = typer.Option(None, help="Pages evaluated (default 3)"),
    questions: int = typer.Option(None, help="Questions per page (default 50, max 200)"),
    trials: int = typer.Option(None, help="Repeated trials (default 3)"),
    top_k: int = typer.Option(None, help="Chunks retrieved per question (default 5)"),
    facts: str = typer.Option(None, help="Facts file (YAML) used as ground truth"),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Print estimated tokens and cost; make no LLM calls"
    ),
    max_cost: float = typer.Option(None, help="Abort before exceeding this estimated cost"),
    fail_under_eval_margin: float = typer.Option(None, help="Do not gate on a CI wider than this"),
    strict_eval: bool = typer.Option(
        False, "--strict-eval", help="Fail on a threshold even on a wide CI"
    ),
) -> None:
    """Audit a URL. Works with no API key; the eval runs when a key is present."""
    formats = [f.strip().lower() for f in (format or ["terminal"])]
    for fmt in formats:
        if fmt not in report_mod.FORMATS:
            _err(f"Unknown format {fmt!r}; choose from {', '.join(report_mod.FORMATS)}")
            raise typer.Exit(EXIT_USAGE)
    if questions is not None and questions > 200:
        _err(
            "--questions is capped at 200; a larger sample costs more without "
            "resolving more (EVALS §4.2)"
        )
        raise typer.Exit(EXIT_USAGE)

    overrides: dict[str, Any] = {
        "audit": {},
        "fetch": {},
        "eval": {},
        "render": render,
        "dry_run": dry_run,
    }
    if max_pages is not None:
        overrides["audit"]["max_pages"] = max_pages
    if bots:
        overrides["audit"]["bots"] = [b.strip() for b in bots.split(",") if b.strip()]
    if policy:
        if policy not in ("report", "fail", "ignore"):
            _err("--policy must be report, fail, or ignore")
            raise typer.Exit(EXIT_USAGE)
        overrides["audit"]["policy"] = policy
    if fail_under is not None:
        overrides["audit"]["fail_under"] = fail_under
    if only:
        overrides["audit"]["only"] = [t.strip() for t in only.split(",")]
    if skip:
        overrides["audit"]["skip"] = [t.strip() for t in skip.split(",")]
    if concurrency is not None:
        overrides["fetch"]["concurrency"] = concurrency
    if timeout is not None:
        overrides["fetch"]["timeout"] = timeout
    if max_bytes is not None:
        overrides["fetch"]["max_bytes"] = max_bytes
    if allow_private:
        overrides["fetch"]["allow_private"] = True
    overrides["eval"]["enabled"] = eval_mode
    for key, value in (
        ("model", model),
        ("judge_model", judge_model),
        ("questions", questions),
        ("trials", trials),
        ("top_k", top_k),
        ("eval_pages", eval_pages),
        ("fail_under_eval", fail_under_eval),
        ("fail_under_eval_margin", fail_under_eval_margin),
        ("max_cost", max_cost),
        ("facts", facts),
    ):
        if value is not None:
            overrides["eval"][key] = value
    overrides["eval"]["strict_eval"] = strict_eval or None

    try:
        base = load_config(_config_file())
        config = apply_overrides(base, overrides)
    except ConfigError as exc:
        _err(str(exc))
        raise typer.Exit(EXIT_USAGE) from exc

    cache = Cache(config.cache_dir)
    try:
        state = asyncio.run(audit(config, url, cache=cache, use_cache=not no_cache))
    except (InvalidUrl, UnknownCheck, eval_engine.EvalConfigError) as exc:
        _err(str(exc))
        raise typer.Exit(EXIT_USAGE) from exc
    except (BlockedTarget, SSRFBlocked) as exc:
        _err(str(exc))
        raise typer.Exit(EXIT_BLOCKED) from exc
    except Unreachable as exc:
        _err(str(exc))
        raise typer.Exit(EXIT_UNREACHABLE) from exc

    eval_result = None
    eval_error: str | None = None
    eval_costs: list[str] = []

    try:
        eval_result, eval_error, eval_costs = _maybe_eval(
            config, state, cache, use_cache=not no_cache
        )
    except ProviderError as exc:
        _err(str(exc))
        raise typer.Exit(EXIT_AUTH) from exc
    except CostLimitExceeded as exc:
        _err(str(exc))
        raise typer.Exit(EXIT_COST) from exc
    finally:
        for line in eval_costs:
            _note(line)
        cache.close()

    if eval_error:
        _note(f"eval skipped: {eval_error}")

    report = build_report(state, config, eval_result=eval_result)
    _write_report(report, formats, output)

    # Threshold decisions last, so the report is always printed first.
    if config.audit.fail_under is not None and report.score.overall < config.audit.fail_under:
        _err(
            f"deterministic score {report.score.overall:g} is below "
            f"--fail-under {config.audit.fail_under:g}"
        )
        raise typer.Exit(EXIT_THRESHOLD)
    if config.eval.fail_under_eval is not None and eval_result is not None:
        should_fail, note = eval_engine.decide_threshold(
            eval_result,
            fail_under=config.eval.fail_under_eval,
            margin=config.eval.fail_under_eval_margin,
            strict=config.eval.strict_eval,
        )
        if note:
            _note(note)
        if should_fail:
            mean = eval_result.answerability.get("mean", 0.0)
            _err(
                f"answerability {mean:.1f} is below --fail-under-eval "
                f"{config.eval.fail_under_eval:g}"
            )
            raise typer.Exit(EXIT_THRESHOLD)
    elif config.eval.fail_under_eval is not None:
        _note(
            "--fail-under-eval was given but no eval ran, so it was not applied. "
            "A threshold needs an eval to compare against."
        )
    raise typer.Exit(EXIT_OK)


def _maybe_eval(
    config: Any, state: Any, cache: Cache, *, use_cache: bool
) -> tuple[Any, str | None, list[str]]:
    """Run the eval when it should, and explain it plainly when it should not.

    The eval is the headline, so it defaults to auto: run it when a key is
    present, skip with a one-line note when none is found (ADR-012).
    """
    notes: list[str] = []
    if config.eval.enabled == "false":
        return None, "disabled with --eval false", notes

    if config.eval.enabled == "auto" and not has_provider_key():
        return (
            None,
            "no LLM key found, so the eval did not run. Set OPENAI_API_KEY (or "
            "another provider's key) to include it, or pass --facts with a facts "
            "file. The deterministic checks above need no key.",
            notes,
        )

    corpora = build_corpora(state, config.eval.eval_pages)
    rendered_available = bool(corpora)
    if not corpora:
        corpora = build_corpora_crawler_only(state, config.eval.eval_pages)
    if not corpora:
        return None, "no pages had extractable text to evaluate", notes

    facts_file = None
    if config.eval.facts:
        try:
            facts_file = load_facts(config.eval.facts)
        except ValueError as exc:
            return None, str(exc), notes

    plan = eval_engine.plan(
        config.eval,
        corpora,
        facts_questions=len(facts_file.facts) if facts_file else None,
        rendered_available=rendered_available,
    )
    if plan.note:
        notes.append(plan.note)

    if config.dry_run:
        notes.append(plan.estimate.line())
        return None, "--dry-run: no LLM calls were made", notes

    try:
        eval_engine.check_budget(plan.estimate, config.eval.max_cost)
    except CostLimitExceeded:
        raise

    outcome = eval_engine.run(
        config.eval,
        corpora,
        cache=cache,
        facts=facts_file,
        rendered_available=rendered_available,
        use_cache=use_cache,
    )
    return outcome.result, None, notes


@app.command()
def init(
    yes: bool = typer.Option(False, "--yes", "-y", help="Accept defaults, do not prompt"),
    directory: str = typer.Option(".", "--directory", "-C", help="Where to write the files"),
) -> None:
    """Create geoctl.toml and a commented facts.yaml template."""
    target = Path(directory)
    config_path = target / "geoctl.toml"
    facts_path = target / "facts.yaml"

    if config_path.exists() and not yes:
        typer.confirm(f"{config_path} already exists. Overwrite?", abort=True)
    config_path.write_text(TOML_TEMPLATE, encoding="utf-8")

    created_facts = False
    if not facts_path.exists() or yes:
        facts_path.write_text(FACTS_TEMPLATE, encoding="utf-8")
        created_facts = True

    emit(f"wrote {config_path}")
    if created_facts:
        emit(f"wrote {facts_path}")
    emit("")
    emit("Next:")
    emit(f"  geoctl audit <your-url> --facts {facts_path}")
    emit("")
    emit(
        "A facts file is the strongest ground truth for the eval and costs no "
        "generation call (ADR-014). Edit it with questions a real user would ask."
    )
    raise typer.Exit(EXIT_OK)


cache_app = typer.Typer(help="Inspect and clear the disk cache.", no_args_is_help=True)
app.add_typer(cache_app, name="cache")


@cache_app.command("path")
def cache_path() -> None:
    """Print the cache directory."""
    emit(str(Cache().directory))
    raise typer.Exit(EXIT_OK)


@cache_app.command("stats")
def cache_stats() -> None:
    """Show cache size and entry count."""
    stats = Cache().stats()
    for key, value in stats.items():
        emit(f"{key}: {value}")
    raise typer.Exit(EXIT_OK)


@cache_app.command("clear")
def cache_clear(
    llm: bool = typer.Option(False, "--llm", help="Clear cached LLM calls"),
    fetch: bool = typer.Option(False, "--fetch", help="Clear cached fetches and extractions"),
) -> None:
    """Clear the cache. With no flags, clear everything."""
    cache = Cache()
    if not llm and not fetch:
        removed = cache.clear()
        emit(f"cleared {removed} entries")
    if llm:
        removed = cache.clear(NS_LLM) + cache.clear(NS_EMBED)
        emit(f"cleared {removed} LLM entries")
    if fetch:
        removed = cache.clear(NS_FETCH) + cache.clear(NS_EXTRACT)
        emit(f"cleared {removed} fetch entries")
    cache.close()
    raise typer.Exit(EXIT_OK)


telemetry_app = typer.Typer(help="Control opt-in anonymous usage stats.", no_args_is_help=True)
app.add_typer(telemetry_app, name="telemetry")


def _telemetry_config() -> bool | None:
    try:
        return load_config(_config_file()).telemetry.enabled
    except ConfigError:
        return None


@telemetry_app.command("status")
def telemetry_status() -> None:
    """Show whether telemetry is on, and why."""
    state = telemetry_mod.status(_telemetry_config())
    emit(f"telemetry: {'enabled' if state['enabled'] else 'disabled'}")
    emit(f"reason: {state['reason']}")
    emit(f"endpoint configured: {state['endpoint_configured']}")
    if state["install_id"]:
        emit(f"install_id: {state['install_id']}  (request deletion by sending this ID)")
    raise typer.Exit(EXIT_OK)


@telemetry_app.command("enable")
def telemetry_enable() -> None:
    """Opt in to anonymous usage stats."""
    install_id = telemetry_mod.load_install_id(create=True)
    _write_telemetry_config(True)
    emit("Telemetry enabled.")
    emit(f"install_id: {install_id}")
    emit(
        "Never sent: URLs, domains, page content, questions, prompts, model output, "
        "keys, or file paths."
    )
    emit("See exactly what is sent: geoctl telemetry show")
    emit("Turn it off any time: geoctl telemetry disable   (or DO_NOT_TRACK=1)")
    raise typer.Exit(EXIT_OK)


@telemetry_app.command("disable")
def telemetry_disable() -> None:
    """Opt out, and rotate the install ID."""
    _write_telemetry_config(False)
    telemetry_mod.rotate_install_id()
    emit(
        "Telemetry disabled. The install ID was rotated, so events collected under "
        "the old one can no longer be linked."
    )
    raise typer.Exit(EXIT_OK)


@telemetry_app.command("show")
def telemetry_show() -> None:
    """Print the exact payload shape, field by field. Nothing is sent."""
    emit("Fields that may ever be sent (allow-list):")
    for name in sorted(telemetry_mod.ALLOWED_FIELDS):
        emit(f"  {name}")
    emit("")
    emit(
        "Never collected: URLs, hostnames, page content, facts files, questions, "
        "answers, prompts, model output, API keys, file paths, config contents."
    )
    emit("")
    emit("Example payload:")
    emit(telemetry_mod.sample_payload())
    raise typer.Exit(EXIT_OK)


def _config_write_target() -> Path:
    """Where a `geoctl` command should persist a setting.

    Honours --config and GEOCTL_CONFIG before falling back to the user config, so
    a decision made by `telemetry enable` is the one the next command reads.
    Writing to the home config while the run was pointed elsewhere would make the
    choice silently ineffective.
    """
    import os

    explicit = _config_file() or os.environ.get("GEOCTL_CONFIG")
    if explicit:
        return Path(explicit)
    return Path.home() / ".config" / "geoctl" / "config.toml"


def _write_telemetry_config(enabled: bool) -> None:
    """Update [telemetry] enabled in place, preserving any other settings."""
    path = _config_write_target()
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""

    kept: list[str] = []
    in_telemetry = False
    for line in existing.splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            in_telemetry = stripped == "[telemetry]"
            if in_telemetry:
                continue
            kept.append(line)
            continue
        if in_telemetry and stripped.startswith("enabled"):
            continue
        if in_telemetry and not stripped:
            continue
        kept.append(line)

    while kept and not kept[-1].strip():
        kept.pop()

    body = [*kept, "", "[telemetry]", f"enabled = {'true' if enabled else 'false'}"]
    path.write_text("\n".join(body).strip() + "\n", encoding="utf-8")


@app.command()
def doctor(
    test_keys: bool = typer.Option(
        False, "--test-keys", help="Make one tiny call to verify each key is valid"
    ),
) -> None:
    """Check Python version, extras, cache, network, and key configuration."""
    problems: list[str] = []
    emit(f"geoctl {__version__}")
    emit(f"python {sys.version.split()[0]}")

    from .fetch.render import is_available

    emit(f"playwright (render extra): {'installed' if is_available() else 'not installed'}")

    cache = Cache()
    stats = cache.stats()
    if stats.get("unavailable"):
        problems.append(f"cache directory is unusable: {stats['directory']}")
        emit(f"cache: unusable ({stats['directory']})")
    else:
        emit(f"cache: {stats['directory']} ({stats['entries']} entries)")
    cache.close()

    found = [v for v in _provider_keys() if os.environ.get(v)]
    if not found:
        emit("llm keys: none found (the deterministic audit needs no key)")
    else:
        emit(f"llm keys: {', '.join(found)}")
        if test_keys:
            for problem in _test_keys(found):
                problems.append(problem)

    state = telemetry_mod.status(_telemetry_config())
    emit(f"telemetry: {'enabled' if state['enabled'] else 'disabled'} ({state['reason']})")

    try:
        target = normalize_url(os.environ.get("GEOCTL_DOCTOR_URL", "https://example.com"))
        emit(f"network check target: {target}")
        emit("  (run `geoctl audit <url>` to test real reachability)")
    except InvalidUrl as exc:
        problems.append(str(exc))

    if problems:
        _err_console().print()
        for problem in problems:
            _err(problem)
        raise typer.Exit(EXIT_UNREACHABLE if any("network" in p for p in problems) else EXIT_OK)
    raise typer.Exit(EXIT_OK)


def _provider_keys() -> list[str]:
    from .config import PROVIDER_KEY_VARS

    return list(PROVIDER_KEY_VARS)


def _test_keys(keys: list[str]) -> list[str]:
    """One minimal call per key. Reports presence and validity separately."""
    problems: list[str] = []
    for var in keys:
        provider = var.removesuffix("_API_KEY").lower()
        try:
            from .llm.client import LLMClient

            LLMClient(model=f"{provider}/gpt-4o-mini", cache=None, use_cache=False).complete(
                "reply with OK", max_tokens=5
            )
            emit(f"  {var}: accepted")
        except ProviderError as exc:
            problems.append(f"{var}: {exc}")
        except Exception as exc:
            problems.append(f"{var}: {type(exc).__name__}: {exc}")
    return problems


@app.command("schema")
def schema_command(
    output: str = typer.Option(
        None, "--output", "-o", help="Write the schema here instead of stdout"
    ),
) -> None:
    """Print the JSON Schema for the report, generated from the models."""
    text = report_mod.json_report.schema_json()
    if output:
        Path(output).write_text(text, encoding="utf-8")
        _note(f"wrote {output}")
    else:
        emit(text)
    raise typer.Exit(EXIT_OK)


@app.command()
def version() -> None:
    """Print the version."""
    emit(__version__)
    raise typer.Exit(EXIT_OK)


TOML_TEMPLATE = """# geoctl configuration
# Precedence: CLI flags > environment variables > this file > user config > defaults
#
# API keys do NOT belong in this file. Put them in environment variables or your
# OS keyring. geoctl refuses to start if it finds key-like values here.

[audit]
max_pages = 10                    # pages to audit deterministically
bots = []                         # empty = the built-in registry
policy = "report"                 # report | fail | ignore
fail_under = 70                   # exit 1 below this score (0-100)

[fetch]
concurrency = 4                   # be polite to the site you are auditing
timeout = 15
max_bytes = 5000000
# allow_private = false           # true to audit localhost during development

[eval]
enabled = "auto"                  # auto = run if a provider key is present
# model = "openai/gpt-4o-mini"
# judge_model = "anthropic/claude-sonnet-4-5"   # a different family reduces bias
eval_pages = 3                    # independent of audit.max_pages
questions = 50                    # cap 200; the CI on the mean narrows with this
trials = 3
top_k = 5
# max_cost = 1.00                # abort before exceeding this estimated cost

[telemetry]
enabled = false
"""

FACTS_TEMPLATE = """# Ground truth for the answerability eval.
#
# This is the strongest eval input and the cheapest: you write it, so it is
# independent of both the crawler view and the rendered view. Questions generated
# from the crawler view itself are circular and cannot show content loss
# (ADR-014).
#
# Each fact needs a question a real user would ask and the answer your site
# actually gives. `page` is optional and restricts the fact to one page.

site: https://example.com

facts:
  - id: pricing-starter
    question: "How much does the Starter plan cost per month?"
    answer: "$19 per month"
    page: /pricing

  - id: founded
    question: "When was the company founded?"
    answer: "2019"

  - id: main-product
    question: "What does the product do?"
    answer: "It audits whether AI crawlers can read your site."
"""

# Registered under its documented name rather than its Python name, so
# `geoctl audit` works and `geoctl audit-command` does not.
app.command("audit")(_audit_command)


def main() -> None:
    """Entry point. KeyboardInterrupt is a clean exit, not a traceback."""
    try:
        app()
    except KeyboardInterrupt:  # pragma: no cover - interactive only
        _err_console().print("\n[dim]interrupted[/dim]")
        sys.exit(EXIT_OK)
    except Exception as exc:
        _err_console().print(f"[red]internal error:[/red] {type(exc).__name__}: {exc}")
        _err_console().print("[dim]This is a bug. Please report it with the command you ran.[/dim]")
        sys.exit(EXIT_INTERNAL)


if __name__ == "__main__":  # pragma: no cover
    main()
