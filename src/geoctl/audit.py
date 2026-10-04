"""Audit orchestration: fetch, extract, check, score, report.

The pipeline is deliberately tolerant: a failed fetch of one lens becomes an
error on that result, and partial results are always reported (ARCHITECTURE §11).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from urllib.parse import urlparse

from . import __version__
from .cache import Cache
from .checks import run_all
from .checks.base import AuditContext
from .config import Config
from .evals import runner as eval_runner
from .extract import build_bundle
from .fetch import sitemap as sitemap_mod
from .fetch.bots import resolve
from .fetch.client import FetchClient, fetch_all_lenses
from .fetch.robots import evaluate_all, robots_url
from .models import (
    AuditReport,
    CheckResult,
    FetchResult,
    PageSummary,
    RunError,
    RunInfo,
    TargetInfo,
    ToolInfo,
)
from .util import iso_utc, ulid

LLMS_TXT_PATH = "/llms.txt"


class InvalidUrl(Exception):
    """Usage error: exit code 2."""


class Unreachable(Exception):
    """Exit code 3."""


class BlockedTarget(Exception):
    """Exit code 6."""


@dataclass
class AuditOptions:
    url: str
    render: bool = False
    dry_run: bool = False
    include_render: bool = True


@dataclass
class AuditState:
    """Everything gathered, ready to be turned into a report."""

    start_url: str
    final_url: str = ""
    checks: list[CheckResult] = field(default_factory=list)
    errors: list[RunError] = field(default_factory=list)
    pages_audited: int = 0
    sitemap_found: bool = False
    context: AuditContext | None = None
    elapsed_ms: int = 0
    render_error: str | None = None


def normalize_url(raw: str) -> str:
    url = (raw or "").strip()
    if not url:
        raise InvalidUrl("No URL given")
    if "://" not in url:
        url = f"https://{url}"
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise InvalidUrl(f"Only http and https are supported, got {parsed.scheme!r}")
    if not parsed.netloc:
        raise InvalidUrl(f"{raw!r} has no host")
    return url


async def audit(
    config: Config, url: str, *, cache: Cache | None = None, use_cache: bool = True
) -> AuditState:
    """Fetch, extract, and check. Never raises for a network problem."""
    from .fetch.ssrf import BlockedTarget as SSRFBlocked

    start = time.perf_counter()
    start_url = normalize_url(url)
    state = AuditState(start_url=start_url)

    try:
        client = FetchClient(
            timeout=config.fetch.timeout,
            max_bytes=config.fetch.max_bytes,
            max_redirects=config.fetch.max_redirects,
            concurrency=config.fetch.concurrency,
            allow_private=config.fetch.allow_private,
            cache=cache,
            use_cache=use_cache,
        )
        bots = resolve(config.audit.bots)
        ctx = await _gather(
            client, start_url, config, bots, cache=cache, use_cache=use_cache, state=state
        )
    except SSRFBlocked as exc:
        raise BlockedTarget(str(exc)) from exc

    state.context = ctx
    state.checks = run_all(ctx, config.audit.only, config.audit.skip)
    state.pages_audited = len([p for p in ctx.pages if "browser-nojs" in p.views])
    state.final_url = ctx.final_url
    state.sitemap_found = bool(ctx.sitemap and ctx.sitemap.found)
    state.elapsed_ms = int((time.perf_counter() - start) * 1000)
    cache.close() if cache else None
    return state


async def _gather(
    client: FetchClient,
    start_url: str,
    config: Config,
    bots: list,
    *,
    cache: Cache | None,
    use_cache: bool,
    state: AuditState,
) -> AuditContext:
    ctx = AuditContext(
        start_url=start_url,
        final_url=start_url,
        policy=config.audit.policy,
        bot_names=[b.name for b in bots],
    )

    # 1. robots.txt
    r_url = robots_url(start_url)
    r_fetch = await client.fetch(r_url, bot="robots")
    robots_text = None
    if r_fetch.ok and r_fetch.body:
        robots_text = r_fetch.body.decode("utf-8", "replace")
    elif r_fetch.status not in (404, 410, None):
        state.errors.append(
            RunError(
                code="ROBOTS_FETCH",
                severity="warning",
                message=f"Could not read robots.txt ({r_fetch.error})",
                url=r_url,
            )
        )
    ctx.robots = evaluate_all(
        robots_text,
        urlparse(start_url).path or "/",
        {b.name: b.robots_token for b in bots},
        start_url,
    )

    # 2. sitemap
    parsed_sitemaps = []
    found_urls: list[str] = []
    for candidate in sitemap_mod.candidate_urls(start_url, ctx.robots.sitemaps):
        fetch = await client.fetch(candidate, bot="sitemap")
        if not sitemap_mod.looks_like_sitemap(fetch.body, fetch.headers.get("content-type")):
            continue
        found_urls.append(candidate)
        parsed_sitemaps.append(sitemap_mod.parse_sitemap(fetch.body or b""))
        for child in parsed_sitemaps[-1].child_sitemaps:
            child_fetch = await client.fetch(child, bot="sitemap")
            if sitemap_mod.looks_like_sitemap(
                child_fetch.body, child_fetch.headers.get("content-type")
            ):
                found_urls.append(child)
                parsed_sitemaps.append(sitemap_mod.parse_sitemap(child_fetch.body or b""))
        break  # one usable sitemap is enough; more are noise

    all_entries = [e.loc for doc in parsed_sitemaps for e in doc.entries]
    ctx.sitemap = sitemap_mod.build_report(parsed_sitemaps, found_urls, start_url)

    # 3. pages: start URL plus a sitemap sample, spread rather than a prefix
    page_urls = [start_url]
    if all_entries:
        page_urls.extend(
            u
            for u in sitemap_mod.sample_urls(all_entries, start_url, config.audit.max_pages)
            if u != start_url
        )
    page_urls = page_urls[: config.audit.max_pages]

    fetches = await fetch_all_lenses(client, page_urls, bots)
    by_url: dict[str, dict] = {}
    for (page_url, name), fetch in fetches.items():
        by_url.setdefault(page_url, {})[name] = fetch

    for page_url in page_urls:
        lens = by_url.get(page_url, {})
        browser = lens.get("browser")
        if browser is None or browser.error:
            reason = browser.error if browser is not None else "not fetched"
            # A safety-rule refusal is not a page that failed to load. It must
            # stop the run (exit 6), not quietly become a warning while the rest
            # of the report claims the page had no headings and no lang.
            if "private or reserved address" in reason or "Blocked redirect" in reason:
                raise BlockedTarget(reason)
            state.errors.append(
                RunError(
                    code="FETCH_FAILED",
                    severity="error",
                    message=f"Could not fetch the page: {reason}",
                    url=page_url,
                )
            )
        bundle = build_bundle(page_url, lens, cache=cache, use_cache=use_cache)
        ctx.pages.append(bundle)
        if bundle.status is not None:
            ctx.final_url = ctx.final_url or bundle.final_url
        if bundle.final_url:
            ctx.final_url = bundle.final_url

    if not any(p.views.get("browser-nojs") for p in ctx.pages):
        detail = state.errors[0].message if state.errors else "no successful fetch"
        raise Unreachable(f"Could not fetch {start_url}: {detail}")

    # 4. llms.txt
    llms_url = f"{urlparse(start_url).scheme}://{urlparse(start_url).netloc}{LLMS_TXT_PATH}"
    ctx.llms_txt = await client.fetch(llms_url, bot="llms-txt")

    # 5. optional JS rendering, for the no-JS vs rendered comparison (REN-001)
    ctx.render_available = config.render
    if config.render:
        await _attach_rendered(ctx, page_urls, state)
    return ctx


async def _attach_rendered(ctx: AuditContext, page_urls: list[str], state: AuditState) -> None:
    """Add JS-rendered views. Playwright is an extra, so absence is not an error."""
    from .extract.view import add_rendered_view
    from .fetch import render as render_mod

    if not render_mod.is_available():
        state.render_error = (
            "Playwright is not installed. Install the extra with "
            "`pip install geoctl[render]` and `playwright install chromium`."
        )
        state.errors.append(
            RunError(code="RENDER_UNAVAILABLE", severity="warning", message=state.render_error)
        )
        return

    results = render_mod.render_urls(page_urls)
    for result in results:
        bundle = next((b for b in ctx.pages if b.url == result.url), None)
        if bundle is None:
            continue
        if result.error or result.html is None:
            state.errors.append(
                RunError(
                    code="RENDER_FAILED",
                    severity="warning",
                    message=f"JS rendering failed: {result.error}",
                    url=result.url,
                )
            )
            state.render_error = state.render_error or result.error
            continue
        pseudo = FetchResult(
            url=result.url,
            final_url=result.url,
            bot="__rendered__",
            status=result.status,
            body=result.html,
        )
        add_rendered_view(bundle, result.html, lens="rendered")
        ctx.rendered[result.url] = pseudo


def build_report(state: AuditState, config: Config, *, eval_result=None) -> AuditReport:
    """Turn gathered state into the public report document."""
    from .scoring import score_checks

    pages: list[PageSummary] = []
    if state.context:
        for bundle in state.context.pages:
            view = bundle.views.get("browser-nojs")
            sd = bundle.structured_data
            pages.append(
                PageSummary(
                    url=bundle.final_url,
                    status_by_bot={name: f.status for name, f in bundle.fetches.items()},
                    text_chars={name: v.text_chars for name, v in bundle.views.items()}
                    | ({"browser-nojs": view.text_chars} if view else {}),
                    title=bundle.title,
                    h1_count=len(bundle.structure.h1_texts) if bundle.structure else 0,
                    json_ld_types=sorted(sd.types) if sd else [],
                )
            )

    config_block = config.public_dict()
    config_block["bots"] = state.context.bot_names if state.context else list(config.audit.bots)
    config_block["render"] = bool(state.context and state.context.rendered)
    if state.render_error:
        config_block["render_error"] = state.render_error

    return AuditReport(
        tool=ToolInfo(version=__version__),
        run=RunInfo(
            id=ulid(),
            started_at=iso_utc(),
            duration_ms=state.elapsed_ms,
            config=config_block,
            eval_version=eval_result.eval_version if eval_result else None,
        ),
        target=TargetInfo(
            url=state.start_url,
            final_url=state.final_url or state.start_url,
            pages_audited=state.pages_audited,
            sitemap_found=state.sitemap_found,
        ),
        score=score_checks(state.checks),
        checks=state.checks,
        pages=pages,
        eval=eval_result,
        errors=state.errors,
    )


def build_corpora(state: AuditState, eval_pages: int) -> list[eval_runner.PageCorpus]:
    """Build per-page (crawler view, ground truth) pairs for the eval.

    Ground truth prefers the rendered view when it exists, because questions
    must come from something richer than what the answerer sees (EVALS §3.1).
    """
    corpora: list[eval_runner.PageCorpus] = []
    if not state.context:
        return corpora
    for bundle in state.context.pages:
        no_js = bundle.views.get("browser-nojs")
        if not no_js or not no_js.text.strip():
            continue
        rendered_view = bundle.views.get("rendered")
        ground_truth = rendered_view.text if rendered_view else ""
        if not ground_truth.strip():
            continue  # without ground truth there is nothing to generate from
        corpora.append(
            eval_runner.PageCorpus(
                url=bundle.final_url,
                crawler_text=no_js.text,
                ground_truth_text=ground_truth,
            )
        )
        if len(corpora) >= eval_pages:
            break
    return corpora


def build_corpora_crawler_only(state: AuditState, eval_pages: int) -> list[eval_runner.PageCorpus]:
    """Fallback corpora when no rendered ground truth exists.

    These produce a *circular* eval: questions come from the same text the
    answerer sees. It is still run, but labelled low confidence everywhere it
    appears (ADR-014).
    """
    corpora: list[eval_runner.PageCorpus] = []
    if not state.context:
        return corpora
    for bundle in state.context.pages:
        view = bundle.views.get("browser-nojs")
        if not view or not view.text.strip():
            continue
        corpora.append(
            eval_runner.PageCorpus(
                url=bundle.final_url, crawler_text=view.text, ground_truth_text=""
            )
        )
        if len(corpora) >= eval_pages:
            break
    return corpora
