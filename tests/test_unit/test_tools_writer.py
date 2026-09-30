"""``writer_tool``: writing and revising, with the attempt counter held in code (IMPLEMENTATION_PLAN.md Iteration 8).

SPECIFICATIONS.md D-C rules 1 to 7, D-E, §6.2, §6.4 and §7.2. Every test is offline and spends zero tokens (P4): the
Writer is a :class:`ScriptedModel` or a :class:`FailingModel`, and the substrate is the real ``HSEMockMCPClient`` over
an :class:`OfflineSubstrateSession`. A tool is called directly, as the Supervisor's event loop would call it, and
every string it returns in this file passes through :func:`_assert_supervisor_view` (AC2).
"""

import json
import logging
import re
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any, Final

import pytest
from strands import Agent
from strands.hooks import BeforeInvocationEvent, HookProvider, HookRegistry
from strands.tools.decorator import DecoratedFunctionTool
from strands.types.tools import AgentTool

from src.agents import WRITER_MODEL_ID
from src.guardrails import check_qa
from src.logging_setup import CorrelationFilter, configure_logging
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
    writer_turns,
)

#: The logger every ``src.tools`` event is written to.
TOOLS_LOGGER: Final[str] = "src.tools"

#: The run every test works in.
RUN_ID: Final[str] = "run-test-0008"
TODAY: Final[date] = date.fromisoformat(SCOPE_DATE_TO)

#: The candidate most tests draft, and a second one for tests that need two documents.
DOC_ID: Final[str] = "inail-2026-ot23"
OTHER_DOC_ID: Final[str] = "gu-2026-dl-caldo"

#: The ``AttemptRecord`` keys the Supervisor sees (§7.2): never ``draft`` or ``candidate``.
SUPERVISOR_ATTEMPT_KEYS: Final[frozenset[str]] = frozenset({"doc_id", "context", "attempt", "qa_report"})

#: What ``state.documents.get`` falls back to for a ``doc_id`` the Scout never returned.
_EMPTY: Final[DocumentRecord] = DocumentRecord(
    candidate=ScoutCandidate.model_validate(scout_candidate_args("none", 0.0, "Nessuno."))
)

#: The ``ArticleDraft`` fields that hold article text, none of which may reach the Supervisor (D-F).
_ARTICLE_TEXT_FIELDS: Final[tuple[str, ...]] = ("headline", "executive_summary", "article_body", "tdi_cta")


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


def _assert_supervisor_view(state: RunState, returned: Any) -> None:
    """AC2 and D-F, for one string ``writer_tool`` returned: a ``ToolResult[AttemptRecord]`` as the Supervisor sees it.

    Exactly ``result``, ``run`` and ``error``; ``run`` is the run's snapshot; a ``result`` is the supervisor view of
    a new attempt, whose QA slot is still empty; no forbidden key appears at any depth, and no article text the run
    holds appears anywhere in the string.
    """
    assert isinstance(returned, str)
    decoded = json.loads(returned)
    assert set(decoded) == {"result", "run", "error"}
    assert decoded["run"] == state.snapshot().model_dump(mode="json")
    if decoded["result"] is not None:
        assert set(decoded["result"]) == SUPERVISOR_ATTEMPT_KEYS
        assert decoded["result"]["qa_report"] is None
    assert json_keys(decoded) & FORBIDDEN_SUPERVISOR_KEYS == set()
    assert [text for text in _article_text(state) if text in returned] == []


class _CheckedTool:
    """A built tool whose every returned string is checked by :func:`_assert_supervisor_view` before a test sees it.

    Every call a test in this module makes goes through here, so AC2 holds for every result in the file.
    """

    def __init__(self, state: RunState, tool_obj: AgentTool) -> None:
        assert isinstance(tool_obj, DecoratedFunctionTool)  # a plain ``@tool`` function, callable directly
        self._state = state
        self.tool_obj = tool_obj

    def __call__(self, **arguments: Any) -> str:
        returned = self.tool_obj(**arguments)
        _assert_supervisor_view(self._state, returned)
        return returned


def _writer_tool(
    state: RunState,
    writer: Any,
    *,
    session: OfflineSubstrateSession | None = None,
    efforts: SubAgentEfforts | None = None,
    hooks: tuple[Any, ...] = (),
) -> _CheckedTool:
    """Build the tools over an offline substrate and return ``writer_tool``, with ``writer`` as the Writer's model."""
    tools = build_tools(
        state,
        client=offline_client(session if session is not None else OfflineSubstrateSession()),
        models=SubAgentModels(scout=ScriptedModel([]), writer=writer, qa_legal=ScriptedModel([])),
        efforts=efforts if efforts is not None else SubAgentEfforts(),
        hooks=hooks,
    )
    (writer_tool,) = [tool_obj for tool_obj in tools if tool_obj.tool_name == "writer_tool"]
    return _CheckedTool(state, writer_tool)


def _result(returned: str) -> dict[str, Any]:
    """Decode a tool's return value, which must be the ``for_supervisor()`` JSON string."""
    decoded = json.loads(returned)
    assert isinstance(decoded, dict)
    return decoded


def _sent_record(writer: ScriptedModel, turn: int = 0) -> dict[str, Any]:
    """The ``AttemptRecord`` JSON the Writer's user turn carried on round trip ``turn``."""
    _, _, record = sent_text(writer, turn).partition("## AttemptRecord\n")
    decoded = json.loads(record)
    assert isinstance(decoded, dict)
    return decoded


