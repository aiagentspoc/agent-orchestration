"""``save_draft``: marking one audited document saved and allocating its draft ID, with no file written (Iteration 10).

SPECIFICATIONS.md D-B, D-C rules 9–11, §6.4, §6.8 "Draft IDs", §7.1 and §7.3; AGENTS.md Rule 5. ``save_draft`` is
plain Python: it builds no sub-agent and spends no token. The tools are built over an offline substrate with
scripted models (P4), and every ``save_draft`` call in this file passes through :class:`_CheckedTool`, which checks
the string the Supervisor would receive and that the drafts folder is exactly as it was before the call (AC1).
"""

import json
import logging
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any, Final

import pytest
from strands.models.model import Model
from strands.tools.decorator import DecoratedFunctionTool
from strands.types.tools import AgentTool

from src.logging_setup import CorrelationFilter
from src.schemas import (
    AgentContext,
    ArticleDraft,
    AttemptRecord,
    DocumentRecord,
    DraftResult,
    PipelineConfig,
    QAReport,
    QAStatus,
    RunContext,
    RunState,
    ScoutCandidate,
)
from src.tools import SubAgentEfforts, SubAgentModels, build_tools
from tests.support.scripted import (
    FORBIDDEN_SUPERVISOR_KEYS,
    SCOPE_DATE_TO,
    OfflineSubstrateSession,
    ScriptedModel,
    draft_args,
    json_keys,
    offline_client,
    pipeline_config,
    qa_args,
    scout_candidate_args,
    tool_use_turn,
    writer_turns,
)

#: The logger every ``src.tools`` event is written to.
TOOLS_LOGGER: Final[str] = "src.tools"

#: The run every test works in, dated ``SCOPE_DATE_TO``, which is not the system date.
RUN_ID: Final[str] = "run-test-0010"
TODAY: Final[date] = date.fromisoformat(SCOPE_DATE_TO)
STAMP: Final[str] = TODAY.strftime("%Y%m%d")

#: The Scout's two candidates, in rank order.
DOC_ID: Final[str] = "inail-2026-ot23"
OTHER_DOC_ID: Final[str] = "gu-2026-dl-caldo"

#: The keys of a ``DraftResult`` (§6.4): no article text, no attempt record.
DRAFT_RESULT_KEYS: Final[frozenset[str]] = frozenset({"doc_id", "draft_id", "path", "qa_status"})

#: The ``ArticleDraft`` fields that hold article text, none of which may reach the Supervisor (D-F).
_ARTICLE_TEXT_FIELDS: Final[tuple[str, ...]] = ("headline", "executive_summary", "article_body", "tdi_cta")


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


def _run_state(config: PipelineConfig, *, max_drafts: int | None = None) -> RunState:
    """A run whose Scout returned ``DOC_ID`` and ``OTHER_DOC_ID``; the ceiling is set on both config and context."""
    state = RunState(
        run_id=RUN_ID, config=config, context=RunContext(today=TODAY, max_drafts=max_drafts, drafts_saved=0)
    )
    for index, doc_id in enumerate((DOC_ID, OTHER_DOC_ID)):
        candidate = ScoutCandidate.model_validate(scout_candidate_args(doc_id, 0.9 - index / 10, f"Obblighi {doc_id}."))
        state.documents[doc_id] = DocumentRecord(candidate=candidate)
    return state


@pytest.fixture
def state(tmp_path: Path) -> RunState:
    return _run_state(pipeline_config(tmp_path))


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


def _article_text(state: RunState) -> set[str]:
    """Every piece of article text the run holds, across every document and attempt."""
    return {
        getattr(record.draft, field)
        for document in state.documents.values()
        for record in document.attempts
        if record.draft is not None
        for field in _ARTICLE_TEXT_FIELDS
    }


def _folder_contents(folder: Path) -> dict[str, bytes] | None:
    """Every file in ``folder`` with its bytes, or ``None`` if the folder does not exist."""
    if not folder.exists():
        return None
    return {path.name: path.read_bytes() for path in sorted(folder.iterdir())}


