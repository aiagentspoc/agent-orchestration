"""Draft IDs at save time, and rendering at run end (SPECIFICATIONS.md D-B, D-C, §6.8; P11, P12).

``save_draft`` allocates a document's draft ID when it marks the document saved, but the file is written only when
the run ends (AGENTS.md Rule 5). Approach 1's :func:`~src.template_engine.generate_draft_id` finds the next number
by scanning the drafts folder, which was enough when each draft was written as soon as it was numbered; here the
IDs allocated earlier in the run have no file yet, so they are counted from ``RunState.documents`` as well.

:func:`finalise_run` is everything code does once the Supervisor has finished. It records the Supervisor's ledger
entry, logs every candidate left unsaved, and renders every saved draft in save order with its own Writer and
QA-Legal calls plus an equal share of the Scout and the Supervisor (D-B). It returns the run's tokens and cost for
the composition root to log on "Run completed" (P12). It decides nothing: no sub-agent call, no retry, no choice of
draft. This module must not import :mod:`src.tools`, which imports it.
"""

import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from .diagnostics import describe_exception, format_traceback, qualified_type_name
from .logging_setup import log_context
from .schemas import (
    AgentTelemetry,
    ArticleDraft,
    DocumentRecord,
    DraftMetadata,
    DraftResult,
    FailureRecord,
    FailureStage,
    ModelRate,
    QAReport,
    RunState,
    StageTelemetry,
)
from .telemetry import aggregate_draft_totals, amortise_shared_telemetry
from .template_engine import generate_draft_id, render_draft
from .template_engine import save_draft as write_draft_file

__all__ = ["RunFinalisation", "allocate_draft_id", "finalise_run"]

_LOGGER: Final[logging.Logger] = logging.getLogger("src.rendering")

#: The stages that serve the whole run, split equally across the saved drafts (D-B).
_SHARED_STAGES: Final[frozenset[str]] = frozenset({"scout", "supervisor"})
#: The stages that belong to one document, through ``StageTelemetry.doc_id``.
_OWN_STAGES: Final[frozenset[str]] = frozenset({"writer", "qa_legal"})

#: A draft ID exactly as ``f"draft_{stamp}_{n:03d}"`` builds it for ``n >= 1``: group 1 is the date, group 2 the
#: sequence number, three digits zero-padded or, past 999, four or more with no leading zero (``_0099`` is not one).
_DRAFT_ID_PATTERN: Final[re.Pattern[str]] = re.compile(r"^draft_(\d{8})_(\d{3}|[1-9]\d{3,})$")


def allocate_draft_id(state: RunState) -> str:
    """Allocate the next draft ID of the run's date, past every draft on disk and every ID this run allocated.

    The date is ``state.context.today``, the run's date, never the system clock. The disk contributes the number
    ``generate_draft_id`` would choose, and the run contributes one past the highest sequence among the documents
    already saved on that date, so IDs rise in save order. Nothing is written to disk: the drafts folder is scanned
    only if it exists, because ``generate_draft_id`` would otherwise create it.

    Args:
        state: The run state, read, never changed; call this before marking the document saved, so the document
            does not count an ID of its own.

    Returns:
        The draft ID, ``draft_{YYYYMMDD}_{XXX}``, the sequence zero-padded to three digits and wider past 999.
    """
    today = state.context.today
    stamp = today.strftime("%Y%m%d")
    drafts_dir = state.config.drafts_dir
    disk_next = _sequence(generate_draft_id(today, drafts_dir), stamp) if drafts_dir.is_dir() else 1
    run_highest = max(
        (
            _sequence(document.saved.draft_id, stamp)
            for document in state.documents.values()
            if document.saved is not None
        ),
        default=0,
    )
    return f"draft_{stamp}_{max(disk_next, run_highest + 1):03d}"


def _sequence(draft_id: str, stamp: str) -> int:
    """The sequence number of ``draft_id`` if it is a draft ID dated ``stamp``, else ``0``, which counts for nothing."""
    match = _DRAFT_ID_PATTERN.match(draft_id)
    if match is None or match.group(1) != stamp:
        return 0
    return int(match.group(2))


@dataclass(frozen=True)
class RunFinalisation:
    """What :func:`finalise_run` reports to the composition root, which logs it on "Run completed" (P12).

    Attributes:
        persistence_failed: Whether any saved draft could not be rendered or written; the composition root maps it
            to ``ExitCode.PERSISTENCE_ERROR`` (P6).
        total_tokens: The tokens of every ledger entry, the Supervisor's included: unsaved documents, failed calls
            and the Scout all count, because the run spent them (D-B).
        estimated_cost: The cost in USD of the same entries, on Approach 1's cost basis.
    """

    persistence_failed: bool
    total_tokens: int
    estimated_cost: float


