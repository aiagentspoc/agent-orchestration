"""``allocate_draft_id`` and ``finalise_run``: draft IDs at save time, and rendering at run end (Iterations 10, 11).

SPECIFICATIONS.md §6.8 "Draft IDs", D-B and AGENTS.md Rule 5. ``save_draft`` allocates the ID when it marks a
document saved, and the file is written only at run end, so the allocator counts both the drafts already on disk
(Approach 1's ``generate_draft_id`` scan) and the IDs allocated earlier in the same run. The date is the run's
``RunContext.today``, never the system clock, and allocation writes nothing to disk, not even the drafts folder.

``finalise_run`` is everything code does once the Supervisor has finished (D-B, D-C "Unfinished candidates", §6.8,
P11, P12): it records the Supervisor's ledger entry, logs every candidate left unsaved, renders every saved draft in
save order with its share of the Scout and the Supervisor, and returns the run's tokens and cost. Every state here
is built by hand, so no model is called and no token is spent (P4); every file stays inside ``tmp_path``.
"""

import logging
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Final

import pytest

from src import rendering, template_engine
from src.agents import SCOUT_MODEL_ID, WRITER_MODEL_ID
from src.logging_setup import CorrelationFilter
from src.rendering import allocate_draft_id, finalise_run
from src.schemas import (
    AgentContext,
    AgentTelemetry,
    ArticleDraft,
    AttemptRecord,
    DocumentRecord,
    DraftMetadata,
    DraftResult,
    QAReport,
    QAStatus,
    RunContext,
    RunState,
    ScoutCandidate,
    StageTelemetry,
    ToolInvocation,
)
from src.telemetry import amortise_shared_telemetry, estimate_cost
from tests.support.scripted import (
    REAL_TEMPLATE_PATH,
    TEST_RATES,
    draft_args,
    pipeline_config,
    qa_args,
    scout_candidate_args,
)

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


# ---------------------------------------------------------------------------
# finalise_run (Iteration 11): fixtures and helpers
# ---------------------------------------------------------------------------

#: The logger every ``src.rendering`` event is written to.
RENDERING_LOGGER: Final[str] = "src.rendering"

#: The Supervisor runs on the strong binding, the Writer's ``gpt-5.4``, which ``TEST_RATES`` already prices.
SUPERVISOR_MODEL_ID: Final[str] = WRITER_MODEL_ID


def _telemetry(
    model_id: str,
    *,
    input_tokens: int = 0,
    cached: int = 0,
    output_tokens: int = 0,
    duration: float = 0.0,
    tools: tuple[ToolInvocation, ...] = (),
) -> AgentTelemetry:
    """One agent call's telemetry; ``total_tokens`` is input plus output, as the provider reports it."""
    return AgentTelemetry(
        model_id=model_id,
        input_tokens=input_tokens,
        cache_read_input_tokens=cached,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        total_duration_seconds=duration,
        cycles=1,
        tool_invocations=list(tools),
    )


def _supervisor(*, duration: float = 0.0, tool_seconds: tuple[float, ...] = (), tokens: int = 0) -> AgentTelemetry:
    """The Supervisor's run-end telemetry: one ``tool_invocations`` entry per tool time in ``tool_seconds``."""
    names = ("scout_tool", "writer_tool", "qa_tool", "save_draft")
    return _telemetry(
        SUPERVISOR_MODEL_ID,
        input_tokens=tokens,
        output_tokens=tokens // 2,
        duration=duration,
        tools=tuple(
            ToolInvocation(tool_name=names[index % 4], call_count=1, success_count=1, total_time_seconds=seconds)
            for index, seconds in enumerate(tool_seconds)
        ),
    )


def _scouted(tmp_path: Path, *doc_ids: str, scout: AgentTelemetry | None = None) -> RunState:
    """A run dated ``TODAY`` whose Scout returned ``doc_ids`` in rank order, with the Scout's entry on the ledger."""
    state = _run_state(tmp_path, *doc_ids)
    state.run_id = "run-test-0011"
    state.ledger.append(StageTelemetry(stage="scout", telemetry=scout or _telemetry(SCOUT_MODEL_ID)))
    return state


def _attempt(
    state: RunState,
    doc_id: str,
    *,
    status: QAStatus | None = None,
    drafted: bool = True,
    writer: AgentTelemetry | None = None,
    qa: AgentTelemetry | None = None,
) -> AttemptRecord:
    """One ``writer_tool`` call on ``doc_id`` and, given a ``status``, its ``qa_tool`` audit, with their ledger entries.

    A call with ``drafted=False`` failed: its attempt holds no draft, and its Writer entry is still on the ledger,
    as the tool wrapper records it (D-B).
    """
    document = state.documents[doc_id]
    record = AttemptRecord(
        context=AgentContext(today=TODAY), candidate=document.candidate, attempt=document.attempts_used + 1
    )
    document.attempts.append(record)
    state.ledger.append(
        StageTelemetry(
            stage="writer", doc_id=doc_id, attempt=record.attempt, telemetry=writer or _telemetry(WRITER_MODEL_ID)
        )
    )
    if not drafted:
        return record
    record.set_draft(ArticleDraft.model_validate(draft_args(doc_id, headline=f"Bozza {doc_id} {record.attempt}")))
    if status is not None:
        issues = [] if status == "PASS" else [f"Problema {doc_id} {record.attempt}"]
        record.set_qa_report(
            QAReport.model_validate(qa_args(status=status, issues=issues, notes=f"Note {doc_id} {record.attempt}"))
        )
        state.ledger.append(
            StageTelemetry(
                stage="qa_legal", doc_id=doc_id, attempt=record.attempt, telemetry=qa or _telemetry(WRITER_MODEL_ID)
            )
        )
    return record


