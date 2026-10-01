"""The Supervisor's four tools: custom agent tools around the sub-agents (SPECIFICATIONS.md §3.2, D-A, §6.4, §7.1).

:func:`build_tools` binds one run's :class:`~src.schemas.RunState` into ``scout_tool``, ``writer_tool``, ``qa_tool``
and ``save_draft`` by closure, so each tool reads and writes the typed state directly rather than through Strands'
untyped ``invocation_state`` (D-C). Everything the Supervisor sees of a tool is a contract: its name, its §7.1
description word for word, its §6.4 parameters, and the ``ToolResult.for_supervisor()`` string it returns (D-F).
"""

import logging
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from typing import Final, Literal, TypeAlias, TypeVar

from pydantic import BaseModel
from strands import Agent, tool
from strands.agent.agent_result import AgentResult
from strands.hooks import HookProvider
from strands.models.model import Model
from strands.types.tools import AgentTool

from .agents import (
    QA_LEGAL_MODEL_ID,
    QA_LEGAL_REASONING_EFFORT,
    SCOUT_MODEL_ID,
    SCOUT_REASONING_EFFORT,
    WRITER_MODEL_ID,
    WRITER_REASONING_EFFORT,
    build_qa_legal_agent,
    build_scout_agent,
    build_writer_agent,
    extract_telemetry,
    run_qa_legal,
    run_scout,
    run_writer,
)
from .diagnostics import describe_exception, format_traceback, qualified_type_name
from .guardrails import (
    QA_TOOL,
    SAVE_DRAFT_TOOL,
    SCOUT_TOOL,
    WRITER_TOOL,
    ScoutArgs,
    check_qa,
    check_save,
    check_scout,
    check_writer,
)
from .hooks import LoggingHooks
from .logging_setup import log_context
from .mcp_client import HSEMockMCPClient, MCPClientError, MCPClientNotConnectedError, MCPConnectionError
from .rendering import allocate_draft_id
from .schemas import (
    AgentContext,
    AgentTelemetry,
    ArticleDraft,
    AttemptRecord,
    DocumentRecord,
    DraftResult,
    FailureRecord,
    FailureStage,
    GuardrailViolation,
    PipelineScope,
    QAReport,
    RemoteErrorDetail,
    RunState,
    ScoutReport,
    StageTelemetry,
    ToolResult,
    WorkerOutput,
)

__all__ = [
    "MCP_LAUNCH_COMMAND",
    "QA_TOOL_DESCRIPTION",
    "SAVE_DRAFT_TOOL_DESCRIPTION",
    "SCOUT_TOOL_DESCRIPTION",
    "WRITER_TOOL_DESCRIPTION",
    "SubAgentEfforts",
    "SubAgentModels",
    "WriterSourceFetchError",
    "build_tools",
]

_LOGGER = logging.getLogger("src.tools")

#: How the substrate session is launched, quoted in the fatal-error log so a lost session is actionable (D-I); the
#: command ``HSEMockMCPClient`` runs, as Approach 1's orchestrator quoted it.
MCP_LAUNCH_COMMAND: Final[str] = "uv run --quiet --directory <server_dir> fastmcp run server.py"

#: The exceptions meaning the substrate session itself is lost (D-D). Anywhere in a failure's chain, they are fatal.
_FATAL_ERRORS: Final[tuple[type[MCPClientError], ...]] = (MCPConnectionError, MCPClientNotConnectedError)

#: The substrate tool the Writer must call to dereference its candidate (D-C rule 2, Approach 1 D23). Named here
#: because ``writer_tool`` checks the call's telemetry for it.
_SOURCE_FETCH_TOOL: Final[str] = "get_document_by_id"

_PayloadT = TypeVar("_PayloadT", bound=BaseModel)

#: The three sub-agent roles. Each name is both a ``StageTelemetry.stage`` and a ``FailureStage``.
_SubAgentStage: TypeAlias = Literal["scout", "writer", "qa_legal"]

