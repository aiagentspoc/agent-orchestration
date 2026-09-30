"""The Supervisor's tools and ``scout_tool`` (IMPLEMENTATION_PLAN.md Iteration 7; SPECIFICATIONS.md D-A, §6.4, §7.1).

Every test is offline and spends zero tokens (P4): each sub-agent is a :class:`ScriptedModel` or a
:class:`FailingModel`, and the substrate is the real ``HSEMockMCPClient`` over an :class:`OfflineSubstrateSession`.
A tool is called directly, as the Supervisor's event loop would call it, and only its returned string is what the
Supervisor would see.
"""

import json
import logging
import re
from datetime import date
from pathlib import Path
from typing import Any, Final

import httpx
import openai
import pytest
from strands import Agent
from strands.hooks import BeforeInvocationEvent, HookProvider, HookRegistry
from strands.tools.decorator import DecoratedFunctionTool
from strands.types.exceptions import MCPClientInitializationError
from strands.types.tools import AgentTool

from src.agents import QA_LEGAL_REASONING_EFFORT, SCOUT_MODEL_ID, SCOUT_REASONING_EFFORT, WRITER_REASONING_EFFORT
from src.logging_setup import CorrelationFilter, configure_logging
from src.mcp_client import HSEMockMCPClient, MCPClientNotConnectedError, MCPConnectionError
from src.schemas import AgentTelemetry, PipelineConfig, PipelineScope, RunContext, RunState, ScoutCandidate, ScoutReport
from src.tools import SubAgentEfforts, SubAgentModels, build_tools
from tests.support.scripted import (
    FORBIDDEN_SUPERVISOR_KEYS,
    SCOPE_DATE_FROM,
    SCOPE_DATE_TO,
    SUBSTRATE_TOOL_NAMES,
    FailingModel,
    OfflineSubstrateSession,
    ScriptedModel,
    json_keys,
    offline_client,
    pipeline_config,
    scout_candidate_args,
    scout_report_args,
    sent_text,
    text_turn,
    tool_use_turn,
)
from tests.test_unit.test_docs_consistency import SUPERVISOR_TOOL_DESCRIPTIONS

#: The logger every ``src.tools`` event is written to (a literal name, as test_logging.py requires).
TOOLS_LOGGER: Final[str] = "src.tools"

#: The run every test works in.
RUN_ID: Final[str] = "run-test-0001"
TODAY: Final[date] = date.fromisoformat(SCOPE_DATE_TO)

#: The five ``scout_tool`` arguments of §6.4, as the Supervisor sends them. Deliberately not ``VALID_SCOPE_ARGS``,
#: which carries the ``context`` that only code adds.
SCOUT_CALL_ARGS: Final[dict[str, Any]] = {
    "date_from": SCOPE_DATE_FROM,
    "date_to": SCOPE_DATE_TO,
    "sources": ["INAIL"],
    "sector_constraints": ["construction"],
    "max_drafts": None,
}

#: Strands' own description of a parameter no docstring or annotation describes. Every Supervisor tool keeps it:
#: §7.1's tool description carries all the guidance, and a parameter description would be new Supervisor-visible text.
_UNDESCRIBED: Final[str] = "Parameter {}"


def _string(name: str) -> dict[str, Any]:
    return {"description": _UNDESCRIBED.format(name), "type": "string"}


def _string_list(name: str) -> dict[str, Any]:
    return {"description": _UNDESCRIBED.format(name), "items": {"type": "string"}, "type": "array"}


#: SPECIFICATIONS.md §6.4, as the input schema each tool presents to the Supervisor. No parameter has a default.
EXPECTED_INPUT_SCHEMAS: Final[dict[str, dict[str, Any]]] = {
    "scout_tool": {
        "properties": {
            "date_from": _string("date_from"),
            "date_to": _string("date_to"),
            "sources": _string_list("sources"),
            "sector_constraints": _string_list("sector_constraints"),
            "max_drafts": {"anyOf": [{"type": "integer"}, {"type": "null"}], "description": "Parameter max_drafts"},
        },
        "required": ["date_from", "date_to", "sources", "sector_constraints", "max_drafts"],
        "type": "object",
    },
    "writer_tool": {
        "properties": {
            "doc_id": _string("doc_id"),
            "revise": {"description": "Parameter revise", "type": "boolean"},
        },
        "required": ["doc_id", "revise"],
        "type": "object",
    },
    "qa_tool": {"properties": {"doc_id": _string("doc_id")}, "required": ["doc_id"], "type": "object"},
    "save_draft": {"properties": {"doc_id": _string("doc_id")}, "required": ["doc_id"], "type": "object"},
}


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


def _run_state(config: PipelineConfig, *, max_drafts: int | None = None) -> RunState:
    """A fresh run: no scope, no documents, nothing recorded."""
    return RunState(
        run_id=RUN_ID,
        config=config,
        context=RunContext(today=TODAY, max_drafts=max_drafts, drafts_saved=0),
    )


@pytest.fixture
def state(tmp_path: Path) -> RunState:
    return _run_state(pipeline_config(tmp_path))


def _assert_supervisor_view(state: RunState, returned: Any) -> None:
    """IMPLEMENTATION_PLAN.md Iteration 7 AC2 and D-F, for one result string a tool returned.

    The string is a ``ToolResult``: exactly ``result``, ``run`` and ``error``. ``run`` is the run's snapshot, a
    ``result`` is a whole ``ScoutReport`` and nothing more, and no forbidden key appears at any depth.
    """
    assert isinstance(returned, str)
    decoded = json.loads(returned)
    assert set(decoded) == {"result", "run", "error"}
    assert decoded["run"] == state.snapshot().model_dump(mode="json")
    if decoded["result"] is not None:
        assert set(decoded["result"]) == {"candidates"}
        assert decoded["result"] == ScoutReport.model_validate(decoded["result"]).model_dump(mode="json")
    assert json_keys(decoded) & FORBIDDEN_SUPERVISOR_KEYS == set()


