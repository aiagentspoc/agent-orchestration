"""Pydantic v2 data models and internal contracts for HSE Easy Approach 2 (SPECIFICATIONS.md §6).

The substrate models, the agent outputs and the telemetry envelope are Approach 1's, unchanged; the attempt, tool
result and run-state models at the end of the module are Approach 2's own.
"""

import json
from datetime import date
from enum import IntEnum
from pathlib import Path
from typing import Any, Final, Generic, Literal, TypeAlias, TypeVar

from pydantic import BaseModel, ConfigDict, Field, computed_field

__all__ = [
    "MAX_ATTEMPTS_PER_DOC",
    "Source",
    "RegulatoryUpdateSummary",
    "RegulatoryDocument",
    "CitationVerificationResult",
    "TDIServiceOffering",
    "AgentContext",
    "PipelineScope",
    "AttemptRecord",
    "RunContext",
    "GuardrailName",
    "GuardrailViolation",
    "ToolResult",
    "DocumentRecord",
    "RunState",
    "ArticleDraft",
    "QAStatus",
    "QAReport",
    "DraftMetadata",
    "ScoutCandidate",
    "ScoutReport",
    "ToolInvocation",
    "AgentTelemetry",
    "WorkerOutput",
    "StageTelemetry",
    "ModelRate",
    "RemoteErrorDetail",
    "FailureStage",
    "FailureRecord",
    "PipelineConfig",
    "DraftResult",
    "ExitCode",
]


# ============================================================================
# Substrate Models (matching hse-easy-mock MCP server contracts)
# ============================================================================

#: The three authoritative source bodies of the substrate (SPECIFICATIONS.md §6.1).
Source: TypeAlias = Literal["EUR_LEX", "GAZZETTA_UFFICIALE", "INAIL"]


class RegulatoryUpdateSummary(BaseModel):
    """Tier 1 lightweight summary model for HSE regulatory updates."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    doc_id: str = Field(..., description="Unique slug identifier")
    source: Literal["EUR_LEX", "GAZZETTA_UFFICIALE", "INAIL"]
    doc_type: Literal["directive", "regulation", "decree", "circular", "guideline"]
    official_reference: str = Field(..., description="Canonical reference, e.g. 'D.Lgs. 81/2008'")
    title: str = Field(..., description="Official title in Italian")
    publication_date: str = Field(..., description="ISO 8601 YYYY-MM-DD")
    effective_date: str | None = None
    impact_level: Literal["critical", "high", "medium", "low"]
    topic_tags: list[str] = Field(default_factory=list)
    summary: str = Field(..., description="Executive summary")
    canonical_url: str


class RegulatoryDocument(RegulatoryUpdateSummary):
    """Tier 2 comprehensive document model."""

    status: Literal["in_force", "amended", "repealed", "proposed"]
    target_sectors: list[str] = Field(default_factory=list)
    key_obligations: list[str] = Field(default_factory=list)
    penalties_summary: str | None = None
    related_citations: list[str] = Field(default_factory=list)
    content_markdown: str


class CitationVerificationResult(BaseModel):
    """Legal citation verification result returned by legal QA tools."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    citation_input: str
    is_valid: bool
    status: Literal["in_force", "amended", "repealed", "unrecognized"]
    canonical_citation: str
    official_reference: str | None = None
    official_url: str | None = None
    verified_against_doc_id: str | None = None
    notes: str | None = None


