"""Unit tests for the D-C guardrail checks (IMPLEMENTATION_PLAN.md Iteration 5; SPECIFICATIONS.md §7.3).

Every check is a pure function over a hand-built ``RunState``: no agent, no substrate and no I/O. Documents are
advanced by hand exactly as the tools will advance them, by appending an ``AttemptRecord`` and filling its slots
through ``set_draft`` and ``set_qa_report``.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal, TypeAlias, get_args

import pytest

from src.guardrails import (
    QA_TOOL,
    SAVE_DRAFT_TOOL,
    SCOUT_TOOL,
    WRITER_TOOL,
    ScoutArgs,
    check_qa,
    check_save,
    check_scout,
    check_writer,
)
from src.schemas import (
    MAX_ATTEMPTS_PER_DOC,
    AgentContext,
    ArticleDraft,
    AttemptRecord,
    DocumentRecord,
    DraftResult,
    GuardrailName,
    GuardrailViolation,
    PipelineScope,
    QAReport,
    QAStatus,
    RunContext,
    RunState,
    ScoutCandidate,
    Source,
)
from tests.support.scripted import (
    DEFAULT_DOC_ID,
    DRAFT_ARGS,
    SCOPE_DATE_FROM,
    SCOPE_DATE_TO,
    pipeline_config,
    qa_args,
    scout_candidate_args,
)

TODAY = date(2026, 9, 29)


def _scope_args(
    *,
    date_from: str = SCOPE_DATE_FROM,
    date_to: str = SCOPE_DATE_TO,
    sources: list[str] | None = None,
    sector_constraints: list[str] | None = None,
    max_drafts: int | None = None,
) -> ScoutArgs:
    """Build the five ``scout_tool`` arguments of §6.4, valid unless a field is overridden."""
    return ScoutArgs(
        date_from=date_from,
        date_to=date_to,
        sources=["INAIL"] if sources is None else sources,
        sector_constraints=["construction"] if sector_constraints is None else sector_constraints,
        max_drafts=max_drafts,
    )


def _candidate(doc_id: str) -> ScoutCandidate:
    """Build the scripted Scout candidate for ``doc_id``."""
    return ScoutCandidate.model_validate(scout_candidate_args(doc_id, 0.9, f"Obblighi immediati ({doc_id})."))


def _state(tmp_path: Path, *doc_ids: str, max_drafts: int | None = None) -> RunState:
    """Build a fresh run state with one not-drafted document per ``doc_id``.

    ``config.max_drafts`` and ``context.max_drafts`` are set from the one value, as the composition root will set
    them; ``context.drafts_saved`` stays 0, the stored value that a check must never read.
    """
    return RunState(
        run_id="run-0001",
        config=pipeline_config(tmp_path, max_drafts=max_drafts),
        context=RunContext(today=TODAY, max_drafts=max_drafts, drafts_saved=0),
        documents={doc_id: DocumentRecord(candidate=_candidate(doc_id)) for doc_id in doc_ids},
    )


def test_tool_name_constants_are_the_supervisor_tool_names_of_section_7_1() -> None:
    """§7.1: a violation names the tool that was refused, by the name the Supervisor called it with."""
    assert (SCOUT_TOOL, WRITER_TOOL, QA_TOOL, SAVE_DRAFT_TOOL) == ("scout_tool", "writer_tool", "qa_tool", "save_draft")


def test_check_scout_returns_a_valid_scope_with_its_context_filled_in(tmp_path: Path) -> None:
    """§6.2: the Supervisor's five fields become a ``PipelineScope``; code adds ``context`` from the run."""
    state = _state(tmp_path)
    sources: list[Source] = ["INAIL", "EUR_LEX"]

    scope = check_scout(state, _scope_args(sources=list(sources), max_drafts=2))

    assert isinstance(scope, PipelineScope)
    assert scope.context == AgentContext(today=TODAY)
    assert (scope.date_from, scope.date_to) == (SCOPE_DATE_FROM, SCOPE_DATE_TO)
    assert scope.sources == sources
    assert scope.sector_constraints == ["construction"]
    assert scope.max_drafts == 2


def test_check_scout_fills_context_from_the_run_even_if_one_is_sent(tmp_path: Path) -> None:
    """§6.2: code adds ``context``; a ``context`` key in the raw arguments never overrides the run's date."""
    args = _scope_args()
    args.update({"context": {"today": "2000-01-01"}})  # type: ignore[typeddict-unknown-key]

    scope = check_scout(_state(tmp_path), args)

    assert isinstance(scope, PipelineScope)
    assert scope.context == AgentContext(today=TODAY)