class _CheckedTool:
    """A built tool whose every returned string is checked by :func:`_assert_supervisor_view` before a test sees it.

    Every call a test in this module makes goes through here, so AC2 and D-F hold for every result in the file.
    """

    def __init__(self, state: RunState, tool_obj: AgentTool) -> None:
        assert isinstance(tool_obj, DecoratedFunctionTool)  # a plain ``@tool`` function, callable directly
        self._state = state
        self.tool_obj = tool_obj
        self.tool_name = tool_obj.tool_name
        self.tool_spec = tool_obj.tool_spec

    def __call__(self, **arguments: Any) -> str:
        returned = self.tool_obj(**arguments)
        _assert_supervisor_view(self._state, returned)
        return returned


def _tools(
    state: RunState,
    *,
    scout: Any = None,
    session: OfflineSubstrateSession | None = None,
    client: HSEMockMCPClient | None = None,
    efforts: SubAgentEfforts | None = None,
    hooks: tuple[Any, ...] = (),
) -> dict[str, _CheckedTool]:
    """Build the four tools over an offline substrate, keyed by name; ``client`` overrides ``session``."""
    models = SubAgentModels(
        scout=scout if scout is not None else ScriptedModel([]),
        writer=ScriptedModel([]),
        qa_legal=ScriptedModel([]),
    )
    tools = build_tools(
        state,
        client=client or offline_client(session if session is not None else OfflineSubstrateSession()),
        models=models,
        efforts=efforts if efforts is not None else SubAgentEfforts(),
        hooks=hooks,
    )
    return {tool_obj.tool_name: _CheckedTool(state, tool_obj) for tool_obj in tools}


# ---------------------------------------------------------------------------
# The four tools the Supervisor sees (§6.4, §7.1)
# ---------------------------------------------------------------------------


def test_build_tools_returns_the_four_supervisor_tools_in_order(state: RunState) -> None:
    """``scout_tool``, ``writer_tool``, ``qa_tool`` and ``save_draft``, and nothing else (D-A)."""
    tools = build_tools(
        state,
        client=offline_client(OfflineSubstrateSession()),
        models=SubAgentModels(scout=ScriptedModel([]), writer=ScriptedModel([]), qa_legal=ScriptedModel([])),
        efforts=SubAgentEfforts(),
    )

    assert [tool_obj.tool_name for tool_obj in tools] == ["scout_tool", "writer_tool", "qa_tool", "save_draft"]


@pytest.mark.parametrize("name", list(EXPECTED_INPUT_SCHEMAS))
def test_each_tool_spec_is_the_specified_name_description_and_input_schema(state: RunState, name: str) -> None:
    """The whole spec the Supervisor model receives: §7.1's description word for word, §6.4's parameters."""
    spec = _tools(state)[name].tool_spec

    assert spec == {
        "name": name,
        "description": SUPERVISOR_TOOL_DESCRIPTIONS[name],
        "inputSchema": {"json": EXPECTED_INPUT_SCHEMAS[name]},
    }


def test_sources_is_a_list_of_plain_strings_so_an_unknown_source_reaches_code(state: RunState) -> None:
    """§6.4: no enum in the schema, so ``invalid_scope`` rather than the SDK's schema check refuses a bad source."""
    sources = _tools(state)["scout_tool"].tool_spec["inputSchema"]["json"]["properties"]["sources"]

    assert sources["items"] == {"type": "string"}


@pytest.mark.parametrize(
    ("name", "arguments", "iteration"),
    [
        ("save_draft", {"doc_id": "doc-a"}, "Iteration 10"),
    ],
)
def test_the_later_tools_are_declared_but_not_yet_built(
    state: RunState, name: str, arguments: dict[str, Any], iteration: str
) -> None:
    """Their contract is final now; their bodies are the named later iteration's."""
    with pytest.raises(NotImplementedError, match=iteration):
        _tools(state)[name](**arguments)


def test_sub_agent_efforts_default_to_the_role_constants() -> None:
    """The compiled-in efforts of ``src.agents`` (D24) until the composition root resolves ``.env`` overrides."""
    assert SubAgentEfforts() == SubAgentEfforts(
        scout=SCOUT_REASONING_EFFORT, writer=WRITER_REASONING_EFFORT, qa_legal=QA_LEGAL_REASONING_EFFORT
    )


# ---------------------------------------------------------------------------
# A successful Scout call (D-A, D-B, §6.5)
# ---------------------------------------------------------------------------


def _scout_turns(*doc_ids: str, input_tokens: int = 10, output_tokens: int = 5) -> list[list[dict[str, Any]]]:
    """One Scout invocation that answers at once with a ``ScoutReport`` covering ``doc_ids``."""
    return [
        tool_use_turn(
            "ScoutReport", scout_report_args(*doc_ids), input_tokens=input_tokens, output_tokens=output_tokens
        )
    ]


def _result(returned: str) -> dict[str, Any]:
    """Decode a tool's return value, which must be the ``for_supervisor()`` JSON string."""
    assert isinstance(returned, str)
    decoded = json.loads(returned)
    assert isinstance(decoded, dict)
    return decoded


def _messages(caplog: pytest.LogCaptureFixture, level: int | None = None) -> list[str]:
    """The ``src.tools`` messages captured, optionally at one level only."""
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == TOOLS_LOGGER and (level is None or record.levelno == level)
    ]


def test_a_successful_call_stores_the_validated_scope_with_its_context(state: RunState) -> None:
    """§6.5: ``scope`` is set by the one successful call, and code filled in ``context`` from the run."""
    _tools(state, scout=ScriptedModel(_scout_turns("doc-a")))["scout_tool"](**SCOUT_CALL_ARGS)

    assert state.scope == PipelineScope.model_validate({**SCOUT_CALL_ARGS, "context": {"today": TODAY}})


