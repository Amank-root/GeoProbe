# Roadmap

Part of the [geoctl PRD](PRD.md). Working name; see PRD.

Time estimates are rough, assume one developer part-time, and exist to size scope, not to promise dates. Each milestone has **exit criteria**: do not move on until they are met.

## Milestone 0: Spikes and decisions (≈ 1 week)

Goal: remove the biggest unknowns before writing product code.

- [ ] Confirm name; check PyPI / npm / GitHub / domain availability
- [ ] Decide license (ADR-004)
- [ ] Spike: trafilatura output quality on 10 varied sites (docs, blog, SPA, e-commerce)
- [ ] Spike: robots.txt parser choice (stdlib vs Protego) on edge cases (wildcards, `$`, groups, multiple UA lines)
- [ ] Spike: LiteLLM cost/usage reporting accuracy across two providers
- [ ] Spike: question generation quality on 5 pages; try with and without facts file
- [ ] Draft fixture-site list for calibration (30–50 sites)

**Exit:** each spike has a short written conclusion in DECISIONS; fixture list exists.

## Milestone 1: v0.1 "Audit" (≈ 4–6 weeks)

Goal: a useful, honest audit that works with no API key, plus an optional eval.

**Deliverables**

- [ ] Project skeleton: `uv`, `pyproject.toml`, ruff, pyright, pytest, pre-commit, CI
- [ ] Fetch layer: httpx client, SSRF guard, limits, bot registry, parity comparison
- [ ] robots.txt + sitemap parsing
- [ ] Extraction: content, structure, structured data
- [ ] All checks in [CHECKS](CHECKS.md) with fixtures and tests
- [ ] Scoring and reporters (terminal, JSON, Markdown)
- [ ] JSON Schema generated from models; schema validation in CI
- [ ] Config system (flags, env, toml) and `init`, `cache`, `doctor`
- [ ] Eval: question generation, answerer, judge, trials, cache, `--dry-run`, `--max-cost`
- [ ] Telemetry module (opt-in) and `telemetry` commands
- [ ] README with honest limitations, quickstart, and open-core boundary statement
- [ ] Docs site (mkdocs) with methodology page
- [ ] PyPI release via trusted publishing

**Exit criteria**

- A new user gets a report within 2 minutes of install with no key.
- Calibration run complete; false-positive rate < 5% on known-good fixture sites.
- Eval CI on the answerability mean is ≤ ±10 points on fixture sites at the default
  `--questions 50`, `--trials 3`. This is a sampling-error target, not a per-trial
  standard deviation; the two are distinct quantities ([EVALS §4.2](EVALS.md#42-resolution-why-the-default-is-50-questions-not-10)).
- No network or paid API use in CI.
- Telemetry allow-list test passes.

## Milestone 2: v0.2 "Generate + CI" (≈ 3–4 weeks)

Goal: turn findings into starter artifacts and make the tool a CI citizen.

- [ ] `generate llms-txt` (from sitemap and extracted titles). Offered as a convenience for
      users who want the file; per ADR-010 and CHECKS §7 it stays informational and its
      absence is never penalized
- [ ] `generate robots` with policy presets (allow all; allow search, block training; block all AI)
- [ ] `generate jsonld` for Organization / WebSite / Article skeletons with required-field prompts
- [ ] Official GitHub Action (`uses: OWNER/geoctl-action@v1`) with `fail-under`, PR comment summary, artifact upload
- [ ] SARIF or annotations output (optional) for PR surfaces
- [ ] `--only` / `--skip` polish; baseline file to ignore known findings
- [ ] Public changelog and contribution guide

**Exit:** a sample repo uses the Action in CI; generated files validate with the tool's own checks.

## Milestone 3: v0.3 "Fix by PR" (≈ 6–8 weeks)

Goal: the strongest differentiator. Findings become code changes.

- [ ] Machine-readable `fix.machine` payloads on checks that support it
- [ ] Repo analyzer: detect framework (Next.js first), router type (app/pages), metadata API usage
- [ ] LangGraph fix agent: plan → patch → self-check → re-run affected checks → PR description
- [ ] Supported fixes (initial): JSON-LD in layout/pages, metadata exports, heading/semantic fixes where mechanical, server-render guidance with scaffolded changes, robots/sitemap route files
- [ ] `geoctl fix --repo . [--pr]` with dry-run diff by default
- [ ] Safety: never pushes without confirmation; patches limited to allow-listed file types; tests for each patch template
- [ ] Before/after re-audit included in PR description

**Exit:** on 5 real open-source Next.js sites (forks), the agent opens PRs that build successfully and raise relevant check scores; failures documented.

## Milestone 4: v0.4 "Measure" (≈ 4–6 weeks)

Goal: close the loop with citation-style measurement, reported separately from the eval.

- [ ] Query set definition (YAML) per site
- [ ] Local snapshot runner against user-configured providers/search APIs, stored in SQLite
- [ ] `geoctl snapshots diff` for before/after comparison with repeated trials and significance caveats
- [ ] Clear reporting that citation behavior is provider-dependent and noisy
- [ ] Small public benchmark: pages with/without specific features vs measured outcomes, with methodology and raw data

**Exit:** a published write-up with data from at least 30 sites and honest uncertainty.

## Milestone 5: v1.0 (≈ 2–4 weeks hardening)

- [ ] Freeze CLI contract and JSON schema 1.x
- [ ] Plugin API for third-party checks (if demand)
- [ ] Documentation complete; security review; issue triage process
- [ ] Decide what, if anything, the hosted tier needs from the OSS repo (API stability, export formats)

## Hosted tier (separate track, starts only after v0.2–v0.3 shows real usage)

Not part of this repo's roadmap. Candidate scope, following the open-core principles in the PRD:

- Scheduled runs and persistent history
- Alerts on regressions or citation drops
- Multi-site and team workspaces, client-ready reports
- Managed provider keys and managed query sets

Trigger to start: sustained organic usage and repeated user requests for recurring monitoring.

## Public "won't do" list (for the README)

- No feature currently in OSS will be moved to a paid tier.
- No guarantees of citations or ranking.
- No stealth crawling or evasion of bot protection.
- No collection of site content by the telemetry system.

## Risks to the schedule

| Risk | Response |
|---|---|
| Extraction quality varies a lot across sites | Keep the crawler view explicitly an approximation; add per-site override only if needed |
| Eval stability is worse than expected | Increase default trials, tighten prompts, add judge calibration before shipping |
| Fix agent is more work than estimated | Ship a narrower set of fixes (JSON-LD + metadata) first |
| Competitors ship similar features | Prioritize eval validity and fix-by-PR; consider upstream contributions for commodity checks |
