"""``qa_tool``: auditing the latest draft once, with the attempt cap kept out of QA-Legal's view (Iteration 9).

SPECIFICATIONS.md D-C rule 8, DM7, §6.2, §6.4, §7.2 and §7.3. Every test is offline and spends zero tokens (P4):
QA-Legal is a :class:`ScriptedModel` or a :class:`FailingModel`, and the substrate is the real ``HSEMockMCPClient``
over an :class:`OfflineSubstrateSession`. A tool is called directly, as the Supervisor's event loop would call it,
and every string it returns in this file passes through :func:`_assert_supervisor_view`.
"""

import json
import logging
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any, Final

import pytest
from strands import Agent
from strands.hooks import BeforeInvocationEvent, HookProvider, HookRegistry
from strands.models.model import Model
from strands.tools.decorator import DecoratedFunctionTool
from strands.types.tools import AgentTool

from src.agents import QA_LEGAL_MODEL_ID, QA_LEGAL_SYSTEM_PROMPT
from src.guardrails import check_qa
from src.logging_setup import CorrelationFilter
from src.mcp_client import MCPConnectionError
from src.schemas import (
    AgentContext,
    ArticleDraft,
    AttemptRecord,
    DocumentRecord,
    DraftResult,
    PipelineConfig,
    QAReport,
    RunContext,
    RunState,
    ScoutCandidate,
)
from src.tools import SubAgentEfforts, SubAgentModels, build_tools
from tests.support.scripted import (
    FORBIDDEN_SUPERVISOR_KEYS,
    QA_LEGAL_PROMPT_SECTION,
    REVISED_DRAFT_ARGS,
    SCOPE_DATE_TO,
    SUBSTRATE_TOOL_NAMES,
    FailingModel,
    OfflineSubstrateSession,
    ScriptedModel,
    draft_args,
    json_keys,
    offline_client,
    pipeline_config,
    qa_args,
    scout_candidate_args,
    sent_text,
    text_turn,
    tool_use_turn,
    worker_prompts,
    writer_turns,
)

#: The logger every ``src.tools`` event is written to.
TOOLS_LOGGER: Final[str] = "src.tools"

#: The run every test works in.
RUN_ID: Final[str] = "run-test-0009"
TODAY: Final[date] = date.fromisoformat(SCOPE_DATE_TO)

#: The document most tests audit, and a second one for tests that need two documents.
DOC_ID: Final[str] = "inail-2026-ot23"
OTHER_DOC_ID: Final[str] = "gu-2026-dl-caldo"

#: The ``AttemptRecord`` keys the Supervisor sees (§7.2): never ``draft`` or ``candidate``.
SUPERVISOR_ATTEMPT_KEYS: Final[frozenset[str]] = frozenset({"doc_id", "context", "attempt", "qa_report"})

#: The ``ArticleDraft`` fields that hold article text, none of which may reach the Supervisor (D-F).
_ARTICLE_TEXT_FIELDS: Final[tuple[str, ...]] = ("headline", "executive_summary", "article_body", "tdi_cta")

#: The issues a scripted QA-Legal raises; none quotes a draft, so the article-text check tests code, not fixtures.
_ISSUES: Final[list[str]] = ["Citazione non verificata: Art. 99.", "Scadenza non coerente con la fonte."]


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


def _run_state(config: PipelineConfig) -> RunState:
    """A run whose Scout returned ``DOC_ID`` and ``OTHER_DOC_ID``, in that order, and nothing else yet."""
    state = RunState(run_id=RUN_ID, config=config, context=RunContext(today=TODAY, max_drafts=None, drafts_saved=0))
    for index, doc_id in enumerate((DOC_ID, OTHER_DOC_ID)):
        candidate = ScoutCandidate.model_validate(scout_candidate_args(doc_id, 0.9 - index / 10, f"Obblighi {doc_id}."))
        state.documents[doc_id] = DocumentRecord(candidate=candidate)
    return state


@pytest.fixture
def state(tmp_path: Path) -> RunState:
    return _run_state(pipeline_config(tmp_path))


def _article_text(state: RunState) -> set[str]:
    """Every piece of article text the run holds, across every document and attempt."""
    return {
        getattr(record.draft, field)
        for document in state.documents.values()
        for record in document.attempts
        if record.draft is not None
        for field in _ARTICLE_TEXT_FIELDS
    }


def _assert_supervisor_view(state: RunState, returned: Any, *, tool_name: str = "qa_tool") -> None:
    """D-F and §7.2, for one string a tool returned: a ``ToolResult[AttemptRecord]`` as the Supervisor sees it.

    Exactly ``result``, ``run`` and ``error``; ``run`` is the run's snapshot; a ``result`` is the supervisor view of
    the stored attempt it names, whose QA report is set exactly when ``qa_tool`` succeeded; no forbidden key appears
    at any depth, and no article text the run holds appears anywhere in the string.
    """
    assert isinstance(returned, str)
    decoded = json.loads(returned)
    assert set(decoded) == {"result", "run", "error"}
    assert decoded["run"] == state.snapshot().model_dump(mode="json")
    result = decoded["result"]
    if result is not None:
        assert set(result) == SUPERVISOR_ATTEMPT_KEYS
        stored = state.documents[result["doc_id"]].attempts[result["attempt"] - 1]
        assert result == stored.supervisor_view()
        audited = tool_name == "qa_tool" and decoded["error"] is None
        assert (result["qa_report"] is not None) == audited
    assert json_keys(decoded) & FORBIDDEN_SUPERVISOR_KEYS == set()
    assert [text for text in _article_text(state) if text in returned] == []


#: How the attempt cap or the run budget would read in a prompt (DM7): phrasing and ``RunContext`` keys, never the
#: digit alone, because QA-Legal legitimately sees ``"attempt": 3``.
_CAP_PHRASES: Final[tuple[str, ...]] = (
    "3 attempts",
    "max_attempts",
    "attempt cap",
    "attempts remaining",
    "remaining",
    "of 3",
    "attempts_remaining",
    "max_attempts_per_doc",
    "max_drafts",
    "drafts_saved",
)


