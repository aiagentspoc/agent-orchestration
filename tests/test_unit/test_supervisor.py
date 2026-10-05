"""``src.supervisor``: the Supervisor's prompt, builder and runner (IMPLEMENTATION_PLAN.md Iteration 13).

SPECIFICATIONS.md §1.1, D-C, D-F, D-H, §7.1 and §7.4. Every model here is a :class:`ScriptedModel` or a
:class:`FailingModel` (P4), and the prompt is never printed: it holds characters the Windows console cannot encode.
"""

import inspect
import json
import logging
import re
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from strands import Agent, tool
from strands.handlers.callback_handler import null_callback_handler
from strands.hooks import BeforeToolCallEvent, HookProvider, HookRegistry
from strands.models.model import Model
from strands.tools.executors import SequentialToolExecutor
from strands.types.tools import AgentTool

from src.agents import WRITER_MODEL_ID
from src.credentials import STRONG_MODEL_ID, ReasoningSettings
from src.guardrails import QA_TOOL, SAVE_DRAFT_TOOL, SCOUT_TOOL, WRITER_TOOL
from src.hooks import FatalStopHook
from src.mcp_client import MCPConnectionError
from src.schemas import RunContext, RunState
from src.supervisor import (
    SUPERVISOR_MODEL_ID,
    SUPERVISOR_REASONING_EFFORT,
    build_supervisor_agent,
    build_supervisor_prompt,
    run_supervisor,
)
from src.tools import SubAgentEfforts, SubAgentModels, build_tools
from tests.support.scripted import (
    DEFAULT_DOC_ID,
    DRAFT_ARGS,
    FORBIDDEN_SUPERVISOR_KEYS,
    SCOPE_DATE_FROM,
    SCOPE_DATE_TO,
    SUBSTRATE_TOOL_NAMES,
    FailingModel,
    OfflineSubstrateSession,
    ScriptedModel,
    json_keys,
    offline_client,
    pipeline_config,
    qa_args,
    scout_report_args,
    sent_text,
    text_turn,
    tool_use_turn,
    writer_turns,
)
from tests.test_unit.test_docs_consistency import SUPERVISOR_TOOL_DESCRIPTIONS

#: The current date every scripted run here resolves its scope against: ``SCOPE_DATE_TO``.
TODAY: date = date(2026, 9, 22)
#: The Supervisor's four tools, in the order ``build_tools`` returns them (§7.1).
SUPERVISOR_TOOLS: tuple[str, ...] = (SCOUT_TOOL, WRITER_TOOL, QA_TOOL, SAVE_DRAFT_TOOL)


@pytest.fixture
def state(tmp_path: Path) -> RunState:
    """A fresh run state with no ``--max-drafts`` ceiling."""
    return RunState(
        run_id="run-test-0013",
        config=pipeline_config(tmp_path),
        context=RunContext(today=TODAY, max_drafts=None, drafts_saved=0),
    )


def _tools(
    state: RunState,
    *,
    scout: Sequence[list[dict[str, Any]]] = (),
    writer: Sequence[list[dict[str, Any]]] = (),
    qa_legal: Sequence[list[dict[str, Any]]] = (),
) -> list[AgentTool]:
    """The real four tools over ``state``, offline substrate, each sub-agent on its own scripted model."""
    return build_tools(
        state,
        client=offline_client(OfflineSubstrateSession()),
        models=SubAgentModels(
            scout=ScriptedModel(scout), writer=ScriptedModel(writer), qa_legal=ScriptedModel(qa_legal)
        ),
        efforts=SubAgentEfforts(),
    )


def _supervisor(
    state: RunState, model: Model, *, max_drafts: int | None = None, hooks: Sequence[HookProvider] = ()
) -> Agent:
    """A Supervisor over the real tools of ``state``, with sub-agents that are never called."""
    return build_supervisor_agent(model, _tools(state), max_drafts=max_drafts, hooks=hooks)


# ---------------------------------------------------------------------------
# Model binding and effort (D-H)
# ---------------------------------------------------------------------------


def test_supervisor_runs_on_the_strong_binding() -> None:
    """The Supervisor is ``gpt-5.4``, the strong binding the Writer and QA-Legal share (D-H)."""
    assert SUPERVISOR_MODEL_ID == STRONG_MODEL_ID == WRITER_MODEL_ID == "gpt-5.4"


def test_supervisor_effort_is_the_reasoning_settings_default() -> None:
    """The Supervisor's effort is ``ReasoningSettings.supervisor``'s default, ``medium`` (D-H, Q5 = B)."""
    assert SUPERVISOR_REASONING_EFFORT == ReasoningSettings.model_fields["supervisor"].default == "medium"
    assert ReasoningSettings(_env_file=None).supervisor == SUPERVISOR_REASONING_EFFORT


# ---------------------------------------------------------------------------
# build_supervisor_agent (D-H, D-F, Q10 = B)
# ---------------------------------------------------------------------------


def test_supervisor_agent_runs_its_tools_one_after_another(state: RunState) -> None:
    """D-H: ``SequentialToolExecutor`` replaces the concurrent default; the same-turn fatal stop needs it (§8.4)."""
    agent = _supervisor(state, ScriptedModel([]))
    assert isinstance(agent.tool_executor, SequentialToolExecutor)