def _draftless(attempt: int) -> dict[str, Any]:
    """The supervisor view of a ``DOC_ID`` attempt whose QA slot is empty: all ``writer_tool`` ever returns (§7.2)."""
    return {"doc_id": DOC_ID, "context": {"today": SCOPE_DATE_TO}, "attempt": attempt, "qa_report": None}


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


# ---------------------------------------------------------------------------
# A first draft (revise=False): D-C rule 3, D-E step 2, §6.2
# ---------------------------------------------------------------------------


def test_a_first_draft_stores_the_writers_draft_on_attempt_one(state: RunState) -> None:
    """The one new ``AttemptRecord`` holds the Writer's ``ArticleDraft``; its QA slot is still empty."""
    _writer_tool(state, ScriptedModel(writer_turns(DOC_ID)))(doc_id=DOC_ID, revise=False)

    (record,) = state.documents[DOC_ID].attempts
    assert record.attempt == 1
    assert record.draft is not None and record.draft.model_dump() == draft_args(DOC_ID)
    assert record.qa_report is None
    assert state.documents[OTHER_DOC_ID].attempts == []


def test_a_first_draft_hands_the_writer_the_new_record_with_the_documents_own_candidate(state: RunState) -> None:
    """§6.2: the Writer receives ``{context, candidate, attempt: 1}``; the candidate is the document's, never a copy."""
    writer = ScriptedModel(writer_turns(DOC_ID))
    _writer_tool(state, writer)(doc_id=DOC_ID, revise=False)

    document = state.documents[DOC_ID]
    expected = AttemptRecord(context=AgentContext(today=TODAY), candidate=document.candidate, attempt=1)
    assert _sent_record(writer) == expected.model_dump(mode="json")
    assert document.attempts[0].candidate is document.candidate


def test_a_first_draft_returns_the_new_attempt_without_its_draft_and_no_error(state: RunState) -> None:
    """§6.4, §7.2: ``{doc_id, context, attempt, qa_report: null}``, the run snapshot and no error."""
    returned = _result(_writer_tool(state, ScriptedModel(writer_turns(DOC_ID)))(doc_id=DOC_ID, revise=False))

    assert returned == {
        "result": _draftless(1),
        "run": state.snapshot().model_dump(mode="json"),
        "error": None,
    }
    assert returned["run"]["max_attempts_per_doc"] == 3


class _AttemptsSeenByTheWriter(HookProvider):
    """Reads the document's attempts at the moment each Writer invocation starts (D-C rule 3)."""

    def __init__(self, state: RunState, doc_id: str) -> None:
        self._document = state.documents[doc_id]
        self.seen: list[list[tuple[int, bool]]] = []

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeInvocationEvent, self._read)

    def _read(self, event: BeforeInvocationEvent) -> None:
        self.seen.append([(record.attempt, record.draft is not None) for record in self._document.attempts])


def test_the_new_attempt_is_appended_before_the_writer_runs(state: RunState) -> None:
    """D-C rule 3: when the Writer starts, its attempt is already on the document, still without a draft."""
    hooks = _AttemptsSeenByTheWriter(state, DOC_ID)
    _writer_tool(state, ScriptedModel(writer_turns(DOC_ID)), hooks=(hooks,))(doc_id=DOC_ID, revise=False)

    assert hooks.seen == [[(1, False)]]


# ---------------------------------------------------------------------------
# A revision (revise=True): D-C rule 7, D-E step 5, §6.2
# ---------------------------------------------------------------------------

#: The Writer's revised draft of ``DOC_ID``: the shared revision fixture, with its provenance pointing at ``DOC_ID``.
_REVISED: Final[dict[str, Any]] = {**REVISED_DRAFT_ARGS, "source_doc_id": DOC_ID}


@pytest.mark.parametrize("status", ["ERROR", "WARNING"])
def test_a_revision_hands_the_writer_the_latest_drafted_record_with_its_draft_and_report(
    state: RunState, status: str
) -> None:
    """D-E: the Writer's one input is attempt #1 itself, draft and QA report included, with the revision wording."""
    audited = _add_attempt(state, DOC_ID, status=status)
    writer = ScriptedModel(writer_turns(DOC_ID, draft=_REVISED))

    _writer_tool(state, writer)(doc_id=DOC_ID, revise=True)

    assert _sent_record(writer) == audited.model_dump(mode="json")
    assert "Rewrite the previous draft in the record below" in sent_text(writer)


def test_a_revision_stores_the_new_draft_on_a_new_attempt_and_leaves_the_audited_one_untouched(
    state: RunState,
) -> None:
    """D-C: nothing is overwritten; attempt #2 holds the revision with an empty QA slot, #1 keeps A1 and its report."""
    audited = _add_attempt(state, DOC_ID, status="ERROR")
    before = audited.model_dump()

    writer = ScriptedModel(writer_turns(DOC_ID, draft=_REVISED))

    returned = _result(_writer_tool(state, writer)(doc_id=DOC_ID, revise=True))

    first, second = state.documents[DOC_ID].attempts
    assert first is audited and first.model_dump() == before
    assert second.attempt == 2 and second.candidate is state.documents[DOC_ID].candidate
    assert second.draft is not None and second.draft.model_dump() == _REVISED
    assert second.qa_report is None
    assert state.documents[DOC_ID].latest_drafted is second
    assert returned["result"]["attempt"] == 2 and returned["error"] is None


