"""Unit tests for the three Strands sub-agents: Scout, Writer and QA-Legal (IMPLEMENTATION_PLAN.md Iteration 6).

Copied selectively from Approach 1's ``tests/test_unit/test_agents.py`` (D-J): the Scout, QA-Legal, Writer and
``extract_telemetry`` tests are kept, the ScopeParser tests are dropped, and the Writer and QA-Legal tests are
adapted to their one ``AttemptRecord`` input (D-E, D-G).

Every test in this module is offline (D16, P4): no network call, no subprocess and no real credentials. LLM
behaviour is supplied by :class:`ScriptedModel`, a ``strands.models.model.Model`` subclass that replays
pre-recorded stream events through the **real** Strands event loop, and substrate tools are supplied by
:class:`StubSubstrateClient`, which mirrors the ``HSEMockMCPClient`` surface that the agent factories consume.
"""

import ast
import inspect
import json
import re
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any, Final

import pytest
from pydantic import ValidationError
from strands import Agent
from strands.handlers import null_callback_handler
from strands.hooks import BeforeInvocationEvent, HookRegistry
from strands.models.model import Model
from strands.types.exceptions import StructuredOutputException

from src import agents as agents_module
from src.agents import (
    QA_LEGAL_MODEL_ID,
    QA_LEGAL_REASONING_EFFORT,
    QA_LEGAL_SYSTEM_PROMPT,
    QA_LEGAL_TOOL_NAMES,
    SCOUT_MODEL_ID,
    SCOUT_REASONING_EFFORT,
    SCOUT_SYSTEM_PROMPT,
    SCOUT_TOOL_NAMES,
    WRITER_MODEL_ID,
    WRITER_REASONING_EFFORT,
    WRITER_SYSTEM_PROMPT,
    WRITER_TOOL_NAMES,
    build_qa_legal_agent,
    build_scout_agent,
    build_writer_agent,
    extract_telemetry,
    run_qa_legal,
    run_scout,
    run_writer,
)
from src.mcp_client import HSEMockMCPClient, MCPClientNotConnectedError
from src.schemas import (
    AgentContext,
    AgentTelemetry,
    ArticleDraft,
    AttemptRecord,
    PipelineScope,
    QAReport,
    ScoutCandidate,
    ScoutReport,
    ToolInvocation,
)
from tests.support.scripted import (
    DRAFT_ARGS,
    QA_LEGAL_PROMPT_SECTION,
    REVISED_DRAFT_ARGS,
    SUBSTRATE_TOOL_NAMES,
    TDI_OFFERING_FIXTURE,
    VALID_SCOPE_ARGS,
    WRITER_PROMPT_SECTION,
    RecordingMCPSession,
    ScriptedModel,
    StubSubstrateClient,
    list_regulatory_updates,
    offline_client,
    qa_args,
    scout_candidate_args,
    sent_text,
    text_turn,
    tool_use_turn,
    worker_prompts,
)

#: Any ISO calendar date, in the shape a prompt would carry one. The freeze defect
#: these guards exist to catch is ``f"...{date.today()}..."`` evaluated at import,
#: which bakes in whatever day the process started on -- not necessarily the date a
#: test happens to pin. Asserting the *shape* is absent rejects every such date.
_ISO_DATE: Final[re.Pattern[str]] = re.compile(r"\d{4}-\d{2}-\d{2}")


def _flat(prompt: str) -> str:
    """Collapse a prompt to lowercase single-spaced text for clause assertions.

    A system prompt is hard-wrapped for readability, so a clause the author wrote
    as one sentence is split across lines. Asserting on the raw string would force
    the prompt's line breaks to be chosen by the test rather than by the editor.
    """
    return " ".join(prompt.split()).lower()


# ---------------------------------------------------------------------------
# Benchmark constants: model bindings, efforts and declared tool intent (SPECIFICATIONS.md §1)
# ---------------------------------------------------------------------------


def test_model_ids_and_efforts_are_the_benchmark_constants() -> None:
    """Scout ``gpt-5-mini`` with no effort; Writer ``gpt-5.4`` at ``high``; QA-Legal ``gpt-5.4`` at ``medium``.

    Stated as literals, so a silent edit of any constant is caught here rather than in a benchmark report.
    """
    assert SCOUT_MODEL_ID == "gpt-5-mini"
    assert SCOUT_REASONING_EFFORT is None
    assert WRITER_MODEL_ID == "gpt-5.4"
    assert WRITER_REASONING_EFFORT == "high"
    assert QA_LEGAL_MODEL_ID == "gpt-5.4"
    assert QA_LEGAL_REASONING_EFFORT == "medium"


def test_declared_tool_intent_is_approach_1s() -> None:
    """The ``*_TOOL_NAMES`` tuples stay declared intent (P1): documented, never the default binding."""
    assert SCOUT_TOOL_NAMES == ("list_regulatory_updates", "search_regulatory_docs", "get_document_by_id")
    assert WRITER_TOOL_NAMES == ("get_tdi_service_offerings", "get_document_by_id")
    assert QA_LEGAL_TOOL_NAMES == ("verify_legal_citation", "get_document_by_id")


# ---------------------------------------------------------------------------
# Harness and telemetry contract (extract_telemetry, unchanged from Approach 1)
# ---------------------------------------------------------------------------


def test_scripted_model_drives_structured_output() -> None:
    """Self-test: the offline harness drives the real event loop to a typed payload."""
    model = ScriptedModel([tool_use_turn("PipelineScope", VALID_SCOPE_ARGS)])
    agent = Agent(model=model, callback_handler=None, system_prompt="harness self-test")

    result = agent("extract the scope", structured_output_model=PipelineScope)

    assert isinstance(result.structured_output, PipelineScope)
    assert result.structured_output.context.today == date(2026, 9, 22)
    assert model.turns_consumed == 1
    assert model.received_system_prompts[0] == "harness self-test"
    assert "extract the scope" in json.dumps(model.received_messages[0])


def test_load_scoped_tools_returns_only_requested_names() -> None:
    """``load_scoped_tools`` narrows one shared session to the named tools."""
    session = RecordingMCPSession()
    client = offline_client(session)

    tools = client.load_scoped_tools(["get_document_by_id", "verify_legal_citation"])

    assert [tool_obj.tool_name for tool_obj in tools] == ["get_document_by_id", "verify_legal_citation"]
    assert session.tool_filters_seen[-1] == {"allowed": ["get_document_by_id", "verify_legal_citation"]}

    all_tools = client.list_all_tools()
    assert len(all_tools) == len(SUBSTRATE_TOOL_NAMES)
    assert session.tool_filters_seen[-1] is None


def test_extract_telemetry_maps_usage_and_latency() -> None:
    """Every Rule 6 telemetry field is projected out of ``metrics.get_summary()``."""
    model = ScriptedModel(
        [tool_use_turn("PipelineScope", VALID_SCOPE_ARGS, input_tokens=123, output_tokens=45, latency_ms=678)]
    )
    agent = Agent(model=model, callback_handler=None)
    result = agent("prompt", structured_output_model=PipelineScope)

    telemetry = extract_telemetry(result, "gpt-5-mini")

    assert isinstance(telemetry, AgentTelemetry)
    assert telemetry.model_id == "gpt-5-mini"
    assert telemetry.input_tokens == 123
    assert telemetry.output_tokens == 45
    assert telemetry.total_tokens == 168
    assert telemetry.latency_ms == 678
    assert telemetry.cycles == 1
    # Pinned to the SDK's own value, not to ``>= 0.0``: the field defaults to 0.0, so a
    # lower-bound assertion cannot distinguish a correct key mapping from a typo'd one.
    assert telemetry.total_duration_seconds == pytest.approx(result.metrics.get_summary()["total_duration"])

    # ``EventLoopMetrics`` times its cycles with ``time.time()``, whose Windows
    # resolution leaves a scripted sub-millisecond cycle at exactly 0.0 — the same
    # value as the field default, so the equality above is real but not yet decisive.
    # Record a known duration on the real metrics object and re-project: only a
    # correct ``total_duration`` mapping can report it back.
    baseline = result.metrics.get_summary()["total_duration"]
    result.metrics.cycle_durations.append(0.25)

    assert extract_telemetry(result, "gpt-5-mini").total_duration_seconds == pytest.approx(baseline + 0.25)


def test_extract_telemetry_captures_cache_read_tokens() -> None:
    """Phase 6 / PLAN §2.6: the cached half of ``inputTokens`` must survive projection.

    ``prompt_tokens`` is inclusive of ``cached_tokens``, so costing that ignores
    ``cacheReadInputTokens`` charges the cached prefix at the full input rate.
    """
    turn = tool_use_turn("PipelineScope", VALID_SCOPE_ARGS, input_tokens=100, output_tokens=10)
    turn[-1]["metadata"]["usage"]["cacheReadInputTokens"] = 40
    agent = Agent(model=ScriptedModel([turn]), callback_handler=None)
    result = agent("prompt", structured_output_model=PipelineScope)

    telemetry = extract_telemetry(result, "gpt-5-mini")

    assert telemetry.input_tokens == 100
    assert telemetry.cache_read_input_tokens == 40


def test_extract_telemetry_captures_tool_invocations() -> None:
    """Per-tool execution stats become typed ``ToolInvocation`` entries."""
    model = ScriptedModel(
        [
            tool_use_turn("list_regulatory_updates", {"source": "INAIL", "limit": 5}),
            tool_use_turn("PipelineScope", VALID_SCOPE_ARGS),
        ]
    )
    agent = Agent(model=model, callback_handler=None, tools=[list_regulatory_updates])
    result = agent("prompt", structured_output_model=PipelineScope)

    telemetry = extract_telemetry(result, "gpt-5-mini")

    by_name = {invocation.tool_name: invocation for invocation in telemetry.tool_invocations}
    assert "list_regulatory_updates" in by_name
    invocation = by_name["list_regulatory_updates"]
    assert isinstance(invocation, ToolInvocation)
    assert invocation.call_count == 1
    assert invocation.success_count == 1
    assert invocation.error_count == 0
    # Pin to the real execution_stats value rather than to ``>= 0.0``, which the 0.0
    # field default satisfies unconditionally.
    stats = result.metrics.get_summary()["tool_usage"]["list_regulatory_updates"]["execution_stats"]
    assert invocation.total_time_seconds == pytest.approx(stats["total_time"])

    # A scripted tool call also completes inside one ``time.time()`` tick, so record a
    # known duration on the real ``ToolMetrics`` and re-project to make the mapping
    # decisive rather than merely 0.0 == 0.0.
    result.metrics.tool_metrics["list_regulatory_updates"].total_time += 0.5
    reprojected = {
        invocation.tool_name: invocation
        for invocation in extract_telemetry(result, "gpt-5-mini").tool_invocations
    }

    assert reprojected["list_regulatory_updates"].total_time_seconds == pytest.approx(stats["total_time"] + 0.5)


