"""Starter-file generation (ROADMAP M2, CLI_SPEC §2.6).

Every generator here is a **proposal derived from what the crawl observed**, not
an opinion about what the site should say. That distinction is the whole design:

- `llms.txt` lists only pages the audit actually found and their real titles.
- `robots.txt` is a policy preset the user picks, plus the site's own existing
  rules preserved and commented.
- `jsonld` is a skeleton with required fields left blank and marked, because a
  generated `sameAs` or `logo` URL that does not exist is worse than a missing one.

Nothing here overwrites an existing file without `--force`, and nothing reports a
generated artifact as improving the score. Per ADR-010 and CHECKS §7, `llms.txt`
is informational: publishing one must not be sold as a ranking or citation win,
because no published evidence says crawlers fetch it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from .extract.view import PageBundle

# Default output paths, relative to the working directory. Deliberately *not*
# URL-style ("/robots.txt"): this is where the file goes on disk, and a leading
# slash would write to the filesystem root. `--output` overrides it.
ROBOTS_TXT_PATH = "robots.txt"
LLMS_TXT_PATH = "llms.txt"

# robots.txt policy presets (CLI_SPEC §2.6).
ROBOT_POLICIES = (
    "allow-all",
    "allow-search-block-training",
    "block-all-ai",
)

# Bot tokens blocked by `allow-search-block-training`, grouped by who honours
# them. Kept explicit rather than pattern-matched so a preset is auditable: a
# user can see exactly which crawlers a preset denies.
TRAINING_BOTS = (
    "GPTBot",
    "ClaudeBot",
    "Claude-User",
    "Claude-SearchBot",
    "Google-Extended",
    "PerplexityBot",
    "Amazonbot",
    "Meta-ExternalAgent",
    "Applebot-Extended",
    "CCBot",
    "cohere-ai",
    "Diffbot",
    "MistralAI-User",
)

# Bots that fetch for search or user-requested retrieval, which the preset keeps
# allowed. Naming these matters: a preset that blocks "all AI" also blocks the
# crawlers that put a site in an answer, which is usually not what the user meant.
SEARCH_BOTS = (
    "Googlebot",
    "Bingbot",
    "DuckDuckBot",
    "Baiduspider",
    "YandexBot",
    "Applebot",
    "FacebookBot",
    "Twitterbot",
    "LinkedInBot",
    "Slackbot",
    "Discordbot",
    "Telegrambot",
)

AI_BOT_TOKENS = (
    frozenset(TRAINING_BOTS)
    | frozenset(SEARCH_BOTS)
    | frozenset(
        {
            "GPTBot",
            "ChatGPT-User",
            "OAI-SearchBot",
            "anthropic-ai",
            "Bytespider",
            "ImagesiftBot",
            "omgili",
            "PanguBot",
        }
    )
)


class GeneratorError(Exception):
    """Usage error: exit code 2."""


@dataclass
class PageEntry:
    """One page the audit actually found, with what it knows about it."""

    url: str
    title: str
    description: str = ""
    text_chars: int = 0
    is_start: bool = False

    @property
    def label(self) -> str:
        """A human title, or the URL when the page has none."""
        return self.title.strip() or self.url


@dataclass
class GenerationResult:
    """The generated content, plus where it came from and what it omits."""

    content: str
    path: str
    kind: str
    notes: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def byte_count(self) -> int:
        return len(self.content.encode("utf-8"))


# --------------------------------------------------------------- page catalogue


def page_entries(bundles: list[PageBundle], start_url: str = "") -> list[PageEntry]:
    """Turn fetched pages into catalogue entries, skipping ones with no text.

    A page with no extractable text is excluded rather than listed as a title-less
    link: an `llms.txt` that points a crawler at an empty page is a worse artifact
    than one that omits it.
    """
    entries: list[PageEntry] = []
    for bundle in bundles:
        view = bundle.views.get("browser-nojs")
        text = view.text if view else ""
        if not text.strip():
            continue
        meta = bundle.structure.meta if bundle.structure else None
        url = bundle.final_url or bundle.url
        entries.append(
            PageEntry(
                url=url,
                title=(meta.title if meta and meta.title else "") or "",
                description=(meta.description if meta and meta.description else "") or "",
                text_chars=len(text.strip()),
                is_start=(url.rstrip("/") == start_url.rstrip("/")) if start_url else False,
            )
        )
    return entries


def _group_by_first_path_segment(entries: list[PageEntry]) -> list[tuple[str, list[PageEntry]]]:
    """Group pages under their top-level path section.

    Depth 1 is deliberate: `/docs/getting-started` and `/docs/api` belong in one
    section, while `/blog/...` is a different kind of page and gets its own.
    """
    groups: dict[str, list[PageEntry]] = {}
    for entry in entries:
        path = urlparse(entry.url).path.strip("/")
        segment = path.split("/")[0] if path and path else ""
        groups.setdefault(segment, []).append(entry)
    # Root first, then alphabetical, so the file is stable between runs.
    return sorted(groups.items(), key=lambda kv: (kv[0] != "", kv[0]))


# ------------------------------------------------------------------ llms.txt


def generate_llms_txt(
    entries: list[PageEntry],
    *,
    site_url: str,
    title: str = "",
    description: str = "",
) -> GenerationResult:
    """Build an `llms.txt` from the pages the crawl actually found.

    The shape follows the community proposal: an H1 naming the site, a blockquote
    summary, then sections of markdown links grouped by path.
    """
    notes = [
        "Generated by geoctl from the pages this audit fetched. It is a starting "
        "point: check the wording, add sections for pages the crawl did not reach, "
        "and delete anything that is not meant to be public.",
        "Per CHECKS §7, publishing this file is informational. No major AI platform "
        "documents fetching llms.txt from third-party sites, so it is not expected "
        "to change how your site is cited.",
    ]
    if not entries:
        notes.append(
            "No pages with extractable text were found, so this file lists no links. "
            "That usually means the crawl was blocked or the site renders only via "
            "JavaScript — fix that first, then re-run."
        )
        return GenerationResult(
            content=_llms_header(site_url, title, description) + "\n## Pages\n\n(none found)\n",
            path=LLMS_TXT_PATH,
            kind="llms-txt",
            notes=notes,
            metadata={"page_count": 0},
        )

    site_name = title.strip() or _host(site_url)
    lines = [
        f"# {site_name}",
        "",
        f"> {description.strip() or f'Facts and documentation about {site_name}.'}",
        "",
    ]
    # The start page belongs in an "Overview" section of its own rather than
    # being sorted into "/" alongside everything else.
    start = [e for e in entries if e.is_start]
    rest = [e for e in entries if not e.is_start]

    if start:
        lines += ["## Overview", ""]
        lines += [f"- [{e.label}]({e.url})" for e in start]
        lines.append("")

    for segment, group in _group_by_first_path_segment(rest):
        heading = "Other" if not segment else segment.replace("-", " ").replace("_", " ").title()
        lines += [f"## {heading}", ""]
        lines += [f"- [{e.label}]({e.url})" for e in group]
        lines.append("")

    if not start and not rest:
        lines += ["## Pages", "", "(none found)", ""]

    content = "\n".join(lines).rstrip() + "\n"
    return GenerationResult(
        content=content,
        path=LLMS_TXT_PATH,
        kind="llms-txt",
        notes=notes,
        metadata={
            "page_count": len(entries),
            "untitled": sum(1 for e in entries if not e.title.strip()),
            "sections": len({urlparse(e.url).path.strip("/").split("/")[0] for e in rest}) + 1,
        },
    )


def _llms_header(site_url: str, title: str, description: str) -> str:
    site_name = title.strip() or _host(site_url)
    summary = description.strip() or f"Facts and documentation about {site_name}."
    return f"# {site_name}\n\n> {summary}\n\n"


def _host(url: str) -> str:
    return urlparse(url).netloc or url


# ------------------------------------------------------------------ robots.txt


def generate_robots(
    *,
    site_url: str,
    policy: str = "allow-search-block-training",
    sitemaps: list[str] | None = None,
    existing: str = "",
    crawl_delay: int | None = None,
) -> GenerationResult:
    """Build a robots.txt from a policy preset.

    The site's existing rules are preserved verbatim in a comment rather than
    merged: silently rewriting someone's robots.txt is not a thing a tool should
    do on a guess, and the user can diff the two and decide.
    """
    if policy not in ROBOT_POLICIES:
        raise GeneratorError(f"Unknown policy {policy!r}; choose from {', '.join(ROBOT_POLICIES)}")

    host = _host(site_url)
    lines = [
        f"# robots.txt for {host}",
        f"# Generated by geoctl from the preset '{policy}'.",
        "# Review before publishing. This file is a proposal, not a verified improvement:",
        "# blocking a crawler removes it from that system, and no tool can predict the result.",
    ]
    if existing.strip():
        lines += [
            "",
            "# ---- your existing robots.txt, preserved verbatim ----",
            *[f"# {line}" for line in existing.strip().splitlines()],
            "# ---- end of existing robots.txt ----",
        ]

    lines.append("")
    if policy == "allow-all":
        lines += [
            "# Preset: allow all. Every crawler is permitted.",
            "User-agent: *",
            "Allow: /",
            "",
        ]
    elif policy == "block-all-ai":
        lines += [
            "# Preset: block all AI crawlers. Note this blocks search and answer-engine",
            "# crawlers too, not only training crawlers — if you want to stay findable in",
            "# AI answers, use the other preset instead.",
            "User-agent: *",
            "Disallow: /",
            "",
            *[
                f"# Explicit, so the intent is readable in review.\nUser-agent: {bot}\nDisallow: /"
                for bot in sorted(AI_BOT_TOKENS)
            ],
        ]
    else:
        lines += [
            "# Preset: allow search and user-requested retrieval; block training crawlers.",
            "",
            "# Allowed: the crawlers that fetch because a person or a search engine asked,",
            "# which is what keeps the site findable and citable in answers.",
        ]
        lines.append("User-agent: *")
        lines.append("Allow: /")
        lines.append("")
        lines.append("# Blocked: crawlers that gather content for model training.")
        for bot in TRAINING_BOTS:
            lines += [f"User-agent: {bot}", "Disallow: /", ""]

    if crawl_delay:
        lines += [f"Crawl-delay: {crawl_delay}", ""]

    for sitemap in sitemaps or []:
        lines.append(f"Sitemap: {sitemap}")
    if sitemaps:
        lines.append("")

    notes = [
        f"Preset '{policy}' applied to {host}.",
        "The User-agent lines are the control surface AI crawler operators document "
        "and honour; they are also the only place a block can be enforced, so they "
        "work regardless of how the server treats the request.",
    ]
    if policy == "block-all-ai":
        notes.append(
            "This preset blocks search and answer-engine crawlers as well as "
            "training ones (Googlebot, Bingbot, Applebot), because it disallows "
            "everything for every agent. That also removes the site from AI "
            "answers. If you want to stay findable, the "
            "'allow-search-block-training' preset is the one you want."
        )
    if not sitemaps:
        notes.append(
            "No Sitemap: line was added because the audit found no sitemap. Publishing "
            "one and referencing it here is the cheapest way for a crawler to "
            "enumerate your pages (DIS-001)."
        )

    return GenerationResult(
        content="\n".join(lines).rstrip() + "\n",
        path=ROBOTS_TXT_PATH,
        kind="robots",
        notes=notes,
        metadata={"policy": policy, "sitemaps": list(sitemaps or []), "preserved": bool(existing)},
    )


# --------------------------------------------------------------------- jsonld

JSONLD_TYPES = ("Organization", "WebSite", "Article")


@dataclass
class JsonLdField:
    """One field in a skeleton, and whether we could fill it from the crawl."""

    name: str
    value: str | None
    required: bool
    hint: str = ""


# Required and recommended properties per schema.org type, restricted to what
# the crawl can actually observe. Anything needing a human decision (a logo file,
# a verified social profile) is left blank with a hint rather than guessed.
JSONLD_SKELETONS: dict[str, dict[str, object]] = {
    "Organization": {
        "required": ["name", "url"],
        "optional": ["logo", "description", "sameAs", "contactPoint"],
        "hints": {
            "logo": "Absolute URL to a logo image file. Must exist and be crawlable; "
            "guessing this one is how a site ends up with a broken logo in search.",
            "sameAs": "Official profile URLs, one per line. Only list profiles you control.",
            "description": "One sentence on what the organization does.",
        },
    },
    "WebSite": {
        "required": ["name", "url"],
        "optional": ["description", "inLanguage"],
        "hints": {
            "inLanguage": "BCP 47 tag, e.g. en-US.",
            "description": "One sentence on what the site covers.",
        },
    },
    "Article": {
        "required": ["headline"],
        "optional": ["description", "datePublished", "dateModified", "author", "image"],
        "hints": {
            "headline": "The article's H1 or title.",
            "datePublished": "ISO 8601, e.g. 2026-01-31.",
            "author": 'An Organization or Person object: {"@type": "Person", "name": "..."}',
            "image": "Absolute URL to the lead image.",
        },
    },
}


def generate_jsonld(
    schema_type: str,
    *,
    site_url: str,
    title: str = "",
    description: str = "",
) -> GenerationResult:
    """Build a JSON-LD skeleton, filling only what the crawl observed.

    Fields the crawl cannot know are emitted as commented-out placeholders inside
    a `_geoctl_todo` block, so the artifact is valid JSON, validates, and still
    shows the user exactly what is left to do. A skeleton that parses is worth
    more than a filled-in guess that does not.
    """
    if schema_type not in JSONLD_SKELETONS:
        raise GeneratorError(f"Unknown type {schema_type!r}; choose from {', '.join(JSONLD_TYPES)}")
    spec = JSONLD_SKELETONS[schema_type]
    required = list(spec["required"])  # type: ignore[arg-type]
    optional = list(spec["optional"])  # type: ignore[arg-type]
    hints = dict(spec["hints"])  # type: ignore[arg-type]

    observed: dict[str, Any] = {}
    if title.strip() and "name" in required:
        observed["name"] = title.strip()
    if "headline" in required and title.strip():
        observed["headline"] = title.strip()
    if description.strip() and "description" in required + optional:
        observed["description"] = description.strip()
    if "url" in required:
        observed["url"] = site_url

    # Required fields the crawl cannot see must be filled in by the user; leaving
    # them out entirely would produce a document that fails the very validation
    # this is meant to help with.
    missing_required = [name for name in required if name not in observed]
    todos = [
        {
            "field": name,
            "required": name in missing_required,
            "hint": hints.get(name, ""),
        }
        for name in [*missing_required, *optional]
    ]

    document: dict[str, Any] = {"@context": "https://schema.org", "@type": schema_type, **observed}
    document["_geoctl_todo"] = {
        "note": (
            "Remove this block once the fields are filled. Fields marked required "
            "must be present for the document to be valid."
        ),
        "fields": [t for t in todos if t["required"]],
        "optional_fields": [t for t in todos if not t["required"] and t["hint"]],
    }

    content = json.dumps(document, indent=2, ensure_ascii=False) + "\n"

    notes = [
        f"Skeleton for schema.org/{schema_type}, filled from what the audit observed.",
        "Fields the crawl cannot know are listed under _geoctl_todo and are not "
        "guessed — a wrong logo URL or social profile is worse than a missing one.",
        "Delete the _geoctl_todo block before shipping. Per CHECKS, structured data "
        "is reported, never scored: this tool takes no position on whether it changes "
        "how you are cited.",
    ]
    if missing_required:
        notes.append(
            f"Required and still missing: {', '.join(missing_required)}. This document "
            "will not validate until you fill them in."
        )

    return GenerationResult(
        content=content,
        path=f"{schema_type.lower()}.jsonld.json",
        kind="jsonld",
        notes=notes,
        metadata={
            "type": schema_type,
            "filled": sorted(observed),
            "missing_required": missing_required,
        },
    )


__all__ = [
    "AI_BOT_TOKENS",
    "JSONLD_TYPES",
    "LLMS_TXT_PATH",
    "ROBOTS_TXT_PATH",
    "ROBOT_POLICIES",
    "SEARCH_BOTS",
    "TRAINING_BOTS",
    "GenerationResult",
    "GeneratorError",
    "PageEntry",
    "generate_jsonld",
    "generate_llms_txt",
    "generate_robots",
    "page_entries",
]
