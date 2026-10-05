"""The benchmark report: Content Factory (Approach 1) against Research Analyst (Approach 2), from files on disk.

It reads exactly Approach 1's metrics (SPECIFICATIONS.md D-B, Q8 = D): each draft's cost, time, tokens, QA status and
attempts, from the five telemetry bullets every draft layout shares, and each run's wall-clock from its log (P15).
Nothing is recomputed: the report restates what the drafts and logs recorded.

The module has no import-time side effects.
"""

import argparse
import re
import statistics
import sys
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Final, Literal, TypeAlias, cast

from pydantic import BaseModel, ConfigDict

__all__ = [
    "CONTENT_FACTORY",
    "RESEARCH_ANALYST",
    "Approach",
    "ApproachResults",
    "BenchmarkError",
    "DraftRecord",
    "RunRecord",
    "build_arg_parser",
    "load_content_factory_runs",
    "load_drafts",
    "load_research_analyst_runs",
    "main",
    "parse_content_factory_log",
    "parse_draft",
    "parse_research_analyst_log",
    "render_report",
]

#: QA-Legal's verdict, as a draft's ``Status`` bullet states it.
QAStatus: TypeAlias = Literal["PASS", "WARNING", "ERROR"]

#: The bullets every draft layout shares, Approach 1's oldest included, each anchored at the start of its line. The
#: tool table is deliberately not read: its columns changed between Approach 1's runs, and Q8 = D needs none of it.
_APPROACH: Final[re.Pattern[str]] = re.compile(r"^\* \*\*Approach:\*\* (.+?)\s*$", re.MULTILINE)
_STATUS: Final[re.Pattern[str]] = re.compile(r"^\* \*\*Status:\*\* (PASS|WARNING|ERROR)\s*$", re.MULTILINE)
_ATTEMPTS: Final[re.Pattern[str]] = re.compile(r"^\* \*\*Revision Attempts:\*\* (\d+)\s*$", re.MULTILINE)
_TIME: Final[re.Pattern[str]] = re.compile(r"^\* \*\*Time Taken:\*\* (\d+(?:\.\d+)?)s\s*$", re.MULTILINE)
_COST: Final[re.Pattern[str]] = re.compile(
    r"^\* \*\*Estimated Cost:\*\* \$(\d+(?:\.\d+)?) \((\d+) tokens\)\s*$", re.MULTILINE
)

#: The timestamp ``logging`` writes by default, ``%(asctime)s``, in both approaches' logs.
_TIMESTAMP_FORMAT: Final[str] = "%Y-%m-%d %H:%M:%S,%f"
_TIMESTAMP: Final[str] = r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3})"

#: An Approach 1 header line: timestamp, level, logger, message. Traceback and continuation lines never match.
_A1_HEADER: Final[re.Pattern[str]] = re.compile(_TIMESTAMP + r" +(\w+) +(\S+): (.*)$")
#: The one logger whose lines frame an Approach 1 run.
_A1_LOGGER: Final[str] = "src.orchestrator"
_A1_STARTING: Final[str] = "Pipeline run starting: "
_A1_FINISHED: Final[re.Pattern[str]] = re.compile(
    r"Pipeline run finished: exit code (\d+) \((\w+)\), (\d+) draft\(s\) written, (\d+) failure\(s\), "
    r"(\d+) total tokens, \$(\d+\.\d+) estimated cost"
)

#: An Approach 2 header line, per ``src.logging_setup``'s line format: timestamp, level, the three correlation
#: fields, logger, message.
_A2_HEADER: Final[re.Pattern[str]] = re.compile(
    _TIMESTAMP + r" +(\w+) +\[run_id=([^ \]]+) doc_id=\S+ attempt=\S+\] (\S+): (.*)$"
)
#: The one logger that writes "Run completed" (``src.app``, P12).
_A2_LOGGER: Final[str] = "src.app"
#: The fixed fields of "Run completed", anchored at the message start and read up to ``summary=`` only: the summary
#: is the Supervisor's free text, last on the line, so nothing in it can imitate a field. ``violations=`` is matched,
#: so the line format stays pinned, but not captured: Approach 1 has no guardrails, so it is no shared metric (Q8 = D).
_A2_COMPLETED: Final[re.Pattern[str]] = re.compile(
    r"Run completed: exit_code=(\d+) \((\w+)\) drafts_saved=(\d+) failures=(\d+) violations=\d+ "
    r"total_tokens=(\d+) estimated_cost_usd=(\d+\.\d+) wall_clock=(\d+\.\d+)s summary="
)

