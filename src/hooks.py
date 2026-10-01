"""Strands hooks: per-agent logging, and the Supervisor's fatal stop (SPECIFICATIONS.md D-I, D-D, D-D.1).

:class:`FatalStopHook` is the stop the Iteration 12 spike chose (D-D.1, candidate 1): registered on the Supervisor,
built with ``SequentialToolExecutor``, it calls ``Agent.cancel()`` once a tool call completes with
``RunState.fatal_error`` set. No later tool runs, in that model turn or the next; the model is not called again;
and the Supervisor returns normally with ``stop_reason="cancelled"``. The hook only stops: it never selects, skips
or rewrites a tool, and it never touches ``fatal_error``, which the composition root maps to ``MCP_ERROR``.

:class:`LoggingHooks` observes one agent and writes D-I's hook events: "Model HTTP call", "Tool call started /
completed" and, on the Supervisor only, "Supervisor turn completed". It only reads events: it never sets ``retry``,
``cancel_tool`` or any other writable field, so a sub-agent built with it behaves exactly as one built without it.

Token counts are read from each call's own response, ``stop_response.message["metadata"]["usage"]``, which the
event loop sets before the hook fires. ``agent.event_loop_metrics`` is never read here: inside the hook it lags one
call behind (``tests/test_unit/test_sdk_contract.py``), and :func:`src.agents.extract_telemetry` is the one reader
of the metrics summary (Rule 6).
"""

import logging
from typing import Any, Final, Literal, TypeAlias

from strands.hooks import AfterModelCallEvent, AfterToolCallEvent, BeforeToolCallEvent, HookProvider, HookRegistry
from strands.types.event_loop import Usage
from strands.types.tools import ToolUse

from .diagnostics import qualified_type_name
from .schemas import ExitCode, RunState

__all__ = ["AgentRole", "FatalStopHook", "LoggingHooks"]

_LOGGER = logging.getLogger("src.hooks")

#: The agent a hook observes: the Supervisor or one of its three sub-agents, named as ``StageTelemetry.stage`` is.
AgentRole: TypeAlias = Literal["supervisor", "scout", "writer", "qa_legal"]

#: The exit code a fatal abort leads to (D-D): a lost substrate session is ``MCP_ERROR``.
_FATAL_EXIT_CODE: Final[ExitCode] = ExitCode.MCP_ERROR

#: The four token figures D-I logs, as ``(log field, Strands usage key)``. Cache reads are a subset of the input.
_TOKEN_FIELDS: Final[tuple[tuple[str, str], ...]] = (
    ("input_tokens", "inputTokens"),
    ("cache_read_tokens", "cacheReadInputTokens"),
    ("output_tokens", "outputTokens"),
    ("total_tokens", "totalTokens"),
)


