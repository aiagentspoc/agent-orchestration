"""``allocate_draft_id``: draft IDs allocated at save time, before any file exists (Iteration 10).

SPECIFICATIONS.md §6.8 "Draft IDs", D-B and AGENTS.md Rule 5. ``save_draft`` allocates the ID when it marks a
document saved, and the file is written only at run end, so the allocator counts both the drafts already on disk
(Approach 1's ``generate_draft_id`` scan) and the IDs allocated earlier in the same run. The date is the run's
``RunContext.today``, never the system clock, and allocation writes nothing to disk, not even the drafts folder.
"""

from datetime import date
from pathlib import Path
from typing import Final

from src.rendering import allocate_draft_id
from src.schemas import DocumentRecord, DraftResult, RunContext, RunState, ScoutCandidate
from tests.support.scripted import pipeline_config, scout_candidate_args

#: The run's date, deliberately not the system date, so a test cannot pass by reading the clock.
TODAY: Final[date] = date(2026, 3, 14)
STAMP: Final[str] = "20260314"


def _run_state(tmp_path: Path, *doc_ids: str) -> RunState:
    """A run dated ``TODAY`` whose Scout returned ``doc_ids``, in that order, none of them saved yet."""
    state = RunState(
        run_id="run-test-0010",
        config=pipeline_config(tmp_path),
        context=RunContext(today=TODAY, max_drafts=None, drafts_saved=0),
    )
    for doc_id in doc_ids:
        candidate = ScoutCandidate.model_validate(scout_candidate_args(doc_id, 0.9, f"Obblighi {doc_id}."))
        state.documents[doc_id] = DocumentRecord(candidate=candidate)
    return state


def _allocate_and_save(state: RunState, doc_id: str) -> str:
    """Allocate an ID and mark ``doc_id`` saved under it, as ``save_draft`` does, with no file written."""
    draft_id = allocate_draft_id(state)
    state.documents[doc_id].saved = DraftResult(
        doc_id=doc_id, draft_id=draft_id, path=state.config.drafts_dir / f"{draft_id}.md", qa_status="PASS"
    )
    return draft_id


def test_with_no_drafts_folder_the_first_id_is_001_on_the_runs_date_and_no_folder_is_created(tmp_path: Path) -> None:
    """The date is ``RunContext.today``; an absent folder contributes nothing and is still absent afterwards."""
    state = _run_state(tmp_path, "doc-a")
    assert date.today() != TODAY

    assert allocate_draft_id(state) == f"draft_{STAMP}_001"
    assert not state.config.drafts_dir.exists()


def test_two_saves_in_one_run_with_no_drafts_on_disk_give_001_then_002(tmp_path: Path) -> None:
    """No file exists until run end, so the second allocation must count the first one, held on ``documents``."""
    state = _run_state(tmp_path, "doc-a", "doc-b")

    allocated = [_allocate_and_save(state, "doc-a"), _allocate_and_save(state, "doc-b")]

    assert allocated == [f"draft_{STAMP}_001", f"draft_{STAMP}_002"]
    assert not state.config.drafts_dir.exists()


def _folder_contents(folder: Path) -> dict[str, str]:
    """Every file in ``folder``, by name, with its text: what a save must leave exactly as it was."""
    return {path.name: path.read_text(encoding="utf-8") for path in sorted(folder.iterdir())}


def test_with_004_on_disk_two_saves_give_005_then_006_and_the_folder_is_untouched(tmp_path: Path) -> None:
    """The disk scan is Approach 1's; a draft named for the system date, not the run's, is not counted."""
    state = _run_state(tmp_path, "doc-a", "doc-b")
    drafts_dir = state.config.drafts_dir
    drafts_dir.mkdir()
    (drafts_dir / f"draft_{STAMP}_004.md").write_text("# Bozza 4", encoding="utf-8")
    (drafts_dir / f"draft_{STAMP}_002.md").write_text("# Bozza 2", encoding="utf-8")
    (drafts_dir / f"draft_{date.today():%Y%m%d}_009.md").write_text("# Oggi", encoding="utf-8")
    before = _folder_contents(drafts_dir)

    allocated = [_allocate_and_save(state, "doc-a"), _allocate_and_save(state, "doc-b")]

    assert allocated == [f"draft_{STAMP}_005", f"draft_{STAMP}_006"]
    assert _folder_contents(drafts_dir) == before


def test_the_run_ids_count_when_ahead_of_the_disk_and_only_those_on_the_runs_date(tmp_path: Path) -> None:
    """The next number is past both the disk's and the run's highest on ``TODAY``.

    An ID of another date, or one not of ``generate_draft_id``'s form, counts for nothing.
    """
    state = _run_state(tmp_path, "doc-a", "doc-b", "doc-c")
    state.config.drafts_dir.mkdir()
    (state.config.drafts_dir / f"draft_{STAMP}_003.md").write_text("# Bozza 3", encoding="utf-8")
    for doc_id, draft_id in (
        ("doc-a", f"draft_{STAMP}_007"),
        ("doc-b", "draft_20260313_050"),
        ("doc-c", f"draft_{STAMP}_0099"),
    ):
        state.documents[doc_id].saved = DraftResult(
            doc_id=doc_id, draft_id=draft_id, path=state.config.drafts_dir / f"{draft_id}.md", qa_status="PASS"
        )

    assert allocate_draft_id(state) == f"draft_{STAMP}_008"


def test_with_999_on_disk_the_next_id_is_1000_not_a_fallback_to_001(tmp_path: Path) -> None:
    """Past sequence 999 ``generate_draft_id`` gives ``_1000``; the allocator must keep it, not read it as nothing."""
    state = _run_state(tmp_path, "doc-a")
    state.config.drafts_dir.mkdir()
    (state.config.drafts_dir / f"draft_{STAMP}_999.md").write_text("# Bozza 999", encoding="utf-8")

    assert allocate_draft_id(state) == f"draft_{STAMP}_1000"


def test_a_run_already_holding_1000_allocates_1001_not_a_second_1000(tmp_path: Path) -> None:
    """An ID the run allocated past 999 still counts, so the next save cannot reuse it."""
    state = _run_state(tmp_path, "doc-a", "doc-b")
    state.documents["doc-a"].saved = DraftResult(
        doc_id="doc-a",
        draft_id=f"draft_{STAMP}_1000",
        path=state.config.drafts_dir / f"draft_{STAMP}_1000.md",
        qa_status="PASS",
    )

    assert allocate_draft_id(state) == f"draft_{STAMP}_1001"