def _mark_saved(state: RunState, doc_id: str) -> DraftResult:
    """Mark ``doc_id`` saved under a freshly allocated ID, as ``save_draft`` does, with no file written."""
    latest = state.documents[doc_id].latest_drafted
    assert latest is not None and latest.qa_report is not None
    draft_id = allocate_draft_id(state)
    saved = DraftResult(
        doc_id=doc_id,
        draft_id=draft_id,
        path=state.config.drafts_dir / f"{draft_id}.md",
        qa_status=latest.qa_report.status,
    )
    state.documents[doc_id].saved = saved
    return saved


@pytest.fixture
def rendering_log(caplog: pytest.LogCaptureFixture) -> pytest.LogCaptureFixture:
    """``caplog`` at INFO on ``src.rendering``, with the correlation fields stamped as the real handlers stamp them."""
    caplog.set_level(logging.INFO, logger=RENDERING_LOGGER)
    caplog.handler.addFilter(CorrelationFilter())
    return caplog


def _records(caplog: pytest.LogCaptureFixture, level: int | None = None) -> list[logging.LogRecord]:
    """The ``src.rendering`` records captured, optionally at one level only."""
    return [r for r in caplog.records if r.name == RENDERING_LOGGER and (level is None or r.levelno == level)]


@dataclass(frozen=True)
class _RenderCall:
    """One call ``finalise_run`` made to ``render_draft``: its arguments and the Markdown it got back."""

    draft: ArticleDraft
    metadata: DraftMetadata
    template_path: Path | str | None
    content: str


@pytest.fixture
def render_calls(monkeypatch: pytest.MonkeyPatch) -> list[_RenderCall]:
    """Record every ``render_draft`` call ``finalise_run`` makes, calling through to the real one.

    The rendered file shows money to four decimals and time to two, so the metadata itself is read from here.
    """
    calls: list[_RenderCall] = []

    def call_through(
        draft: ArticleDraft,
        metadata: DraftMetadata,
        template_path: Path | str | None = None,
        template_content: str | None = None,
    ) -> str:
        content = template_engine.render_draft(draft, metadata, template_path, template_content)
        calls.append(_RenderCall(draft=draft, metadata=metadata, template_path=template_path, content=content))
        return content

    monkeypatch.setattr(rendering, "render_draft", call_through)
    return calls


#: A template placeholder: ``{...}`` or the shipped template's one bracket token.
_TEMPLATE_TOKEN: Final[re.Pattern[str]] = re.compile(r"\{[^{}\n]+\}|\[Article Headline Here\]")


def _correlation(record: logging.LogRecord) -> tuple[object, ...]:
    """``(run_id, doc_id, attempt)`` as the :class:`CorrelationFilter` stamped them onto ``record``."""
    return tuple(getattr(record, name) for name in ("run_id", "doc_id", "attempt"))


# ---------------------------------------------------------------------------
# The Supervisor's ledger entry (D-B)
# ---------------------------------------------------------------------------


def test_the_supervisor_gets_one_ledger_entry_with_no_doc_id_or_attempt_when_its_telemetry_is_given(
    tmp_path: Path, rendering_log: pytest.LogCaptureFixture
) -> None:
    """D-B: the Supervisor's one entry is recorded at run end, after every sub-agent entry already there."""
    state = _scouted(tmp_path, "doc-a")
    before = list(state.ledger)
    supervisor = _supervisor(duration=12.0, tool_seconds=(5.0,), tokens=400)

    finalise_run(state, supervisor_telemetry=supervisor, rates=TEST_RATES)

    entry = StageTelemetry(stage="supervisor", doc_id=None, attempt=None, telemetry=supervisor)
    assert state.ledger == [*before, entry]
    assert not any("Supervisor" in r.getMessage() for r in _records(rendering_log, logging.WARNING))


def test_with_no_supervisor_telemetry_a_warning_is_logged_and_no_entry_is_added(
    tmp_path: Path, rendering_log: pytest.LogCaptureFixture
) -> None:
    """The Supervisor raised and no metrics could be read: the gap is logged, never filled with zeros."""
    state = _scouted(tmp_path, "doc-a")
    before = list(state.ledger)

    finalise_run(state, supervisor_telemetry=None, rates=TEST_RATES)

    assert state.ledger == before
    (warning,) = [r for r in _records(rendering_log, logging.WARNING) if "Supervisor" in r.getMessage()]
    assert _correlation(warning) == (state.run_id, "-", "-")


