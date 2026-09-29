"""Unit tests for the run's logging wiring (SPECIFICATIONS.md D-I; Approach 1 D22).

Copied and adapted from Approach 1 (D-J): its ``tests/test_unit/test_logging.py`` and the pure
``configure_logging`` tests of its ``tests/test_integration/test_orchestrator.py``, repointed from
``src.orchestrator`` to ``src.logging_setup``. The file is now ``run_YYYYMMDD.log``, not ``pipeline_…``.

Approach 1's logging tests exist because of a defect that was invisible under pytest: a module logger named
``logging.getLogger(__name__)`` is ``"__main__"`` under ``python -m``, which nothing in ``ROUTED_LOGGERS``
captures, so every record escaped the file and the redaction filter. The guard is kept, widened to every
``src`` module, and asserted against the *source text*, because behaviour under import is what hid the bug.

Everything here is offline. No model, agent or HTTP client is constructed: every third-party record is emitted
by hand through ``logging.getLogger(<name>)``.
"""

import ast
import logging
import re
import subprocess
import sys
import threading
from datetime import date
from pathlib import Path

import pytest

from src.logging_setup import (
    LOG_LEVELS,
    ROUTED_LOGGERS,
    CorrelationFilter,
    _resolve_log_level,
    configure_logging,
    log_context,
)

pytestmark = pytest.mark.usefixtures("restore_logging")

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "src"

#: A ``src`` child logger, named the way every ``src`` module names its own: an explicit ``"src.<module>"``.
SRC_CHILD_LOGGER = "src.tools"

#: The formatter's timestamp and padded level: the whole difference from ``logging.lastResort``.
_TIMESTAMP = r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}"


def _log_file(log_dir: Path) -> Path:
    """The dated run log file ``configure_logging`` opens."""
    return log_dir / f"run_{date.today():%Y%m%d}.log"


def _flush() -> None:
    """Flush every handler on every routed logger so the file is readable."""
    for name in ROUTED_LOGGERS:
        for handler in logging.getLogger(name).handlers:
            handler.flush()


def _read_log(log_dir: Path) -> str:
    """Flush the handlers, then return the dated log file's text."""
    _flush()
    return _log_file(log_dir).read_text(encoding="utf-8")


def _line_with(text: str, marker: str) -> str:
    """The single log line containing ``marker``."""
    lines = [line for line in text.splitlines() if marker in line]
    assert len(lines) == 1, f"expected one line with {marker!r}, got {lines!r}"
    return lines[0]


# ---------------------------------------------------------------------------
# Routing and the ``__name__`` regression guard
# ---------------------------------------------------------------------------


def test_routed_loggers_are_approach_1s_five() -> None:
    """D-I carries D22's five routed loggers over unchanged: widening them is a parity change."""
    assert ROUTED_LOGGERS == ("strands", "openai", "httpx", "mcp", "src")


def test_no_src_module_names_its_logger_from_dunder_name() -> None:
    """The regression guard: ``__name__`` is ``"__main__"`` under ``python -m src.cli``.

    Asserted against the source text of every ``src`` module rather than the imported modules, because the
    imported module is precisely where the bug does *not* reproduce. Every logger name must be a string
    literal under a routed logger, so a record can never fall through to ``logging.lastResort``. Literal-only
    is deliberate: a computed name (``f"{__name__}"``, ``__spec__.name``, a variable) cannot be checked from the
    source, so it is rejected outright. The one exemption is ``configure_logging``'s own loop over
    ``ROUTED_LOGGERS``.
    """
    for path in sorted(SRC_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and ast.unparse(node.func).endswith("getLogger")):
                continue
            assert node.args, f"{path.name}: getLogger() without a name is the root logger"
            argument = node.args[0]
            if path.name == "logging_setup.py" and ast.unparse(argument) == "name":
                continue  # configure_logging's own loop over ROUTED_LOGGERS
            assert isinstance(argument, ast.Constant) and isinstance(argument.value, str), (
                f"{path.name}: logger name must be a literal 'src.<module>', got {ast.unparse(argument)}"
            )
            assert argument.value.split(".")[0] in ROUTED_LOGGERS, f"{path.name}: {argument.value!r}"


