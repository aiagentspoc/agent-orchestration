"""``src.hooks``: the logging hooks and the fatal-stop hook (IMPLEMENTATION_PLAN.md Iteration 12).

SPECIFICATIONS.md D-I's "Model HTTP call", "Tool call started / completed", "Supervisor turn completed" and "Fatal
abort triggered (D-D)" events, and D-D.1's stop. Every agent here runs on a :class:`ScriptedModel` (P4), and every
assertion reads the ``src.hooks`` records ``caplog`` captured.
"""

import logging
import re
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any, Final

import pytest
from strands import Agent, tool
from strands.hooks import AfterModelCallEvent, AfterToolCallEvent, BeforeToolCallEvent, HookProvider, HookRegistry
from strands.tools.executors import SequentialToolExecutor
from strands.types.exceptions import MCPClientInitializationError

from src.hooks import AgentRole, FatalStopHook, LoggingHooks
from src.logging_setup import CorrelationFilter, log_context
from src.mcp_client import MCPConnectionError
from src.schemas import DocumentRecord, RunContext, RunState, ScoutCandidate
from src.tools import SubAgentEfforts, SubAgentModels, build_tools
from tests.support.scripted import (
    SCOPE_DATE_FROM,
    SCOPE_DATE_TO,
    OfflineSubstrateSession,
    ScriptedModel,
    offline_client,
    pipeline_config,
    qa_args,
    scout_candidate_args,
    scout_report_args,
    text_turn,
    tool_use_turn,
    tool_uses_turn,
    writer_turns,
)

#: The logger every hook event is written to.
HOOKS_LOGGER: Final[str] = "src.hooks"


@tool(name="noop")
def _noop() -> str:
    """Do nothing."""
    return "ok"


@pytest.fixture
def correlated(caplog: pytest.LogCaptureFixture) -> Iterator[pytest.LogCaptureFixture]:
    """``caplog`` at INFO on ``src.hooks``, its records stamped with the correlation fields as the run log's are."""
    correlation = CorrelationFilter()
    caplog.handler.addFilter(correlation)
    with caplog.at_level(logging.INFO, logger=HOOKS_LOGGER):
        yield caplog
    caplog.handler.removeFilter(correlation)


def _records(caplog: pytest.LogCaptureFixture, prefix: str) -> list[logging.LogRecord]:
    """The ``src.hooks`` INFO records whose message starts with ``prefix``, in order."""
    return [
        record
        for record in caplog.records
        if record.name == HOOKS_LOGGER and record.levelno == logging.INFO and record.getMessage().startswith(prefix)
    ]


def _correlation(record: logging.LogRecord) -> tuple[Any, ...]:
    """``(run_id, doc_id, attempt)`` as the :class:`CorrelationFilter` or ``extra=`` put them on ``record``."""
    return tuple(getattr(record, name) for name in ("run_id", "doc_id", "attempt"))


def _messages(caplog: pytest.LogCaptureFixture, prefix: str, level: int = logging.INFO) -> list[str]:
    """The ``src.hooks`` messages at ``level`` that start with ``prefix``, in order."""
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == HOOKS_LOGGER and record.levelno == level and record.getMessage().startswith(prefix)
    ]


# ---------------------------------------------------------------------------
# "Model HTTP call" (D-I): agent, stop reason, tokens
# ---------------------------------------------------------------------------