def _assert_no_attempt_cap(prompt: str) -> None:
    """AC2 and DM7, for one QA-Legal user turn: nothing of the attempt cap or the run's budget."""
    assert [phrase for phrase in _CAP_PHRASES if phrase in prompt] == []


class _CheckedTool:
    """A built tool whose every call is checked before a test sees its result.

    Every call a test in this module makes goes through here, so both checks hold for every call in the file: the
    returned string passes :func:`_assert_supervisor_view`, and every QA-Legal user turn the run's scripted QA
    model has received so far passes :func:`_assert_no_attempt_cap` (AC2).
    """

    def __init__(self, state: RunState, tool_obj: AgentTool, qa: Model) -> None:
        assert isinstance(tool_obj, DecoratedFunctionTool)  # a plain ``@tool`` function, callable directly
        self._state = state
        self._qa = qa
        self.tool_obj = tool_obj

    def __call__(self, **arguments: Any) -> str:
        returned = self.tool_obj(**arguments)
        _assert_supervisor_view(self._state, returned, tool_name=self.tool_obj.tool_name)
        if isinstance(self._qa, ScriptedModel):
            for prompt in worker_prompts(self._qa, QA_LEGAL_PROMPT_SECTION):
                _assert_no_attempt_cap(prompt)
        return returned


def _tools(
    state: RunState,
    *,
    qa: Model,
    writer: Model | None = None,
    session: OfflineSubstrateSession | None = None,
    efforts: SubAgentEfforts | None = None,
    hooks: tuple[HookProvider, ...] = (),
) -> dict[str, _CheckedTool]:
    """Build the four tools over an offline substrate, with ``qa`` as QA-Legal's model and its own Writer model."""
    tools = build_tools(
        state,
        client=offline_client(session if session is not None else OfflineSubstrateSession()),
        models=SubAgentModels(
            scout=ScriptedModel([]), writer=writer if writer is not None else ScriptedModel([]), qa_legal=qa
        ),
        efforts=efforts if efforts is not None else SubAgentEfforts(),
        hooks=hooks,
    )
    return {tool_obj.tool_name: _CheckedTool(state, tool_obj, qa) for tool_obj in tools}


def _qa_tool(
    state: RunState,
    qa: Model,
    *,
    session: OfflineSubstrateSession | None = None,
    efforts: SubAgentEfforts | None = None,
    hooks: tuple[HookProvider, ...] = (),
) -> _CheckedTool:
    """Build the tools and return ``qa_tool``, with ``qa`` as QA-Legal's model."""
    return _tools(state, qa=qa, session=session, efforts=efforts, hooks=hooks)["qa_tool"]


def _result(returned: str) -> dict[str, Any]:
    """Decode a tool's return value, which must be the ``for_supervisor()`` JSON string."""
    decoded = json.loads(returned)
    assert isinstance(decoded, dict)
    return decoded


def qa_turns(doc_id: str, *, status: str = "PASS", issues: list[str] | None = None, notes: str = "") -> list[Any]:
    """Script one QA-Legal invocation: fetch the draft's source, then issue the ``QAReport``."""
    return [
        tool_use_turn("get_document_by_id", {"doc_id": doc_id}),
        tool_use_turn("QAReport", qa_args(status=status, issues=issues, notes=notes)),
    ]


def _report(*, status: str = "PASS", issues: list[str] | None = None, notes: str = "") -> QAReport:
    """The ``QAReport`` :func:`qa_turns` scripts with the same arguments."""
    return QAReport.model_validate(qa_args(status=status, issues=issues, notes=notes))


def _add_attempt(state: RunState, doc_id: str, *, drafted: bool = True, status: str | None = None) -> AttemptRecord:
    """Put one earlier attempt on ``doc_id``, as an earlier ``writer_tool`` call (and ``qa_tool`` audit) left it."""
    document = state.documents[doc_id]
    record = AttemptRecord(
        context=AgentContext(today=TODAY), candidate=document.candidate, attempt=document.attempts_used + 1
    )
    if drafted:
        record.set_draft(ArticleDraft.model_validate(draft_args(doc_id, headline=f"Bozza {record.attempt}")))
    if status is not None:
        record.set_qa_report(QAReport.model_validate(qa_args(status=status, issues=[f"Problema {record.attempt}"])))
    document.attempts.append(record)
    return record


def _correlation(record: logging.LogRecord) -> tuple[Any, ...]:
    """``(run_id, doc_id, attempt)`` as the :class:`CorrelationFilter` stamped them onto ``record``."""
    return tuple(getattr(record, name) for name in ("run_id", "doc_id", "attempt"))


def _messages(caplog: pytest.LogCaptureFixture, level: int | None = None) -> list[str]:
    """The ``src.tools`` messages captured, optionally at one level only."""
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == TOOLS_LOGGER and (level is None or record.levelno == level)
    ]


# ---------------------------------------------------------------------------
# A successful audit: D-C rule 8, §6.2
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["PASS", "WARNING", "ERROR"])
def test_a_successful_audit_stores_the_report_as_issued_on_the_latest_drafted_record(
    state: RunState, status: str
) -> None:
    """The one drafted attempt receives QA-Legal's ``QAReport``, unchanged; nothing else is touched."""
    drafted = _add_attempt(state, DOC_ID)
    issues = None if status == "PASS" else _ISSUES

    _qa_tool(state, ScriptedModel(qa_turns(DOC_ID, status=status, issues=issues, notes="Nota.")))(doc_id=DOC_ID)

    assert state.documents[DOC_ID].attempts == [drafted]
    assert drafted.qa_report == _report(status=status, issues=issues, notes="Nota.")
    assert state.documents[OTHER_DOC_ID].attempts == []
    assert (state.failures, state.violations) == ([], [])


