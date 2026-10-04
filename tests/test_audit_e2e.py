"""End-to-end audit against a local fixture site. No network, no API key."""

from __future__ import annotations

import asyncio

import pytest

from fixtures.site import (
    BAD_HEADINGS_PAGE,
    BROKEN_JSONLD_PAGE,
    GOOD_PAGE,
    HYBRID_PAGE,
    NO_SCHEMA_PAGE,
    ROBOTS_ALLOW_ALL,
    ROBOTS_BLOCK_ALL,
    ROBOTS_POLICY,
    ROBOTS_WILDCARD,
    SITEMAP,
    SITEMAP_INDEX,
    SPA_SHELL,
    FixtureSite,
    Route,
    challenge_site,
    good_site,
    waf_site,
)
from geoctl.audit import (
    audit,
    build_corpora,
    build_corpora_crawler_only,
    build_report,
)


def run_audit(config, url):  # type: ignore[no-untyped-def]
    return asyncio.run(audit(config, url, cache=None, use_cache=False))


@pytest.fixture
def known_good(serve):  # type: ignore[no-untyped-def]
    """A well-built site. Every check should pass or warn — this is what the
    < 5% false-positive target is measured against."""
    return serve(good_site()) + "/"


def by_id(report, check_id: str):  # type: ignore[no-untyped-def]
    for check in report.checks:
        if check.id == check_id:
            return check
    raise AssertionError(f"{check_id} did not run")


# --------------------------------------------------------------- the happy path


def test_audit_of_a_good_site_scores_well(known_good, allow_private_config):
    report = build_report(run_audit(allow_private_config, known_good), allow_private_config)

    assert report.target.url == known_good
    assert report.target.sitemap_found is True
    assert report.target.pages_audited >= 1
    # A known-good site must not look broken. The bar is deliberately modest:
    # FIXTURES.md measures the false-positive rate, not a perfect score.
    assert report.score.overall >= 70, [c.message for c in report.checks if c.status == "fail"]

    # All three access checks should pass: nothing blocks the simulated bots.
    for check_id in ("ACC-001", "ACC-002", "ACC-003"):
        assert by_id(report, check_id).status == "pass", by_id(report, check_id).message


def test_report_matches_the_published_schema(known_good, allow_private_config):
    from geoctl.report.json import dumps

    report = build_report(run_audit(allow_private_config, known_good), allow_private_config)
    validated = type(report).model_validate_json(dumps(report))
    assert validated.schema_version == "1.0.0"
    assert validated.score.max == 100.0


def test_score_categories_hold_only_scored_checks(known_good, allow_private_config):
    report = build_report(run_audit(allow_private_config, known_good), allow_private_config)
    assert set(report.score.categories) <= {"access", "rendering", "discovery"}
    for check in report.checks:
        if check.weight == 0:
            assert check.points == 0.0, check.id


def test_terminal_report_mentions_the_limits(known_good, allow_private_config):
    from geoctl.report.terminal import render

    report = build_report(run_audit(allow_private_config, known_good), allow_private_config)
    text = render(report)
    assert "Deterministic score" in text
    assert "Not citations or rankings" in text


def test_markdown_report_renders(known_good, allow_private_config):
    from geoctl.report.markdown import render

    report = build_report(run_audit(allow_private_config, known_good), allow_private_config)
    text = render(report)
    assert text.startswith("# geoctl report:")
    assert "Not citations or rankings" in text


# ---------------------------------------------------------------- access checks


def test_waf_blocking_fails_parity(serve, allow_private_config):
    url = serve(waf_site()) + "/"
    report = build_report(run_audit(allow_private_config, url), allow_private_config)

    parity = by_id(report, "ACC-002")
    assert parity.status == "fail"
    # The evidence must name a bot and show the status difference, or the
    # finding is not actionable.
    row = parity.evidence["divergence"][0]["samples"][0]
    assert row["browser_status"] == 200
    assert row["bot_status"] == 403
    assert row["bot_blocked_by"] == "waf"
    diverged = parity.evidence["divergence"]
    assert diverged
    assert any(d["bot"] for d in diverged)
    assert parity.fix is not None