def test_agent_telemetry_rejects_extra_and_defaults_to_zero() -> None:
    """``AgentTelemetry`` ignores unknown keys and defaults every counter to zero."""
    telemetry = AgentTelemetry(model_id="gpt-5-mini", unexpected_upstream_field="ignored")

    assert telemetry.model_id == "gpt-5-mini"
    assert telemetry.input_tokens == 0
    assert telemetry.output_tokens == 0
    assert telemetry.total_tokens == 0
    assert telemetry.latency_ms == 0
    assert telemetry.total_duration_seconds == 0.0
    assert telemetry.cycles == 0
    assert telemetry.tool_invocations == []
    assert not hasattr(telemetry, "unexpected_upstream_field")


def test_extract_telemetry_records_the_effort_it_is_given() -> None:
    """Effort is configuration, not a metric.

    It is injected by the caller and never read out of ``get_summary()``, exactly
    as ``model_id`` already is -- Strands surfaces no reasoning-token count to
    derive it from.
    """
    model = ScriptedModel([tool_use_turn("PipelineScope", VALID_SCOPE_ARGS)])
    agent = Agent(model=model, callback_handler=None)
    result = agent("prompt", structured_output_model=PipelineScope)

    assert extract_telemetry(result, "gpt-5.4").reasoning_effort is None
    assert extract_telemetry(result, "gpt-5.4", "high").reasoning_effort == "high"


def test_scripted_agent_reports_zero_provider_latency_like_the_real_provider() -> None:
    """Documents the zero for the Phase 7 benchmark: the provider's TODO, not a measurement bug."""
    turn = tool_use_turn("ArticleDraft", DRAFT_ARGS, input_tokens=10, output_tokens=5, latency_ms=0)
    agent = Agent(model=ScriptedModel([turn]), callback_handler=None)
    result = agent("draft it", structured_output_model=ArticleDraft)

    telemetry = extract_telemetry(result, WRITER_MODEL_ID)

    assert telemetry.latency_ms == 0
    assert isinstance(agent.model, Model)


# ---------------------------------------------------------------------------
# Builders: the tool binding (P1) and the hooks seam (Iteration 12)
# ---------------------------------------------------------------------------


def test_scout_agent_receives_all_tools() -> None:
    """D19: the Scout is built with every substrate tool by default."""
    client = StubSubstrateClient()
    agent = build_scout_agent(ScriptedModel([]), client)

    assert len(agent.tool_names) == 5
    assert set(agent.tool_names) == set(SUBSTRATE_TOOL_NAMES)
    assert client.list_all_calls == 1
    assert client.scope_requests == []
    assert agent.callback_handler is null_callback_handler
    assert agent.system_prompt == SCOUT_SYSTEM_PROMPT


def test_scout_agent_accepts_explicit_tool_scope() -> None:
    """An explicit ``tool_names`` narrows the binding — the Phase 8 comparison path."""
    client = StubSubstrateClient()
    agent = build_scout_agent(ScriptedModel([]), client, tool_names=SCOUT_TOOL_NAMES)

    assert set(agent.tool_names) == set(SCOUT_TOOL_NAMES)
    assert len(SCOUT_TOOL_NAMES) == 3
    assert client.scope_requests == [list(SCOUT_TOOL_NAMES)]
    assert client.list_all_calls == 0


def test_writer_agent_receives_all_tools() -> None:
    """D19: the Writer is built with every substrate tool by default."""
    client = StubSubstrateClient()
    agent = build_writer_agent(ScriptedModel([]), client)

    assert len(agent.tool_names) == 5
    assert set(agent.tool_names) == set(SUBSTRATE_TOOL_NAMES)
    assert agent.callback_handler is null_callback_handler
    assert agent.system_prompt == WRITER_SYSTEM_PROMPT

    scoped = build_writer_agent(ScriptedModel([]), StubSubstrateClient(), tool_names=WRITER_TOOL_NAMES)
    assert set(scoped.tool_names) == set(WRITER_TOOL_NAMES)
    assert len(WRITER_TOOL_NAMES) == 2


def test_qa_legal_agent_receives_all_tools() -> None:
    """D19: QA-Legal is built with every substrate tool by default."""
    client = StubSubstrateClient()
    agent = build_qa_legal_agent(ScriptedModel([]), client)

    assert len(agent.tool_names) == 5
    assert set(agent.tool_names) == set(SUBSTRATE_TOOL_NAMES)
    assert agent.callback_handler is null_callback_handler
    assert agent.system_prompt == QA_LEGAL_SYSTEM_PROMPT

    scoped = build_qa_legal_agent(ScriptedModel([]), StubSubstrateClient(), tool_names=QA_LEGAL_TOOL_NAMES)
    assert set(scoped.tool_names) == set(QA_LEGAL_TOOL_NAMES)
    assert QA_LEGAL_TOOL_NAMES == ("verify_legal_citation", "get_document_by_id")


def test_factory_requires_live_client() -> None:
    """A factory called with a disconnected client fails loudly, before any agent exists."""
    client = HSEMockMCPClient()  # constructed, never started: spawns no subprocess

    for factory in (build_scout_agent, build_writer_agent, build_qa_legal_agent):
        with pytest.raises(MCPClientNotConnectedError):
            factory(ScriptedModel([]), client)
        with pytest.raises(MCPClientNotConnectedError):
            factory(ScriptedModel([]), client, tool_names=["get_document_by_id"])


_BUILDERS: Final[dict[str, Callable[..., Agent]]] = {
    "scout": build_scout_agent,
    "writer": build_writer_agent,
    "qa_legal": build_qa_legal_agent,
}


class _RecordingHooks:
    """A ``HookProvider`` that records its registration and every invocation it observes."""

    def __init__(self) -> None:
        self.registrations: int = 0
        self.invocations: int = 0

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        """Subscribe to the start of every invocation of the agent it is registered on."""
        self.registrations += 1
        registry.add_callback(BeforeInvocationEvent, self._on_invocation)

    def _on_invocation(self, event: BeforeInvocationEvent) -> None:
        """Count one invocation."""
        self.invocations += 1


@pytest.mark.parametrize("role", list(_BUILDERS))
def test_builder_registers_the_hooks_it_is_given(role: str) -> None:
    """A hook provider passed as ``hooks=`` is registered on the sub-agent and sees its invocations.

    This is the seam Iteration 12's logging and fatal-stop hooks use. It does not change the tool binding: the
    sub-agent still carries all five substrate tools (P1).
    """
    hooks = _RecordingHooks()
    agent = _BUILDERS[role](ScriptedModel([text_turn("ok")]), StubSubstrateClient(), hooks=[hooks])

    assert hooks.registrations == 1
    assert set(agent.tool_names) == set(SUBSTRATE_TOOL_NAMES)

    agent("ping")

    assert hooks.invocations == 1


@pytest.mark.parametrize("role", list(_BUILDERS))
def test_builder_adds_no_hooks_by_default(role: str) -> None:
    """``hooks`` is keyword-only and empty by default, so a plain build registers nothing of ours."""
    parameter = inspect.signature(_BUILDERS[role]).parameters["hooks"]

    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert tuple(parameter.default) == ()


@pytest.mark.parametrize("role", list(_BUILDERS))
def test_builder_without_a_client_builds_a_tool_free_agent(role: str) -> None:
    """``client=None`` builds the sub-agent with no substrate tools at all, the tool-free path the builders document."""
    agent = _BUILDERS[role](ScriptedModel([]))

    assert agent.tool_names == []


# ---------------------------------------------------------------------------
# Scout runner: one PipelineScope in, one ScoutReport out
# ---------------------------------------------------------------------------

#: The run facts code adds to every scope (DM5): the current date only.
_SCOUT_CONTEXT = AgentContext(today=date(2026, 9, 22))

_SCOUT_SCOPE = PipelineScope(
    context=_SCOUT_CONTEXT,
    date_from="2026-06-22",
    date_to="2026-09-22",
    sources=["INAIL"],
    sector_constraints=["construction"],
)


def test_scout_candidate_score_bounds() -> None:
    """``newsworthiness_score`` is constrained to the closed interval [0.0, 1.0]."""
    candidate = ScoutCandidate.model_validate(scout_candidate_args("inail-1", 0.87, "High impact heat-stress circular"))
    assert candidate.newsworthiness_score == 0.87
    assert candidate.update.doc_id == "inail-1"

    with pytest.raises(ValidationError):
        ScoutCandidate.model_validate(scout_candidate_args("inail-1", 1.5, "Out of range"))
    with pytest.raises(ValidationError):
        ScoutCandidate.model_validate(scout_candidate_args("inail-1", -0.1, "Out of range"))


def test_scout_returns_ranked_scout_report() -> None:
    """The Scout returns a typed ``ScoutReport`` and receives the scope verbatim."""
    model = ScriptedModel(
        [
            tool_use_turn(
                "ScoutReport",
                {
                    "candidates": [
                        scout_candidate_args("inail-2024-circ-calore", 0.92, "Critical heat-stress obligations"),
                        scout_candidate_args("gu-2024-dl-preposti", 0.71, "New biennial training duty"),
                    ]
                },
            )
        ]
    )
    agent = build_scout_agent(model, StubSubstrateClient())

    output = run_scout(agent, _SCOUT_SCOPE)

    assert isinstance(output.payload, ScoutReport)
    assert [candidate.update.doc_id for candidate in output.payload.candidates] == [
        "inail-2024-circ-calore",
        "gu-2024-dl-preposti",
    ]
    assert output.telemetry.model_id == SCOUT_MODEL_ID == "gpt-5-mini"

    sent = json.dumps(model.received_messages[0])
    assert "INAIL" in sent
    assert "construction" in sent


