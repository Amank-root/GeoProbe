"""`geoctl generate`: proposals derived from what the crawl actually found.

Every generator is tested on the property that matters: it never invents content.
A generated robots.txt that blocks a crawler the user wanted, an llms.txt listing
pages that do not exist, or a JSON-LD logo URL pointing at nothing are all worse
than the missing file, so the assertions are about fidelity to the crawl rather
than about the exact bytes.
"""

from __future__ import annotations

import json

import pytest

from geoctl.generate import (
    GeneratorError,
    PageEntry,
    generate_jsonld,
    generate_llms_txt,
    generate_robots,
    page_entries,
)

SITE = "https://acme.test/"


def entry(
    url: str, title: str = "", *, start: bool = False, text: str = "some content"
) -> PageEntry:
    return PageEntry(url=url, title=title, text_chars=len(text), is_start=start)


# ------------------------------------------------------------------- llms.txt


def test_llms_txt_lists_only_pages_the_crawl_found():
    entries = [entry(SITE, "Home", start=True), entry("https://acme.test/docs/api", "API")]
    out = generate_llms_txt(entries, site_url=SITE).content
    assert "https://acme.test/docs/api" in out
    # Nothing invented.
    assert out.count("- [") == 2


def test_llms_txt_never_links_a_page_it_did_not_see():
    """The property that makes the artifact safe to publish."""
    entries = [entry(SITE, "Home", start=True)]
    out = generate_llms_txt(entries, site_url=SITE).content
    assert "https://acme.test/" in out
    for line in out.splitlines():
        if line.startswith("- ["):
            url = line.split("](")[1].rstrip(")")
            assert url in {e.url for e in entries}


def test_llms_txt_has_the_shape_dis003_checks_for():
    """DIS-003 warns unless there is an H1, a summary, and link sections."""
    entries = [entry(SITE, "Home", start=True), entry("https://acme.test/docs", "Docs")]
    out = generate_llms_txt(entries, site_url=SITE, description="Docs for widgets.").content
    assert any(line.startswith("# ") for line in out.splitlines()), "no H1"
    assert "> Docs for widgets." in out, "no summary"
    assert "[" in out and "](" in out, "no link section"


def test_llms_txt_uses_the_url_when_a_page_has_no_title():
    """An untitled link is better than a blank label."""
    out = generate_llms_txt([entry("https://acme.test/x", "", start=True)], site_url=SITE).content
    assert "[https://acme.test/x]" in out


def test_llms_txt_groups_pages_by_top_level_path():
    entries = [
        entry(SITE, "Home", start=True),
        entry("https://acme.test/docs/intro", "Intro"),
        entry("https://acme.test/docs/api", "API"),
        entry("https://acme.test/blog/post", "Post"),
    ]
    out = generate_llms_txt(entries, site_url=SITE).content
    assert "## Docs" in out
    assert "## Blog" in out
    # Both docs pages land in one section rather than being sorted by full path.
    docs_section = out.split("## Docs")[1].split("##")[0]
    assert "intro" in docs_section and "api" in docs_section


def test_llms_txt_puts_the_start_page_in_overview():
    entries = [entry(SITE, "Home", start=True), entry("https://acme.test/blog/p", "P")]
    out = generate_llms_txt(entries, site_url=SITE).content
    assert "## Overview" in out
    assert SITE in out.split("## Overview")[1].split("##")[0]


def test_llms_txt_is_deterministic():
    """Two runs must produce identical bytes, or CI sees phantom diffs."""
    entries = [entry(SITE, "Home", start=True), entry("https://acme.test/b", "B")]
    assert (
        generate_llms_txt(entries, site_url=SITE).content
        == generate_llms_txt(entries, site_url=SITE).content
    )


def test_llms_txt_says_so_when_nothing_was_found():
    """An empty crawl must not yield a file that looks authoritative."""
    out = generate_llms_txt([], site_url=SITE)
    assert "(none found)" in out.content
    assert any("No pages" in n for n in out.notes)


def test_llms_txt_states_it_is_informational():
    """Per CHECKS §7 the file must not be sold as a ranking win."""
    out = generate_llms_txt([entry(SITE, "Home", start=True)], site_url=SITE)
    assert any("informational" in n for n in out.notes)


def test_page_entries_skips_pages_with_no_text():
    """Listing an empty page would point a crawler at nothing."""

    class _Bundle:
        def __init__(self, url: str, text: str) -> None:
            self.url = url
            self.final_url = url
            self.views = {"browser-nojs": type("V", (), {"text": text})()}
            self.structure = type(
                "S", (), {"meta": type("M", (), {"title": "T", "description": ""})()}
            )()

    bundles = [
        _Bundle("https://acme.test/ok", "real text"),
        _Bundle("https://acme.test/empty", "   "),
    ]
    out = page_entries(bundles, SITE)
    assert [e.url for e in out] == ["https://acme.test/ok"]


# ----------------------------------------------------------------- robots.txt


@pytest.mark.parametrize("policy", ["allow-all", "allow-search-block-training", "block-all-ai"])
def test_every_preset_produces_valid_robots_directives(policy):
    out = generate_robots(site_url=SITE, policy=policy).content
    assert "User-agent:" in out
    # Every non-comment line is a real directive.
    for line in out.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            assert line.split(":")[0] in {
                "User-agent",
                "Disallow",
                "Allow",
                "Sitemap",
                "Crawl-delay",
            }