def test_challenge_page_with_200_is_caught(serve, allow_private_config):
    url = serve(challenge_site()) + "/"
    report = build_report(run_audit(allow_private_config, url), allow_private_config)

    acc003 = by_id(report, "ACC-003")
    assert acc003.status in ("warn", "fail")
    assert any(d.get("challenge") for d in acc003.evidence["details"])


def test_missing_robots_passes_as_default_allow(serve, allow_private_config):
    site = good_site()
    del site.routes["/robots.txt"]
    url = serve(site) + "/"
    report = build_report(run_audit(allow_private_config, url), allow_private_config)

    acc001 = by_id(report, "ACC-001")
    assert acc001.status == "pass"
    assert "default" in acc001.message.lower()


def test_policy_block_is_a_warn_under_report_policy(serve, allow_private_config):
    site = good_site()
    site.add("/robots.txt", Route(
        body=ROBOTS_POLICY.encode(), content_type="text/plain"
    ))
    url = serve(site) + "/"

    allow_private_config.audit.policy = "report"
    report = build_report(run_audit(allow_private_config, url), allow_private_config)
    acc001 = by_id(report, "ACC-001")
    assert acc001.status == "warn"
    # Training bots blocked, search bots allowed: the evidence must let the user
    # see that this is a deliberate, split policy.
    purposes = acc001.evidence["blocked_by_purpose"]
    assert purposes.get("training")
    assert not purposes.get("search")

    allow_private_config.audit.policy = "ignore"
    ignored = build_report(run_audit(allow_private_config, url), allow_private_config)
    assert by_id(ignored, "ACC-001").status == "pass"


def test_wildcard_robots_rules_are_evaluated_per_bot(serve, allow_private_config):


    site = good_site()
    site.add("/robots.txt", Route(body=ROBOTS_WILDCARD.encode(), content_type="text/plain"))
    url = serve(site) + "/"
    report = build_report(run_audit(allow_private_config, url), allow_private_config)

    verdicts = {row["bot"]: row["verdict"] for row in by_id(report, "ACC-001").evidence["bots"]}
    # ROBOTS_WILDCARD disallows ClaudeBot and allows GPTBot explicitly.
    assert verdicts["ClaudeBot"] == "blocked"
    assert verdicts["GPTBot"] == "allowed"
    # The wildcard rule must not accidentally catch the allow-listed bots.
    assert verdicts["PerplexityBot"] == "allowed"


def test_block_all_robots_is_reported_under_policy_fail(serve, allow_private_config):


    site = good_site()
    site.add("/robots.txt", Route(body=ROBOTS_BLOCK_ALL.encode(), content_type="text/plain"))
    url = serve(site) + "/"

    allow_private_config.audit.policy = "fail"
    report = build_report(run_audit(allow_private_config, url), allow_private_config)
    assert by_id(report, "ACC-001").status == "fail"


# ------------------------------------------------------------ rendering checks


def test_client_rendered_shell_fails_ren001(serve, allow_private_config):
    site = good_site()
    site.add_html("/", SPA_SHELL)
    url = serve(site) + "/"
    report = build_report(run_audit(allow_private_config, url), allow_private_config)

    ren001 = by_id(report, "REN-001")
    assert ren001.status == "fail"
    assert ren001.confidence != "high" or ren001.evidence["shell_markers"]
    assert ren001.evidence["framework_markers"]
    assert ren001.fix is not None


def test_static_content_passes_ren001(serve, allow_private_config):
    url = serve(good_site()) + "/"
    report = build_report(run_audit(allow_private_config, url), allow_private_config)
    assert by_id(report, "REN-001").status == "pass"
    assert by_id(report, "REN-002").status == "pass"


def test_hybrid_page_is_not_a_clean_pass(serve, allow_private_config):
    site = good_site()
    site.add_html("/pricing", HYBRID_PAGE)
    url = serve(site) + "/"
    report = build_report(run_audit(allow_private_config, url), allow_private_config)
    # Hybrid SSR sits in the middle: the check must not call it a clean pass.
    assert by_id(report, "REN-001").status != "pass"


# ----------------------------------------------------------- sitemap behaviour