def test_the_scout_receives_the_scope_with_the_run_date(state: RunState) -> None:
    """D-G: the Scout's one typed input is the ``PipelineScope``, ``context.today`` included."""
    scout = ScriptedModel(_scout_turns("doc-a"))
    _tools(state, scout=scout)["scout_tool"](**SCOUT_CALL_ARGS)

    turn = sent_text(scout)
    assert f'"today": "{SCOPE_DATE_TO}"' in turn
    assert f'"date_from": "{SCOPE_DATE_FROM}"' in turn


def test_one_document_record_per_candidate_keyed_by_doc_id_in_the_scouts_order(state: RunState) -> None:
    """§6.5: the Scout's order is kept as returned, never re-sorted, even when its scores are not descending."""
    report = {
        "candidates": [
            scout_candidate_args("doc-low", 0.2, "Obblighi minori."),
            scout_candidate_args("doc-high", 0.9, "Obblighi immediati."),
        ]
    }
    scout = ScriptedModel([tool_use_turn("ScoutReport", report)])
    _tools(state, scout=scout)["scout_tool"](**SCOUT_CALL_ARGS)

    assert list(state.documents) == ["doc-low", "doc-high"]
    for doc_id, candidate in zip(state.documents, report["candidates"], strict=True):
        document = state.documents[doc_id]
        assert document.candidate == ScoutCandidate.model_validate(candidate)
        assert document.attempts == []
        assert document.saved is None


def test_a_successful_call_appends_one_scout_ledger_entry(state: RunState) -> None:
    """D-B: stage ``scout``, no document or attempt, the Scout's model ID and the effort it was built at."""
    scout = ScriptedModel(_scout_turns("doc-a", input_tokens=120, output_tokens=30))
    _tools(state, scout=scout, efforts=SubAgentEfforts(scout="low"))["scout_tool"](**SCOUT_CALL_ARGS)

    assert len(state.ledger) == 1
    entry = state.ledger[0]
    assert (entry.stage, entry.doc_id, entry.attempt) == ("scout", None, None)
    assert entry.telemetry.model_id == SCOUT_MODEL_ID  # never the injected model's own config
    assert entry.telemetry.reasoning_effort == "low"
    assert (entry.telemetry.input_tokens, entry.telemetry.output_tokens) == (120, 30)


def test_a_successful_call_returns_the_full_report_and_a_run_snapshot(state: RunState) -> None:
    """§6.4, §7.2: ``ToolResult[ScoutReport].for_supervisor()``: the report whole, the snapshot, no error."""
    scout = ScriptedModel(_scout_turns("doc-a", "doc-b"))
    returned = _result(_tools(state, scout=scout)["scout_tool"](**SCOUT_CALL_ARGS))

    expected_report = ScoutReport.model_validate(scout_report_args("doc-a", "doc-b"))
    assert returned == {
        "result": expected_report.model_dump(mode="json"),
        "run": state.snapshot().model_dump(mode="json"),
        "error": None,
    }


def test_a_successful_call_logs_the_scope_the_invocation_pair_and_the_scout_result(
    state: RunState, caplog: pytest.LogCaptureFixture
) -> None:
    """D-I: "Scope built", "Sub-agent invocation started" and "completed", then "Scout result", all at INFO."""
    caplog.set_level(logging.INFO, logger=TOOLS_LOGGER)
    caplog.handler.addFilter(CorrelationFilter())
    scout = ScriptedModel(_scout_turns("doc-a", "doc-b", input_tokens=40, output_tokens=2))
    _tools(state, scout=scout)["scout_tool"](**SCOUT_CALL_ARGS)

    messages = _messages(caplog, logging.INFO)
    assert [message.split(":")[0] for message in messages] == [
        "Scope built by the Supervisor",
        "Sub-agent invocation started",
        "Sub-agent invocation completed",
        "Scout result",
    ]
    scope_line, started, completed, result_line = messages
    assert SCOPE_DATE_FROM in scope_line and "INAIL" in scope_line and "construction" in scope_line
    for line in (started, completed):
        assert "role=scout" in line and f"model={SCOUT_MODEL_ID}" in line and "effort=None" in line
    # doc_id and attempt are correlation fields, read from the log context: the Scout works on no document.
    tool_records = [record for record in caplog.records if record.name == TOOLS_LOGGER]
    fields = {tuple(getattr(record, name) for name in ("run_id", "doc_id", "attempt")) for record in tool_records}
    assert fields == {(RUN_ID, "-", "-")}
    assert "tokens=42" in completed and "duration=" in completed
    assert "tools=[]" in completed
    assert "2 candidate(s)" in result_line and "doc-a (0.9)" in result_line and "doc-b (0.8)" in result_line


def test_the_completed_line_names_the_substrate_tools_the_scout_used(
    state: RunState, caplog: pytest.LogCaptureFixture
) -> None:
    """D-I: "substrate tools used", with their call counts, read from the call's telemetry."""
    caplog.set_level(logging.INFO, logger=TOOLS_LOGGER)
    scout = ScriptedModel([tool_use_turn("list_regulatory_updates", {"source": "INAIL"}), *_scout_turns("doc-a")])
    _tools(state, scout=scout)["scout_tool"](**SCOUT_CALL_ARGS)

    completed = next(m for m in _messages(caplog) if m.startswith("Sub-agent invocation completed"))
    assert "tools=[list_regulatory_updates x1]" in completed