class TDIServiceOffering(BaseModel):
    """Commercial service offering and pre-approved CTA templates."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    service_id: str
    service_name: str
    topic_category: str
    applicable_sectors: list[str] = Field(default_factory=list)
    value_proposition: str
    cta_headline: str
    cta_body: str
    landing_page_url: str


# ============================================================================
# Agent Input and Output Models (SPECIFICATIONS.md §6.2, §6.3, §6.8)
# ============================================================================


class AgentContext(BaseModel):
    """The run facts a sub-agent may know (DM5).

    Only the date, resolved once per run (Approach 1 D25). It never carries a
    budget or the attempt cap: those belong to the Supervisor's ``RunContext``.
    """

    model_config = ConfigDict(extra="ignore")

    today: date


class PipelineScope(BaseModel):
    """The Scout's input: the bounds of one run's search (DM2).

    The Supervisor builds the five scope fields from the user's prompt (Q12 = A),
    resolving ``date_from`` and ``date_to`` against the current date it is given
    in its user turn; code adds ``context``. The Scout passes the absolute bounds
    straight to ``list_regulatory_updates``, so it never has to infer "now". The
    guardrails, not this model, check that the dates are ISO and in order.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    context: AgentContext
    date_from: str = Field(..., description="Absolute start of the lookback window, ISO 8601 YYYY-MM-DD")
    date_to: str = Field(..., description="Absolute end of the lookback window, ISO 8601 YYYY-MM-DD")
    sources: list[Source] = Field(default_factory=list)
    sector_constraints: list[str] = Field(default_factory=list)
    max_drafts: int | None = Field(default=None, description="Draft limit; None = unconstrained")


class ArticleDraft(BaseModel):
    """Article content generated by Writer Agent.

    ``source_doc_id`` is the draft's provenance: the substrate slug of the
    document the article was written from, copied from the Writer's input. It is
    a plain string rather than a nested :class:`RegulatoryUpdateSummary` because
    the Writer *echoes* it, and asking an LLM to echo a whole nested record
    invites corruption. Without it the draft is four strings with no link back to
    the corpus, which leaves QA-Legal instructed to fetch the source instrument
    and holding nothing to fetch it with. The empty string is the Writer's
    contracted way of reporting that its own ``get_document_by_id`` call failed.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    source_doc_id: str = Field(
        ...,
        description="doc_id of the source document, copied exactly from the input; empty if the fetch failed",
    )
    headline: str
    executive_summary: str
    article_body: str
    tdi_cta: str


#: QA-Legal's tri-state verdict (SPECIFICATIONS.md §6.3).
QAStatus: TypeAlias = Literal["PASS", "WARNING", "ERROR"]


class QAReport(BaseModel):
    """Compliance audit returned by QA-Legal Agent."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    status: Literal["PASS", "WARNING", "ERROR"]
    verified_citations: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    review_notes: str = ""


class DraftMetadata(BaseModel):
    """Complete record required to render .agents/templates/draft.md."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    draft_id: str = Field(..., description="Consistent format: draft_YYYYMMDD_001")
    source_name: str
    publication_date: str
    source_document_title: str
    approach_name: str = "Approach 2 (Research Analyst)"
    qa_report: QAReport
    attempts: int
    latency_seconds: float
    estimated_cost: float
    total_tokens: int
    unresolved_errors: list[str] = Field(default_factory=list)
    stage_telemetry: list["StageTelemetry"] = Field(
        default_factory=list,
        description="Per-worker telemetry behind this draft; surfaces tool_invocations (SPECIFICATIONS §3.4)",
    )
    model_rates_used: dict[str, "ModelRate"] = Field(
        default_factory=dict,
        description="The cost basis this draft was priced with, so the figure is auditable after the fact",
    )


# ============================================================================
# Scout Triage Models (SPECIFICATIONS.md §6.3)
# ============================================================================


class ScoutCandidate(BaseModel):
    """One triaged regulatory update with its editorial relevance score."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    update: RegulatoryUpdateSummary
    newsworthiness_score: float = Field(..., ge=0.0, le=1.0)
    rationale: str = Field(..., description="Why this update qualifies for drafting")


