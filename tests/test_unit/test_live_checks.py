"""The checks the live tests apply to a real run, proven offline first (Iteration 16, P14).

A defect in a live check would surface only as a false failure of a run that cost real tokens, so each check is
exercised here on files and states built in ``tmp_path``: the hand-made Approach 2 draft fixture, rendered by the
real ``render_draft``, and copies of it with one fault each. No model and no substrate.
"""

import shutil
from datetime import date
from pathlib import Path

import pytest

from src.schemas import (
    AgentContext,
    ArticleDraft,
    AttemptRecord,
    DocumentRecord,
    DraftMetadata,
    DraftResult,
    QAReport,
    RunContext,
    RunState,
    ScoutCandidate,
)
from src.template_engine import render_draft
from tests.support.live_checks import COMPLIANCE_BANNER, months_before, saved_draft_problems
from tests.support.scripted import DRAFT_ARGS, REAL_TEMPLATE_PATH, UPDATE_FIXTURE, pipeline_config, qa_args

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "draft_20261005_001.md"
DOC_ID = str(UPDATE_FIXTURE["doc_id"])
DRAFT_ID = "draft_20261005_001"


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (date(2026, 10, 5), date(2026, 7, 5)),
        (date(2026, 2, 15), date(2025, 11, 15)),
        (date(2026, 5, 31), date(2026, 2, 28)),
        (date(2028, 5, 31), date(2028, 2, 29)),
        (date(2026, 3, 1), date(2025, 12, 1)),
    ],
    ids=["run-date", "across-the-year", "clamped", "leap-year", "first-of-month"],
)
def test_months_before_steps_back_whole_months_and_clamps_the_day(day: date, expected: date) -> None:
    """The Supervisor's default window is "the past 3 months"; its start is the same day 3 months back, clamped."""
    assert months_before(day, 3) == expected


def _saved_state(tmp_path: Path, *, status: str = "WARNING", attempts: int = 2) -> tuple[RunState, Path]:
    """A run state with one document saved as the fixture draft, and the drafts folder holding that draft."""
    drafts_dir = tmp_path / "drafts"
    drafts_dir.mkdir()
    path = Path(shutil.copyfile(FIXTURE, drafts_dir / f"{DRAFT_ID}.md"))
    context = AgentContext(today=date(2026, 10, 5))
    candidate = ScoutCandidate.model_validate({"update": UPDATE_FIXTURE, "newsworthiness_score": 0.9, "rationale": "r"})
    records = [
        AttemptRecord(
            context=context,
            candidate=candidate,
            attempt=number,
            draft=ArticleDraft.model_validate(DRAFT_ARGS),
            qa_report=QAReport.model_validate(qa_args(status=status)),
        )
        for number in range(1, attempts + 1)
    ]
    document = DocumentRecord(
        candidate=candidate,
        attempts=records,
        saved=DraftResult(doc_id=DOC_ID, draft_id=DRAFT_ID, path=path, qa_status=status),  # type: ignore[arg-type]
    )
    state = RunState(
        run_id="r",
        config=pipeline_config(tmp_path),
        context=RunContext(today=date(2026, 10, 5), max_drafts=None, drafts_saved=1),
        documents={DOC_ID: document},
    )
    return state, drafts_dir


def _rewrite(path: Path, old: str, new: str) -> None:
    """Replace ``old`` with ``new`` in a draft, which must contain it."""
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new), encoding="utf-8")


def test_a_sound_draft_has_no_problem(tmp_path: Path) -> None:
    """The fixture draft, saved at attempt 2 with ``WARNING``, passes every check."""
    state, drafts_dir = _saved_state(tmp_path)
    assert saved_draft_problems(state, drafts_dir) == []


def test_a_run_that_saved_nothing_is_a_problem(tmp_path: Path) -> None:
    """Prompt A's checks include "at least one draft"."""
    state, drafts_dir = _saved_state(tmp_path)
    state.documents[DOC_ID].saved = None
    (drafts_dir / f"{DRAFT_ID}.md").unlink()
    assert saved_draft_problems(state, drafts_dir) == ["no draft was saved"]


def test_a_draft_file_nobody_saved_or_a_saved_draft_with_no_file_is_a_problem(tmp_path: Path) -> None:
    """The files on disk are exactly the drafts the run saved."""
    state, drafts_dir = _saved_state(tmp_path)
    shutil.copyfile(FIXTURE, drafts_dir / "draft_20261005_002.md")
    assert saved_draft_problems(state, drafts_dir) == [
        "draft files on disk ['draft_20261005_001.md', 'draft_20261005_002.md'] differ from the saved drafts "
        "['draft_20261005_001.md']"
    ]
    (drafts_dir / "draft_20261005_002.md").unlink()
    (drafts_dir / f"{DRAFT_ID}.md").unlink()
    problems = saved_draft_problems(state, drafts_dir)
    assert f"{DRAFT_ID}.md was saved but not written" in problems


