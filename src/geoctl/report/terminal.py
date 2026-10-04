"""Terminal report (FR-19).

Layout follows CLI_SPEC §7. Two things this report must not do: imply the score
forecasts citations or rankings, or let the hygiene tier look like it moved the
score.
"""

from __future__ import annotations

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ..models import AuditReport, CheckResult
from ..scoring import SCORED_CATEGORIES, status_counts, top_findings

STATUS_STYLE = {
    "pass": "green",
    "warn": "yellow",
    "fail": "red",
    "error": "red",
    "skip": "dim",
}

# The project's honesty commitment, printed in every terminal report.
DISCLAIMER = (
    "Measures AI readiness — reach, read, answerability. Not citations or rankings."
)


def bar(points: float, maximum: float, width: int = 22) -> str:
    if maximum <= 0:
        return "░" * width
    filled = round(width * min(points / maximum, 1.0))
    return "█" * filled + "░" * (width - filled)


def render(report: AuditReport, *, console: Console | None = None) -> str:
    """Render the report to a string.

    Rich writes to its own console; capturing via a StringIO-backed Console keeps
    the reporter testable and keeps stdout free for the report only (CLI_SPEC §6).
    """
    import io

    buffer = io.StringIO()
    out = console or Console(file=buffer, no_color=True, width=100, force_terminal=False)
    _render_to(report, out)
    return buffer.getvalue()


def _render_to(report: AuditReport, console: Console) -> None:
    console.print()
    run = report.run
    console.print(
        Text.assemble(
            ("geoctl ", "bold"),
            (report.tool.version, "cyan"),
            (" · ", "dim"),
            (report.target.url, ""),
            (" · ", "dim"),
            (f"{report.target.pages_audited} pages", "dim"),
            (" · ", "dim"),
            (f"{run.duration_ms / 1000:.1f}s", "dim"),
        )
    )

    score = report.score
    console.print()
    headline = Text.assemble(
        ("Deterministic score  ", "bold"),
        (f"{score.overall:g}", "bold green" if score.overall >= 70 else
         "bold yellow" if score.overall >= 40 else "bold red"),
        (f" / {score.max:g}", "dim"),
    )
    console.print(headline)

    table = Table.grid(padding=(0, 2))
    for category in SCORED_CATEGORIES:
        entry = score.categories.get(category)
        if entry is None:
            continue
        table.add_row(
            Text(f"  {category.title():<11}"),
            Text(bar(entry.points, entry.max), "magenta"),
            Text(f"{entry.points:g}/{entry.max:g}"),
        )
    console.print(table)

    hygiene = _hygiene_lines(report)
    if hygiene:
        console.print()
        console.print(Text("Hygiene (informational, not scored)", "bold"))
        console.print(Text("  " + "    ".join(hygiene), "dim"))

    findings = top_findings(report.checks, limit=8)
    if findings:
        console.print()
        console.print(Text("Top findings", "bold"))
        console.print(_findings_group(findings))

    if report.eval:
        console.print()
        console.print(_eval_panel(report))

    if report.errors:
        console.print()
        console.print(Text("Warnings", "bold yellow"))
        for err in report.errors[:10]:
            console.print(Text(f"  {err.code}: {err.message}", "yellow"))

    console.print()
    console.print(Text(DISCLAIMER, "dim italic"))
    console.print(
        Text("Full report: --format json | --format markdown", "dim")
    )
    console.print()


def _hygiene_lines(report: AuditReport) -> list[str]:
    lines = []
    for category, counts in sorted(status_counts(report.checks).items()):
        parts = [f"{n} {s}" for s, n in counts.items() if n and s != "skip"]
        if parts:
            lines.append(f"{category.replace('_', ' ').title()}  " + " · ".join(parts))
    return lines


def _findings_group(findings: list[CheckResult]) -> Group:
    parts: list[Text | Panel] = []
    for check in findings:
        label = Text()
        label.append(f"{check.status.upper():<6}", style=STATUS_STYLE.get(check.status, ""))
        label.append(f"{check.id} ", style="bold")
        label.append(check.title, style="dim")
        body = Text(check.message)
        if check.fix:
            body.append("\nFix: ", style="bold green")
            body.append(check.fix.summary)
        parts.append(Panel(body, title=label, border_style=STATUS_STYLE.get(check.status, ""),
                           padding=(0, 1)))
    return Group(*parts)


def _eval_panel(report: AuditReport) -> Panel:
    ev = report.eval
    assert ev is not None
    a = ev.answerability
    lines = [
        f"Answerability ({ev.answerer_model}, {ev.trials} trials, "
        f"{ev.questions_per_page} questions/page)",
        f"  Mean {a.get('mean', 0):.1f} ± {(a.get('ci95') or [0, 0])[1] - a.get('mean', 0):.1f}"
        f"    Context recall {ev.context_recall:.0%}"
        f"    Retrieval gap {ev.retrieval_gap:.0%}",
        f"  Abstained {ev.abstention_rate:.0%}   Hallucinated "
        f"{ev.hallucination_rate:.0%}   Cost ≈ ${ev.usage.estimated_cost_usd:.4f} (estimate)",
        f"  {ev.retrieval.chunk_count} chunks · top-k {ev.retrieval.top_k} · "
        f"embedding {ev.retrieval.embedding_model} · mode {ev.retrieval.mode}",
        f"  Ground truth: {ev.ground_truth} (confidence: {ev.confidence})",
    ]
    return Panel(Text("\n".join(lines)), title="Answerability", border_style="cyan", padding=(0, 1))