# ---------------------------------------------------------------------------
# Unfinished candidates (D-C "Run-level guardrails")
# ---------------------------------------------------------------------------


def test_each_candidate_left_unsaved_is_logged_at_warning_with_its_last_state_in_rank_order(
    tmp_path: Path, rendering_log: pytest.LogCaptureFixture
) -> None:
    """The Supervisor may skip a candidate but never silently; a saved document is not reported."""
    state = _scouted(tmp_path, "doc-none", "doc-failed", "doc-drafted", "doc-audited", "doc-saved")
    _attempt(state, "doc-failed", drafted=False)
    _attempt(state, "doc-drafted")
    _attempt(state, "doc-audited", status="WARNING")
    _attempt(state, "doc-saved", status="PASS")
    _mark_saved(state, "doc-saved")

    finalise_run(state, supervisor_telemetry=_supervisor(), rates=TEST_RATES)

    unsaved = [r for r in _records(rendering_log, logging.WARNING) if "left unsaved" in r.getMessage()]
    assert [r.getMessage() for r in unsaved] == [
        "Candidate left unsaved at run end: doc_id=doc-none last_state=not_drafted",
        "Candidate left unsaved at run end: doc_id=doc-failed last_state=not_drafted",
        "Candidate left unsaved at run end: doc_id=doc-drafted last_state=drafted",
        "Candidate left unsaved at run end: doc_id=doc-audited last_state=audited",
    ]
    assert [_correlation(r) for r in unsaved] == [
        (state.run_id, doc_id, "-") for doc_id in ("doc-none", "doc-failed", "doc-drafted", "doc-audited")
    ]


# ---------------------------------------------------------------------------
# Rendering a saved draft (§6.8, AGENTS.md Rule 5)
# ---------------------------------------------------------------------------


def test_a_saved_draft_is_rendered_from_its_metadata_and_written_to_its_allocated_path(
    tmp_path: Path, render_calls: list[_RenderCall]
) -> None:
    """The source fields come from ``candidate.update`` (Approach 1's mapping); the QA fields from the saved draft.

    AC1: no template token is left. AC2: the approach renders as Approach 2's, from the model's default.
    """
    state = _scouted(tmp_path, "doc-a", "doc-b")
    latest = _attempt(state, "doc-a", status="PASS")
    saved = _mark_saved(state, "doc-a")
    document = state.documents["doc-a"]

    finalise_run(state, supervisor_telemetry=_supervisor(), rates=TEST_RATES)

    (call,) = render_calls
    update = document.candidate.update
    assert call.draft == latest.draft
    assert call.template_path == state.config.template_path
    metadata = call.metadata
    assert (metadata.draft_id, metadata.source_name, metadata.publication_date, metadata.source_document_title) == (
        saved.draft_id,
        update.source,
        update.publication_date,
        update.title,
    )
    assert metadata.approach_name == "Approach 2 (Research Analyst)"
    assert (metadata.qa_report, metadata.attempts, metadata.unresolved_errors) == (latest.qa_report, 1, [])
    assert metadata.model_rates_used == TEST_RATES

    assert saved.path.read_text(encoding="utf-8") == call.content
    assert sorted(path.name for path in state.config.drafts_dir.iterdir()) == [f"{saved.draft_id}.md"]
    assert _TEMPLATE_TOKEN.findall(call.content) == []
    assert "**Approach:** Approach 2 (Research Analyst)" in call.content
    assert f"**Draft ID:** {saved.draft_id}" in call.content
    assert state.config.template_path == REAL_TEMPLATE_PATH  # AC1 is checked against the shipped template


def test_the_draft_is_rendered_with_the_runs_configured_template_not_the_default(
    tmp_path: Path, render_calls: list[_RenderCall]
) -> None:
    """``config.template_path`` is passed through; nothing falls back to ``DEFAULT_TEMPLATE_PATH``."""
    template = tmp_path / "template.md"
    template.write_text("# {headline}\nID {draft_id} by {approach_name}\n", encoding="utf-8")
    state = _scouted(tmp_path, "doc-a")
    state.config = pipeline_config(tmp_path, template_path=template)
    latest = _attempt(state, "doc-a", status="PASS")
    saved = _mark_saved(state, "doc-a")

    finalise_run(state, supervisor_telemetry=_supervisor(), rates=TEST_RATES)

    assert latest.draft is not None
    expected = f"# {latest.draft.headline}\nID {saved.draft_id} by Approach 2 (Research Analyst)\n"
    assert saved.path.read_text(encoding="utf-8") == expected


# ---------------------------------------------------------------------------
# Each draft's telemetry: its own calls plus an equal share of the Scout and the Supervisor (D-B)
# ---------------------------------------------------------------------------