def test_a_revision_after_a_failed_one_is_attempt_three_and_still_revises_the_audited_draft(state: RunState) -> None:
    """D-C rules 3 and 8: the counter is the number of attempts, so #3; the latest drafted record is still #1."""
    audited = _add_attempt(state, DOC_ID, status="ERROR")
    _add_attempt(state, DOC_ID, drafted=False)
    writer = ScriptedModel(writer_turns(DOC_ID, draft=_REVISED))

    returned = _result(_writer_tool(state, writer)(doc_id=DOC_ID, revise=True))

    assert _sent_record(writer) == audited.model_dump(mode="json")
    assert [record.attempt for record in state.documents[DOC_ID].attempts] == [1, 2, 3]
    assert state.documents[DOC_ID].attempts[2].draft is not None
    assert returned["result"]["attempt"] == 3


def test_a_revision_logs_revision_requested_with_the_new_attempt_and_the_status_it_follows(
    state: RunState, caplog: pytest.LogCaptureFixture
) -> None:
    """D-I: INFO "Revision requested" with ``doc_id``, the new attempt and the QA status of the draft it revises."""
    caplog.set_level(logging.INFO, logger=TOOLS_LOGGER)
    caplog.handler.addFilter(CorrelationFilter())
    _add_attempt(state, DOC_ID, status="WARNING")

    _writer_tool(state, ScriptedModel(writer_turns(DOC_ID, draft=_REVISED)))(doc_id=DOC_ID, revise=True)

    (record,) = [r for r in caplog.records if r.getMessage().startswith("Revision requested")]
    assert record.levelno == logging.INFO
    message = record.getMessage()
    assert f"doc_id={DOC_ID}" in message and "attempt=2" in message and "follows=WARNING" in message
    assert _correlation(record) == (RUN_ID, DOC_ID, 2)
    events = [m.split(":")[0] for m in _messages(caplog, logging.INFO)]
    assert events == ["Revision requested", "Sub-agent invocation started", "Sub-agent invocation completed"]


@pytest.mark.parametrize("drafted", [False, True], ids=["no-draft", "draft-without-report"])
def test_a_revision_past_a_broken_not_audited_invariant_raises_before_using_an_attempt(
    state: RunState, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, drafted: bool
) -> None:
    """If ``check_writer`` ever admitted an unaudited revision, the call fails loudly with no side effect at all."""
    caplog.set_level(logging.INFO, logger=TOOLS_LOGGER)
    monkeypatch.setattr("src.tools.check_writer", lambda *_: None)  # the guardrail's invariant, broken on purpose
    if drafted:
        _add_attempt(state, DOC_ID)
    attempts_before = list(state.documents[DOC_ID].attempts)
    writer = ScriptedModel(writer_turns(DOC_ID, draft=_REVISED))

    with pytest.raises(RuntimeError, match="audited"):
        _writer_tool(state, writer)(doc_id=DOC_ID, revise=True)

    assert state.documents[DOC_ID].attempts == attempts_before
    assert (writer.turns_consumed, state.ledger, state.failures) == (0, [], [])
    assert _messages(caplog) == []


def test_a_first_draft_logs_no_revision_requested(state: RunState, caplog: pytest.LogCaptureFixture) -> None:
    """The event is the Supervisor's revision decision; a first draft is not one."""
    caplog.set_level(logging.INFO, logger=TOOLS_LOGGER)
    _writer_tool(state, ScriptedModel(writer_turns(DOC_ID)))(doc_id=DOC_ID, revise=False)

    assert [m.split(":")[0] for m in _messages(caplog)] == [
        "Sub-agent invocation started",
        "Sub-agent invocation completed",
    ]


# ---------------------------------------------------------------------------
# Rule 2: the Writer must dereference its source (Approach 1 D23, moved into writer_tool)
# ---------------------------------------------------------------------------

#: Approach 1's two messages, word for word (``_verify_writer_dereferenced_source``).
_NO_FETCH_MESSAGE: Final[str] = (
    f"The Writer produced a draft for {DOC_ID!r} without calling get_document_by_id at all; tools invoked: "
)
_WRONG_SOURCE_MESSAGE: Final[str] = (
    "for candidate {doc_id!r}; an empty value is its contracted report of a failed fetch and a different value "
    "means the draft is not about the document it was given."
)


def _undereferenced(case: str) -> tuple[list[list[dict[str, Any]]], str]:
    """``(Writer turns, expected FailureRecord message start or fragment)`` for one way rule 2 fails."""
    if case == "no-fetch":
        return [tool_use_turn("ArticleDraft", draft_args(DOC_ID))], _NO_FETCH_MESSAGE
    source = OTHER_DOC_ID if case == "another-document" else ""
    assert case in ("another-document", "empty-source")
    return writer_turns(DOC_ID, draft=draft_args(source)), (
        f"The Writer returned source_doc_id {source!r} " + _WRONG_SOURCE_MESSAGE.format(doc_id=DOC_ID)
    )


RULE_2_CASES: Final[tuple[str, ...]] = ("no-fetch", "another-document", "empty-source")


@pytest.mark.parametrize("case", RULE_2_CASES)
def test_an_undereferenced_draft_is_not_kept_and_the_attempt_still_counts(state: RunState, case: str) -> None:
    """D-C rule 2: the attempt stays on the document with no draft, so a first draft is still allowed."""
    turns, _ = _undereferenced(case)
    _writer_tool(state, ScriptedModel(turns))(doc_id=DOC_ID, revise=False)

    (record,) = state.documents[DOC_ID].attempts
    assert (record.attempt, record.draft, record.qa_report) == (1, None, None)
    assert state.documents[DOC_ID].latest_drafted is None