#: Marks the run wall-clock row and its footnote.
_FOOTNOTE_MARK: Final[str] = "¹"
#: What each approach's run wall-clock spans (P15). Approach 1 logs no wall-clock, so its span is read from two log
#: timestamps that do not bracket the whole process; the footnote says so wherever the two figures appear together.
_WALL_CLOCK_FOOTNOTE: Final[str] = (
    f"{_FOOTNOTE_MARK} Run wall-clock, over the runs that exited 0. Content Factory: the time between its "
    '"Pipeline run starting" and "Pipeline run finished" log lines. Its span starts after its MCP session has '
    "opened, and ends after its drafts were written but before the session closes. Research Analyst: the "
    '`wall_clock` its "Run completed" line records, which also covers opening and closing the session. A run '
    'whose log lacks its "Pipeline run starting" line shows "not recorded"; a "starting" line with no "finished" '
    "line, like a log with neither, contributes no run."
)
#: A summary cell with no value to state.
_NOT_APPLICABLE: Final[str] = "n/a"
#: A table cell whose value the source never recorded.
_UNSET_CELL: Final[str] = "—"
#: The exit code whose runs the wall-clock range covers.
_SUCCESS_EXIT_CODE: Final[int] = 0
_QA_STATUSES: Final[tuple[QAStatus, ...]] = ("PASS", "WARNING", "ERROR")


class Approach(BaseModel):
    """One side of the comparison: its report label (Q9 = C) and the ``approach_name`` its drafts show (§3.3)."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    label: str
    approach_name: str


#: Approach 1, as SPECIFICATIONS.md §3.3 names it in the report and as its drafts already state it.
CONTENT_FACTORY: Final[Approach] = Approach(
    label="Content Factory", approach_name="Approach 1 (Code-Orchestrated Pipeline)"
)
#: Approach 2, as SPECIFICATIONS.md §3.3 names it; ``DraftMetadata.approach_name`` defaults to this name.
RESEARCH_ANALYST: Final[Approach] = Approach(label="Research Analyst", approach_name="Approach 2 (Research Analyst)")


class BenchmarkError(ValueError):
    """A draft or folder the benchmark cannot read as the approach it was given for."""


class DraftRecord(BaseModel):
    """One draft's benchmark metrics, as its telemetry section states them (Q8 = D)."""

    model_config = ConfigDict(extra="ignore")

    draft_id: str
    approach_name: str
    qa_status: QAStatus
    attempts: int
    time_seconds: float
    cost_usd: float
    total_tokens: int


class RunRecord(BaseModel):
    """One run's outcome and totals, as its log states them; the run wall-clock is the one metric not on a draft.

    Attributes:
        log_file: The log file the run was read from.
        run_id: The run's ID; Approach 1 logs none.
        exit_code: The run's exit code, and ``exit_name`` its name.
        drafts: The drafts the run wrote (Approach 1) or saved (Approach 2).
        failures: The failures the run recorded.
        total_tokens: The run's total tokens, and ``cost_usd`` its estimated cost.
        wall_clock_seconds: The run's wall-clock (P15); ``None`` when its log does not record it.
    """

    model_config = ConfigDict(extra="ignore")

    log_file: str
    run_id: str | None
    exit_code: int
    exit_name: str
    drafts: int
    failures: int
    total_tokens: int
    cost_usd: float
    wall_clock_seconds: float | None