def _two_saved_and_one_unsaved(tmp_path: Path) -> tuple[RunState, AgentTelemetry]:
    """doc-a saved after a failed call and a revision, doc-b saved at once, doc-c drafted and never saved.

    The shared tokens do not divide evenly by two, so the remainder rule is exercised.
    """
    state = _scouted(
        tmp_path,
        "doc-a",
        "doc-b",
        "doc-c",
        scout=_telemetry(SCOUT_MODEL_ID, input_tokens=101, cached=11, output_tokens=51, duration=6.0),
    )
    _attempt(state, "doc-a", drafted=False, writer=_telemetry(WRITER_MODEL_ID, input_tokens=7, output_tokens=0))
    _attempt(
        state,
        "doc-a",
        status="WARNING",
        writer=_telemetry(WRITER_MODEL_ID, input_tokens=300, cached=40, output_tokens=120, duration=10.0),
        qa=_telemetry(WRITER_MODEL_ID, input_tokens=250, output_tokens=60, duration=4.0),
    )
    _attempt(
        state,
        "doc-b",
        status="PASS",
        writer=_telemetry(WRITER_MODEL_ID, input_tokens=310, output_tokens=130, duration=9.0),
        qa=_telemetry(WRITER_MODEL_ID, input_tokens=260, output_tokens=70, duration=3.0),
    )
    _attempt(state, "doc-c", writer=_telemetry(WRITER_MODEL_ID, input_tokens=500, output_tokens=200, duration=8.0))
    _mark_saved(state, "doc-a")
    _mark_saved(state, "doc-b")
    return state, _supervisor(duration=100.0, tool_seconds=(30.0, 25.0, 15.0), tokens=333)


def _own(state: RunState, doc_id: str) -> list[StageTelemetry]:
    """``doc_id``'s Writer and QA-Legal ledger entries, failed calls included, in ledger order."""
    return [e for e in state.ledger if e.stage in ("writer", "qa_legal") and e.doc_id == doc_id]


def test_each_drafts_stage_telemetry_is_its_own_calls_then_its_equal_share_of_the_scout_and_supervisor(
    tmp_path: Path, render_calls: list[_RenderCall]
) -> None:
    """Own entries first, unchanged; then ``amortise_shared_telemetry``'s share, the first draft taking the remainder.

    The shared entries are the Scout's and the Supervisor's, in ledger order; another document's calls never appear.
    """
    state, supervisor = _two_saved_and_one_unsaved(tmp_path)

    finalise_run(state, supervisor_telemetry=supervisor, rates=TEST_RATES)

    shared = [e for e in state.ledger if e.stage in ("scout", "supervisor")]
    assert [e.stage for e in shared] == ["scout", "supervisor"]
    shares = amortise_shared_telemetry(shared, 2)
    assert [call.metadata.stage_telemetry for call in render_calls] == [
        _own(state, "doc-a") + shares[0],
        _own(state, "doc-b") + shares[1],
    ]
    stages = [e.stage for e in render_calls[0].metadata.stage_telemetry]
    assert stages == ["writer", "writer", "qa_legal", "scout", "supervisor"]
    supervisor_share = render_calls[0].metadata.stage_telemetry[-1].telemetry
    assert supervisor_share.total_duration_seconds == 50.0
    assert supervisor_share.tool_invocations == supervisor.tool_invocations


def test_each_drafts_tokens_and_cost_are_those_of_its_stage_telemetry(
    tmp_path: Path, render_calls: list[_RenderCall]
) -> None:
    """AC3: the per-draft cost equals ``estimate_cost`` over that draft's ``stage_telemetry``, to within 1e-9."""
    state, supervisor = _two_saved_and_one_unsaved(tmp_path)

    finalise_run(state, supervisor_telemetry=supervisor, rates=TEST_RATES)

    assert len(render_calls) == 2
    for call in render_calls:
        stages = call.metadata.stage_telemetry
        assert call.metadata.total_tokens == sum(e.telemetry.total_tokens for e in stages)
        assert call.metadata.estimated_cost == pytest.approx(
            sum(estimate_cost(e.telemetry, TEST_RATES) for e in stages), abs=1e-9
        )
        assert call.metadata.estimated_cost > 0
        assert f"({call.metadata.total_tokens} tokens)" in call.content


def test_per_draft_tokens_sum_to_the_saved_documents_own_tokens_plus_every_shared_token(
    tmp_path: Path, render_calls: list[_RenderCall]
) -> None:
    """Nothing shared is lost to rounding or counted twice; an unsaved document's tokens are in no draft."""
    state, supervisor = _two_saved_and_one_unsaved(tmp_path)

    finalise_run(state, supervisor_telemetry=supervisor, rates=TEST_RATES)

    own_saved = sum(e.telemetry.total_tokens for doc_id in ("doc-a", "doc-b") for e in _own(state, doc_id))
    shared = sum(e.telemetry.total_tokens for e in state.ledger if e.stage in ("scout", "supervisor"))
    assert shared % 2 == 1
    assert sum(call.metadata.total_tokens for call in render_calls) == own_saved + shared
    assert not any(e.doc_id == "doc-c" for call in render_calls for e in call.metadata.stage_telemetry)


