"""Scripted end-to-end scenarios over the live local substrate (IMPLEMENTATION_PLAN.md Iteration 15).

SPECIFICATIONS.md D-J: the path is decided at runtime, so every scenario asserts guardrails, persisted outcomes and
log events, never an exact call sequence. Each one drives :func:`src.app.run` once, over one real stdio session with
the local ``hse-easy-mock`` substrate, with a scripted Supervisor and scripted sub-agents (P4: zero tokens). The
Supervisor's choices are its scripted turns alone; nothing in this module decides which tool runs next.

Every scenario checks the exit code, ``RunState.violations`` and ``RunState.failures``, the draft files with their
QA status and attempts, and the D-I events it declares in :data:`_SCENARIO_EVENTS`, read back from the run's log
file at the level the catalogue gives them. :func:`test_every_catalogue_event_is_asserted_by_a_scenario` compares
the catalogue in SPECIFICATIONS.md with the union of those declarations (acceptance criterion 2).

The Supervisor runs at effort ``low`` through ``reasoning_settings``, so the builder tells its model apart from
QA-Legal's, which is also ``gpt-5.4`` at ``medium`` (``tests/test_integration/test_app.py`` pins the defaults).
"""

import functools
import inspect
import json
import re
from collections.abc import AsyncIterator, Iterator, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Final, TypeAlias

import httpx
import openai
import pytest
from strands.models.model import Model

from src.agents import QA_LEGAL_MODEL_ID, SCOUT_MODEL_ID, WRITER_MODEL_ID
from src.app import ClientFactory, run
from src.credentials import CredentialManager, ReasoningSettings
from src.guardrails import QA_TOOL, SAVE_DRAFT_TOOL, SCOUT_TOOL, WRITER_TOOL
from src.logging_setup import configure_logging
from src.mcp_client import HSEMockMCPClient, MCPConnectionError
from src.schemas import ExitCode, PipelineConfig, RunState
from src.supervisor import SUPERVISOR_MODEL_ID
from tests.support.scripted import (
    DEFAULT_DOC_ID,
    FORBIDDEN_SUPERVISOR_KEYS,
    REPO_ROOT,
    SCOPE_DATE_FROM,
    SCOPE_DATE_TO,
    ScriptedModel,
    draft_args,
    json_keys,
    pipeline_config,
    qa_args,
    rendered_total_tokens,
    scout_report_args,
    scripted_model_builder_by_effort,
    text_turn,
    tool_use_turn,
    writer_turns,
)

# ---------------------------------------------------------------------------
# The run every scenario shares
# ---------------------------------------------------------------------------

#: The run's current date, injected through ``clock``; draft IDs are stamped with it, never with the real date.
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
#: The Supervisor's effort in these runs: not QA-Legal's ``medium``, so the two models are built apart.
SUPERVISOR_EFFORT: Final[str] = "low"

#: Real corpus IDs, so the Writer's live ``get_document_by_id`` returns a document rather than an error result.
DOC_A: Final[str] = DEFAULT_DOC_ID  # inail-2024-circ-calore
DOC_B: Final[str] = "inail-2026-ot23"

#: The D-I catalogue the scenarios are checked against: SPECIFICATIONS.md, read where it is written.
SPECIFICATIONS_PATH: Final[Path] = REPO_ROOT / ".agents" / "docs" / "SPECIFICATIONS.md"
#: A run is bounded per scenario (acceptance criterion 1), measured by the run itself on "Run completed".
MAX_WALL_CLOCK_SECONDS: Final[float] = 60.0

#: One scripted model round trip: its stream events, or the exception the model raises instead.
_Turn: TypeAlias = list[dict[str, Any]] | BaseException


# ---------------------------------------------------------------------------
# Scripts: the Supervisor's tool calls and the sub-agents' answers
# ---------------------------------------------------------------------------


def _scout_call(scope: dict[str, Any] = SCOPE) -> list[dict[str, Any]]:
    """A Supervisor turn calling ``scout_tool`` with ``scope``."""
    return tool_use_turn(SCOUT_TOOL, scope)


def _write(doc_id: str, *, revise: bool = False) -> list[dict[str, Any]]:
    """A Supervisor turn calling ``writer_tool`` on ``doc_id``."""
    return tool_use_turn(WRITER_TOOL, {"doc_id": doc_id, "revise": revise})


def _audit(doc_id: str) -> list[dict[str, Any]]:
    """A Supervisor turn calling ``qa_tool`` on ``doc_id``."""
    return tool_use_turn(QA_TOOL, {"doc_id": doc_id})


def _save(doc_id: str) -> list[dict[str, Any]]:
    """A Supervisor turn calling ``save_draft`` on ``doc_id``."""
    return tool_use_turn(SAVE_DRAFT_TOOL, {"doc_id": doc_id})


def _flow(doc_id: str) -> list[list[dict[str, Any]]]:
    """The Supervisor's four calls for one document taken to ``PASS``: scout, write, audit, save."""
    return [_scout_call(), _write(doc_id), _audit(doc_id), _save(doc_id)]


def _scout_finds(*doc_ids: str) -> list[_Turn]:
    """The Scout's script: one live substrate listing, then its report on ``doc_ids``, ranked in that order."""
    return [
        tool_use_turn("list_regulatory_updates", {"source": "INAIL"}),
        tool_use_turn("ScoutReport", scout_report_args(*doc_ids)),
    ]


def _verdict(status: str, *issues: str, notes: str = "") -> list[dict[str, Any]]:
    """A QA-Legal turn issuing ``status`` with ``issues``."""
    return tool_use_turn("QAReport", qa_args(status=status, issues=list(issues) or None, notes=notes))


# ---------------------------------------------------------------------------
# The run log: read back from the file configure_logging writes
# ---------------------------------------------------------------------------

#: A record's header line, in ``src.logging_setup``'s format; any other line continues the record above it.
_HEADER: Final[re.Pattern[str]] = re.compile(
    r"^(\S+ \S+) (DEBUG|INFO|WARNING|ERROR|CRITICAL)\s+\[run_id=(\S+) doc_id=(\S+) attempt=(\S+)\] (\S+): (.*)$"
)


@dataclass(frozen=True)
class _LogLine:
    """One record of the run log: its header fields, its message, the lines beneath it (a traceback, say), and its
    position among the log's records, so two records with identical text are still told apart."""

    level: str
    run_id: str
    doc_id: str
    attempt: str
    logger: str
    message: str
    continuation: str
    position: int


def _read_log(log_dir: Path) -> tuple[_LogLine, ...]:
    """Parse the one run log in ``log_dir``.

    The file is named by the real date (``logging_setup``), not the injected clock, so it is found by pattern.
    """
    [log_file] = sorted(log_dir.glob("run_*.log"))
    records: list[_LogLine] = []
    header: tuple[str, ...] | None = None
    continuation: list[str] = []
    for raw in log_file.read_text(encoding="utf-8").splitlines():
        match = _HEADER.match(raw)
        if match is None:
            continuation.append(raw)
            continue
        if header is not None:
            records.append(_LogLine(*header, continuation="\n".join(continuation), position=len(records)))
        header, continuation = match.groups()[1:], []
    if header is not None:
        records.append(_LogLine(*header, continuation="\n".join(continuation), position=len(records)))
    return tuple(records)


