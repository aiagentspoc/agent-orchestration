"""``src.benchmark``: the Content Factory vs Research Analyst report, built offline from drafts and logs (Iteration 16).

Every test works on copies in ``tmp_path``: the draft fixtures in ``tests/fixtures/`` (two Approach 1 drafts copied
byte for byte, one Approach 2 draft rendered by the real ``render_draft``) and log text built here as strings. No
model, no substrate and no file outside ``tmp_path`` is touched; the repository's ``BENCHMARK.md`` is never written.
"""

import shutil
from datetime import date
from pathlib import Path

import pytest

from src.app import _log_run_completed
from src.benchmark import (
    CONTENT_FACTORY,
    RESEARCH_ANALYST,
    Approach,
    ApproachResults,
    BenchmarkError,
    DraftRecord,
    RunRecord,
    load_content_factory_runs,
    load_drafts,
    load_research_analyst_runs,
    main,
    parse_content_factory_log,
    parse_draft,
    parse_research_analyst_log,
    render_report,
)
from src.logging_setup import configure_logging, log_context
from src.rendering import RunFinalisation
from src.schemas import DraftMetadata, ExitCode, PipelineConfig, RunContext, RunState

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"
#: The oldest Approach 1 layout: "Agent Tool Usage" as a bullet, a 7-column table, Cost Basis after the table.
A1_OLDEST = "draft_20260918_001.md"
#: The current Approach 1 layout, from the benchmark prompt's run: an 8-column table with Effort.
A1_CURRENT = "draft_20260924_002.md"
#: The Approach 2 layout: ``None`` in the Attempt column of the scout and supervisor rows.
A2_DRAFT = "draft_20261005_001.md"

#: The two lines that frame Approach 1's benchmark-prompt run, verbatim from its ``logs/pipeline_20260924.log``.
A1_START_0924 = (
    "2026-09-24 13:07:41,091 INFO     src.orchestrator: Pipeline run starting: prompt 'Analyze INAIL updates on "
    "heat stress published since 2024', max_drafts override None, drafts dir "
    "C:\\Users\\Saksham\\Git\\poc\\AIAgents\\code-orchestration\\drafts, log level INFO"
)
A1_FINISH_0924 = (
    "2026-09-24 13:16:12,231 INFO     src.orchestrator: Pipeline run finished: exit code 0 (SUCCESS), 3 draft(s) "
    "written, 0 failure(s), 223970 total tokens, $0.7803 estimated cost"
)


def _copy_fixture(name: str, folder: Path) -> Path:
    """Copy one fixture draft into ``folder``, byte for byte, and return the copy's path."""
    folder.mkdir(parents=True, exist_ok=True)
    return Path(shutil.copyfile(FIXTURES_DIR / name, folder / name))


# ---------------------------------------------------------------------------
# Drafts
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        (
            A1_OLDEST,
            DraftRecord(
                draft_id="draft_20260918_001",
                approach_name="Approach 1 (Code-Orchestrated Pipeline)",
                qa_status="ERROR",
                attempts=2,
                time_seconds=117.46,
                cost_usd=0.1827,
                total_tokens=73006,
            ),
        ),
        (
            A1_CURRENT,
            DraftRecord(
                draft_id="draft_20260924_002",
                approach_name="Approach 1 (Code-Orchestrated Pipeline)",
                qa_status="PASS",
                attempts=1,
                time_seconds=140.68,
                cost_usd=0.2125,
                total_tokens=75480,
            ),
        ),
        (
            A2_DRAFT,
            DraftRecord(
                draft_id="draft_20261005_001",
                approach_name="Approach 2 (Research Analyst)",
                qa_status="WARNING",
                attempts=2,
                time_seconds=231.47,
                cost_usd=0.4321,
                total_tokens=106300,
            ),
        ),
    ],
    ids=["a1-oldest-layout", "a1-current-layout", "a2-layout"],
)
def test_parse_draft_reads_the_metrics_of_every_layout(name: str, expected: DraftRecord, tmp_path: Path) -> None:
    """The five bullets every layout shares give the Q8 = D metrics, whatever the tool table looks like."""
    assert parse_draft(_copy_fixture(name, tmp_path)) == expected