def test_check_scout_allows_a_one_day_window_and_empty_lists(tmp_path: Path) -> None:
    """``date_from == date_to`` is a valid window, and empty lists mean all sources and all sectors."""
    scope = check_scout(
        _state(tmp_path), _scope_args(date_from=SCOPE_DATE_TO, date_to=SCOPE_DATE_TO, sources=[], sector_constraints=[])
    )

    assert isinstance(scope, PipelineScope)
    assert (scope.sources, scope.sector_constraints, scope.max_drafts) == ([], [], None)


def test_check_scout_refuses_once_a_scope_is_set(tmp_path: Path) -> None:
    """D-C run-level guardrails: the Scout runs once; a scope on the state marks the one successful call."""
    state = _state(tmp_path)
    first = check_scout(state, _scope_args())
    assert isinstance(first, PipelineScope)
    state.scope = first  # as scout_tool will, once its Scout call succeeds

    refused = check_scout(state, _scope_args())

    assert isinstance(refused, GuardrailViolation)
    assert refused.guardrail == "scout_already_run"
    assert refused.tool_name == "scout_tool"
    assert refused.doc_id is None
    assert "once per run" in refused.message


@pytest.mark.parametrize("field", ["date_from", "date_to"])
@pytest.mark.parametrize(
    "raw",
    ["22/06/2026", "not-a-date", "20260622", "2026-W26-1", ""],
    ids=["day-first", "prose", "basic-form", "week-form", "empty"],
)
def test_check_scout_refuses_a_date_that_is_not_extended_iso(tmp_path: Path, field: str, raw: str) -> None:
    """§7.3: only ``YYYY-MM-DD`` passes; ``fromisoformat`` also reads ``20260622``, so the form is round-tripped."""
    args = _scope_args(date_from=raw) if field == "date_from" else _scope_args(date_to=raw)

    refused = check_scout(_state(tmp_path), args)

    assert isinstance(refused, GuardrailViolation)
    assert (refused.guardrail, refused.tool_name, refused.doc_id) == ("invalid_scope", "scout_tool", None)
    assert field in refused.message
    assert repr(raw) in refused.message
    assert "YYYY-MM-DD" in refused.message


def test_check_scout_refuses_an_inverted_window_and_names_both_dates(tmp_path: Path) -> None:
    """§7.3: ``date_from`` later than ``date_to`` is ``invalid_scope`` (Approach 1's ``_validate_scope_bounds``)."""
    refused = check_scout(_state(tmp_path), _scope_args(date_from=SCOPE_DATE_TO, date_to=SCOPE_DATE_FROM))

    assert isinstance(refused, GuardrailViolation)
    assert refused.guardrail == "invalid_scope"
    assert "date_from" in refused.message and "date_to" in refused.message
    assert SCOPE_DATE_TO in refused.message and SCOPE_DATE_FROM in refused.message


def test_check_scout_refuses_an_unknown_source_with_the_pydantic_message(tmp_path: Path) -> None:
    """§6.4: ``sources`` arrives as ``list[str]``, so an unknown source reaches code and becomes ``invalid_scope``."""
    refused = check_scout(_state(tmp_path), _scope_args(sources=["INAIL", "OSHA"]))

    assert isinstance(refused, GuardrailViolation)
    assert refused.guardrail == "invalid_scope"
    assert "sources" in refused.message
    assert "Input should be 'EUR_LEX', 'GAZZETTA_UFFICIALE' or 'INAIL'" in refused.message
    assert "errors.pydantic.dev" not in refused.message  # the version-specific help URL is not the Supervisor's


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"max_drafts": "many"}, "max_drafts"),
        ({"date_from": 20260622}, "date_from"),
        ({"sector_constraints": "construction"}, "sector_constraints"),
    ],
    ids=["max-drafts-not-int", "date-not-str", "sectors-not-list"],
)
def test_check_scout_maps_any_scope_validation_error_to_invalid_scope(
    tmp_path: Path, overrides: dict[str, object], field: str
) -> None:
    """§7.3: any validation error raised while building the ``PipelineScope`` is ``invalid_scope``, never raised."""
    args = _scope_args()
    args.update(overrides)  # type: ignore[typeddict-item]

    refused = check_scout(_state(tmp_path), args)

    assert isinstance(refused, GuardrailViolation)
    assert refused.guardrail == "invalid_scope"
    assert field in refused.message