def test_supervisor_agent_has_exactly_the_four_tools_and_no_substrate_tool(state: RunState) -> None:
    """The Supervisor holds the four tools of §7.1 and nothing else: no direct substrate access (Q10 = B)."""
    agent = _supervisor(state, ScriptedModel([]))
    assert agent.tool_names == list(SUPERVISOR_TOOLS)
    assert not set(agent.tool_names) & set(SUBSTRATE_TOOL_NAMES)


def test_supervisor_agent_is_built_on_the_model_it_is_given(state: RunState) -> None:
    """The composition root builds the model on the strong binding at the resolved effort; the builder keeps it."""
    model = ScriptedModel([])
    assert _supervisor(state, model).model is model


def test_supervisor_agent_has_no_console_callback_handler(state: RunState) -> None:
    """``callback_handler=None``, which Strands maps to its null handler: nothing is streamed to stdout."""
    assert _supervisor(state, ScriptedModel([])).callback_handler is null_callback_handler


@pytest.mark.parametrize("max_drafts", [None, 2])
def test_supervisor_agent_system_prompt_is_the_prompt_for_its_ceiling(state: RunState, max_drafts: int | None) -> None:
    """The system prompt is the one built for the run's ``--max-drafts`` ceiling."""
    agent = _supervisor(state, ScriptedModel([]), max_drafts=max_drafts)
    assert agent.system_prompt == build_supervisor_prompt(max_drafts)


class _ToolStartRecorder(HookProvider):
    """A caller's hook: on each tool start, records whether "Tool call started" was already logged for it."""

    def __init__(self, caplog: pytest.LogCaptureFixture) -> None:
        self._caplog = caplog
        self.logged_before_me: list[bool] = []

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        """Register the before-tool-call callback."""
        registry.add_callback(BeforeToolCallEvent, self._before_tool_call)

    def _before_tool_call(self, event: BeforeToolCallEvent) -> None:
        started = [r for r in self._caplog.records if r.getMessage().startswith("Tool call started")]
        self.logged_before_me.append(len(started) == len(self.logged_before_me) + 1)


def test_supervisor_logging_hooks_are_registered_once_and_before_the_callers(
    state: RunState, caplog: pytest.LogCaptureFixture
) -> None:
    """One ``LoggingHooks("supervisor")``, registered first, then the caller's hooks: each turn is logged once."""
    recorder = _ToolStartRecorder(caplog)
    model = ScriptedModel([tool_use_turn(SAVE_DRAFT_TOOL, {"doc_id": "unknown"}), text_turn("done")])
    agent = _supervisor(state, model, hooks=(recorder,))

    with caplog.at_level(logging.INFO, logger="src.hooks"):
        agent("go")

    turns = [r.getMessage() for r in caplog.records if r.getMessage().startswith("Supervisor turn completed")]
    assert len(turns) == 2
    assert all("agent=supervisor" in r.getMessage() for r in caplog.records if r.getMessage().startswith("Tool call"))
    assert recorder.logged_before_me == [True]


def test_supervisor_hooks_are_a_required_keyword() -> None:
    """``hooks`` has no default: the composition root states the Supervisor's hooks, ``FatalStopHook`` among them."""
    parameter = inspect.signature(build_supervisor_agent).parameters["hooks"]
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert parameter.default is inspect.Parameter.empty


# ---------------------------------------------------------------------------
# The system prompt: every item of §7.4
# ---------------------------------------------------------------------------


def _flat(text: str) -> str:
    """``text`` with every run of whitespace, line breaks included, collapsed to one space: the prompt is wrapped."""
    return " ".join(text.split())


