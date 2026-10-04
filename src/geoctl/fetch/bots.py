"""Bot registry: data, not code (ARCHITECTURE §6).

Purpose matters for reporting: blocking a training bot while allowing search
bots is a legitimate policy (ACC-001), and the report groups verdicts by
purpose so that distinction is visible.
"""

from __future__ import annotations

from dataclasses import dataclass

Purpose = str  # training | search | user_triggered | other


@dataclass(frozen=True)
class Bot:
    name: str
    user_agent: str
    robots_token: str
    purpose: Purpose
    docs_url: str


# The `browser` lens is not an AI bot; it is the baseline every bot is compared
# against in ACC-002.
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

BOTS: tuple[Bot, ...] = (
    Bot(
        name="GPTBot",
        user_agent=(
            "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); "
            "compatible; GPTBot/1.2; +https://openai.com/gptbot"
        ),
        robots_token="GPTBot",
        purpose="training",
        docs_url="https://platform.openai.com/docs/bots",
    ),
    Bot(
        name="OAI-SearchBot",
        user_agent=(
            "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); "
            "compatible; OAI-SearchBot/1.0; +https://openai.com/searchbot"
        ),
        robots_token="OAI-SearchBot",
        purpose="search",
        docs_url="https://platform.openai.com/docs/bots",
    ),
    Bot(
        name="ChatGPT-User",
        user_agent=(
            "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); "
            "compatible; ChatGPT-User/1.0; +https://openai.com/bot"
        ),
        robots_token="ChatGPT-User",
        purpose="user_triggered",
        docs_url="https://platform.openai.com/docs/bots",
    ),
    Bot(
        name="ClaudeBot",
        user_agent=(
            "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); "
            "compatible; ClaudeBot/1.0; +claudebot@anthropic.com"
        ),
        robots_token="ClaudeBot",
        purpose="training",
        docs_url="https://anthropic.com/legal/ai-crawling",
    ),
    Bot(
        name="Claude-User",
        user_agent=(
            "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); "
            "compatible; Claude-User/1.0; +claude-user@anthropic.com"
        ),
        robots_token="Claude-User",
        purpose="user_triggered",
        docs_url="https://anthropic.com/legal/ai-crawling",
    ),
    Bot(
        name="anthropic-ai",
        user_agent="anthropic-ai",
        robots_token="anthropic-ai",
        purpose="training",
        docs_url="https://anthropic.com/legal/ai-crawling",
    ),
    Bot(
        name="PerplexityBot",
        user_agent=(
            "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); "
            "compatible; PerplexityBot/1.0; +https://perplexity.ai/perplexitybot"
        ),
        robots_token="PerplexityBot",
        purpose="search",
        docs_url="https://docs.perplexity.ai/guides/bots",
    ),
    Bot(
        name="Perplexity-User",
        user_agent=(
            "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); "
            "compatible; Perplexity-User/1.0; +https://perplexity.ai/perplexity-user"
        ),
        robots_token="Perplexity-User",
        purpose="user_triggered",
        docs_url="https://docs.perplexity.ai/guides/bots",
    ),
    Bot(
        name="Google-Extended",
        user_agent="Mozilla/5.0 (compatible; Google-Extended)",
        robots_token="Google-Extended",
        purpose="training",
        docs_url="https://developers.google.com/search/docs/crawling-indexing/overview-google-crawlers",
    ),
    Bot(
        name="Googlebot",
        user_agent="Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
        robots_token="Googlebot",
        purpose="search",
        docs_url="https://developers.google.com/search/docs/crawling-indexing/overview-google-crawlers",
    ),
    Bot(
        name="Bingbot",
        user_agent="Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)",
        robots_token="bingbot",
        purpose="search",
        docs_url="https://www.bing.com/webmasters/help/how-to-identify-bingbot",
    ),
    Bot(
        name="CCBot",
        user_agent="Mozilla/5.0 (compatible; CCBot/2.0; +https://commoncrawl.org/faq/)",
        robots_token="CCBot",
        purpose="training",
        docs_url="https://commoncrawl.org/ccbot",
    ),
    Bot(
        name="meta-externalagent",
        user_agent=(
            "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); "
            "compatible; meta-externalagent/1.1 (+https://developers.facebook.com/docs/sharing/webmasters/crawler)"
        ),
        robots_token="meta-externalagent",
        purpose="training",
        docs_url="https://developers.facebook.com/docs/sharing/webmasters/crawler",
    ),
    Bot(
        name="Applebot-Extended",
        user_agent="Mozilla/5.0 (compatible; Applebot-Extended/1.0)",
        robots_token="Applebot-Extended",
        purpose="training",
        docs_url="https://support.apple.com/en-us/119829",
    ),
    Bot(
        name="Bytespider",
        user_agent="Mozilla/5.0 (compatible; Bytespider; spider-feedback@bytedance.com)",
        robots_token="Bytespider",
        purpose="training",
        docs_url="https://www.bytedance.com/en/robots",
    ),
)

DEFAULT_BOT_NAMES: tuple[str, ...] = (
    "GPTBot",
    "OAI-SearchBot",
    "ChatGPT-User",
    "ClaudeBot",
    "PerplexityBot",
    "Google-Extended",
    "CCBot",
)

_BY_NAME = {b.name.lower(): b for b in BOTS}
_BY_TOKEN = {b.robots_token.lower(): b for b in BOTS}


def get(name: str) -> Bot:
    """Look up by display name or robots token, case-insensitively."""
    key = name.strip().lower()
    if key in _BY_NAME:
        return _BY_NAME[key]
    if key in _BY_TOKEN:
        return _BY_TOKEN[key]
    raise KeyError(f"Unknown bot {name!r}. Known: {', '.join(sorted(_BY_NAME))}")


def known(name: str) -> bool:
    key = name.strip().lower()
    return key in _BY_NAME or key in _BY_TOKEN


def resolve(names: list[str] | None) -> list[Bot]:
    """Resolve a configured name list, defaulting to DEFAULT_BOT_NAMES.

    Unknown names are an error rather than a silent skip: a typo that silently
    dropped ClaudeBot from an audit would understate the problem.
    """
    if not names:
        names = list(DEFAULT_BOT_NAMES)
    return [get(n) for n in names]


def token_for(name: str) -> str:
    return get(name).robots_token