def test_zero_candidates_is_a_successful_run_logged_as_no_qualifying_updates(
    state: RunState, caplog: pytest.LogCaptureFixture
) -> None:
    """§6.5: an empty report still sets ``scope``, so the Scout cannot run again; there is nothing to store."""
    caplog.set_level(logging.INFO, logger=TOOLS_LOGGER)
    returned = _result(_tools(state, scout=ScriptedModel(_scout_turns()))["scout_tool"](**SCOUT_CALL_ARGS))

    assert state.scope is not None
    assert state.documents == {}
    assert returned["result"] == {"candidates": []}
    assert any(m.startswith("Scout result") and "No qualifying updates" in m for m in _messages(caplog))


def test_the_scout_is_built_with_all_five_substrate_tools(state: RunState) -> None:
    """P1: no ``tool_names`` narrowing; the tools list every substrate tool, unfiltered."""
    session = OfflineSubstrateSession()
    scout = ScriptedModel(_scout_turns("doc-a"))
    _tools(state, scout=scout, session=session)["scout_tool"](**SCOUT_CALL_ARGS)

    assert session.tool_filters_seen == [None]
    assert {spec["name"] for spec in scout.received_tool_specs[0] or []} >= set(SUBSTRATE_TOOL_NAMES)


class _RecordingHooks(HookProvider):
    """Counts every sub-agent invocation it is registered on."""

    def __init__(self) -> None:
        self.invocations: int = 0

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeInvocationEvent, self._count)

    def _count(self, event: BeforeInvocationEvent) -> None:
        self.invocations += 1


def test_the_hooks_given_to_build_tools_reach_the_scout(state: RunState) -> None:
    """Iteration 12's seam: every sub-agent a tool builds registers the hooks ``build_tools`` was given."""
    hooks = _RecordingHooks()
    _tools(state, scout=ScriptedModel(_scout_turns("doc-a")), hooks=(hooks,))["scout_tool"](**SCOUT_CALL_ARGS)

    assert hooks.invocations == 1


# ---------------------------------------------------------------------------
# Refusals: scout_already_run and invalid_scope (D-C, §7.3)
# ---------------------------------------------------------------------------


def _assert_refused(state: RunState, returned: str, guardrail: str, caplog: pytest.LogCaptureFixture) -> None:
    """A complete violation (Gate 4): stored, logged at WARNING with its fields, and returned with no result."""
    violation = state.violations[-1]
    assert violation.guardrail == guardrail
    assert (violation.tool_name, violation.doc_id) == ("scout_tool", None)
    assert _result(returned) == {
        "result": None,
        "run": state.snapshot().model_dump(mode="json"),
        "error": violation.model_dump(mode="json"),
    }
    warnings = [m for m in _messages(caplog, logging.WARNING) if m.startswith("Guardrail violation")]
    assert len(warnings) == 1
    assert f"guardrail={guardrail}" in warnings[0] and "tool=scout_tool" in warnings[0]
    assert "doc_id=None" in warnings[0] and violation.message in warnings[0]


def test_a_second_call_after_a_successful_one_is_refused_as_scout_already_run(
    state: RunState, caplog: pytest.LogCaptureFixture
) -> None:
    """The Scout runs once: the refusal comes before any build, so no agent, token or ledger entry is spent."""
    caplog.set_level(logging.INFO, logger=TOOLS_LOGGER)
    session = OfflineSubstrateSession()
    scout = ScriptedModel(_scout_turns("doc-a"))
    scout_tool = _tools(state, scout=scout, session=session)["scout_tool"]
    scout_tool(**SCOUT_CALL_ARGS)
    documents_before = dict(state.documents)

    returned = scout_tool(**{**SCOUT_CALL_ARGS, "sources": ["EUR_LEX"]})

    _assert_refused(state, returned, "scout_already_run", caplog)
    assert (len(session.tool_filters_seen), scout.turns_consumed, len(state.ledger)) == (1, 1, 1)
    assert state.documents == documents_before
    assert state.scope is not None and state.scope.sources == ["INAIL"]


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"date_from": "20260622"}, id="basic-form-date"),
        pytest.param({"date_from": "2026-09-23"}, id="window-runs-backwards"),
        pytest.param({"sources": ["INAIL", "OSHA"]}, id="unknown-source"),
        pytest.param({"max_drafts": "three"}, id="validation-error"),
    ],
)
def test_an_invalid_scope_is_refused_before_any_build_and_does_not_count_as_a_run(
    state: RunState, caplog: pytest.LogCaptureFixture, overrides: dict[str, Any]
) -> None:
    """``invalid_scope`` leaves ``scope`` unset, builds no Scout and writes no ledger entry."""
    caplog.set_level(logging.INFO, logger=TOOLS_LOGGER)
    session = OfflineSubstrateSession()
    scout_tool = _tools(state, session=session)["scout_tool"]

    returned = scout_tool(**{**SCOUT_CALL_ARGS, **overrides})

    _assert_refused(state, returned, "invalid_scope", caplog)
    assert state.scope is None
    assert (session.tool_filters_seen, state.ledger, state.documents) == ([], [], {})
    assert not any(m.startswith(("Scope built", "Sub-agent")) for m in _messages(caplog))


def test_a_corrected_scope_after_an_invalid_one_runs_the_scout(state: RunState) -> None:
    """D-C: an invalid scope does not count, so the Supervisor can correct it and call again."""
    scout_tool = _tools(state, scout=ScriptedModel(_scout_turns("doc-a")))["scout_tool"]
    scout_tool(**{**SCOUT_CALL_ARGS, "sources": ["OSHA"]})

    returned = _result(scout_tool(**SCOUT_CALL_ARGS))

    assert returned["error"] is None
    assert [v.guardrail for v in state.violations] == ["invalid_scope"]
    assert list(state.documents) == ["doc-a"]


# ---------------------------------------------------------------------------
# Recoverable failures: an ordinary exception at build or during the call (§6.7, D-I)
# ---------------------------------------------------------------------------

#: The provider's own words for a rate limit. They belong in the ``FailureRecord`` and never in the one-line error.
_RATE_LIMIT_MESSAGE: Final[str] = "Rate limit reached for gpt-5-mini; retry after 20 seconds"