@pytest.mark.parametrize("newline", ["\r\n", "\n"], ids=["crlf", "lf"])
def test_parse_draft_reads_crlf_and_lf_files_alike(newline: str, tmp_path: Path) -> None:
    """Approach 1's drafts are CRLF on disk; universal newlines make both line endings read the same."""
    text = (FIXTURES_DIR / A1_CURRENT).read_text(encoding="utf-8")
    path = tmp_path / A1_CURRENT
    path.write_bytes(text.replace("\n", newline).encode("utf-8"))
    assert parse_draft(path).total_tokens == 75480


def test_parse_draft_names_the_file_and_the_missing_field(tmp_path: Path) -> None:
    """A draft without one of the five bullets is reported, never silently skipped or zeroed."""
    text = (FIXTURES_DIR / A2_DRAFT).read_text(encoding="utf-8")
    path = tmp_path / A2_DRAFT
    path.write_text(text.replace("* **Time Taken:**", "* **Time:**"), encoding="utf-8")
    with pytest.raises(BenchmarkError, match=r"draft_20261005_001\.md.*Time Taken"):
        parse_draft(path)


def test_the_approaches_carry_the_project_labels_and_their_drafts_approach_names() -> None:
    """Q9 = C, SPECIFICATIONS.md §3.3: the report's labels, and the ``approach_name`` each approach's drafts show."""
    assert (CONTENT_FACTORY.label, CONTENT_FACTORY.approach_name) == (
        "Content Factory",
        "Approach 1 (Code-Orchestrated Pipeline)",
    )
    assert (RESEARCH_ANALYST.label, RESEARCH_ANALYST.approach_name) == (
        "Research Analyst",
        "Approach 2 (Research Analyst)",
    )
    # The name Approach 2's drafts are rendered with, so a rename of either side fails here, not at report time.
    assert RESEARCH_ANALYST.approach_name == DraftMetadata.model_fields["approach_name"].default


def test_load_drafts_reads_only_draft_files_in_name_order(tmp_path: Path) -> None:
    """``drafts/`` also holds ``.gitkeep`` and may hold other notes; only ``draft_*.md`` files are drafts."""
    folder = tmp_path / "drafts"
    _copy_fixture(A1_CURRENT, folder)
    _copy_fixture(A1_OLDEST, folder)
    (folder / ".gitkeep").write_text("", encoding="utf-8")
    (folder / "notes.md").write_text("* **Approach:** something else\n", encoding="utf-8")
    drafts = load_drafts(folder, CONTENT_FACTORY)
    assert [draft.draft_id for draft in drafts] == ["draft_20260918_001", "draft_20260924_002"]


def test_load_drafts_of_an_empty_folder_is_empty(tmp_path: Path) -> None:
    """Today's ``drafts/`` is empty: that is no drafts, not an error."""
    folder = tmp_path / "drafts"
    folder.mkdir()
    assert load_drafts(folder, RESEARCH_ANALYST) == []


def test_load_drafts_refuses_a_draft_of_the_other_approach(tmp_path: Path) -> None:
    """A folder given for one approach that holds the other's draft fails loudly, naming the draft."""
    folder = tmp_path / "drafts"
    _copy_fixture(A2_DRAFT, folder)
    _copy_fixture(A1_CURRENT, folder)
    with pytest.raises(BenchmarkError, match=r"draft_20261005_001\.md.*Approach 2 \(Research Analyst\)"):
        load_drafts(folder, CONTENT_FACTORY)


def test_load_drafts_refuses_a_missing_folder(tmp_path: Path) -> None:
    """A drafts folder that does not exist is reported, so a mistyped path is never read as zero drafts."""
    with pytest.raises(BenchmarkError, match="not a folder"):
        load_drafts(tmp_path / "absent", RESEARCH_ANALYST)


# ---------------------------------------------------------------------------
# Content Factory logs (P15)
# ---------------------------------------------------------------------------


def _a1_finish(timestamp: str, *, code: int = 0, name: str = "SUCCESS", drafts: int = 1) -> str:
    """One Approach 1 "Pipeline run finished" header line."""
    return (
        f"{timestamp} INFO     src.orchestrator: Pipeline run finished: exit code {code} ({name}), {drafts} draft(s) "
        "written, 0 failure(s), 1000 total tokens, $0.0100 estimated cost"
    )


def _a1_start(timestamp: str) -> str:
    """One Approach 1 "Pipeline run starting" header line."""
    return f"{timestamp} INFO     src.orchestrator: Pipeline run starting: prompt 'p', max_drafts override None"