class ScoutReport(BaseModel):
    """Ranked candidate set returned by the Scout Agent.

    Rule 4 assigns newsworthiness filtering to the Scout and requires drafts for
    all qualifying updates *unless the user set a limit*; D3 has the Scout pass
    all qualifying updates unless the user explicitly bounds ``max_drafts``.
    Neither assigns the ceiling to the orchestrator. So the Scout applies
    ``PipelineScope.max_drafts`` itself — scoring and ranking everything, then
    returning the top N — and this report carries every qualifying candidate only
    when that ceiling is null. The orchestrator retains a defensive cap on the
    returned count as a cost backstop, not as a second selection authority.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    candidates: list[ScoutCandidate] = Field(default_factory=list)


# ============================================================================
# Worker Telemetry Envelope (SPECIFICATIONS.md §6.3, §6.6)
# ============================================================================


class ToolInvocation(BaseModel):
    """Per-tool execution statistics for one agent invocation."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    tool_name: str
    call_count: int = 0
    success_count: int = 0
    error_count: int = 0
    total_time_seconds: float = 0.0


class AgentTelemetry(BaseModel):
    """Typed projection of ``AgentResult.metrics.get_summary()`` for one worker call."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    model_id: str = Field(..., description="Model binding per ARCHITECTURE §3; keys the cost rate table")
    reasoning_effort: str | None = Field(
        default=None,
        description=(
            "Resolved reasoning effort this invocation actually ran at (D24); None when the "
            "request carried no reasoning_effort at all. Configuration, not a metric: it is "
            "injected by the caller, since Strands surfaces no reasoning-token count"
        ),
    )
    input_tokens: int = 0
    cache_read_input_tokens: int = Field(
        default=0,
        description="Cached prefix already counted inside input_tokens; billed at the cached rate",
    )
    output_tokens: int = 0
    total_tokens: int = 0
    latency_ms: int = 0
    total_duration_seconds: float = 0.0
    cycles: int = 0
    tool_invocations: list[ToolInvocation] = Field(default_factory=list)


T = TypeVar("T", bound=BaseModel)


class WorkerOutput(BaseModel, Generic[T]):
    """What every Strands worker returns: its structured payload plus telemetry."""

    model_config = ConfigDict(extra="ignore")

    payload: T
    telemetry: AgentTelemetry


# ============================================================================
# Telemetry, Failures and Configuration (SPECIFICATIONS.md §6.4, §6.6, §6.7, §6.9)
# ============================================================================


class StageTelemetry(BaseModel):
    """One agent invocation's telemetry, labelled with the stage that produced it (DM12).

    ``AgentTelemetry.model_id`` cannot identify the agent: the Supervisor, the
    Writer and QA-Legal share ``gpt-5.4``. Without the stage label, D19's
    role-bleed detection cannot say *which* agent reached for a tool. ``doc_id``
    and ``attempt`` tie a Writer or QA-Legal call to its ``AttemptRecord``; both
    are ``None`` for the Supervisor and the Scout.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    stage: Literal["supervisor", "scout", "writer", "qa_legal"]
    doc_id: str | None = None
    attempt: int | None = Field(default=None, description="The Writer attempt; None outside any document")
    telemetry: AgentTelemetry


class ModelRate(BaseModel):
    """USD per one million tokens for one model, in three parts.

    Three rates and not four: the OpenAI provider populates ``cacheReadInputTokens``
    only — prompt caching is uncharged on write, and generated output is never
    cached — so an output-cached rate would price something that cannot occur.
    """

    model_config = ConfigDict(extra="ignore")

    input_usd_per_mtok: float = Field(..., ge=0.0)
    cached_input_usd_per_mtok: float = Field(default=0.0, ge=0.0)
    output_usd_per_mtok: float = Field(..., ge=0.0)


class RemoteErrorDetail(BaseModel):
    """Provider-side detail lifted off a remote failure, verbatim (D22).

    Populated by :func:`src.diagnostics.describe_exception`, which walks the
    ``__cause__`` chain so a Strands wrapper does not hide the HTTP status code,
    provider error code or request ID underneath it.
    """

    model_config = ConfigDict(extra="ignore")

    status_code: int | None = None
    provider_code: str | None = None
    provider_type: str | None = None
    request_id: str | None = None
    body: str | None = None
    cause_chain: list[str] = Field(default_factory=list)