def test_check_scout_allows_a_corrected_scope_after_an_invalid_one(tmp_path: Path) -> None:
    """D-C: a violation for an invalid scope does not count, so the Supervisor can correct its scope."""
    state = _state(tmp_path)
    refused = check_scout(state, _scope_args(date_from="20260622"))
    assert isinstance(refused, GuardrailViolation)
    state.violations.append(refused)  # as scout_tool will store it

    corrected = check_scout(state, _scope_args())

    assert isinstance(corrected, PipelineScope)
    assert corrected.date_from == SCOPE_DATE_FROM


# ---------------------------------------------------------------------------
# Per-document checks: one table-driven case per rule, plus the allowed cases
# ---------------------------------------------------------------------------

#: One ``writer_tool`` call in a document's history: it failed, it drafted and awaits QA, or its draft was audited.
Step: TypeAlias = Literal["failed", "drafted", "PASS", "WARNING", "ERROR"]
UNKNOWN_DOC_ID = "gu-2026-not-returned-by-the-scout"


def _draft(doc_id: str) -> ArticleDraft:
    """Build the scripted Writer draft whose provenance is ``doc_id``."""
    return ArticleDraft.model_validate({**DRAFT_ARGS, "source_doc_id": doc_id})


def _qa(status: QAStatus) -> QAReport:
    """Build a scripted QA-Legal report with ``status`` and one issue."""
    return QAReport.model_validate(qa_args(status=status, issues=["Art. 28 citato senza comma."], notes="Nota."))


def _add_attempt(document: DocumentRecord, step: Step) -> AttemptRecord:
    """Append one attempt to ``document`` and fill its slots through the setters, as the tools will."""
    record = AttemptRecord(
        context=AgentContext(today=TODAY), candidate=document.candidate, attempt=document.attempts_used + 1
    )
    document.attempts.append(record)
    if step != "failed":
        record.set_draft(_draft(record.doc_id))
    if step != "failed" and step != "drafted":
        record.set_qa_report(_qa(step))
    return record


def _save(document: DocumentRecord, status: QAStatus, number: int = 1) -> None:
    """Mark ``document`` saved with ``status``, as ``save_draft`` will."""
    draft_id = f"draft_20260929_{number:03d}"
    document.saved = DraftResult(
        doc_id=document.candidate.update.doc_id,
        draft_id=draft_id,
        path=Path("drafts") / f"{draft_id}.md",
        qa_status=status,
    )


@dataclass(frozen=True)
class Case:
    """One guardrail case: a document's history, one per-document call on it, and the expected outcome.

    ``expected`` is the guardrail that must trip, or ``None`` when the call is allowed. ``says`` holds the parts of
    the message that state the rule and its limit. ``saved`` closes the document itself; ``saved_elsewhere`` other
    documents are saved beside it, against a ceiling of ``max_drafts``.
    """

    tool: str
    expected: GuardrailName | None
    history: tuple[Step, ...] = ()
    revise: bool = False
    doc_id: str = DEFAULT_DOC_ID
    says: tuple[str, ...] = ()
    saved: QAStatus | None = None
    saved_elsewhere: int = 0
    max_drafts: int | None = None


def _arrange(tmp_path: Path, case: Case) -> RunState:
    """Build the run state ``case`` starts from: one candidate advanced through ``case.history``, and others saved."""
    others = [f"saved-doc-{number}" for number in range(1, case.saved_elsewhere + 1)]
    state = _state(tmp_path, DEFAULT_DOC_ID, *others, max_drafts=case.max_drafts)
    for number, other in enumerate(others, start=1):
        _add_attempt(state.documents[other], "PASS")
        _save(state.documents[other], "PASS", number)
    document = state.documents[DEFAULT_DOC_ID]
    for step in case.history:
        _add_attempt(document, step)
    if case.saved is not None:
        _save(document, case.saved, case.saved_elsewhere + 1)
    return state


def _call(state: RunState, case: Case) -> GuardrailViolation | None:
    """Make the per-document check call that ``case`` describes."""
    if case.tool == WRITER_TOOL:
        return check_writer(state, case.doc_id, case.revise)
    if case.tool == QA_TOOL:
        return check_qa(state, case.doc_id)
    return check_save(state, case.doc_id)


def _assert_outcome(outcome: GuardrailViolation | None, case: Case) -> None:
    """Assert that ``outcome`` is the allowed call or the complete violation ``case`` expects."""
    if case.expected is None:
        assert outcome is None
        return
    assert isinstance(outcome, GuardrailViolation)
    assert (outcome.guardrail, outcome.tool_name, outcome.doc_id) == (case.expected, case.tool, case.doc_id)
    assert repr(case.doc_id) in outcome.message
    for part in case.says:
        assert part in outcome.message