def test_scout_applies_newsworthiness_scoring() -> None:
    """Scores stay within bounds, rank descending, and carry a non-empty rationale."""
    model = ScriptedModel(
        [
            tool_use_turn(
                "ScoutReport",
                {
                    "candidates": [
                        scout_candidate_args("doc-a", 0.95, "Critical impact, immediate compliance deadline"),
                        scout_candidate_args("doc-b", 0.6, "Moderate impact on construction sector"),
                        scout_candidate_args("doc-c", 0.4, "Background guidance, limited novelty"),
                    ]
                },
            )
        ]
    )
    agent = build_scout_agent(model, StubSubstrateClient())

    candidates = run_scout(agent, _SCOUT_SCOPE).payload.candidates

    # Guard the iteration: without this every assertion below is vacuously true for
    # an empty list, and the test passes against a Scout that returns nothing.
    assert len(candidates) == 3
    assert [candidate.update.doc_id for candidate in candidates] == ["doc-a", "doc-b", "doc-c"]

    scores = [candidate.newsworthiness_score for candidate in candidates]
    assert all(0.0 <= score <= 1.0 for score in scores)
    assert scores == sorted(scores, reverse=True)
    assert all(candidate.rationale.strip() for candidate in candidates)


def test_scout_receives_the_ceiling_and_returns_the_top_n() -> None:
    """Item 3: candidate selection is the Scout's, so the ceiling must reach it.

    Rule 4 assigns newsworthiness filtering to the Scout and says only that the
    pipeline drafts everything qualifying *unless the user set a limit*; D3 says the
    Scout "passes all qualifying updates unless the user explicitly bounds
    ``max_drafts``". Neither names the orchestrator as the holder of the ceiling, so
    the Scout selecting the top N by score is within its remit.

    The runner itself still truncates nothing — it is a pass-through — so what this
    pins is that the bounded scope reaches the model and that its top-N answer
    survives to the caller intact.
    """
    model = ScriptedModel(
        [
            tool_use_turn(
                "ScoutReport",
                {"candidates": [scout_candidate_args("doc-a", 0.9, "Highest impact")]},
            )
        ]
    )
    agent = build_scout_agent(model, StubSubstrateClient())
    constrained_scope = PipelineScope(
        context=_SCOUT_CONTEXT,
        date_from="2026-06-22",
        date_to="2026-09-22",
        max_drafts=1,
    )

    output = run_scout(agent, constrained_scope)

    # The ceiling is visible to the Scout in the serialised scope, not hidden from it,
    # and the user turn names it rather than leaving the Scout to notice the field.
    turn = sent_text(model)
    assert '"max_drafts": 1' in turn
    assert "bounded by the scope's max_drafts ceiling" in turn
    assert [candidate.update.doc_id for candidate in output.payload.candidates] == ["doc-a"]


def test_scout_returns_every_qualifying_candidate_when_unbounded() -> None:
    """Rule 4 default: with ``max_drafts`` null the Scout truncates nothing."""
    model = ScriptedModel(
        [
            tool_use_turn(
                "ScoutReport",
                {
                    "candidates": [
                        scout_candidate_args("doc-a", 0.9, "Qualifying"),
                        scout_candidate_args("doc-b", 0.8, "Qualifying"),
                        scout_candidate_args("doc-c", 0.7, "Qualifying"),
                    ]
                },
            )
        ]
    )
    agent = build_scout_agent(model, StubSubstrateClient())

    output = run_scout(agent, PipelineScope(context=_SCOUT_CONTEXT, date_from="2026-06-22", date_to="2026-09-22"))

    assert '"max_drafts": null' in sent_text(model)
    assert len(output.payload.candidates) == 3


def test_scout_invokes_regulatory_tools() -> None:
    """Substrate tool use is visible in telemetry, which is how role bleed is detected."""
    model = ScriptedModel(
        [
            tool_use_turn("list_regulatory_updates", {"source": "INAIL", "limit": 10}),
            tool_use_turn("ScoutReport", {"candidates": [scout_candidate_args("doc-a", 0.9, "Qualifying")]}),
        ]
    )
    agent = build_scout_agent(model, StubSubstrateClient())

    telemetry = run_scout(agent, _SCOUT_SCOPE).telemetry

    by_name = {invocation.tool_name: invocation for invocation in telemetry.tool_invocations}
    assert "list_regulatory_updates" in by_name
    assert by_name["list_regulatory_updates"].call_count >= 1
    assert by_name["list_regulatory_updates"].error_count == 0


def test_scout_user_turn_carries_the_resolved_bounds() -> None:
    """The scope is serialised whole, so the bounds reach the Scout without a runner change."""
    model = ScriptedModel(
        [tool_use_turn("ScoutReport", {"candidates": [scout_candidate_args("doc-a", 0.9, "Qualifying")]})]
    )
    scope = PipelineScope(
        context=_SCOUT_CONTEXT,
        date_from="2026-06-22",
        date_to="2026-09-22",
        sources=["INAIL"],
    )

    run_scout(build_scout_agent(model, StubSubstrateClient()), scope)

    turn = sent_text(model)
    assert '"date_from": "2026-06-22"' in turn
    assert '"date_to": "2026-09-22"' in turn


def test_scout_user_turn_carries_the_whole_scope_with_its_context_as_json() -> None:
    """The scope reaches the Scout as one JSON object, ``context.today`` included, under ``## PipelineScope``.

    Structured object passing, not narrative interpolation (Approach 1 D18). The current date arrives inside the
    scope's ``context`` (DM5), in the place ``time_window`` used to be (DM2); nothing else is added to the turn.
    """
    model = ScriptedModel([tool_use_turn("ScoutReport", {"candidates": []})])

    run_scout(build_scout_agent(model, StubSubstrateClient()), _SCOUT_SCOPE)

    turn = sent_text(model)
    assert turn.startswith("Triage the regulatory substrate for the editorial scope below and return a ScoutReport.")
    serialised = json.loads(turn.split("## PipelineScope\n", 1)[1])
    assert serialised == _SCOUT_SCOPE.model_dump(mode="json")
    assert serialised["context"] == {"today": "2026-09-22"}
    assert '"today": "2026-09-22"' in turn


def test_run_scout_rejects_an_invalid_report() -> None:
    """A structured output that is not a valid ``ScoutReport`` never surfaces as one.

    The runner reports what it was given; it does not repair a malformed payload. Strands retries the structured
    output once the validation fails, so the script offers no valid turn at all.
    """
    model = ScriptedModel(
        [
            tool_use_turn("ScoutReport", {"candidates": [scout_candidate_args("doc-a", 1.5, "Out of range")]}),
            text_turn("I could not comply."),
            text_turn("Still unable to comply."),
        ]
    )

    with pytest.raises((StructuredOutputException, ValidationError)):
        run_scout(build_scout_agent(model, StubSubstrateClient()), _SCOUT_SCOPE)


# ---------------------------------------------------------------------------
# Writer runner: a first draft from a new AttemptRecord
# ---------------------------------------------------------------------------

#: The Scout's triage record, from which the Writer dereferences its own source
#: through ``get_document_by_id``.
_CANDIDATE = ScoutCandidate.model_validate(
    scout_candidate_args("inail-2024-circ-calore", 0.92, "Obblighi immediati per i datori di lavoro.")
)


def _first_attempt(today: date = date(2026, 9, 23)) -> AttemptRecord:
    """Attempt 1 as ``writer_tool`` appends it: the context and the candidate, no draft yet (D-E step 2)."""
    return AttemptRecord(context=AgentContext(today=today), candidate=_CANDIDATE, attempt=1)


def test_writer_generates_article_draft() -> None:
    """The Writer returns a fully populated ``ArticleDraft`` for the source document."""
    model = ScriptedModel([tool_use_turn("ArticleDraft", DRAFT_ARGS)])
    agent = build_writer_agent(model, StubSubstrateClient())

    output = run_writer(agent, _first_attempt())

    draft = output.payload
    assert isinstance(draft, ArticleDraft)
    assert draft.headline.strip()
    assert draft.executive_summary.strip()
    assert draft.article_body.strip()
    assert draft.tdi_cta.strip()

    assert draft.source_doc_id == _CANDIDATE.update.doc_id

    sent = json.dumps(model.received_messages[0])
    assert "Circolare INAIL n. 28/2024" in sent
    # The obligations live in the document the Writer must fetch, not in the candidate.
    assert "Riprogrammare i turni di lavoro nelle ore piu calde" not in sent


def test_writer_includes_tdi_cta_from_offerings() -> None:
    """The CTA is traceable to a real ``get_tdi_service_offerings`` result."""
    model = ScriptedModel(
        [
            tool_use_turn("get_tdi_service_offerings", {"topic": "workplace_safety", "sector": "construction"}),
            tool_use_turn("ArticleDraft", DRAFT_ARGS),
        ]
    )
    agent = build_writer_agent(model, StubSubstrateClient())

    output = run_writer(agent, _first_attempt())

    assert TDI_OFFERING_FIXTURE["cta_headline"] in output.payload.tdi_cta

    by_name = {invocation.tool_name: invocation for invocation in output.telemetry.tool_invocations}
    assert by_name["get_tdi_service_offerings"].call_count == 1
    assert by_name["get_tdi_service_offerings"].error_count == 0


