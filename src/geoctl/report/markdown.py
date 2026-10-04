"""Markdown report (FR-21): a report you can paste into an issue or send a client."""

from __future__ import annotations

from ..models import AuditReport, CheckResult
from ..scoring import SCORED_CATEGORIES, status_counts, top_findings

_STATUS_ICON = {"pass": "✅", "warn": "⚠️", "fail": "❌", "skip": "⏭️", "error": "🛑"}


def render(report: AuditReport) -> str:
    out: list[str] = []
    score = report.score

    out.append(f"# geoctl report: {report.target.url}")
    out.append("")
    out.append(
        f"`geoctl {report.tool.version}` · schema `{report.schema_version}` · "
        f"checks `{report.run.checks_version}` · {report.run.started_at} · "
        f"{report.run.duration_ms / 1000:.1f}s"
    )
    out.append("")
    out.append(f"**Deterministic score: {score.overall:g} / {score.max:g}**")
    out.append("")
    out.append("| Category | Points | Max |")
    out.append("|---|---:|---:|")
    for category in SCORED_CATEGORIES:
        entry = score.categories.get(category)
        if entry is None:
            continue
        out.append(f"| {category.title()} | {entry.points:g} | {entry.max:g} |")
    out.append("")

    findings = top_findings(report.checks, limit=12)
    if findings:
        out.append("## Top findings")
        out.append("")
        for check in findings:
            out.append(f"### {_STATUS_ICON.get(check.status, '')} {check.id} — {check.title}")
            out.append("")
            out.append(f"**{check.status.upper()}** ({check.points:g}/{check.weight} points)")
            out.append("")
            out.append(check.message)
            if check.fix:
                out.append("")
                out.append(f"> **Fix:** {check.fix.summary}")
            out.append("")

    hygiene = status_counts(report.checks)
    if hygiene:
        out.append("## Hygiene (informational, 0 points)")
        out.append("")
        out.append("| Group | pass | warn | fail |")
        out.append("|---|---:|---:|---:|")
        for category, counts in sorted(hygiene.items()):
            out.append(
                f"| {category.replace('_', ' ').title()} | {counts.get('pass', 0)} | "
                f"{counts.get('warn', 0)} | {counts.get('fail', 0)} |"
            )
        out.append("")

    if report.eval:
        out.extend(_eval_section(report))

    if report.errors:
        out.append("## Warnings")
        out.append("")
        for err in report.errors:
            out.append(f"- `{err.code}` {err.message}")
        out.append("")

    out.append("---")
    out.append("")
    out.append(
        "Measures AI readiness \u2014 reach, read, answerability. Not citations or rankings: "
        "this report is **not** a prediction of what any AI product will cite or recommend."
    )
    out.append("")
    return "\n".join(out)


def _eval_section(report: AuditReport) -> list[str]:
    ev = report.eval
    assert ev is not None
    a = ev.answerability
    ci = a.get("ci95") or [0.0, 0.0]
    out = [
        "## Answerability",
        "",
        f"- **Mean: {a.get('mean', 0):.1f}** (95% CI {ci[0]:.1f} to {ci[1]:.1f}, "
        f"{ev.trials} trials, {ev.questions_per_page} questions/page)",
        f"- Context recall: {ev.context_recall:.0%} · retrieval gap: {ev.retrieval_gap:.0%}",
        f"- Abstained: {ev.abstention_rate:.0%} · hallucinated: {ev.hallucination_rate:.0%}",
        f"- Retrieval: {ev.retrieval.mode}, {ev.retrieval.chunk_count} chunks, "
        f"top-k {ev.retrieval.top_k}, `{ev.retrieval.embedding_model}`",
        f"- Answerer: `{ev.answerer_model}` · judge: `{ev.judge_model}`",
        f"- Ground truth: **{ev.ground_truth}** (confidence: {ev.confidence})",
        f"- Estimated cost: ${ev.usage.estimated_cost_usd:.4f}",
        "",
    ]
    if ev.confidence == "low":
        out.extend([
            "> Ground truth was the crawler view itself, which makes this circular. It measures "
            "clarity, not content loss, and must not be used to gate CI.",
            "",
        ])
    if ev.failures:
        out.append("### Questions that failed in most trials")
        out.append("")
        out.append("| Page | Question | Span retrieved | Likely cause |")
        out.append("|---|---|---|---|")
        for failure in ev.failures[:25]:
            page = failure.page.rstrip("/").rsplit("/", 1)[-1] or failure.page
            out.append(
                f"| {page} | {failure.question} | "
                f"{'yes' if failure.span_retrieved else 'no'} | {failure.likely_cause} |"
            )
        out.append("")
    return out


def _icon(check: CheckResult) -> str:
    return _STATUS_ICON.get(check.status, "")


__all__ = ["render"]