#: SPECIFICATIONS.md §7.1, word for word: what the Supervisor model reads about each tool. Part of the system under
#: test, so a change here changes the benchmark.
SCOUT_TOOL_DESCRIPTION: Final[str] = (
    "Find and rank the regulatory updates within a scope. Call it once per run, with the scope you built from the "
    "user's prompt: `date_from` and `date_to` as ISO YYYY-MM-DD dates resolved against the current date, `sources` "
    "(any of EUR_LEX, GAZZETTA_UFFICIALE, INAIL; empty for all), `sector_constraints` (lowercase sectors; empty for "
    "all) and `max_drafts` (only when the user stated a limit, otherwise null). Returns the ranked candidates. An "
    "invalid scope is refused with a message; correct it and call again."
)
WRITER_TOOL_DESCRIPTION: Final[str] = (
    "Ask the Writer to draft the article for one candidate (`revise=false`), or to revise the latest draft against "
    "its QA report (`revise=true`). Each call uses one of the document's attempts, whether or not it succeeds. "
    "Returns the attempt number and the run limits; the article itself is never returned to you."
)
QA_TOOL_DESCRIPTION: Final[str] = (
    "Ask QA-Legal to audit the latest draft of one document. Each draft can be audited once. Returns the QA report: "
    "status (PASS, WARNING or ERROR), issues, review notes and verified citations."
)
SAVE_DRAFT_TOOL_DESCRIPTION: Final[str] = (
    "Mark one document's latest audited draft as saved. The draft file is written when the run ends. PASS and "
    "WARNING may be saved at any attempt; ERROR only when no attempts remain. Returns the draft ID and path."
)


class WriterSourceFetchError(RuntimeError):
    """The Writer did not demonstrably write from the document it was given (D-C rule 2, Approach 1 D23).

    Raised by ``writer_tool``, never by :mod:`src.agents`: a sub-agent has no authority over whether its own
    draft counts. It is recorded as :data:`~src.schemas.FailureStage` ``fetch_document`` because that is what
    failed, the dereference of the candidate's ``doc_id``, even though the call was the Writer's to make.
    """


@dataclass(frozen=True)
class SubAgentModels:
    """The three sub-agent models, built once per run by the composition root; agents are rebuilt per call (D-G)."""

    scout: Model
    writer: Model
    qa_legal: Model


@dataclass(frozen=True)
class SubAgentEfforts:
    """The reasoning effort each sub-agent's model was built at (D24), recorded on its telemetry.

    Resolved once by the composition root, ``.env`` overrides included, and used twice: to build each model and to
    label each call's ``AgentTelemetry``. The defaults are the compiled-in role constants of :mod:`src.agents`.
    """

    scout: str | None = SCOUT_REASONING_EFFORT
    writer: str | None = WRITER_REASONING_EFFORT
    qa_legal: str | None = QA_LEGAL_REASONING_EFFORT


