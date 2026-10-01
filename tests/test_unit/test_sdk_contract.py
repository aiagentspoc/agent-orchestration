"""Characterisation tests of the installed ``strands-agents`` 1.55.1 (IMPLEMENTATION_PLAN.md Iteration 12).

They pin the SDK behaviours Approach 2 is built on, and are kept permanently: an SDK upgrade that changes one of
them fails here first, loudly, rather than in a run.

* **Part (a), the fatal stop (SPECIFICATIONS.md D-D, D-D.1).** A scripted "supervisor" calls a tool that records a
  fatal error, and its script would then call a second tool and send one more turn. The candidates are tried in the
  plan's order and the first that passes every assertion is kept: an ``AfterToolCallEvent`` hook that calls
  ``Agent.cancel()``. The no-hook control shows the same script does run on without it.
* **Part (b), the logging hooks (D-I, D-H).** When ``AfterModelCallEvent``, ``BeforeToolCallEvent`` and
  ``AfterToolCallEvent`` fire and what they carry, and how the two tool executors schedule one turn's tools.

Every model is a :class:`ScriptedModel` (P4); nothing here spends a token.
"""

import threading
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Final

import pytest
from strands import Agent, tool
from strands.agent.agent_result import AgentResult
from strands.hooks import AfterModelCallEvent, AfterToolCallEvent, BeforeToolCallEvent, HookProvider, HookRegistry
from strands.tools.executors import ConcurrentToolExecutor, SequentialToolExecutor
from strands.types.tools import AgentTool

from src.hooks import FatalStopHook
from src.mcp_client import MCPConnectionError
from src.schemas import RunContext, RunState
from src.tools import SubAgentEfforts, SubAgentModels, build_tools
from tests.support.scripted import (
    SCOPE_DATE_FROM,
    SCOPE_DATE_TO,
    OfflineSubstrateSession,
    ScriptedModel,
    offline_client,
    pipeline_config,
    scout_report_args,
    text_turn,
    tool_use_turn,
    tool_uses_turn,
)

#: The two tools of the part (a) script: the one that records the fatal error, and the one that must never run.
FATAL_TOOL: Final[str] = "fatal_tool"
SECOND_TOOL: Final[str] = "second_tool"


# ---------------------------------------------------------------------------
# Part (a): the fatal stop (D-D)
# ---------------------------------------------------------------------------


@pytest.fixture
def state(tmp_path: Path) -> RunState:
    """A fresh run state, whose fatal slot is empty."""
    return RunState(
        run_id="run-test-0012",
        config=pipeline_config(tmp_path),
        context=RunContext(today=date(2026, 9, 22), max_drafts=None, drafts_saved=0),
    )


@dataclass
class _Outcome:
    """What one scripted supervisor invocation did: its result or exception, and what it ran."""

    result: AgentResult | None
    raised: Exception | None
    turns_consumed: int
    ran: list[str]
    messages: list[dict[str, Any]]


def _spike_tools(state: RunState, ran: list[str]) -> list[AgentTool]:
    """``fatal_tool`` records a lost session in ``state`` as a wrapper does (D-D); ``second_tool`` only records."""

    @tool(name=FATAL_TOOL)
    def fatal_tool() -> str:
        """Record a fatal error."""
        ran.append(FATAL_TOOL)
        state.fatal_error = MCPConnectionError("the substrate transport died")
        return "fatal error recorded"

    @tool(name=SECOND_TOOL)
    def second_tool() -> str:
        """Do the next piece of work."""
        ran.append(SECOND_TOOL)
        return "second tool ran"

    return [fatal_tool, second_tool]


#: The two script shapes. Each ends with the turns a supervisor that carried on would consume, so "the model is not
#: called again" shows as ``turns_consumed == 1`` and never as an exhausted script.
_NEXT_TURN: Final[str] = "next-turn"
_SAME_TURN: Final[str] = "same-turn"


def _script(shape: str) -> list[list[dict[str, Any]]]:
    """``next-turn``: the fatal tool, then the second tool in the next turn. ``same-turn``: both in one turn."""
    if shape == _NEXT_TURN:
        return [tool_use_turn(FATAL_TOOL, {}), tool_use_turn(SECOND_TOOL, {}), text_turn("done")]
    return [tool_uses_turn((FATAL_TOOL, {}), (SECOND_TOOL, {})), text_turn("done")]


