"""``src.cli``: the argument parser, the configuration it resolves, and ``main`` (IMPLEMENTATION_PLAN.md Iteration 14).

SPECIFICATIONS.md §7.5. No test here makes a model call (AC3): ``main`` is always given a ``runner``, and the one
test that drives the real ``run`` gives it a model builder that cannot resolve credentials.
"""

import logging
import subprocess
import sys
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Final

import pytest
from strands.models.model import Model

import src.cli as cli_module
from src.app import run
from src.cli import build_arg_parser, build_config, main
from src.credentials import STRONG_MODEL_ID, CredentialManager
from src.logging_setup import LOG_LEVELS
from src.mcp_client import HSEMockMCPClient
from src.schemas import (
    DocumentRecord,
    DraftResult,
    ExitCode,
    FailureRecord,
    PipelineConfig,
    RunContext,
    RunState,
    ScoutCandidate,
)
from tests.support.scripted import DEFAULT_DOC_ID, scout_candidate_args

#: The repository root, worked out here rather than read from the module under test.
REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# build_arg_parser (§7.5)
# ---------------------------------------------------------------------------


def test_the_parser_takes_the_prompt_and_three_options_with_their_defaults() -> None:
    """``PROMPT`` is required; ``--max-drafts`` defaults to none, ``--log-level`` to INFO, ``--drafts-dir`` drafts/."""
    args = build_arg_parser().parse_args(["Analyze INAIL updates"])
    assert vars(args).keys() == {"prompt", "max_drafts", "log_level", "drafts_dir"}
    assert args.prompt == "Analyze INAIL updates"
    assert args.max_drafts is None
    assert args.log_level == "INFO"
    assert args.drafts_dir == str(REPO_ROOT / "drafts")


def test_the_parser_reads_each_option() -> None:
    """``--max-drafts`` is an integer; the prompt is kept exactly as given, surrounding spaces included."""
    args = build_arg_parser().parse_args(
        ["  a prompt  ", "--max-drafts", "2", "--log-level", "WARNING", "--drafts-dir", "out"]
    )
    assert (args.prompt, args.max_drafts, args.log_level, args.drafts_dir) == ("  a prompt  ", 2, "WARNING", "out")


@pytest.mark.parametrize("level", LOG_LEVELS)
def test_the_parser_accepts_each_specified_log_level(level: str) -> None:
    """§7.5: ``{DEBUG,INFO,WARNING,ERROR}``, the levels the logging module resolves."""
    assert build_arg_parser().parse_args(["p", "--log-level", level]).log_level == level
    assert LOG_LEVELS == ("DEBUG", "INFO", "WARNING", "ERROR")