def test_src_child_logger_level_is_unset_so_it_inherits_the_configured_level(tmp_path: Path) -> None:
    """``configure_logging`` sets the level on ``src``; a ``src.<module>`` child must not pin its own."""
    configure_logging("DEBUG", tmp_path / "logs")

    child = logging.getLogger(SRC_CHILD_LOGGER)
    assert child.level == logging.NOTSET
    assert child.getEffectiveLevel() == logging.DEBUG


def test_a_dunder_main_named_logger_would_not_reach_the_file(tmp_path: Path) -> None:
    """Pins the defect's mechanism, so the tests above cannot pass vacuously.

    ``configure_logging`` attaches its handlers to five names and to nothing else. A logger named
    ``"__main__"``, which is what ``getLogger(__name__)`` produces under ``python -m``, is under none of them,
    so its records never reach the file. That is the bug, reproduced here deliberately.
    """
    log_dir = tmp_path / "logs"
    configure_logging("INFO", log_dir)

    logging.getLogger("__main__").info("this is what the pipeline used to emit")

    assert "this is what the pipeline used to emit" not in _read_log(log_dir)


# ---------------------------------------------------------------------------
# The dated file, the routed loggers and re-entrancy
# ---------------------------------------------------------------------------


def test_configure_logging_writes_src_info_records_to_the_file(tmp_path: Path) -> None:
    """An INFO from a ``src`` module reaches the dated file, formatted, not ``lastResort``."""
    log_dir = tmp_path / "logs"
    configure_logging("INFO", log_dir)

    logging.getLogger(SRC_CHILD_LOGGER).info("Scope built by the Supervisor: %s", {"date_from": "2026-06-01"})

    text = _read_log(log_dir)
    assert "Scope built by the Supervisor: {'date_from': '2026-06-01'}" in text
    assert re.search(
        rf"^{_TIMESTAMP} INFO {{5}}\[run_id=- doc_id=- attempt=-\] src\.tools: Scope built by the Supervisor: ",
        text,
        re.MULTILINE,
    ), text


def test_configure_logging_writes_to_the_dated_run_log(tmp_path: Path) -> None:
    """D-I: ``logs/run_YYYYMMDD.log``, and every routed logger is taken off the root logger."""
    log_dir = tmp_path / "logs"

    configure_logging("INFO", log_dir)

    for name in ROUTED_LOGGERS:
        logger = logging.getLogger(name)
        assert logger.propagate is False, name
        file_handlers = [h for h in logger.handlers if isinstance(h, logging.FileHandler)]
        assert [Path(h.baseFilename) for h in file_handlers] == [_log_file(log_dir)], name

    logging.getLogger("strands").info("event loop cycle complete")
    assert "event loop cycle complete" in _read_log(log_dir)


def test_configure_logging_writes_one_file_per_day(tmp_path: Path) -> None:
    """Acceptance criterion 2: configuring twice on one day reuses ``run_YYYYMMDD.log``; no ``pipeline_*``."""
    log_dir = tmp_path / "logs"

    configure_logging("INFO", log_dir)
    logging.getLogger("src").info("first configuration")
    configure_logging("INFO", log_dir)
    logging.getLogger("src").info("second configuration")

    assert sorted(log_dir.glob("*.log")) == [_log_file(log_dir)]
    text = _read_log(log_dir)
    assert "first configuration" in text
    assert "second configuration" in text


def test_configure_logging_is_re_entrant_and_keeps_foreign_handlers(tmp_path: Path) -> None:
    """Handlers it installed earlier are closed and replaced, never stacked; anyone else's are kept."""
    foreign = logging.NullHandler()
    logging.getLogger("httpx").addHandler(foreign)

    configure_logging("INFO", tmp_path / "first")
    first_file_handler = next(h for h in logging.getLogger("src").handlers if isinstance(h, logging.FileHandler))
    configure_logging("INFO", tmp_path / "second")

    for name in ROUTED_LOGGERS:
        managed = [h for h in logging.getLogger(name).handlers if h is not foreign]
        assert len(managed) == 2, name
    assert foreign in logging.getLogger("httpx").handlers
    assert first_file_handler not in logging.getLogger("src").handlers
    assert first_file_handler.stream is None  # closed, so the first directory is not held open


