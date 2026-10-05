"""Live end-to-end tests: the real Supervisor and sub-agents on the real models, over the local substrate (P4, P14).

**Only the user runs these**, with ``uv run pytest -m live``. Every test here is marked ``live``, so the default run
deselects them all, and each is skipped when ``agent-orchestration/.env`` is absent. A run spends real tokens:
Approach 1's run of Prompt A took about 8.5 minutes and cost $0.78.

Each test drives the real command line, ``src.cli.main``, with the real ``src.app.run`` behind a wrapper that keeps
the run's state, so logging is configured and the API key redacted exactly as for a user's run. The benchmark
constants are left alone: the default ``build_model``, the ``.env`` efforts and rates, the system clock, and no
``--max-drafts``. Drafts and logs go to ``tmp_path``, never to the repository's ``drafts/`` and ``logs/``.

The tests assert outcomes, guardrails and the role boundaries, never a call sequence: the Supervisor decides the
path (SPECIFICATIONS.md D-J). The checks they apply are proven offline in ``tests/test_unit/test_live_checks.py``
and ``tests/test_unit/test_role_bleed.py``. Importing this module builds nothing and reads nothing.
"""

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Final

import pytest

from src.app import run
from src.cli import main
from src.costs import CostSettings
from src.credentials import CredentialManager, ReasoningSettings
from src.schemas import ExitCode, PipelineConfig, RunState
from tests.support.live_checks import months_before, saved_draft_problems
from tests.support.role_bleed import role_bleed_violations, supervisor_substrate_calls
from tests.support.scripted import REPO_ROOT

#: Approach 1's benchmark prompt (SPECIFICATIONS.md §2.3): exit 0, 3 drafts, 223,970 tokens and $0.7803 on
#: 2026-09-24.
PROMPT_A: Final[str] = "Analyze INAIL updates on heat stress published since 2024"
#: A prompt that names no window, so the Supervisor applies its default of the past 3 months (§7.4, P14).
PROMPT_B: Final[str] = "Analyze recent INAIL updates on heat stress"

#: The ``.env`` the live tests read: the repository's own, wherever pytest is started from.
DOTENV: Final[Path] = REPO_ROOT / ".env"
#: How far the Supervisor's default window may start from the run date minus 3 months, in days (P14).
WINDOW_START_TOLERANCE_DAYS: Final[int] = 3

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not DOTENV.is_file(),
        reason="agent-orchestration/.env is absent: copy .env.example to .env and fill in the credentials",
    ),
    pytest.mark.usefixtures("restore_logging"),
]


@dataclass(frozen=True)
class LiveRun:
    """One live run: the state ``src.app.run`` returned, and the folder its drafts were written to."""

    state: RunState
    drafts_dir: Path


#: Each prompt's run, kept for the session so the role-bleed audit reads the same runs the prompt tests checked
#: rather than paying for them twice.
_RUNS: dict[str, LiveRun] = {}
#: Each prompt whose run raised, with what it raised, so a crash fails every test sharing the run but is paid once.
_FAILED_RUNS: dict[str, Exception] = {}


@pytest.fixture(autouse=True)
def _read_the_repository_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    """Read ``agent-orchestration/.env``, whatever the working directory.

    The settings classes read ``.env`` from the working directory; ``tests/conftest.py``'s isolation leaves a
    ``live`` test alone, so this pins the file to the repository's for all three, and monkeypatch restores them.
    """
    for settings_class in (CredentialManager, CostSettings, ReasoningSettings):
        monkeypatch.setitem(settings_class.model_config, "env_file", DOTENV)


def _live_run(prompt: str, tmp_path_factory: pytest.TempPathFactory) -> LiveRun:
    """Run ``prompt`` once per session through the real command line, and return what it left.

    A run that raised is not run again: later callers fail at once, naming what it raised.

    Raises:
        AssertionError: If the command line's exit code is not the run's, or if this prompt's run already failed.
    """
    if prompt in _FAILED_RUNS:
        failure = _FAILED_RUNS[prompt]
        raise AssertionError(f"this prompt's live run already failed in this session: {failure!r}") from failure
    if prompt not in _RUNS:
        try:
            _RUNS[prompt] = _run_through_the_cli(prompt, tmp_path_factory.mktemp("live_run"))
        except Exception as exc:
            _FAILED_RUNS[prompt] = exc
            raise
    return _RUNS[prompt]