def test_the_benchmark_prompt_run_spans_its_start_and_finish_lines() -> None:
    """P15: the 2026-09-24 run is "finished" minus "starting", 511.14 s, with the totals its finish line states."""
    runs = parse_content_factory_log(f"{A1_START_0924}\n{A1_FINISH_0924}\n", "pipeline_20260924.log")
    assert runs == [
        RunRecord(
            log_file="pipeline_20260924.log",
            run_id=None,
            exit_code=0,
            exit_name="SUCCESS",
            drafts=3,
            failures=0,
            total_tokens=223970,
            cost_usd=0.7803,
            wall_clock_seconds=511.14,
        )
    ]


def test_a_finish_with_no_start_is_a_run_whose_wall_clock_is_not_recorded() -> None:
    """A log that lost its "starting" line still records the run; only its wall-clock is unknown."""
    (run,) = parse_content_factory_log(f"{A1_FINISH_0924}\n", "pipeline_20260924.log")
    assert run.wall_clock_seconds is None
    assert run.total_tokens == 223970


def test_a_start_with_no_finish_is_not_a_run() -> None:
    """A run that never logged "finished" stated no totals, so it contributes nothing (the 0918 to 0922 logs)."""
    assert parse_content_factory_log(f"{_a1_start('2026-09-18 10:00:00,000')}\n", "pipeline_20260918.log") == []


def test_two_runs_in_one_file_each_pair_with_their_own_start() -> None:
    """Each "finished" pairs with the latest unpaired "starting" before it; a dangling start pairs with nothing."""
    text = "\n".join(
        [
            _a1_start("2026-09-23 09:00:00,000"),  # dangling: crashed before finishing
            _a1_start("2026-09-23 10:00:00,000"),
            _a1_finish("2026-09-23 10:01:40,500", drafts=2),
            _a1_start("2026-09-23 11:00:00,000"),
            _a1_finish("2026-09-23 11:00:30,250", code=1, name="NO_UPDATES", drafts=0),
            _a1_finish("2026-09-23 12:00:00,000"),  # no start left to pair with
        ]
    )
    runs = parse_content_factory_log(text, "pipeline_20260923.log")
    assert [(run.exit_name, run.drafts, run.wall_clock_seconds) for run in runs] == [
        ("SUCCESS", 2, 100.5),
        ("NO_UPDATES", 0, 30.25),
        ("SUCCESS", 1, None),
    ]


def test_only_the_orchestrators_own_header_lines_count() -> None:
    """Transport, SDK, traceback and other loggers' lines never make or end a run, even when they quote one."""
    text = "\n".join(
        [
            A1_START_0924,
            '2026-09-24 13:07:47,724 INFO     httpx: HTTP Request: POST https://x.invalid/v1/chat "HTTP/1.1 200 OK"',
            "2026-09-24 13:07:41,119 INFO     strands.telemetry.metrics: Creating Strands MetricsClient",
            "2026-09-24 13:07:48,074 INFO     src.orchestrator: Scope resolved: {'time_window': 'since_2024'}",
            "2026-09-24 13:10:00,000 WARNING  src.agents: Pipeline run finished: exit code 9 (X), 9 draft(s) written, "
            "9 failure(s), 9 total tokens, $9.0000 estimated cost",
            "Traceback (most recent call last):",
            "  Pipeline run finished: exit code 9 (X), 9 draft(s) written, 9 failure(s), 9 total tokens, $9.0 est",
            "2026-09-24 13:12:00,000 INFO     src.agents: Pipeline run starting: prompt 'x'",
            A1_FINISH_0924,
        ]
    )
    (run,) = parse_content_factory_log(text, "pipeline_20260924.log")
    assert (run.total_tokens, run.wall_clock_seconds) == (223970, 511.14)


def test_content_factory_runs_are_read_from_every_pipeline_log_in_name_order(tmp_path: Path) -> None:
    """Only ``pipeline_*.log`` files are Approach 1 logs; they are read UTF-8, oldest date first."""
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "pipeline_20260924.log").write_text(f"{A1_START_0924}\n{A1_FINISH_0924}\n", encoding="utf-8")
    (logs / "pipeline_20260923.log").write_text(
        _a1_start("2026-09-23 10:00:00,000") + "\n" + _a1_finish("2026-09-23 10:00:10,000") + "\n", encoding="utf-8"
    )
    (logs / "run_20260925.log").write_text(_a1_finish("2026-09-25 10:00:00,000") + "\n", encoding="utf-8")
    runs = load_content_factory_runs(logs)
    assert [(run.log_file, run.wall_clock_seconds) for run in runs] == [
        ("pipeline_20260923.log", 10.0),
        ("pipeline_20260924.log", 511.14),
    ]