# ---------------------------------------------------------------------------
# Per-draft latency: own time, the Scout's share and the Supervisor's own time only (P11)
# ---------------------------------------------------------------------------


def test_latency_is_own_time_plus_the_scout_share_plus_a_share_of_the_supervisors_own_time(
    tmp_path: Path, render_calls: list[_RenderCall]
) -> None:
    """doc-a: writer 10 s + QA 4 s, Scout 6 s / 2, Supervisor (100 s − 70 s in its tools) / 2: 14 + 3 + 15 = 32.

    Summing the durations in ``stage_telemetry`` would give 14 + 3 + 50 = 67, counting every sub-agent call twice.
    """
    state, supervisor = _two_saved_and_one_unsaved(tmp_path)

    finalise_run(state, supervisor_telemetry=supervisor, rates=TEST_RATES)

    assert [call.metadata.latency_seconds for call in render_calls] == [pytest.approx(32.0), pytest.approx(30.0)]
    assert "**Time Taken:** 32.00s" in render_calls[0].content
    assert sum(e.telemetry.total_duration_seconds for e in render_calls[0].metadata.stage_telemetry) == 67.0


def test_when_the_supervisors_tools_took_longer_than_its_run_its_own_time_counts_as_zero(
    tmp_path: Path, render_calls: list[_RenderCall]
) -> None:
    """The Supervisor's own time is never negative: ``max(duration − tool time, 0)``."""
    state, _ = _two_saved_and_one_unsaved(tmp_path)

    finalise_run(state, supervisor_telemetry=_supervisor(duration=20.0, tool_seconds=(70.0,)), rates=TEST_RATES)

    assert render_calls[0].metadata.latency_seconds == pytest.approx(17.0)


def test_with_no_supervisor_telemetry_latency_is_own_time_plus_the_scout_share(
    tmp_path: Path, render_calls: list[_RenderCall], rendering_log: pytest.LogCaptureFixture
) -> None:
    """The Supervisor's time is unknown, so it adds nothing; the warning says why."""
    state, _ = _two_saved_and_one_unsaved(tmp_path)

    finalise_run(state, supervisor_telemetry=None, rates=TEST_RATES)

    assert [call.metadata.latency_seconds for call in render_calls] == [pytest.approx(17.0), pytest.approx(15.0)]
    assert [e.stage for e in render_calls[0].metadata.stage_telemetry][-1] == "scout"
    assert any("Supervisor" in r.getMessage() for r in _records(rendering_log, logging.WARNING))


# ---------------------------------------------------------------------------
# Save order (§6.8 "Draft IDs")
# ---------------------------------------------------------------------------


def test_drafts_are_rendered_in_save_order_and_the_first_saved_takes_the_shared_remainder(
    tmp_path: Path, render_calls: list[_RenderCall]
) -> None:
    """doc-b, ranked second, was saved first: it is rendered first and is the share at index 0."""
    state = _scouted(tmp_path, "doc-a", "doc-b", scout=_telemetry(SCOUT_MODEL_ID, input_tokens=11, output_tokens=0))
    _attempt(state, "doc-a", status="PASS")
    _attempt(state, "doc-b", status="PASS")
    saved_b = _mark_saved(state, "doc-b")
    saved_a = _mark_saved(state, "doc-a")

    finalise_run(state, supervisor_telemetry=None, rates=TEST_RATES)

    assert [call.metadata.draft_id for call in render_calls] == [saved_b.draft_id, saved_a.draft_id]
    assert [call.metadata.stage_telemetry[-1].telemetry.total_tokens for call in render_calls] == [6, 5]


def test_save_order_reads_the_sequence_number_so_999_comes_before_1000(
    tmp_path: Path, render_calls: list[_RenderCall]
) -> None:
    """Sorting the ID strings would put ``_1000`` before ``_999``; rank order would too, here."""
    state = _scouted(tmp_path, "doc-a", "doc-b")
    for doc_id, sequence in (("doc-a", "1000"), ("doc-b", "999")):
        _attempt(state, doc_id, status="PASS")
        draft_id = f"draft_{STAMP}_{sequence}"
        state.documents[doc_id].saved = DraftResult(
            doc_id=doc_id, draft_id=draft_id, path=state.config.drafts_dir / f"{draft_id}.md", qa_status="PASS"
        )

    finalise_run(state, supervisor_telemetry=None, rates=TEST_RATES)

    assert [call.metadata.draft_id for call in render_calls] == [f"draft_{STAMP}_999", f"draft_{STAMP}_1000"]


# ---------------------------------------------------------------------------
# The drafted text is the saved one (§6.8 "Which draft is rendered", P2)
# ---------------------------------------------------------------------------


