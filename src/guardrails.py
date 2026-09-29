"""The D-C guardrail checks, as pure functions over ``RunState`` (SPECIFICATIONS.md D-C, §6.7, §7.3).

Each function runs one Supervisor tool's checks in the order of §7.3 and returns the first that fails, as a
:class:`GuardrailViolation`, or allows the call. None of them mutates the state, logs or does I/O: storing and
logging a violation is the calling tool's job (D-I). Code only refuses; a message restates the rule that was broken
and the state that broke it, and never names the call to make next.
"""

from datetime import date
from typing import Final, TypedDict

from pydantic import ValidationError

from .schemas import (
    MAX_ATTEMPTS_PER_DOC,
    AgentContext,
    AttemptRecord,
    DocumentRecord,
    GuardrailName,
    GuardrailViolation,
    PipelineScope,
    RunState,
)

__all__ = [
    "QA_TOOL",
    "SAVE_DRAFT_TOOL",
    "SCOUT_TOOL",
    "WRITER_TOOL",
    "ScoutArgs",
    "check_qa",
    "check_save",
    "check_scout",
    "check_writer",
]

#: The four Supervisor tool names of §7.1, as each violation's ``tool_name`` records them.
SCOUT_TOOL: Final[str] = "scout_tool"
WRITER_TOOL: Final[str] = "writer_tool"
QA_TOOL: Final[str] = "qa_tool"
SAVE_DRAFT_TOOL: Final[str] = "save_draft"


class ScoutArgs(TypedDict):
    """The five ``scout_tool`` arguments of §6.4, exactly as the Supervisor sent them.

    Raw on purpose: ``sources`` is ``list[str]`` so that an unknown source reaches :func:`check_scout` and becomes
    ``invalid_scope``, rather than failing the tool's schema before any code runs.
    """

    date_from: str
    date_to: str
    sources: list[str]
    sector_constraints: list[str]
    max_drafts: int | None


def _violation(guardrail: GuardrailName, tool_name: str, doc_id: str | None, message: str) -> GuardrailViolation:
    """Build the violation for one refused call."""
    return GuardrailViolation(guardrail=guardrail, tool_name=tool_name, doc_id=doc_id, message=message)


def check_scout(state: RunState, raw_scope: ScoutArgs) -> PipelineScope | GuardrailViolation:
    """Check a ``scout_tool`` call: ``scout_already_run``, then ``invalid_scope``.

    Args:
        state: The run state; read, never changed.
        raw_scope: The five scope fields the Supervisor sent.

    Returns:
        The ``PipelineScope`` to hand the Scout, with ``context`` filled in from the run, or the violation.
    """
    if state.scope is not None:
        return _violation(
            "scout_already_run",
            SCOUT_TOOL,
            None,
            "The Scout has already run successfully in this run, and the Scout runs once per run.",
        )
    try:
        # ``context`` goes last, so the run's date always wins over anything the Supervisor sent.
        scope = PipelineScope.model_validate({**raw_scope, "context": AgentContext(today=state.context.today)})
    except ValidationError as exc:
        return _invalid_scope(_validation_summary(exc))
    problem = _window_problem(scope)
    return scope if problem is None else _invalid_scope(problem)


def _invalid_scope(problem: str) -> GuardrailViolation:
    """Build the ``invalid_scope`` violation for one problem with the scope."""
    return _violation("invalid_scope", SCOUT_TOOL, None, f"The scope is invalid: {problem}.")


def _validation_summary(exc: ValidationError) -> str:
    """Summarise a scope validation error as ``field: reason`` pairs, without pydantic's version-specific URL."""
    return "; ".join(
        f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}" for error in exc.errors(include_url=False)
    )


def _window_problem(scope: PipelineScope) -> str | None:
    """Return why the scope's date window is unusable, or ``None`` if it is a forward ISO window.

    Approach 1's ``_validate_scope_bounds`` logic: each bound must parse as a date and round-trip to the same
    string, because ``date.fromisoformat`` also reads the basic form ``20260622`` and the week form
    ``2026-W26-1``, which the substrate does not. ``date_from`` may equal ``date_to`` but not follow it.
    """
    bounds: dict[str, date] = {}
    for field, raw in (("date_from", scope.date_from), ("date_to", scope.date_to)):
        bound: date | None
        try:
            bound = date.fromisoformat(raw)
        except ValueError:
            bound = None
        if bound is None or bound.isoformat() != raw:
            return f"{field} {raw!r} is not an ISO date; expected YYYY-MM-DD"
        bounds[field] = bound
    if bounds["date_from"] > bounds["date_to"]:
        return f"date_from {scope.date_from!r} falls after date_to {scope.date_to!r}; the window must run forward"
    return None