#: Every point in the pipeline at which a failure can be attributed. Two of them sit
#: outside any single worker stage: ``configuration`` covers credentials or rates that
#: could not be resolved, so the run never started, and ``mcp_session`` covers opening
#: or losing the substrate session itself.
FailureStage: TypeAlias = Literal[
    "configuration",
    "mcp_session",
    "supervisor",
    "scout",
    "fetch_document",
    "writer",
    "qa_legal",
    "render",
    "persist",
]


class FailureRecord(BaseModel):
    """One failed pipeline stage, recorded in full (D22).

    Nothing here is truncated, summarised or sanitised: a partial batch failure
    that reaches the caller only as a log line cannot be inspected by the caller.
    """

    model_config = ConfigDict(extra="ignore")

    doc_id: str | None = None
    attempt: int | None = Field(default=None, description="The Writer attempt the failure belongs to, if any")
    stage: FailureStage
    error_type: str = Field(..., description="Fully-qualified exception class name")
    message: str = Field(..., description="The exception message, verbatim and never truncated")
    remote: RemoteErrorDetail | None = None
    traceback: str | None = Field(default=None, description="Full formatted traceback including the cause chain")


class PipelineConfig(BaseModel):
    """Resolved run configuration handed from the CLI to the pipeline core.

    Every path is absolute by the time it reaches here (PLAN §4.6), so no pipeline
    behaviour depends on the process working directory.
    """

    model_config = ConfigDict(extra="ignore")

    max_drafts: int | None = Field(default=None, description="CLI ceiling; overrides PipelineScope.max_drafts")
    log_level: str = "INFO"
    drafts_dir: Path
    template_path: Path
    log_dir: Path


class DraftResult(BaseModel):
    """What ``save_draft`` returns: the document marked saved, and its allocated draft (§6.4).

    Slim on purpose: the attempt count is already on every ``AttemptRecord`` the
    Supervisor was shown. ``path`` is where the draft is rendered at run end.
    """

    model_config = ConfigDict(extra="ignore")

    doc_id: str
    draft_id: str = Field(..., description="draft_YYYYMMDD_XXX")
    path: Path
    qa_status: QAStatus


# ============================================================================
# System Enumerations & Exit Codes
# ============================================================================


class ExitCode(IntEnum):
    """The CLI's exit codes (SPECIFICATIONS.md §6.10, §7.6); combined by numeric maximum (P6).

    ``CONFIG_ERROR`` exists because every other code describes a run that
    started: a misconfigured checkout that cannot resolve credentials would
    otherwise exit on Python's default uncaught-exception status of 1, which is
    ``NO_UPDATES`` — a *clean* exit meaning the regulatory feed was quiet.
    ``SUPERVISOR_ERROR`` is a Supervisor that failed on a provider or SDK error.
    """

    SUCCESS = 0
    NO_UPDATES = 1
    MCP_ERROR = 2
    PARSER_ERROR = 3
    PERSISTENCE_ERROR = 4
    CONFIG_ERROR = 5
    SUPERVISOR_ERROR = 6


# ============================================================================
# Attempts, Supervisor tool results and run state (SPECIFICATIONS.md §6.2-§6.5)
# ============================================================================

#: D-C rule 4: Writer attempts per document, an initial draft plus up to two revisions (Approach 1 D10).
#: Copied into every ``RunContext``; code, not the Supervisor, counts against it.
MAX_ATTEMPTS_PER_DOC: Final[int] = 3