def test_writer_telemetry_carries_writer_model_id() -> None:
    """The Writer is bound to the strong model (SPECIFICATIONS.md §1)."""
    model = ScriptedModel(
        [tool_use_turn("ArticleDraft", DRAFT_ARGS, input_tokens=900, output_tokens=600, latency_ms=4200)]
    )
    agent = build_writer_agent(model, StubSubstrateClient())

    telemetry = run_writer(agent, _first_attempt()).telemetry

    assert telemetry.model_id == WRITER_MODEL_ID == "gpt-5.4"
    assert telemetry.total_tokens == 1500
    assert telemetry.latency_ms == 4200


def test_writer_receives_the_candidate_not_a_hydrated_document() -> None:
    """The Writer is handed one ``ScoutCandidate``, inside its ``AttemptRecord``, and dereferences it itself.

    The Supervisor chooses *which* document is written about, by ``doc_id``; code
    hands over the candidate rather than the body, so the Writer dereferences
    rather than selects. The candidate's ``summary`` is triage metadata, so the
    obligations and the full text can only reach the model through the Writer's
    own ``get_document_by_id`` call.
    """
    model = ScriptedModel([tool_use_turn("ArticleDraft", DRAFT_ARGS)])
    agent = build_writer_agent(model, StubSubstrateClient())

    run_writer(agent, _first_attempt())

    sent = sent_text(model)
    assert "## AttemptRecord" in sent
    assert '"candidate":' in sent
    assert f'"doc_id":"{_CANDIDATE.update.doc_id}"' in sent
    assert _CANDIDATE.update.summary in sent
    assert "get_document_by_id" in sent
    # The document body was never pre-hydrated into the prompt.
    assert "Riprogrammare i turni di lavoro nelle ore piu calde" not in sent
    assert "content_markdown" not in sent


def test_run_writer_does_not_police_the_fetch_it_asks_for() -> None:
    """A runner reports; it never decides. Judging the draft belongs outside this module.

    ``run_writer`` returns a non-compliant draft — one produced with no
    ``get_document_by_id`` call and an empty ``source_doc_id`` — exactly as it
    returns a compliant one. Raising here would put a decision inside
    ``src/agents.py``, which SPECIFICATIONS.md §1.1 gives to the Supervisor, QA-Legal
    and the tool wrappers, and ``test_agents_module_contains_no_loop_state`` guards
    structurally.
    """
    model = ScriptedModel([tool_use_turn("ArticleDraft", {**DRAFT_ARGS, "source_doc_id": ""})])
    agent = build_writer_agent(model, StubSubstrateClient())

    output = run_writer(agent, _first_attempt())

    assert isinstance(output.payload, ArticleDraft)
    assert output.payload.source_doc_id == ""
    assert [invocation.tool_name for invocation in output.telemetry.tool_invocations] == ["ArticleDraft"]


def test_run_writer_threads_its_role_effort_into_the_returned_telemetry() -> None:
    """The Writer's ``high`` reaches ``AgentTelemetry`` without the caller restating it."""
    model = ScriptedModel([tool_use_turn("ArticleDraft", DRAFT_ARGS)])
    agent = build_writer_agent(model, StubSubstrateClient())

    output = run_writer(agent, _first_attempt())

    assert output.telemetry.reasoning_effort == "high"


def test_writer_user_turn_carries_the_current_date() -> None:
    """The date reaches the model per call, and is never baked into the constant.

    ``draft_20260923_001`` advised its reader to prepare "prima dell'apertura" for
    a window that had opened seven weeks earlier. Nothing in the Writer's prompt
    or turn said what day it was.
    """
    model = ScriptedModel([tool_use_turn("ArticleDraft", DRAFT_ARGS)])

    run_writer(build_writer_agent(model, StubSubstrateClient()), _first_attempt())

    turn = sent_text(model)
    assert "Current date: 2026-09-23" in turn
    # Frozen-at-import is the failure mode this guards: the constant carries no date
    # at all, not merely a different one from the date this test pins.
    assert not _ISO_DATE.search(WRITER_SYSTEM_PROMPT)

    later = ScriptedModel([tool_use_turn("ArticleDraft", DRAFT_ARGS)])
    run_writer(build_writer_agent(later, StubSubstrateClient()), _first_attempt(date(2027, 1, 3)))

    second_turn = sent_text(later)
    assert "Current date: 2027-01-03" in second_turn
    assert "2026-09-23" not in second_turn


def test_run_writer_takes_the_current_date_from_the_record() -> None:
    """``today`` is not a parameter: the turn's ``Current date:`` comes from ``record.context.today`` (D-G).

    The date still reaches the Writer per call rather than being baked into ``WRITER_SYSTEM_PROMPT`` at
    import. It now arrives inside the one typed input, so the runner has no second source of "now" that
    could disagree with the record the Writer is given.
    """
    assert "today" not in inspect.signature(run_writer).parameters

    model = ScriptedModel([tool_use_turn("ArticleDraft", DRAFT_ARGS)])
    run_writer(build_writer_agent(model, StubSubstrateClient()), _first_attempt(date(2026, 11, 4)))

    assert sent_text(model).startswith("Current date: 2026-11-04. Write about this instrument as it stands today.")


def test_writer_first_draft_turn_asks_for_a_draft_and_names_the_candidates_doc_id() -> None:
    """With no draft on the record, the turn asks for a first draft and points ``get_document_by_id`` at its source.

    The instruction names the path ``candidate.update.doc_id`` inside the record, and the record carries its
    value, so the Writer fetches its own source. The record follows whole, as ``writer_view()`` (§7.2).
    """
    model = ScriptedModel([tool_use_turn("ArticleDraft", DRAFT_ARGS)])
    record = _first_attempt()

    run_writer(build_writer_agent(model, StubSubstrateClient()), record)

    turn = sent_text(model)
    assert "Write a publication-ready HSE article as an ArticleDraft" in turn
    assert "in the AttemptRecord below" in turn
    assert "Call get_document_by_id on its candidate.update.doc_id" in turn
    assert "echo that same doc_id back as the draft's source_doc_id" in turn
    assert f'"doc_id":"{_CANDIDATE.update.doc_id}"' in turn
    assert turn.endswith("## AttemptRecord\n" + record.writer_view())
    # A first draft carries no revision instruction and no draft to revise.
    assert "Rewrite the previous draft" not in turn
    assert '"draft":null' in turn


def test_run_writer_leaves_a_first_attempt_unchanged() -> None:
    """The runner returns the draft; storing it on the record is the tool wrapper's job (D-A step 4)."""
    model = ScriptedModel([tool_use_turn("ArticleDraft", DRAFT_ARGS)])
    record = _first_attempt()
    before = record.model_dump()

    output = run_writer(build_writer_agent(model, StubSubstrateClient()), record)

    assert output.payload.headline == DRAFT_ARGS["headline"]
    assert record.draft is None
    assert record.model_dump() == before


# ---------------------------------------------------------------------------
# Writer runner: a revision from the latest drafted and audited AttemptRecord (D-E)
# ---------------------------------------------------------------------------

_PREVIOUS_DRAFT = ArticleDraft.model_validate(DRAFT_ARGS)

_QA_REPORT = QAReport(
    status="ERROR",
    verified_citations=["Circolare INAIL n. 28/2024"],
    issues=[
        "La citazione 'D.Lgs. 81/2008 Art. 28' non supporta l'obbligo di turnazione descritto.",
        "Manca il riferimento alla soglia dei 35 gradi per l'attivazione della CIGO.",
    ],
    review_notes="Correggere i due rilievi mantenendo invariato il resto del testo.",
)


def _audited_attempt(attempt: int = 1) -> AttemptRecord:
    """The latest drafted record as code hands it to a revision: its draft and the QA report on it (D-E step 5)."""
    return AttemptRecord(
        context=AgentContext(today=date(2026, 9, 23)),
        candidate=_CANDIDATE,
        attempt=attempt,
        draft=_PREVIOUS_DRAFT,
        qa_report=_QA_REPORT,
    )


def test_writer_accepts_a_drafted_and_audited_record() -> None:
    """Given a record carrying its draft and QA report, the Writer returns a revised ``ArticleDraft``."""
    model = ScriptedModel([tool_use_turn("ArticleDraft", REVISED_DRAFT_ARGS)])
    agent = build_writer_agent(model, StubSubstrateClient())

    output = run_writer(agent, _audited_attempt())

    assert isinstance(output.payload, ArticleDraft)
    assert output.payload.headline == REVISED_DRAFT_ARGS["headline"]
    assert output.payload.headline != _PREVIOUS_DRAFT.headline
    assert "35 gradi" in output.payload.article_body
    assert output.telemetry.model_id == WRITER_MODEL_ID


def test_writer_revision_serialises_structured_payload() -> None:
    """Approach 1 D18: the draft and its QA report are passed as structured JSON, never narrative."""
    model = ScriptedModel([tool_use_turn("ArticleDraft", REVISED_DRAFT_ARGS)])
    agent = build_writer_agent(model, StubSubstrateClient())

    run_writer(agent, _audited_attempt())

    sent = sent_text(model)
    # The previous draft reaches the model verbatim.
    assert _PREVIOUS_DRAFT.headline in sent
    assert _PREVIOUS_DRAFT.tdi_cta in sent
    # The body is multi-line, so the serializer escapes its newlines; match per line.
    for line in _PREVIOUS_DRAFT.article_body.splitlines():
        assert line in sent
    # So does every QA issue, unparaphrased.
    for issue in _QA_REPORT.issues:
        assert issue in sent
    assert _QA_REPORT.review_notes in sent
    # And it arrives as a JSON object, not as prose about the object.
    assert '"qa_report":' in sent
    assert '"draft":' in sent


def test_writer_revision_does_not_manage_attempts() -> None:
    """``attempt`` comes solely from the record; the runner neither reads nor mutates a counter.

    A revision is handed the record being revised, attempt 1 or 2 under the cap (D-E), and the record is
    left exactly as it was given.
    """
    signature = inspect.signature(run_writer)
    assert "attempts" not in signature.parameters
    assert "max_drafts" not in signature.parameters

    for attempt in (1, 2):
        model = ScriptedModel([tool_use_turn("ArticleDraft", REVISED_DRAFT_ARGS)])
        agent = build_writer_agent(model, StubSubstrateClient())
        record = _audited_attempt(attempt=attempt)
        before = record.model_dump()

        run_writer(agent, record)

        assert f'"attempt":{attempt}' in sent_text(model)
        # The runner leaves the caller's record untouched: no new draft, no new report.
        assert record.model_dump() == before