def test_the_report_goes_to_the_latest_drafted_record_not_to_a_later_draftless_attempt(state: RunState) -> None:
    """D-C rule 8: the audit target is ``latest_drafted``, even when a later attempt left no draft."""
    first = _add_attempt(state, DOC_ID)
    last = _add_attempt(state, DOC_ID, drafted=False)

    _qa_tool(state, ScriptedModel(qa_turns(DOC_ID)))(doc_id=DOC_ID)

    assert first.qa_report == _report()
    assert last.qa_report is None


# ---------------------------------------------------------------------------
# What QA-Legal receives: latest_drafted.qa_view() (§6.2, §7.2, DM7)
# ---------------------------------------------------------------------------

#: The ``AttemptRecord`` keys QA-Legal sees (§7.2): never ``candidate`` or ``qa_report``.
QA_VIEW_KEYS: Final[frozenset[str]] = frozenset({"doc_id", "context", "attempt", "draft"})


def _sent_record(qa: ScriptedModel, turn: int = 0) -> dict[str, Any]:
    """The ``AttemptRecord`` JSON QA-Legal's user turn carried on round trip ``turn``."""
    _, _, record = sent_text(qa, turn).partition("## AttemptRecord\n")
    decoded = json.loads(record)
    assert isinstance(decoded, dict)
    return decoded


def test_qa_legal_receives_the_latest_drafted_records_qa_view_and_nothing_of_its_candidate(state: RunState) -> None:
    """§7.2: ``{doc_id, context, attempt, draft}``; ``context`` is the date alone; the candidate's triage is absent."""
    drafted = _add_attempt(state, DOC_ID)
    qa = ScriptedModel(qa_turns(DOC_ID))

    _qa_tool(state, qa)(doc_id=DOC_ID)

    sent = _sent_record(qa)
    assert sent == json.loads(drafted.qa_view())
    assert set(sent) == QA_VIEW_KEYS
    assert sent["context"] == {"today": SCOPE_DATE_TO}
    assert (sent["doc_id"], sent["attempt"], sent["draft"]["headline"]) == (DOC_ID, 1, "Bozza 1")
    text = sent_text(qa)
    assert "rationale" not in text and "newsworthiness_score" not in text
    assert drafted.candidate.rationale not in text


def test_a_revised_draft_is_audited_without_the_earlier_attempts_report(state: RunState) -> None:
    """QA-Legal audits attempt #2 as it audited #1 in Approach 1: the draft alone, never #1's report or issues."""
    _add_attempt(state, DOC_ID, status="ERROR")
    revised = _add_attempt(state, DOC_ID)
    qa = ScriptedModel(qa_turns(DOC_ID))

    _qa_tool(state, qa)(doc_id=DOC_ID)

    sent = _sent_record(qa)
    assert sent == json.loads(revised.qa_view())
    assert (sent["attempt"], sent["draft"]["headline"]) == (2, "Bozza 2")
    text = sent_text(qa)
    assert "qa_report" not in text and "Problema 1" not in text and "Bozza 1" not in text


# ---------------------------------------------------------------------------
# The result the Supervisor receives (§6.4, §7.2, D-F)
# ---------------------------------------------------------------------------


def _audited_view(attempt: int, report: QAReport) -> dict[str, Any]:
    """The supervisor view of a ``DOC_ID`` attempt carrying ``report`` (§7.2)."""
    return {
        "doc_id": DOC_ID,
        "context": {"today": SCOPE_DATE_TO},
        "attempt": attempt,
        "qa_report": report.model_dump(mode="json"),
    }


@pytest.mark.parametrize("status", ["PASS", "WARNING", "ERROR"])
def test_a_successful_audit_returns_the_record_with_its_full_report_the_run_and_no_error(
    state: RunState, status: str
) -> None:
    """§6.4: the audited record without draft or candidate, the whole ``QAReport``, the run snapshot, no error."""
    _add_attempt(state, DOC_ID)
    issues = None if status == "PASS" else _ISSUES
    qa = ScriptedModel(qa_turns(DOC_ID, status=status, issues=issues, notes="Nota del revisore."))

    returned = _result(_qa_tool(state, qa)(doc_id=DOC_ID))

    assert returned == {
        "result": _audited_view(1, _report(status=status, issues=issues, notes="Nota del revisore.")),
        "run": state.snapshot().model_dump(mode="json"),
        "error": None,
    }
    assert returned["run"]["max_attempts_per_doc"] == 3


# ---------------------------------------------------------------------------
# The verdict log (D-I): PASS at INFO; WARNING or ERROR at WARNING, with the issues
# ---------------------------------------------------------------------------


def test_a_pass_verdict_is_logged_at_info_with_its_document_and_attempt(
    state: RunState, caplog: pytest.LogCaptureFixture
) -> None:
    """D-I: INFO "QA verdict PASS" with ``doc_id`` and ``attempt``, after the invocation pair; no WARNING."""
    caplog.set_level(logging.INFO, logger=TOOLS_LOGGER)
    caplog.handler.addFilter(CorrelationFilter())
    _add_attempt(state, DOC_ID)

    _qa_tool(state, ScriptedModel(qa_turns(DOC_ID, status="PASS")))(doc_id=DOC_ID)

    assert [m.split(":")[0] for m in _messages(caplog, logging.INFO)] == [
        "Sub-agent invocation started",
        "Sub-agent invocation completed",
        "QA verdict PASS",
    ]
    (record,) = [r for r in caplog.records if r.getMessage().startswith("QA verdict")]
    assert f"doc_id={DOC_ID}" in record.getMessage() and "attempt=1" in record.getMessage()
    assert _correlation(record) == (RUN_ID, DOC_ID, 1)
    assert _messages(caplog, logging.WARNING) == []


