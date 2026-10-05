"""The Supervisor: the agent that owns the flow (SPECIFICATIONS.md §1.1, §3, D-C, D-F, D-H, §7.4).

The Supervisor turns the user's prompt into a scope, calls the Scout, chooses the candidates, decides from each QA
report whether to revise or save, and decides when the run is finished. It does so by calling its four tools; this
module only gives it its prompt, builds it, and invokes it once. Nothing here calls a tool or chooses a step.

The system prompt is part of the system under test. Its decision table and run-level priorities are D-C's word for
word, its attempt cap is :data:`~src.schemas.MAX_ATTEMPTS_PER_DOC`, and its tool names are the constants the tools
are registered under; docs tests hold each to its source. Its scope rules are Approach 1's ScopeParser rules,
adapted to the scope fields ``scout_tool`` takes. It never holds the current date, which goes in the user turn.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Final

from strands import Agent
from strands.hooks import HookProvider
from strands.models.model import Model
from strands.tools.executors import SequentialToolExecutor
from strands.types.tools import AgentTool

from .agents import extract_telemetry
from .guardrails import QA_TOOL, SAVE_DRAFT_TOOL, SCOUT_TOOL, WRITER_TOOL
from .hooks import LoggingHooks
from .schemas import MAX_ATTEMPTS_PER_DOC, AgentTelemetry

__all__ = [
    "SUPERVISOR_MODEL_ID",
    "SUPERVISOR_REASONING_EFFORT",
    "SupervisorOutput",
    "build_supervisor_agent",
    "build_supervisor_prompt",
    "run_supervisor",
]

#: The Supervisor's model binding: the strong ``gpt-5.4`` binding (D-H, §6.9).
SUPERVISOR_MODEL_ID: Final[str] = "gpt-5.4"
#: The Supervisor's compiled-in reasoning effort (D-H, Q5 = B); ``ReasoningSettings.supervisor`` defaults to it.
SUPERVISOR_REASONING_EFFORT: Final[str] = "medium"

#: §7.4 Role: the division of labour (§1.1, D-F; Q10 = B). The Supervisor decides what happens next, and nothing else.
_ROLE: Final[str] = """\
You are the Supervisor of the HSE Easy editorial pipeline.

## Role
You supervise agents, not drafts. Each sub-agent does its own job, as defined by its own prompt; you only decide
what happens next. You turn the user's prompt into a scope, call the Scout, decide which candidates to draft, read
each QA report and decide whether to request a revision or save, and decide when the run is finished.
- You never read, judge or edit article text. Full drafts stay with code, and the article is never returned to you.
- You never write feedback for the Writer. Code hands the Writer the latest draft together with the QA report that
  audited it.
- You never write Markdown. Code renders every saved draft into its file when the run ends.
- You have no direct access to the regulatory substrate: every substrate call is made by a sub-agent.
"""

#: §7.4 Tools: the four tools of §7.1, named from the constants the tools are registered under. Their descriptions
#: reach the model in each tool's own specification, word for word, so they are not repeated here.
_TOOLS: Final[str] = f"""\
## Tools
You have four tools, each described in its own specification: `{SCOUT_TOOL}` runs the Scout, `{WRITER_TOOL}` runs
the Writer, `{QA_TOOL}` runs QA-Legal, and `{SAVE_DRAFT_TOOL}` marks a document saved.
"""

#: §7.4 Scope rules: Approach 1's ScopeParser rules (its ``SCOPE_PARSER_SYSTEM_PROMPT``), adapted to the five
#: ``PipelineScope`` fields the Supervisor passes to ``scout_tool`` (DM2). The ``time_window`` rules are dropped; its
#: recency-word rule survives as the default window, and DM3 keeps the scope's limit apart from the run's ceiling.
_SCOPE_RULES: Final[str] = f"""\
## Scope rules
Build the scope for `{SCOUT_TOOL}` from the user's prompt. Work only from what the user wrote; never invent
constraints they did not express.
- `date_from` and `date_to`: absolute ISO `YYYY-MM-DD` dates. The user turn states the current date; resolve every
  date against **that** date and never against your own sense of when "now" is.