@pytest.fixture(autouse=True)
def _run_log(tmp_path: Path, restore_logging: None) -> None:
    """Route the run's loggers to ``tmp_path``'s log file, as ``cli.main`` does; ``restore_logging`` undoes it.

    ``run`` configures no logging of its own, and the routed loggers stop propagating, so ``caplog`` sees nothing:
    the file is the only record, which is the point of reading it.
    """
    configure_logging("INFO", pipeline_config(tmp_path).log_dir)


# ---------------------------------------------------------------------------
# Running one scenario
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Run:
    """One scripted run: its result, each role's scripted model, and the log it wrote."""

    state: RunState
    supervisor: ScriptedModel
    scout: ScriptedModel
    writer: ScriptedModel
    qa_legal: ScriptedModel
    lines: tuple[_LogLine, ...]

    def events(self, prefix: str) -> list[_LogLine]:
        """The records whose message opens with ``prefix``, in log order."""
        return [line for line in self.lines if line.message.startswith(prefix)]

    def index(self, line: _LogLine) -> int:
        """Where ``line`` sits in the log, to compare the order of two events: the position recorded when the log
        was parsed, never a lookup by value, so a record identical to an earlier one keeps its own place."""
        return line.position


def _field(line: _LogLine, name: str) -> str:
    """The value of one ``name=value`` field of a log message."""
    match = re.search(rf"(?:^|\s){re.escape(name)}=(\S+)", line.message)
    assert match is not None, f"no {name}= field in {line.message!r}"
    return match.group(1)


def _run(
    tmp_path: Path,
    *,
    supervisor: Sequence[_Turn] | ScriptedModel,
    scout: Sequence[_Turn] = (),
    writer: Sequence[_Turn] = (),
    qa_legal: Sequence[_Turn] = (),
    config: PipelineConfig | None = None,
    client_factory: ClientFactory = HSEMockMCPClient,
) -> _Run:
    """Run ``run`` once over the live local substrate, with each role on its own scripted model."""
    supervisor_model = supervisor if isinstance(supervisor, ScriptedModel) else ScriptedModel(supervisor)
    scout_model, writer_model, qa_model = ScriptedModel(scout), ScriptedModel(writer), ScriptedModel(qa_legal)
    config = config if config is not None else pipeline_config(tmp_path)
    state = run(
        PROMPT,
        config,
        client_factory=client_factory,
        model_builder=scripted_model_builder_by_effort(
            {
                (SCOUT_MODEL_ID, None): scout_model,
                (WRITER_MODEL_ID, "high"): writer_model,
                (QA_LEGAL_MODEL_ID, "medium"): qa_model,
                (SUPERVISOR_MODEL_ID, SUPERVISOR_EFFORT): supervisor_model,
            }
        ),
        clock=lambda: TODAY,
        reasoning_settings=ReasoningSettings(HSE_MODEL_SUPERVISOR_REASONING_EFFORT=SUPERVISOR_EFFORT),
    )
    return _Run(state, supervisor_model, scout_model, writer_model, qa_model, _read_log(config.log_dir))


# ---------------------------------------------------------------------------
# What every scenario checks
# ---------------------------------------------------------------------------


def _failures(state: RunState) -> list[tuple[str, str | None, int | None]]:
    """Each failure the run recorded, as ``(stage, doc_id, attempt)``, in order."""
    return [(failure.stage, failure.doc_id, failure.attempt) for failure in state.failures]


def _violations(state: RunState) -> list[tuple[str, str, str | None]]:
    """Each guardrail violation the run stored, as ``(guardrail, tool, doc_id)``, in order."""
    return [(violation.guardrail, violation.tool_name, violation.doc_id) for violation in state.violations]


def _drafts(state: RunState) -> list[Path]:
    """The draft files in the run's drafts folder, by name."""
    drafts_dir = state.config.drafts_dir
    return sorted(drafts_dir.glob("draft_*.md")) if drafts_dir.is_dir() else []


def _draft_id(sequence: int) -> str:
    """The draft ID of ``sequence`` on the run's date."""
    return f"draft_{TODAY:%Y%m%d}_{sequence:03d}"


def _review_field(text: str, label: str) -> str:
    """The value of one bullet of a rendered draft's QA-Legal section, ``* **<label>:** <value>``."""
    match = re.search(rf"^\* \*\*{re.escape(label)}:\*\* (.*)$", text, flags=re.MULTILINE)
    assert match is not None, f"the draft has no {label!r} line"
    return match.group(1).strip()


def _assert_draft(path: Path, *, status: str, attempts: int) -> str:
    """The draft at ``path`` carries ``status`` and ``attempts``; returns its text."""
    text = path.read_text(encoding="utf-8")
    assert _review_field(text, "Status") == status
    assert _review_field(text, "Revision Attempts") == str(attempts)
    return text


def _assert_run_completed(result: _Run) -> _LogLine:
    """One "Run completed", the authoritative exit code, under the wall-clock bound; every line carries the run."""
    state = result.state
    code = state.exit_code
    assert code is not None
    [completed] = result.events("Run completed:")
    assert f"exit_code={int(code)} ({code.name})" in completed.message
    assert _field(completed, "violations") == str(len(state.violations))
    assert _field(completed, "failures") == str(len(state.failures))
    wall_clock = re.search(r"wall_clock=(\d+\.\d+)s", completed.message)
    assert wall_clock is not None and float(wall_clock.group(1)) < MAX_WALL_CLOCK_SECONDS
    assert {line.run_id for line in result.lines if line.logger.startswith("src.")} == {state.run_id}
    return completed


def _assert_consumed(result: _Run, **expected: int) -> None:
    """Each role's scripted model replayed exactly ``expected[role]`` turns; a role not named replayed none."""
    consumed = {
        role: getattr(result, role).turns_consumed for role in ("supervisor", "scout", "writer", "qa_legal")
    }
    assert consumed == {role: expected.get(role, 0) for role in consumed}


def _completed_total_tokens(completed: _LogLine) -> int:
    """The run total "Run completed" logs (P12)."""
    match = re.search(r" total_tokens=(\d+) ", completed.message)
    assert match is not None
    return int(match.group(1))


def _assert_tokens_add_up(result: _Run, completed: _LogLine) -> None:
    """Gate 5: the drafts' tokens plus the unsaved documents' own tokens are the run total, logged and ledgered."""
    state = result.state
    unsaved = {doc_id for doc_id, document in state.documents.items() if document.saved is None}
    unsaved_tokens = sum(entry.telemetry.total_tokens for entry in state.ledger if entry.doc_id in unsaved)
    drafted_tokens = sum(rendered_total_tokens(path.read_text(encoding="utf-8")) for path in _drafts(state))
    ledger_tokens = sum(entry.telemetry.total_tokens for entry in state.ledger)
    assert drafted_tokens + unsaved_tokens == _completed_total_tokens(completed) == ledger_tokens