@pytest.mark.parametrize("status", ["WARNING", "ERROR"])
def test_a_warning_or_error_verdict_is_logged_at_warning_with_every_issue(
    state: RunState, caplog: pytest.LogCaptureFixture, status: str
) -> None:
    """D-I: WARNING "QA verdict WARNING/ERROR" with ``doc_id``, ``attempt`` and the issues themselves, not a count."""
    caplog.set_level(logging.INFO, logger=TOOLS_LOGGER)
    caplog.handler.addFilter(CorrelationFilter())
    _add_attempt(state, DOC_ID, status="ERROR")
    _add_attempt(state, DOC_ID)

    _qa_tool(state, ScriptedModel(qa_turns(DOC_ID, status=status, issues=_ISSUES)))(doc_id=DOC_ID)

    (record,) = [r for r in caplog.records if r.name == TOOLS_LOGGER and r.levelno == logging.WARNING]
    message = record.getMessage()
    assert message.startswith(f"QA verdict {status}")
    assert f"doc_id={DOC_ID}" in message and "attempt=2" in message
    assert all(issue in message for issue in _ISSUES)
    assert _correlation(record) == (RUN_ID, DOC_ID, 2)
    assert not any(m.startswith("QA verdict") for m in _messages(caplog, logging.INFO))


# ---------------------------------------------------------------------------
# Telemetry (D-B) and the tool binding (P1)
# ---------------------------------------------------------------------------


def test_a_successful_audit_appends_one_qa_legal_ledger_entry_for_its_attempt(state: RunState) -> None:
    """D-B: stage ``qa_legal`` with the document and attempt, QA-Legal's model ID and the effort it was built at."""
    _add_attempt(state, DOC_ID, status="ERROR")
    _add_attempt(state, DOC_ID)
    qa = ScriptedModel(qa_turns(DOC_ID))

    _qa_tool(state, qa, efforts=SubAgentEfforts(qa_legal="low"))(doc_id=DOC_ID)

    (entry,) = state.ledger
    assert (entry.stage, entry.doc_id, entry.attempt) == ("qa_legal", DOC_ID, 2)
    assert (entry.telemetry.model_id, entry.telemetry.reasoning_effort) == (QA_LEGAL_MODEL_ID, "low")
    assert entry.telemetry.total_tokens == 30  # both scripted round trips of the one call
    assert ("get_document_by_id", 1) in [(t.tool_name, t.call_count) for t in entry.telemetry.tool_invocations]


def test_the_ledger_entry_belongs_to_the_audited_attempt_not_to_the_attempt_count(state: RunState) -> None:
    """The entry names ``latest_drafted.attempt``, even when a later attempt left no draft."""
    _add_attempt(state, DOC_ID)
    _add_attempt(state, DOC_ID, drafted=False)

    _qa_tool(state, ScriptedModel(qa_turns(DOC_ID)))(doc_id=DOC_ID)

    assert [(entry.stage, entry.doc_id, entry.attempt) for entry in state.ledger] == [("qa_legal", DOC_ID, 1)]


def test_qa_legal_is_built_fresh_with_all_five_substrate_tools(state: RunState) -> None:
    """P1: no ``tool_names`` narrowing; QA-Legal's prompt, not its binding, draws the boundary."""
    _add_attempt(state, DOC_ID)
    session = OfflineSubstrateSession()
    qa = ScriptedModel(qa_turns(DOC_ID))

    _qa_tool(state, qa, session=session)(doc_id=DOC_ID)

    assert session.tool_filters_seen == [None]
    assert {spec["name"] for spec in qa.received_tool_specs[0] or []} >= set(SUBSTRATE_TOOL_NAMES)
    assert qa.received_system_prompts[0] == QA_LEGAL_SYSTEM_PROMPT


class _RecordingHooks(HookProvider):
    """Counts every sub-agent invocation it is registered on."""

    def __init__(self) -> None:
        self.invocations: int = 0

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeInvocationEvent, self._count)

    def _count(self, event: BeforeInvocationEvent) -> None:
        self.invocations += 1


@pytest.mark.parametrize(("status", "invocations"), [(None, 1), ("PASS", 0)], ids=["allowed", "already_audited"])
def test_the_hooks_given_to_build_tools_reach_qa_legal_and_only_when_it_is_built(
    state: RunState, status: str | None, invocations: int
) -> None:
    """D-I and Iteration 12's seam: QA-Legal registers the hooks ``build_tools`` was given; a refusal builds nothing."""
    _add_attempt(state, DOC_ID, status=status)
    hooks = _RecordingHooks()

    returned = _result(_qa_tool(state, ScriptedModel(qa_turns(DOC_ID)), hooks=(hooks,))(doc_id=DOC_ID))

    assert (returned["error"] is None) == (status is None)
    assert hooks.invocations == invocations


# ---------------------------------------------------------------------------
# Refusals: every check_qa violation, reached through the tool (D-C rule 8, §7.3, P2, P3)
# ---------------------------------------------------------------------------

#: What ``state.documents.get`` falls back to for a ``doc_id`` the Scout never returned.
_EMPTY: Final[DocumentRecord] = DocumentRecord(
    candidate=ScoutCandidate.model_validate(scout_candidate_args("none", 0.0, "Nessuno."))
)


def _unknown_document(state: RunState) -> str:
    return "not-a-scout-candidate"


def _saved_after_a_warning(state: RunState) -> str:
    """P2: a document saved with ``WARNING`` is closed, even to an audit ``check_qa``'s later rules would refuse."""
    _add_attempt(state, DOC_ID, status="WARNING")
    state.documents[DOC_ID].saved = DraftResult(
        doc_id=DOC_ID, draft_id="draft_20260922_001", path=Path("drafts") / "draft_20260922_001.md", qa_status="WARNING"
    )
    return DOC_ID