def test_each_model_call_is_logged_with_the_agent_its_stop_reason_and_its_own_tokens(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """One line per call, the tokens read from that call's usage, never the run's running total."""
    model = ScriptedModel(
        [
            tool_use_turn("noop", {}, input_tokens=11, output_tokens=7, cache_read_input_tokens=4),
            text_turn("done", input_tokens=3, output_tokens=2),
        ]
    )
    agent = Agent(model=model, tools=[_noop], hooks=[LoggingHooks("scout")], callback_handler=None)

    with caplog.at_level(logging.INFO, logger=HOOKS_LOGGER):
        agent("Run.")

    assert _messages(caplog, "Model HTTP call") == [
        "Model HTTP call: agent=scout stop_reason=tool_use input_tokens=11 cache_read_tokens=4 output_tokens=7 "
        "total_tokens=18",
        "Model HTTP call: agent=scout stop_reason=end_turn input_tokens=3 cache_read_tokens=0 output_tokens=2 "
        "total_tokens=5",
    ]


def test_a_failed_model_call_is_logged_with_its_error_type_and_no_tokens(caplog: pytest.LogCaptureFixture) -> None:
    """``stop_response`` is ``None`` on a failure: the line names the exception's type, and the error still raises."""
    agent = Agent(model=ScriptedModel([RuntimeError("boom")]), hooks=[LoggingHooks("writer")], callback_handler=None)

    with caplog.at_level(logging.INFO, logger=HOOKS_LOGGER), pytest.raises(RuntimeError, match="boom"):
        agent("Run.")

    assert _messages(caplog, "Model HTTP call") == ["Model HTTP call: agent=writer outcome=error:builtins.RuntimeError"]


def test_a_model_call_event_missing_its_usage_or_its_exception_is_still_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Shapes the event loop does not send today: a response with no usage logs zero tokens; neither, ``unknown``."""
    registry = HookRegistry()
    LoggingHooks("qa_legal").register_hooks(registry)
    agent = Agent(model=ScriptedModel([]), callback_handler=None)
    bare = AfterModelCallEvent.ModelStopResponse(message={"role": "assistant", "content": []}, stop_reason="end_turn")

    with caplog.at_level(logging.INFO, logger=HOOKS_LOGGER):
        registry.invoke_callbacks(AfterModelCallEvent(agent=agent, stop_response=bare))
        registry.invoke_callbacks(AfterModelCallEvent(agent=agent))

    assert _messages(caplog, "Model HTTP call") == [
        "Model HTTP call: agent=qa_legal stop_reason=end_turn input_tokens=0 cache_read_tokens=0 output_tokens=0 "
        "total_tokens=0",
        "Model HTTP call: agent=qa_legal outcome=error:unknown",
    ]


# ---------------------------------------------------------------------------
# "Tool call started / completed" (D-I): tool name, calling agent, doc_id, duration, outcome
# ---------------------------------------------------------------------------

#: A completed line's duration, which the SDK measures: seconds, to the millisecond.
_DURATION: Final[str] = r"duration=\d+\.\d{3}s"


@tool(name="writer_tool")
def _doc_tool(doc_id: str, revise: bool) -> str:
    """Stand in for a per-document Supervisor tool."""
    return "ok"


@tool(name="failing")
def _failing() -> str:
    """Raise."""
    raise ValueError("tool broke")


def _noop_as(name: str) -> Any:
    """A tool that does nothing, under ``name``: a stand-in for a substrate tool."""
    @tool(name=name)
    def _named(doc_id: str = "") -> str:
        """Do nothing."""
        return "ok"

    return _named


def _run_tools(role: AgentRole, turns: list[Any], tools: list[Any], hooks: list[HookProvider] | None = None) -> Agent:
    agent = Agent(
        model=ScriptedModel([*turns, text_turn("done")]),
        tools=tools,
        hooks=[*(hooks or []), LoggingHooks(role)],
        callback_handler=None,
        tool_executor=SequentialToolExecutor(),
    )
    agent("Run.")
    return agent


def test_a_sub_agents_tool_call_is_logged_with_the_tool_the_agent_and_its_wrappers_correlation(
    correlated: pytest.LogCaptureFixture,
) -> None:
    """A sub-agent runs inside its wrapper's ``log_context``, so its tool lines carry that document and attempt."""
    with log_context(run_id="run-1", doc_id="doc-a", attempt=2):
        _run_tools(
            "writer", [tool_use_turn("get_document_by_id", {"doc_id": "other-doc"})], [_noop_as("get_document_by_id")]
        )

    (started,) = _records(correlated, "Tool call started")
    (completed,) = _records(correlated, "Tool call completed")
    assert started.getMessage() == "Tool call started: tool=get_document_by_id agent=writer"
    assert re.fullmatch(
        f"Tool call completed: tool=get_document_by_id agent=writer {_DURATION} outcome=success", completed.getMessage()
    )
    assert _correlation(started) == _correlation(completed) == ("run-1", "doc-a", 2)


def test_a_supervisor_tool_call_names_the_document_its_input_names(correlated: pytest.LogCaptureFixture) -> None:
    """The Supervisor's tool events fire outside the wrapper's context, so its ``doc_id`` is read from the call."""
    with log_context(run_id="run-1"):
        _run_tools("supervisor", [tool_use_turn("writer_tool", {"doc_id": "doc-b", "revise": False})], [_doc_tool])

    lines = [*_records(correlated, "Tool call started"), *_records(correlated, "Tool call completed")]
    assert [record.getMessage().split(" duration=")[0] for record in lines] == [
        "Tool call started: tool=writer_tool agent=supervisor",
        "Tool call completed: tool=writer_tool agent=supervisor",
    ]
    assert [_correlation(record) for record in lines] == [("run-1", "doc-b", "-")] * 2


def test_a_supervisor_tool_call_with_no_document_keeps_the_enclosing_correlation(
    correlated: pytest.LogCaptureFixture,
) -> None:
    """``scout_tool`` names no document, so its lines read ``doc_id=-``."""
    with log_context(run_id="run-1"):
        _run_tools("supervisor", [tool_use_turn("noop", {})], [_noop])

    lines = [*_records(correlated, "Tool call started"), *_records(correlated, "Tool call completed")]
    assert [_correlation(record) for record in lines] == [("run-1", "-", "-")] * 2


def test_a_supervisor_tool_call_whose_input_is_not_an_object_keeps_the_enclosing_correlation(
    correlated: pytest.LogCaptureFixture,
) -> None:
    """An input the SDK could not parse into arguments names no document; nothing of it is logged."""
    registry = HookRegistry()
    LoggingHooks("supervisor").register_hooks(registry)
    agent = Agent(model=ScriptedModel([]), callback_handler=None)
    tool_use: Any = {"toolUseId": "writer_tool-1", "name": "writer_tool", "input": "{not json"}

    with log_context(run_id="run-1"):
        registry.invoke_callbacks(
            BeforeToolCallEvent(agent=agent, selected_tool=None, tool_use=tool_use, invocation_state={})
        )

    (started,) = _records(correlated, "Tool call started")
    assert started.getMessage() == "Tool call started: tool=writer_tool agent=supervisor"
    assert _correlation(started) == ("run-1", "-", "-")


def test_a_tool_that_raised_is_logged_with_the_error_status_and_the_exception_type(
    correlated: pytest.LogCaptureFixture,
) -> None:
    """The outcome is the result's status, and the exception's type when the tool raised; never its text."""
    _run_tools("qa_legal", [tool_use_turn("failing", {})], [_failing])

    (completed,) = _records(correlated, "Tool call completed")
    assert re.fullmatch(
        f"Tool call completed: tool=failing agent=qa_legal {_DURATION} outcome=error:builtins.ValueError",
        completed.getMessage(),
    )


class _CancelEveryTool(HookProvider):
    """Cancels every tool call before it runs, as a ``BeforeToolCallEvent`` hook can."""

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeToolCallEvent, self._cancel)

    def _cancel(self, event: BeforeToolCallEvent) -> None:
        event.cancel_tool = "held back"


