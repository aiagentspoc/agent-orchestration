"""Run logging: one dated file, full-fidelity errors, key redaction and correlation (SPECIFICATIONS.md D-I).

Approach 1's logging, extracted from its ``src/orchestrator.py`` (D-J). ``ROUTED_LOGGERS``, the handler flag, the
redaction filter and ``_resolve_log_level`` are moved verbatim; ``configure_logging`` is moved with three
amendments: the file is ``run_YYYYMMDD.log`` rather than ``pipeline_…``, the line format carries ``run_id``,
``doc_id`` and ``attempt``, and every handler gets a :class:`CorrelationFilter`.

**Correlation.** :func:`log_context` sets the fields in a context variable, and the filter on each *handler*
stamps them onto every record the handler receives, so records from ``strands``, ``openai``, ``httpx`` and
``mcp`` child loggers are correlated too: a filter on a logger is never consulted for records propagating up
from its children. A context variable, rather than shared state, is what keeps correlation right when the MCP
client and the SDK copy the caller's context into their worker threads.

**Logger names.** Every ``src`` module takes its logger by an explicit literal ``"src.<module>"`` name, never
``__name__``, which is ``"__main__"`` under ``python -m src.cli`` and is routed by nothing: that was Approach 1's
defect, and ``tests/test_unit/test_logging.py`` scans the source of every ``src`` module for it.

The module has no import-time side effects and imports nothing from ``src``: logging is configured only when
the CLI calls :func:`configure_logging`.
"""

import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date
from pathlib import Path
from typing import Final, NamedTuple

__all__ = ["LOG_LEVELS", "ROUTED_LOGGERS", "CorrelationFilter", "configure_logging", "log_context"]

#: The ``--log-level`` values the CLI offers (SPECIFICATIONS.md §7.5), default ``INFO``. ``DEBUG`` adds the
#: provider request bodies and is outside the D-I catalogue.
LOG_LEVELS: Final[tuple[str, ...]] = ("DEBUG", "INFO", "WARNING", "ERROR")

#: Loggers routed to the run log file (Approach 1's D22, unchanged). ``strands`` carries the SDK's own records;
#: the provider and transport loggers keep wire-level remote detail; ``src`` covers every ``src.<module>`` child.
ROUTED_LOGGERS: Final[tuple[str, ...]] = ("strands", "openai", "httpx", "mcp", "src")

#: Marks handlers this module installed, so re-configuring replaces rather than stacks.
_MANAGED_HANDLER_FLAG: Final[str] = "_hse_easy_managed"

#: What the API key is replaced with — the only string D22 permits suppressing.
_REDACTION_PLACEHOLDER: Final[str] = "[REDACTED]"

#: What a correlation field reads when no enclosing context set it (D-I).
_UNSET: Final[str] = "-"

#: Approach 1's line shape with the three correlation fields between the level and the logger name. They sit on
#: each record's header line; a traceback or a multi-line body follows verbatim beneath it (D22).
_LOG_FORMAT: Final[str] = (
    "%(asctime)s %(levelname)-8s [run_id=%(run_id)s doc_id=%(doc_id)s attempt=%(attempt)s] %(name)s: %(message)s"
)


class _CorrelationFields(NamedTuple):
    """The correlation fields in effect; ``None`` means no enclosing context set the field."""

    run_id: str | None = None
    doc_id: str | None = None
    attempt: int | None = None


#: The fields outside every context: none set, so each reads ``-``. Immutable, so safe as the shared default.
_NO_CORRELATION: Final[_CorrelationFields] = _CorrelationFields()

#: The fields in effect. Only ever replaced through ``set``/``reset``, never mutated, so a context copied into
#: another thread keeps its own values and a nested exit restores the outer ones exactly.
_CORRELATION: Final[ContextVar[_CorrelationFields]] = ContextVar("hse_easy_correlation", default=_NO_CORRELATION)


@contextmanager
def log_context(*, run_id: str | None = None, doc_id: str | None = None, attempt: int | None = None) -> Iterator[None]:
    """Put correlation fields on every record logged inside the block.

    Contexts nest: a field left as ``None`` is not set here and is inherited from the enclosing context, so
    ``log_context(doc_id=…, attempt=…)`` inside ``log_context(run_id=…)`` keeps the run ID. Leaving the block,
    normally or by an exception, restores the enclosing values exactly. Fields are keyword-only, so a misspelt
    field raises ``TypeError`` instead of silently correlating nothing.

    Args:
        run_id: The run's identifier.
        doc_id: The candidate document the enclosed work is about.
        attempt: The Writer attempt number the enclosed work belongs to.

    Yields:
        Nothing; the fields apply for the duration of the block.
    """
    outer = _CORRELATION.get()
    token = _CORRELATION.set(
        _CorrelationFields(
            run_id=outer.run_id if run_id is None else run_id,
            doc_id=outer.doc_id if doc_id is None else doc_id,
            attempt=outer.attempt if attempt is None else attempt,
        )
    )
    try:
        yield
    finally:
        _CORRELATION.reset(token)