@pytest.mark.parametrize(
    "argv",
    [[], ["p", "--log-level", "WARN"], ["p", "--log-level", "info"], ["p", "--max-drafts", "two"]],
    ids=["no_prompt", "approach_1_warn", "lower_case", "non_integer_ceiling"],
)
def test_the_parser_rejects_what_section_7_5_does_not_allow(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    """A missing prompt, a level outside §7.5's four, or a non-integer ceiling is a usage error."""
    with pytest.raises(SystemExit) as raised:
        build_arg_parser().parse_args(argv)
    assert raised.value.code == 2
    capsys.readouterr()


def test_the_parser_is_named_for_its_entry_point() -> None:
    """The usage line names ``python -m src.cli``, the documented entry point."""
    assert build_arg_parser().prog == "python -m src.cli"


# ---------------------------------------------------------------------------
# build_config: every path absolute (§7.5)
# ---------------------------------------------------------------------------


def test_build_config_resolves_the_defaults_to_absolute_repository_paths() -> None:
    """The drafts and logs folders and the shipped template, all absolute; the ceiling and level as parsed."""
    config = build_config(build_arg_parser().parse_args(["p", "--max-drafts", "3", "--log-level", "ERROR"]))

    assert config.max_drafts == 3 and config.log_level == "ERROR"
    assert config.drafts_dir == REPO_ROOT / "drafts"
    assert config.log_dir == REPO_ROOT / "logs"
    assert config.template_path == REPO_ROOT / ".agents" / "templates" / "draft.md"
    assert config.template_path.is_file()
    assert all(path.is_absolute() for path in (config.drafts_dir, config.log_dir, config.template_path))


def test_build_config_resolves_a_relative_drafts_dir_against_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§7.5: paths are made absolute when the configuration is built, so nothing later depends on the cwd."""
    monkeypatch.chdir(tmp_path)
    config = build_config(build_arg_parser().parse_args(["p", "--drafts-dir", "out"]))
    assert config.drafts_dir == (tmp_path / "out").resolve()


def test_build_config_takes_a_log_dir_override_made_absolute(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The log directory seam ``main`` passes on, resolved like every other path."""
    monkeypatch.chdir(tmp_path)
    config = build_config(build_arg_parser().parse_args(["p"]), log_dir=Path("my-logs"))
    assert config.log_dir == (tmp_path / "my-logs").resolve()


# ---------------------------------------------------------------------------
# _resolve_redaction_key: the strong model's key, as Approach 1 (P10)
# ---------------------------------------------------------------------------

#: Credentials that resolve; neither key is real.
_CREDENTIALS: Final[dict[str, str]] = {
    "HSE_MODEL_FAST_ENDPOINT": "https://fast.example.invalid/openai/v1",
    "HSE_MODEL_FAST_API_KEY": "sk-fast-not-a-real-key",
    "HSE_MODEL_STRONG_ENDPOINT": "https://strong.example.invalid/openai/v1",
    "HSE_MODEL_STRONG_API_KEY": "sk-strong-not-a-real-key",
}


def test_the_redaction_key_is_none_and_a_warning_says_why_without_credentials(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An unconfigured checkout has no key to leak; the warning is the operator's first sign the run will fail."""
    with caplog.at_level(logging.WARNING, logger="src.cli"):
        assert cli_module._resolve_redaction_key() is None

    [warning] = [record for record in caplog.records if record.name == "src.cli"]
    assert warning.levelno == logging.WARNING and warning.exc_info is not None
    assert ".env.example" in warning.getMessage()
    assert "HSE_MODEL_STRONG_API_KEY" in caplog.text


def test_the_redaction_key_is_the_strong_model_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """P10: the strong key alone is masked, exactly as in Approach 1."""
    for name, value in _CREDENTIALS.items():
        monkeypatch.setenv(name, value)
    assert cli_module._resolve_redaction_key() == "sk-strong-not-a-real-key"
    assert STRONG_MODEL_ID == "gpt-5.4"


# ---------------------------------------------------------------------------
# main: logging, the runner, the status lines and the exit code
# ---------------------------------------------------------------------------

#: A key the tests hand ``main``; it must never reach the log file.
_API_KEY: Final[str] = "sk-test-not-a-real-key-0123456789"


class _Runner:
    """A ``runner`` that records what it was called with, logs one line with the key in it, and returns ``state``."""

    def __init__(self, state_for: Callable[[PipelineConfig], RunState]) -> None:
        self._state_for = state_for
        self.calls: list[tuple[str, PipelineConfig]] = []

    def __call__(self, prompt: str, config: PipelineConfig) -> RunState:
        self.calls.append((prompt, config))
        logging.getLogger("src.app").info("runner line carrying the key %s", _API_KEY)
        return self._state_for(config)


def _finished_state(config: PipelineConfig, code: ExitCode = ExitCode.SUCCESS) -> RunState:
    """A finished run: one saved PASS draft, one recoverable failure, and ``code``."""
    candidate = ScoutCandidate.model_validate(scout_candidate_args(DEFAULT_DOC_ID, 0.9, "Obblighi immediati."))
    draft_id = f"draft_{date.today():%Y%m%d}_001"
    document = DocumentRecord(
        candidate=candidate,
        saved=DraftResult(
            doc_id=DEFAULT_DOC_ID, draft_id=draft_id, path=config.drafts_dir / f"{draft_id}.md", qa_status="PASS"
        ),
    )
    return RunState(
        run_id="run-cli",
        config=config,
        context=RunContext(today=date.today(), max_drafts=config.max_drafts, drafts_saved=1),
        documents={DEFAULT_DOC_ID: document},
        failures=[
            FailureRecord(doc_id=None, attempt=None, stage="scout", error_type="builtins.RuntimeError", message="x")
        ],
        exit_code=code,
        supervisor_summary="Salvato: una bozza — PASS.",
    )


@pytest.mark.usefixtures("restore_logging")
def test_main_runs_the_prompt_verbatim_and_returns_the_exit_code_as_an_int(tmp_path: Path) -> None:
    """``main(argv)`` returns an ``int``, never the enum and never ``SystemExit`` (§7.5)."""
    runner = _Runner(lambda config: _finished_state(config, ExitCode.PERSISTENCE_ERROR))

    code = main(
        ["  Analyze INAIL updates  ", "--max-drafts", "1", "--drafts-dir", str(tmp_path / "drafts")],
        runner=runner,
        log_dir=tmp_path / "logs",
        api_key=_API_KEY,
    )

    assert type(code) is int and code == 4
    [(prompt, config)] = runner.calls
    assert prompt == "  Analyze INAIL updates  "
    assert config.max_drafts == 1
    assert config.drafts_dir == (tmp_path / "drafts").resolve()
    assert config.log_dir == (tmp_path / "logs").resolve()


@pytest.mark.usefixtures("restore_logging")
def test_main_logs_to_the_dated_file_with_the_key_redacted(tmp_path: Path) -> None:
    """D-I: one file per day, ``run_YYYYMMDD.log`` under the log directory; the key is masked (P10)."""
    main(["p"], runner=_Runner(_finished_state), log_dir=tmp_path / "logs", api_key=_API_KEY)

    log_file = tmp_path / "logs" / f"run_{date.today():%Y%m%d}.log"
    text = log_file.read_text(encoding="utf-8")
    assert "runner line carrying the key [REDACTED]" in text
    assert _API_KEY not in text


@pytest.mark.usefixtures("restore_logging")
def test_main_prints_ascii_status_lines(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """stdout is the CLI's status: the exit code, the candidates, each saved draft and each failure, in ASCII.

    The Supervisor's summary, which may hold any character, goes to the log only.
    """
    main(["p"], runner=_Runner(_finished_state), log_dir=tmp_path / "logs", api_key=_API_KEY)

    out = capsys.readouterr().out
    assert out.isascii()
    lines = out.splitlines()
    assert lines[0] == "Exit code: 0 (SUCCESS)"
    assert "Candidates considered: 1" in lines
    assert any(line.startswith(f"Saved draft_{date.today():%Y%m%d}_001 [PASS] -> ") for line in lines)
    assert "Failed at scout: builtins.RuntimeError" in lines


@pytest.mark.usefixtures("restore_logging")
def test_main_over_the_real_run_exits_config_error_without_credentials(tmp_path: Path) -> None:
    """End to end through ``run``: an unconfigured checkout exits 5, never 1, which would read as a quiet feed."""

    def runner(prompt: str, config: PipelineConfig) -> RunState:
        return run(prompt, config, client_factory=_no_session, model_builder=_unconfigured_model_builder)

    code = main(["Analizza INAIL", "--drafts-dir", str(tmp_path / "drafts")], runner=runner, log_dir=tmp_path / "logs")

    assert type(code) is int
    assert code == int(ExitCode.CONFIG_ERROR) == 5
    log_text = (tmp_path / "logs" / f"run_{date.today():%Y%m%d}.log").read_text(encoding="utf-8")
    assert "Configuration failure" in log_text and "Run completed: exit_code=5 (CONFIG_ERROR)" in log_text


def _unconfigured_model_builder(model_id: str, *, reasoning_effort: str | None = None) -> Model:
    """An unconfigured checkout: ``CredentialManager`` rejects an environment with no credentials."""
    CredentialManager(_env_file=None)
    raise AssertionError("unreachable: CredentialManager must reject an unconfigured environment")


def _no_session() -> HSEMockMCPClient:
    """A client factory that fails the test: a run that cannot be configured opens no session."""
    raise AssertionError("a run that cannot be configured must not open the substrate session")


@pytest.mark.usefixtures("restore_logging")
def test_main_refuses_a_run_with_no_exit_code(tmp_path: Path) -> None:
    """``run`` sets the exit code on every path; a runner that does not is a defect, never reported as success."""

    def runner(prompt: str, config: PipelineConfig) -> RunState:
        return _finished_state(config).model_copy(update={"exit_code": None})

    with pytest.raises(RuntimeError, match="no exit code"):
        main(["p"], runner=runner, log_dir=tmp_path / "logs", api_key=_API_KEY)


# ---------------------------------------------------------------------------
# python -m src.cli --help (AC2)
# ---------------------------------------------------------------------------


def test_help_exits_zero_and_prints_the_four_arguments_in_ascii() -> None:
    """AC2: the entry point runs as a module and documents §7.5's four arguments; no run starts."""
    completed = subprocess.run(
        [sys.executable, "-m", "src.cli", "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        timeout=120,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    out = completed.stdout.decode("ascii")
    assert out.startswith("usage: python -m src.cli ")
    for argument in ("PROMPT", "--max-drafts N", "--log-level {DEBUG,INFO,WARNING,ERROR}", "--drafts-dir DIR"):
        assert argument in out