def test_writer_revision_turn_gives_approach_1s_revision_instruction() -> None:
    """A record with a draft adds Approach 1's revision sentences, reworded only where they name the input.

    The first-draft instruction still leads the turn, as it did in Approach 1, and the record follows once,
    under ``## AttemptRecord``. Whether to revise is not decided here: the branch tests only whether the record
    carries a draft, never the QA status (AGENTS.md Rule 2).
    """
    model = ScriptedModel([tool_use_turn("ArticleDraft", REVISED_DRAFT_ARGS)])
    record = _audited_attempt()

    run_writer(build_writer_agent(model, StubSubstrateClient()), record)

    turn = sent_text(model)
    assert (
        "Rewrite the previous draft in the record below so that every issue in its QA report is resolved. "
        "Preserve everything the audit did not object to."
    ) in turn
    assert turn.index("Write a publication-ready HSE article") < turn.index("Rewrite the previous draft")
    assert turn.index("Rewrite the previous draft") < turn.index("## AttemptRecord")
    assert turn.count("## AttemptRecord") == 1
    assert turn.endswith("## AttemptRecord\n" + record.writer_view())


def test_run_writer_refuses_a_draft_without_its_qa_report() -> None:
    """A revision needs both halves: a record with a draft but no QA report is refused before any model call.

    The guardrails make this input unreachable (D-C rule 7), so it can only be a caller bug. The message names
    the document and the attempt, never article text.
    """
    model = ScriptedModel([tool_use_turn("ArticleDraft", REVISED_DRAFT_ARGS)])
    record = AttemptRecord(
        context=AgentContext(today=date(2026, 9, 23)), candidate=_CANDIDATE, attempt=2, draft=_PREVIOUS_DRAFT
    )

    with pytest.raises(ValueError, match="QA report") as raised:
        run_writer(build_writer_agent(model, StubSubstrateClient()), record)

    message = str(raised.value)
    assert _CANDIDATE.update.doc_id in message
    assert "Attempt 2" in message
    assert _PREVIOUS_DRAFT.headline not in message
    assert model.turns_consumed == 0


# ---------------------------------------------------------------------------
# QA-Legal runner: the latest draft, as qa_view(), and nothing about the cap (DM7)
# ---------------------------------------------------------------------------


def _drafted_attempt(attempt: int = 1, today: date = date(2026, 9, 23)) -> AttemptRecord:
    """The latest drafted record as code hands it to QA-Legal: a draft, no report yet (D-E step 3)."""
    return AttemptRecord(
        context=AgentContext(today=today), candidate=_CANDIDATE, attempt=attempt, draft=_PREVIOUS_DRAFT
    )


def test_qa_legal_fact_checks_against_source_document() -> None:
    """P1 in practice: QA reaches ``get_document_by_id`` to check statutory statements."""
    mismatch = (
        "L'articolo attribuisce alla Circolare INAIL n. 28/2024 un obbligo di dotazione idrica "
        "non presente fra le key_obligations del documento di origine."
    )
    model = ScriptedModel(
        [
            tool_use_turn("get_document_by_id", {"doc_id": "inail-2024-circ-calore"}),
            tool_use_turn("QAReport", qa_args(status="ERROR", issues=[mismatch])),
        ]
    )
    agent = build_qa_legal_agent(model, StubSubstrateClient())

    output = run_qa_legal(agent, _drafted_attempt())

    by_name = {invocation.tool_name: invocation for invocation in output.telemetry.tool_invocations}
    assert by_name["get_document_by_id"].call_count == 1
    assert by_name["get_document_by_id"].error_count == 0
    assert any("key_obligations" in issue for issue in output.payload.issues)


def test_qa_legal_produces_pass_report() -> None:
    """A clean draft yields ``PASS`` with no issues."""
    model = ScriptedModel([tool_use_turn("QAReport", qa_args(status="PASS", notes="Tutte le citazioni sono vigenti."))])
    agent = build_qa_legal_agent(model, StubSubstrateClient())

    output = run_qa_legal(agent, _drafted_attempt())

    assert isinstance(output.payload, QAReport)
    assert output.payload.status == "PASS"
    assert output.payload.issues == []
    assert output.payload.verified_citations
    assert output.telemetry.model_id == QA_LEGAL_MODEL_ID == "gpt-5.4"

    # The draft reaches the auditor as JSON, so its body arrives line by line
    # with newlines escaped by the serializer.
    sent = sent_text(model)
    assert _PREVIOUS_DRAFT.headline in sent
    for line in _PREVIOUS_DRAFT.article_body.splitlines():
        assert line in sent


def test_qa_legal_produces_warning_report() -> None:
    """A non-blocking defect yields ``WARNING``, reported as issued for the Supervisor to act on."""
    model = ScriptedModel(
        [
            tool_use_turn(
                "QAReport",
                qa_args(
                    status="WARNING",
                    issues=["La citazione e vigente ma e stata modificata dal D.L. 19/2024."],
                    notes="Rilievo non bloccante.",
                ),
            )
        ]
    )
    agent = build_qa_legal_agent(model, StubSubstrateClient())

    report = run_qa_legal(agent, _drafted_attempt()).payload

    assert report.status == "WARNING"
    assert report.issues


def test_qa_legal_produces_error_report_with_issues() -> None:
    """A blocking defect yields ``ERROR`` and a non-empty issue list."""
    model = ScriptedModel(
        [
            tool_use_turn(
                "QAReport",
                qa_args(
                    status="ERROR",
                    issues=[
                        "La citazione 'D.Lgs. 81/2008 Art. 999' non esiste.",
                        "Le sanzioni descritte non corrispondono al penalties_summary del documento.",
                    ],
                ),
            )
        ]
    )
    agent = build_qa_legal_agent(model, StubSubstrateClient())

    report = run_qa_legal(agent, _drafted_attempt()).payload

    assert report.status == "ERROR"
    assert len(report.issues) == 2


def test_qa_legal_verifies_each_citation() -> None:
    """Citation verification is visible in telemetry, per citation checked."""
    model = ScriptedModel(
        [
            tool_use_turn("verify_legal_citation", {"citation": "D.Lgs. 81/2008 Art. 28"}),
            tool_use_turn("verify_legal_citation", {"citation": "Circolare INAIL n. 28/2024"}),
            tool_use_turn("QAReport", qa_args(status="PASS")),
        ]
    )
    agent = build_qa_legal_agent(model, StubSubstrateClient())

    telemetry = run_qa_legal(agent, _drafted_attempt()).telemetry

    by_name = {invocation.tool_name: invocation for invocation in telemetry.tool_invocations}
    assert "verify_legal_citation" in by_name
    assert by_name["verify_legal_citation"].call_count >= 1
    assert by_name["verify_legal_citation"].call_count == by_name["verify_legal_citation"].success_count


def test_qa_legal_turn_carries_the_drafts_source_doc_id() -> None:
    """The auditor is told which slug to fetch, in the user turn, not left to guess.

    ``QA_LEGAL_SYSTEM_PROMPT`` instructs QA-Legal to start from
    ``get_document_by_id(draft.source_doc_id)``. In Approach 1's Phase 7 live run,
    an auditor handed no ID reverse-engineered slugs out of citation text and issued
    an ``ERROR`` verdict citing ``key_obligations`` it had never read. The value is
    interpolated into the instruction and also carried in the record's ``draft``.
    """
    model = ScriptedModel([tool_use_turn("QAReport", qa_args(status="PASS"))])
    agent = build_qa_legal_agent(model, StubSubstrateClient())

    run_qa_legal(agent, _drafted_attempt())

    sent = sent_text(model)
    assert _PREVIOUS_DRAFT.source_doc_id
    assert f'"source_doc_id":"{_PREVIOUS_DRAFT.source_doc_id}"' in sent
    # And the instruction names it as the starting point, not merely as a field.
    assert f"get_document_by_id({_PREVIOUS_DRAFT.source_doc_id})" in sent


def test_run_qa_legal_threads_an_explicit_override_into_the_returned_telemetry() -> None:
    """An override passed by the caller beats the role constant in the telemetry."""
    model = ScriptedModel([tool_use_turn("QAReport", qa_args(status="PASS"))])
    agent = build_qa_legal_agent(model, StubSubstrateClient())

    output = run_qa_legal(agent, _drafted_attempt(), reasoning_effort="low")

    assert output.telemetry.reasoning_effort == "low"


def test_qa_legal_user_turn_carries_the_current_date() -> None:
    """QA-Legal passed the stale framing because it had no clock either."""
    model = ScriptedModel([tool_use_turn("QAReport", qa_args(status="PASS"))])

    run_qa_legal(build_qa_legal_agent(model, StubSubstrateClient()), _drafted_attempt())

    turn = sent_text(model)
    assert "Current date: 2026-09-23" in turn
    # As for the Writer: no date of any value may be baked into the constant.
    assert not _ISO_DATE.search(QA_LEGAL_SYSTEM_PROMPT)

    later = ScriptedModel([tool_use_turn("QAReport", qa_args(status="PASS"))])
    run_qa_legal(build_qa_legal_agent(later, StubSubstrateClient()), _drafted_attempt(today=date(2027, 1, 3)))

    second_turn = sent_text(later)
    assert "Current date: 2027-01-03" in second_turn
    assert "2026-09-23" not in second_turn


def test_run_qa_legal_takes_the_current_date_from_the_record() -> None:
    """``today`` is not a parameter: the turn's ``Current date:`` comes from ``record.context.today`` (D-G).

    Temporal accuracy is one of the checks the audit makes, so the auditor needs a clock; it arrives inside
    the one typed input, as the Writer's does.
    """
    assert "today" not in inspect.signature(run_qa_legal).parameters

    model = ScriptedModel([tool_use_turn("QAReport", qa_args(status="PASS"))])
    run_qa_legal(build_qa_legal_agent(model, StubSubstrateClient()), _drafted_attempt(today=date(2026, 11, 4)))

    assert sent_text(model).startswith("Current date: 2026-11-04. Judge the draft's temporal claims against it.")


