"""The composition root: one run, from the user's prompt to its exit code (SPECIFICATIONS.md §4, §6.10, §7.6).

:func:`run` builds what one run needs, opens the one substrate session, binds a fresh
:class:`~src.schemas.RunState` into the Supervisor's four tools, and invokes the Supervisor once. It then
renders the saved drafts and maps the outcome to an exit code. It never decides which tool runs next: the
Supervisor does, by calling its tools, and code here only reads what the run left behind once the Supervisor has
returned.

The module has no import-time side effects.
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Final, Literal, TypeAlias
from uuid import uuid4

from pydantic import ValidationError
from strands import Agent
from strands.models.model import Model

from .agents import (
    QA_LEGAL_MODEL_ID,
    QA_LEGAL_REASONING_EFFORT,
    SCOUT_MODEL_ID,
    SCOUT_REASONING_EFFORT,
    WRITER_MODEL_ID,
    WRITER_REASONING_EFFORT,
)
from .costs import load_model_rates
from .credentials import ReasoningSettings
from .hooks import FatalStopHook
from .logging_setup import log_context
from .mcp_client import HSEMockMCPClient
from .model_factory import ModelBuilder, build_model
from .rendering import RunFinalisation, finalise_run
from .schemas import AgentTelemetry, ExitCode, FailureRecord, PipelineConfig, RunContext, RunState
from .supervisor import SUPERVISOR_MODEL_ID, SUPERVISOR_REASONING_EFFORT, build_supervisor_agent, run_supervisor
from .tools import (
    MCP_LAUNCH_COMMAND,
    SESSION_ERRORS,
    SubAgentEfforts,
    SubAgentModels,
    build_tools,
    failed_call_telemetry,
    failure_record,
)

__all__ = ["ClientFactory", "Clock", "run"]

_LOGGER = logging.getLogger("src.app")

#: Seam returning the substrate client a run opens; tests inject an offline one.
ClientFactory: TypeAlias = Callable[[], HSEMockMCPClient]
#: Seam returning the run's current date, called once per run.
Clock: TypeAlias = Callable[[], date]
#: The failure stages that belong to the run rather than to one tool call (§6.7).
_RunStage: TypeAlias = Literal["configuration", "mcp_session", "supervisor"]


@dataclass(frozen=True)
class _Efforts:
    """The reasoning effort of each role, resolved once and used both to build its model and to label its telemetry.

    The Scout's effort is its role constant and is never overridden (D24); the others take an ``.env`` override
    when one is set, and their role constants otherwise.
    """

    scout: str | None
    writer: str | None
    qa_legal: str | None
    supervisor: str | None


@dataclass(frozen=True)
class _Models:
    """The run's four models, built once each; every agent built on them is fresh (D-G)."""

    scout: Model
    writer: Model
    qa_legal: Model
    supervisor: Model


@dataclass(frozen=True)
class _SupervisorOutcome:
    """How the one Supervisor invocation ended.

    Attributes:
        summary: Its final text exactly as returned, ``""`` after a typical fatal stop; ``None`` if it raised.
        telemetry: Its telemetry, recovered from its agent's metrics if it raised; ``None`` if no agent was built.
        raised: Whether building or invoking it raised, so it did not end its own invocation (P13).
    """

    summary: str | None
    telemetry: AgentTelemetry | None
    raised: bool


#: The outcome before the Supervisor is invoked. Once the run state exists nothing touches the session before the
#: Supervisor runs, so a run that maps its exit code always has a real outcome; this is only the variable's start.
_NOT_INVOKED: Final[_SupervisorOutcome] = _SupervisorOutcome(summary=None, telemetry=None, raised=False)