def finalise_run(
    state: RunState,
    *,
    supervisor_telemetry: AgentTelemetry | None,
    rates: Mapping[str, ModelRate],
) -> RunFinalisation:
    """Do everything code does once the Supervisor has finished, deciding nothing (D-B, §6.8, P11, P12).

    In order: the Supervisor's entry is appended to the ledger (or a WARNING says why it cannot be); each candidate
    left unsaved is logged at WARNING; each saved draft is rendered and written in save order, a failure being
    recorded and the next draft still written; then the run's totals are computed over the whole ledger. Call it
    exactly once per run: a second call would append a second Supervisor entry to the ledger.

    Args:
        state: The run state; the Supervisor's entry is appended to ``ledger``.
        supervisor_telemetry: The Supervisor's telemetry, or ``None`` when it raised and no metrics could be read.
        rates: The resolved cost basis, keyed by model ID.

    Returns:
        Whether persistence failed, and the run's total tokens and cost. Nothing else is stored (DM18).

    Raises:
        ValueError: From ``estimate_cost``, if a ledger entry's model ID has no rate.
    """
    with log_context(run_id=state.run_id):
        if supervisor_telemetry is None:
            _LOGGER.warning("Supervisor telemetry unavailable at run end: no Supervisor entry is recorded")
        else:
            state.ledger.append(StageTelemetry(stage="supervisor", telemetry=supervisor_telemetry))
        _log_unsaved(state)
        saved = _in_save_order(state)
        shared = [entry for entry in state.ledger if entry.stage in _SHARED_STAGES]
        shares = amortise_shared_telemetry(shared, len(saved))
        supervisor_share_seconds = _own_seconds(supervisor_telemetry) / len(saved) if saved else 0.0
        written = [
            _render_and_write(
                state, document, result, share=share, supervisor_share_seconds=supervisor_share_seconds, rates=rates
            )
            for (document, result), share in zip(saved, shares, strict=True)
        ]
        total_tokens, estimated_cost = aggregate_draft_totals(state.ledger, [], rates)
        return RunFinalisation(
            persistence_failed=not all(written), total_tokens=total_tokens, estimated_cost=estimated_cost
        )


def _log_unsaved(state: RunState) -> None:
    """Log each candidate left unsaved, in rank order, with its last state (D-C "Unfinished candidates")."""
    for doc_id, document in state.documents.items():
        if document.saved is None:
            with log_context(doc_id=doc_id):
                _LOGGER.warning("Candidate left unsaved at run end: doc_id=%s last_state=%s", doc_id, document.state)


def _render_and_write(
    state: RunState,
    document: DocumentRecord,
    result: DraftResult,
    *,
    share: list[StageTelemetry],
    supervisor_share_seconds: float,
    rates: Mapping[str, ModelRate],
) -> bool:
    """Render one saved draft and write it to its allocated path; record, log and absorb a failure of either.

    The ``render`` stage covers building the metadata and rendering; the ``persist`` stage covers the write, and a
    file that lands anywhere but ``result.path`` fails it. The cost is computed before either, as Approach 1
    computes it, so an unknown model ID raises rather than being recorded as a render failure.

    Returns:
        ``True`` if the file was written, ``False`` if a failure was recorded instead.
    """
    own = [entry for entry in state.ledger if entry.stage in _OWN_STAGES and entry.doc_id == result.doc_id]
    totals = aggregate_draft_totals(own, share, rates)
    latest = document.latest_drafted
    attempt = None if latest is None else latest.attempt
    with log_context(doc_id=result.doc_id, attempt=attempt):
        stage: FailureStage = "render"
        try:
            rendered = _rendered_attempt(document, result)
            metadata = _draft_metadata(
                document,
                result,
                rendered,
                own=own,
                share=share,
                totals=totals,
                supervisor_share_seconds=supervisor_share_seconds,
                rates=rates,
            )
            content = render_draft(rendered.draft, metadata, template_path=state.config.template_path)
            stage = "persist"
            written_path = write_draft_file(content, result.draft_id, output_dir=result.path.parent)
            if written_path != result.path:
                raise RuntimeError(
                    f"Draft {result.draft_id!r} was written to {written_path}, not its allocated path {result.path}."
                )
        except Exception as exc:  # recorded in full and logged; the other drafts are still written
            _record_failure(state, stage, exc, result, attempt)
            return False
        _log_rendered(result, metadata, document.attempts_used)
        return True


@dataclass(frozen=True)
class _RenderedAttempt:
    """The draft and QA report a saved document is rendered from, the two slots a saved draft must have filled."""

    draft: ArticleDraft
    qa_report: QAReport


def _rendered_attempt(document: DocumentRecord, result: DraftResult) -> _RenderedAttempt:
    """The saved document's ``latest_drafted``, the draft that was saved (§6.8, P2).

    Raises:
        RuntimeError: If the latest draft is missing or was never audited, which ``save_draft`` makes impossible.
    """
    latest = document.latest_drafted
    if latest is None or latest.draft is None or latest.qa_report is None:
        raise RuntimeError(
            f"Document {result.doc_id!r} is saved as {result.draft_id!r} but has no audited latest draft to render."
        )
    return _RenderedAttempt(draft=latest.draft, qa_report=latest.qa_report)


