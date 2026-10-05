"""The role-bleed detector the live tests use (P1; Approach 1's Phase 7 audit), checked offline.

The live audit only runs when the user triggers it, so its detector is proven here first: it must fire for every
non-goal its table lists (a positive control), stay quiet for every tool a prompt allows, and never mistake a
structured-output call for a substrate tool. Each row of the table must also rest on a clause of that sub-agent's own
prompt, as Approach 1 required. No model, no substrate.
"""

import pytest

from src.agents import QA_LEGAL_SYSTEM_PROMPT, SCOUT_SYSTEM_PROMPT, WRITER_SYSTEM_PROMPT
from src.schemas import AgentTelemetry, StageTelemetry, ToolInvocation
from tests.support.role_bleed import NON_GOAL_TOOLS, role_bleed_violations, supervisor_substrate_calls
from tests.support.scripted import SUBSTRATE_TOOL_NAMES


def _entry(stage: str, *tool_names: str) -> StageTelemetry:
    """One ledger entry for ``stage`` whose telemetry records one call of each tool named."""
    return StageTelemetry(
        stage=stage,  # type: ignore[arg-type]  # the four stages are a Literal; the tests pass them as strings
        telemetry=AgentTelemetry(
            model_id="gpt-5.4",
            tool_invocations=[ToolInvocation(tool_name=name, call_count=1, success_count=1) for name in tool_names],
        ),
    )


@pytest.mark.parametrize(
    ("stage", "tool_name"),
    [(stage, tool_name) for stage, forbidden in NON_GOAL_TOOLS.items() for tool_name in forbidden],
)
def test_the_detector_fires_for_every_declared_non_goal(stage: str, tool_name: str) -> None:
    """Positive control: each listed non-goal, called by its stage, is reported against that stage."""
    assert role_bleed_violations([_entry(stage, "get_document_by_id", tool_name)]) == {stage: {tool_name}}


def test_the_table_covers_the_three_sub_agents_and_names_only_substrate_tools() -> None:
    """The Scout, Writer and QA-Legal each have a row, and every non-goal is one of the five substrate tools."""
    assert set(NON_GOAL_TOOLS) == {"scout", "writer", "qa_legal"}
    assert all(set(forbidden) <= set(SUBSTRATE_TOOL_NAMES) for forbidden in NON_GOAL_TOOLS.values())


@pytest.mark.parametrize(
    ("prompt", "clause"),
    [
        (SCOUT_SYSTEM_PROMPT, "You do NOT select TDI commercial services or propose calls to action."),
        (SCOUT_SYSTEM_PROMPT, "You do NOT verify, audit or pass judgement on legal citations"),
        (WRITER_SYSTEM_PROMPT, "You do NOT select which regulatory updates are worth covering. That is the Scout's"),
        (QA_LEGAL_SYSTEM_PROMPT, "You do NOT select, evaluate or write TDI commercial services or calls to action."),
    ],
    ids=["scout-tdi", "scout-citations", "writer-triage", "qa-legal-tdi"],
)
def test_every_row_rests_on_a_clause_of_that_sub_agents_own_prompt(prompt: str, clause: str) -> None:
    """A non-goal is what the prompt says, never what a tool is usually for (Approach 1's Phase 7 lesson)."""
    assert clause in prompt


def test_allowed_tools_and_structured_output_calls_are_not_role_bleed() -> None:
    """Strands records structured output as a tool named after its model; that, and every allowed tool, is clean.

    QA-Legal searching the corpus is allowed: its prompt has no triage clause, and Approach 1's live run showed it
    searching to check a statutory statement.
    """
    ledger = [
        _entry("scout", "list_regulatory_updates", "search_regulatory_docs", "get_document_by_id", "ScoutReport"),
        _entry("writer", "get_document_by_id", "verify_legal_citation", "get_tdi_service_offerings", "ArticleDraft"),
        _entry("qa_legal", "verify_legal_citation", "get_document_by_id", "search_regulatory_docs", "QAReport"),
        _entry("supervisor", "scout_tool", "writer_tool", "qa_tool", "save_draft"),
    ]
    assert role_bleed_violations(ledger) == {}
    assert supervisor_substrate_calls(ledger) == set()


def test_violations_are_gathered_across_every_entry_of_a_stage() -> None:
    """Every call counts, failed attempts and other documents included: the ledger holds them all."""
    ledger = [_entry("writer", "list_regulatory_updates"), _entry("writer"), _entry("writer", "search_regulatory_docs")]
    assert role_bleed_violations(ledger) == {"writer": {"list_regulatory_updates", "search_regulatory_docs"}}


def test_a_supervisor_reaching_the_substrate_is_reported() -> None:
    """Q10 = B: the Supervisor has no substrate tool, so any substrate call recorded against it is reported."""
    ledger = [_entry("supervisor", "scout_tool", "get_document_by_id")]
    assert supervisor_substrate_calls(ledger) == {"get_document_by_id"}
    assert role_bleed_violations(ledger) == {}