def _rate_limit_error() -> openai.RateLimitError:
    """A genuine ``openai.RateLimitError`` on a real 429 response, as test_diagnostics.py builds one."""
    request = httpx.Request("POST", "https://fast.example.invalid/openai/v1/chat/completions")
    body = {"message": _RATE_LIMIT_MESSAGE, "type": "requests", "code": "rate_limit_exceeded", "param": None}
    response = httpx.Response(429, request=request, headers={"x-request-id": "req_scout_1"}, json={"error": body})
    return openai.RateLimitError(_RATE_LIMIT_MESSAGE, response=response, body=body)


def _recoverable_failure(case: str) -> tuple[Any, OfflineSubstrateSession, str, str]:
    """``(scout model, session, root exception type, root message)`` for one way an ordinary failure arises."""
    if case == "build":
        return ScriptedModel([]), OfflineSubstrateSession(fail_listing_with=RuntimeError("listing broke")), (
            "builtins.RuntimeError"
        ), "listing broke"
    if case == "first-turn":
        return ScriptedModel([RuntimeError("model broke")]), OfflineSubstrateSession(), "builtins.RuntimeError", (
            "model broke"
        )
    if case == "after-a-tool-cycle":
        scout = ScriptedModel([tool_use_turn("list_regulatory_updates", {"source": "INAIL"}), RuntimeError("late")])
        return scout, OfflineSubstrateSession(), "builtins.RuntimeError", "late"
    assert case == "provider-error"
    return FailingModel(_rate_limit_error()), OfflineSubstrateSession(), "openai.RateLimitError", _RATE_LIMIT_MESSAGE


RECOVERABLE_CASES: Final[tuple[str, ...]] = ("build", "first-turn", "after-a-tool-cycle", "provider-error")


@pytest.mark.parametrize("case", RECOVERABLE_CASES)
def test_an_ordinary_failure_records_a_full_scout_failure_record(state: RunState, case: str) -> None:
    """§6.7, D22: stage ``scout``, no document or attempt, the whole cause chain and the traceback."""
    scout, session, root_type, root_message = _recoverable_failure(case)
    _tools(state, scout=scout, session=session)["scout_tool"](**SCOUT_CALL_ARGS)

    assert len(state.failures) == 1
    failure = state.failures[0]
    assert (failure.stage, failure.doc_id, failure.attempt) == ("scout", None, None)
    assert failure.remote is not None
    assert failure.remote.cause_chain[0].startswith(failure.error_type)
    assert failure.remote.cause_chain[-1] == f"{root_type}: {root_message}"
    assert failure.traceback is not None and root_message in failure.traceback
    if case == "after-a-tool-cycle":
        assert failure.error_type == "strands.types.exceptions.EventLoopException"
    if case == "provider-error":
        assert (failure.remote.status_code, failure.remote.request_id) == (429, "req_scout_1")


@pytest.mark.parametrize("case", RECOVERABLE_CASES)
def test_an_ordinary_failure_returns_a_one_line_error_without_the_exceptions_text(state: RunState, case: str) -> None:
    """§6.4: ``result`` is empty and ``error`` is one line: the failure's types, never its message or traceback."""
    scout, session, root_type, root_message = _recoverable_failure(case)
    returned = _result(_tools(state, scout=scout, session=session)["scout_tool"](**SCOUT_CALL_ARGS))

    assert set(returned) == {"result", "run", "error"}
    assert returned["result"] is None
    assert returned["run"] == state.snapshot().model_dump(mode="json")
    error = returned["error"]
    assert isinstance(error, str) and error.startswith("scout_tool failed: ")
    assert root_type in error
    assert "\n" not in error and "Traceback" not in error and root_message not in error
    if case == "provider-error":
        assert "429" in error


@pytest.mark.parametrize("case", RECOVERABLE_CASES)
def test_an_ordinary_failure_is_logged_as_a_recoverable_tool_failure_closing_the_started_line(
    state: RunState, caplog: pytest.LogCaptureFixture, case: str
) -> None:
    """D-I: WARNING with the tool, document, attempt and full detail; the "started" line is closed exactly once."""
    caplog.set_level(logging.INFO, logger=TOOLS_LOGGER)
    scout, session, _, root_message = _recoverable_failure(case)
    _tools(state, scout=scout, session=session)["scout_tool"](**SCOUT_CALL_ARGS)

    events = [m.split(":")[0] for m in _messages(caplog) if m.startswith(("Sub-agent", "Recoverable", "MCP"))]
    assert events == ["Sub-agent invocation started", "Recoverable tool failure returned to the Supervisor"]
    record = next(r for r in caplog.records if r.getMessage().startswith("Recoverable tool failure"))
    assert record.levelno == logging.WARNING
    assert "tool=scout_tool" in record.getMessage()
    assert "doc_id=None" in record.getMessage() and "attempt=None" in record.getMessage()
    assert record.exc_info is not None and root_message in caplog.text
    assert not any(m.startswith("Scout result") for m in _messages(caplog))


@pytest.mark.parametrize("case", RECOVERABLE_CASES)
def test_an_ordinary_failure_leaves_the_scope_unset_and_the_run_alive(state: RunState, case: str) -> None:
    """The Scout has not succeeded: no scope, no documents, and nothing fatal."""
    scout, session, _, _ = _recoverable_failure(case)
    _tools(state, scout=scout, session=session)["scout_tool"](**SCOUT_CALL_ARGS)

    assert (state.scope, state.documents, state.fatal_error) == (None, {}, None)