#: What each §7.4 item must say, as phrases the prompt holds verbatim. Checked for both forms of the ceiling.
PROMPT_ITEMS: dict[str, tuple[str, ...]] = {
    "role": (
        "You supervise agents, not drafts.",
        "turn the user's prompt into a scope, call the Scout, decide which candidates to draft, read each QA report "
        "and decide whether to request a revision or save, and decide when the run is finished",
        "You never read, judge or edit article text.",
        "the article is never returned to you",
        "You never write feedback for the Writer.",
        "You never write Markdown.",
        "You have no direct access to the regulatory substrate",
    ),
    "tools": (
        "## Tools You have four tools, each described in its own specification: `scout_tool` runs the Scout, "
        "`writer_tool` runs the Writer, `qa_tool` runs QA-Legal, and `save_draft` marks a document saved.",
    ),
    "scope_resolves_dates_against_the_user_turn": (
        "`date_from` and `date_to`: absolute ISO `YYYY-MM-DD` dates.",
        "The user turn states the current date; resolve every date against **that** date and never against your "
        'own sense of when "now" is.',
    ),
    "scope_defaults_to_the_past_3_months": (
        "`date_from` is the start of the window the user named, counted back from `date_to`. When the user named "
        "no window, use the past 3 months.",
        'Recency words such as "recent", "lately", "current", "latest" or "most recent" order results; they do not '
        "name a period, so they still give the past 3 months.",
        "`date_from` must never be later than `date_to`.",
    ),
    "scope_date_to_is_today_unless_named": (
        '`date_to` is that current date, unless the user named an end date ("up to March 2025", "fino al '
        '31/12/2024"), in which case it is theirs.',
    ),
    "scope_empty_sources_means_all": (
        "`sources`: any of `EUR_LEX`, `GAZZETTA_UFFICIALE`, `INAIL` that the user named. Leave the list empty when "
        'the user named none; an empty list means "all sources".',
    ),
    "scope_max_drafts_only_when_stated": (
        "`max_drafts`: an integer ONLY when the user's own words bound how many articles they want.",
        'A stated count — "at most 3 articles", "just one", "write two pieces".',
        "A **singular definite** request, which names exactly one instrument and is therefore explicit rather than "
        'inferred — "the latest regulatory update", "the most recent change", "the newest circular", "l\'ultimo '
        'aggiornamento". Set `max_drafts` to 1.',
        'Everything else MUST be null. A plural or unquantified request bounds nothing: "recent updates", "the '
        'latest updates", "what changed this quarter", "analizza gli aggiornamenti INAIL" all give `max_drafts: '
        "null`.",
    ),
    "scope_works_only_from_the_users_words": (
        "Work only from what the user wrote; never invent constraints they did not express.",
        "`sector_constraints`: industrial sectors the user restricted to, lowercase (e.g. `construction`, "
        "`manufacturing`, `agriculture`). Empty means unrestricted.",
        "The scope's `max_drafts` comes from the user's words only, never from the `--max-drafts` ceiling under "
        "Limits, which is enforced when you save.",
    ),
    "decision_basis": (
        "After every `writer_tool` or `qa_tool` result, decide the document's next step.",
        "the latest draft's QA report only: `status`, `issues`, `review_notes`, `verified_citations`;",
        "the `attempt` number, and `max_attempts_per_doc` from `RunContext` (the `run` object of every result): "
        "attempts remaining = `max_attempts_per_doc` − `attempt`;",
        "the candidates still waiting, and `drafts_saved` against `max_drafts`.",
        "Read the latest report's issue text to judge whether an issue is one the Writer can fix.",
        "A failed Writer call is shown to you as `ToolResult.error`, a one-line summary, together with an "
        "`AttemptRecord` that has no draft.",
    ),
    "decision_table": ("| QA status | Attempts remaining | Condition | Decision |",),
    "never_compare_qa_reports": (
        "Never compare QA reports across attempts. Earlier results remain in your context; decide from the latest "
        "report alone.",
    ),
    "run_level_priorities": ("**Run-level priorities,** applied on top of the table: 1. **Finish documents",),
    "limits": (
        "## Limits - 3 Writer attempts per document: an initial draft plus up to 2 revisions.",
        "Every `writer_tool` call counts as an attempt, whether it succeeds or fails. The same number is "
        "`max_attempts_per_doc` in the `RunContext` of every result.",
        "The draft ceiling (`--max-drafts`) for this run:",
    ),
    "violations": (
        "A tool call that breaks one of the rules code enforces is refused: its result's `error` carries a "
        "guardrail violation, with a message saying why.",
        "A violation is not the end of the run: read its message and decide again.",
    ),
    "finishing": (
        "When you decide the run is finished, end with a plain-text summary of the documents saved, skipped and "
        "left unfinished.",
    ),
}


@pytest.mark.parametrize(("max_drafts", "stated"), [(None, "no ceiling"), (1, "1"), (3, "3")])
def test_prompt_states_the_draft_ceiling_or_no_ceiling(max_drafts: int | None, stated: str) -> None:
    """§7.4 Limits: the ``--max-drafts`` value, or the words "no ceiling" when it is ``None``."""
    prompt = build_supervisor_prompt(max_drafts)
    assert f"The draft ceiling (`--max-drafts`) for this run: {stated}.\n" in prompt
    assert ("no ceiling" in prompt) is (max_drafts is None)


@pytest.mark.parametrize("max_drafts", [None, 3])
@pytest.mark.parametrize(("item", "phrases"), PROMPT_ITEMS.items(), ids=list(PROMPT_ITEMS))
def test_prompt_covers_the_section_7_4_item(item: str, phrases: tuple[str, ...], max_drafts: int | None) -> None:
    """§7.4: the system prompt carries every listed item, whatever the ceiling."""
    prompt = _flat(build_supervisor_prompt(max_drafts))
    missing = [phrase for phrase in phrases if phrase not in prompt]
    assert missing == [], f"{item}: {missing!r}"


def test_supervisor_model_receives_the_section_7_1_descriptions_word_for_word(state: RunState) -> None:
    """AC2: the tool specs that reach the Supervisor model are exactly §7.1's four, as the docs test pins them."""
    model = ScriptedModel([text_turn("done")])
    _supervisor(state, model)("go")

    specs = model.received_tool_specs[0]
    assert specs is not None
    assert {spec["name"]: spec["description"] for spec in specs} == SUPERVISOR_TOOL_DESCRIPTIONS


# ---------------------------------------------------------------------------
# What the system prompt must never contain (§7.4, D-F, DM3, DM16)
# ---------------------------------------------------------------------------

