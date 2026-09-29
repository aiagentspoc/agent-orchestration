"""Repo-wide pytest fixtures for the HSE Easy suite.

The environment-isolation fixture is the enforcement half of **D16**: no test in
either ``tests/test_unit/`` or ``tests/test_integration/`` may observe a real
credential or a real cost rate, so reaching a live model endpoint from inside
``pytest`` is impossible rather than merely discouraged. Every LLM in every test
is a ``ScriptedModel`` or a ``FailingModel`` injected through the
``model_builder`` seam; the live substrate session, which is a local ``uv``
subprocess over a static corpus, is deliberately *not* isolated.

Declared here rather than per module so a new test file inherits the guarantee
instead of having to re-declare it.
"""

import logging
from collections.abc import Iterator
from typing import Final

import pytest

from src.credentials import ReasoningSettings

#: Every variable ``CredentialManager``, ``CostSettings`` and ``ReasoningSettings``
#: read. Stripped for the duration of each test so a developer's populated ``.env``
#: environment cannot leak into an assertion.
_ISOLATED_ENV_VARS: Final[tuple[str, ...]] = (
    "HSE_MODEL_FAST_ENDPOINT",
    "HSE_MODEL_FAST_API_KEY",
    "HSE_MODEL_FAST_DEPLOYMENT",
    "HSE_MODEL_STRONG_ENDPOINT",
    "HSE_MODEL_STRONG_API_KEY",
    "HSE_MODEL_STRONG_DEPLOYMENT",
    "HSE_COST_FAST_INPUT_USD_PER_MTOK",
    "HSE_COST_FAST_CACHED_INPUT_USD_PER_MTOK",
    "HSE_COST_FAST_OUTPUT_USD_PER_MTOK",
    "HSE_COST_STRONG_INPUT_USD_PER_MTOK",
    "HSE_COST_STRONG_CACHED_INPUT_USD_PER_MTOK",
    "HSE_COST_STRONG_OUTPUT_USD_PER_MTOK",
    "HSE_MODEL_WRITER_REASONING_EFFORT",
    "HSE_MODEL_QA_REASONING_EFFORT",
)

#: The loggers ``configure_logging`` takes over. Restated here rather than
#: imported from ``src.logging_setup`` so the fixture keeps working even while a
#: test is asserting something about that constant.
_ROUTED_LOGGER_NAMES: Final[tuple[str, ...]] = ("strands", "openai", "httpx", "mcp", "src")


@pytest.fixture(autouse=True)
def _isolate_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """D16: no test may see real credentials, real cost rates or a real ``.env``.

    Stripping the OS variables is enough for ``CredentialManager`` and
    ``CostSettings``, which no test constructs without ``_env_file=None``.
    ``ReasoningSettings`` is different: ``execute_pipeline`` default-constructs one
    on every run, so a repository ``.env`` carrying an effort override would reach
    production code under test through a path no test can pass ``_env_file=None``
    to. Pinning ``env_file`` to ``None`` on the class closes that, and monkeypatch
    restores the dict entry afterwards.
    """
    for name in _ISOLATED_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setitem(ReasoningSettings.model_config, "env_file", None)


@pytest.fixture
def restore_logging() -> Iterator[None]:
    """Snapshot and restore every logger ``configure_logging`` touches.

    Without this a logging test would leave ``propagate = False`` and an open
    file handler on module-level loggers, silently breaking ``caplog`` in later
    tests and holding ``tmp_path`` open on Windows.
    """
    saved = [
        (
            logging.getLogger(name),
            list(logging.getLogger(name).handlers),
            logging.getLogger(name).level,
            logging.getLogger(name).propagate,
        )
        for name in _ROUTED_LOGGER_NAMES
    ]
    try:
        yield
    finally:
        for logger, handlers, level, propagate in saved:
            for handler in list(logger.handlers):
                if handler not in handlers:
                    handler.close()
            logger.handlers = handlers
            logger.setLevel(level)
            logger.propagate = propagate
