"""Deterministic local fixture sites for the test suite.

FIXTURES.md requires that fixtures be self-hosted, offline, tiny, and — for the
blocking and challenge cases — able to vary their response per user-agent, which
a static file cannot do. This module is that server, implemented as a small WSGI
app so it runs in-process with no port binding and therefore no flakiness.

Nothing here touches the network: routes are registered per test.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

# A page with everything a well-built page should have: content, one H1, a clean
# heading hierarchy, JSON-LD, Open Graph, canonical, lang, and dates.
GOOD_PAGE = """<!doctype html>
<html lang="en">
<head>
<title>Acme Widgets: industrial widget supply since 2019</title>
<meta name="description" content="Acme Widgets supplies industrial widgets to manufacturers across Europe, with next-day delivery on stocked items.">
<link rel="canonical" href="https://fixtures.local/">
<meta name="robots" content="index, follow">
<meta property="og:title" content="Acme Widgets">
<meta property="og:description" content="Industrial widget supply since 2019.">
<meta property="og:url" content="https://fixtures.local/">
<meta property="og:image" content="https://fixtures.local/og.png">
<meta property="article:published_time" content="2024-03-04T09:00:00Z">
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Organization","name":"Acme Widgets",
 "url":"https://fixtures.local/","author":{"@type":"Organization","name":"Acme Widgets"}}