def check_writer(state: RunState, doc_id: str, revise: bool) -> GuardrailViolation | None:
    """Check a ``writer_tool`` call, in the order of §7.3.

    ``not_a_candidate`` → ``already_saved`` → ``attempt_limit``, then ``initial_draft_exists`` for a first draft, or
    ``not_audited`` → ``revise_after_pass`` for a revision. The latest draft is the last attempt that holds one, so
    a failed call leaves the earlier draft the latest (D-C rule 8).

    Args:
        state: The run state; read, never changed.
        doc_id: The document the Supervisor named.
        revise: ``False`` for the first draft, ``True`` to revise the latest draft against its QA report.

    Returns:
        The first violation, or ``None`` when the call is allowed.
    """
    document = _open_document(state, WRITER_TOOL, doc_id)
    if isinstance(document, GuardrailViolation):
        return document
    if document.attempts_used >= MAX_ATTEMPTS_PER_DOC:
        return _violation(
            "attempt_limit",
            WRITER_TOOL,
            doc_id,
            f"{doc_id!r}: {document.attempts_used} of {MAX_ATTEMPTS_PER_DOC} attempts used; a document has at most "
            f"{MAX_ATTEMPTS_PER_DOC} Writer attempts, failed calls included.",
        )
    latest = document.latest_drafted
    if not revise:
        if latest is None:
            return None
        return _violation(
            "initial_draft_exists",
            WRITER_TOOL,
            doc_id,
            f"{doc_id!r} already has a draft (attempt {latest.attempt}); revise=false is for the first draft only.",
        )
    if latest is None or latest.qa_report is None:
        return _not_audited(WRITER_TOOL, doc_id, latest, "revise=true")
    if latest.qa_report.status == "PASS":
        return _violation(
            "revise_after_pass",
            WRITER_TOOL,
            doc_id,
            f"The latest draft of {doc_id!r} (attempt {latest.attempt}) passed QA, and a PASS is never revised.",
        )
    return None


def check_qa(state: RunState, doc_id: str) -> GuardrailViolation | None:
    """Check a ``qa_tool`` call, in the order of §7.3.

    ``not_a_candidate`` → ``already_saved`` → ``no_draft`` → ``already_audited``. QA-Legal audits the latest draft
    once (D-C rule 8). After a failed revision the latest draft is still the earlier, audited one, so the call is
    refused; after a successful revision it is allowed again.

    Args:
        state: The run state; read, never changed.
        doc_id: The document the Supervisor named.

    Returns:
        The first violation, or ``None`` when the call is allowed.
    """
    document = _open_document(state, QA_TOOL, doc_id)
    if isinstance(document, GuardrailViolation):
        return document
    latest = document.latest_drafted
    if latest is None:
        return _violation("no_draft", QA_TOOL, doc_id, f"{doc_id!r} has no draft to audit.")
    if latest.qa_report is not None:
        return _violation(
            "already_audited",
            QA_TOOL,
            doc_id,
            f"The latest draft of {doc_id!r} (attempt {latest.attempt}) is already audited "
            f"({latest.qa_report.status}); each draft is audited once.",
        )
    return None


def check_save(state: RunState, doc_id: str) -> GuardrailViolation | None:
    """Check a ``save_draft`` call, in the order of §7.3.

    ``not_a_candidate`` → ``already_saved`` → ``not_audited`` → ``error_with_attempts_remaining`` →
    ``draft_ceiling``. The ceiling is ``config.max_drafts``, the ``--max-drafts`` value, and the drafts saved are
    counted from the documents, as every ``RunContext`` snapshot counts them.

    Args:
        state: The run state; read, never changed.
        doc_id: The document the Supervisor named.

    Returns:
        The first violation, or ``None`` when the call is allowed.
    """
    document = _open_document(state, SAVE_DRAFT_TOOL, doc_id)
    if isinstance(document, GuardrailViolation):
        return document
    latest = document.latest_drafted
    if latest is None or latest.qa_report is None:
        return _not_audited(SAVE_DRAFT_TOOL, doc_id, latest, "save_draft")
    if latest.qa_report.status == "ERROR" and document.attempts_remaining > 0:
        return _violation(
            "error_with_attempts_remaining",
            SAVE_DRAFT_TOOL,
            doc_id,
            f"The latest draft of {doc_id!r} (attempt {latest.attempt}) has QA status ERROR with "
            f"{document.attempts_remaining} of {MAX_ATTEMPTS_PER_DOC} attempts remaining; ERROR may be saved only "
            "when no attempts remain.",
        )
    ceiling = state.config.max_drafts
    drafts_saved = state.snapshot().drafts_saved
    if ceiling is not None and drafts_saved >= ceiling:
        return _violation(
            "draft_ceiling",
            SAVE_DRAFT_TOOL,
            doc_id,
            f"{doc_id!r} cannot be saved: {drafts_saved} of {ceiling} drafts saved (max_drafts {ceiling}), and a run "
            "saves at most max_drafts drafts.",
        )
    return None


def _open_document(state: RunState, tool_name: str, doc_id: str) -> DocumentRecord | GuardrailViolation:
    """Return the document a per-document call may work on, or its ``not_a_candidate`` or ``already_saved`` violation.

    Rules 1 and 10 (P2, P3): only a Scout candidate can be worked on, and a saved document is closed.
    """
    document = state.documents.get(doc_id)
    if document is None:
        return _violation(
            "not_a_candidate",
            tool_name,
            doc_id,
            f"{doc_id!r} is not a candidate the Scout returned; only Scout candidates can be worked on.",
        )
    if document.saved is not None:
        return _violation(
            "already_saved",
            tool_name,
            doc_id,
            f"{doc_id!r} is already saved as {document.saved.draft_id}, and a saved document is closed to further "
            "Writer, QA and save calls.",
        )
    return document


def _not_audited(tool_name: str, doc_id: str, latest: AttemptRecord | None, call: str) -> GuardrailViolation:
    """Build the ``not_audited`` violation: ``call`` needs a QA report on the latest draft (rules 7 and 9)."""
    found = (
        f"{doc_id!r} has no draft yet"
        if latest is None
        else f"The latest draft of {doc_id!r} (attempt {latest.attempt}) has no QA report"
    )
    return _violation("not_audited", tool_name, doc_id, f"{found}; {call} needs a QA report on the latest draft.")