def run(
    prompt: str,
    config: PipelineConfig,
    *,
    client_factory: ClientFactory = HSEMockMCPClient,
    model_builder: ModelBuilder = build_model,
    clock: Clock = date.today,
    reasoning_settings: ReasoningSettings | None = None,
) -> RunState:
    """Run once: the Supervisor plans and drives the run; code renders what was saved and maps the exit code.

    Every line the run logs carries its ``run_id``. "Run completed" closes every run, early exits included, with
    the run's totals and the wall-clock measured here (P12). Nothing raises ``SystemExit``; the one exception let
    through is the ``ValueError`` of a ledger entry with no cost rate, which the shipped rates never leave.

    Args:
        prompt: The user's prompt, passed to the Supervisor verbatim (D-F).
        config: The resolved run configuration, with absolute paths.
        client_factory: Builds the substrate client; it is opened exactly once per run.
        model_builder: Builds the model of each role. Tests inject scripted models here (P4).
        clock: Returns the run's current date; called once.
        reasoning_settings: The ``.env`` effort overrides; read from the environment when omitted.

    Returns:
        The run state, with ``exit_code`` and ``supervisor_summary`` set.
    """
    started = time.perf_counter()
    run_id = uuid4().hex
    with log_context(run_id=run_id):
        state, code, finalisation = _run_once(
            run_id,
            prompt,
            config,
            client_factory=client_factory,
            model_builder=model_builder,
            today=clock(),
            reasoning_settings=reasoning_settings if reasoning_settings is not None else ReasoningSettings(),
        )
        _log_run_completed(state, code, finalisation, time.perf_counter() - started)
    return state


def _run_once(
    run_id: str,
    prompt: str,
    config: PipelineConfig,
    *,
    client_factory: ClientFactory,
    model_builder: ModelBuilder,
    today: date,
    reasoning_settings: ReasoningSettings,
) -> tuple[RunState, ExitCode, RunFinalisation | None]:
    """The run itself, in §4's order: configuration, the session, the Supervisor, then the run end.

    Returns:
        The run state with its exit code set, that same exit code, and what ``finalise_run`` reported; ``None``
        for a run that ended before its state was bound into any tool.
    """
    efforts = _resolve_efforts(reasoning_settings)
    _log_run_started(run_id, prompt, config, today, efforts)
    # Before any subprocess: a run that cannot be configured opens no session and spends nothing. A
    # ``ValidationError`` is a ``ValueError``; both are named because both are meant: unresolved settings, and an
    # effort the provider does not accept.
    try:
        rates = load_model_rates()
        models = _build_models(model_builder, efforts)
    except (ValidationError, ValueError) as exc:
        _LOGGER.error("Configuration failure: see .env.example for the required variables", exc_info=exc)
        code = ExitCode.CONFIG_ERROR
        return _ended_early(run_id, config, today, code, _run_failure("configuration", exc)), code, None

    # Exactly one session per run. Only the work that needs it sits inside the ``with``, so the subprocess has
    # always ended before the drafts are rendered and the exit code is mapped.
    client: HSEMockMCPClient | None = None
    state: RunState | None = None
    outcome = _NOT_INVOKED
    session_lost = False
    try:
        client = client_factory()
        with client:
            tool_count = len(client.list_all_tools())
            _LOGGER.info(
                "MCP session opened: server_dir=%s launch=%s tools=%d",
                client.server_dir,
                MCP_LAUNCH_COMMAND,
                tool_count,
            )
            state = RunState(run_id=run_id, config=config, context=_initial_context(config, today))
            outcome = _supervise(state, client, prompt, models, efforts, today)
    except SESSION_ERRORS as exc:
        _LOGGER.error(
            "MCP session failed to open, or died mid-run: server_dir=%s launch=%s",
            "-" if client is None else client.server_dir,
            MCP_LAUNCH_COMMAND,
            exc_info=exc,
        )
        if state is None:
            code = ExitCode.MCP_ERROR
            return _ended_early(run_id, config, today, code, _run_failure("mcp_session", exc)), code, None
        # Lost after the run state was bound, which only closing the session can do: the tools catch everything
        # their sub-agents raise. The run is over, so what it saved is still rendered.
        state.failures.append(_run_failure("mcp_session", exc))
        session_lost = True

    # The run end, after the subprocess has ended. ``finalise_run`` runs exactly once, whatever happened, and its
    # ``ValueError`` for an unpriced model is not caught: that is a defect, not a configuration the user can fix.
    finalisation = finalise_run(state, supervisor_telemetry=outcome.telemetry, rates=rates)
    state.supervisor_summary = outcome.summary
    code = _exit_code(
        fatal_stop=state.fatal_error is not None,
        session_lost=session_lost,
        supervisor_raised=outcome.raised,
        scout_succeeded=state.scope is not None,
        no_candidates=state.scope is not None and not state.documents,
        persistence_failed=finalisation.persistence_failed,
    )
    state.exit_code = code
    return state, code, finalisation