def test_configure_logging_routes_provider_and_transport_loggers(tmp_path: Path) -> None:
    """D22: ``strands``, ``openai``, ``httpx`` and ``mcp`` all reach the same file."""
    log_dir = tmp_path / "logs"
    configure_logging("INFO", log_dir)

    for name in ("strands", "openai", "httpx", "mcp"):
        logger = logging.getLogger(name)
        assert any(isinstance(h, logging.FileHandler) for h in logger.handlers), name
        logger.error("marker from %s", name)

    text = _read_log(log_dir)
    for name in ("strands", "openai", "httpx", "mcp"):
        assert f"marker from {name}" in text


# ---------------------------------------------------------------------------
# Correlation: run_id, doc_id and attempt on every record (D-I)
# ---------------------------------------------------------------------------

#: Child loggers of each routed logger, named as the libraries name theirs. A filter on the ``strands`` *logger*
#: is never consulted for a record logged on ``strands.agent.agent``; only the handlers' filters run, so these
#: records carry correlation fields only if the filter sits on the handler.
_CHILD_LOGGERS: tuple[str, ...] = (
    "strands.agent.agent",
    "openai._base_client",
    "httpx",
    "mcp.client.stdio",
    "src.tools",
)


def test_log_context_puts_run_id_on_records_from_every_routed_logger(tmp_path: Path) -> None:
    """Inside ``log_context(run_id=…)`` every record carries ``run_id``, whichever library logged it."""
    log_dir = tmp_path / "logs"
    configure_logging("INFO", log_dir)

    with log_context(run_id="run-7f3a"):
        for name in _CHILD_LOGGERS:
            logging.getLogger(name).info("marker from %s", name)

    text = _read_log(log_dir)
    for name in _CHILD_LOGGERS:
        assert "run_id=run-7f3a" in _line_with(text, f"marker from {name}"), name


def test_a_record_outside_every_log_context_reads_a_dash(tmp_path: Path) -> None:
    """Outside every context the correlation fields are ``-``, so every line keeps one shape."""
    log_dir = tmp_path / "logs"
    configure_logging("INFO", log_dir)

    with log_context(run_id="run-7f3a"):
        pass
    logging.getLogger("httpx").info("after the run")

    line = _line_with(_read_log(log_dir), "after the run")
    assert re.search(r"\brun_id=-[ \]]", line), line


def _stamp(**extra: object) -> tuple[object, object, object]:
    """Run a hand-made record through a ``CorrelationFilter`` and return its three correlation fields.

    ``extra`` sets attributes on the record first, as ``logger.info(..., extra=…)`` does.
    """
    record = logging.LogRecord(SRC_CHILD_LOGGER, logging.INFO, __file__, 1, "probe", None, None)
    for name, value in extra.items():
        setattr(record, name, value)
    assert CorrelationFilter().filter(record) is True
    return record.run_id, record.doc_id, record.attempt


def test_nested_log_context_adds_fields_and_restores_the_outer_values() -> None:
    """An inner context adds ``doc_id`` and ``attempt`` and keeps ``run_id``; leaving it restores the outer."""
    assert _stamp() == ("-", "-", "-")
    with log_context(run_id="run-7f3a"):
        assert _stamp() == ("run-7f3a", "-", "-")
        with log_context(doc_id="inail-2024-circ-calore", attempt=1):
            assert _stamp() == ("run-7f3a", "inail-2024-circ-calore", 1)
            with log_context(attempt=2):
                assert _stamp() == ("run-7f3a", "inail-2024-circ-calore", 2)
            assert _stamp() == ("run-7f3a", "inail-2024-circ-calore", 1)
        assert _stamp() == ("run-7f3a", "-", "-")
    assert _stamp() == ("-", "-", "-")


def test_leaving_a_log_context_by_an_exception_restores_the_outer_values() -> None:
    """A tool that raises inside its document context must not leave its ``doc_id`` on later records."""
    with log_context(run_id="run-7f3a"):
        with pytest.raises(RuntimeError, match="writer failed"), log_context(doc_id="eu-2024-1234", attempt=3):
            raise RuntimeError("writer failed")
        assert _stamp() == ("run-7f3a", "-", "-")
    assert _stamp() == ("-", "-", "-")