- `date_to` is that current date, unless the user named an end date ("up to March 2025", "fino al 31/12/2024"), in
  which case it is theirs.
- `date_from` is the start of the window the user named, counted back from `date_to`. When the user named no
  window, use the past 3 months. Recency words such as "recent", "lately", "current", "latest" or "most recent"
  order results; they do not name a period, so they still give the past 3 months.
- `date_from` must never be later than `date_to`.
- `sources`: any of `EUR_LEX`, `GAZZETTA_UFFICIALE`, `INAIL` that the user named. Leave the list empty when the
  user named none; an empty list means "all sources".
- `sector_constraints`: industrial sectors the user restricted to, lowercase (e.g. `construction`,
  `manufacturing`, `agriculture`). Empty means unrestricted.
- `max_drafts`: an integer ONLY when the user's own words bound how many articles they want. Exactly two forms
  qualify:
  1. A stated count — "at most 3 articles", "just one", "write two pieces".
  2. A **singular definite** request, which names exactly one instrument and is therefore explicit rather than
     inferred — "the latest regulatory update", "the most recent change", "the newest circular", "l'ultimo
     aggiornamento". Set `max_drafts` to 1.
  Everything else MUST be null. A plural or unquantified request bounds nothing: "recent updates", "the latest
  updates", "what changed this quarter", "analizza gli aggiornamenti INAIL" all give `max_drafts: null`. Never
  guess a ceiling and never infer one from the tone or apparent scale of a request. The singular case is not such
  an inference: the user named one document, and one document is one draft.
- The scope's `max_drafts` comes from the user's words only, never from the `--max-drafts` ceiling under Limits,
  which is enforced when you save.
"""

#: D-C's decision table: its header, its column alignment and its ten rows, each cell byte for byte as
#: SPECIFICATIONS.md states it (a docs test compares them), the rule numbers included. Held as cells so no source
#: line runs past the lint limit; rendered by :func:`_markdown_table` into the Markdown D-C writes.
_DECISION_TABLE_HEADER: Final[tuple[str, ...]] = ("QA status", "Attempts remaining", "Condition", "Decision")
_DECISION_TABLE_ALIGNMENT: Final[tuple[str, ...]] = (":---", ":---:", ":---", ":---")
_DECISION_TABLE_ROWS: Final[tuple[tuple[str, str, str, str], ...]] = (
    ("`PASS`", "any", "—", "**Save.** Revising is refused by rule 7"),
    ("`WARNING`", "0", "—", "**Save**"),
    (
        "`WARNING`",
        "≥ 1",
        "At least one issue says a statement in the article is **wrong or unsupported**: a citation, obligation, "
        "deadline, threshold, penalty or date",
        "**Revise**",
    ),
    (
        "`WARNING`",
        "≥ 1",
        "The issues are advisory only (suggestions, optional extra references, notes that require no change), or "
        "there are no issues",
        "**Save**",
    ),
    ("`ERROR`", "0", "—", "**Save,** with the compliance banner"),
    (
        "`ERROR`",
        "≥ 1",
        "Always",
        "**Revise.** There is no early save for `ERROR`: the Writer gets every remaining attempt, and `save_draft` "
        "refuses an `ERROR` while attempts remain (rule 9)",
    ),
    ("Writer call failed", "≥ 1", "No draft exists yet", "**Retry** `writer_tool(revise=False)`"),
    (
        "Writer call failed",
        "≥ 1",
        "An earlier draft exists",
        "Apply this table to the latest draft's QA report; the earlier draft is still the latest one (rule 8)",
    ),
    ("Writer call failed", "0", "No draft exists", "**Skip** the document; it is recorded as unfinished"),
    ("Writer call failed", "0", "An earlier draft exists", "**Save** the earlier draft"),
)


def _markdown_table(header: Sequence[str], alignment: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    """Render a Markdown table as SPECIFICATIONS.md writes one: ``| a | b |`` lines, one per row, header first."""
    return "\n".join(f"| {' | '.join(cells)} |" for cells in (header, alignment, *rows))


#: §7.4 run-level priorities: D-C's two, word for word (a docs test compares them), each one unbroken line.
_RUN_LEVEL_PRIORITIES: Final[tuple[str, ...]] = (
    "**Finish documents before starting new ones.** Take each document to a save or a skip before calling "
    "`writer_tool` on the next candidate.",
    "**Respect the draft ceiling.** Once `drafts_saved` reaches `max_drafts` (the `--max-drafts` ceiling, stated in "
    "the system prompt and in `RunContext`), start no new document: `save_draft` would refuse it (`draft_ceiling`).",
)


def _numbered_list(items: Sequence[str]) -> str:
    """Render ``items`` as a Markdown numbered list, ``1. …``, one line per item."""
    return "\n".join(f"{number}. {item}" for number, item in enumerate(items, start=1))


#: §7.4 decision table and never-compare rule: D-C's Supervisor decision policy, with what the decision may be
#: based on and how a failed Writer call is shown. D-C's rules themselves are enforced in code, not restated here.
_DECISION_POLICY: Final[str] = f"""\
## Decision policy
After every `{WRITER_TOOL}` or `{QA_TOOL}` result, decide the document's next step. Base the decision only on what
you are given, never on article text:
- the latest draft's QA report only: `status`, `issues`, `review_notes`, `verified_citations`;
- the `attempt` number, and `max_attempts_per_doc` from `RunContext` (the `run` object of every result): attempts
  remaining = `max_attempts_per_doc` − `attempt`;