def test_after_an_error_and_a_passing_revision_the_revision_is_rendered_with_two_attempts(
    tmp_path: Path, render_calls: list[_RenderCall]
) -> None:
    """``{A1, ERROR}, {A2, PASS}``: A2's draft and report, and ``attempts == 2``."""
    state = _scouted(tmp_path, "doc-a")
    _attempt(state, "doc-a", status="ERROR")
    revision = _attempt(state, "doc-a", status="PASS")
    saved = _mark_saved(state, "doc-a")

    finalise_run(state, supervisor_telemetry=None, rates=TEST_RATES)

    (call,) = render_calls
    assert (call.draft, call.metadata.qa_report, call.metadata.attempts) == (revision.draft, revision.qa_report, 2)
    assert revision.draft is not None
    assert saved.path.read_text(encoding="utf-8").startswith(f"# {revision.draft.headline}\n")


def test_after_a_warning_and_a_failed_revision_the_warning_draft_is_rendered_with_two_attempts(
    tmp_path: Path, render_calls: list[_RenderCall]
) -> None:
    """``{A1, WARNING}, {failed}``: the failed call holds no draft, so A1 is the latest drafted; both attempts count."""
    state = _scouted(tmp_path, "doc-a")
    first = _attempt(state, "doc-a", status="WARNING")
    _attempt(state, "doc-a", drafted=False)
    _mark_saved(state, "doc-a")

    finalise_run(state, supervisor_telemetry=None, rates=TEST_RATES)

    (call,) = render_calls
    assert (call.draft, call.metadata.qa_report, call.metadata.attempts) == (first.draft, first.qa_report, 2)
    assert call.metadata.unresolved_errors == []
    assert "[UNRESOLVED COMPLIANCE ALERT]" not in call.content


# ---------------------------------------------------------------------------
# Logging the rendered drafts (D-I)
# ---------------------------------------------------------------------------


def test_each_written_draft_is_logged_at_info_with_its_id_path_doc_id_tokens_and_cost(
    tmp_path: Path, render_calls: list[_RenderCall], rendering_log: pytest.LogCaptureFixture
) -> None:
    """One "Draft rendered:" line per draft, after its file is written, correlated to its document and attempt."""
    state, supervisor = _two_saved_and_one_unsaved(tmp_path)

    finalise_run(state, supervisor_telemetry=supervisor, rates=TEST_RATES)

    rendered = [r for r in _records(rendering_log, logging.INFO) if r.getMessage().startswith("Draft rendered:")]
    assert len(rendered) == 2
    for record, call, doc_id, attempt in zip(rendered, render_calls, ("doc-a", "doc-b"), (2, 1), strict=True):
        saved = state.documents[doc_id].saved
        assert saved is not None
        assert record.getMessage() == (
            f"Draft rendered: draft_id={saved.draft_id} path={saved.path} doc_id={doc_id} "
            f"tokens={call.metadata.total_tokens} cost={call.metadata.estimated_cost:.6f}"
        )
        assert _correlation(record) == (state.run_id, doc_id, attempt)
    assert not any(r.getMessage().startswith("Draft rendered with") for r in _records(rendering_log))


def test_an_error_draft_saved_at_the_cap_carries_the_banner_and_logs_a_compliance_alert_warning(
    tmp_path: Path, render_calls: list[_RenderCall], rendering_log: pytest.LogCaptureFixture
) -> None:
    """The banner comes from ``format_review_notes`` through ``unresolved_errors``; code never writes its text."""
    state = _scouted(tmp_path, "doc-a")
    last = [_attempt(state, "doc-a", status="ERROR") for _ in range(3)][-1]
    saved = _mark_saved(state, "doc-a")
    assert last.qa_report is not None

    finalise_run(state, supervisor_telemetry=None, rates=TEST_RATES)

    (call,) = render_calls
    assert call.metadata.unresolved_errors == last.qa_report.issues == ["Problema doc-a 3"]
    assert "* **Review Notes:** [UNRESOLVED COMPLIANCE ALERT]\n\nNote doc-a 3" in saved.path.read_text(encoding="utf-8")
    alert_prefix = "Draft rendered with [UNRESOLVED COMPLIANCE ALERT]:"
    alerts = [r for r in _records(rendering_log, logging.WARNING) if r.getMessage().startswith(alert_prefix)]
    assert [r.getMessage() for r in alerts] == [
        f"Draft rendered with [UNRESOLVED COMPLIANCE ALERT]: draft_id={saved.draft_id} doc_id=doc-a "
        "attempts_used=3 issues=['Problema doc-a 3']"
    ]
    assert _correlation(alerts[0]) == (state.run_id, "doc-a", 3)
    assert any(r.getMessage().startswith("Draft rendered:") for r in _records(rendering_log, logging.INFO))


# ---------------------------------------------------------------------------
# Render and write failures: recorded, logged, and the other drafts still written (D-I, P6)
# ---------------------------------------------------------------------------


class _TemplateBroke(ValueError):
    """The failure a broken render raises in these tests."""


def _render_fails_for(monkeypatch: pytest.MonkeyPatch, draft_id: str) -> None:
    """Make ``render_draft`` raise for ``draft_id`` only, calling through to the real one for every other draft."""

    def render(
        draft: ArticleDraft,
        metadata: DraftMetadata,
        template_path: Path | str | None = None,
        template_content: str | None = None,
    ) -> str:
        if metadata.draft_id == draft_id:
            raise _TemplateBroke(f"cannot render {draft_id}")
        return template_engine.render_draft(draft, metadata, template_path, template_content)

    monkeypatch.setattr(rendering, "render_draft", render)


