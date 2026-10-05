"""``src.app.run``: one run, from the user's prompt to its exit code (IMPLEMENTATION_PLAN.md Iteration 14).

SPECIFICATIONS.md §4, D-B, D-D, D-H, D-I, §6.10 and §7.6, with P6, P12 and P13. Every model is a
:class:`ScriptedModel` or a :class:`FailingModel` (P4), injected through ``model_builder``. Most runs use an offline
substrate session behind the real ``HSEMockMCPClient``, whose ``__enter__`` and ``__exit__`` stay in the path; the
tests marked as using the live local substrate spawn it over stdio, which costs no model token.

Scripted runs give the Supervisor the effort ``low`` through ``reasoning_settings``, so the builder can tell its
model from QA-Legal's, which is also ``gpt-5.4`` at ``medium`` by default; one test checks the defaults themselves.
"""

import logging
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Final

import pytest
from strands.models.model import Model
from strands.types.exceptions import MCPClientInitializationError

import src.app as app_module
from src.agents import QA_LEGAL_MODEL_ID, SCOUT_MODEL_ID, WRITER_MODEL_ID
from src.app import run
from src.costs import load_model_rates
from src.credentials import CredentialManager, ReasoningSettings
from src.guardrails import QA_TOOL, SAVE_DRAFT_TOOL, SCOUT_TOOL, WRITER_TOOL
from src.logging_setup import CorrelationFilter
from src.mcp_client import HSEMockMCPClient, MCPClientError, MCPClientNotConnectedError, MCPConnectionError
from src.model_factory import ModelBuilder, build_model
from src.schemas import ExitCode, FailureRecord, PipelineConfig, RunState
from src.supervisor import SUPERVISOR_MODEL_ID, build_supervisor_prompt
from src.telemetry import estimate_cost
from src.tools import MCP_LAUNCH_COMMAND
from tests.support.scripted import (
    DEFAULT_DOC_ID,
    SCOPE_DATE_FROM,
    SCOPE_DATE_TO,
    FailingModel,
    OfflineSubstrateSession,
    ScriptedModel,
    offline_client,
    pipeline_config,
    qa_args,
    scout_report_args,
    scripted_model_builder,
    scripted_model_builder_by_effort,
    sent_text,
    text_turn,
    tool_use_turn,
    writer_turns,
)

#: The run's current date; the scope below is the past 3 months back from it.
TODAY: Final[date] = date(2026, 9, 22)
#: The user's prompt, passed to the Supervisor verbatim.
PROMPT: Final[str] = "Analyze recent INAIL updates on heat stress"
#: The scope a Supervisor builds from ``PROMPT`` on ``TODAY``.
SCOPE: Final[dict[str, Any]] = {
    "date_from": SCOPE_DATE_FROM,
    "date_to": SCOPE_DATE_TO,
    "sources": ["INAIL"],
    "sector_constraints": [],
    "max_drafts": None,
}
SUMMARY: Final[str] = f"Saved: {DEFAULT_DOC_ID} (PASS, attempt 1). Skipped: none. Unfinished: none."
#: The Supervisor's effort in scripted runs: not QA-Legal's ``medium``, so the two models are built apart.
SUPERVISOR_EFFORT: Final[str] = "low"


def _scout_finds(*doc_ids: str) -> list[list[dict[str, Any]]]:
    """The Scout's script: one substrate listing, then its report on ``doc_ids``."""
    return [
        tool_use_turn("list_regulatory_updates", {"source": "INAIL"}),
        tool_use_turn("ScoutReport", scout_report_args(*doc_ids)),
    ]


def _one_document_flow(doc_id: str = DEFAULT_DOC_ID) -> list[list[dict[str, Any]]]:
    """The Supervisor's tool calls for one document: scout, write, audit, save."""
    return [
        tool_use_turn(SCOUT_TOOL, SCOPE),
        tool_use_turn(WRITER_TOOL, {"doc_id": doc_id, "revise": False}),
        tool_use_turn(QA_TOOL, {"doc_id": doc_id}),
        tool_use_turn(SAVE_DRAFT_TOOL, {"doc_id": doc_id}),
    ]


@dataclass
class _Run:
    """One scripted run: its result, and everything a test inspects about how it was reached."""

    state: RunState
    session: OfflineSubstrateSession
    supervisor: Model
    scout: ScriptedModel
    writer: ScriptedModel
    qa_legal: ScriptedModel
    factory_calls: list[HSEMockMCPClient] = field(default_factory=list)


def _run(
    tmp_path: Path,
    *,
    supervisor: Sequence[Any] | Model,
    scout: Sequence[Any] = (),
    writer: Sequence[Any] = (),
    qa_legal: Sequence[Any] = (),
    session: OfflineSubstrateSession | None = None,
    config: PipelineConfig | None = None,
    prompt: str = PROMPT,
) -> _Run:
    """Run ``run`` over an offline session, with each role on its own scripted model."""
    session = session if session is not None else OfflineSubstrateSession()
    supervisor_model = supervisor if isinstance(supervisor, Model) else ScriptedModel(supervisor)
    models = {
        "scout": ScriptedModel(scout),
        "writer": ScriptedModel(writer),
        "qa_legal": ScriptedModel(qa_legal),
    }
    factory_calls: list[HSEMockMCPClient] = []

    def client_factory() -> HSEMockMCPClient:
        client = offline_client(session)
        factory_calls.append(client)
        return client

    state = run(
        prompt,
        config if config is not None else pipeline_config(tmp_path),
        client_factory=client_factory,
        model_builder=scripted_model_builder_by_effort(
            {
                (SCOUT_MODEL_ID, None): models["scout"],
                (WRITER_MODEL_ID, "high"): models["writer"],
                (QA_LEGAL_MODEL_ID, "medium"): models["qa_legal"],
                (SUPERVISOR_MODEL_ID, SUPERVISOR_EFFORT): supervisor_model,
            }
        ),
        clock=lambda: TODAY,
        reasoning_settings=ReasoningSettings(HSE_MODEL_SUPERVISOR_REASONING_EFFORT=SUPERVISOR_EFFORT),
    )
    return _Run(state, session, supervisor_model, factory_calls=factory_calls, **models)