def _run_spike(state: RunState, shape: str, hooks: list[HookProvider]) -> _Outcome:
    """Invoke a scripted supervisor, built as D-H builds the real one, and record what happened."""
    ran: list[str] = []
    model = ScriptedModel(_script(shape))
    agent = Agent(
        model=model,
        tools=_spike_tools(state, ran),
        hooks=hooks,
        callback_handler=None,
        tool_executor=SequentialToolExecutor(),
    )
    result: AgentResult | None = None
    raised: Exception | None = None
    try:
        result = agent("Run.")
    except Exception as exc:  # recorded, so an assertion can say which exception escaped
        raised = exc
    return _Outcome(result, raised, model.turns_consumed, ran, list(agent.messages))


def _assert_stopped_after_the_fatal_tool(outcome: _Outcome, state: RunState) -> None:
    """The plan's four assertions, plus how control returns: normally, with ``stop_reason="cancelled"``."""
    assert outcome.ran == [FATAL_TOOL], "the second tool never runs"
    assert outcome.turns_consumed == 1, "the model is not called again after the fatal tool"
    assert outcome.raised is None, "control returns to the caller without an unhandled exception"
    assert outcome.result is not None and outcome.result.stop_reason == "cancelled"
    assert isinstance(state.fatal_error, MCPConnectionError), "state.fatal_error is still set"


class _CancelOnFatal(HookProvider):
    """Candidate 1: an ``AfterToolCallEvent`` hook calling ``Agent.cancel()`` once the fatal slot is set."""

    def __init__(self, state: RunState) -> None:
        self._state = state

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(AfterToolCallEvent, self._after_tool_call)

    def _after_tool_call(self, event: AfterToolCallEvent) -> None:
        if self._state.fatal_error is not None:
            event.agent.cancel()


@pytest.mark.parametrize("shape", [_NEXT_TURN, _SAME_TURN])
def test_without_a_stop_hook_the_supervisor_runs_on_after_a_fatal_tool(state: RunState, shape: str) -> None:
    """The control: with nothing to stop it, the second tool runs and the script is played to its end."""
    outcome = _run_spike(state, shape, hooks=[])

    assert outcome.ran == [FATAL_TOOL, SECOND_TOOL]
    assert outcome.turns_consumed == len(_script(shape))
    assert outcome.result is not None and outcome.result.stop_reason == "end_turn"


@pytest.mark.parametrize("shape", [_NEXT_TURN, _SAME_TURN])
def test_candidate_1_an_after_tool_call_hook_calling_cancel_stops_the_supervisor(
    state: RunState, shape: str
) -> None:
    """D-D.1: candidate 1 passes every assertion, whether the second tool is asked for in the same turn or the next."""
    _assert_stopped_after_the_fatal_tool(_run_spike(state, shape, hooks=[_CancelOnFatal(state)]), state)


@pytest.mark.parametrize("shape", [_NEXT_TURN, _SAME_TURN])
def test_the_production_fatal_stop_hook_passes_every_spike_assertion(state: RunState, shape: str) -> None:
    """``src.hooks.FatalStopHook`` is candidate 1, and stops the same scripts the same way."""
    _assert_stopped_after_the_fatal_tool(_run_spike(state, shape, hooks=[FatalStopHook(state)]), state)


def test_candidate_1_answers_a_same_turn_tool_use_with_a_cancelled_result_and_no_call(state: RunState) -> None:
    """The second tool of the turn is not run but answered, so the conversation stays well formed for the caller."""
    outcome = _run_spike(state, _SAME_TURN, hooks=[_CancelOnFatal(state)])

    results = [block["toolResult"] for block in outcome.messages[-1]["content"]]
    assert outcome.messages[-1]["role"] == "user"
    assert [(r["toolUseId"], r["status"]) for r in results] == [
        (f"{FATAL_TOOL}-1", "success"),
        (f"{SECOND_TOOL}-2", "error"),
    ]
    assert results[1]["content"] == [{"text": "Tool execution cancelled"}]


# ---------------------------------------------------------------------------
# Part (b): AfterModelCallEvent (D-I "Model HTTP call", "Supervisor turn completed")
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _ModelCallSeen:
    """One ``AfterModelCallEvent`` as a hook sees it, read inside the callback."""

    stop_reason: str | None
    usage: dict[str, Any] | None
    exception: Exception | None
    metrics_total_tokens: int