def test_sitemap_index_is_followed(serve, allow_private_config):


    site = good_site()
    site.add("/sitemap.xml", Route(body=SITEMAP_INDEX.encode(),
        content_type="application/xml"))
    site.add("/sitemap-pages.xml", Route(body=SITEMAP.encode(), content_type="application/xml"))
    url = serve(site) + "/"
    report = build_report(run_audit(allow_private_config, url), allow_private_config)

    dis001 = by_id(report, "DIS-001")
    assert dis001.status == "pass"
    assert len(dis001.evidence["sitemap_urls"]) >= 2


def test_missing_sitemap_fails_dis001_with_weight_1(serve, allow_private_config):
    site = good_site()
    del site.routes["/sitemap.xml"]
    site.add("/robots.txt", Route(
        body=b"User-agent: *\nAllow: /\n", content_type="text/plain"))
    url = serve(site) + "/"
    report = build_report(run_audit(allow_private_config, url), allow_private_config)

    dis001 = by_id(report, "DIS-001")
    assert dis001.status == "fail"
    assert dis001.weight == 1
    assert dis001.points == 0.0


def test_stale_lastmod_is_a_warn(serve, allow_private_config):
    from fixtures.site import SITEMAP_STALE, Route

    site = good_site()
    site.add("/sitemap.xml", Route(body=SITEMAP_STALE.encode(), content_type="application/xml"))
    url = serve(site) + "/"
    report = build_report(run_audit(allow_private_config, url), allow_private_config)
    assert by_id(report, "DIS-001").status == "warn"


# ------------------------------------------------------------ structured data


def test_missing_jsonld_fails_sd001(serve, allow_private_config):
    """No page has JSON-LD. max_pages=1 isolates the home page from the sitemap
    sample, which still carries schema."""
    site = good_site()
    site.add_html("/", NO_SCHEMA_PAGE)
    url = serve(site) + "/"
    allow_private_config.audit.max_pages = 1
    report = build_report(run_audit(allow_private_config, url), allow_private_config)
    assert by_id(report, "SD-001").status == "fail"


def test_malformed_jsonld_is_a_warn_not_a_fail(serve, allow_private_config):
    site = good_site()
    site.add_html("/", BROKEN_JSONLD_PAGE)
    url = serve(site) + "/"
    report = build_report(run_audit(allow_private_config, url), allow_private_config)
    sd001 = by_id(report, "SD-001")
    assert sd001.status == "warn"
    assert sd001.evidence["pages"][0]["errors"]


def test_heading_problems_are_reported(serve, allow_private_config):
    """The bad page must be the start URL, and the only page audited, or the
    well-formed pages dilute the finding."""
    site = good_site()
    site.add_html("/", BAD_HEADINGS_PAGE)
    url = serve(site) + "/"
    allow_private_config.audit.max_pages = 1
    del site.routes["/sitemap.xml"]
    report = build_report(run_audit(allow_private_config, url), allow_private_config)
    assert by_id(report, "STR-004").status in ("warn", "fail")
    assert by_id(report, "STR-005").status in ("warn", "fail")
    assert by_id(report, "STR-006").status == "warn"  # lang="en_US"


# ------------------------------------------------------------------- the facts


def test_https_is_required_by_site001(known_good, allow_private_config):
    report = build_report(run_audit(allow_private_config, known_good), allow_private_config)
    # The fixture server is plain HTTP, so SITE-001 must fail honestly rather
    # than quietly reporting transport security it did not see.
    assert by_id(report, "SITE-001").status == "fail"


def test_corpora_need_a_rich_or_independent_ground_truth(known_good, allow_private_config):
    state = run_audit(allow_private_config, known_good)
    # No --render, so there is no independent ground truth and no eval corpora.
    assert build_corpora(state, 3) == []
    crawler_only = build_corpora_crawler_only(state, 3)
    assert crawler_only
    assert all(c.ground_truth_text == "" for c in crawler_only)


def test_errors_are_collected_not_raised(serve, allow_private_config):
    """A dead page must not abort the audit (ARCHITECTURE §11)."""
    site = FixtureSite()
    site.add_html("/", GOOD_PAGE)
    site.add("/robots.txt", Route(
        body=ROBOTS_ALLOW_ALL.encode(), content_type="text/plain"))
    url = serve(site) + "/missing-page"
    report = build_report(run_audit(allow_private_config, url), allow_private_config)
    assert report.target.pages_audited >= 0
    assert report.errors
    assert all(e.code and e.message for e in report.errors)