def _stages(state: RunState) -> list[str]:
    """The stage of every failure the run recorded, in order."""
    return [failure.stage for failure in state.failures]


def _drafts_on_disk(state: RunState) -> list[Path]:
    """The draft files in the run's drafts folder, by name."""
    drafts_dir = state.config.drafts_dir
    return sorted(drafts_dir.glob("draft_*.md")) if drafts_dir.exists() else []


# ---------------------------------------------------------------------------
# SUCCESS (0)
# ---------------------------------------------------------------------------


def test_one_document_saved_with_pass_exits_success_and_renders_its_draft(tmp_path: Path) -> None:
    """§7.6 "otherwise": one document audited ``PASS`` and saved is rendered at run end, and the run exits 0."""
    result = _run(
        tmp_path,
        supervisor=[*_one_document_flow(), text_turn(SUMMARY)],
        scout=_scout_finds(DEFAULT_DOC_ID),
        writer=writer_turns(DEFAULT_DOC_ID),
        qa_legal=[tool_use_turn("QAReport", qa_args(status="PASS"))],
    )

    state = result.state
    assert state.exit_code is ExitCode.SUCCESS
    assert state.supervisor_summary == SUMMARY
    assert _stages(state) == []
    drafts = sorted((tmp_path / "drafts").glob("draft_*.md"))
    assert [path.name for path in drafts] == [f"draft_{TODAY:%Y%m%d}_001.md"]
    assert "Approach 2 (Research Analyst)" in drafts[0].read_text(encoding="utf-8")
    assert [entry.stage for entry in state.ledger] == ["scout", "writer", "qa_legal", "supervisor"]


# ---------------------------------------------------------------------------
# CONFIG_ERROR (5): settings cannot be resolved; the run never starts
# ---------------------------------------------------------------------------

#: Credentials that resolve but point nowhere: models built on them open no socket, and none is ever called.
_UNREACHABLE_CREDENTIALS: Final[dict[str, str]] = {
    "HSE_MODEL_FAST_ENDPOINT": "https://fast.example.invalid/openai/v1",
    "HSE_MODEL_FAST_API_KEY": "sk-fast-not-a-real-key",
    "HSE_MODEL_STRONG_ENDPOINT": "https://strong.example.invalid/openai/v1",
    "HSE_MODEL_STRONG_API_KEY": "sk-strong-not-a-real-key",
}


def _unconfigured_model_builder(model_id: str, *, reasoning_effort: str | None = None) -> Model:
    """Reproduce an unconfigured checkout: ``CredentialManager`` rejects an environment with no credentials.

    Approach 1's helper: exactly the ``ValidationError`` ``build_model`` raises on a fresh clone, not a stand-in.
    """
    CredentialManager(_env_file=None)
    raise AssertionError("unreachable: CredentialManager must reject an unconfigured environment")


def _unreachable_model_builder(model_id: str, *, reasoning_effort: str | None = None) -> Model:
    """The real ``build_model`` over unreachable credentials, so its effort check is the one that speaks."""
    return build_model(
        model_id, CredentialManager(_env_file=None, **_UNREACHABLE_CREDENTIALS), reasoning_effort=reasoning_effort
    )


def _no_session() -> HSEMockMCPClient:
    """A client factory that fails the test: a run that cannot be configured opens no session."""
    raise AssertionError("a run that cannot be configured must not open the substrate session")


def _unconfigured_run(
    tmp_path: Path, model_builder: ModelBuilder, reasoning_settings: ReasoningSettings | None = None
) -> RunState:
    """Run ``run`` with settings that cannot be resolved."""
    return run(
        PROMPT,
        pipeline_config(tmp_path),
        client_factory=_no_session,
        model_builder=model_builder,
        clock=lambda: TODAY,
        reasoning_settings=reasoning_settings,
    )


def _assert_configuration_failure(state: RunState, caplog: pytest.LogCaptureFixture, detail: str) -> None:
    """Exit 5, one ``configuration`` failure, its ERROR naming ``detail``, and nothing run or rendered."""
    assert state.exit_code is ExitCode.CONFIG_ERROR
    assert _stages(state) == ["configuration"]
    assert state.ledger == [] and state.documents == {} and state.supervisor_summary is None
    errors = [r for r in caplog.records if r.levelno == logging.ERROR and r.name == "src.app"]
    assert [r.getMessage().split(":")[0] for r in errors] == ["Configuration failure"]
    assert errors[0].exc_info is not None
    assert detail in caplog.text
    assert "Supervisor telemetry unavailable" not in caplog.text  # finalise_run never ran
    assert _drafts_on_disk(state) == []


