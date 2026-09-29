"""`.env`-backed cost rate resolution for the HSE Easy pipeline (D21).

Rates are deployment configuration, not code: they change when a provider
repricing lands, and a benchmark run months later must still be able to say what
it was priced with. So they load through pydantic-settings exactly as
:mod:`src.credentials` does, built-in defaults apply when nothing is set, and
each draft records the resolved :class:`~src.schemas.ModelRate` values it used.

**Three rates per model, not four.** ``strands.types.event_loop.Usage`` declares
both ``cacheReadInputTokens`` and ``cacheWriteInputTokens``, but the OpenAI
provider populates only the read side — prompt caching is automatic and
uncharged on write, and generated output is never cached. A fourth rate would
price something that cannot occur.

Slot names follow the ``FAST`` / ``STRONG`` convention of :mod:`src.credentials`
rather than embedding a model name in a variable, so swapping models touches the
deployment variable only.
"""

from typing import Final

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .credentials import FAST_MODEL_ID, STRONG_MODEL_ID
from .schemas import ModelRate

__all__ = ["DEFAULT_MODEL_RATES", "CostSettings", "load_model_rates"]

#: Built-in fallback rates, USD per 1M tokens (ARCHITECTURE §6.2). Illustrative
#: values; real deployments override them through the ``HSE_COST_*`` variables.
DEFAULT_MODEL_RATES: Final[dict[str, ModelRate]] = {
    FAST_MODEL_ID: ModelRate(
        input_usd_per_mtok=0.25,
        cached_input_usd_per_mtok=0.025,
        output_usd_per_mtok=2.00,
    ),
    STRONG_MODEL_ID: ModelRate(
        input_usd_per_mtok=1.25,
        cached_input_usd_per_mtok=0.125,
        output_usd_per_mtok=10.00,
    ),
}


class CostSettings(BaseSettings):
    """Per-model token rates loaded from environment variables or an `.env` file.

    Every field is optional and falls back to :data:`DEFAULT_MODEL_RATES`, so an
    unconfigured environment costs a run rather than failing it. Construct with
    ``_env_file=None`` in tests so a developer's real ``.env`` can never
    influence an assertion (D16).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    fast_input_usd_per_mtok: float = Field(
        default=DEFAULT_MODEL_RATES[FAST_MODEL_ID].input_usd_per_mtok,
        ge=0.0,
        alias="HSE_COST_FAST_INPUT_USD_PER_MTOK",
    )
    fast_cached_input_usd_per_mtok: float = Field(
        default=DEFAULT_MODEL_RATES[FAST_MODEL_ID].cached_input_usd_per_mtok,
        ge=0.0,
        alias="HSE_COST_FAST_CACHED_INPUT_USD_PER_MTOK",
    )
    fast_output_usd_per_mtok: float = Field(
        default=DEFAULT_MODEL_RATES[FAST_MODEL_ID].output_usd_per_mtok,
        ge=0.0,
        alias="HSE_COST_FAST_OUTPUT_USD_PER_MTOK",
    )
    strong_input_usd_per_mtok: float = Field(
        default=DEFAULT_MODEL_RATES[STRONG_MODEL_ID].input_usd_per_mtok,
        ge=0.0,
        alias="HSE_COST_STRONG_INPUT_USD_PER_MTOK",
    )
    strong_cached_input_usd_per_mtok: float = Field(
        default=DEFAULT_MODEL_RATES[STRONG_MODEL_ID].cached_input_usd_per_mtok,
        ge=0.0,
        alias="HSE_COST_STRONG_CACHED_INPUT_USD_PER_MTOK",
    )
    strong_output_usd_per_mtok: float = Field(
        default=DEFAULT_MODEL_RATES[STRONG_MODEL_ID].output_usd_per_mtok,
        ge=0.0,
        alias="HSE_COST_STRONG_OUTPUT_USD_PER_MTOK",
    )

    def as_rates(self) -> dict[str, ModelRate]:
        """Project the flat settings surface into the per-model rate table.

        Returns:
            A fresh mapping from pipeline model ID to its three token rates.
        """
        return {
            FAST_MODEL_ID: ModelRate(
                input_usd_per_mtok=self.fast_input_usd_per_mtok,
                cached_input_usd_per_mtok=self.fast_cached_input_usd_per_mtok,
                output_usd_per_mtok=self.fast_output_usd_per_mtok,
            ),
            STRONG_MODEL_ID: ModelRate(
                input_usd_per_mtok=self.strong_input_usd_per_mtok,
                cached_input_usd_per_mtok=self.strong_cached_input_usd_per_mtok,
                output_usd_per_mtok=self.strong_output_usd_per_mtok,
            ),
        }


def load_model_rates(settings: CostSettings | None = None) -> dict[str, ModelRate]:
    """Resolve the cost rate table the pipeline should price a run with.

    Args:
        settings: Pre-built settings. When omitted they are loaded from the
            environment and the project ``.env`` file.

    Returns:
        A fresh mapping from pipeline model ID to its three token rates; mutating
        it cannot corrupt :data:`DEFAULT_MODEL_RATES`.
    """
    return (settings or CostSettings()).as_rates()
