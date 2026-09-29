"""Unit tests for the .env-backed model credential manager (Phase 5, Batch 0).

Every test builds ``CredentialManager`` with either ``_env_file=None`` or a
``tmp_path`` file, so a developer's real ``.env`` can never leak into an
assertion, and the autouse ``_isolate_environment`` fixture below strips the
``HSE_MODEL_*`` OS variables that would otherwise outrank both (D16: zero-cost,
hermetic, offline tests).
"""

from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from src.costs import CostSettings
from src.credentials import CredentialManager, ModelCredentials, ReasoningSettings
from tests.conftest import _ISOLATED_ENV_VARS

#: The documented configuration surface a developer copies to ``.env``.
ENV_EXAMPLE: Path = Path(__file__).resolve().parents[2] / ".env.example"

_EXPLICIT_VALUES: dict[str, str] = {
    "HSE_MODEL_FAST_ENDPOINT": "https://fast.example.invalid/openai/v1/",
    "HSE_MODEL_FAST_API_KEY": "fast-secret-key",
    "HSE_MODEL_FAST_DEPLOYMENT": "gpt-5-mini",
    "HSE_MODEL_STRONG_ENDPOINT": "https://strong.example.invalid/openai/v1/",
    "HSE_MODEL_STRONG_API_KEY": "strong-secret-key",
    "HSE_MODEL_STRONG_DEPLOYMENT": "gpt-5.4",
}


@pytest.fixture(autouse=True)
def _isolate_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear every ``HSE_MODEL_*`` variable from the OS environment (D16).

    ``pydantic-settings`` ranks OS environment variables *above* dotenv values,
    so without this a developer's exported credentials silently override the
    ``tmp_path`` ``.env`` these tests construct — and, worse, satisfy the very
    required-field check ``test_credential_manager_missing_vars_raises`` exists
    to prove. Keyed off ``_EXPLICIT_VALUES`` so it cannot drift out of sync.
    """
    for name in _EXPLICIT_VALUES:
        monkeypatch.delenv(name, raising=False)


def _manager() -> CredentialManager:
    """Build a manager from explicit values with the .env file disabled."""
    return CredentialManager(_env_file=None, **_EXPLICIT_VALUES)


def test_credential_manager_constructs_from_explicit_values() -> None:
    """Explicit aliased values populate every credential slot without touching disk."""
    manager = _manager()

    assert manager.fast_endpoint == "https://fast.example.invalid/openai/v1/"
    assert manager.fast_api_key.get_secret_value() == "fast-secret-key"
    assert manager.fast_deployment == "gpt-5-mini"
    assert manager.strong_endpoint == "https://strong.example.invalid/openai/v1/"
    assert manager.strong_api_key.get_secret_value() == "strong-secret-key"
    assert manager.strong_deployment == "gpt-5.4"


def test_credential_manager_reads_env_file(tmp_path: Path) -> None:
    """Values are sourced from an explicitly supplied .env file."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "HSE_MODEL_FAST_ENDPOINT=https://file-fast.example.invalid/openai/v1/",
                "HSE_MODEL_FAST_API_KEY=file-fast-key",
                "HSE_MODEL_STRONG_ENDPOINT=https://file-strong.example.invalid/openai/v1/",
                "HSE_MODEL_STRONG_API_KEY=file-strong-key",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    manager = CredentialManager(_env_file=env_file)

    assert manager.fast_endpoint == "https://file-fast.example.invalid/openai/v1/"
    assert manager.fast_api_key.get_secret_value() == "file-fast-key"
    assert manager.strong_api_key.get_secret_value() == "file-strong-key"
    # Deployments fall back to the ARCHITECTURE §3 defaults when absent from the file.
    assert manager.fast_deployment == "gpt-5-mini"
    assert manager.strong_deployment == "gpt-5.4"


def test_credential_manager_missing_vars_raises(tmp_path: Path) -> None:
    """A missing required key raises ValidationError naming it, never at import time."""
    empty_env = tmp_path / ".env"
    empty_env.write_text("", encoding="utf-8")

    with pytest.raises(ValidationError) as excinfo:
        CredentialManager(_env_file=empty_env)

    message = str(excinfo.value)
    assert "HSE_MODEL_FAST_ENDPOINT" in message
    assert "HSE_MODEL_STRONG_API_KEY" in message