def _saved_with_an_unaudited_latest(state: RunState) -> str:
    """P2 comes before rule 8: a saved document whose latest draft would otherwise be auditable is still refused."""
    _saved_after_a_warning(state)
    _add_attempt(state, DOC_ID)
    return DOC_ID


def _no_attempts(state: RunState) -> str:
    return DOC_ID


def _only_a_failed_attempt(state: RunState) -> str:
    _add_attempt(state, DOC_ID, drafted=False)
    return DOC_ID


def _audited(state: RunState) -> str:
    _add_attempt(state, DOC_ID, status="PASS")
    return DOC_ID


def _audited_then_a_failed_revision(state: RunState) -> str:
    """Rule 8 table, row 5: the failed #2 leaves the audited #1 the latest, so there is nothing new to audit."""
    _add_attempt(state, DOC_ID, status="ERROR")
    _add_attempt(state, DOC_ID, drafted=False)
    return DOC_ID


REFUSALS: Final[list[Any]] = [
    pytest.param(_unknown_document, "not_a_candidate", id="not_a_candidate"),
    pytest.param(_saved_after_a_warning, "already_saved", id="already_saved"),
    pytest.param(_saved_with_an_unaudited_latest, "already_saved", id="already_saved-unaudited-latest"),
    pytest.param(_no_attempts, "no_draft", id="no_draft-no-attempts"),
    pytest.param(_only_a_failed_attempt, "no_draft", id="no_draft-failed-attempt"),
    pytest.param(_audited, "already_audited", id="already_audited"),
    pytest.param(_audited_then_a_failed_revision, "already_audited", id="already_audited-after-a-failed-revision"),
]


@pytest.mark.parametrize(("arrange", "guardrail"), REFUSALS)
def test_a_refused_audit_is_stored_logged_and_returned_with_no_result(
    state: RunState, caplog: pytest.LogCaptureFixture, arrange: Callable[[RunState], str], guardrail: str
) -> None:
    """Gate 4: a complete violation, one test per ``check_qa`` guardrail, including ``already_saved`` (P2)."""
    caplog.set_level(logging.INFO, logger=TOOLS_LOGGER)
    caplog.handler.addFilter(CorrelationFilter())
    doc_id = arrange(state)

    returned = _result(_qa_tool(state, ScriptedModel(qa_turns(doc_id)))(doc_id=doc_id))

    (violation,) = state.violations
    assert (violation.guardrail, violation.tool_name, violation.doc_id) == (guardrail, "qa_tool", doc_id)
    assert returned == {
        "result": None,
        "run": state.snapshot().model_dump(mode="json"),
        "error": violation.model_dump(mode="json"),
    }
    (warning,) = [r for r in caplog.records if r.name == TOOLS_LOGGER and r.levelno == logging.WARNING]
    message = warning.getMessage()
    assert message.startswith("Guardrail violation") and f"guardrail={guardrail}" in message
    assert "tool=qa_tool" in message and f"doc_id={doc_id}" in message and violation.message in message
    assert _correlation(warning) == (RUN_ID, doc_id, "-")  # no attempt was audited


@pytest.mark.parametrize(("arrange", "guardrail"), REFUSALS)
def test_a_refused_audit_builds_no_qa_legal_changes_no_attempt_and_spends_nothing(
    state: RunState, caplog: pytest.LogCaptureFixture, arrange: Callable[[RunState], str], guardrail: str
) -> None:
    """The check runs first (D-A step 1): no agent, token, ledger entry, failure, stored report or verdict."""
    caplog.set_level(logging.INFO, logger=TOOLS_LOGGER)
    doc_id = arrange(state)
    attempts_before = [record.model_copy(deep=True) for record in state.documents.get(doc_id, _EMPTY).attempts]
    session = OfflineSubstrateSession()
    qa = ScriptedModel(qa_turns(doc_id))

    _qa_tool(state, qa, session=session)(doc_id=doc_id)

    assert state.documents.get(doc_id, _EMPTY).attempts == attempts_before
    assert (session.tool_filters_seen, qa.turns_consumed, state.ledger, state.failures) == ([], 0, [], [])
    assert not any(m.startswith(("Sub-agent", "QA verdict")) for m in _messages(caplog))


# ---------------------------------------------------------------------------
# A failed QA-Legal call: recoverable or fatal (§6.4, §6.7, D-C rule 8, D-D)
# ---------------------------------------------------------------------------


def _failing_qa(case: str) -> tuple[Model, OfflineSubstrateSession]:
    """``(QA-Legal model, session)`` for one way a QA-Legal call fails; ``fatal-*`` loses the substrate session."""
    fetch = tool_use_turn("get_document_by_id", {"doc_id": DOC_ID})
    if case == "build":
        return ScriptedModel([]), OfflineSubstrateSession(fail_listing_with=RuntimeError("listing broke"))
    if case == "provider-error":
        return FailingModel(RuntimeError("provider broke")), OfflineSubstrateSession()
    if case == "after-the-fetch":
        return ScriptedModel([fetch, RuntimeError("late")]), OfflineSubstrateSession()
    assert case == "fatal-after-the-fetch"
    return ScriptedModel([fetch, MCPConnectionError("died")]), OfflineSubstrateSession()


RECOVERABLE_CASES: Final[tuple[str, ...]] = ("build", "provider-error", "after-the-fetch")
FAILURE_CASES: Final[tuple[str, ...]] = (*RECOVERABLE_CASES, "fatal-after-the-fetch")


def _unaudited_view(attempt: int) -> dict[str, Any]:
    """The supervisor view of a ``DOC_ID`` attempt whose QA slot is still empty (§7.2)."""
    return {"doc_id": DOC_ID, "context": {"today": SCOPE_DATE_TO}, "attempt": attempt, "qa_report": None}