</script>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"WebSite","name":"Acme Widgets"}
</script>
</head>
<body>
<header><nav><a href="/">Home</a> <a href="/pricing">Pricing</a> <a href="/docs">Docs</a></nav></header>
<main>
<h1>Industrial widgets, delivered next day</h1>
<p>Acme Widgets has supplied industrial widgets to manufacturers since 2019. We hold
four thousand stocked lines in our Rotterdam warehouse, and everything in stock ships
the next working day.</p>
<h2>Product range</h2>
<p>Our range covers stainless fixings, aluminium extrusions, and precision bearings. The
Starter plan costs $19 per month and includes two warehouse seats and next-day dispatch
on stocked items.</p>
<h2>Support</h2>
<p>Documentation lives at /docs. Support is available on weekdays from 09:00 to 17:00 CET
by email, and the team answers within one working day.</p>
<h3>Contact</h3>
<p>Email support@fixtures.local or call +31 10 000 0000. The company was founded in 2019
by Ada van Dijk and is registered in Rotterdam.</p>
<h2>Delivery and returns</h2>
<p>Orders placed before 15:00 CET on a working day ship the same day from Rotterdam.
Stocked lines are held in a 4,000 line inventory, and anything not stocked is
manufactured to order with a typical lead time of ten working days. European
customers pay a flat 25 euro delivery charge, and UK orders ship from the Dublin
partner warehouse on the same next-day terms.</p>
<p>Returns are accepted within 30 days of delivery in original packaging. Custom
manufactured items are non-returnable unless faulty, in which case replacement
is arranged at our cost. Damaged-in-transit claims must be raised within five
working days so the carrier claim can be opened.</p>
<h2>Certifications and compliance</h2>
<p>Acme Widgets holds ISO 9001:2015 certification for its manufacturing process and
ISO 14001:2015 for the Rotterdam site. Stainless fixings are certified to EN
1.4401 (AISI 304) and aluminium extrusions to EN 573-3 (EN AW-6060 T6). Every
batch ships with a material certificate traceable to the mill certificate.</p>
<p>The company complies with REACH and RoHS, publishes a conflict minerals
statement annually, and reports scope 1 and 2 emissions per tonne of finished
product. The most recent audited figures cover the 2023 financial year.</p>
<h2>Installation and technical guidance</h2>
<p>Technical drawings for every stocked line are available under /docs as SVG and
PDF, with tolerance tables for both metric and imperial fixings. Engineers can
request a sample pack of ten assorted fixings at no charge, shipped against a
customer account number. Application notes cover torque specifications, corrosion
resistance by atmosphere, and recommended clearance for aluminium into stainless
fasteners to avoid galvanic corrosion.</p>
<h2>Frequently asked</h2>
<p>The Enterprise plan costs $499 per seat per month and includes dedicated support
in your own timezone, a named contact, and quarterly reviews. The Starter plan
costs $19 per month and includes two warehouse seats. Neither plan has a setup
fee, and both can be cancelled monthly without notice.</p>
</main>
<footer><p>&copy; 2024 Acme Widgets. All rights reserved.</p></footer>
</body></html>
"""

# The most common real defect: an app shell that JS fills in. The content exists
# only inside a script payload, so a crawler that does not run JS sees nothing.
SPA_SHELL = """<!doctype html>
<html lang="en">
<head><title>Acme Widgets: industrial widget supply since 2019</title>
<meta name="description" content="Acme Widgets supplies industrial widgets to manufacturers across Europe.">
<link rel="canonical" href="https://fixtures.local/"></head>
<body>
<div id="root"></div>
<script id="__NEXT_DATA__" type="application/json">
{"props":{"pageProps":{"title":"Industrial widgets, delivered next day","body":"Acme Widgets has supplied industrial widgets to manufacturers since 2019. We hold four thousand stocked lines in our Rotterdam warehouse, and everything in stock ships the next working day. The Starter plan costs $19 per month and includes two warehouse seats and next-day dispatch on stocked items. Documentation lives at /docs. Support is available on weekdays from 09:00 to 17:00 CET by email, and the team answers within one working day."}}}
</script>
<script src="/_next/static/chunks/main.js"></script>
</body></html>
"""

# Hybrid: some content in the HTML, the rest client-side. Should land in REN-001's
# warn band rather than either extreme.
HYBRID_PAGE = """<!doctype html>
<html lang="en">
<head><title>Acme Widgets: pricing</title>
<meta name="description" content="Pricing for Acme Widgets warehouse plans, from Starter to Enterprise.">
<link rel="canonical" href="https://fixtures.local/pricing"></head>
<body>
<main>
<h1>Pricing</h1>
<h2>Plans</h2>
<p>Acme Widgets offers three warehouse plans. Every plan includes next-day dispatch on
stocked items from our Rotterdam warehouse, and every plan can be cancelled monthly.</p>
<p>The plan table itself is rendered on the client from the billing API.</p>
<div id="pricing-table"></div>
<script src="/assets/bundle.js"></script>
</main>
</body></html>
"""

# No structured data at all.
NO_SCHEMA_PAGE = """<!doctype html>
<html>
<head><title>Pricing | Acme Widgets</title></head>
<body><main><h1>Pricing</h1><p>Plans start at $19 per month.</p></main></body></html>
"""

# Malformed JSON-LD: the block exists but does not parse. SD-001 must warn, not fail.
BROKEN_JSONLD_PAGE = """<!doctype html>
<html lang="en">
<head><title>Acme Widgets: pricing</title>
<meta name="description" content="Pricing for Acme Widgets warehouse plans, from Starter to Enterprise, all including dispatch.">
<link rel="canonical" href="https://fixtures.local/pricing">
<script type="application/ld+json">{"@type": "Organization", "name": "Acme",}</script>
</head>
<body><main><h1>Pricing</h1><p>Plans start at $19 per month and include next-day dispatch.</p>
</main></body></html>
"""

# Skipped heading level and two H1s, for STR-004 / STR-005.
BAD_HEADINGS_PAGE = """<!doctype html>
<html lang="en_US">
<head><title>Acme Widgets: pricing</title></head>
<body><main>
<h1>Pricing</h1><h1>Plans</h1>
<p>Plans start at $19 per month.</p>
<h2>Plans</h2><h4>Enterprise</h4>
<p>Enterprise is priced per seat with a 12-month minimum term and dedicated support in
your own timezone, including a named contact and quarterly review.</p>
</main></body></html>
"""

# A challenge page returned with 200. Status alone reads as success, which is the
# point of ACC-003.
CHALLENGE_PAGE = """<!doctype html>
<html><head><title>Just a moment...</title></head>
<body><div class="main-wrapper"><h1>Checking your browser before accessing</h1>
<p>Please enable JavaScript and cookies to continue.</p>
<div id="cf-browser-verification"></div></div></body></html>
"""

ROBOTS_ALLOW_ALL = """User-agent: *
Allow: /