def test_api_key_is_masked_in_str_and_repr() -> None:
    """SecretStr keeps API keys out of logs and tracebacks (Rule 6 logging safety)."""
    manager = _manager()

    assert "fast-secret-key" not in str(manager)
    assert "fast-secret-key" not in repr(manager)
    assert "strong-secret-key" not in str(manager)
    assert "strong-secret-key" not in repr(manager)
    assert str(manager.fast_api_key) == "**********"

    credentials = manager.for_model("gpt-5-mini")
    assert "fast-secret-key" not in str(credentials)
    assert "fast-secret-key" not in repr(credentials)


def test_for_model_returns_fast_credentials() -> None:
    """The fast model ID resolves to the fast credential slot."""
    credentials = _manager().for_model("gpt-5-mini")

    assert isinstance(credentials, ModelCredentials)
    assert credentials.endpoint == "https://fast.example.invalid/openai/v1/"
    assert isinstance(credentials.api_key, SecretStr)
    assert credentials.api_key.get_secret_value() == "fast-secret-key"
    assert credentials.deployment == "gpt-5-mini"


def test_for_model_returns_strong_credentials() -> None:
    """The strong model ID resolves to the strong credential slot."""
    credentials = _manager().for_model("gpt-5.4")

    assert isinstance(credentials, ModelCredentials)
    assert credentials.endpoint == "https://strong.example.invalid/openai/v1/"
    assert credentials.api_key.get_secret_value() == "strong-secret-key"
    assert credentials.deployment == "gpt-5.4"


def test_for_model_rejects_unknown_model_id() -> None:
    """An unrecognised model ID raises ValueError naming the offending ID."""
    with pytest.raises(ValueError) as excinfo:
        _manager().for_model("gpt-nonexistent")

    assert "gpt-nonexistent" in str(excinfo.value)


# ---------------------------------------------------------------------------
# ReasoningSettings (D24) — per-role effort overrides, all optional
# ---------------------------------------------------------------------------


def test_reasoning_settings_construct_with_no_credentials_and_no_env_file() -> None:
    """Every field optional, so offline construction never needs a secret.

    This is why the overrides are not on ``CredentialManager``: its endpoint and
    key fields are required, so constructing it inside ``execute_pipeline`` would
    raise in every offline test.
    """
    settings = ReasoningSettings(_env_file=None)

    assert settings.writer is None
    assert settings.qa_legal is None


def test_reasoning_settings_read_both_aliases_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """The two judgement-heavy roles are tunable without a code edit."""
    monkeypatch.setenv("HSE_MODEL_WRITER_REASONING_EFFORT", "max")
    monkeypatch.setenv("HSE_MODEL_QA_REASONING_EFFORT", "low")

    settings = ReasoningSettings(_env_file=None)

    assert settings.writer == "max"
    assert settings.qa_legal == "low"


def test_reasoning_settings_honour_env_file_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``_env_file=None`` really disables the file source, so no test reads a real ``.env``."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "HSE_MODEL_WRITER_REASONING_EFFORT=xhigh\nHSE_MODEL_QA_REASONING_EFFORT=minimal\n",
        encoding="utf-8",
    )

    assert ReasoningSettings(_env_file=env_file).writer == "xhigh"
    assert ReasoningSettings(_env_file=env_file).qa_legal == "minimal"
    assert ReasoningSettings(_env_file=None).writer is None
    assert ReasoningSettings(_env_file=None).qa_legal is None


def test_reasoning_settings_ignore_unrelated_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    """``extra="ignore"``: a populated credential environment does not disturb it."""
    for name, value in _EXPLICIT_VALUES.items():
        monkeypatch.setenv(name, value)

    settings = ReasoningSettings(_env_file=None)

    assert settings.writer is None
    assert settings.qa_legal is None


def test_reasoning_settings_are_populated_through_their_aliases_only() -> None:
    """The alias is the whole accepted surface: two names, exactly as D24 documents.

    ``populate_by_name`` was deliberately dropped: with it, ``writer`` and
    ``qa_legal`` become live configuration names in their own right, so the
    accepted surface would be four names where ``.env.example`` promises two.
    Tests therefore pin an effort through the alias, which is also the only path
    a real run can take.
    """
    settings = ReasoningSettings(
        _env_file=None,
        HSE_MODEL_WRITER_REASONING_EFFORT="max",
        HSE_MODEL_QA_REASONING_EFFORT="low",
    )

    assert (settings.writer, settings.qa_legal) == ("max", "low")
    # The field names are not a second way in; ``extra="ignore"`` drops them.
    by_name = ReasoningSettings(_env_file=None, writer="max", qa_legal="low")
    assert (by_name.writer, by_name.qa_legal) == (None, None)