def build_tools(
    state: RunState,
    *,
    client: HSEMockMCPClient,
    models: SubAgentModels,
    efforts: SubAgentEfforts,
    hooks: Sequence[HookProvider] = (),
) -> list[AgentTool]:
    """Build the Supervisor's four tools over one run's state.

    The tools carry no parameter descriptions of their own: §7.1's description holds all the guidance, so Strands'
    default ``Parameter <name>`` stands for each parameter, and the tool functions' docstrings have no ``Args``
    section for the SDK to publish.

    Args:
        state: The run state, bound into every tool by closure.
        client: The run's connected substrate client; every sub-agent is built with all five of its tools (P1).
        models: The three sub-agent models.
        efforts: The effort each model was built at, recorded on each call's telemetry.
        hooks: Hook providers registered on every sub-agent a tool builds, after the ``LoggingHooks`` of its role
            that every sub-agent gets (D-I). The Supervisor's own hooks, ``FatalStopHook`` among them, are never
            passed here, and neither is a ``LoggingHooks``, which would log every line twice.

    Returns:
        ``scout_tool``, ``writer_tool``, ``qa_tool`` and ``save_draft``, in that order.
    """

    @tool(name=SCOUT_TOOL, description=SCOUT_TOOL_DESCRIPTION)
    def scout_tool(
        date_from: str, date_to: str, sources: list[str], sector_constraints: list[str], max_drafts: int | None
    ) -> str:
        """Run the Scout once over the scope the Supervisor built."""
        with log_context(run_id=state.run_id):
            checked = check_scout(
                state,
                ScoutArgs(
                    date_from=date_from,
                    date_to=date_to,
                    sources=sources,
                    sector_constraints=sector_constraints,
                    max_drafts=max_drafts,
                ),
            )
            if isinstance(checked, GuardrailViolation):
                return _refuse(state, checked)
            _LOGGER.info("Scope built by the Supervisor: %s", checked.model_dump_json())
            output = _invoke_sub_agent(
                state,
                client,
                tool_name=SCOUT_TOOL,
                stage="scout",
                model_id=SCOUT_MODEL_ID,
                reasoning_effort=efforts.scout,
                build=lambda: build_scout_agent(models.scout, client, hooks=(LoggingHooks("scout"), *hooks)),
                run=lambda agent: run_scout(agent, checked, model_id=SCOUT_MODEL_ID, reasoning_effort=efforts.scout),
            )
            if isinstance(output, _SubAgentFailure):
                return ToolResult[ScoutReport](result=None, run=state.snapshot(), error=output.error).for_supervisor()
            _record_scout_success(state, checked, output.payload)
            return ToolResult[ScoutReport](result=output.payload, run=state.snapshot()).for_supervisor()

    @tool(name=WRITER_TOOL, description=WRITER_TOOL_DESCRIPTION)
    def writer_tool(doc_id: str, revise: bool) -> str:
        """Run the Writer on one candidate: a first draft, or a revision of the latest draft."""
        with log_context(run_id=state.run_id, doc_id=doc_id):
            violation = check_writer(state, doc_id, revise)
            if violation is not None:
                return _refuse(state, violation)
            document = state.documents[doc_id]
            # Resolved before the append, so a broken guardrail invariant raises with no attempt used.
            revision = _revision_source(document) if revise else None
            # D-C rule 3: the attempt counts from here, whether the call then succeeds or fails.
            record = AttemptRecord(
                context=AgentContext(today=state.context.today),
                candidate=document.candidate,
                attempt=document.attempts_used + 1,
            )
            document.attempts.append(record)
            with log_context(attempt=record.attempt):
                writer_input = record if revision is None else _revision_input(revision, record)
                output = _invoke_sub_agent(
                    state,
                    client,
                    tool_name=WRITER_TOOL,
                    stage="writer",
                    model_id=WRITER_MODEL_ID,
                    reasoning_effort=efforts.writer,
                    build=lambda: build_writer_agent(models.writer, client, hooks=(LoggingHooks("writer"), *hooks)),
                    run=lambda agent: run_writer(
                        agent, writer_input, model_id=WRITER_MODEL_ID, reasoning_effort=efforts.writer
                    ),
                    doc_id=doc_id,
                    attempt=record.attempt,
                )
                error = output.error if isinstance(output, _SubAgentFailure) else _store_draft(state, record, output)
                return ToolResult[AttemptRecord](result=record, run=state.snapshot(), error=error).for_supervisor()

    @tool(name=QA_TOOL, description=QA_TOOL_DESCRIPTION)
    def qa_tool(doc_id: str) -> str:
        """Run QA-Legal on the latest draft of one document."""
        with log_context(run_id=state.run_id, doc_id=doc_id):
            violation = check_qa(state, doc_id)
            if violation is not None:
                return _refuse(state, violation)
            # Resolved before any sub-agent is built, so a broken guardrail invariant raises with nothing spent.
            latest = _audit_target(state.documents[doc_id])
            with log_context(attempt=latest.attempt):
                output = _invoke_sub_agent(
                    state,
                    client,
                    tool_name=QA_TOOL,
                    stage="qa_legal",
                    model_id=QA_LEGAL_MODEL_ID,
                    reasoning_effort=efforts.qa_legal,
                    build=lambda: build_qa_legal_agent(
                        models.qa_legal, client, hooks=(LoggingHooks("qa_legal"), *hooks)
                    ),
                    run=lambda agent: run_qa_legal(
                        agent, latest, model_id=QA_LEGAL_MODEL_ID, reasoning_effort=efforts.qa_legal
                    ),
                    doc_id=doc_id,
                    attempt=latest.attempt,
                )
                error: str | None = None
                if isinstance(output, _SubAgentFailure):
                    error = output.error
                else:
                    _store_report(latest, output.payload)
                return ToolResult[AttemptRecord](result=latest, run=state.snapshot(), error=error).for_supervisor()

    @tool(name=SAVE_DRAFT_TOOL, description=SAVE_DRAFT_TOOL_DESCRIPTION)
    def save_draft(doc_id: str) -> str:
        """Mark one document's latest audited draft as saved."""
        with log_context(run_id=state.run_id, doc_id=doc_id):
            violation = check_save(state, doc_id)
            if violation is not None:
                return _refuse(state, violation)
            document = state.documents[doc_id]
            # Resolved before the allocation, so a broken guardrail invariant raises with nothing marked saved.
            latest, report = _save_target(document)
            # Allocated before ``saved`` is set, so the document does not count an ID of its own (§6.8).
            draft_id = allocate_draft_id(state)
            document.saved = DraftResult(
                doc_id=doc_id,
                draft_id=draft_id,
                path=state.config.drafts_dir / f"{draft_id}.md",
                qa_status=report.status,
            )
            with log_context(attempt=latest.attempt):
                _LOGGER.info(
                    "Document marked saved: doc_id=%s draft_id=%s qa_status=%s attempts=%d (the draft of attempt %d)",
                    doc_id,
                    draft_id,
                    report.status,
                    document.attempts_used,
                    latest.attempt,
                )
            return ToolResult[DraftResult](result=document.saved, run=state.snapshot()).for_supervisor()

    return [scout_tool, writer_tool, qa_tool, save_draft]