Sitemap: https://fixtures.local/sitemap.xml
"""

# Blocks training bots but allows search and user-triggered ones — a legitimate
# policy that ACC-001 must report as policy rather than as failure.
ROBOTS_POLICY = """User-agent: *
Allow: /

User-agent: GPTBot
Disallow: /

User-agent: ClaudeBot
Disallow: /

User-agent: CCBot
Disallow: /

User-agent: Google-Extended
Disallow: /

User-agent: OAI-SearchBot
Allow: /

User-agent: PerplexityBot
Allow: /

Sitemap: https://fixtures.local/sitemap.xml
"""

# The wildcard / $ / Allow-precedence cases ADR-013 exists to get right.
ROBOTS_WILDCARD = """User-agent: *
Disallow: /*.json$
Allow: /public/
Disallow: /private/

User-agent: ClaudeBot
Disallow: /

User-agent: GPTBot
Allow: /

Sitemap: https://fixtures.local/sitemap.xml
"""

# A wildcard Disallow: / that unintentionally catches the AI bots too.
ROBOTS_BLOCK_ALL = """User-agent: *
Disallow: /

User-agent: GPTBot
Disallow: /
"""

SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://fixtures.local/</loc><lastmod>2024-03-04</lastmod></url>
<url><loc>https://fixtures.local/pricing</loc><lastmod>2024-03-04</lastmod></url>
<url><loc>https://fixtures.local/docs</loc><lastmod>2024-03-04</lastmod></url>
</urlset>
"""

SITEMAP_INDEX = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<sitemap><loc>https://fixtures.local/sitemap-pages.xml</loc></sitemap>
</sitemapindex>
"""

# A stale lastmod in the future: a real and common defect.
SITEMAP_STALE = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://fixtures.local/</loc><lastmod>2099-01-01</lastmod></url>
</urlset>
"""

LLMS_TXT = """# Acme Widgets

We supply industrial widgets to manufacturers across Europe, with next-day delivery on
stocked items from our Rotterdam warehouse.

## Docs

- [Pricing](/pricing)
- [Documentation](/docs)
"""

BOT_AGENT_MARKERS = (
    "GPTBot",
    "ClaudeBot",
    "PerplexityBot",
    "CCBot",
    "Google-Extended",
    "OAI-SearchBot",
    "ChatGPT-User",
    "anthropic-ai",
    "Bingbot",
    "Googlebot",
)


# Fixture documents name this placeholder origin; the server rewrites it to the
# origin it is actually serving, because a real sitemap lists the site's own URLs.
PLACEHOLDER_ORIGIN = "https://fixtures.local"


@dataclass
class Route:
    body: bytes
    content_type: str = "text/html; charset=utf-8"
    status: int = 200
    headers: dict[str, str] = field(default_factory=dict)
    # Per-user-agent overrides: body, status, or headers may vary by bot.
    by_agent: dict[str, tuple[bytes | None, int | None, dict[str, str] | None]] = field(
        default_factory=dict
    )


class FixtureSite:
    """A routing table with per-user-agent behaviour. No sockets involved."""

    def __init__(self) -> None:
        self.routes: dict[str, Route] = {}

    def add(self, path: str, route: Route) -> None:
        self.routes[path] = route

    def add_html(self, path: str, html: str, **kwargs: object) -> None:
        self.add(path, Route(body=html.encode("utf-8"), **kwargs))  # type: ignore[arg-type]

    def get(
        self, path: str, user_agent: str = "", origin: str = PLACEHOLDER_ORIGIN
    ) -> tuple[int, dict[str, str], bytes]:
        route = self.routes.get(path)
        if route is None:
            return 404, {"content-type": "text/plain"}, b"not found"

        status, headers, body = route.status, dict(route.headers), route.body
        for marker, (agent_body, agent_status, agent_headers) in route.by_agent.items():
            if marker in user_agent:
                if agent_body is not None:
                    body = agent_body
                if agent_status is not None:
                    status = agent_status
                if agent_headers:
                    headers.update(agent_headers)
                break

        content_type = route.content_type
        if not headers.get("content-type"):
            headers["content-type"] = content_type
        if origin != PLACEHOLDER_ORIGIN:
            body = body.replace(PLACEHOLDER_ORIGIN.encode(), origin.encode())
        return status, headers, body


Handler = Callable[[str, str], tuple[int, dict[str, str], bytes]]


def good_site(site: FixtureSite | None = None) -> FixtureSite:
    """A known-good site: every check should pass or warn.

    This is what the < 5% false-positive release target is measured against
    (FIXTURES.md), so it must not be a strawman.
    """
    site = site or FixtureSite()
    site.add_html("/", GOOD_PAGE)
    site.add_html("/pricing", GOOD_PAGE)
    site.add_html("/docs", GOOD_PAGE)
    site.add("/robots.txt", Route(body=ROBOTS_ALLOW_ALL.encode(), content_type="text/plain"))
    site.add("/sitemap.xml", Route(body=SITEMAP.encode(), content_type="application/xml"))
    site.add("/llms.txt", Route(body=LLMS_TXT.encode(), content_type="text/plain"))
    return site


def waf_site(site: FixtureSite | None = None) -> FixtureSite:
    """Row 6: bots get 403, browsers get 200. Invisible to a robots.txt parse."""
    site = site or FixtureSite()
    site.add(
        "/",
        Route(
            body=GOOD_PAGE.encode(),
            by_agent=dict.fromkeys(BOT_AGENT_MARKERS, (b"", 403, None)),
        ),
    )
    site.add("/robots.txt", Route(body=ROBOTS_ALLOW_ALL.encode(), content_type="text/plain"))
    site.add("/sitemap.xml", Route(body=SITEMAP.encode(), content_type="application/xml"))
    return site


# The exact Chrome-125 string geoctl used to send as its browser baseline. Sites
# running UA-reputation middleware refuse this while serving every other browser
# and bot (issue #40).
FINGERPRINTED_CHROME_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


def ua_fingerprint_site(site: FixtureSite | None = None) -> FixtureSite:
    """Row 6 variant: refuses one exact browser UA, serves every bot normally.

    This is the failure mode of issue #40. If the baseline geoctl compares
    against is itself blocked, ACC-002 reports that AI bots are blocked when
    they are not — so this fixture must NOT produce an ACC-002 failure.
    """
    site = site or good_site()
    site.add(
        "/",
        Route(
            body=GOOD_PAGE.encode(),
            by_agent={FINGERPRINTED_CHROME_UA: (b"", 403, None)},
        ),
    )
    site.add("/robots.txt", Route(body=ROBOTS_ALLOW_ALL.encode(), content_type="text/plain"))
    site.add("/sitemap.xml", Route(body=SITEMAP.encode(), content_type="application/xml"))
    return site


def challenge_site(site: FixtureSite | None = None) -> FixtureSite:
    """Row 7: a bot-challenge page returned with HTTP 200."""
    site = site or FixtureSite()
    site.add(
        "/",
        Route(
            body=GOOD_PAGE.encode(),
            by_agent={marker: (CHALLENGE_PAGE.encode(), 200, None) for marker in BOT_AGENT_MARKERS},
        ),
    )
    site.add("/robots.txt", Route(body=ROBOTS_ALLOW_ALL.encode(), content_type="text/plain"))
    return site


def handler_for(site: FixtureSite) -> Handler:
    """Adapt a FixtureSite to the callable the fetch client expects."""
    return lambda path, user_agent: site.get(path, user_agent)


# --------------------------------------------------------------------------------
# Builders for the fixture catalog (tests/fixtures/catalog.py).
#
# Each one reproduces exactly one defect or one clean case from FIXTURES.md, so a
# check that fires wrongly can be attributed to a specific fixture. They stay tiny
# and deterministic: no external assets, no network, no timestamps that change.
# --------------------------------------------------------------------------------


def good_site_variant() -> FixtureSite:
    """A second known-good site, structurally different from good_site().

    One passing fixture cannot establish a false-positive rate, so the set needs
    more than one site where every check should pass.
    """
    site = FixtureSite()
    page = GOOD_PAGE.replace(
        "Acme Widgets: industrial widget supply since 2019",
        "Northwind Components: fastener supply for marine builders since 2011",
    ).replace("Acme Widgets", "Northwind Components")
    page = page.replace('<html lang="en">', '<html lang="en-GB">')
    site.add_html("/", page)
    site.add_html("/pricing", page)
    site.add("/robots.txt", Route(body=ROBOTS_ALLOW_ALL.encode(), content_type="text/plain"))
    site.add("/sitemap.xml", Route(body=SITEMAP.encode(), content_type="application/xml"))
    return site


def spa_site() -> FixtureSite:
    site = good_site()
    site.add_html("/", SPA_SHELL)
    return site


def spa_site_variant() -> FixtureSite:
    """A second SPA whose content sits in a different payload shape."""
    site = good_site()
    site.add_html(
        "/",
        """<!doctype html><html lang="en"><head>
<title>Acme Widgets: industrial widget supply since 2019</title>
<meta name="description" content="Acme Widgets supplies industrial widgets to manufacturers across Europe.">
<link rel="canonical" href="https://fixtures.local/"></head>
<body><div id="app"></div>
<script type="application/json" id="__NUXT_DATA__">
{"data":[{"title":"Industrial widgets","body":"Acme Widgets has supplied industrial widgets since 2019. The Starter plan costs $19 per month and ships next day from Rotterdam."}]}
</script>
<script src="/_nuxt/entry.js"></script></body></html>""",
    )
    return site


def hybrid_site() -> FixtureSite:
    site = good_site()
    site.add_html("/pricing", HYBRID_PAGE)
    return site


def ssr_site() -> FixtureSite:
    """Server-rendered: the content is in the HTML, so REN-001 must pass."""
    site = good_site()
    return site


def robots_policy_site() -> FixtureSite:
    site = good_site()
    site.add("/robots.txt", Route(body=ROBOTS_POLICY.encode(), content_type="text/plain"))
    return site


def robots_block_all_site() -> FixtureSite:
    site = good_site()
    site.add("/robots.txt", Route(body=ROBOTS_BLOCK_ALL.encode(), content_type="text/plain"))
    return site


def robots_wildcard_site() -> FixtureSite:
    site = good_site()
    site.add("/robots.txt", Route(body=ROBOTS_WILDCARD.encode(), content_type="text/plain"))
    return site


def robots_missing_site() -> FixtureSite:
    """No robots.txt at all: default-allow, so ACC-001 must pass (row 9)."""
    site = good_site()
    del site.routes["/robots.txt"]
    return site


def sitemap_index_site() -> FixtureSite:
    site = good_site()
    site.add("/sitemap.xml", Route(body=SITEMAP_INDEX.encode(), content_type="application/xml"))
    site.add("/sitemap-pages.xml", Route(body=SITEMAP.encode(), content_type="application/xml"))
    return site


def sitemap_stale_site() -> FixtureSite:
    site = good_site()
    site.add("/sitemap.xml", Route(body=SITEMAP_STALE.encode(), content_type="application/xml"))
    return site


def sitemap_missing_site() -> FixtureSite:
    site = good_site()
    del site.routes["/sitemap.xml"]
    site.add("/robots.txt", Route(body=b"User-agent: *\nAllow: /\n", content_type="text/plain"))
    return site


def multi_page_site() -> FixtureSite:
    """More URLs than --max-pages, so the sampler has to choose (row 20)."""
    site = good_site()
    urls = "\n".join(
        f"<url><loc>https://fixtures.local/page{i}</loc><lastmod>2024-03-04</lastmod></url>"
        for i in range(15)
    )
    site.add(
        "/sitemap.xml",
        Route(
            body=(
                f'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                f"{urls}</urlset>"
            ).encode(),
            content_type="application/xml",
        ),
    )
    for i in range(15):
        site.add_html(f"/page{i}", GOOD_PAGE)
    return site


def noindex_site() -> FixtureSite:
    site = good_site()
    site.add_html(
        "/",
        GOOD_PAGE.replace(
            '<meta name="robots" content="index, follow">',
            '<meta name="robots" content="noindex, follow">',
        ),
    )
    return site


def jsonld_clean_site() -> FixtureSite:
    site = good_site()
    site.add_html("/blog/post", ARTICLE_PAGE)
    return site


def jsonld_broken_site() -> FixtureSite:
    site = good_site()
    site.add_html("/", BROKEN_JSONLD_PAGE)
    return site


def no_schema_site() -> FixtureSite:
    site = good_site()
    site.add_html("/", NO_SCHEMA_PAGE)
    return site


def headings_good_site() -> FixtureSite:
    site = good_site()
    site.add_html("/", GOOD_PAGE)
    return site


def headings_bad_site() -> FixtureSite:
    site = good_site()
    site.add_html("/", BAD_HEADINGS_PAGE)
    return site


def boilerplate_site() -> FixtureSite:
    """Navigation, cookie chrome, and footer dominate the HTML (row 19)."""
    nav = "<nav>" + "".join(f'<a href="/x{i}">Link {i}</a> ' for i in range(120)) + "</nav>"
    body = GOOD_PAGE.split("<body>")[1].split("</body>")[0]
    page = (
        '<!doctype html><html lang="en"><head>'
        "<title>Acme Widgets: industrial widget supply since 2019</title>"
        '<meta name="description" content="Acme Widgets supplies industrial widgets to manufacturers across Europe, with next-day delivery.">'
        '<link rel="canonical" href="https://fixtures.local/">'
        '<meta name="robots" content="index, follow">'
        '<script type="application/ld+json">{"@type":"Organization","name":"Acme Widgets"}</script>'
        "</head><body>"
        f'<div class="cookie-banner">We use cookies. {"Accept " * 300}</div>'
        f"{nav}<main>{body}</main>{nav}"
        "<footer>" + ("Legal boilerplate. " * 200) + "</footer>"
        "</body></html>"
    )
    site = good_site()
    site.add_html("/", page)
    return site


def iframe_site() -> FixtureSite:
    """Main content only inside an iframe, which extractors skip (row 25)."""
    site = good_site()
    site.add_html(
        "/",
        """<!doctype html><html lang="en"><head>
<title>Acme Widgets: industrial widget supply since 2019</title>
<meta name="description" content="Acme Widgets supplies industrial widgets to manufacturers across Europe.">
<link rel="canonical" href="https://fixtures.local/"></head>
<body><main><h1>Widget catalogue</h1>
<p>Our catalogue is embedded below. If this paragraph is all you can read, the
catalogue was not extracted.</p>
<iframe src="/catalogue" title="catalogue" width="800" height="600"></iframe>
</main></body></html>""",
    )
    return site


def docs_site() -> FixtureSite:
    site = good_site()
    site.add_html("/docs", GOOD_PAGE)
    site.add_html("/docs/getting-started", GOOD_PAGE)
    return site


def product_site() -> FixtureSite:
    """A product page, so SD-002 expects Product/Offer for the product role."""
    site = good_site()
    site.add_html(
        "/products/widget",
        """<!doctype html><html lang="en"><head>
<title>Stainless Widget | Acme Widgets</title>
<meta name="description" content="A 316 stainless widget rated to 900 bar, supplied from stock with next-day dispatch.">
<link rel="canonical" href="https://fixtures.local/products/widget">
<meta property="og:title" content="Stainless Widget">
<meta property="og:description" content="A 316 stainless widget rated to 900 bar.">
<meta property="og:url" content="https://fixtures.local/products/widget">
<meta property="og:image" content="https://fixtures.local/widget.png">
<script type="application/ld+json">{"@context":"https://schema.org","@type":"Product",
"name":"Stainless Widget","sku":"SW-316","offers":{"@type":"Offer","price":"42.00","priceCurrency":"EUR"}}</script>
</head><body><main><h1>Stainless Widget</h1>
<p>The Stainless Widget is machined from 316 stainless steel and rated to 900 bar. It
weighs 340 grams and ships from Rotterdam the next working day. The Enterprise plan
costs $499 per seat per month for teams that need dedicated support.</p>
</main></body></html>""",
    )
    return site


def blog_site() -> FixtureSite:
    site = good_site()
    site.add_html("/blog/launch", ARTICLE_PAGE)
    return site


def no_hsts_site() -> FixtureSite:
    """HTTPS absent in the fixture server, so SITE-001 fails; the HSTS header is
    omitted for the same reason (row 24)."""
    site = good_site()
    site.add(
        "/",
        Route(body=GOOD_PAGE.encode(), headers={"strict-transport-security": ""}),
    )
    return site


def tiny_page_site() -> FixtureSite:
    """Under three chunks, so the eval must fall back to whole_page (row 26)."""
    site = good_site()
    site.add_html(
        "/",
        """<!doctype html><html lang="en"><head>
<title>Widget pricing | Acme Widgets</title>
<meta name="description" content="Pricing for the Acme Widgets Starter plan, at nineteen dollars per month including dispatch.">
<link rel="canonical" href="https://fixtures.local/"></head>
<body><main><h1>Pricing</h1><p>The Starter plan costs $19 per month.</p>
</main></body></html>""",
    )
    return site


def buried_facts_site() -> FixtureSite:
    """Content-rich, but the pricing fact sits at the very bottom (row 27)."""
    filler = " ".join(
        f"Paragraph {i} about general widget logistics and warehouse operations." for i in range(60)
    )
    page = f"""<!doctype html><html lang="en"><head>
<title>Acme Widgets: industrial widget supply since 2019</title>
<meta name="description" content="Acme Widgets supplies industrial widgets to manufacturers across Europe, with next-day delivery on stocked items.">
<link rel="canonical" href="https://fixtures.local/"></head>
<body><main><h1>Widgets and logistics</h1>
{filler}
<h2>Shipping</h2><p>{filler}</p>
<h2>Returns</h2><p>{filler}</p>
<h2>Billing</h2><p>The Starter plan costs $19 per month and the Enterprise plan costs
$499 per seat per month. Both include next-day dispatch on stocked items from our
Rotterdam warehouse, and neither carries a setup fee.</p>
</main></body></html>"""
    site = good_site()
    site.add_html("/", page)
    return site


def client_facts_site() -> FixtureSite:
    """The pricing fact exists only after JS runs (row 28)."""
    site = good_site()
    site.add_html(
        "/",
        """<!doctype html><html lang="en"><head>
<title>Acme Widgets: pricing | Acme Widgets</title>
<meta name="description" content="Acme Widgets warehouse plans, from Starter at nineteen dollars per month to Enterprise.">
<link rel="canonical" href="https://fixtures.local/"></head>
<body><main><h1>Pricing</h1>
<p>Plans are listed in the table below.</p>
<div id="pricing-root"></div>
<script>window.__PRICING__={"starter":19,"enterprise":499};</script>
</main></body></html>""",
    )
    return site


# A blog post with a visible byline, machine-readable dates, and Article JSON-LD.
ARTICLE_PAGE = """<!doctype html>
<html lang="en">
<head>
<title>How we cut our picker error rate by 40% | Acme Widgets</title>
<meta name="description" content="A walkthrough of the bin-picking changes that reduced our picker error rate by 40% over one quarter of operational data.">
<link rel="canonical" href="https://fixtures.local/blog/picker-error-rate">
<meta name="robots" content="index, follow">
<meta property="og:title" content="How we cut our picker error rate by 40%">
<meta property="og:description" content="The changes that reduced picker errors by 40%.">
<meta property="og:url" content="https://fixtures.local/blog/picker-error-rate">
<meta property="og:image" content="https://fixtures.local/blog/picker.png">
<meta property="article:published_time" content="2024-03-04T09:00:00Z">
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"BlogPosting",
"headline":"How we cut our picker error rate by 40%",
"datePublished":"2024-03-04","dateModified":"2024-06-11",
"author":{"@type":"Person","name":"Ada van Dijk"},
"publisher":{"@type":"Organization","name":"Acme Widgets"}}
</script>
</head>
<body>
<main>
<h1>How we cut our picker error rate by 40%</h1>
<p class="byline">By Ada van Dijk &middot; <time datetime="2024-03-04">4 March 2024</time></p>
<p>Our picker error rate sat at 3.8% for six months. We changed three things: we moved
to a fixed pick-face layout, we added a scan-confirm step at the bin edge, and we
stopped letting the picker app reorder the list mid-pick. Error rate fell to 2.3% over
one quarter of operational data, a 40% relative reduction.</p>
<h2>What we changed</h2>
<p>The fixed pick-face layout removed 1.1 points of error on its own. The scan-confirm
step at the bin edge removed a further 0.3 points. Disabling mid-pick reordering, which
operators had asked for, accounted for the remaining 0.2.</p>
<h2>What we would do differently</h2>
<p>We would have run the scan-confirm test first. It was the smallest change and the
second-largest effect, and we spent two weeks on layout before trying it.</p>
</main>
</body></html>
"""


# --------------------------------------------------------------------------------
# Additional known-good fixtures.
#
# FIXTURES.md requires at least 40% of the set to be sites where every check
# should pass or warn, because that is what a false-positive rate is measured
# against. Most fixtures above deliberately reproduce a defect, so these supply
# the clean half of the set.
# --------------------------------------------------------------------------------


def good_no_llms_txt_site() -> FixtureSite:
    """Known-good, and without llms.txt.

    DIS-003 fails by design when the file is absent, and CHECKS §7 is explicit
    that this is not a penalty. Including it in the known-good set is how the
    suite proves the tool does not punish a site for omitting the file.
    """
    site = good_site()
    del site.routes["/llms.txt"]
    return site


def good_multi_page_site() -> FixtureSite:
    """Several well-formed pages, so sampling across them stays clean."""
    site = good_site()
    site.add_html("/about", GOOD_PAGE)
    site.add_html("/docs/api", GOOD_PAGE)
    site.add_html("/blog/launch", ARTICLE_PAGE)
    return site


def good_docs_index_site() -> FixtureSite:
    site = good_site()
    site.add_html("/docs/index", GOOD_PAGE)
    site.add_html("/docs/reference", GOOD_PAGE)
    return site


def good_with_sitemap_index_site() -> FixtureSite:
    """A clean site that uses a sitemap index, the tidier real-world shape."""
    site = good_site()
    site.add("/sitemap.xml", Route(body=SITEMAP_INDEX.encode(), content_type="application/xml"))
    site.add("/sitemap-pages.xml", Route(body=SITEMAP.encode(), content_type="application/xml"))
    return site


def good_long_content_site() -> FixtureSite:
    """Long-form content, so REN-001 and REN-002 are measured well above their
    thresholds rather than near the boundary."""
    site = good_site()
    body = " ".join(
        f"Section {i} covers the operational detail for warehouse teams running "
        f"multi-line orders in the Benelux region, including the routing rules, the "
        f"carrier handoff times, and the returns path for damaged consignments."
        for i in range(12)
    )
    page = GOOD_PAGE.replace(
        "<h2>Frequently asked</h2>",
        f"<h2>Operational reference</h2><p>{body}</p><h2>Frequently asked</h2>",
    )
    site.add_html("/", page)
    return site


def good_hybrid_site() -> FixtureSite:
    """A hybrid page that still ships enough server-rendered content.

    Included as known-good on purpose: REN-001 must not fire merely because a
    page renders *some* of its content client-side, which is the false positive
    this check is most likely to produce.
    """
    page = HYBRID_PAGE.replace(
        "<p>The plan table itself is rendered on the client from the billing API.</p>",
        "<p>The plan table itself is rendered on the client from the billing API. "
        "Starter costs $19 per month, Enterprise costs $499 per seat per month, and "
        "every plan includes next-day dispatch on stocked items from Rotterdam, with "
        "no setup fee and no minimum term on Starter or Enterprise beyond their own "
        "stated billing periods, which are monthly and can be cancelled at any time "
        "before the next renewal date without penalty or further obligation.</p>",
    )
    site = good_site()
    site.add_html("/", page)
    return site


def good_article_site() -> FixtureSite:
    """A clean blog post at the root, so article-role expectations hold."""
    site = good_site()
    site.add_html("/", ARTICLE_PAGE)
    return site