class LoggingHooks(HookProvider):
    """Write D-I's hook events for one agent; observe only.

    The Supervisor's instance counts its turns, so it is built once per Supervisor. A sub-agent's instance never
    changes after it is built; :func:`src.tools.build_tools` builds one for each sub-agent anyway.

    Args:
        role: The agent the hook is registered on, named on every line it writes.
    """

    def __init__(self, role: AgentRole) -> None:
        self._role: AgentRole = role
        self._turns: int = 0

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        """Register the model-call and tool-call callbacks."""
        registry.add_callback(AfterModelCallEvent, self._after_model_call)
        registry.add_callback(BeforeToolCallEvent, self._before_tool_call)
        registry.add_callback(AfterToolCallEvent, self._after_tool_call)

    def _after_model_call(self, event: AfterModelCallEvent) -> None:
        """Log "Model HTTP call": the agent, then the stop reason and tokens, or the type of the error it raised."""
        response = event.stop_response
        if response is None:
            outcome = "unknown" if event.exception is None else qualified_type_name(event.exception)
            _LOGGER.info("Model HTTP call: agent=%s outcome=error:%s", self._role, outcome)
            return
        tokens = _format_tokens(response.message.get("metadata", {}).get("usage"))
        _LOGGER.info("Model HTTP call: agent=%s stop_reason=%s %s", self._role, response.stop_reason, tokens)
        if self._role == "supervisor":
            self._log_supervisor_turn(response, tokens)

    def _log_supervisor_turn(self, response: AfterModelCallEvent.ModelStopResponse, tokens: str) -> None:
        """Log "Supervisor turn completed" for one successful response; a failed call is not a turn."""
        self._turns += 1
        content = response.message["content"]
        _LOGGER.info(
            "Supervisor turn completed: turn=%d stop_reason=%s tools_requested=[%s] %s text=%r",
            self._turns,
            response.stop_reason,
            ", ".join(block["toolUse"]["name"] for block in content if "toolUse" in block),
            tokens,
            "\n".join(block["text"] for block in content if "text" in block),
        )

    def _before_tool_call(self, event: BeforeToolCallEvent) -> None:
        """Log "Tool call started": the tool and the calling agent, correlated with the call's document."""
        _LOGGER.info(
            "Tool call started: tool=%s agent=%s",
            event.tool_use["name"],
            self._role,
            extra=self._correlation(event.tool_use),
        )

    def _after_tool_call(self, event: AfterToolCallEvent) -> None:
        """Log "Tool call completed": the tool, the agent, the SDK-measured duration and the outcome."""
        _LOGGER.info(
            "Tool call completed: tool=%s agent=%s duration=%s outcome=%s",
            event.tool_use["name"],
            self._role,
            "-" if event.duration is None else f"{event.duration:.3f}s",
            _tool_outcome(event),
            extra=self._correlation(event.tool_use),
        )

    def _correlation(self, tool_use: ToolUse) -> dict[str, str] | None:
        """The ``doc_id`` a Supervisor tool call names, as a log ``extra``; ``None`` to keep the enclosing context.

        A sub-agent's tool calls run inside its wrapper's ``log_context``, which already carries the document. The
        Supervisor's own tool events fire before and after that context, so the document is read from the call's
        ``doc_id`` argument instead, the one every per-document Supervisor tool takes (§6.4). A sub-agent's
        arguments are never read: its ``doc_id`` arguments name substrate documents, not the run's.
        """
        if self._role != "supervisor":
            return None
        arguments = tool_use.get("input")
        doc_id = arguments.get("doc_id") if isinstance(arguments, dict) else None
        return {"doc_id": doc_id} if isinstance(doc_id, str) else None


class FatalStopHook(HookProvider):
    """Stop the Supervisor once a fatal error is recorded (D-D.1); register on the Supervisor only.

    On every ``AfterToolCallEvent`` it reads ``state.fatal_error``, which the tool wrappers set (D-D), never the
    event's exception. Once the slot is set it calls ``Agent.cancel()``, which is idempotent, and logs "Fatal abort
    triggered" the first time only.

    Args:
        state: The run state whose fatal slot is read.
    """

    def __init__(self, state: RunState) -> None:
        self._state = state
        self._logged: bool = False

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        """Register the after-tool-call callback."""
        registry.add_callback(AfterToolCallEvent, self._after_tool_call)

    def _after_tool_call(self, event: AfterToolCallEvent) -> None:
        """Cancel the agent if the fatal slot is set, logging the abort once."""
        fatal = self._state.fatal_error
        if fatal is None:
            return
        if not self._logged:
            self._logged = True
            _LOGGER.error(
                "Fatal abort triggered (D-D): cause=%s tool=%s exit_code=%d (%s)",
                qualified_type_name(fatal),
                event.tool_use["name"],
                _FATAL_EXIT_CODE,
                _FATAL_EXIT_CODE.name,
            )
        event.agent.cancel()


def _tool_outcome(event: AfterToolCallEvent) -> str:
    """The result's status, with the exception's type or the cancel message when there is one; never the result."""
    status = event.result["status"]
    if event.exception is not None:
        return f"{status}:{qualified_type_name(event.exception)}"
    if event.cancel_message is not None:
        return f"{status}:cancelled:{event.cancel_message}"
    return status


def _format_tokens(usage: Usage | None) -> str:
    """Format one call's usage as D-I's four token fields; a figure the provider did not report reads 0."""
    figures = usage or {}
    return " ".join(f"{field}={figures.get(key, 0)}" for field, key in _TOKEN_FIELDS)