def test_a_retry_after_a_failed_call_runs_a_fresh_scout_with_all_five_tools(state: RunState) -> None:
    """A failed call is not a run, so the retry is allowed; it builds a new agent, unfiltered again (P1, D-G)."""
    session = OfflineSubstrateSession()
    scout = ScriptedModel([RuntimeError("model broke"), *_scout_turns("doc-a")])
    scout_tool = _tools(state, scout=scout, session=session)["scout_tool"]

    first = _result(scout_tool(**SCOUT_CALL_ARGS))
    second = _result(scout_tool(**SCOUT_CALL_ARGS))

    assert first["error"] is not None and second["error"] is None
    assert session.tool_filters_seen == [None, None]
    assert len(scout.received_messages[1]) == 1  # the retry's agent starts from an empty conversation
    assert list(state.documents) == ["doc-a"]


# ---------------------------------------------------------------------------
# Fatal failures: the substrate session is lost (D-D, §6.7, D-I)
# ---------------------------------------------------------------------------


def _fatal_failure(case: str) -> tuple[Any, HSEMockMCPClient, type[Exception]]:
    """``(scout model, client, fatal type)`` for one way the substrate session is lost around a Scout call."""
    if case == "build-transport-died":
        session = OfflineSubstrateSession(fail_listing_with=MCPClientInitializationError("transport gone"))
        return ScriptedModel([]), offline_client(session), MCPConnectionError
    if case == "build-not-connected":
        client = offline_client(OfflineSubstrateSession())
        client._connected = False
        return ScriptedModel([]), client, MCPClientNotConnectedError
    if case == "first-turn":
        return ScriptedModel([MCPConnectionError("died")]), offline_client(OfflineSubstrateSession()), (
            MCPConnectionError
        )
    assert case == "after-a-tool-cycle"
    scout = ScriptedModel([tool_use_turn("list_regulatory_updates", {"source": "INAIL"}), MCPConnectionError("late")])
    return scout, offline_client(OfflineSubstrateSession()), MCPConnectionError


FATAL_CASES: Final[tuple[str, ...]] = (
    "build-transport-died",
    "build-not-connected",
    "first-turn",
    "after-a-tool-cycle",
)


@pytest.mark.parametrize("case", FATAL_CASES)
def test_a_lost_session_sets_the_fatal_slot_to_the_mcp_exception_itself(state: RunState, case: str) -> None:
    """D-D: the slot holds the MCP exception found in the chain, even when Strands wrapped it."""
    scout, client, fatal_type = _fatal_failure(case)
    _tools(state, scout=scout, client=client)["scout_tool"](**SCOUT_CALL_ARGS)

    assert type(state.fatal_error) is fatal_type
    assert state.scope is None and state.documents == {}


@pytest.mark.parametrize("case", FATAL_CASES)
def test_a_lost_session_records_one_mcp_session_failure(state: RunState, case: str) -> None:
    """§6.7: stage ``mcp_session``, with the whole chain; it is not also recorded as a Scout failure."""
    scout, client, fatal_type = _fatal_failure(case)
    _tools(state, scout=scout, client=client)["scout_tool"](**SCOUT_CALL_ARGS)

    assert [(f.stage, f.doc_id, f.attempt) for f in state.failures] == [("mcp_session", None, None)]
    failure = state.failures[0]
    assert failure.remote is not None
    assert any(link.startswith(f"src.mcp_client.{fatal_type.__name__}") for link in failure.remote.cause_chain)
    assert failure.traceback is not None and fatal_type.__name__ in failure.traceback


@pytest.mark.parametrize("case", FATAL_CASES)
def test_a_lost_session_is_logged_at_error_with_the_server_and_its_launch_command(
    state: RunState, caplog: pytest.LogCaptureFixture, case: str
) -> None:
    """D-I: ERROR with the server directory, the launch command and the full chain; it closes the started line."""
    caplog.set_level(logging.INFO, logger=TOOLS_LOGGER)
    scout, client, fatal_type = _fatal_failure(case)
    _tools(state, scout=scout, client=client)["scout_tool"](**SCOUT_CALL_ARGS)

    events = [m.split(":")[0] for m in _messages(caplog) if m.startswith(("Sub-agent", "Recoverable", "MCP"))]
    assert events == ["Sub-agent invocation started", "MCP session failed to open, or died mid-run"]
    record = next(r for r in caplog.records if r.getMessage().startswith("MCP session failed"))
    assert record.levelno == logging.ERROR
    assert f"server_dir={client.server_dir}" in record.getMessage()
    assert "uv run --quiet --directory <server_dir> fastmcp run server.py" in record.getMessage()
    assert "tool=scout_tool" in record.getMessage()
    assert record.exc_info is not None and fatal_type.__name__ in caplog.text


@pytest.mark.parametrize("case", FATAL_CASES)
def test_a_lost_session_returns_an_error_result_to_the_supervisor(state: RunState, case: str) -> None:
    """Iteration 7 returns the error; Iteration 12's hook stops the Supervisor once the slot is set."""
    scout, client, fatal_type = _fatal_failure(case)
    returned = _result(_tools(state, scout=scout, client=client)["scout_tool"](**SCOUT_CALL_ARGS))

    assert returned["result"] is None and returned["run"] == state.snapshot().model_dump(mode="json")
    error = returned["error"]
    assert isinstance(error, str) and error.startswith("scout_tool failed: ") and "\n" not in error
    assert f"src.mcp_client.{fatal_type.__name__}" in error


def test_a_second_fatal_failure_keeps_the_first_in_the_slot(state: RunState) -> None:
    """The first lost session is the cause of the run's end; a later one is recorded, not promoted."""
    scout = ScriptedModel([MCPConnectionError("first"), MCPConnectionError("second")])
    scout_tool = _tools(state, scout=scout)["scout_tool"]

    scout_tool(**SCOUT_CALL_ARGS)
    first = state.fatal_error
    scout_tool(**SCOUT_CALL_ARGS)

    assert str(first) == "first" and state.fatal_error is first
    assert [f.stage for f in state.failures] == ["mcp_session", "mcp_session"]


