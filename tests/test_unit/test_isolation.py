"""``tests/conftest.py``'s autouse isolation (D16, P4): no test reads a real ``.env``, whatever the cwd holds.

``CredentialManager()``, ``CostSettings()`` and ``ReasoningSettings()`` read ``.env`` from the working directory, and
the composition root default-constructs all three on every run. A developer's populated ``.env`` in the repository
must therefore reach none of them under test, or a run with the default ``build_model`` would spend real tokens.
"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from src.costs import DEFAULT_MODEL_RATES, CostSettings
from src.credentials import CredentialManager, ReasoningSettings

#: A ``.env`` that would configure a live run, priced and effort-overridden, if any settings class read it.
_POPULATED_ENV = (
    "HSE_MODEL_FAST_ENDPOINT=https://fast.example.invalid/openai/v1\n"
    "HSE_MODEL_FAST_API_KEY=sk-fast-not-a-real-key\n"
    "HSE_MODEL_STRONG_ENDPOINT=https://strong.example.invalid/openai/v1\n"
    "HSE_MODEL_STRONG_API_KEY=sk-strong-not-a-real-key\n"
    "HSE_COST_STRONG_INPUT_USD_PER_MTOK=99.0\n"
    "HSE_MODEL_SUPERVISOR_REASONING_EFFORT=low\n"
)


@pytest.fixture
def populated_env_in_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A populated ``.env`` in a temporary working directory."""
    env_file = tmp_path / ".env"
    env_file.write_text(_POPULATED_ENV, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return env_file


@pytest.mark.usefixtures("populated_env_in_cwd")
def test_credential_manager_ignores_a_dotenv_in_the_working_directory() -> None:
    """Credentials stay unresolved: a test can never build a live model by accident."""
    with pytest.raises(ValidationError):
        CredentialManager()


@pytest.mark.usefixtures("populated_env_in_cwd")
def test_cost_settings_ignore_a_dotenv_in_the_working_directory() -> None:
    """Rates stay the built-in defaults."""
    assert CostSettings().as_rates() == DEFAULT_MODEL_RATES


@pytest.mark.usefixtures("populated_env_in_cwd")
def test_reasoning_settings_ignore_a_dotenv_in_the_working_directory() -> None:
    """The Supervisor's effort stays the default."""
    assert ReasoningSettings().supervisor == "medium"


def test_an_explicit_env_file_is_still_read(populated_env_in_cwd: Path) -> None:
    """The pin is a class default: a test that passes ``_env_file=`` explicitly still reads that file."""
    assert CredentialManager(_env_file=populated_env_in_cwd).strong_endpoint == "https://strong.example.invalid/openai/v1"


#: The inner session's tests: one marked ``live``, one not. Each reads the variable and the ``env_file`` setting the
#: outer test arranged, so the pair shows which of them the isolation fixture touched.
_INNER_TESTS = """
import os

import pytest

from src.credentials import CredentialManager


@pytest.mark.live
def test_live_sees_the_real_environment():
    assert os.environ.get("HSE_MODEL_STRONG_API_KEY") == "sk-survives"
    assert CredentialManager.model_config["env_file"] == ".env"


def test_any_other_test_is_isolated():
    assert "HSE_MODEL_STRONG_API_KEY" not in os.environ
    assert CredentialManager.model_config["env_file"] is None
"""


def test_only_a_live_test_opts_out_of_the_isolation(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> None:
    """The ``live`` marker, and nothing else, switches the autouse isolation off, in one place (P4).

    An inner session runs the real fixture over two tests. The inner session has none of the repository's
    ``addopts``, so its ``live`` test runs there; it only reads the environment, and calls no model.
    """
    monkeypatch.setenv("HSE_MODEL_STRONG_API_KEY", "sk-survives")
    monkeypatch.setitem(CredentialManager.model_config, "env_file", ".env")
    pytester.makeini("[pytest]\nmarkers =\n    live: calls real model endpoints\n")
    pytester.makeconftest("from tests.conftest import _isolate_environment  # noqa: F401\n")
    pytester.makepyfile(test_inner=_INNER_TESTS)
    result = pytester.runpytest("-p", "no:cacheprovider", "-p", "no:asyncio")
    result.assert_outcomes(passed=2)
