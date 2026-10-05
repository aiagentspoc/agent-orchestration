"""The role-bleed audit (P1): which substrate tools each sub-agent's own prompt declares a non-goal.

Every sub-agent is built with all five substrate tools, as in Approach 1 (its D19), and each prompt draws the
boundary. ``StageTelemetry.telemetry.tool_invocations`` records what each call actually used, so the boundary can be
audited after a run. The live tests apply this audit to a real run's ledger; ``tests/test_unit/test_role_bleed.py``
proves the detector offline, so it is never first exercised by a run that costs tokens.

The table is Approach 1's ``NON_GOAL_TOOLS`` (``../code-orchestration/tests/test_integration/test_e2e.py``) without
its ScopeParser row, which Approach 2 does not have. A row lists a tool only when that sub-agent's own prompt has a
clause against the act the tool performs.
"""

from collections.abc import Sequence
from typing import Final

from src.schemas import StageTelemetry
from tests.support.scripted import SUBSTRATE_TOOL_NAMES

#: Stage to the substrate tools its prompt declares a non-goal, each resting on a clause in ``src/agents.py``:
#:
#: * ``scout``: "You do NOT select TDI commercial services or propose calls to action", and "You do NOT verify,
#:   audit or pass judgement on legal citations ... That is QA-Legal's job".
#: * ``writer``: "You do NOT select which regulatory updates are worth covering. That is the Scout's job." The two
#:   feed-discovery tools are how that selection is made.
#: * ``qa_legal``: "You do NOT select, evaluate or write TDI commercial services or calls to action." It has no triage
#:   clause, and Approach 1's live run showed it searching the corpus to check a statutory statement.
NON_GOAL_TOOLS: Final[dict[str, tuple[str, ...]]] = {
    "scout": ("get_tdi_service_offerings", "verify_legal_citation"),
    "writer": ("list_regulatory_updates", "search_regulatory_docs"),
    "qa_legal": ("get_tdi_service_offerings",),
}


def _substrate_tools(entry: StageTelemetry) -> set[str]:
    """The substrate tools one ledger entry used.

    Intersecting with the five substrate tool names is required: Strands records each structured-output call as a
    tool named after its model, such as ``ScoutReport`` or ``QAReport``, which is no substrate tool.
    """
    return {invocation.tool_name for invocation in entry.telemetry.tool_invocations} & set(SUBSTRATE_TOOL_NAMES)


def role_bleed_violations(ledger: Sequence[StageTelemetry]) -> dict[str, set[str]]:
    """The non-goal tools each sub-agent was seen calling, over every entry of the run's ledger.

    Args:
        ledger: The run's ledger: every sub-agent call, failed ones and unsaved documents included.

    Returns:
        Stage to the non-goal tools it called; a stage with none is omitted, so a clean run returns ``{}``.
    """
    observed: dict[str, set[str]] = {}
    for entry in ledger:
        observed.setdefault(entry.stage, set()).update(_substrate_tools(entry))
    violations = {stage: observed.get(stage, set()) & set(forbidden) for stage, forbidden in NON_GOAL_TOOLS.items()}
    return {stage: bled for stage, bled in violations.items() if bled}


def supervisor_substrate_calls(ledger: Sequence[StageTelemetry]) -> set[str]:
    """The substrate tools recorded against the Supervisor, which has none of its own (Q10 = B); ``set()`` if clean."""
    return {tool for entry in ledger if entry.stage == "supervisor" for tool in _substrate_tools(entry)}