def _supervise(
    state: RunState,
    client: HSEMockMCPClient,
    prompt: str,
    models: _Models,
    efforts: _Efforts,
    today: date,
) -> _SupervisorOutcome:
    """Bind the run state into the four tools, build the Supervisor and invoke it once over the prompt.

    The one call to :func:`~src.supervisor.run_supervisor` is the whole run: which tool runs next, and when the run
    is finished, is the Supervisor's to decide. ``FatalStopHook`` is registered on the Supervisor only (D-D.1);
    the sub-agents get their own ``LoggingHooks`` from ``build_tools``, and nothing else.

    A provider or SDK error is recorded in full and logged; it is never retried. ``BaseException`` is not caught,
    so an interrupt still stops the process.
    """
    tools = build_tools(
        state,
        client=client,
        models=SubAgentModels(scout=models.scout, writer=models.writer, qa_legal=models.qa_legal),
        efforts=SubAgentEfforts(scout=efforts.scout, writer=efforts.writer, qa_legal=efforts.qa_legal),
    )
    _LOGGER.info(
        "Supervisor invocation started: role=supervisor model=%s effort=%s", SUPERVISOR_MODEL_ID, efforts.supervisor
    )
    started = time.perf_counter()
    agent: Agent | None = None
    try:
        agent = build_supervisor_agent(
            models.supervisor, tools, max_drafts=state.config.max_drafts, hooks=(FatalStopHook(state),)
        )
        output = run_supervisor(
            agent, prompt, today=today, model_id=SUPERVISOR_MODEL_ID, reasoning_effort=efforts.supervisor
        )
    except Exception as exc:
        failure = _run_failure("supervisor", exc)
        state.failures.append(failure)
        _LOGGER.error(
            "Supervisor invocation failed: model=%s effort=%s remote=%s",
            SUPERVISOR_MODEL_ID,
            efforts.supervisor,
            None if failure.remote is None else failure.remote.model_dump_json(),
            exc_info=exc,
        )
        # F1, §6.6: the tokens it spent before failing are read from its agent's metrics; none without an agent.
        telemetry = None if agent is None else failed_call_telemetry(agent, SUPERVISOR_MODEL_ID, efforts.supervisor)
        return _SupervisorOutcome(summary=None, telemetry=telemetry, raised=True)
    _LOGGER.info(
        "Supervisor invocation completed: role=supervisor model=%s effort=%s tokens=%d duration=%.2fs tools=%s",
        SUPERVISOR_MODEL_ID,
        efforts.supervisor,
        output.telemetry.total_tokens,
        time.perf_counter() - started,
        "[" + ", ".join(f"{t.tool_name} x{t.call_count}" for t in output.telemetry.tool_invocations) + "]",
    )
    return _SupervisorOutcome(summary=output.summary, telemetry=output.telemetry, raised=False)


def _run_failure(stage: _RunStage, exc: BaseException) -> FailureRecord:
    """Capture a failure of the run itself, in full (D22): it concerns no document and no attempt."""
    return failure_record(stage, exc, doc_id=None, attempt=None)


def _initial_context(config: PipelineConfig, today: date) -> RunContext:
    """The run's budget before any tool has run: the ``--max-drafts`` ceiling, and no draft saved (DM10)."""
    return RunContext(today=today, max_drafts=config.max_drafts, drafts_saved=0)


def _ended_early(run_id: str, config: PipelineConfig, today: date, code: ExitCode, failure: FailureRecord) -> RunState:
    """The result of a run that ended before its state was bound into any tool: nothing was saved or spent.

    Built only to carry the exit code and the failure; ``finalise_run`` is not called, since there is nothing to
    render and no Supervisor ran.
    """
    return RunState(
        run_id=run_id, config=config, context=_initial_context(config, today), failures=[failure], exit_code=code
    )


def _resolve_efforts(settings: ReasoningSettings) -> _Efforts:
    """Resolve each role's effort: an ``.env`` override, or the role constant when it is unset or empty."""
    return _Efforts(
        scout=SCOUT_REASONING_EFFORT,
        writer=settings.writer or WRITER_REASONING_EFFORT,
        qa_legal=settings.qa_legal or QA_LEGAL_REASONING_EFFORT,
        supervisor=settings.supervisor or SUPERVISOR_REASONING_EFFORT,
    )


