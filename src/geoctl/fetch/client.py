"""httpx fetch layer: per-bot lenses, limits, SSRF guard, challenge detection.

Design rules that are not negotiable here (ARCHITECTURE §6):

- Simulated bot requests identify themselves with `X-Geoctl-Test: 1`. There is
  no stealth mode, by design (ADR-008).
- Bodies are truncated at `max_bytes`. A 5 MB cap is a politeness limit as much
  as a memory one.
- Network failure becomes an `error` on the FetchResult, never an exception out
  of the fetch call, because one failed lens must not abort an audit.
"""

from __future__ import annotations

import asyncio
import random
import time
from typing import Any

import httpx

from ..cache import NS_FETCH, Cache
from ..models import BlockedBy, FetchResult
from .bots import BROWSER_UA, Bot
from .ssrf import BlockedTarget, check_url

# Markers of an interstitial or challenge page returned with a 200. A status-only
# check would read these as content, which is exactly what ACC-003 exists to stop.
CHALLENGE_MARKERS: tuple[tuple[str, str], ...] = (
    ("cf-browser-verification", "cloudflare"),
    ("cf_chl_opt", "cloudflare"),
    ("Checking your browser before accessing", "cloudflare"),
    ("Enable JavaScript and cookies to continue", "cloudflare"),
    ("Just a moment...", "cloudflare"),
    ("/cdn-cgi/challenge-platform", "cloudflare"),
    ("__cf_chl_", "cloudflare"),
    ("captcha-delivery", "datadome"),
    ("geo.captcha-delivery.com", "datadome"),
    ("Incapsula incident ID", "imperva"),
    ("_Incapsula_Resource", "imperva"),
    ("Request unsuccessful. Incapsula", "imperva"),
    ("px-captcha", "perimeterx"),
    ("Press and hold", "perimeterx"),
    ("unusual traffic from your computer", "google"),
    ("Attention Required! | Cloudflare", "cloudflare"),
)

WAF_STATUS = frozenset({401, 403, 407, 429, 451, 503})


def detect_challenge(body: bytes | None, headers: dict[str, str] | None = None) -> str | None:
    """Return a marker name if the body looks like a challenge, else None."""
    if not body:
        return None
    sample = body[:200_000].decode("utf-8", "replace")
    lowered = sample.lower()
    for needle, vendor in CHALLENGE_MARKERS:
        if needle.lower() in lowered:
            return vendor
    if headers:
        server = headers.get("server", "").lower()
        if "cloudflare" in server and "cf-mitigated" in {k.lower() for k in headers}:
            return "cloudflare"
    return None


def classify_status(status: int | None, challenge: str | None) -> BlockedBy | None:
    if challenge:
        return "challenge"
    if status in WAF_STATUS:
        return "waf"
    if status is not None and status >= 400:
        return "status"
    return None