@pytest.mark.parametrize("case", RULE_2_CASES)
def test_an_undereferenced_draft_records_a_full_fetch_document_failure(state: RunState, case: str) -> None:
    """§6.7: stage ``fetch_document`` with the document and attempt, Approach 1's message and a traceback."""
    turns, expected = _undereferenced(case)
    _writer_tool(state, ScriptedModel(turns))(doc_id=DOC_ID, revise=False)

    (failure,) = state.failures
    assert (failure.stage, failure.doc_id, failure.attempt) == ("fetch_document", DOC_ID, 1)
    assert failure.error_type == "src.tools.WriterSourceFetchError"
    if case == "no-fetch":
        assert failure.message.startswith(expected) and "ArticleDraft" in failure.message
    else:
        assert failure.message == expected
    assert failure.traceback is not None and "WriterSourceFetchError" in failure.traceback
    assert state.fatal_error is None


@pytest.mark.parametrize("case", RULE_2_CASES)
def test_an_undereferenced_draft_returns_the_draftless_attempt_and_a_one_line_error(
    state: RunState, case: str
) -> None:
    """§6.4: ``result`` is the attempt without a draft; ``error`` is one line naming the failure, never its text."""
    turns, _ = _undereferenced(case)
    returned = _result(_writer_tool(state, ScriptedModel(turns))(doc_id=DOC_ID, revise=False))

    assert returned["result"] == _draftless(1)
    assert returned["error"] == "writer_tool failed: src.tools.WriterSourceFetchError"


@pytest.mark.parametrize("case", RULE_2_CASES)
def test_an_undereferenced_draft_keeps_its_one_writer_ledger_entry_and_is_logged_as_recoverable(
    state: RunState, caplog: pytest.LogCaptureFixture, case: str
) -> None:
    """D-B: the Writer's spent tokens are recorded once; D-I: WARNING "Recoverable tool failure" with full detail."""
    caplog.set_level(logging.INFO, logger=TOOLS_LOGGER)
    caplog.handler.addFilter(CorrelationFilter())
    turns, _ = _undereferenced(case)
    _writer_tool(state, ScriptedModel(turns))(doc_id=DOC_ID, revise=False)

    (entry,) = state.ledger
    assert (entry.stage, entry.doc_id, entry.attempt) == ("writer", DOC_ID, 1)
    assert entry.telemetry.total_tokens > 0
    (warning,) = [r for r in caplog.records if r.name == TOOLS_LOGGER and r.levelno == logging.WARNING]
    message = warning.getMessage()
    assert message.startswith("Recoverable tool failure returned to the Supervisor")
    assert "tool=writer_tool" in message and f"doc_id={DOC_ID}" in message and "attempt=1" in message
    assert warning.exc_info is not None and "WriterSourceFetchError" in caplog.text
    assert _correlation(warning) == (RUN_ID, DOC_ID, 1)


def test_an_undereferenced_revision_is_not_kept_and_the_audited_draft_stays_the_latest(state: RunState) -> None:
    """Rule 2 on ``revise=True``: #2 keeps no draft, A1 stays the latest and audited, so ``qa_tool`` is refused."""
    audited = _add_attempt(state, DOC_ID, status="ERROR")
    writer = ScriptedModel([tool_use_turn("ArticleDraft", _REVISED)])  # the revision skips the fetch

    returned = _result(_writer_tool(state, writer)(doc_id=DOC_ID, revise=True))

    assert [(f.stage, f.doc_id, f.attempt) for f in state.failures] == [("fetch_document", DOC_ID, 2)]
    assert returned["result"] == _draftless(2)
    assert returned["error"] == "writer_tool failed: src.tools.WriterSourceFetchError"
    assert state.documents[DOC_ID].latest_drafted is audited
    violation = check_qa(state, DOC_ID)
    assert violation is not None and violation.guardrail == "already_audited"


def test_a_fetch_of_another_document_still_counts_as_dereferencing_as_in_approach_1(state: RunState) -> None:
    """Parity: rule 2 checks that ``get_document_by_id`` was called and the echoed ID, never the call's argument."""
    writer = ScriptedModel(writer_turns(DOC_ID, fetch_doc_id=OTHER_DOC_ID))
    returned = _result(_writer_tool(state, writer)(doc_id=DOC_ID, revise=False))

    assert returned["error"] is None and state.failures == []
    assert state.documents[DOC_ID].attempts[0].draft is not None


# ---------------------------------------------------------------------------
# A failed Writer call: recoverable or fatal (§6.4, §6.7, D-C rule 3, D-D)
# ---------------------------------------------------------------------------


def _failing_writer(case: str) -> tuple[Any, OfflineSubstrateSession]:
    """``(Writer model, session)`` for one way a Writer call fails; ``fatal-*`` cases lose the substrate session."""
    if case == "build":
        return ScriptedModel([]), OfflineSubstrateSession(fail_listing_with=RuntimeError("listing broke"))
    if case == "provider-error":
        return FailingModel(RuntimeError("provider broke")), OfflineSubstrateSession()
    if case == "after-the-fetch":
        return ScriptedModel([writer_turns(DOC_ID)[0], RuntimeError("late")]), OfflineSubstrateSession()
    assert case == "fatal-after-the-fetch"
    return ScriptedModel([writer_turns(DOC_ID)[0], MCPConnectionError("died")]), OfflineSubstrateSession()


