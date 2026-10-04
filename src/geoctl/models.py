"""Result models shared by the fetch layer, checks, eval, and every reporter.

One result model, many reporters (ARCHITECTURE §1.3). Reporters must never
compute anything; they only render these models.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "1.0.0"

# Version of the check catalog and weights. Bumped when a check or a weight
# changes, because that changes reported scores across versions (CHECKS §8).
CHECKS_VERSION = "2026.10.0"

# Version of the eval prompts and retrieval configuration. Comparing scores
# across eval_version values is discouraged (EVALS §4.1).
EVAL_VERSION = "1"

CheckStatus = Literal["pass", "warn", "fail", "skip", "error"]
Confidence = Literal["high", "medium", "low"]
BlockedBy = Literal["robots", "waf", "challenge", "status"]
PolicyMode = Literal["report", "fail", "ignore"]


class _Base(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)


class Heading(_Base):
    level: int
    text: str


class MetaInfo(_Base):
    title: str | None = None
    description: str | None = None
    canonical: str | None = None
    lang: str | None = None
    robots_meta: str | None = None
    og: dict[str, str] = Field(default_factory=dict)
    html_chars: int = 0


class FetchResult(_Base):
    """One HTTP fetch, through one lens."""

    url: str
    final_url: str
    bot: str
    status: int | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    body: bytes | None = None
    elapsed_ms: int = 0
    error: str | None = None
    blocked_by: BlockedBy | None = None
    redirect_chain: list[dict[str, Any]] = Field(default_factory=list)
    challenge_marker: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.status is not None and 200 <= self.status < 300

    @property
    def body_len(self) -> int:
        return len(self.body or b"")


class PageView(_Base):
    """One page as seen through one lens (a bot user-agent, or a JS browser)."""

    url: str
    lens: str
    text: str = ""
    text_chars: int = 0
    headings: list[Heading] = Field(default_factory=list)
    meta: MetaInfo = Field(default_factory=MetaInfo)
    structured_data: list[dict[str, Any]] = Field(default_factory=list)
    html_chars: int = 0
    extraction_ratio: float = 0.0
    extraction_mode: str | None = None
    framework_markers: list[str] = Field(default_factory=list)
    shell_markers: list[str] = Field(default_factory=list)


class FixHint(_Base):
    summary: str
    docs_url: str | None = None
    # Reserved for the v0.3 fix agent (ROADMAP M3). Always null in v0.1.
    machine: dict[str, Any] | None = None


class CheckResult(_Base):
    id: str
    category: str
    title: str = ""
    status: CheckStatus
    weight: int = 0
    points: float = 0.0
    confidence: Confidence = "high"
    message: str = ""
    evidence: dict[str, Any] = Field(default_factory=dict)
    fix: FixHint | None = None


class SitemapReport(_Base):
    found: bool = False
    urls: list[str] = Field(default_factory=list)
    sitemap_urls: list[str] = Field(default_factory=list)
    parse_errors: list[str] = Field(default_factory=list)
    includes_start_url: bool = False
    stale_lastmod: list[str] = Field(default_factory=list)


class RobotsReport(_Base):
    found: bool = False
    url: str | None = None
    verdicts: dict[str, dict[str, Any]] = Field(default_factory=dict)
    sitemaps: list[str] = Field(default_factory=list)
    parse_failed: bool = False


class PageSummary(_Base):
    url: str
    status_by_bot: dict[str, int | None] = Field(default_factory=dict)
    text_chars: dict[str, int] = Field(default_factory=dict)
    title: str | None = None
    h1_count: int = 0
    json_ld_types: list[str] = Field(default_factory=list)


class RetrievalReport(_Base):
    mode: Literal["chunked", "whole_page"]
    top_k: int
    chunk_target_tokens: int
    chunk_overlap_pct: int
    embedding_model: str
    chunk_count: int


class EvalFailure(_Base):
    page: str
    question: str
    reference_answer: str
    outcomes: list[str] = Field(default_factory=list)
    span_retrieved: bool = False
    likely_cause: Literal[
        "content_not_in_crawler_view", "content_ambiguous", "answerer_error", "unknown"
    ] = "unknown"


class EvalUsage(_Base):
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0
    cache_hits: int = 0


class EvalResult(_Base):
    eval_version: str = EVAL_VERSION
    confidence: Confidence = "high"
    ground_truth: Literal["facts", "rendered", "facts+rendered", "crawler_only"]
    answerer_model: str
    judge_model: str
    trials: int
    questions_per_page: int
    pages_evaluated: int
    answerability: dict[str, Any] = Field(default_factory=dict)
    context_recall: float = 0.0
    retrieval_gap: float = 0.0
    retrieval: RetrievalReport
    abstention_rate: float = 0.0
    hallucination_rate: float = 0.0
    coverage_loss: float | None = None
    usage: EvalUsage = Field(default_factory=EvalUsage)
    failures: list[EvalFailure] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ScoreCategory(_Base):
    points: float = 0.0
    max: float = 0.0


class ScoreReport(_Base):
    overall: float = 0.0
    max: float = 100.0
    categories: dict[str, ScoreCategory] = Field(default_factory=dict)


class RunError(_Base):
    code: str
    severity: Literal["warning", "error"] = "warning"
    message: str
    url: str | None = None


class ToolInfo(_Base):
    name: str = "geoctl"
    version: str = "0.1.0"


class RunInfo(_Base):
    id: str
    started_at: str
    duration_ms: int = 0
    checks_version: str = CHECKS_VERSION
    eval_version: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)


class TargetInfo(_Base):
    url: str
    final_url: str
    pages_audited: int = 0
    sitemap_found: bool = False


class AuditReport(_Base):
    """The top-level document. `geoctl audit --format json` emits exactly this."""

    schema_version: str = SCHEMA_VERSION
    tool: ToolInfo = Field(default_factory=ToolInfo)
    run: RunInfo
    target: TargetInfo
    score: ScoreReport = Field(default_factory=ScoreReport)
    checks: list[CheckResult] = Field(default_factory=list)
    pages: list[PageSummary] = Field(default_factory=list)
    eval: EvalResult | None = None
    errors: list[RunError] = Field(default_factory=list)

    def scored_checks(self) -> list[CheckResult]:
        return [c for c in self.checks if c.weight > 0]