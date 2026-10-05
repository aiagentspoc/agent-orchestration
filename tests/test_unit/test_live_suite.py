"""The live suite's own contract, checked offline (Iteration 16, acceptance criteria 1 and 2; P4).

The default run deselects every ``live`` test through ``addopts = "-m 'not live'"`` (pinned by ``test_packaging``).
That only holds if every test under ``tests/test_live/`` carries the marker, so this module checks it, together with
the skip rule and the benchmark prompts the live tests run. Importing the live modules here is itself a check: it
happens under the default isolation, with no credentials, so a module that built a model or read ``.env`` at import
would fail here rather than spend tokens.
"""

import importlib
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LIVE_DIR = REPO_ROOT / "tests" / "test_live"


def _live_modules() -> list[ModuleType]:
    """Import every ``test_*.py`` module under ``tests/test_live/``."""
    return [importlib.import_module(f"tests.test_live.{path.stem}") for path in sorted(LIVE_DIR.glob("test_*.py"))]


def _module_marks(module: ModuleType) -> list[pytest.Mark]:
    """The marks a module applies to all its tests through ``pytestmark``."""
    declared = getattr(module, "pytestmark", [])
    decorators = declared if isinstance(declared, list) else [declared]
    return [decorator.mark for decorator in decorators]


def test_the_live_folder_holds_the_live_end_to_end_module() -> None:
    """``tests/test_live/`` is a package holding the live end-to-end tests (IMPLEMENTATION_PLAN.md §4)."""
    assert (LIVE_DIR / "__init__.py").is_file()
    assert [module.__name__ for module in _live_modules()] == ["tests.test_live.test_live_e2e"]


def test_every_live_module_marks_all_its_tests_live() -> None:
    """A module-level ``live`` mark covers every test in it, so the default run deselects all of them (AC1)."""
    modules = _live_modules()
    assert modules, "no live module found"
    for module in modules:
        assert "live" in [mark.name for mark in _module_marks(module)], module.__name__
        assert [name for name in vars(module) if name.startswith("test_")], module.__name__


def test_the_live_tests_skip_with_a_reason_when_the_dotenv_is_absent() -> None:
    """Without ``agent-orchestration/.env`` a live test is skipped, and says what to do; collection still lists it."""
    modules = _live_modules()
    assert modules, "no live module found"
    for module in modules:
        (skip,) = [mark for mark in _module_marks(module) if mark.name == "skipif"]
        # The repository's own .env, never one relative to the directory pytest was started from.
        assert module.DOTENV == REPO_ROOT / ".env", module.__name__
        assert skip.args == (not (REPO_ROOT / ".env").is_file(),)
        assert "agent-orchestration/.env" in skip.kwargs["reason"]
        assert ".env.example" in skip.kwargs["reason"]


def test_the_live_tests_run_the_benchmark_prompts() -> None:
    """Prompt A is Approach 1's benchmark prompt (SPECIFICATIONS.md §2.3); Prompt B states no window (P14)."""
    live = importlib.import_module("tests.test_live.test_live_e2e")
    assert live.PROMPT_A == "Analyze INAIL updates on heat stress published since 2024"
    assert live.PROMPT_B == "Analyze recent INAIL updates on heat stress"
    assert {"test_prompt_a_runs_to_sound_drafts", "test_prompt_b_applies_the_recency_rule"} <= set(vars(live))
    assert "test_no_sub_agent_calls_a_tool_its_prompt_declares_a_non_goal" in vars(live)


def test_a_failed_live_run_is_not_paid_for_twice(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """Prompt A's run is shared by two tests: if it crashes, the second test reports the crash rather than rerunning.

    The command line is replaced by one that fails at once, so nothing is built and nothing is spent.
    """
    live = importlib.import_module("tests.test_live.test_live_e2e")
    calls: list[list[str]] = []

    def crashing_main(argv: list[str], **_: object) -> int:
        calls.append(argv)
        raise RuntimeError("the model endpoint refused the call")

    monkeypatch.setattr(live, "main", crashing_main)
    monkeypatch.setattr(live, "_RUNS", {})
    monkeypatch.setattr(live, "_FAILED_RUNS", {})
    with pytest.raises(RuntimeError, match="refused"):
        live._live_run(live.PROMPT_A, tmp_path_factory)
    with pytest.raises(AssertionError, match="already failed"):
        live._live_run(live.PROMPT_A, tmp_path_factory)
    assert len(calls) == 1


def test_the_readme_gives_the_users_live_benchmark_commands() -> None:
    """The user, not an assistant, runs the live benchmark (P4), so the README states each command in full."""
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "## Running the live benchmark" in readme
    section = readme.split("## Running the live benchmark", 1)[1].split("\n## ", 1)[0]
    for command in (
        "uv run pytest -m live",
        'uv run python -m src.cli "Analyze INAIL updates on heat stress published since 2024"',
        "uv run python -m src.benchmark --a1 ../code-orchestration/drafts --a2 drafts --out .agents/docs/BENCHMARK.md",
        "--a1-logs",
        "--a2-logs",
    ):
        assert command in section, command