def test_bare_writer_and_qa_legal_environment_variables_are_not_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``WRITER`` and ``QA_LEGAL`` are far too generic to be a live setting.

    The regression this pins is concrete: under ``populate_by_name=True`` a
    developer shell exporting ``WRITER`` for any unrelated reason silently became
    the Writer's reasoning effort, because ``execute_pipeline`` default-constructs
    ``ReasoningSettings()`` on every run.
    """
    monkeypatch.setenv("WRITER", "xhigh")
    monkeypatch.setenv("QA_LEGAL", "minimal")

    settings = ReasoningSettings(_env_file=None)

    assert settings.writer is None
    assert settings.qa_legal is None


# ---------------------------------------------------------------------------
# ReasoningSettings.supervisor (D-H, Q5 = B) — the Supervisor's effort override
# ---------------------------------------------------------------------------


def test_supervisor_reasoning_effort_resolves_to_medium_when_unset() -> None:
    """D-H: the Supervisor runs at ``medium`` unless ``.env`` says otherwise."""
    assert ReasoningSettings(_env_file=None).supervisor == "medium"


def test_supervisor_reasoning_effort_resolves_to_medium_when_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An empty value, in the environment or in ``.env``, means the default, as ``.env.example`` states."""
    env_file = tmp_path / ".env"
    env_file.write_text("HSE_MODEL_SUPERVISOR_REASONING_EFFORT=\n", encoding="utf-8")
    assert ReasoningSettings(_env_file=env_file).supervisor == "medium"

    monkeypatch.setenv("HSE_MODEL_SUPERVISOR_REASONING_EFFORT", "")
    assert ReasoningSettings(_env_file=None).supervisor == "medium"

    monkeypatch.setenv("HSE_MODEL_SUPERVISOR_REASONING_EFFORT", "high")
    assert ReasoningSettings(_env_file=None).supervisor == "high"


def test_supervisor_reasoning_effort_is_read_from_its_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    """``HSE_MODEL_SUPERVISOR_REASONING_EFFORT`` overrides it, in the Writer's and QA-Legal's style."""
    monkeypatch.setenv("HSE_MODEL_SUPERVISOR_REASONING_EFFORT", "high")

    settings = ReasoningSettings(_env_file=None)

    assert settings.supervisor == "high"
    assert (settings.writer, settings.qa_legal) == (None, None)


def test_supervisor_reasoning_effort_honours_env_file_none(tmp_path: Path) -> None:
    """A ``.env`` file sets it, and ``_env_file=None`` really disables that file."""
    env_file = tmp_path / ".env"
    env_file.write_text("HSE_MODEL_SUPERVISOR_REASONING_EFFORT=low\n", encoding="utf-8")

    assert ReasoningSettings(_env_file=env_file).supervisor == "low"
    assert ReasoningSettings(_env_file=None).supervisor == "medium"


def test_supervisor_reasoning_effort_is_populated_through_its_alias_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neither the field name nor a bare ``SUPERVISOR`` variable is a second way in."""
    assert ReasoningSettings(_env_file=None, HSE_MODEL_SUPERVISOR_REASONING_EFFORT="xhigh").supervisor == "xhigh"
    assert ReasoningSettings(_env_file=None, supervisor="xhigh").supervisor == "medium"

    monkeypatch.setenv("SUPERVISOR", "minimal")
    assert ReasoningSettings(_env_file=None).supervisor == "medium"


@pytest.mark.parametrize("settings_class", [CredentialManager, CostSettings, ReasoningSettings])
def test_environment_isolation_strips_every_settings_variable(settings_class: type) -> None:
    """D16: the autouse isolation in ``tests/conftest.py`` strips every variable a settings class reads.

    A variable missing from that list would let a developer's exported value reach an assertion, such as
    the Supervisor's ``medium`` default.
    """
    aliases = {field.alias for field in settings_class.model_fields.values()}

    assert None not in aliases
    assert aliases <= set(_ISOLATED_ENV_VARS)


@pytest.mark.parametrize("settings_class", [CredentialManager, CostSettings, ReasoningSettings])
def test_env_example_documents_every_settings_variable(settings_class: type) -> None:
    """Every variable a settings class reads has a line in ``.env.example``, set or commented out."""
    documented = {
        line.lstrip("#").split("=", 1)[0].strip()
        for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
        if "=" in line
    }

    assert {field.alias for field in settings_class.model_fields.values()} <= documented