RECOVERABLE_CASES: Final[tuple[str, ...]] = ("build", "provider-error", "after-the-fetch")
FAILURE_CASES: Final[tuple[str, ...]] = (*RECOVERABLE_CASES, "fatal-after-the-fetch")


@pytest.mark.parametrize("case", RECOVERABLE_CASES)
def test_a_failed_call_records_a_writer_failure_on_its_attempt(state: RunState, case: str) -> None:
    """§6.7: stage ``writer``, tied to the document and the attempt it used; nothing fatal."""
    writer, session = _failing_writer(case)
    _writer_tool(state, writer, session=session)(doc_id=DOC_ID, revise=False)

    (failure,) = state.failures
    assert (failure.stage, failure.doc_id, failure.attempt) == ("writer", DOC_ID, 1)
    assert failure.traceback is not None
    assert state.fatal_error is None


@pytest.mark.parametrize("case", FAILURE_CASES)
def test_a_failed_call_still_uses_its_attempt_and_returns_it_without_a_draft(state: RunState, case: str) -> None:
    """D-C rule 3: the attempt stays; §6.4: ``result`` is that draft-less attempt and ``error`` is one line."""
    writer, session = _failing_writer(case)
    returned = _result(_writer_tool(state, writer, session=session)(doc_id=DOC_ID, revise=False))

    (record,) = state.documents[DOC_ID].attempts
    assert (record.attempt, record.draft) == (1, None)
    assert returned["result"] == _draftless(1)
    error = returned["error"]
    assert isinstance(error, str) and error.startswith("writer_tool failed: ") and "\n" not in error


def test_a_lost_session_records_an_mcp_session_failure_on_the_attempt_and_sets_the_fatal_slot(
    state: RunState, caplog: pytest.LogCaptureFixture
) -> None:
    """D-D: stage ``mcp_session``, still tied to the document and attempt, logged at ERROR; the slot is set."""
    caplog.set_level(logging.INFO, logger=TOOLS_LOGGER)
    writer, session = _failing_writer("fatal-after-the-fetch")
    _writer_tool(state, writer, session=session)(doc_id=DOC_ID, revise=False)

    assert isinstance(state.fatal_error, MCPConnectionError)
    assert [(f.stage, f.doc_id, f.attempt) for f in state.failures] == [("mcp_session", DOC_ID, 1)]
    (error,) = [r for r in caplog.records if r.name == TOOLS_LOGGER and r.levelno == logging.ERROR]
    assert error.getMessage().startswith("MCP session failed") and "tool=writer_tool" in error.getMessage()


@pytest.mark.parametrize("case", RECOVERABLE_CASES)
def test_a_failed_call_is_logged_as_a_recoverable_tool_failure_with_its_document_and_attempt(
    state: RunState, caplog: pytest.LogCaptureFixture, case: str
) -> None:
    """D-I: WARNING with the tool, ``doc_id``, ``attempt`` and the full detail."""
    caplog.set_level(logging.INFO, logger=TOOLS_LOGGER)
    writer, session = _failing_writer(case)
    _writer_tool(state, writer, session=session)(doc_id=DOC_ID, revise=False)

    (warning,) = [r for r in caplog.records if r.name == TOOLS_LOGGER and r.levelno == logging.WARNING]
    message = warning.getMessage()
    assert message.startswith("Recoverable tool failure returned to the Supervisor")
    assert "tool=writer_tool" in message and f"doc_id={DOC_ID}" in message and "attempt=1" in message
    assert warning.exc_info is not None


def test_a_first_draft_may_be_retried_after_a_failed_call_as_attempt_two(state: RunState) -> None:
    """D-C rule 6: no draft exists yet, so ``revise=false`` is allowed again, and it is the document's attempt #2."""
    writer = ScriptedModel([RuntimeError("provider broke"), *writer_turns(DOC_ID)])
    writer_tool = _writer_tool(state, writer)

    first = _result(writer_tool(doc_id=DOC_ID, revise=False))
    second = _result(writer_tool(doc_id=DOC_ID, revise=False))

    assert first["error"] is not None and second == {**second, "result": _draftless(2), "error": None}
    assert [record.draft is not None for record in state.documents[DOC_ID].attempts] == [False, True]
    assert len(writer.received_messages[1]) == 1  # a fresh agent: the retry starts from an empty conversation


# ---------------------------------------------------------------------------
# Telemetry (D-B) and the tool binding (P1)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", ["success", *FAILURE_CASES, "no-fetch"])
def test_every_allowed_call_appends_exactly_one_writer_ledger_entry(state: RunState, case: str) -> None:
    """D-B: stage ``writer`` with the document and attempt, the Writer's model ID and the effort it was built at."""
    if case == "success":
        writer, session = ScriptedModel(writer_turns(DOC_ID)), OfflineSubstrateSession()
    elif case == "no-fetch":
        writer, session = ScriptedModel(_undereferenced(case)[0]), OfflineSubstrateSession()
    else:
        writer, session = _failing_writer(case)
    _writer_tool(state, writer, session=session, efforts=SubAgentEfforts(writer="low"))(doc_id=DOC_ID, revise=False)

    (entry,) = state.ledger
    assert (entry.stage, entry.doc_id, entry.attempt) == ("writer", DOC_ID, 1)
    assert (entry.telemetry.model_id, entry.telemetry.reasoning_effort) == (WRITER_MODEL_ID, "low")


