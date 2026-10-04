# Contributing to geoctl

geoctl is open source under [AGPL-3.0-only](LICENSE). Contributions are welcome, including
ones you have never made before. This page covers how to get set up, how to add a check or
a fixture, and what "good" looks like here.

The project is small and pre-release. If something is unclear or wrong in this document,
that is a bug — please open an issue, and a fix to this file is a genuinely useful first
contribution.

## Why this project is worth contributing to

Two things make it unusual:

- **The check catalog is deliberately narrow.** Only 6 of 20 checks are scored, because
  most "AI readiness" signals are not specific to AI crawlers. Adding a *scored* check is a
  deliberate decision with a bar; adding an *informational* check is easy and needs no
  argument. See [ADR-010](docs/DECISIONS.md#adr-010-the-check-catalog-is-narrow-and-mostly-unscored).
- **Every number is inspectable.** No black-box scoring, no hidden rubric. If a check fires,
  the evidence behind it is in the report.

## Ways to contribute, roughly by effort

| Contribution | Effort | Where |
|---|---|---|
| Report a bug or false positive | minutes | [Open an issue](https://github.com/Amank-root/GeoProbe/issues) |
| Add a site to the fixture set | ~30 min | [docs/FIXTURES.md](docs/FIXTURES.md) |
| Improve a docs page | ~30 min | `docs/` |
| Report a check that fires wrongly | ~1 hr | issue + a fixture that reproduces it |
| Add an **informational** check | ~half a day | [CONTRIBUTING.md](CONTRIBUTING.md#adding-an-informational-check) |
| Improve extraction heuristics | hours | `src/geoctl/extract/` |
| Add a **scored** check | needs discussion first | [open an issue](https://github.com/Amank-root/GeoProbe/issues) first |

If you are unsure where something belongs, open an issue and ask. That is a normal and
welcome way to start.

## Legal: the one thing to know before your first PR

This is AGPL-3.0. Under the AGPL's own inbound-contribution defaults, your contribution is
licensed under AGPL-3.0 along with everything else — which is usually all you need to know.

We do **not** operate a CLA bot or a DCO sign-off requirement. The practical effect:

- You keep your copyright.
- Your work ships under AGPL-3.0, the same licence as the project.
- You are not asked to sign a separate agreement or assign rights.

If your employer requires a different position on inbound contributions, please raise it in
an issue *before* writing code, so nobody wastes their time.

## Getting set up

Requires Python 3.10+ (3.12 recommended — that is what CI uses).

```bash
git clone https://github.com/Amank-root/GeoProbe
cd GeoProbe

# with uv (fastest)
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"

# or with pip
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# optional: JS rendering support, needed for --render paths
uv pip install -e ".[dev,render]" && playwright install chromium
```

Check it works:

```bash
pytest                  # test suite
ruff check .            # lint
pyright                 # type check
pre-commit install      # runs lint+types on every commit
```

**Tests must run with no network access and no LLM API key.** This is a hard project
constraint, not a preference — CI has no secrets and no network, and the exit criteria in
[ROADMAP](docs/ROADMAP.md) require it. LLM behaviour is tested with recorded cassettes, not live
calls. If your change makes a test hit the network, that is a bug in the change.

## Adding an informational check

Informational checks are the easy entry point: they are reported with evidence and a fix
hint but contribute **0 points** to the score, so there is no weight argument to win.

1. **Pick an unused ID.** Prefixes are `ACC-`, `REN-`, `STR-`, `SD-`, `DIS-`, `TRU-`,
   `SITE-`. Never reuse an ID for a different meaning — downstream baselines and user configs
   may already reference it.
2. **Document the criteria in [docs/CHECKS.md](docs/CHECKS.md) §3.1–§3.5 before writing
   code.** Every existing check has pass/warn/fail criteria and a list of what evidence is
   reported. Write yours in the same shape; an undocumented check cannot be calibrated or
   reviewed.
3. **Implement** in the matching module under `src/geoctl/checks/` (`access.py`,
   `render.py`, `structure.py`, `schema.py`, `discovery.py`, `trust.py`, `site.py`).
4. **Register it** in the explicit list in `src/geoctl/checks/__init__.py`. Registration is a
   deliberate list rather than import magic, so the catalog stays auditable.
5. **Add fixtures** covering pass, warn, and fail, plus at least one edge case. See
   [docs/FIXTURES.md](docs/FIXTURES.md) for what the suite needs.
6. **Set `weight = 0`.** Also add the `License ::` classifier-free metadata note only if the
   check genuinely earns scored status — which is the harder path below.

A check is a pure function of an `AuditContext`; it must never perform its own network
requests. That is what keeps checks testable against fixtures and fast in CI.

## Adding a scored check — ask first

A scored check needs the evidence and calibration, not just a preference. It must be
**specific to AI crawler access** and **discriminate between sites real crawlers can and
cannot use**. Open an issue before writing it. See
[CHECKS §8](docs/CHECKS.md#8-adding-or-changing-checks) for the criteria and
[ADR-010](docs/DECISIONS.md#adr-010-the-check-catalog-is-narrow-and-mostly-unscored) for the
reason the bar is deliberate.

## Code conventions

- **Typed.** Every public function and model has annotations; `pyright` is clean in CI.
- **Comments explain *why*, not *what*.** The code says what it does. If a line needs a
  comment to explain itself, the code should be clearer instead.
- **Line length 100.** `ruff` handles the rest.
- **No new runtime dependencies** without discussion in an issue. The CLI must stay
  `uvx`-installable and light; [ADR-006](docs/DECISIONS.md) is why Playwright is an extra.
- **Never log or report API keys, full page text, or URLs of private targets.** Telemetry
  and reports have separate allow-lists, and tests assert them
  ([TELEMETRY §9](docs/TELEMETRY.md#9-engineering-requirements)).
- **Preserve the honesty properties.** The tool reports readiness, never predicted citations
  or rankings. Please do not add language implying it forecasts AI recommendations — that
  promise is the project's core commitment.

## Making a pull request

- One logical change per PR. Doc changes separate from behaviour changes.
- Write or update tests. A PR that changes a threshold must say why in the description,
  because weights and thresholds change reported scores across versions.
- Say which docs you updated. Several docs cross-reference each other, and a check change
  usually touches [CHECKS.md](docs/CHECKS.md) plus its own entry.
- Reference the issue it closes (`Refs #12`, or `Closes #12` when it should close on merge).
- CI must pass. If it fails and you cannot see why, ask — that is a docs or CI bug worth
  fixing separately.

## Reporting a false positive

The most useful bug reports in this project are "check X fired on site Y and was wrong."
Please include the URL (or a fixture), the output, and what the site actually does. A
false positive on a known-good site counts directly against the
**< 5% false-positive rate** release criterion in [ROADMAP](docs/ROADMAP.md), so these
reports directly improve the release quality bar.

## Code of conduct

Be decent to each other. Assume good faith, critique code rather than people, and accept that
maintainers may say no to a scope change without it being a judgement of you. Report
unacceptable behaviour to the maintainer via the email in `pyproject.toml`.

## Licence

By contributing you agree that your contribution is licensed under AGPL-3.0-only, the same
terms as the project. See [LICENSE](LICENSE) and
[ADR-004](docs/DECISIONS.md#adr-004-license-is-agpl-30-only).