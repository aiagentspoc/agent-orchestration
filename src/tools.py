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
    QA_LEGAL_REASONING_EFFORT,
    SCOUT_MODEL_ID,
    SCOUT_REASONING_EFFORT,
    WRITER_REASONING_EFFORT,
    build_scout_agent,
    extract_telemetry,
    run_scout,
)
from .diagnostics import describe_exception, format_traceback, qualified_type_name
from .guardrails import QA_TOOL, SAVE_DRAFT_TOOL, SCOUT_TOOL, WRITER_TOOL, ScoutArgs, check_scout
from .logging_setup import log_context
from .mcp_client import HSEMockMCPClient, MCPClientError, MCPClientNotConnectedError, MCPConnectionError
from .schemas import (
    AgentTelemetry,
    DocumentRecord,
    FailureRecord,
    FailureStage,
    GuardrailViolation,
    PipelineScope,
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
    "build_tools",
]

_LOGGER = logging.getLogger("src.tools")

#: How the substrate session is launched, quoted in the fatal-error log so a lost session is actionable (D-I); the
#: command ``HSEMockMCPClient`` runs, as Approach 1's orchestrator quoted it.
MCP_LAUNCH_COMMAND: Final[str] = "uv run --quiet --directory <server_dir> fastmcp run server.py"

#: The exceptions meaning the substrate session itself is lost (D-D). Anywhere in a failure's chain, they are fatal.
_FATAL_ERRORS: Final[tuple[type[MCPClientError], ...]] = (MCPConnectionError, MCPClientNotConnectedError)

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
        hooks: Hook providers registered on every sub-agent a tool builds.

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
                build=lambda: build_scout_agent(models.scout, client, hooks=hooks),
                run=lambda agent: run_scout(agent, checked, model_id=SCOUT_MODEL_ID, reasoning_effort=efforts.scout),
            )
            if isinstance(output, _SubAgentFailure):
                return ToolResult[ScoutReport](result=None, run=state.snapshot(), error=output.error).for_supervisor()
            _record_scout_success(state, checked, output.payload)
            return ToolResult[ScoutReport](result=output.payload, run=state.snapshot()).for_supervisor()

    @tool(name=WRITER_TOOL, description=WRITER_TOOL_DESCRIPTION)
    def writer_tool(doc_id: str, revise: bool) -> str:
        """Run the Writer on one candidate: a first draft, or a revision of the latest draft."""
        raise NotImplementedError("writer_tool is built in Iteration 8.")

    @tool(name=QA_TOOL, description=QA_TOOL_DESCRIPTION)
    def qa_tool(doc_id: str) -> str:
        """Run QA-Legal on the latest draft of one document."""
        raise NotImplementedError("qa_tool is built in Iteration 9.")

    @tool(name=SAVE_DRAFT_TOOL, description=SAVE_DRAFT_TOOL_DESCRIPTION)
    def save_draft(doc_id: str) -> str:
        """Mark one document's latest audited draft as saved."""
        raise NotImplementedError("save_draft is built in Iteration 10.")

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
    ``FailureRecord`` is built from the exception as caught, so any Strands wrapper stays in its chain. Stopping the
    Supervisor is Iteration 12's hook; this call still returns its error to the Supervisor.
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
    stage: _SubAgentStage,
    doc_id: str | None,
    attempt: int | None,
) -> _SubAgentFailure:
    """Record an ordinary sub-agent failure in full and summarise it for the Supervisor (§6.7, D-I).

    The run goes on: the Supervisor decides what to do with the failed call.
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