class _ModelCallRecorder(HookProvider):
    """Records every ``AfterModelCallEvent``, and what ``event_loop_metrics`` held at that moment."""

    def __init__(self) -> None:
        self.seen: list[_ModelCallSeen] = []

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(AfterModelCallEvent, self._after_model_call)

    def _after_model_call(self, event: AfterModelCallEvent) -> None:
        response = event.stop_response
        self.seen.append(
            _ModelCallSeen(
                stop_reason=None if response is None else response.stop_reason,
                usage=None if response is None else dict(response.message["metadata"]["usage"]),
                exception=event.exception,
                metrics_total_tokens=event.agent.event_loop_metrics.accumulated_usage["totalTokens"],
            )
        )


@tool(name="noop")
def _noop() -> str:
    """Do nothing."""
    return "ok"


def _two_counted_calls() -> list[list[dict[str, Any]]]:
    """A tool turn of 11 + 7 tokens, then a text turn of 3 + 2."""
    return [
        tool_use_turn("noop", {}, input_tokens=11, output_tokens=7),
        text_turn("done", input_tokens=3, output_tokens=2),
    ]


def _model_call_run(turns: list[Any]) -> tuple[_ModelCallRecorder, ScriptedModel, Agent]:
    recorder = _ModelCallRecorder()
    model = ScriptedModel(turns)
    agent = Agent(model=model, tools=[_noop], hooks=[recorder], callback_handler=None)
    return recorder, model, agent


def test_after_model_call_fires_once_per_model_call_with_its_stop_reason() -> None:
    """One event per round trip, in order, each with that response's stop reason."""
    recorder, model, agent = _model_call_run([tool_use_turn("noop", {}), text_turn("done")])
    agent("Run.")

    assert len(recorder.seen) == model.turns_consumed == 2
    assert [seen.stop_reason for seen in recorder.seen] == ["tool_use", "end_turn"]


def test_after_model_call_carries_the_calls_token_usage_on_its_message_metadata() -> None:
    """D-I's token source: ``stop_response.message["metadata"]["usage"]``, each call's own, set before the hook."""
    recorder, _, agent = _model_call_run(_two_counted_calls())
    agent("Run.")

    assert [seen.usage for seen in recorder.seen] == [
        {"inputTokens": 11, "outputTokens": 7, "totalTokens": 18},
        {"inputTokens": 3, "outputTokens": 2, "totalTokens": 5},
    ]


def test_event_loop_metrics_lag_one_call_behind_the_after_model_call_event() -> None:
    """Why usage is read from the event: inside the hook, ``event_loop_metrics`` does not yet hold the call."""
    recorder, _, agent = _model_call_run(_two_counted_calls())
    agent("Run.")

    assert [seen.metrics_total_tokens for seen in recorder.seen] == [0, 18]
    assert agent.event_loop_metrics.accumulated_usage["totalTokens"] == 23


def test_after_model_call_on_a_failed_call_has_no_stop_response_and_carries_the_exception() -> None:
    """A provider failure: one event, ``stop_response`` ``None``, the exception on the event, then raised as is."""
    boom = RuntimeError("boom")
    recorder, _, agent = _model_call_run([boom])

    with pytest.raises(RuntimeError, match="boom"):
        agent("Run.")
    assert recorder.seen == [_ModelCallSeen(stop_reason=None, usage=None, exception=boom, metrics_total_tokens=0)]


# ---------------------------------------------------------------------------
# Part (b): BeforeToolCallEvent and AfterToolCallEvent (D-I "Tool call started / completed")
# ---------------------------------------------------------------------------

#: ``scout_tool``'s arguments as a Supervisor sends them (§6.4).
_SCOUT_CALL_ARGS: Final[dict[str, Any]] = {
    "date_from": SCOPE_DATE_FROM,
    "date_to": SCOPE_DATE_TO,
    "sources": ["INAIL"],
    "sector_constraints": [],
    "max_drafts": None,
}


@dataclass(frozen=True)
class _ToolCallSeen:
    """One tool-call event: which agent fired it, before or after, the tool, and the after-event's outcome."""

    agent: Agent
    phase: str
    tool_name: str
    duration: float | None = None
    status: str | None = None


class _ToolCallRecorder(HookProvider):
    """Records every ``BeforeToolCallEvent`` and ``AfterToolCallEvent`` of each agent it is registered on."""

    def __init__(self) -> None:
        self.seen: list[_ToolCallSeen] = []

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeToolCallEvent, self._before)
        registry.add_callback(AfterToolCallEvent, self._after)

    def _before(self, event: BeforeToolCallEvent) -> None:
        self.seen.append(_ToolCallSeen(event.agent, "before", event.tool_use["name"]))

    def _after(self, event: AfterToolCallEvent) -> None:
        self.seen.append(
            _ToolCallSeen(event.agent, "after", event.tool_use["name"], event.duration, event.result["status"])
        )

    def of(self, agent: Agent, *, is_agent: bool = True) -> list[tuple[str, str]]:
        """``(phase, tool)`` for the events ``agent`` fired, or, with ``is_agent=False``, every other agent fired."""
        return [(seen.phase, seen.tool_name) for seen in self.seen if (seen.agent is agent) is is_agent]