class FetchClient:
    """Async fetcher. One instance per audit run."""

    def __init__(
        self,
        *,
        timeout: float = 15.0,
        max_bytes: int = 5_000_000,
        max_redirects: int = 5,
        concurrency: int = 4,
        allow_private: bool = False,
        cache: Cache | None = None,
        use_cache: bool = True,
        per_host_delay: float = 0.2,
    ) -> None:
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.max_redirects = max_redirects
        self.concurrency = max(1, concurrency)
        self.allow_private = allow_private
        self.cache = cache
        self.use_cache = use_cache and cache is not None
        self.per_host_delay = per_host_delay
        self._sem = asyncio.Semaphore(self.concurrency)
        self._last_hit: dict[str, float] = {}

    async def fetch(
        self,
        url: str,
        *,
        bot: str = "browser",
        user_agent: str = BROWSER_UA,
        headers: dict[str, str] | None = None,
    ) -> FetchResult:
        try:
            check_url(url, self.allow_private)
        except BlockedTarget as exc:
            return FetchResult(url=url, final_url=url, bot=bot, error=str(exc), blocked_by="status")

        cache_key = (url, bot, user_agent, self.allow_private)
        if self.use_cache and self.cache:
            cached = self.cache.get(NS_FETCH, *cache_key)
            if isinstance(cached, FetchResult):
                return cached

        result = await self._fetch_uncached(
            url, bot=bot, user_agent=user_agent, headers=headers or {}
        )
        if self.use_cache and self.cache and result.error is None:
            self.cache.set(NS_FETCH, result, *cache_key)
        return result

    async def _fetch_uncached(
        self, url: str, *, bot: str, user_agent: str, headers: dict[str, str]
    ) -> FetchResult:
        simulated = bot != "browser"
        req_headers = {
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en;q=0.9",
        }
        if simulated:
            # ADR-008: test traffic is honest about what it is.
            req_headers["X-Geoctl-Test"] = "1"
        req_headers.update(headers)

        limits = httpx.Limits(max_connections=self.concurrency * 2)
        timeout = httpx.Timeout(self.timeout)
        started = time.perf_counter()
        redirect_chain: list[dict[str, Any]] = []

        try:
            async with self._sem:
                await self._polite_delay(url)
                async with httpx.AsyncClient(
                    follow_redirects=False, timeout=timeout, limits=limits
                ) as client:
                    current = url
                    response: httpx.Response | None = None
                    for _hop in range(self.max_redirects + 1):
                        response = await client.get(current, headers=req_headers)
                        if response.status_code in (301, 302, 303, 307, 308):
                            location = response.headers.get("location")
                            if not location:
                                break
                            next_url = str(httpx.URL(current).join(location))
                            redirect_chain.append(
                                {"from": current, "status": response.status_code, "to": next_url}
                            )
                            try:
                                check_url(next_url, self.allow_private)
                            except BlockedTarget as exc:
                                blocked = FetchResult(
                                    url=url,
                                    final_url=current,
                                    bot=bot,
                                    status=response.status_code,
                                    elapsed_ms=self._elapsed(started),
                                    error=f"Blocked redirect: {exc}",
                                    redirect_chain=redirect_chain,
                                )
                                return blocked
                            current = next_url
                            await self._polite_delay(current)
                            continue
                        break

            if response is None:  # pragma: no cover - loop always assigns
                raise httpx.RequestError("no response")

            body = response.content[: self.max_bytes]
            truncated = len(response.content) > self.max_bytes
            hdrs = {k.lower(): v for k, v in response.headers.items()}
            challenge = detect_challenge(body, hdrs)
            error = None
            if truncated:
                error = f"response truncated at {self.max_bytes} bytes"
            elif response.status_code >= 400:
                error = f"HTTP {response.status_code}"
            return FetchResult(
                url=url,
                final_url=str(response.url),
                bot=bot,
                status=response.status_code,
                headers=hdrs,
                body=body,
                elapsed_ms=self._elapsed(started),
                error=error,
                blocked_by=classify_status(response.status_code, challenge),
                redirect_chain=redirect_chain,
                challenge_marker=challenge,
            )
        except httpx.TooManyRedirects as exc:
            return self._fail(url, bot, started, f"Too many redirects: {exc}", redirect_chain)
        except httpx.TimeoutException as exc:
            return self._fail(url, bot, started, f"Timed out: {exc}", redirect_chain)
        except (httpx.HTTPError, OSError) as exc:
            return self._fail(url, bot, started, f"{type(exc).__name__}: {exc}", redirect_chain)

    @staticmethod
    def _elapsed(started: float) -> int:
        return int((time.perf_counter() - started) * 1000)

    def _fail(
        self,
        url: str,
        bot: str,
        started: float,
        message: str,
        chain: list[dict[str, Any]] | None = None,
    ) -> FetchResult:
        return FetchResult(
            url=url,
            final_url=url,
            bot=bot,
            error=message,
            elapsed_ms=self._elapsed(started),
            redirect_chain=chain or [],
        )

    async def _polite_delay(self, url: str) -> None:
        """Per-host delay with jitter, so we never look like a burst (ADR-008)."""
        host = url.split("/")[2] if "://" in url else url
        now = time.monotonic()
        last = self._last_hit.get(host, 0.0)
        wait = self.per_host_delay - (now - last)
        if wait > 0:
            await asyncio.sleep(wait + random.uniform(0, self.per_host_delay / 2))
        self._last_hit[host] = time.monotonic()

    async def fetch_many(
        self,
        urls: list[str],
        bot: Bot | None = None,
        user_agent: str = BROWSER_UA,
        name: str = "browser",
    ) -> list[FetchResult]:
        tasks = [self.fetch(u, bot=name, user_agent=user_agent) for u in urls]
        return list(await asyncio.gather(*tasks))


async def fetch_all_lenses(
    client: FetchClient, urls: list[str], bots: list[Bot]
) -> dict[tuple[str, str], FetchResult]:
    """Fetch every URL through the browser lens and each configured bot.

    Returns {(url, bot_name): FetchResult}. Concurrency is bounded inside the
    client, so this is a fan-out rather than an unbounded burst.
    """
    jobs: list[tuple[str, str, str]] = []
    for url in urls:
        jobs.append((url, "browser", BROWSER_UA))
        for bot in bots:
            jobs.append((url, bot.name, bot.user_agent))

    results = await asyncio.gather(
        *(client.fetch(url, bot=name, user_agent=ua) for url, name, ua in jobs),
        return_exceptions=True,
    )
    out: dict[tuple[str, str], FetchResult] = {}
    for job, res in zip(jobs, results, strict=True):
        url, name, _ = job
        out[(url, name)] = (
            res
            if isinstance(res, FetchResult)
            else FetchResult(url=url, final_url=url, bot=name, error=f"{type(res).__name__}: {res}")
        )
    return out


def compare_parity(
    browser: FetchResult, bot_result: FetchResult, browser_text: str, bot_text: str
) -> dict[str, Any]:
    """Status, size ratio, and text similarity for ACC-002 evidence."""
    from ..util import similarity

    size_ratio = bot_result.body_len / browser.body_len if browser.body_len else None
    return {
        "browser_status": browser.status,
        "bot_status": bot_result.status,
        "status_match": browser.status == bot_result.status,
        "browser_chars": browser.body_len,
        "bot_chars": bot_result.body_len,
        "size_ratio": round(size_ratio, 4) if size_ratio is not None else None,
        "text_similarity": round(similarity(browser_text, bot_text), 4)
        if (browser_text or bot_text)
        else None,
        "bot_error": bot_result.error,
        "bot_blocked_by": bot_result.blocked_by,
        "bot_challenge": bot_result.challenge_marker,
    }