def _writer(
    expected: GuardrailName | None,
    *history: Step,
    revise: bool,
    doc_id: str = DEFAULT_DOC_ID,
    says: tuple[str, ...] = (),
    saved: QAStatus | None = None,
) -> Case:
    """Build a ``writer_tool`` case."""
    return Case(WRITER_TOOL, expected, history, revise, doc_id, says, saved)


_CAP_REACHED = (f"{MAX_ATTEMPTS_PER_DOC} of {MAX_ATTEMPTS_PER_DOC} attempts used",)
_NEEDS_REPORT = ("needs a QA report on the latest draft",)

WRITER_CASES = [
    pytest.param(
        _writer("not_a_candidate", revise=False, doc_id=UNKNOWN_DOC_ID, says=("not a candidate",)), id="unknown-doc"
    ),
    pytest.param(
        _writer("already_saved", "WARNING", revise=True, saved="WARNING", says=("already saved",)),
        id="revise-a-saved-warning",
    ),
    pytest.param(_writer("attempt_limit", "ERROR", "ERROR", "ERROR", revise=True, says=_CAP_REACHED), id="4th-revise"),
    pytest.param(
        _writer("attempt_limit", "failed", "failed", "failed", revise=False, says=_CAP_REACHED),
        id="4th-call-after-three-failures",
    ),
    pytest.param(
        _writer("initial_draft_exists", "drafted", revise=False, says=("first draft only",)), id="restart-a-draft"
    ),
    pytest.param(
        _writer("initial_draft_exists", "ERROR", "failed", revise=False, says=("first draft only",)),
        id="restart-after-a-failed-revision",
    ),
    pytest.param(_writer("not_audited", revise=True, says=_NEEDS_REPORT), id="revise-with-no-draft"),
    pytest.param(_writer("not_audited", "failed", revise=True, says=_NEEDS_REPORT), id="revise-after-a-failed-call"),
    pytest.param(_writer("not_audited", "drafted", revise=True, says=_NEEDS_REPORT), id="revise-an-unaudited-draft"),
    pytest.param(
        _writer("not_audited", "ERROR", "drafted", revise=True, says=_NEEDS_REPORT), id="revise-an-unaudited-revision"
    ),
    pytest.param(_writer("revise_after_pass", "PASS", revise=True, says=("PASS is never revised",)), id="revise-pass"),
    pytest.param(
        _writer("revise_after_pass", "ERROR", "PASS", revise=True, says=("PASS is never revised",)),
        id="revise-a-revised-pass",
    ),
    pytest.param(_writer(None, revise=False), id="allowed-first-draft"),
    pytest.param(_writer(None, "failed", revise=False), id="allowed-retry-after-a-failed-first-call"),
    pytest.param(_writer(None, "failed", "failed", revise=False), id="allowed-retry-after-two-failed-calls"),
    pytest.param(_writer(None, "ERROR", revise=True), id="allowed-revise-an-error"),
    pytest.param(_writer(None, "WARNING", revise=True), id="allowed-revise-a-warning"),
    pytest.param(_writer(None, "ERROR", "failed", revise=True), id="allowed-revise-after-a-failed-revision"),
    pytest.param(_writer(None, "failed", "WARNING", revise=True), id="allowed-revise-at-attempt-3"),
]


@pytest.mark.parametrize("case", WRITER_CASES)
def test_check_writer(tmp_path: Path, case: Case) -> None:
    """§7.3 ``writer_tool``: rules 1, 4, 6 and 7 in order; a failed call leaves the earlier draft the latest."""
    _assert_outcome(_call(_arrange(tmp_path, case), case), case)


def test_check_writer_counts_attempts_against_the_constant_not_the_supervisor_copy(tmp_path: Path) -> None:
    """D-C rule 4: the cap is ``MAX_ATTEMPTS_PER_DOC``; ``RunContext.max_attempts_per_doc`` is only what is shown."""
    state = _state(tmp_path, DEFAULT_DOC_ID)
    document = state.documents[DEFAULT_DOC_ID]
    state.context.max_attempts_per_doc = MAX_ATTEMPTS_PER_DOC + 2
    for _ in range(MAX_ATTEMPTS_PER_DOC):
        _add_attempt(document, "ERROR")

    refused = check_writer(state, DEFAULT_DOC_ID, True)

    assert isinstance(refused, GuardrailViolation)
    assert refused.guardrail == "attempt_limit"
    assert _CAP_REACHED[0] in refused.message

    state.context.max_attempts_per_doc = 1
    del document.attempts[1:]
    assert check_writer(state, DEFAULT_DOC_ID, True) is None