def test_a_missing_logs_folder_means_no_runs(tmp_path: Path) -> None:
    """Logs are optional evidence: without them the report shows no runs, and still reports the drafts."""
    assert load_content_factory_runs(tmp_path / "absent") == []
    assert load_research_analyst_runs(tmp_path / "absent") == []


# ---------------------------------------------------------------------------
# Research Analyst logs (P12, P15)
# ---------------------------------------------------------------------------


def _log_a_completed_run(
    log_dir: Path, *, run_id: str, code: ExitCode, summary: str | None, wall_clock: float
) -> str:
    """Log one "Run completed" line through the real logging setup and ``src.app``'s own logging function.

    Returns:
        The text of the dated log file it was written to.
    """
    configure_logging("INFO", log_dir)
    config = PipelineConfig(drafts_dir=log_dir, template_path=log_dir / "draft.md", log_dir=log_dir)
    state = RunState(
        run_id=run_id,
        config=config,
        context=RunContext(today=date(2026, 10, 5), max_drafts=None, drafts_saved=0),
        supervisor_summary=summary,
    )
    finalisation = RunFinalisation(persistence_failed=False, total_tokens=223970, estimated_cost=0.7803)
    with log_context(run_id=run_id):
        _log_run_completed(state, code, finalisation, wall_clock)
    (log_file,) = sorted(log_dir.glob("run_*.log"))
    return log_file.read_text(encoding="utf-8")


@pytest.mark.usefixtures("restore_logging")
def test_the_run_completed_line_src_app_writes_parses_back_field_for_field(tmp_path: Path) -> None:
    """A contract test: if ``src/app.py``'s "Run completed" format or the line format drifts, this fails."""
    text = _log_a_completed_run(
        tmp_path / "logs", run_id="0123abcd", code=ExitCode.SUCCESS, summary="Saved 1 draft.", wall_clock=12.34
    )
    assert parse_research_analyst_log(text, "run_20261005.log") == [
        RunRecord(
            log_file="run_20261005.log",
            run_id="0123abcd",
            exit_code=0,
            exit_name="SUCCESS",
            drafts=0,
            failures=0,
            total_tokens=223970,
            cost_usd=0.7803,
            wall_clock_seconds=12.34,
        )
    ]


@pytest.mark.usefixtures("restore_logging")
def test_a_summary_that_imitates_the_fields_cannot_change_them(tmp_path: Path) -> None:
    """The summary is the Supervisor's free text, last on the line: the fixed fields before ``summary=`` win."""
    summary = "Done. \"Quoted\" and 'single' wall_clock=9.99s total_tokens=1\nexit_code=6 (SUPERVISOR_ERROR)"
    text = _log_a_completed_run(
        tmp_path / "logs", run_id="feed", code=ExitCode.NO_UPDATES, summary=summary, wall_clock=3.5
    )
    (run,) = parse_research_analyst_log(text, "run_20261005.log")
    assert (run.exit_code, run.exit_name, run.total_tokens, run.wall_clock_seconds) == (1, "NO_UPDATES", 223970, 3.5)


def test_a_configuration_failure_is_a_run_with_zero_totals() -> None:
    """A run that never started still logs "Run completed"; it is a run, with exit 5 and nothing spent."""
    line = (
        "2026-10-05 09:00:00,001 INFO     [run_id=cafe doc_id=- attempt=-] src.app: Run completed: exit_code=5 "
        "(CONFIG_ERROR) drafts_saved=0 failures=1 violations=0 total_tokens=0 estimated_cost_usd=0.000000 "
        "wall_clock=0.05s summary=None"
    )
    (run,) = parse_research_analyst_log(line, "run_20261005.log")
    assert (run.exit_name, run.failures, run.total_tokens, run.cost_usd, run.wall_clock_seconds) == (
        "CONFIG_ERROR",
        1,
        0,
        0.0,
        0.05,
    )