def test_a_tool_cancelled_before_it_ran_is_logged_with_no_duration_and_its_cancel_message(
    correlated: pytest.LogCaptureFixture,
) -> None:
    """The SDK measures no duration for a call it never ran, so the line reads ``duration=-``."""
    _run_tools("scout", [tool_use_turn("noop", {})], [_noop], hooks=[_CancelEveryTool()])

    (completed,) = _records(correlated, "Tool call completed")
    assert completed.getMessage() == (
        "Tool call completed: tool=noop agent=scout duration=- outcome=error:cancelled:held back"
    )


# ---------------------------------------------------------------------------
# "Supervisor turn completed" (D-I): turn number, stop reason, tools requested, tokens, text
# ---------------------------------------------------------------------------


def test_each_supervisor_turn_is_logged_with_its_number_the_tools_it_requested_its_tokens_and_its_text(
    correlated: pytest.LogCaptureFixture,
) -> None:
    """Turns are numbered from 1; a turn asking for two tools names both, in order; the final turn has its text."""
    _run_tools(
        "supervisor",
        [tool_uses_turn(("noop", {}), ("failing", {}), input_tokens=11, output_tokens=7)],
        [_noop, _failing],
    )

    assert _messages(correlated, "Supervisor turn completed") == [
        "Supervisor turn completed: turn=1 stop_reason=tool_use tools_requested=[noop, failing] input_tokens=11 "
        "cache_read_tokens=0 output_tokens=7 total_tokens=18 text=''",
        "Supervisor turn completed: turn=2 stop_reason=end_turn tools_requested=[] input_tokens=3 "
        "cache_read_tokens=0 output_tokens=2 total_tokens=5 text='done'",
    ]