def _build_models(model_builder: ModelBuilder, efforts: _Efforts) -> _Models:
    """Build the four models once each: the Scout on the fast binding, the other three on the strong one (D-H)."""
    return _Models(
        scout=model_builder(SCOUT_MODEL_ID, reasoning_effort=efforts.scout),
        writer=model_builder(WRITER_MODEL_ID, reasoning_effort=efforts.writer),
        qa_legal=model_builder(QA_LEGAL_MODEL_ID, reasoning_effort=efforts.qa_legal),
        supervisor=model_builder(SUPERVISOR_MODEL_ID, reasoning_effort=efforts.supervisor),
    )


def _log_run_started(run_id: str, prompt: str, config: PipelineConfig, today: date, efforts: _Efforts) -> None:
    """Log D-I's "Run started": the run, the raw prompt, the date, the ceiling, the level, models and efforts."""
    _LOGGER.info(
        "Run started: run_id=%s prompt=%r today=%s max_drafts=%s log_level=%s "
        "models=[scout=%s/%s, writer=%s/%s, qa_legal=%s/%s, supervisor=%s/%s]",
        run_id,
        prompt,
        today.isoformat(),
        config.max_drafts,
        config.log_level,
        SCOUT_MODEL_ID,
        efforts.scout,
        WRITER_MODEL_ID,
        efforts.writer,
        QA_LEGAL_MODEL_ID,
        efforts.qa_legal,
        SUPERVISOR_MODEL_ID,
        efforts.supervisor,
    )


def _log_run_completed(
    state: RunState, code: ExitCode, finalisation: RunFinalisation | None, wall_clock_seconds: float
) -> None:
    """Log D-I's "Run completed" once per run, with the run's totals and wall-clock (P12); nothing is stored (DM18).

    A run that ended before its state was bound spent nothing, so its totals are zero.
    """
    _LOGGER.info(
        "Run completed: exit_code=%s (%s) drafts_saved=%d failures=%d violations=%d total_tokens=%d "
        "estimated_cost_usd=%.6f wall_clock=%.2fs summary=%r",
        int(code),
        code.name,
        sum(1 for document in state.documents.values() if document.saved is not None),
        len(state.failures),
        len(state.violations),
        0 if finalisation is None else finalisation.total_tokens,
        0.0 if finalisation is None else finalisation.estimated_cost,
        wall_clock_seconds,
        state.supervisor_summary,
    )


def _exit_code(
    *,
    fatal_stop: bool,
    session_lost: bool,
    supervisor_raised: bool,
    scout_succeeded: bool,
    no_candidates: bool,
    persistence_failed: bool,
) -> ExitCode:
    """Map a finished run's outcome to its exit code: the numeric maximum of the §7.6 conditions that hold (P6).

    ``PARSER_ERROR`` needs a Supervisor that ended its own invocation (P13): it did not raise, no fatal stop
    occurred, and no ``scout_tool`` call succeeded. A session lost at the Scout is therefore ``MCP_ERROR``, and a
    Scout failure never retried successfully is ``PARSER_ERROR``. ``SUCCESS`` is the floor, whatever the number of
    drafts saved.

    Args:
        fatal_stop: A wrapper recorded a lost substrate session, and the fatal stop ended the Supervisor (D-D).
        session_lost: The substrate session was lost outside any tool, as it closed, after the run state existed.
        supervisor_raised: Building or invoking the Supervisor raised a provider or SDK error.
        scout_succeeded: A ``scout_tool`` call succeeded, so the run has a scope.
        no_candidates: The Scout succeeded with zero candidates.
        persistence_failed: A saved draft could not be rendered or written.

    Returns:
        The run's exit code.
    """
    holding = [ExitCode.SUCCESS]
    if fatal_stop or session_lost:
        holding.append(ExitCode.MCP_ERROR)
    if supervisor_raised:
        holding.append(ExitCode.SUPERVISOR_ERROR)
    if not supervisor_raised and not fatal_stop and not scout_succeeded:
        holding.append(ExitCode.PARSER_ERROR)
    if no_candidates:
        holding.append(ExitCode.NO_UPDATES)
    if persistence_failed:
        holding.append(ExitCode.PERSISTENCE_ERROR)
    return ExitCode(max(holding))