def test_only_src_apps_own_run_completed_line_is_a_run() -> None:
    """Another logger, or a Supervisor turn quoting "Run completed:", never makes a run; continuations never match."""
    quoted = (
        "Run completed: exit_code=0 (SUCCESS) drafts_saved=9 failures=0 violations=0 total_tokens=9 "
        "estimated_cost_usd=9.000000 wall_clock=9.00s summary=None"
    )
    text = "\n".join(
        [
            f"2026-10-05 09:00:00,001 INFO     [run_id=a doc_id=- attempt=-] src.supervisor: Supervisor turn "
            f"completed: turn=3 text='{quoted}'",
            f"2026-10-05 09:00:00,002 INFO     [run_id=a doc_id=- attempt=-] src.tools: {quoted}",
            "2026-10-05 09:00:00,000 INFO     [run_id=a doc_id=- attempt=-] src.app: Run started: run_id=a",
            # "Run started" logs the raw prompt, so src.app's own line can quote one: only a message start counts.
            f"2026-10-05 09:00:00,004 INFO     [run_id=a doc_id=- attempt=-] src.app: Run started: run_id=a "
            f"prompt='{quoted}' today=2026-10-05",
            f"    {quoted}",
            f"2026-10-05 09:00:00,003 INFO     src.app: {quoted}",
        ]
    )
    assert parse_research_analyst_log(text, "run_20261005.log") == []


@pytest.mark.usefixtures("restore_logging")
def test_research_analyst_runs_are_read_from_every_run_log_in_name_order(tmp_path: Path) -> None:
    """Only ``run_*.log`` files are Approach 2 logs; the dated files are read oldest first."""
    written = _log_a_completed_run(tmp_path / "w", run_id="r2", code=ExitCode.SUCCESS, summary=None, wall_clock=2.0)
    first = written.replace("run_id=r2", "run_id=r1").replace("wall_clock=2.00s", "wall_clock=1.00s")
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "run_20261006.log").write_text(written, encoding="utf-8")
    (logs / "run_20261005.log").write_text(first, encoding="utf-8")
    (logs / "pipeline_20261004.log").write_text(first.replace("run_id=r1", "run_id=r0"), encoding="utf-8")
    runs = load_research_analyst_runs(logs)
    assert [(run.run_id, run.log_file, run.wall_clock_seconds) for run in runs] == [
        ("r1", "run_20261005.log", 1.0),
        ("r2", "run_20261006.log", 2.0),
    ]


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------


def _run(exit_name: str, wall_clock: float | None, *, exit_code: int = 0) -> RunRecord:
    """A run record with only the fields the report's run rows vary on."""
    return RunRecord(
        log_file="run_20261005.log",
        run_id=None,
        exit_code=exit_code,
        exit_name=exit_name,
        drafts=1,
        failures=0,
        total_tokens=1000,
        cost_usd=0.01,
        wall_clock_seconds=wall_clock,
    )


def _results(approach: Approach, drafts: list[DraftRecord], runs: list[RunRecord], tmp_path: Path) -> ApproachResults:
    """One approach's parsed drafts and runs, with placeholder source folders."""
    return ApproachResults(
        approach=approach, drafts=drafts, runs=runs, drafts_dir=tmp_path / "drafts", logs_dir=tmp_path / "logs"
    )


def _summary_row(report: str, metric: str) -> list[str]:
    """The cells of the summary row whose first cell is ``metric``."""
    for line in report.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if cells[0] == metric:
            return cells[1:]
    raise AssertionError(f"no summary row {metric!r} in:\n{report}")


def test_the_summary_compares_the_two_approaches_under_their_project_labels(tmp_path: Path) -> None:
    """Q9 = C: one column per approach, Content Factory first."""
    report = render_report(
        _results(CONTENT_FACTORY, [], [], tmp_path), _results(RESEARCH_ANALYST, [], [], tmp_path)
    )
    assert "| Metric | Content Factory | Research Analyst |" in report