def test_a_failed_supervisor_model_call_is_not_counted_as_a_turn(correlated: pytest.LogCaptureFixture) -> None:
    """A call that raised and was retried is not a turn: the next successful response is still turn 1."""
    registry = HookRegistry()
    LoggingHooks("supervisor").register_hooks(registry)
    agent = Agent(model=ScriptedModel([]), callback_handler=None)
    response = AfterModelCallEvent.ModelStopResponse(
        message={"role": "assistant", "content": [{"text": "Fine."}, {"text": "Done."}]}, stop_reason="end_turn"
    )

    registry.invoke_callbacks(AfterModelCallEvent(agent=agent, exception=RuntimeError("throttled")))
    registry.invoke_callbacks(AfterModelCallEvent(agent=agent, stop_response=response))

    assert _messages(correlated, "Supervisor turn completed") == [
        "Supervisor turn completed: turn=1 stop_reason=end_turn tools_requested=[] input_tokens=0 cache_read_tokens=0 "
        "output_tokens=0 total_tokens=0 text='Fine.\\nDone.'"
    ]


@pytest.mark.parametrize("role", ["scout", "writer", "qa_legal"])
def test_a_sub_agent_writes_no_supervisor_turn_line(correlated: pytest.LogCaptureFixture, role: AgentRole) -> None:
    """D-I: the turn line is the Supervisor's alone; a sub-agent's calls are logged as model calls only."""
    _run_tools(role, [tool_use_turn("noop", {})], [_noop])

    assert _messages(correlated, "Supervisor turn completed") == []
    assert len(_messages(correlated, "Model HTTP call")) == 2


# ---------------------------------------------------------------------------
# FatalStopHook (D-D.1) and "Fatal abort triggered (D-D)"
# ---------------------------------------------------------------------------


@pytest.fixture
def state(tmp_path: Path) -> RunState:
    """A fresh run state, whose fatal slot is empty."""
    return RunState(
        run_id="run-test-0012",
        config=pipeline_config(tmp_path),
        context=RunContext(today=date(2026, 9, 22), max_drafts=None, drafts_saved=0),
    )


def _after_tool_call(agent: Agent, name: str) -> AfterToolCallEvent:
    """A completed ``name`` call on ``agent``, as the executor fires it."""
    return AfterToolCallEvent(
        agent=agent,
        selected_tool=None,
        tool_use={"toolUseId": f"{name}-1", "name": name, "input": {}},
        invocation_state={},
        result={"toolUseId": f"{name}-1", "status": "success", "content": [{"text": "ok"}]},
    )