def test_unresolved_credentials_exit_config_error_before_any_session(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """No credentials: the run never starts, and the full pydantic report is logged (D-I)."""
    with caplog.at_level(logging.INFO):
        state = _unconfigured_run(tmp_path, _unconfigured_model_builder)
    _assert_configuration_failure(state, caplog, "HSE_MODEL_FAST_API_KEY")
    assert state.failures[0].error_type == "pydantic_core._pydantic_core.ValidationError"


def test_an_invalid_cost_rate_exits_config_error_before_any_model_is_built(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A rate ``CostSettings`` rejects is a configuration failure: the run is never priced, so never started."""
    monkeypatch.setenv("HSE_COST_STRONG_INPUT_USD_PER_MTOK", "-1")
    built: list[str] = []

    def recording_builder(model_id: str, *, reasoning_effort: str | None = None) -> Model:
        built.append(model_id)
        return ScriptedModel([])

    with caplog.at_level(logging.INFO):
        state = _unconfigured_run(tmp_path, recording_builder)
    _assert_configuration_failure(state, caplog, "HSE_COST_STRONG_INPUT_USD_PER_MTOK")
    assert built == []


def test_an_unknown_reasoning_effort_exits_config_error(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """``build_model`` rejects an effort the provider does not accept, before any token is spent (D24)."""
    settings = ReasoningSettings(HSE_MODEL_SUPERVISOR_REASONING_EFFORT="bogus")
    with caplog.at_level(logging.INFO):
        state = _unconfigured_run(tmp_path, _unreachable_model_builder, settings)
    _assert_configuration_failure(state, caplog, "Unknown reasoning effort 'bogus'")
    assert state.failures[0].error_type == "builtins.ValueError"


def test_a_model_builder_defect_is_not_a_configuration_failure(tmp_path: Path) -> None:
    """Only unresolved settings and a rejected effort are ``CONFIG_ERROR``: any other builder error leaves ``run``."""

    def defective_builder(model_id: str, *, reasoning_effort: str | None = None) -> Model:
        raise RuntimeError("builder defect")

    with pytest.raises(RuntimeError, match="builder defect"):
        _unconfigured_run(tmp_path, defective_builder)


# ---------------------------------------------------------------------------
# MCP_ERROR (2): the session fails to open
# ---------------------------------------------------------------------------


def _assert_session_never_opened(result: _Run, caplog: pytest.LogCaptureFixture) -> None:
    """Exit 2, one ``mcp_session`` failure, an ERROR naming the server and its launch, and nothing run."""
    state = result.state
    assert state.exit_code is ExitCode.MCP_ERROR
    assert _stages(state) == ["mcp_session"]
    assert state.ledger == [] and state.documents == {} and state.supervisor_summary is None
    assert isinstance(result.supervisor, ScriptedModel) and result.supervisor.turns_consumed == 0
    errors = [r for r in caplog.records if r.levelno == logging.ERROR and r.name == "src.app"]
    assert len(errors) == 1 and errors[0].exc_info is not None
    message = errors[0].getMessage()
    assert message.startswith("MCP session failed to open, or died mid-run")
    assert MCP_LAUNCH_COMMAND in message
    assert "Supervisor telemetry unavailable" not in caplog.text  # finalise_run never ran


def test_a_session_that_fails_to_start_exits_mcp_error(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """A spawn or handshake failure, classified by ``HSEMockMCPClient.start()``, ends the run before it begins."""
    session = OfflineSubstrateSession(fail_enter_with=MCPClientInitializationError("the server did not start"))
    with caplog.at_level(logging.INFO):
        result = _run(tmp_path, supervisor=[text_turn("must not be reached")], session=session)

    _assert_session_never_opened(result, caplog)
    assert result.state.failures[0].error_type == "src.mcp_client.MCPConnectionError"
    assert f"server_dir={result.factory_calls[0].server_dir}" in caplog.text
    assert session.events == ["enter"]


@pytest.mark.parametrize("error_type", [MCPConnectionError, MCPClientNotConnectedError])
def test_a_client_that_cannot_be_built_exits_mcp_error(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, error_type: type[MCPClientError]
) -> None:
    """The factory itself may raise either lost-session error (D-D), as Approach 1's tests have it; no client exists."""

    def failing_factory() -> HSEMockMCPClient:
        raise error_type("substrate unavailable")

    supervisor = ScriptedModel([text_turn("must not be reached")])
    with caplog.at_level(logging.INFO):
        state = run(
            PROMPT,
            pipeline_config(tmp_path),
            client_factory=failing_factory,
            model_builder=scripted_model_builder(ScriptedModel([]), supervisor),
            clock=lambda: TODAY,
        )

    unused = ScriptedModel([])
    _assert_session_never_opened(_Run(state, OfflineSubstrateSession(), supervisor, unused, unused, unused), caplog)


def test_a_session_whose_tool_listing_fails_exits_mcp_error_and_is_closed(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The composition root's own listing is the session's first use; when it fails, the session is still closed."""
    session = OfflineSubstrateSession(
        fail_listing_with=MCPClientInitializationError("the transport died"), fail_listing_on={0}
    )
    with caplog.at_level(logging.INFO):
        result = _run(tmp_path, supervisor=[text_turn("must not be reached")], session=session)

    _assert_session_never_opened(result, caplog)
    assert session.events == ["enter", "exit"]


# ---------------------------------------------------------------------------
# SUPERVISOR_ERROR (6): the Supervisor raises a provider or SDK error
# ---------------------------------------------------------------------------


def _supervisor_failures(state: RunState) -> list[FailureRecord]:
    """The run's ``supervisor`` failures."""
    return [failure for failure in state.failures if failure.stage == "supervisor"]


def _assert_supervisor_failure_logged(caplog: pytest.LogCaptureFixture, cause: str) -> None:
    """One ERROR "Supervisor invocation failed", carrying the full ``RemoteErrorDetail`` and the traceback (D-I)."""
    errors = [r for r in caplog.records if r.getMessage().startswith("Supervisor invocation failed")]
    assert len(errors) == 1
    assert errors[0].levelno == logging.ERROR and errors[0].name == "src.app"
    assert errors[0].exc_info is not None
    assert "cause_chain" in errors[0].getMessage() and cause in errors[0].getMessage()


def test_a_provider_error_after_a_save_exits_supervisor_error_and_still_renders(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The saved draft is rendered (§6.10), and the Supervisor's spent tokens reach the ledger (F1, §6.6)."""
    with caplog.at_level(logging.INFO):
        result = _run(
            tmp_path,
            supervisor=[*_one_document_flow(), RuntimeError("provider unavailable")],
            scout=_scout_finds(DEFAULT_DOC_ID),
            writer=writer_turns(DEFAULT_DOC_ID),
            qa_legal=[tool_use_turn("QAReport", qa_args(status="PASS"))],
        )

    state = result.state
    assert state.exit_code is ExitCode.SUPERVISOR_ERROR
    assert state.supervisor_summary is None
    [failure] = _supervisor_failures(state)
    assert _stages(state) == ["supervisor"]
    assert failure.remote is not None
    assert any("provider unavailable" in link for link in failure.remote.cause_chain)
    assert failure.traceback is not None and "RuntimeError: provider unavailable" in failure.traceback
    _assert_supervisor_failure_logged(caplog, "provider unavailable")
    assert len(_drafts_on_disk(state)) == 1
    [entry] = [entry for entry in state.ledger if entry.stage == "supervisor"]
    assert (entry.telemetry.model_id, entry.telemetry.reasoning_effort) == (SUPERVISOR_MODEL_ID, SUPERVISOR_EFFORT)
    assert entry.telemetry.total_tokens == 4 * 15  # the four tool-use turns it spent before failing


def test_a_supervisor_that_fails_on_its_first_turn_exits_supervisor_error_not_parser_error(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """It raised, so it did not end its own invocation: ``scope is None`` does not make it ``PARSER_ERROR`` (P13)."""
    failing = FailingModel(RuntimeError("provider unavailable"))
    with caplog.at_level(logging.INFO):
        result = _run(tmp_path, supervisor=failing)

    state = result.state
    assert state.exit_code is ExitCode.SUPERVISOR_ERROR
    assert state.scope is None and state.supervisor_summary is None
    assert _stages(state) == ["supervisor"]
    assert failing.invocations == 1
    _assert_supervisor_failure_logged(caplog, "provider unavailable")
    [entry] = [entry for entry in state.ledger if entry.stage == "supervisor"]
    assert entry.telemetry.total_tokens == 0


def test_a_supervisor_that_cannot_be_built_exits_supervisor_error_with_no_ledger_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """With no agent there are no metrics to read: ``finalise_run`` says so, and records no Supervisor entry."""

    def failing_builder(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("the SDK rejected the agent")

    monkeypatch.setattr(app_module, "build_supervisor_agent", failing_builder)
    with caplog.at_level(logging.INFO):
        result = _run(tmp_path, supervisor=[text_turn("must not be reached")])

    state = result.state
    assert state.exit_code is ExitCode.SUPERVISOR_ERROR
    assert _stages(state) == ["supervisor"]
    _assert_supervisor_failure_logged(caplog, "the SDK rejected the agent")
    assert state.ledger == []
    assert "Supervisor telemetry unavailable" in caplog.text


def test_an_interrupt_during_the_supervisor_leaves_run_and_still_closes_the_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``BaseException`` is not a Supervisor failure: an interrupt stops the process, and the ``with`` still closes."""

    def interrupted(*args: Any, **kwargs: Any) -> Any:
        raise KeyboardInterrupt

    monkeypatch.setattr(app_module, "run_supervisor", interrupted)
    session = OfflineSubstrateSession()
    with pytest.raises(KeyboardInterrupt):
        _run(tmp_path, supervisor=[text_turn("must not be reached")], session=session)
    assert session.events == ["enter", "exit"]


# ---------------------------------------------------------------------------
# MCP_ERROR (2): the session dies as it closes, after the run state exists
# ---------------------------------------------------------------------------


def test_a_session_lost_as_it_closes_exits_mcp_error_and_still_renders(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The run is over when the session dies on closing: the saved draft is still rendered, and the run exits 2."""
    session = OfflineSubstrateSession(fail_exit_with=MCPConnectionError("the transport died as it closed"))
    with caplog.at_level(logging.INFO):
        result = _run(
            tmp_path,
            supervisor=[*_one_document_flow(), text_turn(SUMMARY)],
            scout=_scout_finds(DEFAULT_DOC_ID),
            writer=writer_turns(DEFAULT_DOC_ID),
            qa_legal=[tool_use_turn("QAReport", qa_args(status="PASS"))],
            session=session,
        )

    state = result.state
    assert state.exit_code is ExitCode.MCP_ERROR
    assert state.fatal_error is None
    assert _stages(state) == ["mcp_session"]
    assert state.supervisor_summary == SUMMARY
    assert len(_drafts_on_disk(state)) == 1
    assert [entry.stage for entry in state.ledger][-1] == "supervisor"
    errors = [r for r in caplog.records if r.getMessage().startswith("MCP session failed to open, or died mid-run")]
    assert [r.name for r in errors] == ["src.app"]


def test_a_session_lost_as_it_closes_after_a_run_with_no_scout_is_parser_error(tmp_path: Path) -> None:
    """P13 and P6: the Supervisor ended on its own with no Scout, so ``PARSER_ERROR`` holds and outranks the 2."""
    session = OfflineSubstrateSession(fail_exit_with=MCPConnectionError("the transport died as it closed"))
    result = _run(tmp_path, supervisor=[text_turn("I cannot build a scope from this prompt.")], session=session)

    assert result.state.exit_code is ExitCode.PARSER_ERROR
    assert _stages(result.state) == ["mcp_session"]


# ---------------------------------------------------------------------------
# Logging (D-I, P12): the run's own events, and one run_id on every line
# ---------------------------------------------------------------------------


@pytest.fixture
def correlated_caplog(caplog: pytest.LogCaptureFixture) -> Iterator[pytest.LogCaptureFixture]:
    """``caplog`` at INFO, with the correlation filter ``configure_logging`` puts on every real handler."""
    correlation = CorrelationFilter()
    caplog.handler.addFilter(correlation)
    with caplog.at_level(logging.INFO):
        yield caplog
    caplog.handler.removeFilter(correlation)


def _event(caplog: pytest.LogCaptureFixture, event: str) -> list[logging.LogRecord]:
    """The records whose message opens with ``event``, as D-I names it."""
    return [record for record in caplog.records if record.getMessage().startswith(f"{event}:")]


def _happy_run(tmp_path: Path, config: PipelineConfig | None = None) -> _Run:
    """The one-document ``PASS`` run of the SUCCESS row."""
    return _run(
        tmp_path,
        supervisor=[*_one_document_flow(), text_turn(SUMMARY)],
        scout=_scout_finds(DEFAULT_DOC_ID),
        writer=writer_turns(DEFAULT_DOC_ID),
        qa_legal=[tool_use_turn("QAReport", qa_args(status="PASS"))],
        config=config,
    )


def test_run_started_logs_the_prompt_date_ceiling_level_and_every_model_and_effort(
    tmp_path: Path, correlated_caplog: pytest.LogCaptureFixture
) -> None:
    """D-I "Run started": ``run_id``, the raw prompt, the current date, ``--max-drafts``, log level, models, efforts."""
    result = _happy_run(tmp_path, pipeline_config(tmp_path, max_drafts=2, log_level="WARNING"))

    [record] = _event(correlated_caplog, "Run started")
    message = record.getMessage()
    assert record.name == "src.app" and record.levelno == logging.INFO
    for expected in (
        f"run_id={result.state.run_id}",
        f"prompt={PROMPT!r}",
        "today=2026-09-22",
        "max_drafts=2",
        "log_level=WARNING",
        "scout=gpt-5-mini/None",
        "writer=gpt-5.4/high",
        "qa_legal=gpt-5.4/medium",
        f"supervisor=gpt-5.4/{SUPERVISOR_EFFORT}",
    ):
        assert expected in message


def test_run_completed_logs_the_outcome_and_the_run_totals_once(
    tmp_path: Path, correlated_caplog: pytest.LogCaptureFixture
) -> None:
    """D-I "Run completed" and P12: exit code, counts, the run's total tokens and cost, wall-clock, the summary."""
    state = _happy_run(tmp_path).state

    [record] = _event(correlated_caplog, "Run completed")
    message = record.getMessage()
    total_tokens = sum(entry.telemetry.total_tokens for entry in state.ledger)
    cost = sum(estimate_cost(entry.telemetry, load_model_rates()) for entry in state.ledger)
    assert record.name == "src.app" and record.levelno == logging.INFO
    for expected in (
        "exit_code=0 (SUCCESS)",
        "drafts_saved=1",
        "failures=0",
        "violations=0",
        f"total_tokens={total_tokens}",
        f"estimated_cost_usd={cost:.6f}",
        f"summary={SUMMARY!r}",
    ):
        assert expected in message
    assert re.search(r"wall_clock=\d+\.\d{2}s", message)
    assert record is correlated_caplog.records[-1]


def test_mcp_session_opened_logs_the_server_its_launch_and_the_tools_listed(
    tmp_path: Path, correlated_caplog: pytest.LogCaptureFixture
) -> None:
    """D-I "MCP session opened": server directory, launch command, and the number of tools listed (five)."""
    result = _happy_run(tmp_path)

    [record] = _event(correlated_caplog, "MCP session opened")
    message = record.getMessage()
    assert f"server_dir={result.factory_calls[0].server_dir}" in message
    assert f"launch={MCP_LAUNCH_COMMAND}" in message
    assert "tools=5" in message


def test_the_supervisor_invocation_is_logged_as_it_starts_and_completes(
    tmp_path: Path, correlated_caplog: pytest.LogCaptureFixture
) -> None:
    """D-I: the composition root logs the Supervisor's invocation, as each wrapper logs its sub-agent's."""
    _happy_run(tmp_path)

    [started] = _event(correlated_caplog, "Supervisor invocation started")
    [completed] = _event(correlated_caplog, "Supervisor invocation completed")
    assert f"model=gpt-5.4 effort={SUPERVISOR_EFFORT}" in started.getMessage()
    message = completed.getMessage()
    assert "tokens=65" in message  # four tool-use turns of 15 tokens each, then the summary turn of 5
    assert re.search(r"duration=\d+\.\d{2}s", message)
    assert "tools=[scout_tool x1, writer_tool x1, qa_tool x1, save_draft x1]" in message


def test_every_line_of_a_run_carries_its_run_id(tmp_path: Path, correlated_caplog: pytest.LogCaptureFixture) -> None:
    """D-I correlation: ``log_context(run_id=…)`` wraps the whole run, so every ``src`` line names the same run."""
    state = _happy_run(tmp_path).state

    src_records = [record for record in correlated_caplog.records if record.name.startswith("src.")]
    assert len(src_records) > 10
    assert {getattr(record, "run_id", None) for record in src_records} == {state.run_id}


@pytest.mark.parametrize("path", ["configuration", "session"])
def test_an_early_exit_still_logs_run_completed_with_nothing_spent(
    tmp_path: Path, correlated_caplog: pytest.LogCaptureFixture, path: str
) -> None:
    """One "Run completed" per run, early exits included: zero tokens, no cost, and the early exit code."""
    if path == "configuration":
        state = _unconfigured_run(tmp_path, _unconfigured_model_builder)
    else:
        session = OfflineSubstrateSession(fail_enter_with=MCPClientInitializationError("the server did not start"))
        state = _run(tmp_path, supervisor=[], session=session).state

    [started] = _event(correlated_caplog, "Run started")
    [completed] = _event(correlated_caplog, "Run completed")
    code = state.exit_code
    assert code is not None
    assert f"exit_code={int(code)} ({code.name})" in completed.getMessage()
    assert "total_tokens=0 estimated_cost_usd=0.000000" in completed.getMessage()
    assert "failures=1" in completed.getMessage() and "summary=None" in completed.getMessage()
    assert {getattr(record, "run_id", None) for record in (started, completed)} == {state.run_id}


# ---------------------------------------------------------------------------
# The remaining exit-code rows, end to end (§7.6, P6, P13)
# ---------------------------------------------------------------------------

#: A second candidate, for the run that loses its session on the second document.
SECOND_DOC_ID: Final[str] = "inail-2024-circ-calore-bis"


def _assert_no_supervisor_failure(state: RunState) -> None:
    """A mis-scripted Supervisor raises "script exhausted", which would read as exit 6: no row but 6 may show one."""
    assert _supervisor_failures(state) == []


def test_a_scout_that_finds_nothing_exits_no_updates(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """§7.6: the Scout succeeded with zero candidates; nothing is drafted."""
    with caplog.at_level(logging.INFO):
        result = _run(
            tmp_path,
            supervisor=[tool_use_turn(SCOUT_TOOL, SCOPE), text_turn("Nothing qualified; no document was drafted.")],
            scout=[tool_use_turn("ScoutReport", {"candidates": []})],
        )

    state = result.state
    assert state.exit_code is ExitCode.NO_UPDATES
    assert state.scope is not None and state.documents == {}
    assert _drafts_on_disk(state) == []
    assert "Scout result: No qualifying updates" in caplog.text
    _assert_no_supervisor_failure(state)


def test_a_supervisor_that_never_calls_the_scout_exits_parser_error(tmp_path: Path) -> None:
    """P13: it ended its own invocation, no fatal stop occurred, and no ``scout_tool`` call succeeded."""
    text = "I could not work out a scope from this prompt."
    result = _run(tmp_path, supervisor=[text_turn(text)])

    state = result.state
    assert state.exit_code is ExitCode.PARSER_ERROR
    assert state.scope is None and state.supervisor_summary == text
    assert state.failures == [] and _drafts_on_disk(state) == []


def test_an_invalid_scope_the_supervisor_never_corrects_exits_parser_error(tmp_path: Path) -> None:
    """The refused scope is a violation, not a failure; the Supervisor then finishes with no scope."""
    result = _run(
        tmp_path,
        supervisor=[tool_use_turn(SCOUT_TOOL, {**SCOPE, "date_from": "20260622"}), text_turn("I give up.")],
    )

    state = result.state
    assert state.exit_code is ExitCode.PARSER_ERROR
    assert [violation.guardrail for violation in state.violations] == ["invalid_scope"]
    assert state.failures == []
    assert result.scout.turns_consumed == 0


def test_a_scout_failure_never_retried_exits_parser_error(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Row 4b, P13: a recoverable Scout failure is returned; the Supervisor ends on its own with no scope."""
    with caplog.at_level(logging.INFO):
        result = _run(
            tmp_path,
            supervisor=[tool_use_turn(SCOUT_TOOL, SCOPE), text_turn(SUMMARY)],
            scout=[RuntimeError("scout provider unavailable")],
        )

    state = result.state
    assert state.exit_code is ExitCode.PARSER_ERROR
    assert state.fatal_error is None and state.scope is None and state.violations == []
    assert _stages(state) == ["scout"]
    assert "Recoverable tool failure returned to the Supervisor" in caplog.text
    assert isinstance(result.supervisor, ScriptedModel) and result.supervisor.turns_consumed == 2
    assert state.supervisor_summary == SUMMARY


def test_a_scout_failure_retried_successfully_is_not_parser_error(tmp_path: Path) -> None:
    """Row 4c: the retry succeeds, so the run has a scope; its empty report makes it ``NO_UPDATES``."""
    result = _run(
        tmp_path,
        supervisor=[tool_use_turn(SCOUT_TOOL, SCOPE), tool_use_turn(SCOUT_TOOL, SCOPE), text_turn("Nothing found.")],
        scout=[RuntimeError("scout provider unavailable"), tool_use_turn("ScoutReport", {"candidates": []})],
    )

    state = result.state
    assert state.scope is not None
    assert state.exit_code is ExitCode.NO_UPDATES
    assert _stages(state) == ["scout"]


def test_a_draft_that_cannot_be_rendered_exits_persistence_error(tmp_path: Path) -> None:
    """§7.6: ``finalise_run`` reports the render failure; nothing is written."""
    result = _run(
        tmp_path,
        supervisor=[*_one_document_flow(), text_turn(SUMMARY)],
        scout=_scout_finds(DEFAULT_DOC_ID),
        writer=writer_turns(DEFAULT_DOC_ID),
        qa_legal=[tool_use_turn("QAReport", qa_args(status="PASS"))],
        config=pipeline_config(tmp_path, template_path=tmp_path / "missing.md"),
    )

    state = result.state
    assert state.exit_code is ExitCode.PERSISTENCE_ERROR
    assert _stages(state) == ["render"]
    assert _drafts_on_disk(state) == []


def test_a_run_that_saves_no_draft_still_exits_success(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """§7.6 "whatever the number of drafts saved": the Supervisor may finish with a candidate left unsaved."""
    with caplog.at_level(logging.INFO):
        result = _run(
            tmp_path,
            supervisor=[tool_use_turn(SCOUT_TOOL, SCOPE), text_turn("Skipped: the only candidate.")],
            scout=_scout_finds(DEFAULT_DOC_ID),
        )

    state = result.state
    assert state.exit_code is ExitCode.SUCCESS
    assert _drafts_on_disk(state) == []
    assert "Candidate left unsaved at run end" in caplog.text
    _assert_no_supervisor_failure(state)


def test_a_session_lost_on_the_second_document_exits_mcp_error_and_renders_the_first(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Row 2b, D-D: the fatal stop ends the Supervisor; the draft it saved is rendered; the run exits 2, never 6."""
    # Listings: 0 the composition root's, 1 the Scout's build, 2 the Writer's, 3 QA-Legal's, 4 the second Writer's.
    session = OfflineSubstrateSession(
        fail_listing_with=MCPClientInitializationError("the transport died"), fail_listing_on={4}
    )
    with caplog.at_level(logging.INFO):
        result = _run(
            tmp_path,
            supervisor=[
                *_one_document_flow(),
                tool_use_turn(WRITER_TOOL, {"doc_id": SECOND_DOC_ID, "revise": False}),
                text_turn("must not be reached"),
            ],
            scout=_scout_finds(DEFAULT_DOC_ID, SECOND_DOC_ID),
            writer=writer_turns(DEFAULT_DOC_ID),
            qa_legal=[tool_use_turn("QAReport", qa_args(status="PASS"))],
            session=session,
        )

    state = result.state
    assert state.exit_code is ExitCode.MCP_ERROR
    assert isinstance(state.fatal_error, MCPConnectionError)
    assert _stages(state) == ["mcp_session"]
    assert "Fatal abort triggered" in caplog.text
    assert isinstance(result.supervisor, ScriptedModel) and result.supervisor.turns_consumed == 5
    assert len(_drafts_on_disk(state)) == 1
    assert [entry.stage for entry in state.ledger].count("supervisor") == 1


def test_a_session_lost_at_the_scout_exits_mcp_error_not_parser_error(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Row 2c, P13: a fatal stop is code stopping the Supervisor, not the Supervisor ending on its own."""
    # Listing 0 is the composition root's own; 1 is the Scout's build.
    session = OfflineSubstrateSession(
        fail_listing_with=MCPClientInitializationError("the transport died"), fail_listing_on={1}
    )
    with caplog.at_level(logging.INFO):
        result = _run(
            tmp_path,
            supervisor=[tool_use_turn(SCOUT_TOOL, SCOPE), text_turn("must not be reached")],
            session=session,
        )

    state = result.state
    assert state.exit_code is ExitCode.MCP_ERROR
    assert isinstance(state.fatal_error, MCPConnectionError)
    assert state.scope is None
    assert isinstance(result.supervisor, ScriptedModel) and result.supervisor.turns_consumed == 1
    assert result.scout.turns_consumed == 0
    assert _stages(state) == ["mcp_session"]
    [abort] = [r for r in caplog.records if r.getMessage().startswith("Fatal abort triggered")]
    assert abort.levelno == logging.ERROR and "tool=scout_tool" in abort.getMessage()
    assert [entry.stage for entry in state.ledger] == ["scout", "supervisor"]
    assert _drafts_on_disk(state) == []
    assert state.supervisor_summary == ""


# ---------------------------------------------------------------------------
# One session, four models, one invocation (§7.6, D-H, D-D.1, D-F, DM3)
# ---------------------------------------------------------------------------


class _EventMarker(logging.Handler):
    """Appends a marker to the session's event list when one of the run's milestones is logged."""

    _MILESTONES: Final[tuple[str, ...]] = ("Supervisor invocation completed", "Draft rendered", "Run completed")

    def __init__(self, events: list[str]) -> None:
        super().__init__(level=logging.INFO)
        self._events = events

    def emit(self, record: logging.LogRecord) -> None:
        """Record the milestone the message opens with, if any."""
        message = record.getMessage()
        self._events.extend(milestone for milestone in self._MILESTONES if message.startswith(milestone))


def test_one_session_is_opened_per_run_and_closed_before_the_run_end(tmp_path: Path) -> None:
    """Exactly one ``with HSEMockMCPClient()``; rendering and the exit code come after it has closed (§7.6)."""
    session = OfflineSubstrateSession()
    marker = _EventMarker(session.events)
    src_logger = logging.getLogger("src")
    src_logger.addHandler(marker)
    previous_level = src_logger.level
    src_logger.setLevel(logging.INFO)
    try:
        result = _run(
            tmp_path,
            supervisor=[*_one_document_flow(), text_turn(SUMMARY)],
            scout=_scout_finds(DEFAULT_DOC_ID),
            writer=writer_turns(DEFAULT_DOC_ID),
            qa_legal=[tool_use_turn("QAReport", qa_args(status="PASS"))],
            session=session,
        )
    finally:
        src_logger.removeHandler(marker)
        src_logger.setLevel(previous_level)

    assert len(result.factory_calls) == 1
    assert session.events == ["enter", "Supervisor invocation completed", "exit", "Draft rendered", "Run completed"]


def test_the_clock_is_read_once_and_its_date_reaches_the_run(tmp_path: Path) -> None:
    """One date per run: the run context and the Supervisor's user turn both use it."""
    reads: list[date] = []

    def clock() -> date:
        reads.append(TODAY)
        return TODAY

    supervisor = ScriptedModel([text_turn("done")])
    state = run(
        PROMPT,
        pipeline_config(tmp_path),
        client_factory=lambda: offline_client(OfflineSubstrateSession()),
        model_builder=scripted_model_builder(ScriptedModel([]), supervisor),
        clock=clock,
    )

    assert reads == [TODAY]
    assert state.context.today == TODAY
    assert sent_text(supervisor, 0) == f"Current date: 2026-09-22\n\n{PROMPT}"


class _RecordingBuilder:
    """A ``model_builder`` that hands out a fresh scripted model per call and records what it was asked for."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []
        self.models: list[ScriptedModel] = []

    def __call__(self, model_id: str, *, reasoning_effort: str | None = None) -> Model:
        self.calls.append((model_id, reasoning_effort))
        model = ScriptedModel([text_turn("Nothing to do.")])
        self.models.append(model)
        return model


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        (
            {},
            [("gpt-5-mini", None), ("gpt-5.4", "high"), ("gpt-5.4", "medium"), ("gpt-5.4", "medium")],
        ),
        (
            {
                "HSE_MODEL_WRITER_REASONING_EFFORT": "xhigh",
                "HSE_MODEL_QA_REASONING_EFFORT": "low",
                "HSE_MODEL_SUPERVISOR_REASONING_EFFORT": "high",
            },
            [("gpt-5-mini", None), ("gpt-5.4", "xhigh"), ("gpt-5.4", "low"), ("gpt-5.4", "high")],
        ),
    ],
    ids=["defaults", "env_overrides"],
)
def test_four_models_are_built_once_each_on_their_bindings_and_efforts(
    tmp_path: Path, overrides: dict[str, str], expected: list[tuple[str, str | None]]
) -> None:
    """D-H, D24: the Scout on the fast binding with no effort; Writer, QA-Legal and Supervisor on the strong one.

    The settings are built here, not in the parametrize: at collection time the isolation fixture has not yet
    pinned ``env_file``, so a ``.env`` in the working directory would be read (D16).
    """
    builder = _RecordingBuilder()
    state = run(
        PROMPT,
        pipeline_config(tmp_path),
        client_factory=lambda: offline_client(OfflineSubstrateSession()),
        model_builder=builder,
        clock=lambda: TODAY,
        reasoning_settings=ReasoningSettings(**overrides),
    )

    assert sorted(builder.calls, key=repr) == sorted(expected, key=repr)
    # The one model the run called is the Supervisor's: told apart by its system prompt, not by build order.
    [supervisor] = [model for model in builder.models if model.turns_consumed]
    assert supervisor.received_system_prompts[0] == build_supervisor_prompt(None)
    supervisor_key = builder.calls[builder.models.index(supervisor)]
    assert supervisor_key == ("gpt-5.4", expected[-1][1])
    [entry] = state.ledger
    assert (entry.stage, entry.telemetry.model_id, entry.telemetry.reasoning_effort) == ("supervisor", *supervisor_key)


def test_the_effort_override_labels_each_role_s_telemetry(tmp_path: Path) -> None:
    """The resolved effort is used twice: to build each model and to label its ledger entry (D24)."""
    state = _happy_run(tmp_path).state

    efforts = {entry.stage: (entry.telemetry.model_id, entry.telemetry.reasoning_effort) for entry in state.ledger}
    assert efforts == {
        "scout": ("gpt-5-mini", None),
        "writer": ("gpt-5.4", "high"),
        "qa_legal": ("gpt-5.4", "medium"),
        "supervisor": ("gpt-5.4", SUPERVISOR_EFFORT),
    }


def test_max_drafts_sets_the_run_context_the_prompt_and_the_save_ceiling(tmp_path: Path) -> None:
    """``--max-drafts`` reaches ``RunContext`` and the prompt's Limits, and ``save_draft`` enforces it (DM3)."""
    result = _run(
        tmp_path,
        supervisor=[
            *_one_document_flow(DEFAULT_DOC_ID),
            *_one_document_flow(SECOND_DOC_ID)[1:],
            text_turn("Saved one; the ceiling refused the second."),
        ],
        scout=_scout_finds(DEFAULT_DOC_ID, SECOND_DOC_ID),
        writer=[*writer_turns(DEFAULT_DOC_ID), *writer_turns(SECOND_DOC_ID)],
        qa_legal=[tool_use_turn("QAReport", qa_args(status="PASS"))] * 2,
        config=pipeline_config(tmp_path, max_drafts=1),
    )

    state = result.state
    assert state.context.max_drafts == 1 and state.config.max_drafts == 1
    assert isinstance(result.supervisor, ScriptedModel)
    assert result.supervisor.received_system_prompts[0] == build_supervisor_prompt(1)
    assert [violation.guardrail for violation in state.violations] == ["draft_ceiling"]
    assert state.scope is not None and state.scope.max_drafts is None  # the scope's ceiling is the prompt's alone
    assert len(_drafts_on_disk(state)) == 1
    assert state.exit_code is ExitCode.SUCCESS


def test_the_supervisor_logs_each_turn_once_and_receives_only_the_prompt(
    tmp_path: Path, correlated_caplog: pytest.LogCaptureFixture
) -> None:
    """One ``LoggingHooks`` on the Supervisor (the builder's), so each turn is logged once; D-F: the prompt alone."""
    result = _happy_run(tmp_path)

    assert isinstance(result.supervisor, ScriptedModel)
    turns = _event(correlated_caplog, "Supervisor turn completed")
    assert len(turns) == result.supervisor.turns_consumed == 5
    assert sent_text(result.supervisor, 0) == f"Current date: 2026-09-22\n\n{PROMPT}"
    assert len(result.supervisor.received_messages[0]) == 1


def test_finalise_run_runs_once_and_an_unpriced_model_is_not_swallowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``finalise_run``'s ``ValueError`` is a defect, not ``CONFIG_ERROR``: it leaves ``run``, after the session."""
    fast_only = {SCOUT_MODEL_ID: load_model_rates()[SCOUT_MODEL_ID]}
    monkeypatch.setattr(app_module, "load_model_rates", lambda: fast_only)
    session = OfflineSubstrateSession()

    with pytest.raises(ValueError, match="gpt-5.4"):
        _run(tmp_path, supervisor=[text_turn("done")], session=session)
    assert session.events == ["enter", "exit"]


# ---------------------------------------------------------------------------
# Over the live local substrate: a real stdio session, scripted models, zero tokens
# ---------------------------------------------------------------------------


def test_a_run_over_the_live_substrate_lists_five_tools_and_renders_its_draft(
    tmp_path: Path, correlated_caplog: pytest.LogCaptureFixture
) -> None:
    """The real ``HSEMockMCPClient`` session: its five tools are listed, and every sub-agent is built over them (P1)."""
    supervisor = ScriptedModel([*_one_document_flow(), text_turn(SUMMARY)])
    state = run(
        PROMPT,
        pipeline_config(tmp_path),
        model_builder=scripted_model_builder_by_effort(
            {
                (SCOUT_MODEL_ID, None): ScriptedModel(_scout_finds(DEFAULT_DOC_ID)),
                (WRITER_MODEL_ID, "high"): ScriptedModel(writer_turns(DEFAULT_DOC_ID)),
                (QA_LEGAL_MODEL_ID, "medium"): ScriptedModel([tool_use_turn("QAReport", qa_args(status="PASS"))]),
                (SUPERVISOR_MODEL_ID, SUPERVISOR_EFFORT): supervisor,
            }
        ),
        clock=lambda: TODAY,
        reasoning_settings=ReasoningSettings(HSE_MODEL_SUPERVISOR_REASONING_EFFORT=SUPERVISOR_EFFORT),
    )

    assert state.exit_code is ExitCode.SUCCESS, state.failures
    [opened] = _event(correlated_caplog, "MCP session opened")
    assert "tools=5" in opened.getMessage()
    assert len(_drafts_on_disk(state)) == 1


def test_a_run_over_the_live_substrate_opens_one_session_and_closes_it(tmp_path: Path) -> None:
    """One real subprocess per run, and it has ended by the time ``run`` returns (Gate 8: no orphan)."""
    clients: list[HSEMockMCPClient] = []

    def counting_factory() -> HSEMockMCPClient:
        client = HSEMockMCPClient()
        clients.append(client)
        return client

    state = run(
        PROMPT,
        pipeline_config(tmp_path),
        client_factory=counting_factory,
        model_builder=scripted_model_builder(ScriptedModel([]), ScriptedModel([text_turn("No scope.")])),
        clock=lambda: TODAY,
    )

    assert state.exit_code is ExitCode.PARSER_ERROR
    assert len(clients) == 1
    with pytest.raises(MCPClientNotConnectedError):  # the client's public signal that its session has closed
        clients[0].list_all_tools()