class AttemptRecord(BaseModel):
    """One ``writer_tool`` call and, once audited, its QA report (DM4, D-C).

    The one input model of the Writer and QA-Legal, the result of ``writer_tool``
    and ``qa_tool``, and the stored attempt. ``candidate`` is the same object as
    the document's ``DocumentRecord.candidate``, never a copy (DM6). ``draft``
    stays ``None`` when the Writer call failed. Each slot is set once, through
    :meth:`set_draft` and :meth:`set_qa_report`, and never overwritten.
    """

    model_config = ConfigDict(extra="ignore")

    context: AgentContext
    candidate: ScoutCandidate
    attempt: int = Field(..., description="1-based position of this call among the document's attempts")
    draft: ArticleDraft | None = None
    qa_report: QAReport | None = None

    @computed_field
    @property
    def doc_id(self) -> str:
        """The substrate slug of the document this attempt is about, derived from ``candidate``."""
        return self.candidate.update.doc_id

    def set_draft(self, draft: ArticleDraft) -> None:
        """Store the Writer's draft in the empty ``draft`` slot.

        Raises:
            ValueError: If this attempt already holds a draft.
        """
        if self.draft is not None:
            raise ValueError(f"Attempt {self.attempt} of {self.doc_id!r} already holds a draft; a slot is set once.")
        self.draft = draft

    def set_qa_report(self, report: QAReport) -> None:
        """Store QA-Legal's report in the empty ``qa_report`` slot.

        Raises:
            ValueError: If this attempt already holds a QA report.
        """
        if self.qa_report is not None:
            raise ValueError(
                f"Attempt {self.attempt} of {self.doc_id!r} already holds a QA report; a slot is set once."
            )
        self.qa_report = report

    def writer_view(self) -> str:
        """The Writer's user turn (§7.2): the whole record as JSON, ``doc_id`` included."""
        return self.model_dump_json()

    def qa_view(self) -> str:
        """QA-Legal's user turn (§7.2): ``{doc_id, context, attempt, draft}`` as JSON, without the candidate."""
        return self.model_dump_json(exclude={"candidate", "qa_report"})

    def supervisor_view(self) -> dict[str, Any]:
        """What the Supervisor sees of an attempt (§7.2, D-F): ``{doc_id, context, attempt, qa_report}``.

        Never the draft or the candidate. Dumped in JSON mode, so every value is a
        plain JSON type, ready for :meth:`ToolResult.for_supervisor` to serialise.
        """
        return self.model_dump(mode="json", exclude={"draft", "candidate"})


class RunContext(BaseModel):
    """The budget the Supervisor sees (DM10); a snapshot goes into every ``ToolResult``.

    The Supervisor works out a document's attempts remaining from
    ``max_attempts_per_doc`` and the attempt number it is shown. ``max_drafts`` is
    the ``--max-drafts`` ceiling, ``None`` meaning unconstrained, and
    ``drafts_saved`` is counted from the run's documents when the snapshot is taken.
    """

    model_config = ConfigDict(extra="ignore")

    today: date
    max_attempts_per_doc: int = MAX_ATTEMPTS_PER_DOC
    max_drafts: int | None
    drafts_saved: int


#: The 12 rules code enforces on the Supervisor's tool calls (SPECIFICATIONS.md §6.7, D-C), in the order of §6.7.
GuardrailName: TypeAlias = Literal[
    "invalid_scope",
    "scout_already_run",
    "not_a_candidate",
    "attempt_limit",
    "initial_draft_exists",
    "not_audited",
    "revise_after_pass",
    "no_draft",
    "already_audited",
    "already_saved",
    "error_with_attempts_remaining",
    "draft_ceiling",
]


class GuardrailViolation(BaseModel):
    """One refused tool call (DM13): returned in ``ToolResult.error`` and stored in ``RunState.violations``.

    ``doc_id`` is ``None`` for a run-level guardrail. ``message`` is a plain
    explanation the Supervisor can act on, including any limit that was reached.
    """

    model_config = ConfigDict(extra="ignore")

    guardrail: GuardrailName
    tool_name: str
    doc_id: str | None
    message: str