class ApproachResults(BaseModel):
    """Everything the report states about one approach: its drafts, its runs, and where they were read from."""

    model_config = ConfigDict(extra="ignore")

    approach: Approach
    drafts: list[DraftRecord]
    runs: list[RunRecord]
    drafts_dir: Path
    logs_dir: Path


def parse_draft(path: Path) -> DraftRecord:
    """Read one draft's metrics from its five shared bullets.

    The file is read as UTF-8 with universal newlines, so Approach 1's CRLF drafts read like LF ones.

    Args:
        path: A ``draft_*.md`` file.

    Returns:
        The draft's metrics; ``draft_id`` is the file name without its suffix.

    Raises:
        BenchmarkError: If any of the five bullets is missing, naming the file and the bullet.
    """
    text = path.read_text(encoding="utf-8")
    approach = _search(_APPROACH, text, path, "Approach")
    status = _search(_STATUS, text, path, "Status")
    attempts = _search(_ATTEMPTS, text, path, "Revision Attempts")
    time_taken = _search(_TIME, text, path, "Time Taken")
    cost = _search(_COST, text, path, "Estimated Cost")
    return DraftRecord(
        draft_id=path.stem,
        approach_name=approach.group(1),
        qa_status=cast(QAStatus, status.group(1)),  # _STATUS admits only the three statuses
        attempts=int(attempts.group(1)),
        time_seconds=float(time_taken.group(1)),
        cost_usd=float(cost.group(1)),
        total_tokens=int(cost.group(2)),
    )


def load_drafts(folder: Path, approach: Approach) -> list[DraftRecord]:
    """Read every ``draft_*.md`` in ``folder``, in name order, and check each belongs to ``approach``.

    Only ``draft_*.md`` files are read, so ``.gitkeep`` and any other note are ignored. An empty folder is no drafts.

    Args:
        folder: The approach's drafts folder.
        approach: The approach the folder was given for.

    Returns:
        One record per draft, in file-name order, which is date and sequence order.

    Raises:
        BenchmarkError: If ``folder`` is not a folder, if a draft lacks one of the five bullets, or if a draft's
            ``Approach`` is not ``approach.approach_name``: a folder of the other approach would otherwise be
            reported as this one.
    """
    if not folder.is_dir():
        raise BenchmarkError(f"{folder} is not a folder of drafts")
    drafts = [parse_draft(path) for path in sorted(folder.glob("draft_*.md"))]
    for draft in drafts:
        if draft.approach_name != approach.approach_name:
            raise BenchmarkError(
                f"{draft.draft_id}.md in {folder} is a draft of {draft.approach_name!r}, "
                f"not of {approach.approach_name!r} ({approach.label})"
            )
    return drafts


def parse_content_factory_log(text: str, log_file: str) -> list[RunRecord]:
    """Read the runs one Approach 1 log records (P15).

    Only ``src.orchestrator`` header lines count. A run is one "Pipeline run finished" line, which states its exit
    code and totals; its wall-clock is that line's timestamp minus the latest "Pipeline run starting" line before it
    that no earlier run used, and ``None`` ("not recorded") when there is none. A "starting" line never followed by
    a "finished" one stated no totals, so it is not a run.

    Args:
        text: The log's text.
        log_file: The log's file name, recorded on each run.

    Returns:
        The runs, in the order they finished.
    """
    runs: list[RunRecord] = []
    pending_start: datetime | None = None
    for line in text.splitlines():
        header = _A1_HEADER.match(line)
        if header is None or header.group(3) != _A1_LOGGER:
            continue
        timestamp = datetime.strptime(header.group(1), _TIMESTAMP_FORMAT)
        message = header.group(4)
        if message.startswith(_A1_STARTING):
            pending_start = timestamp
            continue
        finished = _A1_FINISHED.match(message)
        if finished is None:
            continue
        wall_clock = None if pending_start is None else (timestamp - pending_start).total_seconds()
        pending_start = None
        runs.append(
            RunRecord(
                log_file=log_file,
                run_id=None,
                exit_code=int(finished.group(1)),
                exit_name=finished.group(2),
                drafts=int(finished.group(3)),
                failures=int(finished.group(4)),
                total_tokens=int(finished.group(5)),
                cost_usd=float(finished.group(6)),
                wall_clock_seconds=wall_clock,
            )
        )
    return runs