def _qa_case(
    expected: GuardrailName | None,
    *history: Step,
    doc_id: str = DEFAULT_DOC_ID,
    says: tuple[str, ...] = (),
    saved: QAStatus | None = None,
) -> Case:
    """Build a ``qa_tool`` case."""
    return Case(QA_TOOL, expected, history, False, doc_id, says, saved)


QA_CASES = [
    pytest.param(_qa_case("not_a_candidate", doc_id=UNKNOWN_DOC_ID, says=("not a candidate",)), id="unknown-doc"),
    pytest.param(_qa_case("already_saved", "PASS", saved="PASS", says=("already saved",)), id="audit-a-saved-doc"),
    pytest.param(_qa_case("no_draft", says=("no draft",)), id="nothing-drafted"),
    pytest.param(_qa_case("no_draft", "failed", "failed", says=("no draft",)), id="only-failed-calls"),
    pytest.param(_qa_case("already_audited", "ERROR", says=("audited once",)), id="audit-twice"),
    pytest.param(_qa_case("already_audited", "WARNING", says=("audited once",)), id="audit-a-warning-twice"),
    pytest.param(
        _qa_case("already_audited", "ERROR", "failed", says=("audited once",)), id="audit-after-a-failed-revision"
    ),
    pytest.param(_qa_case(None, "drafted"), id="allowed-audit-the-latest-draft"),
    pytest.param(_qa_case(None, "failed", "drafted"), id="allowed-audit-after-a-failed-first-call"),
    pytest.param(_qa_case(None, "ERROR", "drafted"), id="allowed-audit-after-a-successful-revision"),
]


@pytest.mark.parametrize("case", QA_CASES)
def test_check_qa(tmp_path: Path, case: Case) -> None:
    """§7.3 ``qa_tool``: rules 1, 10 and 8 in order; the latest draft is audited once."""
    _assert_outcome(_call(_arrange(tmp_path, case), case), case)


def _save_case(
    expected: GuardrailName | None,
    *history: Step,
    doc_id: str = DEFAULT_DOC_ID,
    says: tuple[str, ...] = (),
    saved: QAStatus | None = None,
    saved_elsewhere: int = 0,
    max_drafts: int | None = None,
) -> Case:
    """Build a ``save_draft`` case."""
    return Case(SAVE_DRAFT_TOOL, expected, history, False, doc_id, says, saved, saved_elsewhere, max_drafts)


_ERROR_RULE = "ERROR may be saved only when no attempts remain"
_ERROR_2_LEFT = ("ERROR with 2 of 3 attempts remaining", _ERROR_RULE)
_ERROR_1_LEFT = ("ERROR with 1 of 3 attempts remaining", _ERROR_RULE)
_CEILING_2 = ("2 of 2 drafts saved (max_drafts 2)",)

