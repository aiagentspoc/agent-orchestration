"""Unit tests for `.env`-backed cost rate resolution (Phase 6, Batch 3).

Every test disables the dotenv file (``_env_file=None``) and strips the
``HSE_COST_*`` OS variables, so a developer's real rates can never decide an
assertion (D16). The pipeline's own cost tests inject fixed rates and assert
arithmetic, never constants.
"""

import pytest
from pydantic import ValidationError

from src.agents import QA_LEGAL_MODEL_ID, SCOUT_MODEL_ID, WRITER_MODEL_ID
from src.costs import DEFAULT_MODEL_RATES, CostSettings, load_model_rates
from src.schemas import ModelRate

_COST_ENV_VARS: tuple[str, ...] = (
    "HSE_COST_FAST_INPUT_USD_PER_MTOK",
    "HSE_COST_FAST_CACHED_INPUT_USD_PER_MTOK",
    "HSE_COST_FAST_OUTPUT_USD_PER_MTOK",
    "HSE_COST_STRONG_INPUT_USD_PER_MTOK",
    "HSE_COST_STRONG_CACHED_INPUT_USD_PER_MTOK",
    "HSE_COST_STRONG_OUTPUT_USD_PER_MTOK",
)


@pytest.fixture(autouse=True)
def _isolate_cost_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear every ``HSE_COST_*`` variable: OS environment outranks dotenv (D16)."""
    for name in _COST_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def test_default_model_rates_cover_every_worker_model_id() -> None:
    """A model rename that outruns the rate table must fail here, not silently bill zero."""
    worker_model_ids = {SCOUT_MODEL_ID, WRITER_MODEL_ID, QA_LEGAL_MODEL_ID}

    assert worker_model_ids <= set(DEFAULT_MODEL_RATES)
    for model_id in worker_model_ids:
        rate = DEFAULT_MODEL_RATES[model_id]
        assert isinstance(rate, ModelRate)
        assert rate.input_usd_per_mtok > 0.0
        assert rate.output_usd_per_mtok > 0.0
        # Caching is a discount, never a surcharge.
        assert rate.cached_input_usd_per_mtok <= rate.input_usd_per_mtok


def test_load_model_rates_reads_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    """Deployment rates come from the environment without touching code."""
    monkeypatch.setenv("HSE_COST_FAST_INPUT_USD_PER_MTOK", "9.5")
    monkeypatch.setenv("HSE_COST_STRONG_OUTPUT_USD_PER_MTOK", "42.0")

    rates = load_model_rates(CostSettings(_env_file=None))

    assert rates[SCOUT_MODEL_ID].input_usd_per_mtok == 9.5
    assert rates[WRITER_MODEL_ID].output_usd_per_mtok == 42.0
    # Unset slots keep their built-in defaults.
    assert rates[WRITER_MODEL_ID].input_usd_per_mtok == DEFAULT_MODEL_RATES[WRITER_MODEL_ID].input_usd_per_mtok


def test_load_model_rates_falls_back_to_defaults_when_unset() -> None:
    """Rates are optional configuration: an empty environment must not raise."""
    rates = load_model_rates(CostSettings(_env_file=None))

    assert rates == dict(DEFAULT_MODEL_RATES)
    # The returned mapping is a copy; mutating it cannot corrupt the module default.
    rates[WRITER_MODEL_ID] = ModelRate(input_usd_per_mtok=0.0, output_usd_per_mtok=0.0)
    assert DEFAULT_MODEL_RATES[WRITER_MODEL_ID].input_usd_per_mtok > 0.0


def test_load_model_rates_rejects_negative_rate(monkeypatch: pytest.MonkeyPatch) -> None:
    """A negative rate would make tokens earn money; fail loudly at load time."""
    monkeypatch.setenv("HSE_COST_STRONG_INPUT_USD_PER_MTOK", "-1.0")

    with pytest.raises(ValidationError):
        load_model_rates(CostSettings(_env_file=None))