def test_a_revisions_ledger_entry_carries_the_new_attempt_number(state: RunState) -> None:
    """The entry belongs to the attempt the call used, never to the attempt it revised."""
    _add_attempt(state, DOC_ID, status="ERROR")
    _writer_tool(state, ScriptedModel(writer_turns(DOC_ID, draft=_REVISED)))(doc_id=DOC_ID, revise=True)

    assert [(entry.stage, entry.doc_id, entry.attempt) for entry in state.ledger] == [("writer", DOC_ID, 2)]


def test_a_successful_calls_ledger_entry_counts_both_writer_round_trips(state: RunState) -> None:
    """The fetch turn and the draft turn are one call's tokens, and ``get_document_by_id`` is its substrate tool."""
    writer = ScriptedModel(
        writer_turns(DOC_ID, input_tokens=200, output_tokens=40, fetch_input_tokens=100, fetch_output_tokens=5)
    )
    _writer_tool(state, writer)(doc_id=DOC_ID, revise=False)

    telemetry = state.ledger[0].telemetry
    assert (telemetry.input_tokens, telemetry.output_tokens) == (300, 45)
    assert ("get_document_by_id", 1) in [(t.tool_name, t.call_count) for t in telemetry.tool_invocations]


def test_the_writer_is_built_with_all_five_substrate_tools(state: RunState) -> None:
    """P1: no ``tool_names`` narrowing; the Writer's prompt, not its binding, draws the boundary."""
    session = OfflineSubstrateSession()
    writer = ScriptedModel(writer_turns(DOC_ID))
    _writer_tool(state, writer, session=session)(doc_id=DOC_ID, revise=False)

    assert session.tool_filters_seen == [None]
    assert {spec["name"] for spec in writer.received_tool_specs[0] or []} >= set(SUBSTRATE_TOOL_NAMES)


# ---------------------------------------------------------------------------
# Refusals: every check_writer violation, reached through the tool (D-C, §7.3, P2, P3)
# ---------------------------------------------------------------------------


def _unknown_document(state: RunState) -> str:
    return "not-a-scout-candidate"


def _saved_after_a_warning(state: RunState) -> str:
    """P2's own example: a ``WARNING`` saved at attempt 1, which rule 7 alone would let be revised."""
    _add_attempt(state, DOC_ID, status="WARNING")
    state.documents[DOC_ID].saved = DraftResult(
        doc_id=DOC_ID, draft_id="draft_20260922_001", path=Path("drafts") / "draft_20260922_001.md", qa_status="WARNING"
    )
    return DOC_ID


def _three_failed_attempts(state: RunState) -> str:
    for _ in range(3):
        _add_attempt(state, DOC_ID, drafted=False)
    return DOC_ID


def _drafted(state: RunState) -> str:
    _add_attempt(state, DOC_ID)
    return DOC_ID


def _nothing_drafted_yet(state: RunState) -> str:
    _add_attempt(state, DOC_ID, drafted=False)
    return DOC_ID


def _passed(state: RunState) -> str:
    _add_attempt(state, DOC_ID, status="PASS")
    return DOC_ID


REFUSALS: Final[list[Any]] = [
    pytest.param(_unknown_document, False, "not_a_candidate", id="not_a_candidate"),
    pytest.param(_saved_after_a_warning, True, "already_saved", id="already_saved"),
    pytest.param(_three_failed_attempts, False, "attempt_limit", id="attempt_limit"),
    pytest.param(_drafted, False, "initial_draft_exists", id="initial_draft_exists"),
    pytest.param(_nothing_drafted_yet, True, "not_audited", id="not_audited-no-draft"),
    pytest.param(_drafted, True, "not_audited", id="not_audited-no-report"),
    pytest.param(_passed, True, "revise_after_pass", id="revise_after_pass"),
]


@pytest.mark.parametrize(("arrange", "revise", "guardrail"), REFUSALS)
def test_a_refused_call_is_stored_logged_and_returned_with_no_result(
    state: RunState,
    caplog: pytest.LogCaptureFixture,
    arrange: Callable[[RunState], str],
    revise: bool,
    guardrail: str,
) -> None:
    """Gate 4: a complete violation, one test per ``check_writer`` guardrail, including ``already_saved`` (P2)."""
    caplog.set_level(logging.INFO, logger=TOOLS_LOGGER)
    caplog.handler.addFilter(CorrelationFilter())
    doc_id = arrange(state)
    writer = ScriptedModel(writer_turns(doc_id))

    returned = _result(_writer_tool(state, writer)(doc_id=doc_id, revise=revise))

    (violation,) = state.violations
    assert (violation.guardrail, violation.tool_name, violation.doc_id) == (guardrail, "writer_tool", doc_id)
    assert returned == {
        "result": None,
        "run": state.snapshot().model_dump(mode="json"),
        "error": violation.model_dump(mode="json"),
    }
    (warning,) = [r for r in caplog.records if r.name == TOOLS_LOGGER and r.levelno == logging.WARNING]
    message = warning.getMessage()
    assert message.startswith("Guardrail violation") and f"guardrail={guardrail}" in message
    assert "tool=writer_tool" in message and f"doc_id={doc_id}" in message and violation.message in message
    assert _correlation(warning) == (RUN_ID, doc_id, "-")  # no attempt was made