SAVE_CASES = [
    pytest.param(_save_case("not_a_candidate", doc_id=UNKNOWN_DOC_ID, says=("not a candidate",)), id="unknown-doc"),
    pytest.param(_save_case("already_saved", "PASS", saved="PASS", says=("already saved",)), id="save-twice"),
    pytest.param(_save_case("not_audited", says=_NEEDS_REPORT), id="nothing-drafted"),
    pytest.param(_save_case("not_audited", "failed", says=_NEEDS_REPORT), id="only-a-failed-call"),
    pytest.param(_save_case("not_audited", "drafted", says=_NEEDS_REPORT), id="save-without-qa"),
    pytest.param(_save_case("not_audited", "ERROR", "drafted", says=_NEEDS_REPORT), id="save-an-unaudited-revision"),
    pytest.param(_save_case("error_with_attempts_remaining", "ERROR", says=_ERROR_2_LEFT), id="error-at-attempt-1"),
    pytest.param(
        _save_case("error_with_attempts_remaining", "ERROR", "ERROR", says=_ERROR_1_LEFT), id="error-at-attempt-2"
    ),
    pytest.param(
        _save_case("error_with_attempts_remaining", "ERROR", "failed", says=_ERROR_1_LEFT),
        id="earlier-error-after-a-failed-revision",
    ),
    pytest.param(
        _save_case("draft_ceiling", "PASS", saved_elsewhere=2, max_drafts=2, says=_CEILING_2),
        id="ceiling-reached",
    ),
    pytest.param(
        _save_case("draft_ceiling", "WARNING", saved_elsewhere=3, max_drafts=1, says=("3 of 1 drafts saved",)),
        id="ceiling-passed",
    ),
    pytest.param(_save_case(None, "PASS"), id="allowed-pass-at-attempt-1"),
    pytest.param(_save_case(None, "ERROR", "PASS"), id="allowed-pass-at-attempt-2"),
    pytest.param(_save_case(None, "ERROR", "ERROR", "PASS"), id="allowed-pass-at-attempt-3"),
    pytest.param(_save_case(None, "WARNING"), id="allowed-warning-at-attempt-1"),
    pytest.param(_save_case(None, "failed", "WARNING"), id="allowed-warning-at-attempt-2"),
    pytest.param(_save_case(None, "ERROR", "WARNING", "WARNING"), id="allowed-warning-at-attempt-3"),
    pytest.param(_save_case(None, "ERROR", "ERROR", "ERROR"), id="allowed-error-at-3-of-3"),
    pytest.param(_save_case(None, "ERROR", "failed", "failed"), id="allowed-earlier-error-at-3-of-3"),
    pytest.param(_save_case(None, "WARNING", "failed"), id="allowed-earlier-warning-after-a-failed-call"),
    pytest.param(_save_case(None, "PASS", saved_elsewhere=1, max_drafts=2), id="allowed-under-the-ceiling"),
    pytest.param(_save_case(None, "PASS", saved_elsewhere=3), id="allowed-no-ceiling-when-max-drafts-is-none"),
]


@pytest.mark.parametrize("case", SAVE_CASES)
def test_check_save(tmp_path: Path, case: Case) -> None:
    """§7.3 ``save_draft``: rules 1, 10 and 9 in order, then the draft ceiling."""
    _assert_outcome(_call(_arrange(tmp_path, case), case), case)


def test_check_save_counts_drafts_saved_from_documents_not_the_stored_context(tmp_path: Path) -> None:
    """D-C: ``drafts_saved`` is counted from the documents; ``RunState.context.drafts_saved`` is never updated."""
    case = _save_case("draft_ceiling", "PASS", saved_elsewhere=2, max_drafts=2)
    state = _arrange(tmp_path, case)
    assert state.context.drafts_saved == 0

    refused = check_save(state, DEFAULT_DOC_ID)

    assert isinstance(refused, GuardrailViolation)
    assert refused.guardrail == "draft_ceiling"


def test_check_save_reads_the_ceiling_from_the_configuration(tmp_path: Path) -> None:
    """§7.3: the ceiling is ``config.max_drafts``, the ``--max-drafts`` value; never a copy of it or the scope's."""
    state = _arrange(tmp_path, _save_case(None, "PASS", saved_elsewhere=1))
    state.context.max_drafts = 1
    state.scope = PipelineScope(
        context=AgentContext(today=TODAY), date_from=SCOPE_DATE_FROM, date_to=SCOPE_DATE_TO, max_drafts=1
    )
    assert check_save(state, DEFAULT_DOC_ID) is None

    state.config.max_drafts = 1
    refused = check_save(state, DEFAULT_DOC_ID)
    assert isinstance(refused, GuardrailViolation)
    assert refused.guardrail == "draft_ceiling"


# ---------------------------------------------------------------------------
# Precedence: when two checks fail, the earlier one in §7.3 wins
# ---------------------------------------------------------------------------

PRECEDENCE_CASES = [
    pytest.param(
        _writer("already_saved", "ERROR", "ERROR", "ERROR", revise=True, saved="ERROR"),
        id="writer-already-saved-before-attempt-limit",
    ),
    pytest.param(
        _writer("attempt_limit", "ERROR", "ERROR", "WARNING", revise=False),
        id="writer-attempt-limit-before-initial-draft-exists",
    ),
    pytest.param(
        _writer("attempt_limit", "ERROR", "ERROR", "PASS", revise=True),
        id="writer-attempt-limit-before-revise-after-pass",
    ),
    pytest.param(
        _writer("attempt_limit", "ERROR", "ERROR", "drafted", revise=True), id="writer-attempt-limit-before-not-audited"
    ),
    pytest.param(_qa_case("already_saved", "WARNING", saved="WARNING"), id="qa-already-saved-before-already-audited"),
    pytest.param(
        _save_case("already_saved", "PASS", saved="PASS", saved_elsewhere=1, max_drafts=1),
        id="save-already-saved-before-draft-ceiling",
    ),
    pytest.param(
        _save_case("not_audited", "ERROR", "drafted", saved_elsewhere=2, max_drafts=2),
        id="save-not-audited-before-draft-ceiling",
    ),
    pytest.param(
        _save_case("error_with_attempts_remaining", "ERROR", "failed", saved_elsewhere=2, max_drafts=2),
        id="save-error-with-attempts-remaining-before-draft-ceiling",
    ),
]