class CorrelationFilter(logging.Filter):
    """Stamp the correlation fields in effect onto every record; never drop one.

    Attached to every handler :func:`configure_logging` installs. A field a record already carries, such as
    ``doc_id`` passed through ``extra=``, is kept, so a caller can name a document explicitly outside its context.
    Fields are filled one by one, so a caller naming a different ``doc_id`` should pass its ``attempt`` too, or
    the line pairs that document with the enclosing context's attempt. Tests that read ``caplog`` can add one to
    ``caplog.handler`` to see the same fields.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Set each field the record does not already carry, ``-`` when unset, and keep the record."""
        for name, value in _CORRELATION.get()._asdict().items():
            if not hasattr(record, name):
                setattr(record, name, _UNSET if value is None else value)
        return True


class _ApiKeyRedactionFilter(logging.Filter):
    """Mask the literal API key, and nothing else.

    This is the **sole** permitted suppression under D22. Everything else —
    status codes, provider error codes, response bodies, request IDs, prompts,
    tracebacks — is written verbatim. A leaked credential is not an error code or
    a diagnostic message, so redacting it does not cost any of the information
    this proof of concept exists to collect.
    """

    def __init__(self, api_key: str) -> None:
        super().__init__(name="hse-easy-api-key-redaction")
        self._api_key = api_key

    def filter(self, record: logging.LogRecord) -> bool:
        """Rewrite the record in place when it contains the key; never drop it."""
        formatted = record.getMessage()
        if self._api_key and self._api_key in formatted:
            record.msg = formatted.replace(self._api_key, _REDACTION_PLACEHOLDER)
            record.args = None
        return True


def _resolve_log_level(level: str) -> int:
    """Translate a CLI log level to a :mod:`logging` level.

    The CLI offers :data:`LOG_LEVELS` (SPECIFICATIONS.md §7.5). ``WARN``, which Approach 1's CLI offered, is
    still accepted as an alias of Python's canonical ``WARNING``; the body is Approach 1's, unchanged.

    Args:
        level: One of ``DEBUG``, ``INFO``, ``WARNING``, ``ERROR``, or the alias ``WARN``; case-insensitive.

    Returns:
        The numeric logging level, defaulting to ``INFO`` for anything unknown.
    """
    normalised = "WARNING" if level.upper() == "WARN" else level.upper()
    resolved = logging.getLevelName(normalised)
    return resolved if isinstance(resolved, int) else logging.INFO


def configure_logging(level: str, log_dir: Path, api_key: str | None = None) -> None:
    """Route the run's diagnostics to ``log_dir / run_YYYYMMDD.log``, one file per day.

    The ``strands`` logger and, as in Approach 1's D22, the provider and transport loggers ``openai``, ``httpx``
    and ``mcp`` all write to the same file as the ``src`` modules. At ``DEBUG`` the ``openai`` logger writes the
    request body, so prompts and draft content reach the log; that is intended, and the logs are local.

    ``propagate`` is disabled on each routed logger so records are not duplicated through the root logger, and
    stdout is left entirely to the CLI's status output; WARNING and worse are mirrored to stderr. Both handlers
    carry a :class:`CorrelationFilter`, and the redaction filter when a key is given. Errors are written in full.

    Called by the CLI, never at import. Re-entrant: the handlers it installed earlier are closed and replaced
    rather than stacked, and handlers anyone else installed are left alone.

    Args:
        level: The CLI log level, one of :data:`LOG_LEVELS`; anything unknown resolves to ``INFO``.
        log_dir: Directory for the dated log file; created if absent.
        api_key: When supplied, the literal string is redacted from every record.
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    resolved_level = _resolve_log_level(level)
    formatter = logging.Formatter(_LOG_FORMAT)

    file_handler = logging.FileHandler(log_dir / f"run_{date.today():%Y%m%d}.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.setLevel(resolved_level)
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(formatter)
    stderr_handler.setLevel(logging.WARNING)

    handlers: list[logging.Handler] = [file_handler, stderr_handler]
    for handler in handlers:
        setattr(handler, _MANAGED_HANDLER_FLAG, True)
        handler.addFilter(CorrelationFilter())
        if api_key:
            handler.addFilter(_ApiKeyRedactionFilter(api_key))

    for name in ROUTED_LOGGERS:
        logger = logging.getLogger(name)
        for existing in list(logger.handlers):
            if getattr(existing, _MANAGED_HANDLER_FLAG, False):
                logger.removeHandler(existing)
                existing.close()
        for handler in handlers:
            logger.addHandler(handler)
        logger.setLevel(resolved_level)
        logger.propagate = False