def test_qa_legal_turn_sends_the_records_qa_view() -> None:
    """The record reaches the auditor as ``qa_view()``: ``{context, attempt, draft, doc_id}``, no candidate (§7.2)."""
    model = ScriptedModel([tool_use_turn("QAReport", qa_args(status="PASS"))])
    record = _drafted_attempt()

    run_qa_legal(build_qa_legal_agent(model, StubSubstrateClient()), record)

    turn = sent_text(model)
    assert "Audit the article draft in the AttemptRecord below and return a QAReport." in turn
    assert turn.count("## AttemptRecord") == 1
    assert turn.endswith("## AttemptRecord\n" + record.qa_view())
    assert json.loads(record.qa_view()).keys() == {"context", "attempt", "draft", "doc_id"}


@pytest.mark.parametrize("attempt", [2, 3])
def test_qa_legal_turn_never_mentions_the_candidate_or_the_attempt_cap(attempt: int) -> None:
    """DM7: QA-Legal sees the attempt number, and nothing of the Scout's triage or of the 3-attempt cap.

    It audits a draft, as it did in Approach 1. The Scout's ``rationale`` and ``newsworthiness_score`` stay
    with the candidate, and no phrasing of the cap reaches it (DM5).
    """
    model = ScriptedModel([tool_use_turn("QAReport", qa_args(status="PASS"))])

    run_qa_legal(build_qa_legal_agent(model, StubSubstrateClient()), _drafted_attempt(attempt=attempt))

    turn = sent_text(model)
    assert f'"attempt":{attempt}' in turn
    lowered = turn.lower()
    for absent in ("rationale", "newsworthiness_score", "candidate", _CANDIDATE.rationale.lower()):
        assert absent not in lowered, absent
    for cap in ("3 attempts", "max_attempts", "attempt cap", "attempts remaining"):
        assert cap not in lowered, cap


def test_writer_turn_never_mentions_the_attempt_cap() -> None:
    """DM5: the Writer's record carries the date only, never a budget or the attempt cap."""
    model = ScriptedModel([tool_use_turn("ArticleDraft", REVISED_DRAFT_ARGS)])

    run_writer(build_writer_agent(model, StubSubstrateClient()), _audited_attempt(attempt=2))

    lowered = sent_text(model).lower()
    for cap in ("3 attempts", "max_attempts", "attempt cap", "attempts remaining"):
        assert cap not in lowered, cap


def test_run_qa_legal_refuses_a_record_without_a_draft() -> None:
    """There is nothing to audit on a record whose Writer call has not produced a draft.

    The ``no_draft`` guardrail makes this input unreachable (D-C), so it can only be a caller bug; it is
    refused before any model call, and the message names the document and the attempt.
    """
    model = ScriptedModel([tool_use_turn("QAReport", qa_args(status="PASS"))])

    with pytest.raises(ValueError, match="no draft") as raised:
        run_qa_legal(build_qa_legal_agent(model, StubSubstrateClient()), _first_attempt())

    assert _CANDIDATE.update.doc_id in str(raised.value)
    assert "Attempt 1" in str(raised.value)
    assert model.turns_consumed == 0


def test_run_qa_legal_leaves_the_record_unchanged() -> None:
    """The runner returns the report; storing it on the record is the tool wrapper's job (D-A step 4)."""
    model = ScriptedModel([tool_use_turn("QAReport", qa_args(status="WARNING", issues=["[WARNING] Imprecisa."]))])
    record = _drafted_attempt()
    before = record.model_dump()

    output = run_qa_legal(build_qa_legal_agent(model, StubSubstrateClient()), record)

    assert output.payload.status == "WARNING"
    assert record.qa_report is None
    assert record.model_dump() == before


def test_worker_prompt_markers_tell_the_writers_turns_from_qa_legals() -> None:
    """Each harness marker occurs in exactly one runner's user turn, first draft and revision alike.

    The Writer and QA-Legal share the strong model, and both turns now carry ``## AttemptRecord``, so
    ``worker_prompts`` tells them apart by the opening sentence each runner alone writes.
    """
    model = ScriptedModel(
        [
            tool_use_turn("ArticleDraft", DRAFT_ARGS),
            tool_use_turn("ArticleDraft", REVISED_DRAFT_ARGS),
            tool_use_turn("QAReport", qa_args(status="PASS")),
        ]
    )
    client = StubSubstrateClient()

    run_writer(build_writer_agent(model, client), _first_attempt())
    run_writer(build_writer_agent(model, client), _audited_attempt())
    run_qa_legal(build_qa_legal_agent(model, client), _drafted_attempt())

    assert worker_prompts(model, WRITER_PROMPT_SECTION) == [sent_text(model, 0), sent_text(model, 1)]
    assert worker_prompts(model, QA_LEGAL_PROMPT_SECTION) == [sent_text(model, 2)]


# ---------------------------------------------------------------------------
# Reasoning effort reaches the telemetry (Approach 1 D24)
# ---------------------------------------------------------------------------


def _runner_effort_default(runner: object) -> str | None:
    """The ``reasoning_effort`` default declared on one worker runner."""
    parameter = inspect.signature(runner).parameters["reasoning_effort"]
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    return parameter.default


def test_each_runner_defaults_to_its_role_reasoning_effort() -> None:
    """The role constant is the *default*; the caller passes the resolved value."""
    assert _runner_effort_default(run_scout) is SCOUT_REASONING_EFFORT
    assert _runner_effort_default(run_writer) == WRITER_REASONING_EFFORT
    assert _runner_effort_default(run_qa_legal) == QA_LEGAL_REASONING_EFFORT

    # The settled values, stated literally so a silent constant edit is caught.
    assert _runner_effort_default(run_writer) == "high"
    assert _runner_effort_default(run_qa_legal) == "medium"
    assert _runner_effort_default(run_scout) is None


def test_fresh_agent_per_invocation_reports_per_call_telemetry() -> None:
    """D20 regression guard: ``EventLoopMetrics`` accumulate per ``Agent`` object.

    ``reset_usage_metrics()`` does not clear ``accumulated_usage``, so reusing one
    ``Agent`` across two Writer calls reports call 2 as *call 1 + call 2* — a silent
    telemetry doubling. Every tool wrapper must therefore build a fresh ``Agent`` per
    sub-agent call (D-G), and this test pins both halves of that fact.
    """
    turns = [
        tool_use_turn("ArticleDraft", DRAFT_ARGS, input_tokens=10, output_tokens=5),
        tool_use_turn("ArticleDraft", DRAFT_ARGS, input_tokens=20, output_tokens=10),
    ]
    candidate = ScoutCandidate.model_validate(
        scout_candidate_args("inail-2024-circ-calore", 0.9, "Obblighi immediati.")
    )
    record = AttemptRecord(context=AgentContext(today=date(2026, 9, 23)), candidate=candidate, attempt=1)

    # Fresh agent per invocation — what the tool wrappers do.
    model = ScriptedModel(turns)
    client = StubSubstrateClient()
    first = run_writer(build_writer_agent(model, client), record)
    second = run_writer(build_writer_agent(model, client), record)

    assert first.telemetry.input_tokens == 10
    assert first.telemetry.total_tokens == 15
    assert second.telemetry.input_tokens == 20
    assert second.telemetry.total_tokens == 30
    assert first.telemetry.cycles == 1 and second.telemetry.cycles == 1

    # The behaviour that forces the rule: one reused agent accumulates instead.
    reused_model = ScriptedModel(
        [
            tool_use_turn("ArticleDraft", DRAFT_ARGS, input_tokens=10, output_tokens=5),
            tool_use_turn("ArticleDraft", DRAFT_ARGS, input_tokens=20, output_tokens=10),
        ]
    )
    reused_agent = build_writer_agent(reused_model, client)
    run_writer(reused_agent, record)
    accumulated = run_writer(reused_agent, record)

    assert accumulated.telemetry.input_tokens == 30
    assert accumulated.telemetry.cycles == 2


def test_agents_module_contains_no_loop_state() -> None:
    """Source-level guard: no loop counters, no ceilings and no ``while`` in executable code.

    Not a Red-Green cycle: this is an executable architectural constraint rather
    than TDD evidence (AGENTS.md Rule 2: code never sequences the sub-agents). Its
    value is prospective — it fails the moment loop state is added to this module.

    The check is over the AST rather than the raw text, because the Scout's system
    prompt must legitimately mention ``max_drafts`` in order to instruct the Scout to
    apply it. Only executable code is inspected.
    """
    module_path = Path(__file__).resolve().parents[2] / "src" / "agents.py"
    tree = ast.parse(module_path.read_text(encoding="utf-8"))

    forbidden = {"attempts", "max_drafts"}
    offending: list[str] = []
    for node in ast.walk(tree):
        assert not isinstance(node, ast.While), "src/agents.py must contain no while loop"
        if isinstance(node, ast.Name) and node.id in forbidden:
            offending.append(node.id)
        elif isinstance(node, ast.Attribute) and node.attr in forbidden:
            offending.append(node.attr)
        elif isinstance(node, ast.arg) and node.arg in forbidden:
            offending.append(node.arg)
        elif isinstance(node, ast.keyword) and node.arg in forbidden:
            # Without this a call such as ``PipelineScope(max_drafts=1)`` slips through.
            offending.append(node.arg)
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) and node.name in forbidden:
            offending.append(node.name)

    assert offending == [], f"src/agents.py references orchestrator loop state: {offending}"