def load_content_factory_runs(logs_dir: Path) -> list[RunRecord]:
    """Read the runs of every ``pipeline_*.log`` in ``logs_dir``, oldest file first; none if the folder is absent."""
    return [
        run
        for path in _log_files(logs_dir, "pipeline_*.log")
        for run in parse_content_factory_log(path.read_text(encoding="utf-8"), path.name)
    ]


def parse_research_analyst_log(text: str, log_file: str) -> list[RunRecord]:
    """Read the runs one Approach 2 log records: one per ``src.app`` "Run completed" line (P12).

    Its wall-clock is the one that line records. Only the fields before ``summary=`` are read.

    Args:
        text: The log's text.
        log_file: The log's file name, recorded on each run.

    Returns:
        The runs, in the order they completed.
    """
    runs: list[RunRecord] = []
    for line in text.splitlines():
        header = _A2_HEADER.match(line)
        if header is None or header.group(4) != _A2_LOGGER:
            continue
        completed = _A2_COMPLETED.match(header.group(5))
        if completed is None:
            continue
        runs.append(
            RunRecord(
                log_file=log_file,
                run_id=header.group(3),
                exit_code=int(completed.group(1)),
                exit_name=completed.group(2),
                drafts=int(completed.group(3)),
                failures=int(completed.group(4)),
                total_tokens=int(completed.group(5)),
                cost_usd=float(completed.group(6)),
                wall_clock_seconds=float(completed.group(7)),
            )
        )
    return runs


def load_research_analyst_runs(logs_dir: Path) -> list[RunRecord]:
    """Read the runs of every ``run_*.log`` in ``logs_dir``, oldest file first; none if the folder is absent."""
    return [
        run
        for path in _log_files(logs_dir, "run_*.log")
        for run in parse_research_analyst_log(path.read_text(encoding="utf-8"), path.name)
    ]


def render_report(content_factory: ApproachResults, research_analyst: ApproachResults) -> str:
    """Render the benchmark report as Markdown: a side-by-side summary, then each approach's drafts and runs.

    The summary states each per-draft metric as ``min – max (mean …)``, SPECIFICATIONS.md §2.3's range style, or
    the one value when there is one draft, and "n/a" when there is none. The run wall-clock row covers only the runs
    that exited 0 with a recorded wall-clock, so a run that failed at configuration cannot distort the range; every
    run is still listed, with its exit code, in its approach's runs table, and a footnote states what each
    approach's wall-clock spans (P15).

    Args:
        content_factory: Approach 1's drafts and runs.
        research_analyst: Approach 2's drafts and runs.

    Returns:
        The report text, ending with a newline.
    """
    sides = (content_factory, research_analyst)
    lines = [
        f"# Benchmark: {content_factory.approach.label} vs {research_analyst.approach.label}",
        "",
        "Approach 1's metrics only (SPECIFICATIONS.md D-B, Q8 = D), restated from each draft's telemetry section and "
        "each run's log line; nothing is recomputed.",
        "",
        *(
            f"* **{side.approach.label}** ({side.approach.approach_name}): drafts from `{side.drafts_dir}`, "
            f"runs from `{side.logs_dir}`."
            for side in sides
        ),
        "",
        "## Summary",
        "",
        f"| Metric | {content_factory.approach.label} | {research_analyst.approach.label} |",
        "| :--- | :--- | :--- |",
        _summary_line("Drafts parsed", [str(len(side.drafts)) for side in sides]),
        _summary_line("Cost per draft (USD)", [_spread([d.cost_usd for d in side.drafts], _usd) for side in sides]),
        _summary_line(
            "Time per draft (s)", [_spread([d.time_seconds for d in side.drafts], _seconds) for side in sides]
        ),
        _summary_line(
            "Tokens per draft", [_spread([float(d.total_tokens) for d in side.drafts], _tokens) for side in sides]
        ),
        _summary_line("QA status", [_status_counts(side.drafts) for side in sides]),
        _summary_line(
            "Revision attempts per draft",
            [_spread([float(d.attempts) for d in side.drafts], _attempts, _two_decimals) for side in sides],
        ),
        _summary_line(f"Run wall-clock (s) {_FOOTNOTE_MARK}", [_wall_clock_range(side.runs) for side in sides]),
        "",
        _WALL_CLOCK_FOOTNOTE,
    ]
    for side in sides:
        lines += ["", f"## {side.approach.label} drafts", "", *_drafts_table(side.drafts)]
    for side in sides:
        lines += ["", f"## {side.approach.label} runs", "", *_runs_table(side.runs)]
    return "\n".join(lines) + "\n"