- the candidates still waiting, and `drafts_saved` against `max_drafts`.

Never compare QA reports across attempts. Earlier results remain in your context; decide from the latest report
alone. `issues` is free text: QA-Legal does not tag issues by type. Read the latest report's issue text to judge
whether an issue is one the Writer can fix.

**Decision table:**

{_markdown_table(_DECISION_TABLE_HEADER, _DECISION_TABLE_ALIGNMENT, _DECISION_TABLE_ROWS)}

A failed Writer call is shown to you as `ToolResult.error`, a one-line summary, together with an `AttemptRecord`
that has no draft.

**Run-level priorities,** applied on top of the table:
{_numbered_list(_RUN_LEVEL_PRIORITIES)}
"""


#: §7.4 Violations (D-C, DM16): a refusal is information for the next decision, never the end of the run.
_VIOLATIONS: Final[str] = """\
## Violations
A tool call that breaks one of the rules code enforces is refused: its result's `error` carries a guardrail
violation, with a message saying why. A violation is not the end of the run: read its message and decide again.
"""

#: §7.4 Finishing: the run ends with the Supervisor's own plain-text summary, its final message.
_FINISHING: Final[str] = """\
## Finishing
When you decide the run is finished, end with a plain-text summary of the documents saved, skipped and left
unfinished.
"""

#: The words §7.4 gives the Limits section when the run has no ``--max-drafts`` ceiling.
_NO_CEILING: Final[str] = "no ceiling"


def _limits(max_drafts: int | None) -> str:
    """§7.4 Limits: the attempt cap, from ``MAX_ATTEMPTS_PER_DOC``, and this run's ``--max-drafts`` ceiling."""
    ceiling = _NO_CEILING if max_drafts is None else str(max_drafts)
    revisions = MAX_ATTEMPTS_PER_DOC - 1
    return f"""\
## Limits
- {MAX_ATTEMPTS_PER_DOC} Writer attempts per document: an initial draft plus up to {revisions} revisions.
  Every `{WRITER_TOOL}` call counts as an attempt, whether it succeeds or fails. The same number is
  `max_attempts_per_doc` in the `RunContext` of every result.
- The draft ceiling (`--max-drafts`) for this run: {ceiling}.
"""