def _failure_logs(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    """The "Draft render or write failure" records captured from ``src.rendering``."""
    return [
        r for r in _records(caplog, logging.ERROR) if r.getMessage().startswith("Draft render or write failure")
    ]


def test_a_render_failure_is_recorded_logged_and_the_next_draft_is_still_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rendering_log: pytest.LogCaptureFixture
) -> None:
    """``FailureRecord(stage="render")`` with the rendered draft's attempt, an ERROR line, and no file for it."""
    state, supervisor = _two_saved_and_one_unsaved(tmp_path)
    saved_a, saved_b = state.documents["doc-a"].saved, state.documents["doc-b"].saved
    assert saved_a is not None and saved_b is not None
    _render_fails_for(monkeypatch, saved_a.draft_id)

    finalisation = finalise_run(state, supervisor_telemetry=supervisor, rates=TEST_RATES)

    assert finalisation.persistence_failed is True
    assert not saved_a.path.exists() and saved_b.path.is_file()
    (failure,) = state.failures
    assert (failure.stage, failure.doc_id, failure.attempt) == ("render", "doc-a", 2)
    assert (failure.error_type, failure.message) == (f"{__name__}._TemplateBroke", f"cannot render {saved_a.draft_id}")
    assert failure.remote is not None and failure.traceback is not None and "_TemplateBroke" in failure.traceback
    (logged,) = _failure_logs(rendering_log)
    assert f"draft_id={saved_a.draft_id}" in logged.getMessage() and f"path={saved_a.path}" in logged.getMessage()
    assert "stage=render" in logged.getMessage()
    assert logged.exc_info is not None and isinstance(logged.exc_info[1], _TemplateBroke)
    assert _correlation(logged) == (state.run_id, "doc-a", 2)
    rendered = [r.getMessage() for r in _records(rendering_log, logging.INFO) if r.getMessage().startswith("Draft")]
    assert len(rendered) == 1 and f"draft_id={saved_b.draft_id}" in rendered[0]


def test_a_write_failure_is_recorded_at_the_persist_stage_and_the_next_draft_is_still_written(
    tmp_path: Path, rendering_log: pytest.LogCaptureFixture
) -> None:
    """A directory already standing at the draft's path makes the write fail, after a successful render."""
    state, supervisor = _two_saved_and_one_unsaved(tmp_path)
    saved_a, saved_b = state.documents["doc-a"].saved, state.documents["doc-b"].saved
    assert saved_a is not None and saved_b is not None
    saved_b.path.mkdir(parents=True)

    finalisation = finalise_run(state, supervisor_telemetry=supervisor, rates=TEST_RATES)

    assert finalisation.persistence_failed is True
    assert saved_a.path.is_file() and saved_b.path.is_dir()
    (failure,) = state.failures
    assert (failure.stage, failure.doc_id, failure.attempt) == ("persist", "doc-b", 1)
    assert failure.error_type.endswith(("PermissionError", "IsADirectoryError"))
    (logged,) = _failure_logs(rendering_log)
    assert f"draft_id={saved_b.draft_id}" in logged.getMessage() and "stage=persist" in logged.getMessage()
    assert _correlation(logged) == (state.run_id, "doc-b", 1)


def test_a_draft_written_anywhere_but_its_allocated_path_is_a_persist_failure(
    tmp_path: Path, rendering_log: pytest.LogCaptureFixture
) -> None:
    """The file must land at ``DraftResult.path``, the path the Supervisor was shown; elsewhere is not a success."""
    state, supervisor = _two_saved_and_one_unsaved(tmp_path)
    saved_a, saved_b = state.documents["doc-a"].saved, state.documents["doc-b"].saved
    assert saved_a is not None and saved_b is not None
    saved_b.path = saved_b.path.with_name("not_the_draft_id.md")

    finalisation = finalise_run(state, supervisor_telemetry=supervisor, rates=TEST_RATES)

    assert finalisation.persistence_failed is True
    assert saved_a.path.is_file() and not saved_b.path.exists()
    (failure,) = state.failures
    assert (failure.stage, failure.doc_id, failure.attempt) == ("persist", "doc-b", 1)
    assert failure.error_type == "builtins.RuntimeError"
    assert str(saved_b.path) in failure.message
    (logged,) = _failure_logs(rendering_log)
    assert f"draft_id={saved_b.draft_id}" in logged.getMessage() and "stage=persist" in logged.getMessage()