def _assert_supervisor_view(state: RunState, returned: Any) -> None:
    """D-F and §6.4, for one string ``save_draft`` returned: a ``ToolResult[DraftResult]`` as the Supervisor sees it.

    Exactly ``result``, ``run`` and ``error``; ``run`` is the run's snapshot; a ``result`` is the stored
    ``DraftResult`` of the document it names, whole; no forbidden key at any depth and no article text anywhere.
    """
    assert isinstance(returned, str)
    decoded = json.loads(returned)
    assert set(decoded) == {"result", "run", "error"}
    assert decoded["run"] == state.snapshot().model_dump(mode="json")
    result = decoded["result"]
    if result is not None:
        assert set(result) == DRAFT_RESULT_KEYS
        saved = state.documents[result["doc_id"]].saved
        assert saved is not None and result == saved.model_dump(mode="json")
        assert decoded["error"] is None
    assert json_keys(decoded) & FORBIDDEN_SUPERVISOR_KEYS == set()
    assert [text for text in _article_text(state) if text in returned] == []


class _CheckedTool:
    """A built tool whose every call is checked before a test sees its result.

    For ``save_draft``: the returned string passes :func:`_assert_supervisor_view`, and the drafts folder, present
    or absent, is byte for byte what it was before the call (AC1: nothing is written until run end).
    """

    def __init__(self, state: RunState, tool_obj: AgentTool) -> None:
        assert isinstance(tool_obj, DecoratedFunctionTool)  # a plain ``@tool`` function, callable directly
        self._state = state
        self.tool_obj = tool_obj

    def __call__(self, **arguments: Any) -> str:
        drafts_dir = self._state.config.drafts_dir
        before = _folder_contents(drafts_dir)
        returned = self.tool_obj(**arguments)
        if self.tool_obj.tool_name == "save_draft":
            _assert_supervisor_view(self._state, returned)
            assert _folder_contents(drafts_dir) == before
        return returned


def _tools(
    state: RunState, *, writer: Model | None = None, qa: Model | None = None
) -> dict[str, _CheckedTool]:
    """Build the four tools over an offline substrate, with scripted Writer and QA-Legal models."""
    tools = build_tools(
        state,
        client=offline_client(OfflineSubstrateSession()),
        models=SubAgentModels(
            scout=ScriptedModel([]),
            writer=writer if writer is not None else ScriptedModel([]),
            qa_legal=qa if qa is not None else ScriptedModel([]),
        ),
        efforts=SubAgentEfforts(),
    )
    return {tool_obj.tool_name: _CheckedTool(state, tool_obj) for tool_obj in tools}


def _save(state: RunState, doc_id: str) -> dict[str, Any]:
    """Call ``save_draft`` on ``doc_id`` through a freshly built tool set, and decode what it returned."""
    decoded = json.loads(_tools(state)["save_draft"](doc_id=doc_id))
    assert isinstance(decoded, dict)
    return decoded


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
# A successful save: D-C rules 9–11, §6.4
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["PASS", "WARNING"])
def test_an_audited_draft_is_marked_saved_with_its_draft_id_path_and_qa_status(
    state: RunState, status: QAStatus
) -> None:
    """``saved`` is a ``DraftResult`` whose path is ``drafts_dir / f"{draft_id}.md"``; the result is that record."""
    _add_attempt(state, DOC_ID, status=status)

    returned = _save(state, DOC_ID)

    draft_id = f"draft_{STAMP}_001"
    expected = DraftResult(
        doc_id=DOC_ID, draft_id=draft_id, path=state.config.drafts_dir / f"{draft_id}.md", qa_status=status
    )
    assert state.documents[DOC_ID].saved == expected
    assert returned == {
        "result": expected.model_dump(mode="json"),
        "run": {"today": SCOPE_DATE_TO, "max_attempts_per_doc": 3, "max_drafts": None, "drafts_saved": 1},
        "error": None,
    }
    assert state.documents[OTHER_DOC_ID].saved is None
    assert (state.violations, state.failures) == ([], [])


# ---------------------------------------------------------------------------
# Refusals: every check_save violation, reached through the tool (D-C rules 9 and 10, §7.3, P2, P3)
# ---------------------------------------------------------------------------


def _unknown_document(tmp_path: Path) -> tuple[RunState, str]:
    """P3: a ``doc_id`` the Scout never returned."""
    return _run_state(pipeline_config(tmp_path)), "not-a-scout-candidate"


def _saved_once_already(tmp_path: Path) -> tuple[RunState, str]:
    """Rule 10: a second save of a document ``save_draft`` itself saved."""
    state = _run_state(pipeline_config(tmp_path))
    _add_attempt(state, DOC_ID, status="PASS")
    assert _save(state, DOC_ID)["error"] is None
    return state, DOC_ID


def _no_attempts(tmp_path: Path) -> tuple[RunState, str]:
    return _run_state(pipeline_config(tmp_path)), DOC_ID