def _summary_line(metric: str, cells: list[str]) -> str:
    """One summary table row."""
    return "| " + " | ".join([metric, *cells]) + " |"


def _usd(value: float) -> str:
    """A cost in USD, to the four decimals the drafts state."""
    return f"${value:.4f}"


def _seconds(value: float) -> str:
    """A duration in seconds, to two decimals, with thousands separators."""
    return f"{value:,.2f}"


def _tokens(value: float) -> str:
    """A token count, rounded to a whole token, with thousands separators."""
    return f"{value:,.0f}"


def _attempts(value: float) -> str:
    """A whole number of Writer attempts."""
    return f"{value:.0f}"


def _two_decimals(value: float) -> str:
    """A mean that is not a whole number, such as the mean attempts, to two decimals."""
    return f"{value:.2f}"


def _spread(
    values: list[float], render: Callable[[float], str], render_mean: Callable[[float], str] | None = None
) -> str:
    """``min – max (mean …)`` over ``values``; the one value alone; "n/a" when there is none.

    The mean is rendered by ``render_mean``, or like the values when it is not given.
    """
    if not values:
        return _NOT_APPLICABLE
    if len(values) == 1:
        return render(values[0])
    mean = statistics.fmean(values)
    return f"{render(min(values))} – {render(max(values))} (mean {(render_mean or render)(mean)})"


def _status_counts(drafts: list[DraftRecord]) -> str:
    """How many drafts ended at each QA status, in PASS, WARNING, ERROR order; "n/a" with no drafts."""
    if not drafts:
        return _NOT_APPLICABLE
    return ", ".join(f"{status} {sum(1 for d in drafts if d.qa_status == status)}" for status in _QA_STATUSES)


def _wall_clock_range(runs: list[RunRecord]) -> str:
    """The wall-clock range of the runs that exited 0 with a recorded wall-clock, and how many there were."""
    values = [
        run.wall_clock_seconds
        for run in runs
        if run.exit_code == _SUCCESS_EXIT_CODE and run.wall_clock_seconds is not None
    ]
    if not values:
        return _NOT_APPLICABLE
    if len(values) == 1:
        return f"{_seconds(values[0])} (1 run)"
    return f"{_seconds(min(values))} – {_seconds(max(values))} ({len(values)} runs)"


def _drafts_table(drafts: list[DraftRecord]) -> list[str]:
    """One row per draft, in the order read."""
    if not drafts:
        return ["_No drafts._"]
    return [
        "| Draft | QA status | Attempts | Time (s) | Cost (USD) | Tokens |",
        "| :--- | :--- | ---: | ---: | ---: | ---: |",
        *(
            f"| {d.draft_id} | {d.qa_status} | {d.attempts} | {_seconds(d.time_seconds)} | {_usd(d.cost_usd)} "
            f"| {_tokens(d.total_tokens)} |"
            for d in drafts
        ),
    ]