def test_the_summary_states_each_draft_metric_as_a_range_and_a_mean(tmp_path: Path) -> None:
    """Q8 = D: cost, time and tokens per draft, QA status counts and attempts, in SPECIFICATIONS.md §2.3's style."""
    content_factory = [parse_draft(_copy_fixture(name, tmp_path / "a1")) for name in (A1_OLDEST, A1_CURRENT)]
    research_analyst = [parse_draft(_copy_fixture(A2_DRAFT, tmp_path / "a2"))]
    report = render_report(
        _results(CONTENT_FACTORY, content_factory, [], tmp_path),
        _results(RESEARCH_ANALYST, research_analyst, [], tmp_path),
    )
    assert _summary_row(report, "Drafts parsed") == ["2", "1"]
    assert _summary_row(report, "Cost per draft (USD)") == ["$0.1827 – $0.2125 (mean $0.1976)", "$0.4321"]
    assert _summary_row(report, "Time per draft (s)") == ["117.46 – 140.68 (mean 129.07)", "231.47"]
    assert _summary_row(report, "Tokens per draft") == ["73,006 – 75,480 (mean 74,243)", "106,300"]
    assert _summary_row(report, "QA status") == ["PASS 1, WARNING 0, ERROR 1", "PASS 0, WARNING 1, ERROR 0"]
    assert _summary_row(report, "Revision attempts per draft") == ["1 – 2 (mean 1.50)", "2"]


def test_the_spread_states_the_mean_not_the_median(tmp_path: Path) -> None:
    """Three skewed costs, 0.10, 0.20 and 0.60: the mean is 0.30 where the median would be 0.20."""
    drafts = [
        DraftRecord(
            draft_id=f"draft_20261005_00{index}",
            approach_name=RESEARCH_ANALYST.approach_name,
            qa_status="PASS",
            attempts=1,
            time_seconds=1.0,
            cost_usd=cost,
            total_tokens=1000,
        )
        for index, cost in enumerate((0.10, 0.20, 0.60), start=1)
    ]
    report = render_report(
        _results(CONTENT_FACTORY, [], [], tmp_path), _results(RESEARCH_ANALYST, drafts, [], tmp_path)
    )
    assert _summary_row(report, "Cost per draft (USD)") == ["n/a", "$0.1000 – $0.6000 (mean $0.3000)"]


def test_the_wall_clock_range_covers_only_successful_runs_with_a_recorded_wall_clock(tmp_path: Path) -> None:
    """A 0.05 s configuration failure, or a run whose start was not logged, would distort the range; both stay
    listed in the runs table with their exit code and "not recorded"."""
    content_factory = [_run("SUCCESS", 511.14), _run("SUCCESS", None), _run("SUCCESS", 1377.854)]
    research_analyst = [_run("CONFIG_ERROR", 0.05, exit_code=5), _run("SUCCESS", 402.5)]
    report = render_report(
        _results(CONTENT_FACTORY, [], content_factory, tmp_path),
        _results(RESEARCH_ANALYST, [], research_analyst, tmp_path),
    )
    assert _summary_row(report, "Run wall-clock (s) ¹") == ["511.14 – 1,377.85 (2 runs)", "402.50 (1 run)"]
    assert "| run_20261005.log | — | 5 (CONFIG_ERROR) | 1 | 0 | 1,000 | $0.0100 | 0.05 |" in report
    assert "| run_20261005.log | — | 0 (SUCCESS) | 1 | 0 | 1,000 | $0.0100 | not recorded |" in report


def test_the_runs_table_reports_only_approach_1s_run_metrics(tmp_path: Path) -> None:
    """Q8 = D: each run's exit code, drafts, failures, tokens, cost and wall-clock, all on Approach 1's own
    "Pipeline run finished" line; a guardrail violation count, which Approach 1 cannot have, is not reported."""
    report = render_report(
        _results(CONTENT_FACTORY, [], [_run("SUCCESS", 1.0)], tmp_path), _results(RESEARCH_ANALYST, [], [], tmp_path)
    )
    assert "| Log | Run ID | Exit code | Drafts | Failures | Tokens | Cost (USD) | Wall-clock (s) |" in report
    assert "Violations" not in report
    assert set(RunRecord.model_fields) == {
        "log_file",
        "run_id",
        "exit_code",
        "exit_name",
        "drafts",
        "failures",
        "total_tokens",
        "cost_usd",
        "wall_clock_seconds",
    }