def _unaudited_latest(tmp_path: Path) -> tuple[RunState, str]:
    """Rule 9: the latest draft is a successful revision not yet audited, though the one before it was."""
    state = _run_state(pipeline_config(tmp_path))
    _add_attempt(state, DOC_ID, status="WARNING")
    _add_attempt(state, DOC_ID)
    return state, DOC_ID


def _only_a_failed_attempt(tmp_path: Path) -> tuple[RunState, str]:
    state = _run_state(pipeline_config(tmp_path))
    _add_attempt(state, DOC_ID, drafted=False)
    return state, DOC_ID


def _error_at_attempt(attempts: int) -> Callable[[Path], tuple[RunState, str]]:
    """Rule 9: the latest draft is audited ``ERROR`` after ``attempts`` attempts, with attempts still remaining."""

    def arrange(tmp_path: Path) -> tuple[RunState, str]:
        state = _run_state(pipeline_config(tmp_path))
        for _ in range(attempts):
            _add_attempt(state, DOC_ID, status="ERROR")
        return state, DOC_ID

    return arrange


def _at_the_draft_ceiling(tmp_path: Path) -> tuple[RunState, str]:
    """``--max-drafts 1``: one document saved, so an audited second one is refused."""
    state = _run_state(pipeline_config(tmp_path, max_drafts=1), max_drafts=1)
    _add_attempt(state, DOC_ID, status="PASS")
    _add_attempt(state, OTHER_DOC_ID, status="PASS")
    assert _save(state, DOC_ID)["error"] is None
    return state, OTHER_DOC_ID


REFUSALS: Final[list[Any]] = [
    pytest.param(_unknown_document, "not_a_candidate", id="not_a_candidate"),
    pytest.param(_saved_once_already, "already_saved", id="already_saved"),
    pytest.param(_no_attempts, "not_audited", id="not_audited-no-attempts"),
    pytest.param(_unaudited_latest, "not_audited", id="not_audited-unaudited-latest"),
    pytest.param(_only_a_failed_attempt, "not_audited", id="not_audited-failed-attempt"),
    pytest.param(_error_at_attempt(1), "error_with_attempts_remaining", id="error_with_attempts_remaining-1"),
    pytest.param(_error_at_attempt(2), "error_with_attempts_remaining", id="error_with_attempts_remaining-2"),
    pytest.param(_at_the_draft_ceiling, "draft_ceiling", id="draft_ceiling"),
]


@pytest.mark.parametrize(("arrange", "guardrail"), REFUSALS)
def test_a_refused_save_is_stored_logged_and_returned_with_no_result(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    arrange: Callable[[Path], tuple[RunState, str]],
    guardrail: str,
) -> None:
    """Gate 4: a complete violation, one test per ``check_save`` guardrail, including ``already_saved`` (P2)."""
    state, doc_id = arrange(tmp_path)
    caplog.set_level(logging.INFO, logger=TOOLS_LOGGER)
    caplog.handler.addFilter(CorrelationFilter())
    caplog.clear()  # an arrange that saves through the tool logs its own save

    returned = _save(state, doc_id)

    (violation,) = state.violations
    assert (violation.guardrail, violation.tool_name, violation.doc_id) == (guardrail, "save_draft", doc_id)
    assert returned == {
        "result": None,
        "run": state.snapshot().model_dump(mode="json"),
        "error": violation.model_dump(mode="json"),
    }
    (warning,) = [r for r in caplog.records if r.name == TOOLS_LOGGER and r.levelno == logging.WARNING]
    message = warning.getMessage()
    assert message.startswith("Guardrail violation") and f"guardrail={guardrail}" in message
    assert "tool=save_draft" in message and f"doc_id={doc_id}" in message and violation.message in message
    assert _correlation(warning) == (RUN_ID, doc_id, "-")
    assert not any(m.startswith("Document marked saved") for m in _messages(caplog))


@pytest.mark.parametrize(("arrange", "guardrail"), REFUSALS)
def test_a_refused_save_marks_nothing_saved_and_leaves_drafts_saved_unchanged(
    tmp_path: Path, arrange: Callable[[Path], tuple[RunState, str]], guardrail: str
) -> None:
    """Nothing is allocated or marked: every document's ``saved`` and the snapshot's count are as they were."""
    state, doc_id = arrange(tmp_path)
    saved_before = {key: document.saved for key, document in state.documents.items()}
    drafts_saved_before = state.snapshot().drafts_saved

    returned = _save(state, doc_id)

    assert {key: document.saved for key, document in state.documents.items()} == saved_before
    assert returned["run"]["drafts_saved"] == drafts_saved_before
    assert (state.ledger, state.failures) == ([], [])