def build_supervisor_prompt(max_drafts: int | None) -> str:
    """Build the Supervisor's system prompt, every item of §7.4, for one run's ``--max-drafts`` ceiling.

    The prompt holds no date: the current date goes in the user turn (:func:`run_supervisor`), so the same ceiling
    always builds the same prompt. The ceiling feeds the Limits section only, never the scope rules (DM3).

    Args:
        max_drafts: The run's ``--max-drafts`` ceiling, or ``None`` for none, which the prompt states as "no ceiling".

    Returns:
        The system prompt.
    """
    return "\n".join((_ROLE, _TOOLS, _SCOPE_RULES, _DECISION_POLICY, _limits(max_drafts), _VIOLATIONS, _FINISHING))


def build_supervisor_agent(
    model: Model, tools: Sequence[AgentTool], *, max_drafts: int | None, hooks: Sequence[HookProvider]
) -> Agent:
    """Build the Supervisor: its prompt, its four tools run one after another, and its hooks (D-H, D-D.1, D-I).

    The model is injected: the composition root builds it on the strong binding, :data:`SUPERVISOR_MODEL_ID`, at the
    effort ``ReasoningSettings.supervisor`` resolves, :data:`SUPERVISOR_REASONING_EFFORT` by default.
    ``SequentialToolExecutor`` replaces Strands' concurrent default, so one sub-agent runs at a time and a fatal stop
    also skips a tool requested in the same turn (§8.4).

    Args:
        model: The Supervisor's model.
        tools: The four tools :func:`src.tools.build_tools` returns, and nothing else: no substrate tool (Q10 = B).
        max_drafts: The run's ``--max-drafts`` ceiling, stated in the prompt's Limits section.
        hooks: The Supervisor's own hook providers, ``FatalStopHook`` among them, registered after the one
            ``LoggingHooks("supervisor")`` this builder adds. Passing another ``LoggingHooks`` would log every line
            twice.

    Returns:
        The Supervisor ``Agent``, with no console callback handler.
    """
    return Agent(
        model=model,
        system_prompt=build_supervisor_prompt(max_drafts),
        tools=list(tools),
        callback_handler=None,
        hooks=[LoggingHooks("supervisor"), *hooks],
        tool_executor=SequentialToolExecutor(),
    )


@dataclass(frozen=True)
class SupervisorOutput:
    """What one Supervisor invocation returns: its final plain-text summary and its telemetry.

    A plain value, not one of §6's models: it never crosses into the data model. The composition root stores the
    summary on ``RunState.supervisor_summary`` and hands the telemetry to ``finalise_run``, which appends the
    Supervisor's one ledger entry (DM12).
    """

    summary: str
    telemetry: AgentTelemetry


def run_supervisor(
    agent: Agent,
    prompt: str,
    *,
    today: date,
    model_id: str = SUPERVISOR_MODEL_ID,
    reasoning_effort: str | None = SUPERVISOR_REASONING_EFFORT,
) -> SupervisorOutput:
    """Invoke the Supervisor once over the user's prompt; the Supervisor itself decides every step of the run.

    The user turn is ``Current date: YYYY-MM-DD``, a blank line, then the prompt exactly as given (§7.4). There is
    one invocation and no loop: which tool runs next is the model's choice, never this function's. Errors are not
    caught, so a provider or SDK error reaches the composition root, which maps it to ``SUPERVISOR_ERROR``.

    The summary is the text of the final message, its text blocks joined by line breaks. After a fatal stop
    (D-D.1) the invocation returns normally with ``stop_reason="cancelled"``, and the final message is the one
    that requested the fatal tool, so the summary is usually empty; ``RunState.fatal_error`` says what happened.

    Args:
        agent: The Supervisor, built by :func:`build_supervisor_agent`.
        prompt: The user's raw prompt.
        today: The run's current date, resolved once by the composition root.
        model_id: The model binding recorded in the telemetry.
        reasoning_effort: The effort recorded in the telemetry. The role constant is only the default; the caller
            passes the value it resolved, so an ``.env`` override is recorded as run.

    Returns:
        The summary and the invocation's telemetry. ``RunState`` is left to the composition root.
    """
    result = agent(f"Current date: {today:%Y-%m-%d}\n\n{prompt}")
    summary = "\n".join(block["text"] for block in result.message["content"] if "text" in block)
    return SupervisorOutput(summary=summary, telemetry=extract_telemetry(result, model_id, reasoning_effort))