#: The verbs of working on article text, as the verbs' stems; ``_ARTICLE_WORK`` adds the regular endings and
#: ``rewrote``/``rewritten``.
_ARTICLE_VERB = (
    r"(?:review|scor|rat|grad|improv|edit|rewr[io]t|reword|proofread|polish|read|judg|check|assess|evaluat"
    r"|fix|correct|critiqu|inspect|examin)"
)
#: An instruction to work on article text: one of those verbs, in any inflection, then within four words an article
#: or a draft, singular or plural, after any determiner or possessive. A plain word list would also catch
#: ``review_notes`` and ``newsworthiness_score``, so the verb must govern the object; a word after "and" or "or"
#: starts a new phrase, so "read each QA report and ... the latest draft" is not one instruction.
_ARTICLE_WORK = re.compile(
    r"\b" + _ARTICLE_VERB + r"(?:e|es|ed|d|s|ing|ten)?\b"
    r"(?:[ ,]+(?!(?:and|or)\b)[^\s,]+){0,4}?"
    r"[ ,]+(?:article|draft)s?\b",
    re.IGNORECASE,
)
#: A negation that governs a match: within three words before it, as in "never read, judge or edit article text".
#: "no" is left out: it is usually a determiner ("no issues"), not a negation of the instruction.
_NEGATED_BEFORE = re.compile(r"\b(?:never|not|don't|cannot)\b(?:[ ,]+[^\s,]+){0,3}[ ,]*$", re.IGNORECASE)
#: A negation that governs the matched verb itself: the negation, then only a list of verbs it also governs, as in
#: "never read, judge or edit article text". "Never save before you review the draft" negates "save", not "review".
_NEGATED_VERB = re.compile(
    r"\b(?:never|not|don't|cannot)[ ]+(?:[^\s,]+(?:,[ ]+(?:(?:and|or)[ ]+)?|[ ]+(?:and|or)[ ]+))*$",
    re.IGNORECASE,
)
#: Words that negate a clause: "never read", "not the end", "no direct access".
_NEGATION = re.compile(r"\b(?:never|not|no|nothing)\b", re.IGNORECASE)
#: Clauses end at ``.``, ``!``, ``?`` or ``;`` followed by whitespace.
_CLAUSE_BREAK = re.compile(r"(?<=[.!?;])\s+")
#: A count, in digits or in words, as a bound on the run would state it.
_COUNT = r"(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|twelve|fifteen|twenty|thirty|forty|fifty)"
#: A bound on the run: a tool-call budget, or a limit on repeated violations. DM16 sets neither.
_RUN_BOUNDS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bbudget\b", re.IGNORECASE),
    re.compile(
        r"\b(?:after|within|more than|at most|up to|maximum of|exceed) " + _COUNT + r" (?:tool )?(?:calls|tools)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\btool[- ]calls? (?:limit|ceiling|cap)\b", re.IGNORECASE),
    re.compile(r"\b(?:after|at most|more than) " + _COUNT + r" violations\b", re.IGNORECASE),
    re.compile(r"\bviolations? (?:repeats?|occurs?) (?:\d+|one|two|three|four|five) times\b", re.IGNORECASE),
)
#: An ISO date literal; the token ``YYYY-MM-DD`` is not one.
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
#: The article's own field names (§6.3): none reaches the Supervisor (D-F), so its prompt never names one.
ARTICLE_FIELDS: tuple[str, ...] = ("headline", "article_body", "executive_summary", "tdi_cta")


def _clauses(text: str) -> list[str]:
    """The clauses of ``text``, its line breaks collapsed first so a wrapped sentence is one clause."""
    return _CLAUSE_BREAK.split(_flat(text))


def _affirmative_clauses(text: str, pattern: re.Pattern[str]) -> list[str]:
    """The clauses of ``text`` that match ``pattern`` and are not negated."""
    return [clause for clause in _clauses(text) if pattern.search(clause) and not _NEGATION.search(clause)]


def _affirmative_matches(text: str, pattern: re.Pattern[str], negation: re.Pattern[str]) -> list[str]:
    """Every match of ``pattern`` in ``text`` whose preceding clause text ``negation`` does not end in."""
    return [
        match.group(0)
        for clause in _clauses(text)
        for match in pattern.finditer(clause)
        if not negation.search(clause[: match.start()])
    ]


def _article_work_instructions(text: str) -> list[str]:
    """Every instruction in ``text`` to review, score or improve article text, unless its own verb is negated."""
    return _affirmative_matches(text, _ARTICLE_WORK, _NEGATED_VERB)


#: A request for the Supervisor to brief the Writer: feedback, revision notes or instructions, or telling it.
_WRITER_FEEDBACK = re.compile(
    r"\b(?:feedback|revision (?:notes|instructions?)|instructions? for the Writer|tell the Writer|give the Writer"
    r"|brief the Writer|explain to the Writer|(?:guidance|comments) (?:to|for) the Writer)\b",
    re.IGNORECASE,
)
#: A clause naming the Scout or QA-Legal, by tool or by agent.
_SCOUT_OR_QA = re.compile(r"\b(?:scout_tool|qa_tool|Scout|QA-Legal)\b", re.IGNORECASE)
#: A failure, in lower case: the prompt's ``ERROR`` is a QA status, not a failed call, so case matters here.
_FAILURE = re.compile(r"\bfail|\berrors?\b")


def _writer_feedback_instructions(text: str) -> list[str]:
    """Every request in ``text`` for feedback or revision instructions for the Writer."""
    # Within three words, not only of its own verb: "You never write feedback for the Writer." negates "write".
    return _affirmative_matches(text, _WRITER_FEEDBACK, _NEGATED_BEFORE)