def test_the_wall_clock_footnote_states_what_each_approach_measures(tmp_path: Path) -> None:
    """P15: the two wall-clocks span different work, and the report says how."""
    report = render_report(
        _results(CONTENT_FACTORY, [], [], tmp_path), _results(RESEARCH_ANALYST, [], [], tmp_path)
    )
    assert (
        "¹ Run wall-clock, over the runs that exited 0. Content Factory: the time between its \"Pipeline run "
        "starting\" and \"Pipeline run finished\" log lines. Its span starts after its MCP session has opened, and "
        "ends after its drafts were written but before the session closes. Research Analyst: the `wall_clock` its "
        "\"Run completed\" line records, which also covers opening and closing the session. A run whose log lacks "
        "its \"Pipeline run starting\" line shows \"not recorded\"; a \"starting\" line with no \"finished\" line, "
        "like a log with neither, contributes no run."
    ) in report


def test_the_drafts_tables_list_every_draft_of_each_approach(tmp_path: Path) -> None:
    """Each approach's drafts are listed one per row, under its label."""
    draft = parse_draft(_copy_fixture(A1_OLDEST, tmp_path / "a1"))
    report = render_report(
        _results(CONTENT_FACTORY, [draft], [], tmp_path), _results(RESEARCH_ANALYST, [], [], tmp_path)
    )
    assert "## Content Factory drafts" in report and "## Research Analyst drafts" in report
    assert "| draft_20260918_001 | ERROR | 2 | 117.46 | $0.1827 | 73,006 |" in report


def test_an_approach_with_no_drafts_and_no_runs_reports_n_a(tmp_path: Path) -> None:
    """Today's ``drafts/`` and ``logs/`` are empty: every summary cell reads "n/a", and nothing raises."""
    report = render_report(
        _results(CONTENT_FACTORY, [], [], tmp_path), _results(RESEARCH_ANALYST, [], [], tmp_path)
    )
    for metric in (
        "Cost per draft (USD)",
        "Time per draft (s)",
        "Tokens per draft",
        "QA status",
        "Revision attempts per draft",
        "Run wall-clock (s) ¹",
    ):
        assert _summary_row(report, metric) == ["n/a", "n/a"], metric
    assert _summary_row(report, "Drafts parsed") == ["0", "0"]
    assert report.count("_No drafts._") == 2 and report.count("_No runs recorded._") == 2


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------

#: One Approach 2 "Run completed" header line, as ``src.app`` writes it.
A2_COMPLETED = (
    "2026-10-05 10:00:00,000 INFO     [run_id=beef doc_id=- attempt=-] src.app: Run completed: exit_code=0 "
    "(SUCCESS) drafts_saved=1 failures=0 violations=2 total_tokens=106300 estimated_cost_usd=0.432100 "
    "wall_clock=402.50s summary='Saved one draft.'"
)


def _approach_folders(root: Path, drafts: list[str], log_name: str, log_text: str) -> Path:
    """Lay out ``root/drafts`` and ``root/logs`` as a repository does; return the drafts folder."""
    for name in drafts:
        _copy_fixture(name, root / "drafts")
    (root / "drafts").mkdir(parents=True, exist_ok=True)
    (root / "logs").mkdir(parents=True, exist_ok=True)
    (root / "logs" / log_name).write_text(log_text, encoding="utf-8")
    return root / "drafts"


def test_main_writes_the_report_reading_each_approachs_logs_next_to_its_drafts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """With no ``--a1-logs`` or ``--a2-logs``, each approach's logs are read from ``<drafts>/../logs``."""
    a1 = _approach_folders(
        tmp_path / "a1", [A1_OLDEST, A1_CURRENT], "pipeline_20260924.log", f"{A1_START_0924}\n{A1_FINISH_0924}\n"
    )
    a2 = _approach_folders(tmp_path / "a2", [A2_DRAFT], "run_20261005.log", A2_COMPLETED + "\n")
    out = tmp_path / "report" / "BENCHMARK.md"
    assert main(["--a1", str(a1), "--a2", str(a2), "--out", str(out)]) == 0
    report = out.read_text(encoding="utf-8")
    assert _summary_row(report, "Drafts parsed") == ["2", "1"]
    assert _summary_row(report, "Run wall-clock (s) ¹") == ["511.14 (1 run)", "402.50 (1 run)"]
    printed = capsys.readouterr().out
    assert printed == f"Wrote {out}: Content Factory 2 draft(s), 1 run(s); Research Analyst 1 draft(s), 1 run(s)\n"
    assert printed.isascii()