@pytest.mark.parametrize("case", RECOVERABLE_CASES)
def test_a_failed_audit_records_a_qa_legal_failure_on_the_audited_attempt(state: RunState, case: str) -> None:
    """§6.7: stage ``qa_legal``, tied to the document and the attempt it audited; full detail; nothing fatal."""
    _add_attempt(state, DOC_ID, status="ERROR")
    _add_attempt(state, DOC_ID)
    qa, session = _failing_qa(case)

    _qa_tool(state, qa, session=session)(doc_id=DOC_ID)

    (failure,) = state.failures
    assert (failure.stage, failure.doc_id, failure.attempt) == ("qa_legal", DOC_ID, 2)
    assert failure.traceback is not None and "RuntimeError" in failure.traceback  # Strands may wrap it
    assert state.fatal_error is None


@pytest.mark.parametrize("case", FAILURE_CASES)
def test_a_failed_audit_leaves_the_report_empty_and_returns_the_record_and_a_one_line_error(
    state: RunState, case: str
) -> None:
    """§6.4: ``result`` is the still unaudited record, with the run snapshot; ``error`` is one line, never text."""
    drafted = _add_attempt(state, DOC_ID)
    qa, session = _failing_qa(case)

    returned = _result(_qa_tool(state, qa, session=session)(doc_id=DOC_ID))

    assert drafted.qa_report is None
    assert returned["result"] == _unaudited_view(1)
    assert returned["run"] == state.snapshot().model_dump(mode="json")
    error = returned["error"]
    assert isinstance(error, str) and error.startswith("qa_tool failed: ") and "\n" not in error
    assert "broke" not in error and "late" not in error and "died" not in error


@pytest.mark.parametrize("case", FAILURE_CASES)
def test_a_failed_audit_still_appends_its_one_qa_legal_ledger_entry(state: RunState, case: str) -> None:
    """D-B: a failed call is recorded in the ledger too, with the audited attempt and the effort it was built at."""
    _add_attempt(state, DOC_ID)
    qa, session = _failing_qa(case)

    _qa_tool(state, qa, session=session, efforts=SubAgentEfforts(qa_legal="low"))(doc_id=DOC_ID)

    (entry,) = state.ledger
    assert (entry.stage, entry.doc_id, entry.attempt) == ("qa_legal", DOC_ID, 1)
    assert (entry.telemetry.model_id, entry.telemetry.reasoning_effort) == (QA_LEGAL_MODEL_ID, "low")


@pytest.mark.parametrize("case", RECOVERABLE_CASES)
def test_a_failed_audit_is_logged_as_a_recoverable_tool_failure_and_logs_no_verdict(
    state: RunState, caplog: pytest.LogCaptureFixture, case: str
) -> None:
    """D-I: WARNING with the tool, ``doc_id``, ``attempt`` and the full detail; no verdict was issued."""
    caplog.set_level(logging.INFO, logger=TOOLS_LOGGER)
    caplog.handler.addFilter(CorrelationFilter())
    _add_attempt(state, DOC_ID)
    qa, session = _failing_qa(case)

    _qa_tool(state, qa, session=session)(doc_id=DOC_ID)

    (warning,) = [r for r in caplog.records if r.name == TOOLS_LOGGER and r.levelno == logging.WARNING]
    message = warning.getMessage()
    assert message.startswith("Recoverable tool failure returned to the Supervisor")
    assert "tool=qa_tool" in message and f"doc_id={DOC_ID}" in message and "attempt=1" in message
    assert warning.exc_info is not None
    assert _correlation(warning) == (RUN_ID, DOC_ID, 1)
    assert not any(m.startswith("QA verdict") for m in _messages(caplog))


def test_a_lost_session_records_an_mcp_session_failure_on_the_attempt_and_sets_the_fatal_slot(
    state: RunState, caplog: pytest.LogCaptureFixture
) -> None:
    """D-D: stage ``mcp_session``, still tied to the document and attempt, logged at ERROR; the slot is set."""
    caplog.set_level(logging.INFO, logger=TOOLS_LOGGER)
    _add_attempt(state, DOC_ID)
    qa, session = _failing_qa("fatal-after-the-fetch")

    _qa_tool(state, qa, session=session)(doc_id=DOC_ID)

    assert isinstance(state.fatal_error, MCPConnectionError)
    assert [(f.stage, f.doc_id, f.attempt) for f in state.failures] == [("mcp_session", DOC_ID, 1)]
    (error,) = [r for r in caplog.records if r.name == TOOLS_LOGGER and r.levelno == logging.ERROR]
    assert error.getMessage().startswith("MCP session failed") and "tool=qa_tool" in error.getMessage()


def test_an_audit_may_be_retried_after_a_failed_call_on_the_same_attempt(state: RunState) -> None:
    """D-C rule 8: the report is still empty, so ``check_qa`` allows a retry; a fresh agent audits the same draft."""
    drafted = _add_attempt(state, DOC_ID)
    qa = ScriptedModel([RuntimeError("provider broke"), *qa_turns(DOC_ID, status="WARNING", issues=_ISSUES)])
    qa_tool = _qa_tool(state, qa)

    first = _result(qa_tool(doc_id=DOC_ID))
    assert first["error"] is not None and check_qa(state, DOC_ID) is None
    second = _result(qa_tool(doc_id=DOC_ID))

    assert second["result"] == _audited_view(1, _report(status="WARNING", issues=_ISSUES))
    assert second["error"] is None and drafted.qa_report is not None
    assert len(qa.received_messages[1]) == 1  # a fresh agent: the retry starts from an empty conversation
    assert [(entry.stage, entry.attempt) for entry in state.ledger] == [("qa_legal", 1), ("qa_legal", 1)]