def _failed_call_rules(text: str) -> list[str]:
    """The clauses of ``text`` that state a rule for a failed or erroring ``scout_tool`` or ``qa_tool`` call."""
    return [clause for clause in _clauses(text) if _SCOUT_OR_QA.search(clause) and _FAILURE.search(clause)]


def _run_bounds(text: str) -> list[str]:
    """Every phrase of ``text`` that sets a tool-call budget or bounds repeated violations."""
    return [match.group(0) for pattern in _RUN_BOUNDS for match in pattern.finditer(text)]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Review the draft before you save it.", 1),
        ("Score the article. Improve the draft where QA-Legal objects.", 2),
        ("Proofread, polish and rewrite article text.", 1),
        ("You never read, judge or edit article text.", 0),
        ("Read `review_notes` and the `newsworthiness_score`.", 0),
        ("Read each QA report; decide from the latest report alone.", 0),
        ("The article is never returned to you; read the latest report's issue text.", 0),
        ("Code hands the Writer the latest draft together with the QA report that audited it.", 0),
        ("Apply this table to the latest draft's QA report.", 0),
    ],
)
def test_article_work_instructions_catch_instructions_but_not_their_negation(text: str, expected: int) -> None:
    """The verb-object check finds an instruction to work on article text and spares the Role's negation."""
    assert len(_article_work_instructions(text)) == expected


#: Realistic instructions to work on article text (QA-M1): each one must be caught.
ARTICLE_WORK_PROBES: tuple[str, ...] = (
    "Review each draft before you save it.",
    "Read the latest draft and decide.",
    "Review the drafts before saving.",
    "Check the article for errors before saving.",
    "Assess the quality of the draft.",
    "Evaluate the article against the QA report.",
    "If QA-Legal reports no issues, review the draft yourself.",
    "Do not save until you have reviewed the draft.",
    "You never edit article text, but you should score the article.",
    "Improve the Writer's draft where QA-Legal objects.",
    "Rate the article from 1 to 10.",
    "Fix the article where needed.",
    "Before saving, review each draft and improve its wording where QA-Legal objects.",
    "Read the latest draft and check the article for errors before you call save_draft.",
    "If QA-Legal reports no issues, still review the draft yourself and tell the Writer what to fix.",
    # A2: inflections whose stem drops a final "e", and the irregular "rewrote".
    "When scoring the draft, be strict.",
    "Consider improving the article.",
    "Before judging the draft, read the report.",
    "Rating the article is your job.",
    "Start by evaluating the draft.",
    "You rewrote the draft.",
    # A3: the negation governs another verb, so the instruction to work on the draft still stands.
    "Never save before you review the draft.",
    "Don't save until you read the draft.",
)


@pytest.mark.parametrize("text", ARTICLE_WORK_PROBES)
def test_article_work_instructions_catch_realistic_phrasings(text: str) -> None:
    """Inflected verbs, plural or possessive objects and a determiner "no" do not hide an instruction."""
    assert _article_work_instructions(text) != []


def test_article_work_check_is_linear_on_comma_dense_text() -> None:
    """A1 / QA-m4: comma-dense text with no article or draft returns at once; the checks never backtrack on it."""
    assert _article_work_instructions("review " + ", " * 2000 + "x") == []


@pytest.mark.parametrize(
    "text",
    [
        "Tell the Writer what to fix in its revision.",
        "Give the Writer revision notes.",
        "When no issue is fixable, write feedback for the Writer anyway.",
        "Write revision instructions for the Writer.",
        "If QA-Legal reports no issues, still review the draft yourself and tell the Writer what to fix.",
        # QA-m6: briefing the Writer without the word "feedback".
        "Explain to the Writer what QA-Legal found.",
        "Pass your comments to the Writer.",
        "Brief the Writer on each issue.",
        "Provide guidance to the Writer.",
    ],
)
def test_writer_feedback_check_catches_realistic_phrasings(text: str) -> None:
    """Any common way of asking the Supervisor to brief the Writer is caught."""
    assert _writer_feedback_instructions(text) != []


@pytest.mark.parametrize(
    "text",
    [
        "You never write feedback for the Writer.",
        "Code hands the Writer the latest draft together with the QA report that audited it.",
        "Decide whether to request a revision or save.",
    ],
)
def test_writer_feedback_check_spares_negations_and_hand_offs(text: str) -> None:
    """The Role's negation and what code hands the Writer are not feedback instructions."""
    assert _writer_feedback_instructions(text) == []


@pytest.mark.parametrize(
    "text",
    [
        "If scout_tool fails, stop the run.",
        "If qa_tool returns an error, call it again.",
        "When QA-Legal errors, save the draft.",
        "If the Scout errors out, retry once.",
    ],
)
def test_failed_call_check_catches_realistic_phrasings(text: str) -> None:
    """A rule for a failed or erroring ``scout_tool`` or ``qa_tool`` call is caught in any common form."""
    assert _failed_call_rules(text) != []