def test_an_interrupt_is_never_caught_so_it_stops_the_process_and_leaves_no_record(state: RunState) -> None:
    """Only ``Exception`` is caught: a ``KeyboardInterrupt`` at build propagates out of the tool, recorded nowhere."""
    session = OfflineSubstrateSession(fail_listing_with=KeyboardInterrupt())
    scout_tool = _tools(state, session=session)["scout_tool"]

    with pytest.raises(KeyboardInterrupt):
        scout_tool(**SCOUT_CALL_ARGS)

    assert (state.failures, state.fatal_error, state.ledger) == ([], None, [])


# ---------------------------------------------------------------------------
# A failed call still records its telemetry (D-B, §6.6)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "case"),
    [*(("recoverable", case) for case in RECOVERABLE_CASES), *(("fatal", case) for case in FATAL_CASES)],
)
def test_every_failed_call_appends_one_scout_ledger_entry(state: RunState, kind: str, case: str) -> None:
    """D-B: a ledger entry on failure as well, labelled with the Scout's model ID and the effort it was built at."""
    if kind == "recoverable":
        scout, session, _, _ = _recoverable_failure(case)
        client = offline_client(session)
    else:
        scout, client, _ = _fatal_failure(case)
    _tools(state, scout=scout, client=client, efforts=SubAgentEfforts(scout="low"))["scout_tool"](**SCOUT_CALL_ARGS)

    assert len(state.ledger) == 1
    entry = state.ledger[0]
    assert (entry.stage, entry.doc_id, entry.attempt) == ("scout", None, None)
    assert (entry.telemetry.model_id, entry.telemetry.reasoning_effort) == (SCOUT_MODEL_ID, "low")


@pytest.mark.parametrize("case", ["build", "build-transport-died", "build-not-connected"])
def test_a_call_whose_agent_was_never_built_records_zero_usage(state: RunState, case: str) -> None:
    """Nothing reached a model, so nothing was spent: the entry is there, with every count at zero."""
    if case == "build":
        scout, session, _, _ = _recoverable_failure(case)
        client = offline_client(session)
    else:
        scout, client, _ = _fatal_failure(case)
    _tools(state, scout=scout, client=client)["scout_tool"](**SCOUT_CALL_ARGS)

    assert state.ledger[0].telemetry == AgentTelemetry(model_id=SCOUT_MODEL_ID, reasoning_effort=None)


@pytest.mark.parametrize("failure", [RuntimeError("late"), MCPConnectionError("late")], ids=["recoverable", "fatal"])
def test_a_call_that_raised_after_spending_tokens_keeps_them_and_its_tool_usage(
    state: RunState, failure: Exception
) -> None:
    """§6.6: read from the agent's ``event_loop_metrics``, so the first turn's tokens and tool call are not lost."""
    scout = ScriptedModel(
        [tool_use_turn("list_regulatory_updates", {"source": "INAIL"}, input_tokens=100, output_tokens=7), failure]
    )
    _tools(state, scout=scout)["scout_tool"](**SCOUT_CALL_ARGS)

    telemetry = state.ledger[0].telemetry
    assert (telemetry.input_tokens, telemetry.output_tokens, telemetry.total_tokens) == (100, 7, 107)
    assert [(t.tool_name, t.call_count) for t in telemetry.tool_invocations] == [("list_regulatory_updates", 1)]


# ---------------------------------------------------------------------------
# Correlation: every line a call writes carries run_id (D-I)
# ---------------------------------------------------------------------------

#: The header of a formatted log line; a traceback's continuation lines do not start with a timestamp.
_LOG_LINE_HEADER: Final[re.Pattern[str]] = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} ")


@pytest.mark.usefixtures("restore_logging")
def test_every_line_a_call_writes_to_the_run_log_carries_the_run_id(state: RunState, tmp_path: Path) -> None:
    """The tool sets the run's context itself, so SDK lines are correlated even with no enclosing context."""
    scout = ScriptedModel(
        [
            RuntimeError("model broke"),
            tool_use_turn("list_regulatory_updates", {"source": "INAIL"}),
            *_scout_turns("doc-a"),
        ]
    )
    scout_tool = _tools(state, scout=scout)["scout_tool"]
    log_dir = tmp_path / "logs"
    configure_logging("DEBUG", log_dir)  # after the build, so the file holds only what the calls write

    scout_tool(**SCOUT_CALL_ARGS)  # a recoverable failure
    scout_tool(**SCOUT_CALL_ARGS)  # a success, with a substrate tool call
    scout_tool(**SCOUT_CALL_ARGS)  # a refusal

    for handler in logging.getLogger("src").handlers:
        handler.flush()
    (log_file,) = log_dir.glob("run_*.log")
    headers = [line for line in log_file.read_text(encoding="utf-8").splitlines() if _LOG_LINE_HEADER.match(line)]
    assert headers
    assert [line for line in headers if f"[run_id={RUN_ID} " not in line] == []
    assert any(" strands" in line for line in headers)
    assert any(" src.tools: " in line for line in headers)


# ---------------------------------------------------------------------------
# What reaches the Supervisor: the result's key set (AC2) and no article text (D-F)
# ---------------------------------------------------------------------------


def test_a_success_result_is_the_report_and_the_run_context_and_nothing_more(tmp_path: Path) -> None:
    """AC2 by key set, level by level: ``ToolResult``, then ``ScoutReport``, candidate and ``RunContext``."""
    state = _run_state(pipeline_config(tmp_path, max_drafts=2), max_drafts=2)
    scout_tool = _tools(state, scout=ScriptedModel(_scout_turns("doc-a", "doc-b")))["scout_tool"]
    returned = _result(scout_tool(**SCOUT_CALL_ARGS))

    assert set(returned) == {"result", "run", "error"}
    assert set(returned["result"]) == set(ScoutReport.model_fields)
    for candidate in returned["result"]["candidates"]:
        assert set(candidate) == set(ScoutCandidate.model_fields)
    assert set(returned["run"]) == set(RunContext.model_fields)
    assert returned["run"]["max_drafts"] == 2 and returned["run"]["drafts_saved"] == 0