# ---------------------------------------------------------------------------
# The guardrail's invariant: a broken check_qa never spends a token
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("audited", [False, True], ids=["no-draft", "already-audited"])
def test_an_audit_past_a_broken_check_qa_invariant_raises_before_building_qa_legal(
    state: RunState, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, audited: bool
) -> None:
    """If ``check_qa`` ever admitted a call with nothing to audit, the call fails loudly with no side effect at all."""
    caplog.set_level(logging.INFO, logger=TOOLS_LOGGER)
    monkeypatch.setattr("src.tools.check_qa", lambda *_: None)  # the guardrail's invariant, broken on purpose
    if audited:
        _add_attempt(state, DOC_ID, status="WARNING")
    attempts_before = [record.model_copy(deep=True) for record in state.documents[DOC_ID].attempts]
    session = OfflineSubstrateSession()
    qa = ScriptedModel(qa_turns(DOC_ID))

    with pytest.raises(RuntimeError, match="unaudited draft"):
        _qa_tool(state, qa, session=session)(doc_id=DOC_ID)

    assert state.documents[DOC_ID].attempts == attempts_before
    assert (session.tool_filters_seen, qa.turns_consumed, state.ledger, state.failures) == ([], 0, [], [])
    assert _messages(caplog) == []


# ---------------------------------------------------------------------------
# AC2: no QA-Legal user turn contains the attempt cap (DM7)
# ---------------------------------------------------------------------------


def test_the_audit_of_a_third_attempt_names_its_number_and_nothing_of_the_cap(state: RunState) -> None:
    """At the cap, QA-Legal still sees only ``"attempt": 3``: no limit, no remaining count, no ``RunContext``."""
    _add_attempt(state, DOC_ID, status="ERROR")
    _add_attempt(state, DOC_ID, status="ERROR")
    _add_attempt(state, DOC_ID)
    qa = ScriptedModel(qa_turns(DOC_ID, status="ERROR", issues=_ISSUES))

    _qa_tool(state, qa)(doc_id=DOC_ID)

    (prompt,) = worker_prompts(qa, QA_LEGAL_PROMPT_SECTION)
    assert _sent_record(qa)["attempt"] == 3
    _assert_no_attempt_cap(prompt)
    assert "Problema 1" not in prompt and "Problema 2" not in prompt


@pytest.mark.parametrize("phrase", _CAP_PHRASES)
def test_the_attempt_cap_check_rejects_every_way_the_cap_could_be_phrased(phrase: str) -> None:
    """The check every call in this file goes through cannot pass vacuously."""
    _assert_no_attempt_cap('Audit the article draft. {"attempt": 3}')

    with pytest.raises(AssertionError):
        _assert_no_attempt_cap(f"Audit the article draft. {phrase}")


# ---------------------------------------------------------------------------
# AC1: the rule 8 walk-through table, reproduced through the real writer_tool and qa_tool (D-C)
# ---------------------------------------------------------------------------

#: The Writer's revised draft of ``DOC_ID``: the shared revision fixture, with its provenance pointing at ``DOC_ID``.
_REVISED: Final[dict[str, Any]] = {**REVISED_DRAFT_ARGS, "source_doc_id": DOC_ID}
_A1: Final[str] = str(draft_args(DOC_ID)["headline"])
_A2: Final[str] = str(_REVISED["headline"])


def _attempts_table(state: RunState) -> list[tuple[int, str | None, str | None]]:
    """The table's second column: each attempt as ``(number, draft headline, QA status)``, ``None`` for a dash."""
    return [
        (
            record.attempt,
            None if record.draft is None else record.draft.headline,
            None if record.qa_report is None else record.qa_report.status,
        )
        for record in state.documents[DOC_ID].attempts
    ]


def _latest_headline(state: RunState) -> str | None:
    latest = state.documents[DOC_ID].latest_drafted
    return None if latest is None or latest.draft is None else latest.draft.headline


def _qa_allowed(state: RunState) -> bool:
    """The table's last column, read from the ``qa_tool`` guardrail itself."""
    return check_qa(state, DOC_ID) is None


def test_the_rule_8_table_draft_error_revision_pass_through_both_tools(state: RunState) -> None:
    """Rows 1 to 4: each audit is allowed once per draft; after a successful revision ``qa_tool`` is allowed again."""
    writer = ScriptedModel([*writer_turns(DOC_ID), *writer_turns(DOC_ID, draft=_REVISED)])
    qa = ScriptedModel([*qa_turns(DOC_ID, status="ERROR", issues=_ISSUES), *qa_turns(DOC_ID, status="PASS")])
    tools = _tools(state, qa=qa, writer=writer)

    tools["writer_tool"](doc_id=DOC_ID, revise=False)
    assert (_attempts_table(state), _latest_headline(state), _qa_allowed(state)) == ([(1, _A1, None)], _A1, True)

    audit = _result(tools["qa_tool"](doc_id=DOC_ID))
    assert audit["result"]["attempt"] == 1 and audit["result"]["qa_report"]["status"] == "ERROR"
    assert (_attempts_table(state), _latest_headline(state), _qa_allowed(state)) == ([(1, _A1, "ERROR")], _A1, False)
    refused = _result(tools["qa_tool"](doc_id=DOC_ID))
    assert refused["result"] is None and refused["error"]["guardrail"] == "already_audited"

    tools["writer_tool"](doc_id=DOC_ID, revise=True)
    assert (_attempts_table(state), _latest_headline(state), _qa_allowed(state)) == (
        [(1, _A1, "ERROR"), (2, _A2, None)],
        _A2,
        True,
    )

    audit = _result(tools["qa_tool"](doc_id=DOC_ID))
    assert audit["result"]["attempt"] == 2 and audit["result"]["qa_report"]["status"] == "PASS"
    assert (_attempts_table(state), _latest_headline(state), _qa_allowed(state)) == (
        [(1, _A1, "ERROR"), (2, _A2, "PASS")],
        _A2,
        False,
    )
    assert [(entry.stage, entry.attempt) for entry in state.ledger] == [
        ("writer", 1),
        ("qa_legal", 1),
        ("writer", 2),
        ("qa_legal", 2),
    ]
    assert qa.turns_consumed == 4  # the refused audit spent nothing