@pytest.mark.parametrize(("arrange", "revise", "guardrail"), REFUSALS)
def test_a_refused_call_uses_no_attempt_builds_no_writer_and_spends_nothing(
    state: RunState,
    caplog: pytest.LogCaptureFixture,
    arrange: Callable[[RunState], str],
    revise: bool,
    guardrail: str,
) -> None:
    """The check runs before the append (D-A step 1): no new attempt, agent, token, ledger entry or failure."""
    caplog.set_level(logging.INFO, logger=TOOLS_LOGGER)
    doc_id = arrange(state)
    attempts_before = [record.model_copy() for record in state.documents.get(doc_id, _EMPTY).attempts]
    session = OfflineSubstrateSession()
    writer = ScriptedModel(writer_turns(doc_id))

    _writer_tool(state, writer, session=session)(doc_id=doc_id, revise=revise)

    assert state.documents.get(doc_id, _EMPTY).attempts == attempts_before
    assert (session.tool_filters_seen, writer.turns_consumed, state.ledger, state.failures) == ([], 0, [], [])
    assert not any(m.startswith(("Sub-agent", "Revision requested")) for m in _messages(caplog))


# ---------------------------------------------------------------------------
# Correlation: every line a call writes carries run_id, doc_id and attempt (D-I)
# ---------------------------------------------------------------------------

#: The correlation fields of a formatted run-log line; a traceback's continuation lines carry none.
_CORRELATION: Final[re.Pattern[str]] = re.compile(r" \[run_id=(\S+) doc_id=(\S+) attempt=(\S+)\] (\S+): (.*)$")


def test_every_src_tools_record_of_a_call_carries_its_document_and_attempt(
    state: RunState, caplog: pytest.LogCaptureFixture
) -> None:
    """The started and completed pair read ``doc_id`` and ``attempt`` from the log context, not their arguments."""
    caplog.set_level(logging.INFO, logger=TOOLS_LOGGER)
    caplog.handler.addFilter(CorrelationFilter())
    _add_attempt(state, DOC_ID, status="ERROR")
    _writer_tool(state, ScriptedModel(writer_turns(DOC_ID, draft=_REVISED)))(doc_id=DOC_ID, revise=True)

    records = [record for record in caplog.records if record.name == TOOLS_LOGGER]
    assert len(records) == 3
    assert {_correlation(record) for record in records} == {(RUN_ID, DOC_ID, 2)}


@pytest.mark.usefixtures("restore_logging")
def test_every_line_a_call_writes_to_the_run_log_carries_the_run_document_and_attempt(
    state: RunState, tmp_path: Path
) -> None:
    """SDK lines too, each with its own document's attempt; a refusal made no attempt, so it reads ``-``."""
    writer = ScriptedModel([*writer_turns(DOC_ID), writer_turns(OTHER_DOC_ID)[0], RuntimeError("late")])
    writer_tool = _writer_tool(state, writer)
    log_dir = tmp_path / "logs"
    configure_logging("DEBUG", log_dir)  # after the build, so the file holds only what the calls write

    writer_tool(doc_id=DOC_ID, revise=False)  # a success, with a substrate tool call
    writer_tool(doc_id=OTHER_DOC_ID, revise=False)  # a recoverable failure after the fetch
    writer_tool(doc_id=DOC_ID, revise=False)  # a refusal: initial_draft_exists

    for handler in logging.getLogger("src").handlers:
        handler.flush()
    (log_file,) = log_dir.glob("run_*.log")
    lines = [m.groups() for m in map(_CORRELATION.search, log_file.read_text(encoding="utf-8").splitlines()) if m]
    fields = {(run_id, doc_id, attempt) for run_id, doc_id, attempt, _, _ in lines}
    assert fields == {(RUN_ID, DOC_ID, "1"), (RUN_ID, OTHER_DOC_ID, "1"), (RUN_ID, DOC_ID, "-")}
    unattributed = [(logger, message) for _, _, attempt, logger, message in lines if attempt == "-"]
    assert [message.split(":")[0] for _, message in unattributed] == ["Guardrail violation"]
    assert any(logger.startswith("strands") and doc_id == OTHER_DOC_ID for _, doc_id, _, logger, _ in lines)


# ---------------------------------------------------------------------------
# AC1: the rule 8 walk-through table, reproduced through the real writer_tool (D-C)
# ---------------------------------------------------------------------------


def _attempts_table(state: RunState) -> list[tuple[int, str | None, str | None]]:
    """The table's second column: each attempt as ``(number, draft headline, QA status)``, ``None`` for "—"."""
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


def _audit(state: RunState, status: str) -> None:
    """A stubbed ``qa_tool``: QA-Legal's report stored on the latest draft, once (Iteration 9 builds the tool)."""
    latest = state.documents[DOC_ID].latest_drafted
    assert latest is not None
    latest.set_qa_report(QAReport.model_validate(qa_args(status=status, issues=["Citazione errata."])))


_A1: Final[str] = str(draft_args(DOC_ID)["headline"])
_A2: Final[str] = str(_REVISED["headline"])