def _refuse(state: RunState, violation: GuardrailViolation) -> str:
    """Refuse one call (D-C): store the violation, log it at WARNING, and return it with no result.

    A violation never ends the run; the Supervisor reads its message and decides again.
    """
    state.violations.append(violation)
    _LOGGER.warning(
        "Guardrail violation: guardrail=%s tool=%s doc_id=%s message=%s",
        violation.guardrail,
        violation.tool_name,
        violation.doc_id,
        violation.message,
    )
    return ToolResult(result=None, run=state.snapshot(), error=violation).for_supervisor()


@dataclass(frozen=True)
class _SubAgentFailure:
    """A sub-agent call that raised, as the calling tool sees it: the one-line summary for the Supervisor."""

    error: str


def _invoke_sub_agent(
    state: RunState,
    client: HSEMockMCPClient,
    *,
    tool_name: str,
    stage: _SubAgentStage,
    model_id: str,
    reasoning_effort: str | None,
    build: Callable[[], Agent],
    run: Callable[[Agent], WorkerOutput[_PayloadT]],
    doc_id: str | None = None,
    attempt: int | None = None,
) -> WorkerOutput[_PayloadT] | _SubAgentFailure:
    """Run one sub-agent call: fresh agent, run, ledger entry, log, then classify any failure (D-A steps 2, 3, 5, 6).

    A failure whose chain holds ``MCPConnectionError`` or ``MCPClientNotConnectedError`` is fatal (D-D), however
    Strands wrapped it; any other ``Exception`` is recoverable. ``BaseException`` is never caught, so an interrupt
    still stops the process.

    Args:
        state: The run state the ledger entry and any failure are appended to.
        client: The run's substrate client, whose server directory a fatal failure's log names.
        tool_name: The Supervisor tool making the call, named in its failure summary and log lines.
        stage: The sub-agent's role, which labels its ledger entry.
        model_id: The model binding the call's telemetry records (a role constant, never the model's own config).
        reasoning_effort: The effort the sub-agent's model was built at.
        build: Builds the fresh agent; called once per call (D-G).
        run: Runs the agent on its one typed input, with ``structured_output_model``.
        doc_id: The document the call works on, or ``None`` for the Scout.
        attempt: The Writer attempt the call belongs to, or ``None`` outside one.

    Returns:
        The sub-agent's output and telemetry, or the failure the calling tool returns to the Supervisor.
    """
    _LOGGER.info("Sub-agent invocation started: role=%s model=%s effort=%s", stage, model_id, reasoning_effort)
    started = time.perf_counter()
    agent: Agent | None = None
    try:
        agent = build()
        output = run(agent)
    except Exception as exc:
        telemetry = _failed_call_telemetry(agent, model_id, reasoning_effort)
        state.ledger.append(StageTelemetry(stage=stage, doc_id=doc_id, attempt=attempt, telemetry=telemetry))
        fatal = _fatal_cause(exc)
        if fatal is not None:
            return _fatal_failure(state, client, exc, fatal, tool_name=tool_name, doc_id=doc_id, attempt=attempt)
        return _recoverable_failure(state, exc, tool_name=tool_name, stage=stage, doc_id=doc_id, attempt=attempt)
    state.ledger.append(StageTelemetry(stage=stage, doc_id=doc_id, attempt=attempt, telemetry=output.telemetry))
    _LOGGER.info(
        "Sub-agent invocation completed: role=%s model=%s effort=%s tokens=%d duration=%.2fs tools=%s",
        stage,
        model_id,
        reasoning_effort,
        output.telemetry.total_tokens,
        time.perf_counter() - started,
        _substrate_tools_used(output),
    )
    return output