@pytest.mark.parametrize(
    "text",
    [
        "| `ERROR` | 0 | — | **Save,** with the compliance banner |",
        "QA-Legal's `ERROR` status means the draft could not be verified.",
        "A failed Writer call is shown to you as `ToolResult.error`, a one-line summary.",
    ],
)
def test_failed_call_check_spares_the_error_status_and_writer_failures(text: str) -> None:
    """The ``ERROR`` QA status and the Writer's failure rule are not rules for a failed Scout or QA-Legal call."""
    assert _failed_call_rules(text) == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("You have a budget of 40 tool calls.", 1),
        ("Make at most 12 calls. Stop after 3 violations.", 2),
        ("There is a tool-call limit.", 1),
        ("A violation is not the end of the run. 3 Writer attempts per document.", 0),
        ("Stop after 20 tool calls.", 1),
        ("Do not call more than 30 tools.", 1),
        ("If the same violation repeats three times, stop.", 1),
        ("Finish within 40 calls.", 1),
        ("Use no more than 25 tool calls.", 1),
        ("An initial draft plus up to 2 revisions.", 0),
        # QA-m6: counts in words, and "exceed".
        ("Stop after three violations.", 1),
        ("Never exceed 50 tool calls.", 1),
        ("Call at most twenty tools.", 1),
        ("An initial draft plus up to two revisions.", 0),
    ],
)
def test_run_bounds_catch_a_tool_call_budget_or_violation_bound(text: str, expected: int) -> None:
    """The run-bound check finds a tool-call budget or a bound on violations, and not the attempt cap."""
    assert len(_run_bounds(text)) == expected


@pytest.mark.parametrize("max_drafts", [None, 3])
def test_prompt_never_tells_the_supervisor_to_work_on_article_text(max_drafts: int | None) -> None:
    """§7.4, D-F: no clause tells the Supervisor to review, score or improve article text."""
    assert _article_work_instructions(build_supervisor_prompt(max_drafts)) == []


@pytest.mark.parametrize("max_drafts", [None, 3])
def test_prompt_holds_no_date(max_drafts: int | None) -> None:
    """§7.4: the current date goes in the user turn; the system prompt holds no date at all."""
    prompt = build_supervisor_prompt(max_drafts)
    assert _ISO_DATE.findall(prompt) == []
    assert f"{TODAY:%Y-%m-%d}" not in prompt and f"{date.today():%Y-%m-%d}" not in prompt


def test_supervisor_module_never_reads_the_clock() -> None:
    """The prompt is built from its inputs only: ``src.supervisor`` never asks for today's date."""
    source = (Path(__file__).resolve().parents[2] / "src" / "supervisor.py").read_text(encoding="utf-8")
    assert "today()" not in source and "now()" not in source


@pytest.mark.parametrize("max_drafts", [None, 3])
def test_prompt_names_no_dropped_scope_field_and_no_article_field(max_drafts: int | None) -> None:
    """DM2 dropped ``time_window`` and ``time_window_specified``; D-F keeps the article's fields from the Supervisor."""
    prompt = build_supervisor_prompt(max_drafts)
    assert "time_window" not in prompt
    assert [field for field in ARTICLE_FIELDS if field in prompt] == []


@pytest.mark.parametrize("max_drafts", [None, 3])
def test_prompt_never_asks_for_feedback_for_the_writer(max_drafts: int | None) -> None:
    """§1.1: the Supervisor writes no feedback and no revision instructions; code hands the Writer its input (D-E)."""
    assert _writer_feedback_instructions(build_supervisor_prompt(max_drafts)) == []


@pytest.mark.parametrize("max_drafts", [None, 3])
def test_prompt_never_asks_for_citation_checks_or_substrate_calls(max_drafts: int | None) -> None:
    """Q10 = B: QA-Legal verifies citations and sub-agents call the substrate; the prompt names no substrate tool."""
    prompt = build_supervisor_prompt(max_drafts)
    assert re.search(r"\bverify\b", prompt, re.IGNORECASE) is None
    assert [name for name in SUBSTRATE_TOOL_NAMES if name in prompt] == []


@pytest.mark.parametrize("max_drafts", [None, 3])
def test_prompt_sets_no_tool_call_budget_and_no_violation_bound(max_drafts: int | None) -> None:
    """DM16: no tool-call ceiling and no bound on repeated guardrail violations."""
    assert _run_bounds(build_supervisor_prompt(max_drafts)) == []


@pytest.mark.parametrize("max_drafts", [None, 3])
def test_prompt_never_passes_the_ceiling_into_the_scope(max_drafts: int | None) -> None:
    """DM3: no affirmative clause puts the ``--max-drafts`` ceiling into the scope or ``scout_tool``."""
    into_scope = re.compile(r"--max-drafts.*\b(?:scope|scout_tool)\b|\b(?:scope|scout_tool)\b.*--max-drafts")
    assert _affirmative_clauses(build_supervisor_prompt(max_drafts), into_scope) == []


@pytest.mark.parametrize("max_drafts", [None, 3])
def test_prompt_adds_no_rule_for_a_failed_scout_or_qa_call(max_drafts: int | None) -> None:
    """X4: the sources give no rule for a failed ``scout_tool`` or ``qa_tool`` call, so the prompt states none."""
    assert _failed_call_rules(build_supervisor_prompt(max_drafts)) == []


# ---------------------------------------------------------------------------
# run_supervisor (§7.4 user turn, Rule 6)
# ---------------------------------------------------------------------------

