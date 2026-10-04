"""The fixture catalog: one entry per required category in FIXTURES.md.

Each entry names a site builder, whether it is known-good, and which categories
of the coverage spec it exercises. The builders live in `site.py`; the expected
per-check statuses live in `expected/*.yaml` and are what the calibration runner
compares against.
"""

from __future__ import annotations

from fixtures import site as S

# (name, builder, known_good, coverage notes)
FIXTURES: tuple[tuple[str, object, bool, str], ...] = (
    # --- 1: static HTML, content-rich baseline (FIXTURES row 1)
    ("static-content-rich", S.good_site, True, "row 1: everything should pass or warn"),
    (
        "static-content-rich-2",
        S.good_site_variant,
        True,
        "row 1: a second known-good instance, so a single lucky fixture cannot pass the set",
    ),
    # --- 2: client-rendered SPA, empty shell (row 2, the most common real defect)
    ("spa-empty-shell", S.spa_site, False, "row 2: REN-001 must fail, ACC-002 must pass"),
    (
        "spa-empty-shell-2",
        S.spa_site_variant,
        False,
        "row 2: a second SPA, with the content in a differently-shaped payload",
    ),
    # --- 3: hybrid / partial SSR, the warn band (row 3)
    ("hybrid-partial-ssr", S.hybrid_site, False, "row 3: REN-001 between pass and fail"),
    ("ssr-content", S.ssr_site, True, "row 4: content present in raw HTML, REN-001 must pass"),
    # --- 5: deliberate robots.txt block (row 5)
    (
        "robots-blocks-training",
        S.robots_policy_site,
        False,
        "row 5: ACC-001 reports policy, not accident",
    ),
    (
        "robots-block-all",
        S.robots_block_all_site,
        False,
        "row 5: ACC-001 must fail under --policy fail",
    ),
    # --- 8: wildcards, $, Allow precedence (row 8)
    (
        "robots-wildcard-rules",
        S.robots_wildcard_site,
        False,
        "row 8: Protego wildcard, $ and Allow precedence (ADR-013)",
    ),
    # --- 9: missing robots.txt is default-allow (row 9)
    ("robots-missing", S.robots_missing_site, True, "row 9: ACC-001 must PASS as default-allow"),
    # --- 6: WAF / UA cloaking, invisible to robots.txt (row 6)
    (
        "waf-blocks-bots",
        S.waf_site,
        False,
        "row 6: ACC-002 fails even though robots.txt allows everything",
    ),
    # --- 6 variant: refuses one exact browser UA, serves every bot (issue #40)
    (
        "ua-fingerprint-block",
        S.ua_fingerprint_site,
        False,
        "issue #40: a fingerprintable browser baseline must not invert ACC-002",
    ),
    # --- 7: challenge page returned with 200 (row 7)
    (
        "challenge-page-200",
        S.challenge_site,
        False,
        "row 7: ACC-003 must not read a 200 challenge as success",
    ),
    # --- 10-12: sitemap handling (rows 10, 11, 12)
    (
        "sitemap-index",
        S.sitemap_index_site,
        False,
        "row 10: sitemap index followed to its children",
    ),
    ("sitemap-stale-lastmod", S.sitemap_stale_site, False, "row 11: future lastmod is a warn"),
    ("sitemap-missing", S.sitemap_missing_site, False, "row 12: DIS-001 fails at weight 1"),
    # --- 20: multi-URL site for sampling (row 20)
    (
        "multi-url-site",
        S.multi_page_site,
        True,
        "row 20: more URLs than --max-pages, so sampling is exercised",
    ),
    # --- 13: sitemap lists a noindex page (row 13)
    ("sitemap-lists-noindex", S.noindex_site, False, "row 13: DIS-002 reports the contradiction"),
    # --- 14-16: structured data (rows 14, 15, 16)
    (
        "jsonld-clean",
        S.jsonld_clean_site,
        True,
        "row 14: Organization, WebSite, Article all correct",
    ),
    (
        "jsonld-malformed",
        S.jsonld_broken_site,
        False,
        "row 15: a block that does not parse is a warn, not a fail",
    ),
    ("no-structured-data", S.no_schema_site, False, "row 16: SD-001 and SD-002 fail"),
    # --- 17, 18: heading hierarchy (rows 17, 18)
    ("headings-complete", S.headings_good_site, True, "row 17: clean hierarchy passes"),
    ("headings-skipped-level", S.headings_bad_site, False, "row 18: h2 to h4 and two H1s"),
    # --- 19, 25: extraction quality (rows 19, 25)
    (
        "boilerplate-heavy",
        S.boilerplate_site,
        False,
        "row 19: navigation and footer dominate the HTML",
    ),
    ("content-in-iframe", S.iframe_site, False, "row 25: main content only inside an iframe"),
    # --- 21-23: persona fixtures (rows 21, 22, 23)
    ("docs-site", S.docs_site, True, "row 21: DevRel persona, the strongest known-good case"),
    (
        "ecommerce-product",
        S.product_site,
        False,
        "row 22: Product JSON-LD expected for the product role",
    ),
    ("blog-with-byline", S.blog_site, True, "row 23: visible byline and machine-readable dates"),
    # --- 24: transport sanity (row 24)
    ("no-hsts", S.no_hsts_site, False, "row 24: HTTPS present but HSTS missing"),
    # --- 3/7 of the eval's discrimination gates (rows 26, 27, 28)
    ("very-small-page", S.tiny_page_site, False, "row 26: forces retrieval.mode whole_page"),
    (
        "facts-buried-deep",
        S.buried_facts_site,
        False,
        "row 27: key facts buried, retrieval must miss them",
    ),
    (
        "facts-in-client-component",
        S.client_facts_site,
        False,
        "row 28: the case the eval exists to catch",
    ),
    # --- known-good instances, so the set reaches the 40% floor FIXTURES.md sets
    (
        "known-good-no-llms-txt",
        S.good_no_llms_txt_site,
        True,
        "CHECKS §7: a missing llms.txt must not cost a known-good site anything",
    ),
    (
        "known-good-multi-page",
        S.good_multi_page_site,
        True,
        "row 20: several clean pages sampled together",
    ),
    ("known-good-docs-index", S.good_docs_index_site, True, "row 21: a clean docs site"),
    (
        "known-good-sitemap-index",
        S.good_with_sitemap_index_site,
        True,
        "row 10: a clean site using a sitemap index",
    ),
    (
        "known-good-long-content",
        S.good_long_content_site,
        True,
        "REN-001/REN-002 measured well clear of their thresholds",
    ),
    (
        "known-good-hybrid",
        S.good_hybrid_site,
        True,
        "a partly client-rendered page with enough static content to stay clean",
    ),
    (
        "known-good-article",
        S.good_article_site,
        True,
        "a clean article at the root, exercising the article role",
    ),
)