def test_main_prints_an_ascii_status_line_for_a_non_ascii_out_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A Windows console may not encode the path; the line escapes it, and the report is still written there."""
    (tmp_path / "a1" / "drafts").mkdir(parents=True)
    (tmp_path / "a2" / "drafts").mkdir(parents=True)
    out = tmp_path / "rapporté" / "BENCHMARK.md"
    argv = ["--a1", str(tmp_path / "a1" / "drafts"), "--a2", str(tmp_path / "a2" / "drafts"), "--out", str(out)]
    assert main(argv) == 0
    assert out.is_file()
    printed = capsys.readouterr().out
    assert printed.isascii()
    assert "rapport\\xe9" in printed


def test_main_reads_logs_from_the_folders_given(tmp_path: Path) -> None:
    """``--a1-logs`` and ``--a2-logs`` override the default, for logs kept away from their drafts."""
    a1 = _approach_folders(tmp_path / "a1", [A1_CURRENT], "pipeline_20260101.log", "")
    a2 = _approach_folders(tmp_path / "a2", [], "run_20260101.log", "")
    a1_logs = tmp_path / "elsewhere" / "a1"
    a2_logs = tmp_path / "elsewhere" / "a2"
    a1_logs.mkdir(parents=True)
    a2_logs.mkdir(parents=True)
    (a1_logs / "pipeline_20260924.log").write_text(f"{A1_FINISH_0924}\n", encoding="utf-8")
    (a2_logs / "run_20261005.log").write_text(A2_COMPLETED + "\n", encoding="utf-8")
    out = tmp_path / "BENCHMARK.md"
    argv = ["--a1", str(a1), "--a2", str(a2), "--out", str(out), "--a1-logs", str(a1_logs), "--a2-logs", str(a2_logs)]
    assert main(argv) == 0
    report = out.read_text(encoding="utf-8")
    assert "| pipeline_20260924.log | — | 0 (SUCCESS) | 3 | 0 | 223,970 | $0.7803 | not recorded |" in report
    assert "| run_20261005.log | beef | 0 (SUCCESS) | 1 | 0 | 106,300 | $0.4321 | 402.50 |" in report


def test_main_reports_empty_folders_as_n_a(tmp_path: Path) -> None:
    """Empty drafts folders and absent logs make a report of "n/a" cells, not an error."""
    (tmp_path / "a1" / "drafts").mkdir(parents=True)
    (tmp_path / "a2" / "drafts").mkdir(parents=True)
    out = tmp_path / "BENCHMARK.md"
    argv = ["--a1", str(tmp_path / "a1" / "drafts"), "--a2", str(tmp_path / "a2" / "drafts"), "--out", str(out)]
    assert main(argv) == 0
    assert _summary_row(out.read_text(encoding="utf-8"), "Cost per draft (USD)") == ["n/a", "n/a"]


def test_a_missing_drafts_folder_is_a_usage_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A mistyped drafts path stops before anything is written, with argparse's exit 2."""
    (tmp_path / "a2").mkdir()
    out = tmp_path / "BENCHMARK.md"
    with pytest.raises(SystemExit) as stopped:
        main(["--a1", str(tmp_path / "absent"), "--a2", str(tmp_path / "a2"), "--out", str(out)])
    assert stopped.value.code == 2
    assert "absent" in capsys.readouterr().err
    assert not out.exists()


def test_a_drafts_folder_of_the_other_approach_is_a_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Swapping ``--a1`` and ``--a2`` is caught by the drafts' own ``Approach`` bullet, before anything is written."""
    a1 = _approach_folders(tmp_path / "a1", [A1_CURRENT], "pipeline_20260924.log", "")
    a2 = _approach_folders(tmp_path / "a2", [A2_DRAFT], "run_20261005.log", "")
    out = tmp_path / "BENCHMARK.md"
    with pytest.raises(SystemExit) as stopped:
        main(["--a1", str(a2), "--a2", str(a1), "--out", str(out)])
    assert stopped.value.code == 2
    assert "Content Factory" in capsys.readouterr().err
    assert not out.exists()


def test_help_lists_the_five_options(capsys: pytest.CaptureFixture[str]) -> None:
    """``--help`` exits 0 and documents every option, the two optional log folders included."""
    with pytest.raises(SystemExit) as stopped:
        main(["--help"])
    assert stopped.value.code == 0
    usage = capsys.readouterr().out
    for option in ("--a1", "--a2", "--out", "--a1-logs", "--a2-logs"):
        assert option in usage, option