#: A raw prompt with surrounding whitespace, so a runner that strips or rewrites it is caught.
RAW_PROMPT: str = "  Analyze recent INAIL updates on heat stress\n"


def test_user_turn_is_the_current_date_then_the_raw_prompt_verbatim(state: RunState) -> None:
    """§7.4: ``Current date: YYYY-MM-DD``, a blank line, then the prompt exactly as the user wrote it."""
    model = ScriptedModel([text_turn("Nothing to do.")])
    run_supervisor(_supervisor(state, model), RAW_PROMPT, today=TODAY)

    assert sent_text(model, 0) == f"Current date: 2026-09-22\n\n{RAW_PROMPT}"
    assert len(model.received_messages[0]) == 1


def test_run_supervisor_returns_the_final_text_as_the_summary(state: RunState) -> None:
    """The Supervisor's final message is its plain-text summary."""
    model = ScriptedModel([text_turn("Saved: none. Skipped: none. Unfinished: none.")])
    output = run_supervisor(_supervisor(state, model), RAW_PROMPT, today=TODAY)
    assert output.summary == "Saved: none. Skipped: none. Unfinished: none."


def test_run_supervisor_labels_its_telemetry_with_the_supervisor_binding(state: RunState) -> None:
    """By default the telemetry carries ``gpt-5.4`` at ``medium``, with the call's tokens (Rule 6)."""
    model = ScriptedModel([text_turn("done", input_tokens=7, output_tokens=4)])
    telemetry = run_supervisor(_supervisor(state, model), RAW_PROMPT, today=TODAY).telemetry

    assert (telemetry.model_id, telemetry.reasoning_effort) == (SUPERVISOR_MODEL_ID, SUPERVISOR_REASONING_EFFORT)
    assert (telemetry.input_tokens, telemetry.output_tokens, telemetry.total_tokens) == (7, 4, 11)


def test_run_supervisor_labels_its_telemetry_with_the_effort_it_was_given(state: RunState) -> None:
    """An ``.env`` override reaches the telemetry: the composition root passes the effort it resolved."""
    model = ScriptedModel([text_turn("done")])
    telemetry = run_supervisor(
        _supervisor(state, model), RAW_PROMPT, today=TODAY, model_id="gpt-5.4", reasoning_effort="high"
    ).telemetry
    assert telemetry.reasoning_effort == "high"


def test_run_supervisor_leaves_the_run_state_to_the_composition_root(state: RunState) -> None:
    """``finalise_run`` appends the Supervisor's ledger entry and the composition root sets the summary (DM18)."""
    model = ScriptedModel([text_turn("done")])
    run_supervisor(_supervisor(state, model), RAW_PROMPT, today=TODAY)
    assert state.ledger == []
    assert state.supervisor_summary is None


# ---------------------------------------------------------------------------
# A scripted Supervisor over the real tools (zero tokens)
# ---------------------------------------------------------------------------

#: The scope a Supervisor builds from ``RAW_PROMPT`` on ``TODAY``: "recent" names no period, so the past 3 months.
SCOPE: dict[str, Any] = {
    "date_from": SCOPE_DATE_FROM,
    "date_to": SCOPE_DATE_TO,
    "sources": ["INAIL"],
    "sector_constraints": [],
    "max_drafts": None,
}
SUMMARY: str = f"Saved: {DEFAULT_DOC_ID} (PASS, attempt 1). Skipped: none. Unfinished: none."


def _flow_tools(state: RunState) -> list[AgentTool]:
    """The four tools over sub-agents scripted for one document: one candidate, one draft, one ``PASS``."""
    return _tools(
        state,
        scout=[
            tool_use_turn("list_regulatory_updates", {"source": "INAIL"}),
            tool_use_turn("ScoutReport", scout_report_args(DEFAULT_DOC_ID)),
        ],
        writer=writer_turns(DEFAULT_DOC_ID),
        qa_legal=[tool_use_turn("QAReport", qa_args(status="PASS"))],
    )


def _flow_supervisor() -> ScriptedModel:
    """The Supervisor's own script: scout, write, audit, save, then its summary. The flow lives in the model."""
    return ScriptedModel(
        [
            tool_use_turn(SCOUT_TOOL, SCOPE),
            tool_use_turn(WRITER_TOOL, {"doc_id": DEFAULT_DOC_ID, "revise": False}),
            tool_use_turn(QA_TOOL, {"doc_id": DEFAULT_DOC_ID}),
            tool_use_turn(SAVE_DRAFT_TOOL, {"doc_id": DEFAULT_DOC_ID}),
            text_turn(SUMMARY),
        ]
    )


def test_scripted_supervisor_takes_one_document_from_scout_to_save(state: RunState) -> None:
    """scout_tool → writer_tool → qa_tool → save_draft leaves one saved document, and the summary is returned."""
    model = _flow_supervisor()
    agent = build_supervisor_agent(model, _flow_tools(state), max_drafts=None, hooks=(FatalStopHook(state),))

    output = run_supervisor(agent, RAW_PROMPT, today=TODAY)

    assert list(state.documents) == [DEFAULT_DOC_ID]
    record = state.documents[DEFAULT_DOC_ID]
    assert record.saved is not None and record.saved.qa_status == "PASS"
    assert record.attempts_used == 1
    assert output.summary == SUMMARY
    assert model.turns_consumed == 5
    assert model.received_system_prompts[0] == build_supervisor_prompt(None)
    assert sent_text(model, 0) == f"Current date: 2026-09-22\n\n{RAW_PROMPT}"