def _fatal_hook(state: RunState) -> HookRegistry:
    registry = HookRegistry()
    FatalStopHook(state).register_hooks(registry)
    return registry


def test_the_fatal_stop_hook_does_nothing_while_the_fatal_slot_is_empty(
    state: RunState, caplog: pytest.LogCaptureFixture
) -> None:
    """No fatal error, no stop: the agent is not cancelled and nothing is logged."""
    agent = Agent(model=ScriptedModel([]), callback_handler=None)

    with caplog.at_level(logging.INFO, logger=HOOKS_LOGGER):
        _fatal_hook(state).invoke_callbacks(_after_tool_call(agent, "writer_tool"))

    assert not agent.cancel_signal.is_set()
    assert [record for record in caplog.records if record.name == HOOKS_LOGGER] == []


def test_the_fatal_stop_hook_cancels_the_agent_once_the_fatal_slot_is_set(state: RunState) -> None:
    """D-D.1: the first tool call to complete after a fatal error cancels the agent; the error itself is untouched."""
    agent = Agent(model=ScriptedModel([]), callback_handler=None)
    fatal = MCPConnectionError("the substrate transport died")
    state.fatal_error = fatal

    _fatal_hook(state).invoke_callbacks(_after_tool_call(agent, "writer_tool"))

    assert agent.cancel_signal.is_set()
    assert state.fatal_error is fatal


@pytest.mark.parametrize(("recording_tool", "later_tool"), [("writer_tool", "qa_tool"), ("scout_tool", "writer_tool")])
def test_the_fatal_abort_is_logged_once_at_error_with_its_cause_the_tool_and_the_exit_code(
    state: RunState, caplog: pytest.LogCaptureFixture, recording_tool: str, later_tool: str
) -> None:
    """D-I: "Fatal abort triggered (D-D)" names the cause, the tool that recorded it and ``MCP_ERROR`` (2), once."""
    agent = Agent(model=ScriptedModel([]), callback_handler=None)
    state.fatal_error = MCPConnectionError("the substrate transport died")
    registry = _fatal_hook(state)

    with caplog.at_level(logging.INFO, logger=HOOKS_LOGGER):
        registry.invoke_callbacks(_after_tool_call(agent, recording_tool))
        registry.invoke_callbacks(_after_tool_call(agent, later_tool))

    assert _messages(caplog, "Fatal abort triggered", level=logging.ERROR) == [
        "Fatal abort triggered (D-D): cause=src.mcp_client.MCPConnectionError "
        f"tool={recording_tool} exit_code=2 (MCP_ERROR)"
    ]
    assert [record.levelno for record in caplog.records if record.name == HOOKS_LOGGER] == [logging.ERROR]


# ---------------------------------------------------------------------------
# build_tools gives every sub-agent its LoggingHooks (D-I)
# ---------------------------------------------------------------------------

#: The candidate the flow below drafts and audits.
_DOC_ID: Final[str] = "inail-2026-ot23"


def _hook_lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    """Every ``src.hooks`` message captured so far, then clears the capture for the next call."""
    lines = [record.getMessage() for record in caplog.records if record.name == HOOKS_LOGGER]
    caplog.clear()
    return lines


