"""Fetch layer: HTTP client, bot registry, robots.txt, sitemaps, optional render."""

from __future__ import annotations

from .bots import BROWSER_UA, Bot, get, known, resolve
from .client import FetchClient, classify_status, compare_parity, detect_challenge, fetch_all_lenses
from .robots import classify_verdict_list, evaluate_all, parse_robots, robots_url
from .sitemap import build_report, candidate_urls, parse_sitemap, sample_urls
from .ssrf import BlockedTarget, check_url

__all__ = [
    "BROWSER_UA",
    "BlockedTarget",
    "Bot",
    "FetchClient",
    "build_report",
    "candidate_urls",
    "check_url",
    "classify_status",
    "classify_verdict_list",
    "compare_parity",
    "detect_challenge",
    "evaluate_all",
    "fetch_all_lenses",
    "get",
    "known",
    "parse_robots",
    "parse_sitemap",
    "resolve",
    "robots_url",
    "sample_urls",
]