# ---------------------------------------------------------------------------
# The save log (D-I): "Document marked saved", and nothing of a sub-agent
# ---------------------------------------------------------------------------


def _passed_at_once(state: RunState) -> None:
    _add_attempt(state, DOC_ID, status="PASS")


def _error_at_the_cap(state: RunState) -> None:
    for _ in range(3):
        _add_attempt(state, DOC_ID, status="ERROR")


def _warning_then_a_failed_revision(state: RunState) -> None:
    """Rule 8 table, row 5: the failed #3 leaves the audited #2 the latest draft; three attempts are used."""
    _add_attempt(state, DOC_ID, status="ERROR")
    _add_attempt(state, DOC_ID, status="WARNING")
    _add_attempt(state, DOC_ID, drafted=False)


SAVES: Final[list[Any]] = [
    pytest.param(_passed_at_once, 1, 1, "PASS", id="pass-at-attempt-1"),
    pytest.param(_error_at_the_cap, 3, 3, "ERROR", id="error-at-the-cap"),
    pytest.param(_warning_then_a_failed_revision, 2, 3, "WARNING", id="earlier-draft-after-a-failed-call"),
]


@pytest.mark.parametrize(("arrange", "saved_attempt", "attempts_used", "status"), SAVES)
def test_a_save_is_logged_at_info_with_its_draft_id_qa_status_and_attempts_used(
    state: RunState,
    caplog: pytest.LogCaptureFixture,
    arrange: Callable[[RunState], None],
    saved_attempt: int,
    attempts_used: int,
    status: str,
) -> None:
    """D-I: one INFO line, with ``attempts`` = ``attempts_used`` (rule 11); its ``attempt`` is the saved draft's."""
    caplog.set_level(logging.INFO, logger=TOOLS_LOGGER)
    caplog.handler.addFilter(CorrelationFilter())
    arrange(state)

    _save(state, DOC_ID)

    (record,) = [r for r in caplog.records if r.name == TOOLS_LOGGER]
    message = record.getMessage()
    assert record.levelno == logging.INFO and message.startswith("Document marked saved")
    assert f"doc_id={DOC_ID}" in message and f"draft_id=draft_{STAMP}_001" in message
    assert f"qa_status={status}" in message and f"attempts={attempts_used}" in message
    assert _correlation(record) == (RUN_ID, DOC_ID, saved_attempt)


@pytest.mark.parametrize(("arrange", "saved_attempt", "attempts_used", "status"), SAVES)
def test_the_save_takes_the_latest_drafted_attempts_report_and_spends_nothing(
    state: RunState,
    arrange: Callable[[RunState], None],
    saved_attempt: int,
    attempts_used: int,
    status: str,
) -> None:
    """Rule 9: "saves that draft and that report", an ``ERROR`` at the cap included; plain Python, no ledger entry."""
    arrange(state)
    document = state.documents[DOC_ID]
    assert document.latest_drafted is not None and document.latest_drafted.attempt == saved_attempt

    returned = _save(state, DOC_ID)

    assert document.saved is not None and document.saved.qa_status == status
    assert returned["result"]["qa_status"] == status and returned["run"]["drafts_saved"] == 1
    assert document.attempts_used == attempts_used  # a save uses no attempt
    assert (state.ledger, state.failures, state.violations) == ([], [], [])


# ---------------------------------------------------------------------------
# Draft IDs through the tool: save order, past the disk, and no file (§6.8, AC1)
# ---------------------------------------------------------------------------


def test_draft_ids_follow_save_order_not_scout_rank(state: RunState) -> None:
    """The lower-ranked document saved first gets ``_001``: run-end rendering is in save order."""
    _add_attempt(state, DOC_ID, status="PASS")
    _add_attempt(state, OTHER_DOC_ID, status="WARNING")
    save_draft = _tools(state)["save_draft"]

    first = json.loads(save_draft(doc_id=OTHER_DOC_ID))
    second = json.loads(save_draft(doc_id=DOC_ID))

    assert [first["result"]["draft_id"], second["result"]["draft_id"]] == [f"draft_{STAMP}_001", f"draft_{STAMP}_002"]
    assert [first["run"]["drafts_saved"], second["run"]["drafts_saved"]] == [1, 2]
    assert not state.config.drafts_dir.exists()