def test_every_sub_agent_a_tool_builds_logs_its_model_and_tool_calls_under_its_role(
    state: RunState, correlated: pytest.LogCaptureFixture
) -> None:
    """Scout, Writer and QA-Legal each log "Model HTTP call" and "Tool call started / completed" as themselves."""
    tools = {
        tool_obj.tool_name: tool_obj
        for tool_obj in build_tools(
            state,
            client=offline_client(OfflineSubstrateSession()),
            models=SubAgentModels(
                scout=ScriptedModel(
                    [
                        tool_use_turn("list_regulatory_updates", {"source": "INAIL"}),
                        tool_use_turn("ScoutReport", scout_report_args(_DOC_ID)),
                    ]
                ),
                writer=ScriptedModel(writer_turns(_DOC_ID)),
                qa_legal=ScriptedModel(
                    [
                        tool_use_turn("verify_legal_citation", {"citation": "D.Lgs. 81/2008 Art. 28"}),
                        tool_use_turn("QAReport", qa_args(status="PASS")),
                    ]
                ),
            ),
            efforts=SubAgentEfforts(),
        )
    }

    tools["scout_tool"](
        date_from=SCOPE_DATE_FROM, date_to=SCOPE_DATE_TO, sources=["INAIL"], sector_constraints=[], max_drafts=None
    )
    scout = _hook_lines(correlated)
    tools["writer_tool"](doc_id=_DOC_ID, revise=False)
    writer = _hook_lines(correlated)
    tools["qa_tool"](doc_id=_DOC_ID)
    qa_legal = _hook_lines(correlated)

    for role, lines, substrate_tool in (
        ("scout", scout, "list_regulatory_updates"),
        ("writer", writer, "get_document_by_id"),
        ("qa_legal", qa_legal, "verify_legal_citation"),
    ):
        assert len([line for line in lines if line.startswith(f"Model HTTP call: agent={role} ")]) == 2, role
        assert f"Tool call started: tool={substrate_tool} agent={role}" in lines, role
        assert any(line.startswith(f"Tool call completed: tool={substrate_tool} agent={role} ") for line in lines)
        assert [line for line in lines if f"agent={role}" not in line] == [], role
    assert state.documents[_DOC_ID].attempts[0].qa_report is not None


# ---------------------------------------------------------------------------
# Acceptance criterion 2: a dying transport stops the Supervisor within one tool call
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("same_turn", [False, True], ids=["next-turn", "same-turn"])
def test_writer_tool_on_a_dead_transport_stops_a_scripted_supervisor_within_one_tool_call(
    state: RunState, caplog: pytest.LogCaptureFixture, same_turn: bool
) -> None:
    """D-D end to end: the Writer's build finds the session gone, ``writer_tool`` records it, and nothing else runs."""
    state.documents[_DOC_ID] = DocumentRecord(
        candidate=ScoutCandidate.model_validate(scout_candidate_args(_DOC_ID, 0.9, "Obblighi immediati."))
    )
    session = OfflineSubstrateSession(fail_listing_with=MCPClientInitializationError("the transport died"))
    writer = ScriptedModel([])
    tools = build_tools(
        state,
        client=offline_client(session),
        models=SubAgentModels(scout=ScriptedModel([]), writer=writer, qa_legal=ScriptedModel([])),
        efforts=SubAgentEfforts(),
    )
    writer_call = ("writer_tool", {"doc_id": _DOC_ID, "revise": False})
    qa_call = ("qa_tool", {"doc_id": _DOC_ID})
    script = (
        [tool_uses_turn(writer_call, qa_call), text_turn("done")]
        if same_turn
        else [tool_use_turn(*writer_call), tool_use_turn(*qa_call), text_turn("done")]
    )
    model = ScriptedModel(script)
    supervisor = Agent(
        model=model,
        tools=tools,
        hooks=[FatalStopHook(state)],
        callback_handler=None,
        tool_executor=SequentialToolExecutor(),
    )

    with caplog.at_level(logging.INFO):
        result = supervisor("Run.")

    assert result.stop_reason == "cancelled"
    assert model.turns_consumed == 1
    assert len(session.tool_filters_seen) == 1  # the Writer's build; no second sub-agent was ever built
    assert writer.turns_consumed == 0
    assert state.documents[_DOC_ID].attempts_used == 1
    assert [failure.stage for failure in state.failures] == ["mcp_session"]
    assert isinstance(state.fatal_error, MCPConnectionError)
    assert state.violations == []  # qa_tool was never called, so it was not refused either
    assert _messages(caplog, "Fatal abort triggered", level=logging.ERROR) == [
        "Fatal abort triggered (D-D): cause=src.mcp_client.MCPConnectionError tool=writer_tool exit_code=2 (MCP_ERROR)"
    ]
