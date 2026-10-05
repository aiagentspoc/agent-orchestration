"""The command line: ``python -m src.cli PROMPT [--max-drafts N] [--log-level LEVEL] [--drafts-dir DIR]`` (§7.5).

The module has no import-time side effects: logging is configured, and a run started, only when :func:`main` is
called. Everything it prints is ASCII, because a Windows console is routinely on a legacy code page.
"""

import argparse
import logging
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Final, TypeAlias

from pydantic import ValidationError

from .app import run
from .credentials import STRONG_MODEL_ID, CredentialManager
from .logging_setup import LOG_LEVELS, configure_logging
from .schemas import PipelineConfig, RunState

__all__ = ["REPO_ROOT", "Runner", "build_arg_parser", "build_config", "main"]

_LOGGER = logging.getLogger("src.cli")

#: The repository root, which the default drafts, logs and template paths are resolved against.
REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[1]

#: Seam for the run entry point: ``src.app.run`` with its defaults, or a test's stand-in.
Runner: TypeAlias = Callable[[str, PipelineConfig], RunState]


def build_arg_parser() -> argparse.ArgumentParser:
    """Build the CLI parser exactly as SPECIFICATIONS.md §7.5 defines it.

    Returns:
        The parser for ``PROMPT`` and its three options. Nothing beyond §7.5 is validated.
    """
    parser = argparse.ArgumentParser(
        prog="python -m src.cli",
        description="Run the HSE Easy Research Analyst: a Supervisor agent drafts articles from regulatory updates.",
    )
    parser.add_argument(
        "prompt", metavar="PROMPT", help="The natural-language task, passed to the Supervisor verbatim."
    )
    parser.add_argument(
        "--max-drafts",
        type=int,
        default=None,
        metavar="N",
        help="The draft ceiling, enforced when a draft is saved and stated in the Supervisor's prompt "
        "(default: none).",
    )
    parser.add_argument(
        "--log-level",
        choices=LOG_LEVELS,
        default="INFO",
        help="Logging verbosity; DEBUG adds provider request bodies (default: INFO).",
    )
    parser.add_argument(
        "--drafts-dir",
        default=str(REPO_ROOT / "drafts"),
        metavar="DIR",
        help="Where the drafts are written at run end (default: drafts/).",
    )
    return parser


def build_config(args: argparse.Namespace, *, log_dir: Path | None = None) -> PipelineConfig:
    """Resolve the parsed arguments into the run configuration, every path absolute (§7.5).

    Approach 1's ``build_config``. The template is the shipped one at the repository root, never a copy, and the
    one divergence is that a ``log_dir`` override is resolved too, as every other path is.

    Args:
        args: The parsed CLI namespace.
        log_dir: Override for the log directory; defaults to ``<repo>/logs``.

    Returns:
        The :class:`~src.schemas.PipelineConfig` for this run.
    """
    return PipelineConfig(
        max_drafts=args.max_drafts,
        log_level=args.log_level,
        drafts_dir=Path(args.drafts_dir).resolve(),
        template_path=REPO_ROOT / ".agents" / "templates" / "draft.md",
        log_dir=log_dir.resolve() if log_dir is not None else REPO_ROOT / "logs",
    )


def _resolve_redaction_key() -> str | None:
    """Read the strong model's API key so the log filter can mask it (Approach 1's, unchanged; P10).

    Returns ``None`` when credentials are not configured: there is then no key to leak, and the run itself fails
    with ``CONFIG_ERROR`` a moment later. Only a settings ``ValidationError`` is handled, and it is logged in full
    rather than swallowed, because this is the earliest point at which an operator can be told the checkout is
    unconfigured.
    """
    try:
        return CredentialManager().for_model(STRONG_MODEL_ID).api_key.get_secret_value()
    except ValidationError as exc:
        _LOGGER.warning(
            "Model credentials could not be resolved, so no API key will be redacted from the logs; "
            "the run will fail to configure. See .env.example for the required variables.",
            exc_info=exc,
        )
        return None


def main(
    argv: Sequence[str] | None = None,
    *,
    runner: Runner = run,
    log_dir: Path | None = None,
    api_key: str | None = None,
) -> int:
    """Parse the arguments, configure logging, run once, print the status and return the exit code.

    Returns an ``int`` rather than raising ``SystemExit``: only the ``__main__`` guard turns it into the process's
    exit status. A usage error is argparse's own exit 2, before any run starts.

    Args:
        argv: The command-line arguments; ``sys.argv[1:]`` when omitted.
        runner: The run entry point; tests inject one so no test makes a model call.
        log_dir: Override for the log directory.
        api_key: The key to redact from the log; resolved from the credentials when omitted.

    Returns:
        The run's :class:`~src.schemas.ExitCode`, as an integer.
    """
    args = build_arg_parser().parse_args(argv)
    config = build_config(args, log_dir=log_dir)
    configure_logging(config.log_level, config.log_dir, api_key or _resolve_redaction_key())

    state = runner(args.prompt, config)

    code = state.exit_code
    if code is None:
        raise RuntimeError("The run returned with no exit code; run() sets one on every path.")
    print(f"Exit code: {int(code)} ({code.name})")
    print(f"Candidates considered: {len(state.documents)}")
    for document in state.documents.values():
        if document.saved is not None:
            saved = document.saved
            print(f"Saved {saved.draft_id} [{saved.qa_status}] -> {saved.path}")
    for failure in state.failures:
        print(f"Failed at {failure.stage}: {failure.error_type}")
    return int(code)


if __name__ == "__main__":
    sys.exit(main())