def _failed_call_telemetry(agent: Agent | None, model_id: str, reasoning_effort: str | None) -> AgentTelemetry:
    """The telemetry of a call that raised: what its agent spent, or zero usage if no agent was built (§6.6).

    A failed call returns no ``AgentResult``, but its agent's ``event_loop_metrics`` survive the exception: Strands
    resets them only when an invocation starts. They are wrapped in a result so :func:`src.agents.extract_telemetry`
    stays the one reader of ``get_summary()``.
    """
    if agent is None:
        return AgentTelemetry(model_id=model_id, reasoning_effort=reasoning_effort)
    result = AgentResult(
        stop_reason="end_turn",
        message={"role": "assistant", "content": []},
        metrics=agent.event_loop_metrics,
        state={},
    )
    return extract_telemetry(result, model_id, reasoning_effort)


def _fatal_cause(exc: BaseException) -> MCPClientError | None:
    """Return the lost-session exception in ``exc``'s chain, or ``None`` when the failure is recoverable.

    The chain is walked because Strands wraps a model-side failure after the first tool cycle in an
    ``EventLoopException``, with the original as its ``__cause__``.
    """
    return next((link for link in _exception_chain(exc) if isinstance(link, _FATAL_ERRORS)), None)


def _fatal_failure(
    state: RunState,
    client: HSEMockMCPClient,
    exc: Exception,
    fatal: MCPClientError,
    *,
    tool_name: str,
    doc_id: str | None,
    attempt: int | None,
) -> _SubAgentFailure:
    """Record a lost substrate session (D-D): the fatal slot, an ``mcp_session`` failure and an ERROR log.

    The slot holds the MCP exception itself, and keeps the first lost session, which is what ended the run. The
    ``FailureRecord`` is built from the exception as caught, so any Strands wrapper stays in its chain. This call
    still returns its error to the Supervisor; :class:`~src.hooks.FatalStopHook` then stops the Supervisor once the
    call completes (D-D.1).
    """
    if state.fatal_error is None:
        state.fatal_error = fatal
    failure = _failure_record("mcp_session", exc, doc_id=doc_id, attempt=attempt)
    state.failures.append(failure)
    _LOGGER.error(
        "MCP session failed to open, or died mid-run: tool=%s server_dir=%s launch=%s",
        tool_name,
        client.server_dir,
        MCP_LAUNCH_COMMAND,
        exc_info=exc,
    )
    return _SubAgentFailure(error=_one_line_error(tool_name, exc, failure.remote))