def test_an_unresolved_template_token_is_a_problem(tmp_path: Path) -> None:
    """A token the template declares, left in the rendered draft, is reported; braces the Writer wrote are not."""
    state, drafts_dir = _saved_state(tmp_path)
    _rewrite(drafts_dir / f"{DRAFT_ID}.md", "**Draft ID:** draft_20261005_001", "**Draft ID:** {draft_id}")
    assert saved_draft_problems(state, drafts_dir) == [f"{DRAFT_ID}.md leaves template tokens ['{{draft_id}}']"]


def test_more_attempts_than_the_cap_is_a_problem(tmp_path: Path) -> None:
    """3 Writer attempts per document: a fourth, recorded or rendered, is reported."""
    state, drafts_dir = _saved_state(tmp_path, attempts=4)
    _rewrite(drafts_dir / f"{DRAFT_ID}.md", "* **Revision Attempts:** 2", "* **Revision Attempts:** 4")
    assert saved_draft_problems(state, drafts_dir) == [f"{DRAFT_ID}.md used 4 attempts, over the cap of 3"]


def test_a_rendered_attempt_count_that_differs_from_the_record_is_a_problem(tmp_path: Path) -> None:
    """The draft states the attempts its document used (§6.8)."""
    state, drafts_dir = _saved_state(tmp_path)
    _rewrite(drafts_dir / f"{DRAFT_ID}.md", "* **Revision Attempts:** 2", "* **Revision Attempts:** 1")
    assert saved_draft_problems(state, drafts_dir) == [f"{DRAFT_ID}.md renders 1 attempt(s), but 2 were used"]
    _rewrite(drafts_dir / f"{DRAFT_ID}.md", "* **Revision Attempts:** 1", "* **Attempts:** 1")
    assert saved_draft_problems(state, drafts_dir) == [f"{DRAFT_ID}.md renders no attempt(s), but 2 were used"]


def test_an_error_draft_without_the_banner_is_a_problem(tmp_path: Path) -> None:
    """A draft saved with ``ERROR`` carries the compliance banner (AGENTS.md Rule 5)."""
    state, drafts_dir = _saved_state(tmp_path, status="ERROR", attempts=2)
    _rewrite(drafts_dir / f"{DRAFT_ID}.md", "* **Status:** WARNING", "* **Status:** ERROR")
    assert saved_draft_problems(state, drafts_dir) == [f"{DRAFT_ID}.md is ERROR without [UNRESOLVED COMPLIANCE ALERT]"]


def test_an_error_draft_rendered_with_its_banner_has_no_problem(tmp_path: Path) -> None:
    """The negative control: an ``ERROR`` draft as the real ``render_draft`` writes it, banner included, passes."""
    state, drafts_dir = _saved_state(tmp_path, status="ERROR", attempts=2)
    report = QAReport.model_validate(qa_args(status="ERROR", issues=["Citation not in force."]))
    metadata = DraftMetadata(
        draft_id=DRAFT_ID,
        source_name="INAIL",
        publication_date="2026-08-20",
        source_document_title="Heat stress guidance",
        qa_report=report,
        attempts=2,
        latency_seconds=231.47,
        estimated_cost=0.4321,
        total_tokens=106300,
        unresolved_errors=list(report.issues),
    )
    content = render_draft(ArticleDraft.model_validate(DRAFT_ARGS), metadata, template_path=REAL_TEMPLATE_PATH)
    (drafts_dir / f"{DRAFT_ID}.md").write_text(content, encoding="utf-8")
    assert COMPLIANCE_BANNER in content
    assert saved_draft_problems(state, drafts_dir) == []


def test_a_draft_of_another_approach_is_a_problem(tmp_path: Path) -> None:
    """Every draft is Approach 2's (§3.3)."""
    state, drafts_dir = _saved_state(tmp_path)
    _rewrite(drafts_dir / f"{DRAFT_ID}.md", "Approach 2 (Research Analyst)", "Approach 1 (Code-Orchestrated Pipeline)")
    assert saved_draft_problems(state, drafts_dir) == [f"{DRAFT_ID}.md is not marked Approach 2 (Research Analyst)"]