def _runs_table(runs: list[RunRecord]) -> list[str]:
    """One row per run, whatever its exit code, in the order read."""
    if not runs:
        return ["_No runs recorded._"]
    return [
        "| Log | Run ID | Exit code | Drafts | Failures | Tokens | Cost (USD) | Wall-clock (s) |",
        "| :--- | :--- | :--- | ---: | ---: | ---: | ---: | ---: |",
        *(
            f"| {run.log_file} | {run.run_id or _UNSET_CELL} | {run.exit_code} ({run.exit_name}) | {run.drafts} "
            f"| {run.failures} | {_tokens(run.total_tokens)} | {_usd(run.cost_usd)} "
            f"| {'not recorded' if run.wall_clock_seconds is None else _seconds(run.wall_clock_seconds)} |"
            for run in runs
        ),
    ]


def build_arg_parser() -> argparse.ArgumentParser:
    """Build the parser for ``--a1``, ``--a2`` and ``--out``, and the optional ``--a1-logs`` and ``--a2-logs`` (P15)."""
    parser = argparse.ArgumentParser(
        prog="python -m src.benchmark",
        description="Write the Content Factory vs Research Analyst benchmark report from the drafts and run logs.",
    )
    parser.add_argument("--a1", required=True, metavar="DIR", help="Content Factory (Approach 1) drafts folder.")
    parser.add_argument("--a2", required=True, metavar="DIR", help="Research Analyst (Approach 2) drafts folder.")
    parser.add_argument("--out", required=True, metavar="FILE", help="Where the Markdown report is written.")
    parser.add_argument(
        "--a1-logs", default=None, metavar="DIR", help="Content Factory logs folder (default: <a1 drafts>/../logs)."
    )
    parser.add_argument(
        "--a2-logs", default=None, metavar="DIR", help="Research Analyst logs folder (default: <a2 drafts>/../logs)."
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Read both approaches' drafts and logs, write the report and print one ASCII status line.

    A drafts folder that is missing, or that holds the other approach's drafts, is a usage error: argparse's exit 2,
    before anything is written. A missing logs folder is no runs.

    Args:
        argv: The command-line arguments; ``sys.argv[1:]`` when omitted.

    Returns:
        ``0`` once the report is written.
    """
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    sides: list[ApproachResults] = []
    for approach, drafts_arg, logs_arg, load_runs in (
        (CONTENT_FACTORY, args.a1, args.a1_logs, load_content_factory_runs),
        (RESEARCH_ANALYST, args.a2, args.a2_logs, load_research_analyst_runs),
    ):
        drafts_dir = Path(drafts_arg).resolve()
        logs_dir = Path(logs_arg).resolve() if logs_arg is not None else drafts_dir.parent / "logs"
        try:
            drafts = load_drafts(drafts_dir, approach)
        except BenchmarkError as exc:
            parser.error(f"{approach.label}: {exc}")
        sides.append(
            ApproachResults(
                approach=approach, drafts=drafts, runs=load_runs(logs_dir), drafts_dir=drafts_dir, logs_dir=logs_dir
            )
        )
    content_factory, research_analyst = sides
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_report(content_factory, research_analyst), encoding="utf-8")
    # A console that cannot encode the path, such as a Windows code page, would fail after the report was written.
    shown_out = str(out).encode("ascii", "backslashreplace").decode("ascii")
    print(
        f"Wrote {shown_out}: "
        + "; ".join(f"{side.approach.label} {len(side.drafts)} draft(s), {len(side.runs)} run(s)" for side in sides)
    )
    return 0


def _log_files(logs_dir: Path, pattern: str) -> list[Path]:
    """The files matching ``pattern`` in ``logs_dir``, in name order, which is date order; none if it is absent."""
    return sorted(logs_dir.glob(pattern)) if logs_dir.is_dir() else []


def _search(pattern: re.Pattern[str], text: str, path: Path, bullet: str) -> re.Match[str]:
    """The first match of ``pattern`` in ``text``.

    Raises:
        BenchmarkError: If there is none, naming the file and the bullet.
    """
    match = pattern.search(text)
    if match is None:
        raise BenchmarkError(f"{path.name}: no '{bullet}' bullet in its telemetry section")
    return match


if __name__ == "__main__":
    sys.exit(main())