@pytest.mark.parametrize("case", PRECEDENCE_CASES)
def test_the_earlier_check_wins_when_two_fail(tmp_path: Path, case: Case) -> None:
    """§7.3: the checks run in order and the first that fails is returned."""
    _assert_outcome(_call(_arrange(tmp_path, case), case), case)


def test_check_scout_refuses_a_second_call_before_looking_at_its_scope(tmp_path: Path) -> None:
    """§7.3: ``scout_already_run`` comes before ``invalid_scope``; an invalid second scope is refused as a rerun."""
    state = _state(tmp_path)
    scope = check_scout(state, _scope_args())
    assert isinstance(scope, PipelineScope)
    state.scope = scope

    refused = check_scout(state, _scope_args(date_from="20260622", sources=["OSHA"]))

    assert isinstance(refused, GuardrailViolation)
    assert refused.guardrail == "scout_already_run"


def test_check_scout_reports_the_validation_error_before_the_dates(tmp_path: Path) -> None:
    """The scope is built before its dates are parsed, so a model error is the problem reported."""
    refused = check_scout(_state(tmp_path), _scope_args(date_from="20260622", sources=["OSHA"]))

    assert isinstance(refused, GuardrailViolation)
    assert refused.guardrail == "invalid_scope"
    assert "sources" in refused.message
    assert "20260622" not in refused.message


# ---------------------------------------------------------------------------
# Purity: no check changes the run state (AC2)
# ---------------------------------------------------------------------------


def _prefixed(prefix: str, params: Sequence[Any]) -> list[Any]:
    """Re-id ``params`` as ``prefix-id``, so cases from different tables stay distinct when combined."""
    return [pytest.param(*param.values, id=f"{prefix}-{param.id}") for param in params]


ALL_CASES = [
    *_prefixed("writer", WRITER_CASES),
    *_prefixed("qa", QA_CASES),
    *_prefixed("save", SAVE_CASES),
    *_prefixed("precedence", PRECEDENCE_CASES),
]


@pytest.mark.parametrize("fatal", [False, True], ids=["plain", "with-fatal-error"])
@pytest.mark.parametrize("case", ALL_CASES)
def test_per_document_checks_never_change_the_run_state(tmp_path: Path, case: Case, fatal: bool) -> None:
    """§7.3: no check mutates the state, whether it refuses or allows; the dump is identical before and after."""
    state = _arrange(tmp_path, case)
    if fatal:
        state.fatal_error = ConnectionError("MCP transport closed")  # Python-mode dumps carry the object itself
    before = state.model_dump()

    _call(state, case)

    assert state.model_dump() == before


#: The ``check_scout`` cases, as ``(id, scope_set, args)``: one typed source for the purity test and for AC1.
_SCOUT_PURITY_INPUTS: list[tuple[str, bool, ScoutArgs]] = [
    ("allowed", False, _scope_args()),
    ("invalid-date", False, _scope_args(date_from="20260622")),
    ("inverted-window", False, _scope_args(date_from=SCOPE_DATE_TO, date_to=SCOPE_DATE_FROM)),
    ("unknown-source", False, _scope_args(sources=["OSHA"])),
    ("scout-already-run", True, _scope_args()),
]
SCOUT_PURITY_CASES = [pytest.param(scope_set, args, id=name) for name, scope_set, args in _SCOUT_PURITY_INPUTS]


@pytest.mark.parametrize(("scope_set", "args"), SCOUT_PURITY_CASES)
def test_check_scout_never_changes_the_run_state(tmp_path: Path, scope_set: bool, args: ScoutArgs) -> None:
    """§7.3: ``check_scout`` returns a scope but never stores it; storing it is ``scout_tool``'s job."""
    state = _state(tmp_path, DEFAULT_DOC_ID)
    if scope_set:
        state.scope = PipelineScope(context=AgentContext(today=TODAY), date_from=SCOPE_DATE_FROM, date_to=SCOPE_DATE_TO)
    before = state.model_dump()
    scope_before = state.scope

    outcome = check_scout(state, args)

    assert state.model_dump() == before
    assert state.scope is scope_before
    assert state.violations == []
    if isinstance(outcome, PipelineScope):
        assert state.scope is None
        assert outcome is not state.scope