def test_with_004_on_disk_two_saves_allocate_005_and_006_and_write_nothing(state: RunState) -> None:
    """The disk is counted, the run's own IDs are counted, and the folder is byte for byte unchanged."""
    drafts_dir = state.config.drafts_dir
    drafts_dir.mkdir()
    (drafts_dir / f"draft_{STAMP}_004.md").write_text("# Bozza 4", encoding="utf-8")
    _add_attempt(state, DOC_ID, status="PASS")
    _add_attempt(state, OTHER_DOC_ID, status="PASS")
    save_draft = _tools(state)["save_draft"]

    save_draft(doc_id=DOC_ID)
    save_draft(doc_id=OTHER_DOC_ID)

    assert [document.saved.draft_id for document in state.documents.values() if document.saved is not None] == [
        f"draft_{STAMP}_005",
        f"draft_{STAMP}_006",
    ]
    assert [path.name for path in drafts_dir.iterdir()] == [f"draft_{STAMP}_004.md"]


# ---------------------------------------------------------------------------
# P2 through the real tools: a document save_draft saved is closed to writer_tool and qa_tool
# ---------------------------------------------------------------------------


def _qa_turns(doc_id: str, *, status: str, issues: list[str] | None = None) -> list[Any]:
    """Script one QA-Legal invocation: fetch the draft's source, then issue the ``QAReport``."""
    return [
        tool_use_turn("get_document_by_id", {"doc_id": doc_id}),
        tool_use_turn("QAReport", qa_args(status=status, issues=issues)),
    ]


def test_after_a_save_writer_tool_and_qa_tool_refuse_the_document_with_already_saved(state: RunState) -> None:
    """Draft, audit ``WARNING``, save; then a revision, a restart and an audit are each refused, spending nothing."""
    writer = ScriptedModel(writer_turns(DOC_ID))
    qa = ScriptedModel(_qa_turns(DOC_ID, status="WARNING", issues=["Riferimento facoltativo mancante."]))
    tools = _tools(state, writer=writer, qa=qa)
    tools["writer_tool"](doc_id=DOC_ID, revise=False)
    tools["qa_tool"](doc_id=DOC_ID)

    saved = json.loads(tools["save_draft"](doc_id=DOC_ID))
    refused = [
        json.loads(tools["writer_tool"](doc_id=DOC_ID, revise=True)),
        json.loads(tools["writer_tool"](doc_id=DOC_ID, revise=False)),
        json.loads(tools["qa_tool"](doc_id=DOC_ID)),
    ]

    assert saved["error"] is None and saved["result"]["qa_status"] == "WARNING"
    assert [(r["result"], r["error"]["guardrail"], r["error"]["tool_name"]) for r in refused] == [
        (None, "already_saved", "writer_tool"),
        (None, "already_saved", "writer_tool"),
        (None, "already_saved", "qa_tool"),
    ]
    assert [(v.guardrail, v.tool_name) for v in state.violations] == [
        ("already_saved", "writer_tool"),
        ("already_saved", "writer_tool"),
        ("already_saved", "qa_tool"),
    ]
    assert state.documents[DOC_ID].attempts_used == 1
    assert [(entry.stage, entry.attempt) for entry in state.ledger] == [("writer", 1), ("qa_legal", 1)]
    assert state.documents[DOC_ID].saved == DraftResult.model_validate(saved["result"])


# ---------------------------------------------------------------------------
# The guardrail's invariant: a broken check_save never marks anything saved
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("drafted", [False, True], ids=["no-draft", "unaudited-draft"])
def test_a_save_past_a_broken_check_save_invariant_raises_before_allocating_anything(
    state: RunState, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, drafted: bool
) -> None:
    """If ``check_save`` ever admitted a document with no audited draft, the call fails loudly and changes nothing."""
    caplog.set_level(logging.INFO, logger=TOOLS_LOGGER)
    monkeypatch.setattr("src.tools.check_save", lambda *_: None)  # the guardrail's invariant, broken on purpose
    if drafted:
        _add_attempt(state, DOC_ID)
    save_draft = _tools(state)["save_draft"].tool_obj

    with pytest.raises(RuntimeError, match="no audited draft"):
        save_draft(doc_id=DOC_ID)

    assert state.documents[DOC_ID].saved is None and state.snapshot().drafts_saved == 0
    assert (state.ledger, state.failures, state.violations) == ([], [], [])
    assert _messages(caplog) == []
    assert not state.config.drafts_dir.exists()