def _draft_metadata(
    document: DocumentRecord,
    result: DraftResult,
    rendered: _RenderedAttempt,
    *,
    own: list[StageTelemetry],
    share: list[StageTelemetry],
    totals: tuple[int, float],
    supervisor_share_seconds: float,
    rates: Mapping[str, ModelRate],
) -> DraftMetadata:
    """The record one saved draft is rendered from, mapped as Approach 1's ``_build_draft_metadata`` maps it.

    ``approach_name`` is left at the model's default; ``unresolved_errors`` is filled only for an ``ERROR`` report,
    and ``format_review_notes`` turns it into the compliance banner, so no banner text is written here.
    """
    report = rendered.qa_report
    update = document.candidate.update
    total_tokens, estimated_cost = totals
    return DraftMetadata(
        draft_id=result.draft_id,
        source_name=update.source,
        publication_date=update.publication_date,
        source_document_title=update.title,
        qa_report=report,
        attempts=document.attempts_used,
        latency_seconds=_latency_seconds(own, share, supervisor_share_seconds),
        estimated_cost=estimated_cost,
        total_tokens=total_tokens,
        unresolved_errors=list(report.issues) if report.status == "ERROR" else [],
        stage_telemetry=own + share,
        model_rates_used=dict(rates),
    )


def _record_failure(
    state: RunState, stage: FailureStage, exc: Exception, result: DraftResult, attempt: int | None
) -> None:
    """Record one draft's render or write failure in full and log it at ERROR, traceback included (D22, D-I).

    A local twin of ``src.tools``' failure helper: ``src.tools`` imports this module, so it cannot be imported here.
    """
    state.failures.append(
        FailureRecord(
            doc_id=result.doc_id,
            attempt=attempt,
            stage=stage,
            error_type=qualified_type_name(exc),
            message=str(exc),
            remote=describe_exception(exc),
            traceback=format_traceback(exc),
        )
    )
    _LOGGER.error(
        "Draft render or write failure: stage=%s draft_id=%s path=%s doc_id=%s",
        stage,
        result.draft_id,
        result.path,
        result.doc_id,
        exc_info=exc,
    )


def _log_rendered(result: DraftResult, metadata: DraftMetadata, attempts_used: int) -> None:
    """Log one written draft at INFO and, if it carries the compliance banner, at WARNING too (D-I)."""
    _LOGGER.info(
        "Draft rendered: draft_id=%s path=%s doc_id=%s tokens=%d cost=%.6f",
        result.draft_id,
        result.path,
        result.doc_id,
        metadata.total_tokens,
        metadata.estimated_cost,
    )
    if metadata.qa_report.status == "ERROR":
        _LOGGER.warning(
            "Draft rendered with [UNRESOLVED COMPLIANCE ALERT]: draft_id=%s doc_id=%s attempts_used=%d issues=%s",
            result.draft_id,
            result.doc_id,
            attempts_used,
            metadata.unresolved_errors,
        )


def _own_seconds(supervisor: AgentTelemetry | None) -> float:
    """The Supervisor's own time: its duration less the time spent in its tools, never below zero (P11).

    Its duration contains every sub-agent call it made through a tool, each already counted on its own ledger
    entry, so only what remains is the Supervisor's. ``0.0`` when its telemetry could not be read.
    """
    if supervisor is None:
        return 0.0
    tool_seconds = sum(invocation.total_time_seconds for invocation in supervisor.tool_invocations)
    return max(supervisor.total_duration_seconds - tool_seconds, 0.0)


def _latency_seconds(
    own: list[StageTelemetry], share: list[StageTelemetry], supervisor_share_seconds: float
) -> float:
    """One draft's latency: its own calls, its Scout share and its share of the Supervisor's own time (P11).

    Never the sum of durations over ``stage_telemetry``: the Supervisor's share there still contains the sub-agent
    calls, so that sum would count them twice.
    """
    own_seconds = sum(entry.telemetry.total_duration_seconds for entry in own)
    scout_seconds = sum(entry.telemetry.total_duration_seconds for entry in share if entry.stage == "scout")
    return own_seconds + scout_seconds + supervisor_share_seconds


def _in_save_order(state: RunState) -> list[tuple[DocumentRecord, DraftResult]]:
    """The saved documents, in the order they were saved: by their draft ID's sequence number, never its text.

    ``allocate_draft_id`` hands out rising numbers in save order; ``documents`` is in Scout rank order, and sorting
    the ID strings would put ``_1000`` before ``_999``.
    """
    stamp = state.context.today.strftime("%Y%m%d")
    saved = [(document, document.saved) for document in state.documents.values() if document.saved is not None]
    return sorted(saved, key=lambda pair: _sequence(pair[1].draft_id, stamp))