def _recoverable_failure(
    state: RunState,
    exc: Exception,
    *,
    tool_name: str,
    stage: FailureStage,
    doc_id: str | None,
    attempt: int | None,
) -> _SubAgentFailure:
    """Record a recoverable failure in full and summarise it for the Supervisor (§6.7, D-I).

    An ordinary sub-agent failure, or a Writer draft that fails D-C rule 2. The run goes on: the Supervisor decides
    what to do with the failed call.
    """
    failure = _failure_record(stage, exc, doc_id=doc_id, attempt=attempt)
    state.failures.append(failure)
    _LOGGER.warning(
        "Recoverable tool failure returned to the Supervisor: tool=%s doc_id=%s attempt=%s",
        tool_name,
        doc_id,
        attempt,
        exc_info=exc,
    )
    return _SubAgentFailure(error=_one_line_error(tool_name, exc, failure.remote))


def _failure_record(
    stage: FailureStage, exc: BaseException, *, doc_id: str | None, attempt: int | None
) -> FailureRecord:
    """Capture one failure in full (Approach 1's ``_failure_record``, with ``attempt``): nothing is truncated (D22)."""
    return FailureRecord(
        doc_id=doc_id,
        attempt=attempt,
        stage=stage,
        error_type=qualified_type_name(exc),
        message=str(exc),
        remote=describe_exception(exc),
        traceback=format_traceback(exc),
    )


def _one_line_error(tool_name: str, exc: BaseException, remote: RemoteErrorDetail | None) -> str:
    """Summarise a failed call in one line for the Supervisor: the exception types, outermost first, and any status.

    Never the exceptions' own text, which can carry request bodies or input fragments, and never a traceback: the
    full detail stays in the ``FailureRecord`` and the log. It names no next step; the Supervisor decides that.
    """
    chain = " <- ".join(qualified_type_name(link) for link in _exception_chain(exc))
    status = "" if remote is None or remote.status_code is None else f" (HTTP {remote.status_code})"
    return f"{tool_name} failed: {chain}{status}"


def _exception_chain(exc: BaseException) -> Iterator[BaseException]:
    """Yield ``exc`` and every exception beneath it, outermost first, through ``__cause__`` or ``__context__``.

    The walk :func:`src.diagnostics.describe_exception` makes, restated here because that module keeps it private.
    """
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        following = current.__cause__
        if following is None and not current.__suppress_context__:
            following = current.__context__
        current = following


def _substrate_tools_used(output: WorkerOutput[_PayloadT]) -> str:
    """Name the substrate tools one call used, with their call counts, as ``[name xN, …]``.

    Strands counts its structured-output tool among the call's tools, under the output model's class name; it is
    not a substrate tool, so it is left out.
    """
    output_tool = type(output.payload).__name__
    used = [f"{t.tool_name} x{t.call_count}" for t in output.telemetry.tool_invocations if t.tool_name != output_tool]
    return "[" + ", ".join(used) + "]"


@dataclass(frozen=True)
class _Revision:
    """What a revision revises (D-E): the latest drafted attempt, and the QA report it carries."""

    source: AttemptRecord
    report: QAReport