def test_agents_module_exports_public_surface() -> None:
    """``__all__`` is declared, complete, and every name resolves; nothing of the ScopeParser remains."""
    expected = {
        "SCOUT_REASONING_EFFORT",
        "WRITER_REASONING_EFFORT",
        "QA_LEGAL_REASONING_EFFORT",
        "SCOUT_MODEL_ID",
        "WRITER_MODEL_ID",
        "QA_LEGAL_MODEL_ID",
        "SCOUT_TOOL_NAMES",
        "WRITER_TOOL_NAMES",
        "QA_LEGAL_TOOL_NAMES",
        "SCOUT_SYSTEM_PROMPT",
        "WRITER_SYSTEM_PROMPT",
        "QA_LEGAL_SYSTEM_PROMPT",
        "extract_telemetry",
        "build_scout_agent",
        "build_writer_agent",
        "build_qa_legal_agent",
        "run_scout",
        "run_writer",
        "run_qa_legal",
    }

    assert set(agents_module.__all__) == expected
    for name in agents_module.__all__:
        assert hasattr(agents_module, name), f"__all__ names missing attribute {name}"
    assert not [name for name in vars(agents_module) if "SCOPE_PARSER" in name.upper()]


# ---------------------------------------------------------------------------
# Scout system prompt (byte-identical to Approach 1's)
# ---------------------------------------------------------------------------


def test_scout_prompt_passes_the_resolved_bounds_through_untouched() -> None:
    """The Scout stops reasoning about dates: it forwards the bounds it is given."""
    prompt = SCOUT_SYSTEM_PROMPT
    flat = _flat(prompt)

    assert "scope.date_from" in prompt
    assert "scope.date_to" in prompt
    # Named as the substrate arguments they become, not as free-form guidance.
    assert "`date_from`" in prompt and "`date_to`" in prompt
    assert "list_regulatory_updates" in prompt
    # And explicitly forbidden from second-guessing them.
    assert "never" in flat.split("scope.date_from", 1)[1].split("2.", 1)[0]

    # The Phase 5 selection rules are untouched.
    assert "scope.max_drafts" in prompt
    assert "score and rank every qualifying update before truncating" in flat


def test_scout_prompt_assigns_candidate_selection_to_the_scout() -> None:
    """The Scout prompt must instruct the top-N selection, and stop denying it.

    The previous prompt told the Scout to "ignore it entirely" and called returning
    fewer candidates than qualify "a Rule 4 violation". Rule 4 says no such thing;
    that clause was a derived artifact asserting more than its source.
    """
    prompt = SCOUT_SYSTEM_PROMPT
    flat = _flat(prompt)

    assert "scope.max_drafts" in prompt
    assert "descending" in flat and "newsworthiness_score" in prompt
    # It truncates when bound, and returns everything when it is not.
    assert "top" in flat and "null" in flat
    # Scoring is never skipped to save effort: rank everything, then truncate.
    assert "score and rank every qualifying update before truncating" in flat

    # The two clauses that claimed the orchestrator owns the ceiling are gone.
    assert "ignore it entirely" not in flat
    assert "the orchestrator, never you, applies any ceiling" not in flat


def test_scout_prompt_declares_role_boundary() -> None:
    """The Scout prompt names its output model and states its explicit non-goals (D19)."""
    prompt = SCOUT_SYSTEM_PROMPT
    lowered = prompt.lower()

    assert "ScoutReport" in prompt
    assert "newsworthiness_score" in prompt
    assert "non-goals" in lowered
    # Does not draft.
    assert "do not write" in lowered or "do not draft" in lowered
    # Does not audit citations.
    assert "citation" in lowered
    # Does not limit candidate count.
    assert "max_drafts" in prompt
    assert "never" in lowered


# ---------------------------------------------------------------------------
# QA-Legal system prompt (byte-identical to Approach 1's)
# ---------------------------------------------------------------------------


def test_qa_legal_prompt_declares_role_boundary() -> None:
    """The QA prompt names its output model, the tri-state semantics, and its non-goals."""
    prompt = QA_LEGAL_SYSTEM_PROMPT
    lowered = prompt.lower()

    assert "QAReport" in prompt
    for status in ("PASS", "WARNING", "ERROR"):
        assert status in prompt
    assert "verify_legal_citation" in prompt
    assert "get_document_by_id" in prompt
    assert "non-goals" in lowered
    # Never rewrites prose, never proposes copy, never selects CTAs.
    assert "rewrite" in lowered
    assert "cta" in lowered or "call to action" in lowered
    assert "never" in lowered


def test_qa_legal_prompt_starts_the_audit_from_the_source_doc_id() -> None:
    """Statutory checking begins with the draft's own provenance, then widens.

    The ``verify_legal_citation`` -> ``verified_against_doc_id`` path stays: that
    is how *related* instruments are resolved. What changes is that the draft's
    own source no longer has to be inferred from citation text.
    """
    prompt = QA_LEGAL_SYSTEM_PROMPT
    flat = _flat(prompt)

    assert "get_document_by_id(draft.source_doc_id)" in prompt
    assert "key_obligations" in prompt and "penalties_summary" in prompt
    # Never minted from citation text — the failure mode the live run exhibited.
    assert "never build a doc id from citation text" in flat
    # The related-instrument path is preserved.
    assert "verified_against_doc_id" in prompt
    # An unfetchable source is reported, not papered over.
    assert (
        "if `source_doc_id` is empty or the fetch fails, say so in `issues` and return `error`"
    ) in flat


def test_qa_legal_prompt_checks_temporal_accuracy() -> None:
    """Temporal accuracy joins citation existence and statutory grounding as a check.

    The two pre-existing checks must survive the addition: a third axis is not a
    replacement for either.
    """
    flat = _flat(QA_LEGAL_SYSTEM_PROMPT)

    assert "### 4. temporal accuracy" in flat
    assert "the user turn states the current date" in flat
    assert "advises preparing for a window that has already opened" in flat
    assert "future tense about a date already past" in flat
    # Graded, not a blanket verdict.
    assert "`warning` where the framing is merely stale" in flat
    assert "`error` where it would lead the reader to miss or misjudge a deadline" in flat

    # The original two checks are untouched.
    assert "### 2. every citation" in flat
    assert "### 3. every statutory statement" in flat


def test_qa_legal_prompt_treats_a_flag_on_an_in_force_citation_as_the_defect() -> None:
    """Checking a Writer flag is only half an instruction; QA needs a verdict too.

    QA-Legal is told to treat a flagged reference as one to check and never as one
    to accept. That covers the citation being bad. It says nothing about the case
    the live runs actually produced: QA calls ``verify_legal_citation``, the
    citation comes back in force, and the draft still ships a ``riferimento da
    verificare`` hedge on a verifiably valid reference. Without this sentence the
    hedge survives the audit, because nothing tells QA that the *flag* is what is
    wrong.
    """
    flat = _flat(QA_LEGAL_SYSTEM_PROMPT)

    # The standing half — a flag is a prompt to check, not a licence to accept.
    assert (
        "treat any reference the writer flagged as unverified as a citation to check, "
        "never as one to accept"
    ) in flat
    # The new half — what to conclude when the check comes back positive.
    assert "if your call verifies it, the hedge is the defect" in flat
    # And the status contract files a hedged valid reference under WARNING.
    assert "hedged valid references" in flat
    # Graded and actionable: the Writer must drop the hedge, not the citation.
    assert "report it as `warning`, name the hedged sentence" in flat
    assert "removes the hedge rather than the citation" in flat


def test_qa_legal_prompt_checks_citations_against_the_sources_related_citations() -> None:
    """``verify_legal_citation`` answers existence, never relevance.

    It takes no document parameter, so a citation that is real but has nothing to
    do with the instrument under discussion passes it. ``RegulatoryDocument``
    carries ``related_citations`` — the authoritative list of what the source
    actually references — and it appeared twice in the Writer's prompt and not
    once in QA-Legal's, so no stage compared the two.
    """
    prompt = QA_LEGAL_SYSTEM_PROMPT
    flat = _flat(prompt)

    assert "related_citations" in prompt
    # The source's related citations are resolved to canonicals up front ...
    assert "call `verify_legal_citation` once on each entry of the source's `related_citations`" in flat
    assert "these canonicals are the instruments the source actually relies on" in flat
    # ... and a draft citation outside them is the draft's own introduction.
    assert "a citation not tied to the source is one the draft has introduced on its own" in flat
    # Graded by what the draft rests on it.
    assert "`warning` where it is plausible supporting context" in flat
    assert "`error` where a legal effect, obligation, penalty or deadline is asserted on it" in flat
    # The escape hatch: a citation tied to the source through a verified doc ID.
    assert "its `verified_against_doc_id` equals `draft.source_doc_id`" in flat
    # An additional axis, never a whitelist that launders a misdescribed citation.
    assert "`related_citations` is not a whitelist" in flat


def test_qa_legal_prompt_keeps_its_three_grounding_fields() -> None:
    """The provenance check is added to task 2, not substituted for it.

    ``key_obligations``, ``penalties_summary`` and ``status`` are what the audit
    compares the draft's claims against; a new axis that quietly displaced any of
    them would trade one blind spot for another.
    """
    prompt = QA_LEGAL_SYSTEM_PROMPT

    for field in ("key_obligations", "penalties_summary", "status"):
        assert field in prompt, field
    assert "get_document_by_id(draft.source_doc_id)" in prompt


# ---------------------------------------------------------------------------
# Writer system prompt (Approach 1's, reworded only where it names its input)
# ---------------------------------------------------------------------------


def test_writer_prompt_declares_role_boundary() -> None:
    """The Writer prompt names its output model, the CTA duty, and its non-goals (D19)."""
    prompt = WRITER_SYSTEM_PROMPT
    lowered = prompt.lower()

    assert "ArticleDraft" in prompt
    assert "get_tdi_service_offerings" in prompt
    assert "tdi_cta" in prompt
    assert "non-goals" in lowered
    # Issues no compliance verdict.
    assert "verdict" in lowered
    assert "qa-legal" in lowered
    # Never silently drops an unverifiable citation: keep it and flag it.
    assert "never" in lowered
    assert "flag" in lowered
    assert "citation" in lowered