def test_the_default_preset_blocks_training_bots():
    out = generate_robots(site_url=SITE, policy="allow-search-block-training").content
    assert "User-agent: GPTBot" in out
    assert "User-agent: ClaudeBot" in out
    assert "User-agent: Google-Extended" in out


def test_the_default_preset_does_not_block_search_crawlers():
    """Blocking these removes the site from AI answers, which is usually not
    what someone asking for this wants."""
    out = generate_robots(site_url=SITE, policy="allow-search-block-training").content
    for bot in ("Googlebot", "Bingbot", "Applebot"):
        block = f"User-agent: {bot}\nDisallow: /"
        assert block not in out, f"{bot} is blocked"


def test_block_all_ai_is_strictly_broader_and_says_so():
    out = generate_robots(site_url=SITE, policy="block-all-ai")
    assert "User-agent: *\nDisallow: /" in out.content
    # Normalised: the note is wrapped across lines, so match words rather than
    # asserting on one contiguous substring.
    joined = " ".join(" ".join(out.notes).split())
    assert "blocks search and answer-engine crawlers" in joined
    assert "Googlebot" in joined
    assert "allow-search-block-training" in joined


def test_allow_all_blocks_nothing():
    out = generate_robots(site_url=SITE, policy="allow-all").content
    assert "Disallow" not in out


def test_an_existing_robots_txt_is_preserved_not_merged():
    """Merging on a guess could silently unblock a path someone locked down."""
    existing = "User-agent: *\nDisallow: /admin\nDisallow: /private"
    out = generate_robots(
        site_url=SITE, policy="allow-search-block-training", existing=existing
    ).content
    assert "# Disallow: /admin" in out
    assert "# Disallow: /private" in out
    # And the original text is not silently dropped from the file.
    assert existing.count("Disallow") == out.count("# Disallow: /admin") + out.count(
        "# Disallow: /private"
    )


def test_sitemaps_are_referenced_when_found():
    out = generate_robots(site_url=SITE, sitemaps=["https://acme.test/sitemap.xml"]).content
    assert "Sitemap: https://acme.test/sitemap.xml" in out


def test_a_missing_sitemap_is_called_out():
    out = generate_robots(site_url=SITE, sitemaps=[])
    assert "Sitemap:" not in out.content
    assert any("no sitemap" in n for n in out.notes)


def test_an_unknown_policy_is_a_usage_error():
    with pytest.raises(GeneratorError, match="Unknown policy"):
        generate_robots(site_url=SITE, policy="make-it-fast")


def test_crawl_delay_is_only_emitted_when_asked():
    assert "Crawl-delay" not in generate_robots(site_url=SITE).content
    assert "Crawl-delay: 5" in generate_robots(site_url=SITE, crawl_delay=5).content


# --------------------------------------------------------------------- jsonld


@pytest.mark.parametrize("schema_type", ["Organization", "WebSite", "Article"])
def test_every_skeleton_is_valid_json(schema_type):
    """A skeleton that does not parse is worse than no file."""
    out = generate_jsonld(schema_type, site_url=SITE, title="Acme", description="Widgets.")
    parsed = json.loads(out.content)
    assert parsed["@context"] == "https://schema.org"
    assert parsed["@type"] == schema_type


def test_jsonld_fills_only_what_the_crawl_observed():
    out = json.loads(generate_jsonld("Organization", site_url=SITE, title="Acme").content)
    assert out["name"] == "Acme"
    assert out["url"] == SITE
    # The crawl cannot know these, so they must not be invented.
    assert "logo" not in out
    assert "sameAs" not in out


def test_jsonld_lists_the_fields_the_user_must_fill():
    out = generate_jsonld("Organization", site_url=SITE, title="Acme")
    todo = json.loads(out.content)["_geoctl_todo"]
    names = {f["field"] for f in todo["fields"]} | {f["field"] for f in todo["optional_fields"]}
    assert "logo" in names
    assert "sameAs" in names


def test_jsonld_reports_missing_required_fields():
    """An Article with no headline cannot validate, so say so rather than
    emitting a document that fails the check it is meant to help with."""
    out = generate_jsonld("Article", site_url=SITE, title="")
    assert "headline" in out.metadata["missing_required"]
    assert any("will not validate" in n for n in out.notes)


def test_jsonld_fills_the_article_headline_from_the_title():
    out = json.loads(generate_jsonld("Article", site_url=SITE, title="My Post").content)
    assert out["headline"] == "My Post"


def test_jsonld_tells_the_user_to_delete_the_todo_block():
    out = generate_jsonld("Organization", site_url=SITE, title="Acme")
    assert any("Delete the _geoctl_todo block" in n for n in out.notes)


def test_an_unknown_jsonld_type_is_a_usage_error():
    with pytest.raises(GeneratorError, match="Unknown type"):
        generate_jsonld("Product", site_url=SITE)


def test_jsonld_takes_the_description_from_the_crawl():
    out = json.loads(
        generate_jsonld("Organization", site_url=SITE, title="Acme", description="Widgets.").content
    )
    assert out["description"] == "Widgets."


# ------------------------------------------------------- shared guarantees


def test_no_generator_claims_to_improve_a_score():
    """The project's honesty commitment: these are proposals, not fixes."""
    results = [
        generate_llms_txt([entry(SITE, "Home", start=True)], site_url=SITE),
        generate_robots(site_url=SITE),
        generate_jsonld("Organization", site_url=SITE, title="Acme"),
    ]
    for r in results:
        joined = " ".join(r.notes).lower()
        for banned in ("will improve", "guarantees", "boosts your ranking"):
            assert banned not in joined