def test_an_explicit_extra_field_overrides_the_context() -> None:
    """A record that names its own ``doc_id`` (``extra=``) keeps it; the context fills only what is missing."""
    with log_context(run_id="run-7f3a", doc_id="inail-2024-circ-calore", attempt=1):
        assert _stamp(doc_id="eu-2024-1234") == ("run-7f3a", "eu-2024-1234", 1)


def test_log_context_rejects_an_unknown_field() -> None:
    """A misspelt field fails loudly instead of silently correlating nothing."""
    with pytest.raises(TypeError), log_context(doc="inail-2024-circ-calore"):  # type: ignore[call-arg]
        pass


def test_a_log_context_does_not_leak_into_an_unrelated_thread() -> None:
    """The fields live in a context variable, not in shared state: a thread that did not copy the context sees ``-``."""
    seen: list[tuple[object, object, object]] = []
    with log_context(run_id="run-7f3a", doc_id="inail-2024-circ-calore", attempt=1):
        worker = threading.Thread(target=lambda: seen.append(_stamp()))
        worker.start()
        worker.join()
    assert seen == [("-", "-", "-")]


#: One record's header line: timestamp, padded level, the three correlation fields, the logger name.
_HEADER_LINE = re.compile(
    rf"^{_TIMESTAMP} (?:DEBUG|INFO|WARNING|ERROR) +\[run_id=\S+ doc_id=\S+ attempt=\S+\] [\w.]+: "
)


def _header_lines(text: str) -> list[str]:
    """Every line that starts a record, recognised by its leading timestamp."""
    return [line for line in text.splitlines() if re.match(_TIMESTAMP, line)]


def test_every_line_in_the_file_and_on_stderr_carries_the_three_fields(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """D-I: every line carries ``run_id``, ``doc_id`` and ``attempt``, ``-`` where no context set them."""
    log_dir = tmp_path / "logs"
    configure_logging("INFO", log_dir)

    logging.getLogger(SRC_CHILD_LOGGER).warning("before the run")
    with log_context(run_id="run-7f3a"):
        logging.getLogger("mcp.client.stdio").warning("during the run")
        with log_context(doc_id="inail-2024-circ-calore", attempt=2):
            logging.getLogger("strands.agent.agent").warning("during an attempt")

    file_text = _read_log(log_dir)
    stderr_text = capsys.readouterr().err
    for text in (file_text, stderr_text):
        headers = _header_lines(text)
        assert len(headers) == 3, headers
        for line in headers:
            assert _HEADER_LINE.match(line), line
        assert "[run_id=- doc_id=- attempt=-] src.tools: before the run" in text
        assert "[run_id=run-7f3a doc_id=- attempt=-] mcp.client.stdio: during the run" in text
        assert (
            "[run_id=run-7f3a doc_id=inail-2024-circ-calore attempt=2] strands.agent.agent: during an attempt" in text
        )


def test_a_traceback_is_written_in_full_under_its_correlated_header(tmp_path: Path) -> None:
    """Full fidelity (D22): the fields sit on the record's header line; the traceback follows verbatim."""
    log_dir = tmp_path / "logs"
    configure_logging("INFO", log_dir)

    with log_context(run_id="run-7f3a", doc_id="eu-2024-1234", attempt=1):
        try:
            raise RuntimeError("provider exploded: status=500 request_id=req_xyz789")
        except RuntimeError:
            logging.getLogger(SRC_CHILD_LOGGER).exception("Recoverable tool failure")

    lines = _read_log(log_dir).splitlines()
    header = _line_with("\n".join(lines), "Recoverable tool failure")
    assert _HEADER_LINE.match(header), header
    assert "[run_id=run-7f3a doc_id=eu-2024-1234 attempt=1]" in header
    body = lines[lines.index(header) + 1 :]
    assert body[0] == "Traceback (most recent call last):"
    assert body[-1] == "RuntimeError: provider exploded: status=500 request_id=req_xyz789"


@pytest.mark.parametrize("api_key", [None, "sk-live-0123456789abcdefSECRET"])
def test_redaction_still_applies_to_records_that_carry_correlation_fields(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], api_key: str | None
) -> None:
    """Approach 1's redaction survives correlation: the key is masked and the fields are still written.

    Both outputs are read: the ERROR is mirrored to stderr, the terminal, where a leaked key is most visible.
    """
    log_dir = tmp_path / "logs"
    configure_logging("INFO", log_dir, api_key=api_key)
    key_in_record = "sk-live-0123456789abcdefSECRET"

    with log_context(run_id="run-7f3a", doc_id="inail-2024-circ-calore", attempt=2):
        logging.getLogger("openai").error("Request failed: api-key=%s status=401 request_id=req_abc123", key_in_record)
        logging.getLogger("httpx").info("HTTP Request: %s %s", "POST /chat/completions", "200 OK")

    text = _read_log(log_dir)
    # A record without the key passes through the redaction filter untouched, fields and all.
    passed_through = _line_with(text, "HTTP Request")
    assert (
        "[run_id=run-7f3a doc_id=inail-2024-circ-calore attempt=2] httpx: HTTP Request: POST /chat/completions 200 OK"
        in passed_through
    )
    line = _line_with(text, "Request failed")
    assert _HEADER_LINE.match(line), line
    assert "[run_id=run-7f3a doc_id=inail-2024-circ-calore attempt=2] openai:" in line
    assert "status=401 request_id=req_abc123" in line
    if api_key is None:
        assert f"api-key={key_in_record}" in line
    else:
        assert key_in_record not in line
        assert "api-key=[REDACTED]" in line

    # The ERROR reaches stderr too; the INFO does not, so exactly one stderr line matches.
    stderr_line = _line_with(capsys.readouterr().err, "Request failed")
    assert "[run_id=run-7f3a doc_id=inail-2024-circ-calore attempt=2] openai:" in stderr_line
    if api_key is None:
        assert f"api-key={key_in_record}" in stderr_line
    else:
        assert key_in_record not in stderr_line
        assert "api-key=[REDACTED]" in stderr_line