def test_writer_prompt_gates_every_claim_on_a_citation_verification() -> None:
    """Item 1: ``verify_legal_citation`` is mandatory and gating, not discretionary.

    The Phase 7 live run shows why. The Writer's old Method made verification
    optional ("you **may** call ``verify_legal_citation`` to check a reference you
    are unsure of"), and the draft it produced asserted a CIGO entitlement on
    ``Messaggio INPS n. 2729/2023`` — a citation the substrate does not recognise
    at all. QA-Legal's verdict was that "some legal-effect/sanction statements are
    overstated or incomplete versus the source metadata".
    """
    prompt = WRITER_SYSTEM_PROMPT
    flat = _flat(prompt)

    assert "verify_legal_citation" in prompt
    # Gating, and stated as an imperative rather than a permission — covering every
    # citation the draft will contain, not only the doubtful ones.
    assert (
        "**verify before you assert.** call `verify_legal_citation` once for each "
        "distinct citation the draft will contain"
    ) in flat
    assert "you may call `verify_legal_citation`" not in flat
    # The call precedes the claim it supports.
    assert "before writing any claim that rests on it" in flat


def test_writer_prompt_gives_the_real_related_document_resolution_path() -> None:
    """Item 1: ``verified_against_doc_id`` is the only route to a related instrument.

    ``RegulatoryDocument.related_citations`` holds citation *strings*, not substrate
    slugs, so "call ``get_document_by_id`` for a related instrument" was never
    implementable as written. QA-Legal proved it live by minting
    ``messaggio-inps-2729-2023`` and ``decreto-legislativo-81-2008-articolo-28``
    out of citation text and taking three ``ValueError``s for it.
    """
    prompt = WRITER_SYSTEM_PROMPT
    flat = _flat(prompt)

    assert "verified_against_doc_id" in prompt
    # The resolution path: the ID ``verify_legal_citation`` returns, and only that.
    assert "when `verify_legal_citation` returns a non-null `verified_against_doc_id`" in flat
    assert "call `get_document_by_id` on that id" in flat
    assert "related_citations" in prompt
    # The prohibition on minting an ID out of citation text.
    assert "never construct a doc id from a citation string" in flat


def test_writer_prompt_forbids_legal_effect_on_an_unverified_citation() -> None:
    """Item 1: an unrecognised citation is kept and flagged, but carries no obligation.

    The existing non-goal against silently dropping a doubtful citation is
    preserved — deleting it would hide the signal QA-Legal exists to catch — and
    is now paired with the complementary constraint: keeping it does not licence
    asserting a legal effect on it.
    """
    prompt = WRITER_SYSTEM_PROMPT
    flat = _flat(prompt)

    assert "riferimento da verificare" in flat
    assert "is_valid" in prompt and "unrecognized" in prompt
    assert "assert no legal effect, penalty, deadline or threshold on it" in flat
    # Positive statements are bounded by what a *resolved* document supports.
    assert (
        "state penalties, sanctions, deadlines, amounts, percentages and thresholds only "
        "where the source document or a related document you reached through step 5 "
        "supports them"
    ) in flat

    # The pre-existing non-goal is not weakened by any of the above.
    non_goals = flat.split("## non-goals", 1)[1]
    assert (
        "you do not silently drop a citation the source relies on because you could not verify it"
    ) in non_goals
    assert "you do not invent facts, obligations, deadlines, penalties or citations" in non_goals
    # Keeping an unverified citation is not licence to rest an obligation on it.
    assert "keeping it is not licence to rely on it" in non_goals


def test_writer_prompt_mandates_fetching_its_own_source() -> None:
    """Method step 1 is a gating ``get_document_by_id``, not an optional lookup.

    The live Phase 7 run never exercised the Writer's fetch path at all: the
    orchestrator hydrated the document and the prompt told the Writer there was
    "nothing to fetch for your own subject". That clause must be gone, and the
    candidate's own fields (its triage ``summary`` included) must be explicitly
    disqualified as a substitute for the fetched source.
    """
    prompt = WRITER_SYSTEM_PROMPT
    flat = _flat(prompt)

    assert "get_document_by_id(update.doc_id)" in prompt
    assert "calling `get_document_by_id(update.doc_id)` is mandatory and gating" in flat
    assert "before any other tool call and before you write a single sentence" in flat
    # The article is written from the fetched document's substance.
    assert "content_markdown" in prompt
    assert "key_obligations" in prompt
    assert "penalties_summary" in prompt
    # The candidate's fields are not a substitute for the source.
    assert "the candidate's own fields do not replace this fetch" in flat
    # And the superseded claim is gone.
    assert "you are given it in full" not in flat


def test_writer_prompt_requires_the_source_doc_id_to_be_echoed_exactly() -> None:
    """``source_doc_id`` is copied from the input, never invented or reformatted.

    It is the only provenance the draft carries, and QA-Legal's audit now starts
    from it, so a reformatted slug is as bad as a missing one. A failed fetch has
    a defined output — the empty string — rather than an invented article.
    """
    prompt = WRITER_SYSTEM_PROMPT
    flat = _flat(prompt)

    assert "`source_doc_id`" in prompt
    assert "copied exactly from the input candidate's `update.doc_id`" in flat
    assert "never invented, reformatted or derived from citation text" in flat
    # A failed fetch has a defined output, not an invented article.
    assert "do not invent an article and do not fall back to the candidate" in flat
    assert "`source_doc_id` set to the empty string" in flat


def test_writer_prompt_makes_the_current_date_load_bearing() -> None:
    """A bare date in the turn is not self-evidently actionable; the rule makes it so.

    A date printed in the source document is not necessarily in the future, and
    the live run shows the Writer treating it as though it always is.
    """
    flat = _flat(WRITER_SYSTEM_PROMPT)

    # The prompt bolds the step's lead-in, so the closing ``**`` sits mid-clause.
    assert "write from the current date,** which the user turn states" in flat
    assert "a date in the source is not necessarily in the future" in flat
    assert "where a window has already opened, say that it is open" in flat
    assert "where a deadline has passed, say so rather than advising preparation for it" in flat
    assert "never write in the future tense about something that has already happened" in flat


def test_writer_prompt_gates_the_unverified_flag_on_an_actual_tool_result() -> None:
    """``riferimento da verificare`` is a claim about a call, not about a hunch.

    ``draft_20260923_002`` stamped the flag on two citations and spent its whole
    three-attempt budget on the ERROR loop that followed, because QA-Legal is
    instructed to treat a Writer-flagged reference as one to check. The flag has
    to cost the Writer a tool call before it costs the pipeline a rewrite.

    The rewritten prompt enforces this procedurally rather than with an explicit
    "only when" clause: step 4 submits every citation to ``verify_legal_citation``,
    and step 6's flag is conditioned on the citation being *still unrecognized
    after the retry* — a state that exists only as a tool result.
    """
    flat = _flat(WRITER_SYSTEM_PROMPT)

    # Every citation is submitted, so none can be flagged without a call.
    assert "call `verify_legal_citation` once for each distinct citation the draft will contain" in flat
    # The flag's trigger is a tool status after a retry, not a hunch.
    assert (
        'if a citation the source relies on is still unrecognized after the retry, keep it '
        'in the text and flag it inline with "riferimento da verificare"'
    ) in flat
    # A near miss on wording is a retry, not a verdict.
    assert '`status: "unrecognized"`: retry once in the form the source document writes it' in flat
    # A positive result with an article-level note is not grounds for a flag either.
    assert "is a successful verification, not a doubt" in flat

    # The framing that licensed the sloppiness is gone.
    assert "routinely include references the substrate does not recognise" not in flat
    assert "this is the ordinary case, not an edge case" not in flat
    # And so is the empirical prior that replaced it: against the committed
    # 18-entry registry it is false, and biasing the Writer toward under-flagging
    # is the wrong direction of error for a compliance pipeline. The rule's force
    # is procedural -- a flag costs a call -- not statistical.
    assert "most references" not in flat


def test_writer_prompt_still_keeps_and_flags_a_genuinely_unrecognised_citation() -> None:
    """Tightening the flag must not turn into licence to delete the reference.

    Both halves of the original contract are downstream dependencies: the literal
    marker text, and the prohibition on silently dropping what could not be
    verified.
    """
    flat = _flat(WRITER_SYSTEM_PROMPT)

    assert "riferimento da verificare" in flat
    assert 'keep it in the text and flag it inline with "riferimento da verificare"' in flat
    assert "assert no legal effect, penalty, deadline or threshold on it" in flat
    non_goals = flat.split("## non-goals", 1)[1]
    assert (
        "you do not silently drop a citation the source relies on because you could not verify it"
    ) in non_goals


# ---------------------------------------------------------------------------
# Cross-cutting prompt guards
# ---------------------------------------------------------------------------

_ALL_WORKER_PROMPTS: dict[str, str] = {
    "Scout": SCOUT_SYSTEM_PROMPT,
    "Writer": WRITER_SYSTEM_PROMPT,
    "QA-Legal": QA_LEGAL_SYSTEM_PROMPT,
}

_PROMPT_OUTPUT_MODELS: dict[str, str] = {
    "Scout": "ScoutReport",
    "Writer": "ArticleDraft",
    "QA-Legal": "QAReport",
}


def test_all_worker_prompts_declare_structured_output_model() -> None:
    """Every worker prompt names the structured output model it must emit (D8)."""
    for worker, prompt in _ALL_WORKER_PROMPTS.items():
        assert _PROMPT_OUTPUT_MODELS[worker] in prompt, f"{worker} prompt does not name its output model"


def test_all_worker_prompts_declare_non_goals() -> None:
    """D19 enforcement: with tools unscoped, the prompt is the only role boundary."""
    for worker, prompt in _ALL_WORKER_PROMPTS.items():
        lowered = prompt.lower()
        assert "## non-goals" in lowered, f"{worker} prompt has no non-goals section"

        section = lowered.split("## non-goals", 1)[1]
        bullets = [line for line in section.splitlines() if line.strip().startswith("-")]
        assert len(bullets) >= 3, f"{worker} non-goals section is too thin: {len(bullets)} item(s)"
        assert "you do not" in section, f"{worker} non-goals section does not state what it must not do"