class ToolResult(BaseModel, Generic[T]):
    """What every Supervisor tool returns (DM9): its result, a run snapshot and any error.

    ``result`` is ``None`` when the call was refused or produced nothing; a failed
    call that still has a result, such as an attempt with no draft, returns both.
    ``error`` is a :class:`GuardrailViolation` or a one-line failure summary.

    The default dumps carry the whole result, candidate and draft included.
    :meth:`for_supervisor` is therefore the only serialisation a tool may hand to
    the Supervisor (D-F).
    """

    model_config = ConfigDict(extra="ignore")

    result: T | None
    run: RunContext
    error: GuardrailViolation | str | None = None

    def for_supervisor(self) -> str:
        """Serialise this result as the JSON string a tool returns to the Supervisor (§7.2).

        An :class:`AttemptRecord` is sent as its :meth:`~AttemptRecord.supervisor_view`,
        so no draft, candidate or article text reaches the Supervisor. A
        ``ScoutReport`` or ``DraftResult`` is sent whole. ``run`` and ``error`` are
        always present.
        """
        if isinstance(self.result, AttemptRecord):
            result: dict[str, Any] | None = self.result.supervisor_view()
        elif self.result is None:
            result = None
        else:
            result = self.result.model_dump(mode="json")
        error = self.error.model_dump(mode="json") if isinstance(self.error, GuardrailViolation) else self.error
        payload = {"result": result, "run": self.run.model_dump(mode="json"), "error": error}
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


class DocumentRecord(BaseModel):
    """One Scout candidate and everything done with it, keyed by ``doc_id`` in ``RunState.documents`` (DM11).

    ``attempts`` is append-only: one :class:`AttemptRecord` per ``writer_tool``
    call, failed calls included. ``saved`` is set once, by ``save_draft``, and
    closes the document (P2). The four properties are derived on every read and
    never stored, so they cannot drift from ``attempts`` and ``saved``.
    """

    model_config = ConfigDict(extra="ignore")

    candidate: ScoutCandidate
    attempts: list[AttemptRecord] = Field(default_factory=list)
    saved: DraftResult | None = None

    @property
    def attempts_used(self) -> int:
        """Writer calls made on this document, whether or not they produced a draft."""
        return len(self.attempts)

    @property
    def attempts_remaining(self) -> int:
        """Writer calls still allowed under ``MAX_ATTEMPTS_PER_DOC``."""
        return MAX_ATTEMPTS_PER_DOC - self.attempts_used

    @property
    def latest_drafted(self) -> AttemptRecord | None:
        """The most recent attempt that holds a draft, skipping failed calls (D-C rule 8); ``None`` if none does."""
        return next((record for record in reversed(self.attempts) if record.draft is not None), None)

    @property
    def state(self) -> Literal["not_drafted", "drafted", "audited", "saved"]:
        """Where the document stands, read from ``saved`` and the latest draft."""
        if self.saved is not None:
            return "saved"
        latest = self.latest_drafted
        if latest is None:
            return "not_drafted"
        return "audited" if latest.qa_report is not None else "drafted"


class RunState(BaseModel):
    """Everything one run knows, seen only by code, and returned as the run's result (DM11, DM18).

    Created once per run and bound into every tool by ``build_tools(state, …)``.
    ``documents`` holds one :class:`DocumentRecord` per Scout candidate, in rank
    order; saved drafts and unfinished candidates are worked out from it, so
    nothing is stored twice. ``arbitrary_types_allowed`` is set for one reason:
    ``fatal_error`` holds the exception object itself (D-D), which pydantic has no
    schema for. ``exit_code`` and ``supervisor_summary`` are set at run end.
    """

    model_config = ConfigDict(extra="ignore", arbitrary_types_allowed=True)

    run_id: str
    config: PipelineConfig
    context: RunContext
    scope: PipelineScope | None = None
    documents: dict[str, DocumentRecord] = Field(default_factory=dict)
    ledger: list[StageTelemetry] = Field(default_factory=list)
    failures: list[FailureRecord] = Field(default_factory=list)
    violations: list[GuardrailViolation] = Field(default_factory=list)
    fatal_error: BaseException | None = None
    exit_code: ExitCode | None = None
    supervisor_summary: str | None = None

    def snapshot(self) -> RunContext:
        """Return a new :class:`RunContext` for a ``ToolResult``, with ``drafts_saved`` counted from ``documents``.

        ``context`` itself is left untouched, and the snapshot shares nothing with it.
        """
        drafts_saved = sum(1 for document in self.documents.values() if document.saved is not None)
        return self.context.model_copy(update={"drafts_saved": drafts_saved})


DraftMetadata.model_rebuild()