def test_tool_call_events_fire_for_the_supervisors_tools_and_for_the_mcp_tools_inside_a_sub_agent(
    state: RunState,
) -> None:
    """D-I: passed to ``build_tools``, the hook sees the Scout's substrate call; on the Supervisor, ``scout_tool``."""
    recorder = _ToolCallRecorder()
    scout = ScriptedModel(
        [
            tool_use_turn("list_regulatory_updates", {"source": "INAIL"}),
            tool_use_turn("ScoutReport", scout_report_args("doc-a")),
        ]
    )
    tools = build_tools(
        state,
        client=offline_client(OfflineSubstrateSession()),
        models=SubAgentModels(scout=scout, writer=ScriptedModel([]), qa_legal=ScriptedModel([])),
        efforts=SubAgentEfforts(),
        hooks=(recorder,),
    )
    supervisor = Agent(
        model=ScriptedModel([tool_use_turn("scout_tool", _SCOUT_CALL_ARGS), text_turn("done")]),
        tools=tools,
        hooks=[recorder],
        callback_handler=None,
        tool_executor=SequentialToolExecutor(),
    )

    supervisor("Run.")

    assert recorder.of(supervisor) == [("before", "scout_tool"), ("after", "scout_tool")]
    assert recorder.of(supervisor, is_agent=False) == [
        ("before", "list_regulatory_updates"),
        ("after", "list_regulatory_updates"),
        ("before", "ScoutReport"),
        ("after", "ScoutReport"),
    ]
    after = [seen for seen in recorder.seen if seen.phase == "after"]
    assert all(isinstance(seen.duration, float) and seen.status == "success" for seen in after)
    assert "doc-a" in state.documents


# ---------------------------------------------------------------------------
# Part (b): the tool executors (D-H)
# ---------------------------------------------------------------------------

#: How long the first tool holds its turn, so a second tool started alongside it would log its start first.
_HOLD_SECONDS: Final[float] = 0.2


def _paired_tools(order: list[str], barrier: threading.Barrier | None = None) -> list[AgentTool]:
    """Tools ``a`` and ``b``, each logging ``+`` on entry and ``-`` on exit; with ``barrier``, both wait at it."""

    def _work(name: str) -> str:
        order.append(f"{name}+")
        if barrier is not None:
            barrier.wait()  # raises BrokenBarrierError after its timeout unless the other tool is running too
        elif name == "a":
            time.sleep(_HOLD_SECONDS)
        order.append(f"{name}-")
        return name

    @tool(name="a")
    def tool_a() -> str:
        """Tool a."""
        return _work("a")

    @tool(name="b")
    def tool_b() -> str:
        """Tool b."""
        return _work("b")

    return [tool_a, tool_b]


def _run_paired(executor: SequentialToolExecutor | None, tools: list[AgentTool]) -> Agent:
    model = ScriptedModel([tool_uses_turn(("a", {}), ("b", {})), text_turn("done")])
    agent = Agent(model=model, tools=tools, callback_handler=None, tool_executor=executor)
    agent("Run.")
    return agent


def _tool_statuses(agent: Agent) -> list[str]:
    return [block["toolResult"]["status"] for block in agent.messages[2]["content"]]


def test_sequential_tool_executor_runs_one_turns_tools_one_after_another() -> None:
    """D-H's executor, at ``strands.tools.executors``: ``b`` starts only once ``a``, which holds its turn, has ended."""
    order: list[str] = []
    agent = _run_paired(SequentialToolExecutor(), _paired_tools(order))

    assert order == ["a+", "a-", "b+", "b-"]
    assert _tool_statuses(agent) == ["success", "success"]


def test_the_default_executor_is_concurrent_and_runs_one_turns_tools_together() -> None:
    """Strands' default, which the sub-agents keep: both tools are inside at once, or neither passes the barrier."""
    order: list[str] = []
    agent = _run_paired(None, _paired_tools(order, threading.Barrier(2, timeout=5)))

    assert isinstance(agent.tool_executor, ConcurrentToolExecutor)
    assert sorted(order[:2]) == ["a+", "b+"]
    assert _tool_statuses(agent) == ["success", "success"]