def test_scripted_supervisor_telemetry_counts_each_of_the_four_tools(state: RunState) -> None:
    """The Supervisor's ``tool_invocations`` count each tool it called; nothing is added to the ledger for it."""
    agent = build_supervisor_agent(_flow_supervisor(), _flow_tools(state), max_drafts=None, hooks=())

    telemetry = run_supervisor(agent, RAW_PROMPT, today=TODAY).telemetry

    counts = {invocation.tool_name: invocation.call_count for invocation in telemetry.tool_invocations}
    assert counts == dict.fromkeys(SUPERVISOR_TOOLS, 1)
    assert (telemetry.model_id, telemetry.reasoning_effort) == ("gpt-5.4", "medium")
    assert [entry.stage for entry in state.ledger] == ["scout", "writer", "qa_legal"]
    assert state.supervisor_summary is None


def test_scripted_supervisor_never_receives_article_text(state: RunState) -> None:
    """D-F: no message the Supervisor model received holds the article's text or an article key."""
    model = _flow_supervisor()
    agent = build_supervisor_agent(model, _flow_tools(state), max_drafts=None, hooks=())

    run_supervisor(agent, RAW_PROMPT, today=TODAY)

    texts = _tool_result_texts(model)
    assert _leaked_article_fields(texts) == []
    results = [json.loads(text) for text in texts]
    assert len(results) == 4
    assert json_keys(results) & FORBIDDEN_SUPERVISOR_KEYS == set()


def _tool_result_texts(model: ScriptedModel) -> list[str]:
    """The text of every tool result the Supervisor model received on its last turn, as each tool returned it."""
    return [
        block["toolResult"]["content"][0]["text"]
        for message in model.received_messages[-1]
        for block in message["content"]
        if "toolResult" in block
    ]


def _leaked_article_fields(texts: Sequence[str]) -> list[str]:
    """The article fields of the scripted draft whose value appears in any of ``texts``, JSON-escaped as there.

    A tool result is JSON, so a value's line break reaches the Supervisor as ``\\n``: the value is matched in its
    escaped form, without its quotes.
    """
    return [
        field
        for field in ARTICLE_FIELDS
        if any(json.dumps(DRAFT_ARGS[field], ensure_ascii=False)[1:-1] in text for text in texts)
    ]


def test_leaked_article_fields_catches_article_text_in_a_tool_result() -> None:
    """A4 / QA-m5: a headline or an article body inside a tool result's JSON is caught, line breaks and all."""
    clean = json.dumps({"result": {"doc_id": DEFAULT_DOC_ID}}, ensure_ascii=False, separators=(",", ":"))
    leaked = json.dumps(
        {"result": {"note": DRAFT_ARGS["headline"], "text": DRAFT_ARGS["article_body"]}},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    assert _leaked_article_fields([clean]) == []
    assert _leaked_article_fields([clean, leaked]) == ["headline", "article_body"]


# ---------------------------------------------------------------------------
# The fatal stop and a failing provider (D-D, D-D.1)
# ---------------------------------------------------------------------------


def _fatal_tools(state: RunState, ran: list[str]) -> list[AgentTool]:
    """``fatal_tool`` records a lost session as a wrapper does (D-D); ``second_tool`` must never run after it."""

    @tool(name="fatal_tool")
    def fatal_tool() -> str:
        """Record a fatal error."""
        ran.append("fatal_tool")
        state.fatal_error = MCPConnectionError("the substrate transport died")
        return "fatal error recorded"

    @tool(name="second_tool")
    def second_tool() -> str:
        """Do the next piece of work."""
        ran.append("second_tool")
        return "second tool ran"

    return [fatal_tool, second_tool]


def test_fatal_stop_returns_an_empty_summary_with_the_telemetry_intact(state: RunState) -> None:
    """D-D.1: once cancelled, the Supervisor returns normally; its last message requested a tool, so has no text."""
    ran: list[str] = []
    model = ScriptedModel([tool_use_turn("fatal_tool", {}), tool_use_turn("second_tool", {}), text_turn("done")])
    agent = build_supervisor_agent(model, _fatal_tools(state, ran), max_drafts=None, hooks=(FatalStopHook(state),))

    output = run_supervisor(agent, RAW_PROMPT, today=TODAY)

    assert output.summary == ""
    assert ran == ["fatal_tool"]
    assert model.turns_consumed == 1
    assert [invocation.tool_name for invocation in output.telemetry.tool_invocations] == ["fatal_tool"]
    assert isinstance(state.fatal_error, MCPConnectionError)


def test_a_provider_error_propagates_out_of_run_supervisor(state: RunState) -> None:
    """A provider or SDK error is not caught: the composition root maps it to ``SUPERVISOR_ERROR`` (Iteration 14)."""
    model = FailingModel(RuntimeError("provider unavailable"))
    with pytest.raises(RuntimeError, match="provider unavailable"):
        run_supervisor(_supervisor(state, model), RAW_PROMPT, today=TODAY)
    assert model.invocations == 1