def _revision_source(document: DocumentRecord) -> _Revision:
    """Resolve what a ``revise=true`` call revises, before its new attempt is appended.

    :func:`~src.guardrails.check_writer` refuses ``revise=true`` unless the latest draft carries a QA report
    (``not_audited``). Resolving it before the append means that, were that invariant ever broken, the call would
    raise with no attempt used rather than leave an attempt with no ledger entry or failure record.

    Raises:
        RuntimeError: If the document has no latest draft, or that draft has no QA report.
    """
    latest = document.latest_drafted
    if latest is None or latest.qa_report is None:
        raise RuntimeError(
            f"writer_tool reached a revision of {document.candidate.update.doc_id!r} with no audited draft; "
            "check_writer admits only an audited revision."
        )
    return _Revision(source=latest, report=latest.qa_report)


def _revision_input(revision: _Revision, record: AttemptRecord) -> AttemptRecord:
    """The Writer's input for a revision (D-E): the latest drafted attempt, with its draft and QA report; logged.

    Logged once ``record``, the new attempt, has been appended, so the line carries its number.
    """
    _LOGGER.info(
        "Revision requested: doc_id=%s attempt=%d follows=%s (the QA report on attempt %d)",
        record.doc_id,
        record.attempt,
        revision.report.status,
        revision.source.attempt,
    )
    return revision.source


def _store_draft(state: RunState, record: AttemptRecord, output: WorkerOutput[ArticleDraft]) -> str | None:
    """Keep the Writer's draft on its attempt only if the Writer dereferenced its source (D-C rule 2).

    A draft that fails the check is not kept: the attempt stays without one, and a ``fetch_document`` failure is
    recorded. The call's ledger entry was already written by :func:`_invoke_sub_agent`, so the tokens it spent are
    counted once either way.

    Args:
        state: The run state any failure is appended to.
        record: The new attempt the call used, whose empty ``draft`` slot the draft fills.
        output: The Writer's draft and the telemetry of the same call.

    Returns:
        ``None`` when the draft was stored, or the one-line error for the Supervisor.
    """
    try:
        _verify_writer_dereferenced_source(output.payload, output.telemetry, record.doc_id)
    except WriterSourceFetchError as exc:
        failure = _recoverable_failure(
            state, exc, tool_name=WRITER_TOOL, stage="fetch_document", doc_id=record.doc_id, attempt=record.attempt
        )
        return failure.error
    record.set_draft(output.payload)
    return None


def _verify_writer_dereferenced_source(draft: ArticleDraft, telemetry: AgentTelemetry, doc_id: str) -> None:
    """Check, code-side, that the Writer really fetched and named its own source (Approach 1's check, unchanged).

    A substrate tool error inside the Writer's turn is returned to the **model**, never raised to Python, so the
    returned ``ArticleDraft`` looks the same either way. Two independent signals are checked:

    1. **The call's telemetry names the tool.** A Writer that never called ``get_document_by_id`` drafted from the
       Scout's triage summary, which its own prompt disqualifies as a source. The call's argument is not checked.
    2. **The draft's provenance matches the candidate.** The Writer is contracted to return an empty
       ``source_doc_id`` when its fetch fails, so empty means "reported failure", and a different slug means the
       draft is about another document.

    Neither catches a Writer that calls the tool, receives an error and fabricates an article while echoing the
    right ID; QA-Legal is the backstop for that.

    Args:
        draft: The draft the Writer returned.
        telemetry: That same call's telemetry.
        doc_id: The candidate's ``doc_id``, which the Supervisor chose.

    Raises:
        WriterSourceFetchError: If either check fails.
    """
    fetched = any(
        invocation.tool_name == _SOURCE_FETCH_TOOL and invocation.call_count > 0
        for invocation in telemetry.tool_invocations
    )
    if not fetched:
        raise WriterSourceFetchError(
            f"The Writer produced a draft for {doc_id!r} without calling {_SOURCE_FETCH_TOOL} at all; "
            f"tools invoked: {[invocation.tool_name for invocation in telemetry.tool_invocations]}."
        )
    if draft.source_doc_id != doc_id:
        raise WriterSourceFetchError(
            f"The Writer returned source_doc_id {draft.source_doc_id!r} for candidate {doc_id!r}; "
            "an empty value is its contracted report of a failed fetch and a different value means "
            "the draft is not about the document it was given."
        )


