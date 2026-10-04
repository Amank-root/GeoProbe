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
from . import generate as generate_mod
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
from .evals.answer import ANSWERER_MAX_TOKENS
from .evals.runner import decide_threshold
from .fetch.ssrf import BlockedTarget as SSRFBlocked
from .generate import GeneratorError
from .llm import providers
from .llm.client import CostLimitExceeded, Endpoint, ProviderError, UnknownPricing

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
    embedding_model: str = typer.Option(
        None, help="Embedding model for retrieval, e.g. gemini/gemini-embedding-001"
    ),
    base_url: str = typer.Option(
        None,
        help="OpenAI-compatible endpoint, e.g. https://api.groq.com/openai/v1 "
        "or https://integrate.api.nvidia.com/v1",
    ),
    api_key_env: str = typer.Option(
        None, help="Environment variable holding the API key (the key is never read from config)"
    ),
    input_cost_per_mtok: float = typer.Option(
        None, help="Price per 1M input tokens, for models LiteLLM does not price"
    ),
    output_cost_per_mtok: float = typer.Option(
        None, help="Price per 1M output tokens, for models LiteLLM does not price"
    ),
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
        ("embedding_model", embedding_model),
        ("base_url", base_url),
        ("api_key_env", api_key_env),
        ("input_cost_per_mtok", input_cost_per_mtok),
        ("output_cost_per_mtok", output_cost_per_mtok),
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
    except UnknownPricing as exc:
        _err(str(exc))
        raise typer.Exit(EXIT_COST) from exc
    except ProviderError as exc:
        _err(str(exc))
        raise typer.Exit(EXIT_AUTH) from exc
    except CostLimitExceeded as exc:
        _err(str(exc))
        raise typer.Exit(EXIT_COST) from exc
    except eval_engine.EvalSkipped as exc:
        # A skip is a known, explainable outcome — not a crash. Letting it reach
        # main() made every "no questions could be produced" run print
        # "internal error ... please report" and exit 70, telling the user to file
        # a bug against their own website (issue #46).
        eval_result, eval_error = None, str(exc)
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
        should_fail, note = decide_threshold(
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

    # Checked before the dry-run return as well: `--dry-run` is exactly where a
    # user goes to find out what a run will cost, so discovering there that the
    # ceiling cannot be enforced is exactly the right time to say so.
    eval_engine.enforce_pricing_known(config.eval, config.eval.max_cost)

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


# ------------------------------------------------------------------- generate

generate_app = typer.Typer(
    help="Generate starter files from an audit (proposals, never applied).",
    no_args_is_help=True,
)
app.add_typer(generate_app, name="generate")


def _generation_config(*, max_pages: int, allow_private: bool, timeout: float | None) -> Any:
    """Config for a generate run: crawl only, never eval."""
    try:
        return apply_overrides(
            load_config(_config_file()),
            {
                "audit": {"max_pages": max_pages},
                "fetch": {"allow_private": allow_private or None, "timeout": timeout},
            },
        )
    except ConfigError as exc:
        _err(str(exc))
        raise typer.Exit(EXIT_USAGE) from exc


def _crawl_for_generation(config: Any, url: str, *, no_cache: bool) -> Any:
    """Crawl the site, mapping every failure to its documented exit code.

    `generate` fetches, so the SSRF guard and the reachability contract apply
    exactly as they do to `audit`. A loopback target without --allow-private is
    a refusal, not a failed fetch.
    """
    cache = Cache(config.cache_dir)
    try:
        return asyncio.run(audit(config, url, cache=cache, use_cache=not no_cache))
    except InvalidUrl as exc:
        _err(str(exc))
        raise typer.Exit(EXIT_USAGE) from exc
    except (SSRFBlocked, BlockedTarget) as exc:
        # A safety refusal is not a failed fetch. It gets its own exit code (6),
        # the same as `audit`, and it must never degrade into a warning while the
        # run continues — CLI_SPEC §5.
        _err(str(exc))
        raise typer.Exit(EXIT_BLOCKED) from exc
    except Unreachable as exc:
        _err(str(exc))
        raise typer.Exit(EXIT_UNREACHABLE) from exc
    finally:
        cache.close()


def _write_generated(result: Any, output: str | None, *, force: bool) -> None:
    """Write a generated file, refusing to clobber without --force.

    Every generator here produces a proposal. Overwriting a real robots.txt or an
    llms.txt a user hand-edited would be data loss, so it needs an explicit
    --force rather than a prompt (CLI_SPEC §2.6).
    """
    target = Path(output) if output else Path(result.path.lstrip("/"))
    if target.exists() and not force:
        _err(f"{target} already exists. Pass --force to overwrite it.")
        raise typer.Exit(EXIT_USAGE)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(result.content, encoding="utf-8")

    emit(f"wrote {target} ({result.byte_count} bytes)")
    for note in result.notes:
        emit(f"  note: {note}")
    emit("")
    emit(
        "This is a proposal derived from what the audit observed. Review it before "
        "publishing: nothing here is verified to improve how your site is cited."
    )
    raise typer.Exit(EXIT_OK)


def _start_page_facts(state: Any) -> tuple[str, str]:
    """(title, description) from the start page, for the generators to fill in."""
    ctx = state.context
    first = ctx.start_bundle if ctx else None
    if first is None:
        return "", ""
    title = first.title or ""
    description = ""
    if first.structure is not None:
        description = first.structure.meta.description or ""
    return title, description


def _emit_generator_error(exc: Exception) -> None:  # pragma: no cover - trivial
    _err(str(exc))


@generate_app.command("llms-txt")
def generate_llms_txt_command(
    url: str = typer.Argument(..., help="The site to crawl"),
    output: str = typer.Option(None, "--output", "-o", help="Where to write the file"),
    max_pages: int = typer.Option(20, help="Pages to crawl (default 20)"),
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite an existing file"),
    title: str = typer.Option(None, help="Site name (default: the home page title)"),
    description: str = typer.Option(None, help="One-line summary"),
    allow_private: bool = typer.Option(False, "--allow-private", help="Allow loopback targets"),
    timeout: float = typer.Option(None, help="Per-request timeout in seconds"),
    no_cache: bool = typer.Option(False, "--no-cache", help="Ignore cache reads"),
) -> None:
    """Generate an llms.txt from the pages the crawl actually found."""
    config = _generation_config(max_pages=max_pages, allow_private=allow_private, timeout=timeout)
    state = _crawl_for_generation(config, url, no_cache=no_cache)

    entries = (
        generate_mod.page_entries(state.context.pages, state.start_url) if state.context else []
    )
    default_title, default_description = _start_page_facts(state)
    try:
        result = generate_mod.generate_llms_txt(
            entries,
            site_url=state.start_url,
            title=title or default_title,
            description=description or default_description,
        )
    except GeneratorError as exc:
        _emit_generator_error(exc)
        raise typer.Exit(EXIT_USAGE) from exc
    _write_generated(result, output, force=force)


@generate_app.command("robots")
def generate_robots_command(
    url: str = typer.Argument(..., help="The site to crawl"),
    output: str = typer.Option(None, "--output", "-o", help="Where to write the file"),
    policy: str = typer.Option(
        "allow-search-block-training",
        "--policy",
        help="allow-all | allow-search-block-training | block-all-ai",
    ),
    max_pages: int = typer.Option(5, help="Pages to crawl (default 5)"),
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite an existing file"),
    crawl_delay: int = typer.Option(None, help="Add a Crawl-delay directive"),
    allow_private: bool = typer.Option(False, "--allow-private", help="Allow loopback targets"),
    timeout: float = typer.Option(None, help="Per-request timeout in seconds"),
    no_cache: bool = typer.Option(False, "--no-cache", help="Ignore cache reads"),
) -> None:
    """Generate a robots.txt from a policy preset, preserving the current one."""
    if policy not in generate_mod.ROBOT_POLICIES:
        _err(f"--policy must be one of {', '.join(generate_mod.ROBOT_POLICIES)}")
        raise typer.Exit(EXIT_USAGE)

    config = _generation_config(max_pages=max_pages, allow_private=allow_private, timeout=timeout)
    state = _crawl_for_generation(config, url, no_cache=no_cache)

    robots = state.context.robots if state.context else None
    sitemaps = list(robots.sitemaps) if robots else []
    # Preserve whatever is already published, commented out, so the diff the user
    # reviews shows both versions rather than only ours.
    existing = getattr(robots, "body", "") or ""
    try:
        result = generate_mod.generate_robots(
            site_url=state.start_url,
            policy=policy,
            sitemaps=sitemaps,
            existing=existing,
            crawl_delay=crawl_delay,
        )
    except GeneratorError as exc:
        _emit_generator_error(exc)
        raise typer.Exit(EXIT_USAGE) from exc
    _write_generated(result, output, force=force)


@generate_app.command("jsonld")
def generate_jsonld_command(
    url: str = typer.Argument(..., help="The site to crawl"),
    type: str = typer.Option(
        "Organization", "--type", "-t", help="Organization | WebSite | Article"
    ),
    output: str = typer.Option(None, "--output", "-o", help="Where to write the file"),
    max_pages: int = typer.Option(1, help="Pages to crawl (default 1)"),
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite an existing file"),
    description: str = typer.Option(None, help="One-line description"),
    allow_private: bool = typer.Option(False, "--allow-private", help="Allow loopback targets"),
    timeout: float = typer.Option(None, help="Per-request timeout in seconds"),
    no_cache: bool = typer.Option(False, "--no-cache", help="Ignore cache reads"),
) -> None:
    """Generate a JSON-LD skeleton with the unfillable fields marked."""
    if type not in generate_mod.JSONLD_TYPES:
        _err(f"--type must be one of {', '.join(generate_mod.JSONLD_TYPES)}")
        raise typer.Exit(EXIT_USAGE)

    config = _generation_config(max_pages=max_pages, allow_private=allow_private, timeout=timeout)
    state = _crawl_for_generation(config, url, no_cache=no_cache)

    default_title, default_description = _start_page_facts(state)
    try:
        result = generate_mod.generate_jsonld(
            type,
            site_url=state.start_url,
            title=default_title,
            description=description or default_description,
        )
    except GeneratorError as exc:
        _emit_generator_error(exc)
        raise typer.Exit(EXIT_USAGE) from exc
    _write_generated(result, output, force=force)


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
    """Key variables actually set in the environment.

    Reports the names present, not the canonical list, so `doctor` names the
    variable the user actually set — including a suffixed one such as
    `GEMINI_API_KEY_1`.
    """
    return providers.present_key_vars()


def _test_keys(keys: list[str]) -> list[str]:
    """One minimal call per key. Reports presence and validity separately.

    Each key is tested with a model that key can actually call, including the
    base URL for OpenAI-compatible hosts LiteLLM has no first-class provider for.
    Hardcoding one OpenAI model for every provider made `--test-keys` report a
    working NVIDIA or Groq key as broken (issue #45).
    """
    problems: list[str] = []
    for var in keys:
        provider = providers.provider_for_key_var(var)
        if provider is None:
            problems.append(f"{var}: not a key geoctl recognises")
            continue
        try:
            from .llm.client import LLMClient

            endpoint = Endpoint(base_url=provider.base_url, api_key=os.environ.get(var))
            LLMClient(
                model=provider.model,
                cache=None,
                use_cache=False,
                endpoint=endpoint,
            ).complete_text("reply with OK", max_tokens=ANSWERER_MAX_TOKENS)
            target = f" via {provider.base_url}" if provider.base_url else ""
            emit(f"  {var}: accepted ({provider.model}{target})")
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