def _run_through_the_cli(prompt: str, root: Path) -> LiveRun:
    """Run ``prompt`` through ``src.cli.main`` with its drafts and logs under ``root``, keeping the run's state.

    Raises:
        AssertionError: If the command line's exit code is not the run's.
    """
    captured: list[RunState] = []

    def runner(run_prompt: str, config: PipelineConfig) -> RunState:
        state = run(run_prompt, config)
        captured.append(state)
        return state

    drafts_dir = root / "drafts"
    code = main([prompt, "--drafts-dir", str(drafts_dir)], runner=runner, log_dir=root / "logs")
    (state,) = captured
    assert state.exit_code is not None and code == int(state.exit_code), (code, state.exit_code)
    return LiveRun(state=state, drafts_dir=drafts_dir)


def _outcome(state: RunState) -> str:
    """The run's outcome, for a failure message: exit code, failures, violations and the Supervisor's summary."""
    code = "None" if state.exit_code is None else state.exit_code.name
    failures = [f"{failure.stage}:{failure.error_type}" for failure in state.failures]
    violations = [f"{violation.guardrail}@{violation.tool_name}" for violation in state.violations]
    return f"exit={code} failures={failures} violations={violations} summary={state.supervisor_summary!r}"


def test_prompt_a_runs_to_sound_drafts(tmp_path_factory: pytest.TempPathFactory) -> None:
    """Prompt A, the benchmark prompt: exit 0 and sound drafts.

    At least one draft is saved and written; none leaves a template token; each used at most 3 Writer attempts and
    renders that count; every ``ERROR`` draft carries the compliance banner; every draft is Approach 2's. No
    violation ended the run: violations may occur, and are listed in the message, but the run reaches exit 0
    with no fatal stop (AGENTS.md Rule 3).
    """
    live = _live_run(PROMPT_A, tmp_path_factory)
    state = live.state
    assert state.exit_code is ExitCode.SUCCESS, _outcome(state)
    assert state.fatal_error is None, _outcome(state)
    assert saved_draft_problems(state, live.drafts_dir) == [], _outcome(state)


def test_prompt_b_applies_the_recency_rule(tmp_path_factory: pytest.TempPathFactory) -> None:
    """Prompt B names no window, so the Supervisor's scope is the past 3 months to the run date, INAIL only (P14).

    Exit 0 and exit 1 are both valid. The Scout's input carries no topic, and the corpus on disk (P7) holds INAIL
    updates dated 2026-07-15 and 2026-08-20, so whether the window holds a qualifying update depends on the run
    date. With exit 1 nothing is written; with exit 0 Prompt A's draft checks apply, at least one draft included.
    """
    live = _live_run(PROMPT_B, tmp_path_factory)
    state = live.state
    assert state.exit_code in {ExitCode.SUCCESS, ExitCode.NO_UPDATES}, _outcome(state)
    assert state.fatal_error is None, _outcome(state)
    assert state.scope is not None, _outcome(state)
    today = state.context.today
    assert state.scope.date_to == today.isoformat(), state.scope
    window_start = months_before(today, 3)
    assert abs((date.fromisoformat(state.scope.date_from) - window_start).days) <= WINDOW_START_TOLERANCE_DAYS, (
        state.scope,
        window_start,
    )
    assert list(state.scope.sources) == ["INAIL"], state.scope
    if state.exit_code is ExitCode.NO_UPDATES:
        assert state.documents == {}, _outcome(state)
        assert sorted(live.drafts_dir.glob("draft_*.md")) == [], _outcome(state)
    else:
        assert saved_draft_problems(state, live.drafts_dir) == [], _outcome(state)


@pytest.mark.parametrize("prompt", [PROMPT_A, PROMPT_B], ids=["prompt-a", "prompt-b"])
def test_no_sub_agent_calls_a_tool_its_prompt_declares_a_non_goal(
    prompt: str, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """The role-bleed audit (P1), over every ledger entry of the run, unsaved documents and failed calls included.

    Every sub-agent holds all five substrate tools; its prompt draws the boundary, and ``tool_invocations``
    shows whether it held. The Supervisor has no substrate tool at all (Q10 = B).
    """
    state = _live_run(prompt, tmp_path_factory).state
    assert role_bleed_violations(state.ledger) == {}, _outcome(state)
    assert supervisor_substrate_calls(state.ledger) == set(), _outcome(state)