def _tool_results(messages: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every tool result in a message history, in order, its JSON text parsed: what each tool returned.

    Paired by position, never by ``toolUseId``: every scripted turn names its call ``<tool>-1``.
    """
    return [
        json.loads(item["text"])
        for message in messages
        for block in message.get("content", [])
        if "toolResult" in block
        for item in block["toolResult"]["content"]
        if "text" in item
    ]


# ---------------------------------------------------------------------------
# The D-I event catalogue (acceptance criterion 2)
# ---------------------------------------------------------------------------


def _prefix(text: str) -> re.Pattern[str]:
    """A pattern matching a message that opens with ``text``, literally."""
    return re.compile(re.escape(text))


#: How each catalogue event is recognised in the log: every pattern must match at least one message. Keyed by the
#: catalogue's own event names, backticks stripped. "Draft rendered:" keeps its colon, so the banner line, which
#: opens "Draft rendered with", is not mistaken for it. "Model HTTP call" is the hook half only: a scripted model
#: makes no HTTP request, so the ``httpx`` half of the event cannot appear in a zero-token run (P4).
_CATALOGUE_PATTERNS: Final[dict[str, tuple[re.Pattern[str], ...]]] = {
    "Run started": (_prefix("Run started: "),),
    "MCP session opened": (_prefix("MCP session opened: "),),
    "Scope built by the Supervisor": (_prefix("Scope built by the Supervisor: "),),
    "Supervisor turn completed": (_prefix("Supervisor turn completed: "),),
    "Model HTTP call": (_prefix("Model HTTP call: "),),
    "Tool call started / completed": (_prefix("Tool call started: "), _prefix("Tool call completed: ")),
    "Sub-agent invocation started / completed": (
        _prefix("Sub-agent invocation started: "),
        _prefix("Sub-agent invocation completed: "),
        _prefix("Supervisor invocation started: "),
        _prefix("Supervisor invocation completed: "),
    ),
    "Scout result": (_prefix("Scout result: "),),
    "QA verdict PASS": (_prefix("QA verdict PASS: "),),
    "Revision requested": (_prefix("Revision requested: "),),
    "Document marked saved": (_prefix("Document marked saved: "),),
    "Draft rendered (run end)": (_prefix("Draft rendered: "),),
    "Run completed": (_prefix("Run completed: "),),
    "QA verdict WARNING or ERROR": (re.compile(r"QA verdict (WARNING|ERROR): "),),
    "Draft rendered with [UNRESOLVED COMPLIANCE ALERT]": (
        _prefix("Draft rendered with [UNRESOLVED COMPLIANCE ALERT]: "),
    ),
    "Guardrail violation": (_prefix("Guardrail violation: "),),
    "Recoverable tool failure returned to the Supervisor": (
        _prefix("Recoverable tool failure returned to the Supervisor: "),
    ),
    "Candidate left unsaved at run end": (_prefix("Candidate left unsaved at run end: "),),
    "Configuration failure": (_prefix("Configuration failure: "),),
    "MCP session failed to open, or died mid-run": (_prefix("MCP session failed to open, or died mid-run: "),),
    "Supervisor invocation failed (provider or SDK error)": (_prefix("Supervisor invocation failed: "),),
    "Draft render or write failure": (_prefix("Draft render or write failure: "),),
    "Fatal abort triggered (D-D)": (_prefix("Fatal abort triggered (D-D): "),),
}

#: The run's bracketing events, which every scenario asserts.
_EVERY_RUN: Final[frozenset[str]] = frozenset({"Run started", "Run completed"})

#: The catalogue events each scenario asserts, keyed by the scenario's test-name prefix (``test_<key>_…``). Static,
#: so the coverage test does not depend on which scenarios ran, or in what order.
_SCENARIO_EVENTS: Final[dict[str, frozenset[str]]] = {
    "s01": _EVERY_RUN
    | {
        "MCP session opened",
        "Scope built by the Supervisor",
        "Supervisor turn completed",
        "Model HTTP call",
        "Tool call started / completed",
        "Sub-agent invocation started / completed",
        "Scout result",
        "QA verdict PASS",
        "Document marked saved",
        "Draft rendered (run end)",
    },
    "s02": _EVERY_RUN
    | {"QA verdict WARNING or ERROR", "Revision requested", "Draft rendered with [UNRESOLVED COMPLIANCE ALERT]"},
    "s03": _EVERY_RUN | {"QA verdict WARNING or ERROR", "Revision requested", "QA verdict PASS"},
    "s04": _EVERY_RUN | {"QA verdict WARNING or ERROR", "Document marked saved"},
    "s05": _EVERY_RUN | {"Recoverable tool failure returned to the Supervisor", "QA verdict PASS"},
    "s06": _EVERY_RUN | {"Recoverable tool failure returned to the Supervisor", "QA verdict WARNING or ERROR"},
    "s07": _EVERY_RUN | {"Recoverable tool failure returned to the Supervisor", "Candidate left unsaved at run end"},
    "s08": _EVERY_RUN | {"Guardrail violation", "Candidate left unsaved at run end", "Revision requested"},
    "s09": _EVERY_RUN | {"Guardrail violation", "Scout result"},
    "s10": _EVERY_RUN
    | {
        "MCP session failed to open, or died mid-run",
        "Fatal abort triggered (D-D)",
        "Tool call started / completed",
        "Draft rendered (run end)",
        "Candidate left unsaved at run end",
    },
    "s11": _EVERY_RUN
    | {"Supervisor invocation failed (provider or SDK error)", "Model HTTP call", "Draft rendered (run end)"},
    "s12": _EVERY_RUN | {"Scout result", "Scope built by the Supervisor"},
    "s13a": _EVERY_RUN | {"MCP session opened", "Supervisor turn completed"},
    "s13b": _EVERY_RUN | {"Guardrail violation", "Scope built by the Supervisor", "Draft rendered (run end)"},
    "s14": _EVERY_RUN | {"Document marked saved", "Draft rendered (run end)"},
    "s15": _EVERY_RUN
    | {"Revision requested", "Recoverable tool failure returned to the Supervisor", "Guardrail violation"},
    "x01": _EVERY_RUN | {"Configuration failure"},
    "x02": _EVERY_RUN | {"Draft render or write failure", "Document marked saved"},
}


@functools.cache
def _catalogue() -> dict[str, str]:
    """The D-I event catalogue as ``{event: level}``, parsed from SPECIFICATIONS.md, backticks stripped from names."""
    text = SPECIFICATIONS_PATH.read_text(encoding="utf-8")
    section = text.split("**Event catalogue:**", 1)[1].split("#### D-J.", 1)[0]
    rows = [
        [cell.strip() for cell in line.strip().strip("|").split("|")]
        for line in section.splitlines()
        if line.startswith("|")
    ]
    return {cells[1].replace("`", ""): cells[0].strip("*") for cells in rows[2:]}


def _assert_events(result: _Run, scenario: str) -> None:
    """Every event ``scenario`` declares is in the log, and every line of it is at the catalogue's level."""
    catalogue = _catalogue()
    for event in sorted(_SCENARIO_EVENTS[scenario]):
        for pattern in _CATALOGUE_PATTERNS[event]:
            matching = [line for line in result.lines if pattern.match(line.message)]
            assert matching, f"{scenario}: no {event!r} line matches {pattern.pattern!r}"
            assert {line.level for line in matching} == {catalogue[event]}, f"{scenario}: {event!r} level"


# ---------------------------------------------------------------------------
# Scenario 1: the happy path
# ---------------------------------------------------------------------------


def test_s01_two_candidates_pass_at_attempt_one_and_their_tokens_add_up(tmp_path: Path) -> None:
    """Two drafts in save order; exit 0; the drafts' tokens plus the unsaved tokens (none here) are the run total."""
    result = _run(
        tmp_path,
        supervisor=[*_flow(DOC_A), *_flow(DOC_B)[1:], text_turn("Saved both candidates.")],
        scout=_scout_finds(DOC_A, DOC_B),
        writer=[*writer_turns(DOC_A), *writer_turns(DOC_B)],
        qa_legal=[_verdict("PASS"), _verdict("PASS")],
    )

    state = result.state
    assert state.exit_code is ExitCode.SUCCESS
    assert _failures(state) == [] and _violations(state) == []
    drafts = _drafts(state)
    assert [path.name for path in drafts] == [f"{_draft_id(1)}.md", f"{_draft_id(2)}.md"]
    for path, doc_id in zip(drafts, (DOC_A, DOC_B), strict=True):
        _assert_draft(path, status="PASS", attempts=1)
        assert state.documents[doc_id].saved is not None and state.documents[doc_id].saved.path == path
    _assert_consumed(result, supervisor=8, scout=2, writer=4, qa_legal=2)
    completed = _assert_run_completed(result)
    _assert_tokens_add_up(result, completed)
    _assert_events(result, "s01")
    [opened] = result.events("MCP session opened:")
    assert opened.message.endswith("tools=5")
    assert len(result.events("Supervisor turn completed:")) == result.supervisor.turns_consumed
    assert result.events("Tool call completed: tool=get_document_by_id agent=writer")
    assert [line.doc_id for line in result.events("Draft rendered:")] == [DOC_A, DOC_B]


# ---------------------------------------------------------------------------
# Scenarios 2 to 7: code handles each decision-table path (D-C); the Supervisor's choices are scripted
# ---------------------------------------------------------------------------

#: An issue saying a statement in the article is wrong: the decision table's "Revise" condition for a WARNING.
SUBSTANTIVE_ISSUE: Final[str] = "The deadline stated in the article is wrong: the circular applies from 24 July 2024."
#: An issue that asks for no change: the decision table's "Save" condition for a WARNING.
ADVISORY_ISSUE: Final[str] = "Optional: a reference to the INAIL heat-stress guidance could be added."
#: The issue an ERROR audit keeps raising.
ERROR_ISSUE: Final[str] = "The penalty cited for employers does not match D.Lgs. 81/2008."


def test_s02_error_three_times_is_saved_at_the_cap_with_the_compliance_banner(tmp_path: Path) -> None:
    """ERROR with attempts left is revised; ERROR at the cap is saved, and its draft carries the banner (rule 9)."""
    result = _run(
        tmp_path,
        supervisor=[
            _scout_call(),
            _write(DOC_A),
            _audit(DOC_A),
            _write(DOC_A, revise=True),
            _audit(DOC_A),
            _write(DOC_A, revise=True),
            _audit(DOC_A),
            _save(DOC_A),
            text_turn("Saved with an unresolved compliance alert at the attempt cap."),
        ],
        scout=_scout_finds(DOC_A),
        writer=[*writer_turns(DOC_A), *writer_turns(DOC_A), *writer_turns(DOC_A)],
        qa_legal=[_verdict("ERROR", ERROR_ISSUE) for _ in range(3)],
    )

    state = result.state
    assert state.exit_code is ExitCode.SUCCESS
    assert _failures(state) == [] and _violations(state) == []
    [draft] = _drafts(state)
    text = _assert_draft(draft, status="ERROR", attempts=3)
    assert "[UNRESOLVED COMPLIANCE ALERT]" in text
    _assert_consumed(result, supervisor=9, scout=2, writer=6, qa_legal=3)
    _assert_run_completed(result)
    _assert_events(result, "s02")
    revisions = result.events("Revision requested:")
    assert [(line.attempt, _field(line, "follows")) for line in revisions] == [("2", "ERROR"), ("3", "ERROR")]
    [banner] = result.events("Draft rendered with [UNRESOLVED COMPLIANCE ALERT]:")
    assert banner.doc_id == DOC_A and "attempts_used=3" in banner.message and ERROR_ISSUE in banner.message


def test_s03_a_substantive_warning_is_revised_and_the_revision_passes(tmp_path: Path) -> None:
    """WARNING with an issue saying a statement is wrong → revise → PASS → save; the revision follows the WARNING."""
    result = _run(
        tmp_path,
        supervisor=[
            _scout_call(),
            _write(DOC_A),
            _audit(DOC_A),
            _write(DOC_A, revise=True),
            _audit(DOC_A),
            _save(DOC_A),
            text_turn("Saved after one revision."),
        ],
        scout=_scout_finds(DOC_A),
        writer=[*writer_turns(DOC_A), *writer_turns(DOC_A)],
        qa_legal=[_verdict("WARNING", SUBSTANTIVE_ISSUE), _verdict("PASS")],
    )

    state = result.state
    assert state.exit_code is ExitCode.SUCCESS
    assert _failures(state) == [] and _violations(state) == []
    [draft] = _drafts(state)
    _assert_draft(draft, status="PASS", attempts=2)
    _assert_consumed(result, supervisor=7, scout=2, writer=4, qa_legal=2)
    _assert_run_completed(result)
    _assert_events(result, "s03")
    [warning] = result.events("QA verdict WARNING:")
    [revision] = result.events("Revision requested:")
    assert (warning.doc_id, warning.attempt) == (DOC_A, "1") and SUBSTANTIVE_ISSUE in warning.message
    assert "attempt=2 follows=WARNING" in revision.message
    assert result.index(warning) < result.index(revision)


def test_s04_an_advisory_warning_is_saved_at_attempt_one(tmp_path: Path) -> None:
    """WARNING whose issues ask for no change → save: one attempt, saved as WARNING, and no revision requested."""
    result = _run(
        tmp_path,
        supervisor=[*_flow(DOC_A), text_turn("Saved with an advisory warning.")],
        scout=_scout_finds(DOC_A),
        writer=writer_turns(DOC_A),
        qa_legal=[_verdict("WARNING", ADVISORY_ISSUE)],
    )

    state = result.state
    assert state.exit_code is ExitCode.SUCCESS
    assert _failures(state) == [] and _violations(state) == []
    [draft] = _drafts(state)
    _assert_draft(draft, status="WARNING", attempts=1)
    _assert_consumed(result, supervisor=5, scout=2, writer=2, qa_legal=1)
    _assert_run_completed(result)
    _assert_events(result, "s04")
    assert result.events("Revision requested:") == []
    [saved] = result.events("Document marked saved:")
    assert "qa_status=WARNING attempts=1" in saved.message


def _writer_failure(attempt: int) -> RuntimeError:
    """A Writer provider failure for one attempt: recoverable, since no lost session is in its chain."""
    return RuntimeError(f"writer provider unavailable on attempt {attempt}")


def test_s05_a_writer_failure_with_no_draft_is_retried_and_the_retry_passes(tmp_path: Path) -> None:
    """Writer failed, no draft yet → retry ``revise=false``: the failure is attempt 1; the draft saved, attempt 2."""
    result = _run(
        tmp_path,
        supervisor=[
            _scout_call(),
            _write(DOC_A),
            _write(DOC_A),
            _audit(DOC_A),
            _save(DOC_A),
            text_turn("Saved after retrying the failed first draft."),
        ],
        scout=_scout_finds(DOC_A),
        writer=[_writer_failure(1), *writer_turns(DOC_A)],
        qa_legal=[_verdict("PASS")],
    )

    state = result.state
    assert state.exit_code is ExitCode.SUCCESS
    assert _failures(state) == [("writer", DOC_A, 1)]
    assert _violations(state) == []  # the retry is not initial_draft_exists: the failed call left no draft
    [draft] = _drafts(state)
    _assert_draft(draft, status="PASS", attempts=2)
    _assert_consumed(result, supervisor=6, scout=2, writer=3, qa_legal=1)
    _assert_run_completed(result)
    _assert_events(result, "s05")
    [failure] = result.events("Recoverable tool failure returned to the Supervisor:")
    assert (failure.doc_id, failure.attempt) == (DOC_A, "1") and f"tool={WRITER_TOOL}" in failure.message
    assert "RuntimeError: writer provider unavailable on attempt 1" in failure.continuation


def test_s06_a_failed_revision_leaves_the_earlier_draft_which_is_saved(tmp_path: Path) -> None:
    """Writer failed with an earlier draft: the table applies to that draft's report; attempt 1's text is rendered."""
    first = draft_args(DOC_A, headline="Prima stesura: obblighi contro lo stress termico", article_body="Corpo A1.")
    rejected = draft_args(DOC_A, headline="Revisione respinta: mai verificata", article_body="Corpo respinto A2.")
    result = _run(
        tmp_path,
        supervisor=[
            _scout_call(),
            _write(DOC_A),
            _audit(DOC_A),
            _write(DOC_A, revise=True),
            _save(DOC_A),
            text_turn("The revision failed; saved the audited first draft."),
        ],
        scout=_scout_finds(DOC_A),
        # The revision skips the mandatory fetch, so writer_tool rejects it (D-C rule 2) and keeps no draft.
        writer=[*writer_turns(DOC_A, draft=first), tool_use_turn("ArticleDraft", rejected)],
        qa_legal=[_verdict("WARNING", SUBSTANTIVE_ISSUE)],
    )

    state = result.state
    assert state.exit_code is ExitCode.SUCCESS
    assert _failures(state) == [("fetch_document", DOC_A, 2)]
    assert _violations(state) == []
    [draft] = _drafts(state)
    text = _assert_draft(draft, status="WARNING", attempts=2)
    assert first["headline"] in text and first["article_body"] in text
    assert rejected["headline"] not in text and rejected["article_body"] not in text
    _assert_consumed(result, supervisor=6, scout=2, writer=3, qa_legal=1)
    _assert_run_completed(result)
    _assert_events(result, "s06")
    [failure] = result.events("Recoverable tool failure returned to the Supervisor:")
    assert (failure.doc_id, failure.attempt) == (DOC_A, "2")
    assert "WriterSourceFetchError" in failure.continuation


def test_s07_a_writer_that_fails_three_times_leaves_the_candidate_unsaved(tmp_path: Path) -> None:
    """Writer failed, no draft, no attempt left → skip: no draft, and the candidate is logged as left unsaved."""
    result = _run(
        tmp_path,
        supervisor=[_scout_call(), _write(DOC_A), _write(DOC_A), _write(DOC_A), text_turn("Skipped: three failures.")],
        scout=_scout_finds(DOC_A),
        writer=[_writer_failure(1), _writer_failure(2), _writer_failure(3)],
    )

    state = result.state
    assert state.exit_code is ExitCode.SUCCESS
    assert _failures(state) == [("writer", DOC_A, 1), ("writer", DOC_A, 2), ("writer", DOC_A, 3)]
    assert _violations(state) == []
    assert _drafts(state) == []
    _assert_consumed(result, supervisor=5, scout=2, writer=3)
    _assert_run_completed(result)
    _assert_events(result, "s07")
    assert [line.attempt for line in result.events("Recoverable tool failure returned to the Supervisor:")] == [
        "1",
        "2",
        "3",
    ]
    [unsaved] = result.events("Candidate left unsaved at run end:")
    assert unsaved.doc_id == DOC_A and unsaved.message.endswith("last_state=not_drafted")


# ---------------------------------------------------------------------------
# Scenarios 8 and 9: guardrails refuse, and the run goes on (D-C, DM16)
# ---------------------------------------------------------------------------

#: A ``doc_id`` the Scout never returned.
NOT_A_CANDIDATE: Final[str] = "not-a-candidate"


def test_s08_each_violation_is_returned_logged_and_stored_and_the_run_exits_success(tmp_path: Path) -> None:
    """Re-audit, revise a PASS, restart a draft, a non-candidate, work after a save (P2), save an ERROR with attempts
    left, and the ``--max-drafts`` ceiling: each refused call is returned, logged at WARNING and stored."""
    result = _run(
        tmp_path,
        supervisor=[
            _scout_call(),
            _write(DOC_A),
            _audit(DOC_A),
            _audit(DOC_A),  # already_audited
            _write(DOC_A, revise=True),  # revise_after_pass
            _write(DOC_A),  # initial_draft_exists
            _write(NOT_A_CANDIDATE),  # not_a_candidate
            _save(DOC_A),
            _write(DOC_A, revise=True),  # already_saved (P2)
            _write(DOC_B),
            _audit(DOC_B),
            _save(DOC_B),  # error_with_attempts_remaining
            _write(DOC_B, revise=True),
            _audit(DOC_B),
            _save(DOC_B),  # draft_ceiling
            text_turn("Saved one document; the ceiling refused the second."),
        ],
        scout=_scout_finds(DOC_A, DOC_B),
        writer=[*writer_turns(DOC_A), *writer_turns(DOC_B), *writer_turns(DOC_B)],
        qa_legal=[_verdict("PASS"), _verdict("ERROR", ERROR_ISSUE), _verdict("PASS")],
        config=pipeline_config(tmp_path, max_drafts=1),
    )

    state = result.state
    expected = [
        ("already_audited", QA_TOOL, DOC_A),
        ("revise_after_pass", WRITER_TOOL, DOC_A),
        ("initial_draft_exists", WRITER_TOOL, DOC_A),
        ("not_a_candidate", WRITER_TOOL, NOT_A_CANDIDATE),
        ("already_saved", WRITER_TOOL, DOC_A),
        ("error_with_attempts_remaining", SAVE_DRAFT_TOOL, DOC_B),
        ("draft_ceiling", SAVE_DRAFT_TOOL, DOC_B),
    ]
    assert state.exit_code is ExitCode.SUCCESS
    assert _violations(state) == expected  # stored
    assert _failures(state) == []
    [draft] = _drafts(state)
    _assert_draft(draft, status="PASS", attempts=1)
    _assert_consumed(result, supervisor=16, scout=2, writer=6, qa_legal=3)
    completed = _assert_run_completed(result)
    _assert_tokens_add_up(result, completed)  # B's own Writer and QA-Legal tokens are the unsaved term
    _assert_events(result, "s08")
    # Returned: the refused call's result is empty and its error names the guardrail.
    refusals = [payload for payload in _tool_results(result.supervisor.received_messages[-1]) if payload["error"]]
    assert [(payload["result"], payload["error"]["guardrail"]) for payload in refusals] == [
        (None, guardrail) for guardrail, _, _ in expected
    ]
    # Logged at WARNING, each on the line of the document it refused.
    logged = result.events("Guardrail violation:")
    assert [(line.level, line.doc_id) for line in logged] == [("WARNING", doc_id) for _, _, doc_id in expected]
    for line, (guardrail, tool_name, _) in zip(logged, expected, strict=True):
        assert line.message.startswith(f"Guardrail violation: guardrail={guardrail} tool={tool_name} ")
    [unsaved] = result.events("Candidate left unsaved at run end:")
    assert unsaved.doc_id == DOC_B and unsaved.message.endswith("last_state=audited")


def test_s09_the_same_violation_five_times_is_logged_and_stored_every_time(tmp_path: Path) -> None:
    """DM16: no bound on repeated violations. Five more Scout calls are five ``scout_already_run``; the run goes on."""
    repeats = 5
    result = _run(
        tmp_path,
        supervisor=[
            *(_scout_call() for _ in range(1 + repeats)),
            text_turn("The Scout had already run; nothing drafted."),
        ],
        scout=_scout_finds(DOC_A),
    )

    state = result.state
    assert state.exit_code is ExitCode.SUCCESS
    assert _violations(state) == [("scout_already_run", SCOUT_TOOL, None)] * repeats
    assert _failures(state) == []
    assert _drafts(state) == []
    _assert_consumed(result, supervisor=2 + repeats, scout=2)  # the run went on to its final turn
    completed = _assert_run_completed(result)
    assert _field(completed, "violations") == str(repeats)
    _assert_events(result, "s09")
    logged = result.events("Guardrail violation:")
    assert [(line.level, _field(line, "guardrail")) for line in logged] == [("WARNING", "scout_already_run")] * repeats


# ---------------------------------------------------------------------------
# Scenarios 10 and 11: the run ends early, and what was saved is still rendered (D-D, §6.10)
# ---------------------------------------------------------------------------


class _SessionKillingSupervisor(ScriptedModel):
    """A scripted Supervisor that stops the run's real substrate session just before it replays one of its turns.

    The kill is keyed on the Supervisor's own turn index, never on substrate listings: it ends the real subprocess
    under the client, so the next sub-agent build's tool listing finds the session gone, the dead-transport surface
    of §8.4. The client's own ``with`` still closes cleanly afterwards.

    Args:
        turns: The Supervisor's script.
        clients: Filled by the run's client factory with the one client it opens.
        kill_before: The index of the turn before which the session is stopped.
    """

    def __init__(self, turns: Sequence[_Turn], *, clients: list[HSEMockMCPClient], kill_before: int) -> None:
        super().__init__(turns)
        self._clients = clients
        self._kill_before = kill_before

    async def stream(
        self, messages: Any, tool_specs: Any = None, system_prompt: str | None = None, **kwargs: Any
    ) -> AsyncIterator[dict[str, Any]]:
        """Stop the session first if this is the chosen turn, then replay it as a ``ScriptedModel`` does."""
        if self.turns_consumed == self._kill_before:
            [client] = self._clients
            client.mcp_client.stop(None, None, None)
        async for event in super().stream(messages, tool_specs, system_prompt, **kwargs):
            yield event


def test_s10_a_transport_that_dies_after_one_save_exits_mcp_error_and_renders_the_save(tmp_path: Path) -> None:
    """D-D: the second Writer finds the session gone; the fatal stop ends the Supervisor with no further model call."""
    clients: list[HSEMockMCPClient] = []

    def capturing_factory() -> HSEMockMCPClient:
        client = HSEMockMCPClient()
        clients.append(client)
        return client

    script: list[_Turn] = [*_flow(DOC_A), _write(DOC_B), text_turn("must not be reached")]
    result = _run(
        tmp_path,
        supervisor=_SessionKillingSupervisor(script, clients=clients, kill_before=4),
        scout=_scout_finds(DOC_A, DOC_B),
        writer=writer_turns(DOC_A),
        qa_legal=[_verdict("PASS")],
        client_factory=capturing_factory,
    )

    state = result.state
    assert state.exit_code is ExitCode.MCP_ERROR
    assert isinstance(state.fatal_error, MCPConnectionError)
    assert _failures(state) == [("mcp_session", DOC_B, 1)]
    assert _violations(state) == []
    assert state.supervisor_summary == ""
    [draft] = _drafts(state)
    _assert_draft(draft, status="PASS", attempts=1)
    _assert_consumed(result, supervisor=5, scout=2, writer=2, qa_legal=1)  # the final turn is never requested
    completed = _assert_run_completed(result)
    assert "summary=''" in completed.message
    _assert_events(result, "s10")
    [lost] = result.events("MCP session failed to open, or died mid-run:")
    assert (lost.level, lost.logger, lost.doc_id) == ("ERROR", "src.tools", DOC_B)
    assert f"tool={WRITER_TOOL}" in lost.message
    [abort] = result.events("Fatal abort triggered (D-D):")
    fatal_tool = result.events(f"Tool call completed: tool={WRITER_TOOL} agent=supervisor")[-1]
    assert fatal_tool.doc_id == DOC_B
    assert f"tool={WRITER_TOOL}" in abort.message
    assert result.index(abort) < result.index(fatal_tool)  # the hook fires before the logging hook's completion
    # No model call after the fatal tool: the Supervisor's last model call precedes the abort.
    supervisor_calls = result.events("Model HTTP call: agent=supervisor")
    assert len(supervisor_calls) == 5 and result.index(supervisor_calls[-1]) < result.index(abort)
    [unsaved] = result.events("Candidate left unsaved at run end:")
    assert unsaved.doc_id == DOC_B and unsaved.message.endswith("last_state=not_drafted")


#: The provider's request ID on the scripted 429, which the logged ``RemoteErrorDetail`` must carry.
REQUEST_ID: Final[str] = "req_e2e_429"


def _rate_limit_error() -> openai.RateLimitError:
    """A genuine ``openai.RateLimitError`` on a real 429 response, as ``tests/test_unit/test_diagnostics.py`` builds.

    Never Strands' ``ModelThrottledException``: its retry strategy would retry it, with seconds of back-off.
    """
    body: dict[str, object] = {"message": "Rate limit reached for gpt-5.4.", "type": "rate_limit_error"}
    request = httpx.Request("POST", "https://strong.example.invalid/openai/v1/chat/completions")
    response = httpx.Response(429, request=request, headers={"x-request-id": REQUEST_ID}, json={"error": body})
    return openai.RateLimitError(str(body["message"]), response=response, body=body)


def test_s11_a_provider_error_after_one_save_exits_supervisor_error_and_renders_the_save(tmp_path: Path) -> None:
    """The Supervisor's provider fails on the turn after the save: exit 6, the save rendered, the error in full."""
    result = _run(
        tmp_path,
        supervisor=[*_flow(DOC_A), _rate_limit_error()],
        scout=_scout_finds(DOC_A),
        writer=writer_turns(DOC_A),
        qa_legal=[_verdict("PASS")],
    )

    state = result.state
    assert state.exit_code is ExitCode.SUPERVISOR_ERROR
    assert state.supervisor_summary is None
    assert _failures(state) == [("supervisor", None, None)]
    assert _violations(state) == []
    [draft] = _drafts(state)
    _assert_draft(draft, status="PASS", attempts=1)
    _assert_consumed(result, supervisor=5, scout=2, writer=2, qa_legal=1)
    completed = _assert_run_completed(result)
    assert completed.message.endswith("summary=None")
    _assert_events(result, "s11")
    [failed] = result.events("Supervisor invocation failed:")
    remote = json.loads(failed.message.split(" remote=", 1)[1])
    assert (remote["status_code"], remote["request_id"]) == (429, REQUEST_ID)
    assert "openai.RateLimitError: Rate limit reached for gpt-5.4." in failed.continuation  # the traceback
    assert result.events("Model HTTP call: agent=supervisor outcome=error:openai.RateLimitError")


# ---------------------------------------------------------------------------
# Scenarios 12 and 13: the run ends with nothing to draft (§7.6, P13)
# ---------------------------------------------------------------------------


def test_s12_a_scout_that_finds_nothing_exits_no_updates_with_no_draft(tmp_path: Path) -> None:
    """The Scout succeeded with zero candidates: exit 1, and nothing drafted."""
    result = _run(
        tmp_path,
        supervisor=[_scout_call(), text_turn("No qualifying updates; nothing drafted.")],
        scout=[tool_use_turn("ScoutReport", {"candidates": []})],
    )

    state = result.state
    assert state.exit_code is ExitCode.NO_UPDATES
    assert state.scope is not None and state.documents == {}
    assert _failures(state) == [] and _violations(state) == []
    assert _drafts(state) == []
    _assert_consumed(result, supervisor=2, scout=1)
    _assert_run_completed(result)
    _assert_events(result, "s12")
    [scout_result] = result.events("Scout result:")
    assert scout_result.message == "Scout result: No qualifying updates"


def test_s13a_a_supervisor_that_never_calls_the_scout_exits_parser_error(tmp_path: Path) -> None:
    """P13: it ended its own invocation with no successful ``scout_tool`` call, so the run has no scope: exit 3."""
    result = _run(tmp_path, supervisor=[text_turn("I could not work out a scope from this prompt.")])

    state = result.state
    assert state.exit_code is ExitCode.PARSER_ERROR
    assert state.scope is None
    assert _failures(state) == [] and _violations(state) == []
    assert _drafts(state) == []
    _assert_consumed(result, supervisor=1)
    _assert_run_completed(result)
    _assert_events(result, "s13a")
    assert result.events("Scope built by the Supervisor:") == []


def test_s13b_an_invalid_scope_is_corrected_and_the_retry_succeeds(tmp_path: Path) -> None:
    """``invalid_scope`` does not use up the Scout's one run: the corrected call succeeds, and a draft is saved."""
    result = _run(
        tmp_path,
        supervisor=[
            _scout_call({**SCOPE, "date_from": "20260622"}),
            *_flow(DOC_A),
            text_turn("Corrected the scope; saved one document."),
        ],
        scout=_scout_finds(DOC_A),
        writer=writer_turns(DOC_A),
        qa_legal=[_verdict("PASS")],
    )

    state = result.state
    assert state.exit_code is ExitCode.SUCCESS  # not PARSER_ERROR: the retry gave the run its scope
    assert state.scope is not None and state.scope.date_from == SCOPE_DATE_FROM
    assert _violations(state) == [("invalid_scope", SCOUT_TOOL, None)]
    assert _failures(state) == []
    [draft] = _drafts(state)
    _assert_draft(draft, status="PASS", attempts=1)
    _assert_consumed(result, supervisor=6, scout=2, writer=2, qa_legal=1)
    _assert_run_completed(result)
    _assert_events(result, "s13b")
    [scope_built] = result.events("Scope built by the Supervisor:")
    assert f'"date_from":"{SCOPE_DATE_FROM}"' in scope_built.message
    [violation] = result.events("Guardrail violation:")
    assert "20260622" in violation.message


# ---------------------------------------------------------------------------
# Scenario 14: drafts already on disk (§6.8)
# ---------------------------------------------------------------------------


def test_s14_new_draft_ids_continue_past_todays_files_and_overwrite_none(tmp_path: Path) -> None:
    """Today's ``_001`` and ``_003`` exist: the run's two saves are ``_004`` and ``_005``, and both files stay."""
    config = pipeline_config(tmp_path)
    config.drafts_dir.mkdir(parents=True)
    existing = {config.drafts_dir / f"{_draft_id(sequence)}.md": f"sentinel draft {sequence}\n" for sequence in (1, 3)}
    for path, content in existing.items():
        path.write_text(content, encoding="utf-8")
    before = {path: path.read_bytes() for path in existing}

    result = _run(
        tmp_path,
        supervisor=[*_flow(DOC_A), *_flow(DOC_B)[1:], text_turn("Saved both candidates.")],
        scout=_scout_finds(DOC_A, DOC_B),
        writer=[*writer_turns(DOC_A), *writer_turns(DOC_B)],
        qa_legal=[_verdict("PASS"), _verdict("PASS")],
        config=config,
    )

    state = result.state
    assert state.exit_code is ExitCode.SUCCESS
    assert _failures(state) == [] and _violations(state) == []
    saved = {doc_id: document.saved for doc_id, document in state.documents.items()}
    assert {doc_id: None if draft is None else draft.draft_id for doc_id, draft in saved.items()} == {
        DOC_A: _draft_id(4),
        DOC_B: _draft_id(5),
    }
    assert [path.name for path in _drafts(state)] == [f"{_draft_id(n)}.md" for n in (1, 3, 4, 5)]
    assert {path: path.read_bytes() for path in existing} == before  # no overwrite
    for sequence in (4, 5):
        _assert_draft(config.drafts_dir / f"{_draft_id(sequence)}.md", status="PASS", attempts=1)
    _assert_consumed(result, supervisor=8, scout=2, writer=4, qa_legal=2)
    _assert_run_completed(result)
    _assert_events(result, "s14")
    assert [_field(line, "draft_id") for line in result.events("Document marked saved:")] == [
        _draft_id(4),
        _draft_id(5),
    ]


# ---------------------------------------------------------------------------
# Scenario 15: D-F, the Supervisor never sees article text
# ---------------------------------------------------------------------------

#: The article fields D-F keeps from the Supervisor; each scripted draft fills them with its own sentinels.
ARTICLE_FIELDS: Final[tuple[str, ...]] = ("headline", "article_body", "executive_summary")


def _sentinel_draft(doc_id: str, label: str) -> dict[str, Any]:
    """``ArticleDraft`` arguments for ``doc_id`` whose article fields are each a unique, searchable sentinel."""
    return draft_args(doc_id, **{field: f"SENTINEL-{label}-{field}-d4f1" for field in ARTICLE_FIELDS})


def _string_leaves(value: Any) -> Iterator[str]:
    """Every string in a JSON-like value, at any depth: dict values, list items and the value itself."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _string_leaves(item)
    elif isinstance(value, list):
        for item in value:
            yield from _string_leaves(item)


def test_s15_no_message_the_supervisor_received_carries_article_text(tmp_path: Path) -> None:
    """D-F, Gate 6: across a success, a revision, a failure summary and a violation, the Supervisor's model receives
    no Writer headline, body or summary, raw or inside a tool result's JSON, and no key that would carry one."""
    drafts = [_sentinel_draft(DOC_A, "A1"), _sentinel_draft(DOC_A, "A2"), _sentinel_draft(DOC_B, "B2")]
    result = _run(
        tmp_path,
        supervisor=[
            _scout_call(),
            _write(DOC_A),
            _audit(DOC_A),
            _write(DOC_A, revise=True),
            _audit(DOC_A),
            _save(DOC_A),
            _write(DOC_B),
            _write(DOC_B),
            _audit(DOC_B),
            _save(DOC_B),  # error_with_attempts_remaining
            text_turn("Saved one document; the other is unfinished."),
        ],
        scout=_scout_finds(DOC_A, DOC_B),
        writer=[
            *writer_turns(DOC_A, draft=drafts[0]),
            *writer_turns(DOC_A, draft=drafts[1]),
            _writer_failure(1),
            *writer_turns(DOC_B, draft=drafts[2]),
        ],
        qa_legal=[_verdict("WARNING", SUBSTANTIVE_ISSUE), _verdict("PASS"), _verdict("ERROR", ERROR_ISSUE)],
    )

    state = result.state
    assert state.exit_code is ExitCode.SUCCESS
    assert _failures(state) == [("writer", DOC_B, 1)]
    assert _violations(state) == [("error_with_attempts_remaining", SAVE_DRAFT_TOOL, DOC_B)]
    [draft] = _drafts(state)
    assert all(drafts[1][field] in draft.read_text(encoding="utf-8") for field in ARTICLE_FIELDS)  # the text exists
    _assert_consumed(result, supervisor=11, scout=2, writer=7, qa_legal=3)
    _assert_run_completed(result)
    _assert_events(result, "s15")

    sentinels = [scripted[field] for scripted in drafts for field in ARTICLE_FIELDS]
    received = result.supervisor.received_messages
    assert len(received) == result.supervisor.turns_consumed
    for messages in received:
        leaves = list(_string_leaves(messages))
        assert not [sentinel for sentinel in sentinels if any(sentinel in leaf for leaf in leaves)]
        for payload in _tool_results(messages):
            assert json_keys(payload) & FORBIDDEN_SUPERVISOR_KEYS == set()
            assert not [s for s in sentinels if any(s in leaf for leaf in _string_leaves(payload))]
    # The walk saw every kind of result: a success, a revision, the failure summary and the violation.
    payloads = _tool_results(received[-1])
    assert len(payloads) == 10
    assert any(isinstance(p["error"], str) and p["error"].startswith(f"{WRITER_TOOL} failed:") for p in payloads)
    assert any(isinstance(p["error"], dict) for p in payloads)
    assert any(p["result"] and p["result"].get("attempt") == 2 for p in payloads)


# ---------------------------------------------------------------------------
# Supplementary runs: the two catalogue events none of the fifteen scenarios reaches (acceptance criterion 2)
# ---------------------------------------------------------------------------


def _unconfigured_model_builder(model_id: str, *, reasoning_effort: str | None = None) -> Model:
    """An unconfigured checkout: ``CredentialManager`` rejects an environment with no credentials (D16 isolates it)."""
    CredentialManager(_env_file=None)
    raise AssertionError("unreachable: CredentialManager must reject an unconfigured environment")


def _no_session() -> HSEMockMCPClient:
    """A client factory that fails the test: a run that cannot be configured opens no session."""
    raise AssertionError("a run that cannot be configured must not open the substrate session")


def test_x01_unresolved_settings_log_the_full_validation_report_and_exit_config_error(tmp_path: Path) -> None:
    """The run never starts: exit 5, one ``configuration`` failure, and the pydantic report beneath the ERROR."""
    config = pipeline_config(tmp_path)
    state = run(
        PROMPT,
        config,
        client_factory=_no_session,
        model_builder=_unconfigured_model_builder,
        clock=lambda: TODAY,
        reasoning_settings=ReasoningSettings(HSE_MODEL_SUPERVISOR_REASONING_EFFORT=SUPERVISOR_EFFORT),
    )
    unused = ScriptedModel([])
    result = _Run(state, unused, unused, unused, unused, _read_log(config.log_dir))

    assert state.exit_code is ExitCode.CONFIG_ERROR
    assert _failures(state) == [("configuration", None, None)]
    assert _violations(state) == [] and _drafts(state) == []
    _assert_run_completed(result)
    _assert_events(result, "x01")
    [failure] = result.events("Configuration failure:")
    assert "validation error" in failure.continuation and "HSE_MODEL_FAST_API_KEY" in failure.continuation


def test_x02_a_draft_that_cannot_be_rendered_is_logged_and_exits_persistence_error(tmp_path: Path) -> None:
    """The saved draft's template is missing: exit 4, a ``render`` failure, and its ERROR with the draft's path."""
    result = _run(
        tmp_path,
        supervisor=[*_flow(DOC_A), text_turn("Saved one document.")],
        scout=_scout_finds(DOC_A),
        writer=writer_turns(DOC_A),
        qa_legal=[_verdict("PASS")],
        config=pipeline_config(tmp_path, template_path=tmp_path / "missing.md"),
    )

    state = result.state
    assert state.exit_code is ExitCode.PERSISTENCE_ERROR
    assert _failures(state) == [("render", DOC_A, 1)]
    assert _violations(state) == [] and _drafts(state) == []
    _assert_consumed(result, supervisor=5, scout=2, writer=2, qa_legal=1)
    _assert_run_completed(result)
    _assert_events(result, "x02")
    [failure] = result.events("Draft render or write failure:")
    assert f"draft_id={_draft_id(1)}" in failure.message and "FileNotFoundError" in failure.continuation


# ---------------------------------------------------------------------------
# Acceptance criterion 2: the scenarios together assert every D-I catalogue event
# ---------------------------------------------------------------------------


def test_every_catalogue_event_is_asserted_by_a_scenario() -> None:
    """The union of the events the scenarios assert is the catalogue's event list, read from SPECIFICATIONS.md.

    The catalogue has no DEBUG row, so the request bodies D-I keeps outside it need no exclusion. Each declaration
    belongs to exactly one scenario test, and that test asserts it under its own key, so neither a deleted scenario
    nor a deleted ``_assert_events`` call can leave its events counted.
    """
    catalogue = _catalogue()
    assert len(catalogue) == 23
    assert set(_CATALOGUE_PATTERNS) == set(catalogue)
    asserted = frozenset().union(*_SCENARIO_EVENTS.values())
    assert asserted == set(catalogue), f"never asserted: {sorted(set(catalogue) - asserted)}"
    tests = [name for name, value in globals().items() if name.startswith("test_") and callable(value)]
    for scenario in _SCENARIO_EVENTS:
        [name] = [name for name in tests if name.startswith(f"test_{scenario}_")]
        assert f'_assert_events(result, "{scenario}")' in inspect.getsource(globals()[name]), scenario