def test_the_rule_8_table_revise_after_error_then_pass(state: RunState) -> None:
    """Rows 1 to 4: draft, ``ERROR``, a successful revision, ``PASS``."""
    writer_tool = _writer_tool(state, ScriptedModel([*writer_turns(DOC_ID), *writer_turns(DOC_ID, draft=_REVISED)]))

    writer_tool(doc_id=DOC_ID, revise=False)
    assert (_attempts_table(state), _latest_headline(state), _qa_allowed(state)) == ([(1, _A1, None)], _A1, True)

    _audit(state, "ERROR")
    assert (_attempts_table(state), _latest_headline(state), _qa_allowed(state)) == ([(1, _A1, "ERROR")], _A1, False)

    writer_tool(doc_id=DOC_ID, revise=True)
    assert (_attempts_table(state), _latest_headline(state), _qa_allowed(state)) == (
        [(1, _A1, "ERROR"), (2, _A2, None)],
        _A2,
        True,
    )

    _audit(state, "PASS")
    assert (_attempts_table(state), _latest_headline(state), _qa_allowed(state)) == (
        [(1, _A1, "ERROR"), (2, _A2, "PASS")],
        _A2,
        False,
    )


def test_the_rule_8_table_a_failed_revision_leaves_the_earlier_draft_the_latest(state: RunState) -> None:
    """Row 5: #2 has neither slot, A1 stays the latest and audited, and the Supervisor may revise again from A1."""
    writer = ScriptedModel(
        [*writer_turns(DOC_ID), RuntimeError("provider broke"), *writer_turns(DOC_ID, draft=_REVISED)]
    )
    writer_tool = _writer_tool(state, writer)
    writer_tool(doc_id=DOC_ID, revise=False)
    _audit(state, "ERROR")

    failed = _result(writer_tool(doc_id=DOC_ID, revise=True))

    assert failed["result"] == _draftless(2) and failed["error"] is not None
    assert (_attempts_table(state), _latest_headline(state), _qa_allowed(state)) == (
        [(1, _A1, "ERROR"), (2, None, None)],
        _A1,
        False,
    )

    writer_tool(doc_id=DOC_ID, revise=True)
    assert _sent_record(writer, writer.turns_consumed - 2)["attempt"] == 1  # the retry revised A1 again
    assert (_attempts_table(state), _latest_headline(state), _qa_allowed(state)) == (
        [(1, _A1, "ERROR"), (2, None, None), (3, _A2, None)],
        _A2,
        True,
    )


def test_a_fourth_call_is_refused_whatever_became_of_the_first_three(state: RunState) -> None:
    """D-C rule 4 through the tool: three failed calls use every attempt; a fourth is ``attempt_limit``."""
    writer = ScriptedModel([RuntimeError("one"), RuntimeError("two"), RuntimeError("three")])
    writer_tool = _writer_tool(state, writer)
    for _ in range(3):
        writer_tool(doc_id=DOC_ID, revise=False)

    returned = _result(writer_tool(doc_id=DOC_ID, revise=False))

    assert [record.attempt for record in state.documents[DOC_ID].attempts] == [1, 2, 3]
    assert returned["result"] is None and returned["error"]["guardrail"] == "attempt_limit"
    assert (writer.turns_consumed, len(state.ledger)) == (3, 3)


# ---------------------------------------------------------------------------
# AC2: writer_tool never returns article text (D-F)
# ---------------------------------------------------------------------------


def _drafted_state(tmp_path: Path) -> RunState:
    state = _run_state(pipeline_config(tmp_path))
    _add_attempt(state, DOC_ID)
    return state


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda d: {**d, "extra": 1}, id="extra-top-level-key"),
        pytest.param(lambda d: {**d, "result": {**d["result"], "draft": None}}, id="draft-key"),
        pytest.param(lambda d: {**d, "result": {**d["result"], "qa_report": {"status": "PASS"}}}, id="qa-report-set"),
        pytest.param(lambda d: {**d, "error": {"details": [{"article_body": "x"}]}}, id="nested-article-body"),
        pytest.param(lambda d: {**d, "error": "writer_tool failed: Bozza 1"}, id="headline-inside-error"),
    ],
)
def test_the_supervisor_view_check_rejects_every_way_article_text_could_leak(
    tmp_path: Path, mutate: Callable[[dict[str, Any]], dict[str, Any]]
) -> None:
    """The checker every call in this file goes through cannot pass vacuously."""
    state = _drafted_state(tmp_path)
    clean = {"result": _draftless(1), "run": state.snapshot().model_dump(mode="json"), "error": None}
    _assert_supervisor_view(state, json.dumps(clean))

    with pytest.raises(AssertionError):
        _assert_supervisor_view(state, json.dumps(mutate(clean), ensure_ascii=False))


def test_through_a_strands_agent_the_supervisor_receives_exactly_the_checked_string(state: RunState) -> None:
    """Strands passes a ``str`` result through as the tool result's text, so the checked string is what it sees."""
    writer_tool = _writer_tool(state, ScriptedModel(writer_turns(DOC_ID)))
    supervisor_model = ScriptedModel(
        [tool_use_turn("writer_tool", {"doc_id": DOC_ID, "revise": False}), text_turn("Done.")]
    )
    Agent(model=supervisor_model, tools=[writer_tool.tool_obj], callback_handler=None)("Draft the INAIL update")

    (content,) = [
        block["toolResult"]["content"]
        for message in supervisor_model.received_messages[1]
        for block in message["content"]
        if "toolResult" in block
    ]
    _assert_supervisor_view(state, content[0]["text"])
    assert json.loads(content[0]["text"])["result"] == _draftless(1)
    assert state.documents[DOC_ID].attempts[0].draft is not None