def test_the_rule_8_table_after_a_failed_revision_qa_tool_returns_already_audited(state: RunState) -> None:
    """Row 5: #2 has neither slot and A1 stays the audited latest, so ``qa_tool`` is refused until a revision lands."""
    writer = ScriptedModel(
        [*writer_turns(DOC_ID), RuntimeError("provider broke"), *writer_turns(DOC_ID, draft=_REVISED)]
    )
    qa = ScriptedModel([*qa_turns(DOC_ID, status="ERROR", issues=_ISSUES), *qa_turns(DOC_ID, status="WARNING")])
    tools = _tools(state, qa=qa, writer=writer)
    tools["writer_tool"](doc_id=DOC_ID, revise=False)
    tools["qa_tool"](doc_id=DOC_ID)

    failed = _result(tools["writer_tool"](doc_id=DOC_ID, revise=True))
    assert failed["error"] is not None
    refused = _result(tools["qa_tool"](doc_id=DOC_ID))

    assert refused["result"] is None and refused["error"]["guardrail"] == "already_audited"
    assert (_attempts_table(state), _latest_headline(state)) == ([(1, _A1, "ERROR"), (2, None, None)], _A1)
    assert qa.turns_consumed == 2

    tools["writer_tool"](doc_id=DOC_ID, revise=True)
    audit = _result(tools["qa_tool"](doc_id=DOC_ID))

    assert audit["error"] is None and audit["result"]["attempt"] == 3
    assert _attempts_table(state) == [(1, _A1, "ERROR"), (2, None, None), (3, _A2, "WARNING")]
    assert _sent_record(qa, qa.turns_consumed - 2)["attempt"] == 3  # the audit went to the revision, #3
    assert [(v.guardrail, v.tool_name) for v in state.violations] == [("already_audited", "qa_tool")]


# ---------------------------------------------------------------------------
# D-F: the checker every call goes through, and the string Strands hands the Supervisor
# ---------------------------------------------------------------------------


def _audited_state(tmp_path: Path) -> RunState:
    state = _run_state(pipeline_config(tmp_path))
    _add_attempt(state, DOC_ID, status="WARNING")
    return state


def _with_status(decoded: dict[str, Any], status: str) -> dict[str, Any]:
    """``decoded`` with its result's QA status replaced: a report other than the stored one."""
    result = decoded["result"]
    return {**decoded, "result": {**result, "qa_report": {**result["qa_report"], "status": status}}}


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda d: {**d, "extra": 1}, id="extra-top-level-key"),
        pytest.param(lambda d: {**d, "result": {**d["result"], "draft": None}}, id="draft-key"),
        pytest.param(lambda d: {**d, "result": {**d["result"], "qa_report": None}}, id="report-missing-on-success"),
        pytest.param(lambda d: _with_status(d, "PASS"), id="report-not-the-stored-one"),
        pytest.param(lambda d: {**d, "error": {"details": [{"article_body": "x"}]}}, id="nested-article-body"),
        pytest.param(lambda d: {**d, "error": "qa_tool failed: Bozza 1"}, id="headline-inside-error"),
    ],
)
def test_the_supervisor_view_check_rejects_every_way_the_result_could_be_wrong(
    tmp_path: Path, mutate: Callable[[dict[str, Any]], dict[str, Any]]
) -> None:
    """The checker every call in this file goes through cannot pass vacuously."""
    state = _audited_state(tmp_path)
    audited = state.documents[DOC_ID].attempts[0]
    clean = {"result": audited.supervisor_view(), "run": state.snapshot().model_dump(mode="json"), "error": None}
    _assert_supervisor_view(state, json.dumps(clean))

    with pytest.raises(AssertionError):
        _assert_supervisor_view(state, json.dumps(mutate(clean), ensure_ascii=False))


def test_through_a_strands_agent_the_supervisor_receives_exactly_the_checked_string(state: RunState) -> None:
    """Strands passes a ``str`` result through as the tool result's text, so the checked string is what it sees."""
    _add_attempt(state, DOC_ID)
    qa_tool = _qa_tool(state, ScriptedModel(qa_turns(DOC_ID, status="WARNING", issues=_ISSUES)))
    supervisor_model = ScriptedModel([tool_use_turn("qa_tool", {"doc_id": DOC_ID}), text_turn("Done.")])
    Agent(model=supervisor_model, tools=[qa_tool.tool_obj], callback_handler=None)("Audit the INAIL draft")

    (content,) = [
        block["toolResult"]["content"]
        for message in supervisor_model.received_messages[1]
        for block in message["content"]
        if "toolResult" in block
    ]
    _assert_supervisor_view(state, content[0]["text"])
    assert json.loads(content[0]["text"])["result"] == _audited_view(1, _report(status="WARNING", issues=_ISSUES))


# ---------------------------------------------------------------------------
# Correlation: every line a call writes carries run_id, doc_id and attempt (D-I)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["PASS", "ERROR"])
def test_every_src_tools_record_of_an_audit_carries_its_document_and_audited_attempt(
    state: RunState, caplog: pytest.LogCaptureFixture, status: str
) -> None:
    """The invocation pair and the verdict read ``doc_id`` and ``attempt`` from the log context."""
    caplog.set_level(logging.INFO, logger=TOOLS_LOGGER)
    caplog.handler.addFilter(CorrelationFilter())
    _add_attempt(state, DOC_ID, status="ERROR")
    _add_attempt(state, DOC_ID)

    _qa_tool(state, ScriptedModel(qa_turns(DOC_ID, status=status, issues=_ISSUES)))(doc_id=DOC_ID)

    records = [record for record in caplog.records if record.name == TOOLS_LOGGER]
    assert len(records) == 3
    assert {_correlation(record) for record in records} == {(RUN_ID, DOC_ID, 2)}