@pytest.mark.parametrize(
    "decoded",
    [
        {"result": None, "run": None, "error": None, "extra": 1},
        {"result": None, "run": None, "error": {"attempt": {"record": {"draft": {"source_doc_id": "doc-a"}}}}},
        {"result": None, "run": None, "error": {"message": "x", "details": [{"headline": "leak"}]}},
    ],
    ids=["extra-top-level-key", "nested-draft", "headline-inside-error"],
)
def test_the_supervisor_view_check_rejects_an_extra_key_or_a_forbidden_key_at_any_depth(
    state: RunState, decoded: dict[str, Any]
) -> None:
    """The checker every call goes through cannot pass vacuously."""
    decoded = {**decoded, "run": state.snapshot().model_dump(mode="json")}
    with pytest.raises(AssertionError):
        _assert_supervisor_view(state, json.dumps(decoded))


def test_the_supervisor_view_check_does_not_mistake_candidates_for_candidate(state: RunState) -> None:
    """Keys, not substrings: the report's ``candidates`` field is allowed; ``candidate`` alone is not."""
    assert "candidate" not in json_keys({"candidates": [{"update": {"doc_id": "candidate"}}]})
    assert "candidate" in json_keys({"x": [{"candidate": 1}]})


def test_through_a_strands_agent_the_supervisor_receives_exactly_the_returned_string(state: RunState) -> None:
    """Strands passes a ``str`` result through as the tool result's text, so the checked string is what it sees."""
    tools = _tools(state, scout=ScriptedModel(_scout_turns("doc-a")))
    supervisor_model = ScriptedModel([tool_use_turn("scout_tool", SCOUT_CALL_ARGS), text_turn("Done.")])
    supervisor = Agent(model=supervisor_model, tools=[tools["scout_tool"].tool_obj], callback_handler=None)

    supervisor("Analyze INAIL updates on heat stress")

    tool_results = [
        block["toolResult"]
        for message in supervisor_model.received_messages[1]
        for block in message["content"]
        if "toolResult" in block
    ]
    assert len(tool_results) == 1
    (content,) = tool_results[0]["content"]
    _assert_supervisor_view(state, content["text"])
    assert json.loads(content["text"])["result"]["candidates"][0]["update"]["doc_id"] == "doc-a"


def test_a_doc_id_the_scout_returns_twice_keeps_its_first_candidate_and_is_warned(
    state: RunState, caplog: pytest.LogCaptureFixture
) -> None:
    """One document per ``doc_id``: the first, higher-ranked candidate wins; the report itself is returned as is."""
    caplog.set_level(logging.INFO, logger=TOOLS_LOGGER)
    returned = _result(
        _tools(state, scout=ScriptedModel(_scout_turns("doc-a", "doc-b", "doc-a")))["scout_tool"](**SCOUT_CALL_ARGS)
    )

    assert list(state.documents) == ["doc-a", "doc-b"]
    assert state.documents["doc-a"].candidate.newsworthiness_score == 0.9
    assert [c["update"]["doc_id"] for c in returned["result"]["candidates"]] == ["doc-a", "doc-b", "doc-a"]
    warnings = [m for m in _messages(caplog, logging.WARNING) if m.startswith("Duplicate Scout candidate")]
    assert len(warnings) == 1 and "doc_id=doc-a" in warnings[0]


# ---------------------------------------------------------------------------
# Classifying a failure by its whole chain (D-D)
# ---------------------------------------------------------------------------


def _chained(outer: Exception, inner: BaseException, *, suppress: bool = False) -> Exception:
    """``outer`` raised while handling ``inner``, without ``from``: linked by ``__context__`` alone."""
    outer.__context__ = inner
    outer.__suppress_context__ = suppress
    return outer


def test_a_lost_session_found_only_through_the_implicit_context_is_still_fatal(state: RunState) -> None:
    """A wrapper raised inside an ``except`` block without ``from`` cannot hide the lost session."""
    failure = _chained(RuntimeError("wrapper"), MCPConnectionError("hidden"))
    returned = _result(_tools(state, scout=ScriptedModel([failure]))["scout_tool"](**SCOUT_CALL_ARGS))

    assert isinstance(state.fatal_error, MCPConnectionError)
    assert [f.stage for f in state.failures] == ["mcp_session"]
    assert returned["error"] == "scout_tool failed: builtins.RuntimeError <- src.mcp_client.MCPConnectionError"


def test_a_context_suppressed_with_from_none_is_not_followed(state: RunState) -> None:
    """``raise … from None`` declares the earlier exception irrelevant, so it does not make the failure fatal."""
    failure = _chained(RuntimeError("replaced"), MCPConnectionError("suppressed"), suppress=True)
    returned = _result(_tools(state, scout=ScriptedModel([failure]))["scout_tool"](**SCOUT_CALL_ARGS))

    assert state.fatal_error is None
    assert [f.stage for f in state.failures] == ["scout"]
    assert returned["error"] == "scout_tool failed: builtins.RuntimeError"


def test_a_cyclic_chain_is_walked_once(state: RunState) -> None:
    """Each exception is visited once, so a chain that loops back on itself still ends."""
    first, second = RuntimeError("first"), ValueError("second")
    _chained(second, first)
    returned = _result(
        _tools(state, scout=ScriptedModel([_chained(first, second)]))["scout_tool"](**SCOUT_CALL_ARGS)
    )

    assert returned["error"] == "scout_tool failed: builtins.RuntimeError <- builtins.ValueError"
    assert [f.stage for f in state.failures] == ["scout"]