def _audit_target(document: DocumentRecord) -> AttemptRecord:
    """Resolve what a ``qa_tool`` call audits (D-C rule 8): the latest drafted attempt, which has no QA report yet.

    :func:`~src.guardrails.check_qa` refuses a call unless that holds (``no_draft``, ``already_audited``). Resolving
    it before QA-Legal is built means that, were that invariant ever broken, the call would raise with no agent
    built, no token spent and no ledger entry, rather than fail in :meth:`~src.schemas.AttemptRecord.set_qa_report`
    after the audit.

    Raises:
        RuntimeError: If the document has no latest draft, or that draft already has a QA report.
    """
    latest = document.latest_drafted
    if latest is None or latest.qa_report is not None:
        raise RuntimeError(
            f"qa_tool reached {document.candidate.update.doc_id!r} with no unaudited draft; "
            "check_qa admits only an unaudited latest draft."
        )
    return latest


def _store_report(record: AttemptRecord, report: QAReport) -> None:
    """Store QA-Legal's report, as issued, on the attempt it audited, and log the verdict at its D-I level.

    ``PASS`` is logged at INFO; ``WARNING`` or ``ERROR`` at WARNING, with every issue rather than their count. The
    level is the only thing the status decides here: what to do with the report is the Supervisor's decision.
    """
    record.set_qa_report(report)
    if report.status == "PASS":
        _LOGGER.info("QA verdict PASS: doc_id=%s attempt=%d", record.doc_id, record.attempt)
        return
    _LOGGER.warning(
        "QA verdict %s: doc_id=%s attempt=%d issues=%s", report.status, record.doc_id, record.attempt, report.issues
    )


def _save_target(document: DocumentRecord) -> tuple[AttemptRecord, QAReport]:
    """Resolve what a ``save_draft`` call saves (D-C rule 9): the latest drafted attempt, and the QA report it carries.

    :func:`~src.guardrails.check_save` refuses a call unless that report exists (``not_audited``). Resolving it
    before the draft ID is allocated means that, were that invariant ever broken, the call would raise with nothing
    allocated, marked saved or logged.

    Raises:
        RuntimeError: If the document has no latest draft, or that draft has no QA report.
    """
    latest = document.latest_drafted
    if latest is None or latest.qa_report is None:
        raise RuntimeError(
            f"save_draft reached {document.candidate.update.doc_id!r} with no audited draft; "
            "check_save admits only an audited latest draft."
        )
    return latest, latest.qa_report


def _record_scout_success(state: RunState, scope: PipelineScope, report: ScoutReport) -> None:
    """Store a successful Scout call: the scope, then one document per candidate in the Scout's order (§6.5).

    A ``doc_id`` the Scout returns twice keeps its first, higher-ranked candidate, and the repeat is logged. The
    report itself is returned to the Supervisor as the Scout wrote it.
    """
    state.scope = scope
    for candidate in report.candidates:
        doc_id = candidate.update.doc_id
        if doc_id in state.documents:
            _LOGGER.warning("Duplicate Scout candidate ignored; the first is kept: doc_id=%s", doc_id)
            continue
        state.documents[doc_id] = DocumentRecord(candidate=candidate)
    if not report.candidates:
        _LOGGER.info("Scout result: No qualifying updates")
        return
    _LOGGER.info(
        "Scout result: %d candidate(s): %s",
        len(report.candidates),
        ", ".join(f"{c.update.doc_id} ({c.newsworthiness_score})" for c in report.candidates),
    )