@pytest.mark.parametrize("audited", [False, True], ids=["no-attempt", "unaudited-latest"])
def test_a_saved_document_without_an_audited_latest_draft_is_a_render_failure_not_a_crash(
    tmp_path: Path, rendering_log: pytest.LogCaptureFixture, audited: bool
) -> None:
    """A broken ``save_draft`` invariant, built by hand: ``RuntimeError`` inside the render stage, then carry on."""
    state = _scouted(tmp_path, "doc-a", "doc-b")
    _attempt(state, "doc-a", status="PASS")
    _mark_saved(state, "doc-a")
    _attempt(state, "doc-b", status="PASS")
    _mark_saved(state, "doc-b")
    broken = state.documents["doc-a"]
    broken.attempts = [] if not audited else broken.attempts
    if audited:
        _attempt(state, "doc-a")  # a later, unaudited draft is now the latest
    expected_attempt = 2 if audited else None

    finalisation = finalise_run(state, supervisor_telemetry=None, rates=TEST_RATES)

    assert finalisation.persistence_failed is True
    (failure,) = state.failures
    assert (failure.stage, failure.doc_id, failure.attempt) == ("render", "doc-a", expected_attempt)
    assert failure.error_type == "builtins.RuntimeError"
    saved_b = state.documents["doc-b"].saved
    assert saved_b is not None and saved_b.path.is_file()
    assert len(_failure_logs(rendering_log)) == 1


def test_an_unknown_model_id_raises_from_the_cost_basis_and_is_not_recorded_as_a_render_failure(
    tmp_path: Path,
) -> None:
    """``estimate_cost`` fails loudly on a model with no rate; a run priced at zero would be a false benchmark."""
    state = _scouted(tmp_path, "doc-a")
    _attempt(state, "doc-a", status="PASS", writer=_telemetry("gpt-unpriced", input_tokens=10))
    _mark_saved(state, "doc-a")

    with pytest.raises(ValueError, match="No cost rate configured for model ID 'gpt-unpriced'"):
        finalise_run(state, supervisor_telemetry=None, rates=TEST_RATES)

    assert state.failures == []


# ---------------------------------------------------------------------------
# The run's totals: returned, never logged here, never stored (P12, DM18)
# ---------------------------------------------------------------------------


def test_the_run_totals_cover_the_whole_ledger_unsaved_documents_failed_calls_and_the_supervisor_included(
    tmp_path: Path,
) -> None:
    """Every entry the run spent counts once: a failed Scout call, doc-c's unsaved draft and the Supervisor too."""
    state, supervisor = _two_saved_and_one_unsaved(tmp_path)
    state.ledger.insert(0, StageTelemetry(stage="scout", telemetry=_telemetry(SCOUT_MODEL_ID, input_tokens=9)))

    finalisation = finalise_run(state, supervisor_telemetry=supervisor, rates=TEST_RATES)

    assert state.ledger[-1].stage == "supervisor"
    assert finalisation.persistence_failed is False
    assert finalisation.total_tokens == sum(e.telemetry.total_tokens for e in state.ledger)
    assert finalisation.total_tokens == 9 + 152 + 7 + 420 + 310 + 440 + 330 + 700 + 499
    assert finalisation.estimated_cost == pytest.approx(
        sum(estimate_cost(e.telemetry, TEST_RATES) for e in state.ledger), abs=1e-9
    )


def test_with_nothing_saved_and_no_supervisor_telemetry_the_totals_are_still_what_the_run_spent(
    tmp_path: Path, render_calls: list[_RenderCall]
) -> None:
    """A run that saved nothing still paid for its Scout and its drafts; reporting zero would be false."""
    state = _scouted(tmp_path, "doc-a", scout=_telemetry(SCOUT_MODEL_ID, input_tokens=40, output_tokens=2))
    _attempt(state, "doc-a", status="ERROR", writer=_telemetry(WRITER_MODEL_ID, input_tokens=100, output_tokens=20))

    finalisation = finalise_run(state, supervisor_telemetry=None, rates=TEST_RATES)

    assert render_calls == []
    assert (finalisation.persistence_failed, finalisation.total_tokens) == (False, 162)
    assert finalisation.estimated_cost == pytest.approx(
        sum(estimate_cost(e.telemetry, TEST_RATES) for e in state.ledger), abs=1e-9
    )


def test_finalise_run_logs_no_totals_line_sets_no_exit_code_and_changes_only_the_ledger_and_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rendering_log: pytest.LogCaptureFixture
) -> None:
    """The composition root logs the totals on "Run completed" and sets the exit code (P12); nothing is stored."""
    state, supervisor = _two_saved_and_one_unsaved(tmp_path)
    saved_a = state.documents["doc-a"].saved
    assert saved_a is not None
    _render_fails_for(monkeypatch, saved_a.draft_id)
    before = state.model_copy(deep=True)

    finalise_run(state, supervisor_telemetry=supervisor, rates=TEST_RATES)

    infos = [r.getMessage() for r in _records(rendering_log, logging.INFO)]
    assert len(infos) == 1 and infos[0].startswith("Draft rendered:")
    assert state.exit_code is None
    unchanged = {"ledger", "failures"}
    assert state.model_dump(exclude=unchanged) == before.model_dump(exclude=unchanged)
    assert state.ledger == [*before.ledger, StageTelemetry(stage="supervisor", telemetry=supervisor)]
    assert [(f.stage, f.doc_id) for f in state.failures] == [("render", "doc-a")]