# ---------------------------------------------------------------------------
# Coverage: every guardrail is produced (AC1)
# ---------------------------------------------------------------------------


def test_the_cases_produce_every_one_of_the_twelve_guardrails(tmp_path: Path) -> None:
    """AC1: the guardrails the case tables actually produce are exactly the 12 ``GuardrailName`` values of §6.7."""
    produced: set[str] = set()
    for param in ALL_CASES:
        case: Case = param.values[0]
        outcome = _call(_arrange(tmp_path, case), case)
        if outcome is not None:
            produced.add(outcome.guardrail)
    for _, scope_set, args in _SCOUT_PURITY_INPUTS:
        state = _state(tmp_path)
        if scope_set:
            state.scope = PipelineScope(
                context=AgentContext(today=TODAY), date_from=SCOPE_DATE_FROM, date_to=SCOPE_DATE_TO
            )
        outcome_or_scope = check_scout(state, args)
        if isinstance(outcome_or_scope, GuardrailViolation):
            produced.add(outcome_or_scope.guardrail)

    assert produced == set(get_args(GuardrailName))
    assert len(produced) == 12


# ---------------------------------------------------------------------------
# D-C "How rule 8 plays out for one document", row by row
# ---------------------------------------------------------------------------


def _guardrail(outcome: GuardrailViolation | None) -> str | None:
    """The guardrail a check tripped, or ``None`` when it allowed the call."""
    return None if outcome is None else outcome.guardrail


def test_rule_8_walk_through_for_one_document(tmp_path: Path) -> None:
    """D-C "How rule 8 plays out": after each call, the latest draft and whether ``qa_tool`` is allowed."""
    state = _state(tmp_path, DEFAULT_DOC_ID)
    document = state.documents[DEFAULT_DOC_ID]

    # writer_tool(revise=False) succeeds: #1 {draft: A1, qa_report: —}; latest A1; qa_tool allowed.
    assert check_writer(state, DEFAULT_DOC_ID, False) is None
    first = _add_attempt(document, "drafted")
    assert document.latest_drafted is first
    assert check_qa(state, DEFAULT_DOC_ID) is None

    # qa_tool → ERROR: #1 {A1, ERROR}; latest A1; qa_tool refused, A1 already audited.
    first.set_qa_report(_qa("ERROR"))
    assert document.latest_drafted is first
    assert _guardrail(check_qa(state, DEFAULT_DOC_ID)) == "already_audited"
    after_first_audit = state.model_copy(deep=True)  # the "or instead" row branches from here

    # writer_tool(revise=True) succeeds: #1 {A1, ERROR}, #2 {draft: A2, qa_report: —}; latest A2; qa_tool allowed.
    assert check_writer(state, DEFAULT_DOC_ID, True) is None
    second = _add_attempt(document, "drafted")
    assert document.latest_drafted is second
    assert check_qa(state, DEFAULT_DOC_ID) is None

    # qa_tool → PASS: #1 {A1, ERROR}, #2 {A2, PASS}; latest A2; qa_tool refused, A2 already audited.
    second.set_qa_report(_qa("PASS"))
    assert document.latest_drafted is second
    assert _guardrail(check_qa(state, DEFAULT_DOC_ID)) == "already_audited"
    assert check_save(state, DEFAULT_DOC_ID) is None

    # Or instead: writer_tool(revise=True) fails: #1 {A1, ERROR}, #2 {draft: —, qa_report: —}; latest A1.
    fork = after_first_audit
    forked = fork.documents[DEFAULT_DOC_ID]
    assert check_writer(fork, DEFAULT_DOC_ID, True) is None
    failed = _add_attempt(forked, "failed")
    assert forked.latest_drafted is forked.attempts[0]
    assert failed.draft is None
    assert _guardrail(check_qa(fork, DEFAULT_DOC_ID)) == "already_audited"
    assert check_writer(fork, DEFAULT_DOC_ID, True) is None  # revise again from A1, with 1 of 3 attempts remaining
    # The row's "or save A1" does not hold: A1's report is ERROR with an attempt remaining, and D-C rule 9, §7.3 and
    # the save_draft description refuse that save. SPECIFICATIONS.md's rule 8 table (the "Or instead" row) is
    # illustrative; the normative rule 9 decides the guardrail.
    assert _guardrail(check_save(fork, DEFAULT_DOC_ID)) == "error_with_attempts_remaining"
