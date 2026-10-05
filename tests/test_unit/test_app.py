"""``src.app``'s exit-code mapping, a pure function of the run's outcome (SPECIFICATIONS.md §7.6, P6, P13).

The composition root itself is tested end to end in ``tests/test_integration/test_app.py``; here the mapping is
pinned exhaustively, every combination of its six conditions, without building a run.
"""

import itertools
from typing import Final

import pytest

from src.app import _exit_code
from src.schemas import ExitCode

#: The helper's six conditions, in its keyword order.
_FLAGS: Final[tuple[str, ...]] = (
    "fatal_stop",
    "session_lost",
    "supervisor_raised",
    "scout_succeeded",
    "no_candidates",
    "persistence_failed",
)


def _flags(**set_flags: bool) -> dict[str, bool]:
    """Every condition ``False`` except the ones given."""
    return {flag: set_flags.get(flag, False) for flag in _FLAGS}


@pytest.mark.parametrize(
    ("flags", "expected"),
    [
        # §7.6 row by row, each condition alone (a run whose Scout succeeded unless the row is about the Scout).
        (_flags(scout_succeeded=True), ExitCode.SUCCESS),
        (_flags(scout_succeeded=True, no_candidates=True), ExitCode.NO_UPDATES),
        (_flags(scout_succeeded=True, fatal_stop=True), ExitCode.MCP_ERROR),
        (_flags(scout_succeeded=True, session_lost=True), ExitCode.MCP_ERROR),
        (_flags(), ExitCode.PARSER_ERROR),
        (_flags(scout_succeeded=True, persistence_failed=True), ExitCode.PERSISTENCE_ERROR),
        (_flags(scout_succeeded=True, supervisor_raised=True), ExitCode.SUPERVISOR_ERROR),
    ],
    ids=["success", "no_updates", "fatal_stop", "session_lost", "parser_error", "persistence_error", "supervisor"],
)
def test_each_exit_code_condition_alone(flags: dict[str, bool], expected: ExitCode) -> None:
    """Each §7.6 condition, holding alone, gives its own code."""
    assert _exit_code(**flags) is expected


@pytest.mark.parametrize(
    ("flags", "expected"),
    [
        (_flags(fatal_stop=True), ExitCode.MCP_ERROR),  # P13: a session lost at the Scout is not PARSER_ERROR
        (_flags(), ExitCode.PARSER_ERROR),  # P13: ended on its own, no successful Scout
        (_flags(supervisor_raised=True), ExitCode.SUPERVISOR_ERROR),  # it raised, so it did not end on its own
        (_flags(fatal_stop=True, supervisor_raised=True), ExitCode.SUPERVISOR_ERROR),  # P6
        (_flags(fatal_stop=True, persistence_failed=True), ExitCode.PERSISTENCE_ERROR),  # P6; P13 excludes the 3
        # Close-time death: the session died as it closed, after a Supervisor that ended on its own with no
        # successful Scout. No fatal stop occurred, so P13 holds, and P6 combines it with the lost session.
        (_flags(session_lost=True), ExitCode.PARSER_ERROR),
        (_flags(fatal_stop=True, scout_succeeded=True), ExitCode.MCP_ERROR),  # fatal after the Scout ran
    ],
    ids=[
        "fatal_at_scout",
        "ended_without_scout",
        "raised_without_scout",
        "fatal_and_raised",
        "fatal_and_persistence",
        "close_time_death_without_scout",
        "fatal_after_scout",
    ],
)
def test_p13_parser_error_needs_a_supervisor_that_ended_on_its_own(flags: dict[str, bool], expected: ExitCode) -> None:
    """P13: ``PARSER_ERROR`` only when the Supervisor ended its own invocation, with no fatal stop and no Scout."""
    assert _exit_code(**flags) is expected


def _conditions_holding(flags: dict[str, bool]) -> list[ExitCode]:
    """The codes of the §7.6 conditions that hold, read as P13 states them.

    This oracle restates the helper's conditions, so it pins only that their combination is the numeric maximum
    (P6). The independent check of each condition is the two explicit tables above, written from §7.6 and P13.
    """
    holding = [ExitCode.SUCCESS]
    if flags["fatal_stop"] or flags["session_lost"]:
        holding.append(ExitCode.MCP_ERROR)
    if flags["supervisor_raised"]:
        holding.append(ExitCode.SUPERVISOR_ERROR)
    if not flags["supervisor_raised"] and not flags["fatal_stop"] and not flags["scout_succeeded"]:
        holding.append(ExitCode.PARSER_ERROR)
    if flags["no_candidates"]:
        holding.append(ExitCode.NO_UPDATES)
    if flags["persistence_failed"]:
        holding.append(ExitCode.PERSISTENCE_ERROR)
    return holding


@pytest.mark.parametrize(
    "values",
    list(itertools.product((False, True), repeat=len(_FLAGS))),
    ids=lambda values: "".join("FT"[value] for value in values),
)
def test_every_combination_is_the_numeric_maximum_of_the_conditions_holding(values: tuple[bool, ...]) -> None:
    """P6: whatever holds together, the most severe code wins, severity being the number; ``SUCCESS`` is the floor."""
    flags: dict[str, bool] = dict(zip(_FLAGS, values, strict=True))
    assert _exit_code(**flags) is max(_conditions_holding(flags))


def test_the_conditions_are_keyword_only() -> None:
    """Six booleans in a row are easy to transpose, so none can be passed by position."""
    with pytest.raises(TypeError):
        _exit_code(False, False, False, False, False, False)  # type: ignore[misc]