def test_the_stderr_mirror_redacts_a_record_the_file_handler_never_sees(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Each handler redacts for itself, so a record that reaches stderr but not the file is masked too.

    The redaction filter rewrites the record in place, and the file handler runs first, so any record the file
    handler accepts is already masked when stderr formats it. A record reaches stderr alone when a child logger
    carries its own, lower level: each handler's level is checked separately, so under ``--log-level ERROR`` a
    WARNING from ``openai._base_client`` set to WARNING skips the file and is still mirrored to stderr.
    """
    log_dir = tmp_path / "logs"
    api_key = "sk-live-0123456789abcdefSECRET"
    configure_logging("ERROR", log_dir, api_key=api_key)
    child = logging.getLogger("openai._base_client")
    child_level = child.level
    child.setLevel(logging.WARNING)
    try:
        child.warning("Retrying request: api-key=%s status=429 request_id=req_abc123", api_key)
    finally:
        child.setLevel(child_level)

    stderr_line = _line_with(capsys.readouterr().err, "Retrying request")
    assert api_key not in stderr_line
    assert "api-key=[REDACTED] status=429 request_id=req_abc123" in stderr_line
    assert "Retrying request" not in _read_log(log_dir)


@pytest.mark.parametrize("api_key", [None, "sk-live-0123456789abcdefSECRET"])
def test_every_handler_carries_a_correlation_filter(tmp_path: Path, api_key: str | None) -> None:
    """The file and stderr handlers of all five loggers carry a ``CorrelationFilter``, with or without a key."""
    configure_logging("INFO", tmp_path / "logs", api_key=api_key)

    for name in ROUTED_LOGGERS:
        logger = logging.getLogger(name)
        assert len(logger.handlers) == 2, name
        for handler in logger.handlers:
            assert any(isinstance(f, CorrelationFilter) for f in handler.filters), (name, handler)
        assert not any(isinstance(f, CorrelationFilter) for f in logger.filters), name


# ---------------------------------------------------------------------------
# Levels
# ---------------------------------------------------------------------------


def test_the_cli_log_levels_are_the_four_the_specification_lists() -> None:
    """SPECIFICATIONS.md §7.5: ``--log-level {DEBUG,INFO,WARNING,ERROR}``; Iteration 14 uses these as ``choices``."""
    assert LOG_LEVELS == ("DEBUG", "INFO", "WARNING", "ERROR")


@pytest.mark.parametrize(
    ("level", "expected"),
    [("DEBUG", logging.DEBUG), ("INFO", logging.INFO), ("WARNING", logging.WARNING), ("ERROR", logging.ERROR)],
)
def test_every_cli_log_level_is_accepted_and_applied(tmp_path: Path, level: str, expected: int) -> None:
    """Each ``--log-level`` value resolves, and is set on all five routed loggers and on the file handler."""
    assert level in LOG_LEVELS
    assert _resolve_log_level(level) == expected

    configure_logging(level, tmp_path / "logs")

    for name in ROUTED_LOGGERS:
        logger = logging.getLogger(name)
        assert logger.level == expected, name
        file_handler = next(h for h in logger.handlers if isinstance(h, logging.FileHandler))
        assert file_handler.level == expected, name


def test_the_stderr_mirror_stays_at_warning_whatever_the_level(tmp_path: Path) -> None:
    """At ``DEBUG`` the file takes everything, but stderr still shows only WARNING and worse."""
    configure_logging("DEBUG", tmp_path / "logs")

    stderr_handlers = [
        h for h in logging.getLogger("src").handlers if type(h) is logging.StreamHandler and h.stream is sys.stderr
    ]
    assert [h.level for h in stderr_handlers] == [logging.WARNING]


def test_cli_log_level_warn_maps_to_logging_warning(tmp_path: Path) -> None:
    """Approach 1's CLI wrote ``WARN``; Python's level is named ``WARNING``, and ``WARN`` still resolves."""
    configure_logging("WARN", tmp_path / "logs")

    assert logging.getLogger("strands").level == logging.WARNING
    assert logging.getLogger("src").level == logging.WARNING


def test_an_unknown_log_level_falls_back_to_info(tmp_path: Path) -> None:
    """Anything that is not a level name resolves to ``INFO`` rather than raising."""
    assert _resolve_log_level("VERBOSE") == logging.INFO

    configure_logging("VERBOSE", tmp_path / "logs")

    for name in ROUTED_LOGGERS:
        assert logging.getLogger(name).level == logging.INFO, name


def test_configure_logging_honours_debug_level(tmp_path: Path) -> None:
    """``--log-level DEBUG`` works for ``src.*``; INFO still filters DEBUG out."""
    debug_dir = tmp_path / "debug"
    configure_logging("DEBUG", debug_dir)
    logging.getLogger(SRC_CHILD_LOGGER).debug("candidate payload %s", "inail-2024-circ-calore")
    assert "candidate payload inail-2024-circ-calore" in _read_log(debug_dir)

    info_dir = tmp_path / "info"
    configure_logging("INFO", info_dir)
    logging.getLogger(SRC_CHILD_LOGGER).debug("this record must not survive the INFO floor")
    assert "must not survive" not in _read_log(info_dir)


def test_debug_level_captures_remote_request_detail(tmp_path: Path) -> None:
    """D22: at DEBUG the provider's own wire-level records are retained verbatim."""
    log_dir = tmp_path / "logs"
    configure_logging("DEBUG", log_dir)

    logging.getLogger("openai").debug(
        "Request options: %s",
        {"method": "post", "url": "/chat/completions", "json_data": {"model": "gpt-5.4"}},
    )
    logging.getLogger("openai._base_client").debug("HTTP Response: %s %s", "POST /chat/completions", "429 Too Many")

    text = _read_log(log_dir)
    assert "Request options:" in text
    assert "/chat/completions" in text
    assert "429 Too Many" in text


# ---------------------------------------------------------------------------
# Redaction: the single permitted suppression (D22)
# ---------------------------------------------------------------------------


def test_src_error_records_are_redacted(tmp_path: Path) -> None:
    """A ``src`` ERROR goes through the filter, and only the literal key is masked.

    D22 forbids suppressing anything else, so the status code, provider error code, body and request ID must
    all survive intact.
    """
    log_dir = tmp_path / "logs"
    api_key = "sk-live-0123456789abcdefSECRET"
    configure_logging("INFO", log_dir, api_key=api_key)

    logging.getLogger(SRC_CHILD_LOGGER).error(
        "Recoverable tool failure 'writer_tool': AuthenticationError headers={'api-key': '%s'} "
        'status=401 body={"error": {"code": "invalid_api_key"}} request_id=req_abc123',
        api_key,
    )

    text = _read_log(log_dir)
    assert api_key not in text
    assert "[REDACTED]" in text
    assert "status=401" in text
    assert "invalid_api_key" in text
    assert "req_abc123" in text


def test_log_filter_redacts_only_the_api_key(tmp_path: Path) -> None:
    """The single permitted suppression: the literal key, and nothing else (D22)."""
    log_dir = tmp_path / "logs"
    api_key = "sk-live-0123456789abcdefSECRET"
    configure_logging("DEBUG", log_dir, api_key=api_key)

    logging.getLogger("openai").error(
        "Request failed: headers={'authorization': 'Bearer %s'} status=429 "
        'body={"error": {"code": "rate_limit_exceeded", "message": "Rate limit reached"}} request_id=req_abc123',
        api_key,
    )

    text = _read_log(log_dir)
    assert api_key not in text
    assert "[REDACTED]" in text
    # Everything a diagnosis needs is still there, untouched.
    assert "status=429" in text
    assert "rate_limit_exceeded" in text
    assert "Rate limit reached" in text
    assert "req_abc123" in text


def test_without_an_api_key_nothing_is_redacted(tmp_path: Path) -> None:
    """No key, no redaction filter: a key-shaped string is written verbatim."""
    log_dir = tmp_path / "logs"
    configure_logging("INFO", log_dir)

    logging.getLogger("openai").error("headers={'api-key': 'sk-live-0123456789abcdefSECRET'}")

    text = _read_log(log_dir)
    assert "sk-live-0123456789abcdefSECRET" in text
    assert "[REDACTED]" not in text


# ---------------------------------------------------------------------------
# stdout and stderr
# ---------------------------------------------------------------------------


def test_configure_logging_keeps_stdout_clean(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """D-I: diagnostics go to the file; stdout is reserved for the CLI's own status output."""
    configure_logging("DEBUG", tmp_path / "logs")

    logging.getLogger("strands").debug("verbose internal detail")
    logging.getLogger(SRC_CHILD_LOGGER).info("run progress")

    assert capsys.readouterr().out == ""


def test_warnings_and_worse_are_mirrored_to_stderr(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """D-I: WARNING and above reach stderr as well as the file; INFO stays in the file only."""
    log_dir = tmp_path / "logs"
    configure_logging("INFO", log_dir)

    logging.getLogger(SRC_CHILD_LOGGER).info("an info record for the file only")
    logging.getLogger(SRC_CHILD_LOGGER).warning("a guardrail violation")
    logging.getLogger("mcp").error("the session died")

    captured = capsys.readouterr()
    assert "an info record for the file only" not in captured.err
    assert "a guardrail violation" in captured.err
    assert "the session died" in captured.err
    assert captured.out == ""
    assert "an info record for the file only" in _read_log(log_dir)


# ---------------------------------------------------------------------------
# No import-time side effects
# ---------------------------------------------------------------------------


def test_importing_logging_setup_has_no_side_effects() -> None:
    """The module is imported at collection time and must stay inert.

    A fresh interpreter proves the import installs no handler; the source proves every top-level statement is
    an import, a constant, a definition or the docstring. A reload is avoided on purpose: it would rebuild the
    module's classes and context variable underneath the rest of the suite.
    """
    probe = (
        "import logging, src.logging_setup as m; "
        "print(sum(len(logging.getLogger(n).handlers) for n in m.ROUTED_LOGGERS))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe], cwd=REPO_ROOT, capture_output=True, text=True, check=True, timeout=60
    )
    assert completed.stdout.strip() == "0"

    tree = ast.parse((SRC_DIR / "logging_setup.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Expr):
            assert isinstance(node.value, ast.Constant), f"module-scope call: {ast.unparse(node)}"
        else:
            assert isinstance(
                node,
                ast.Import | ast.ImportFrom | ast.Assign | ast.AnnAssign | ast.FunctionDef | ast.ClassDef,
            ), f"unexpected module-scope statement: {ast.unparse(node)[:80]}"
