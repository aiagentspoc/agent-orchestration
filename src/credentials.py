"""`.env`-backed model credential resolution for the HSE Easy pipeline.

Two credential slots are defined, keyed by the ARCHITECTURE §3 model bindings:
a *fast* slot (ScopeParser, Scout) and a *strong* slot (Writer, QA-Legal).
API keys are held as :class:`~pydantic.SecretStr` so they are masked in every
``str()`` and ``repr()`` and therefore cannot leak into Rule 6 telemetry logs.

This module holds no provider knowledge; see :mod:`src.model_factory`.
"""

from typing import Final

from pydantic import BaseModel, ConfigDict, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = [
    "FAST_MODEL_ID",
    "STRONG_MODEL_ID",
    "CredentialManager",
    "ModelCredentials",
    "ReasoningSettings",
]

#: Pipeline model IDs, canonical per ARCHITECTURE §3.
FAST_MODEL_ID: Final[str] = "gpt-5-mini"
STRONG_MODEL_ID: Final[str] = "gpt-5.4"


class ModelCredentials(BaseModel):
    """Resolved endpoint, key and deployment for one pipeline model ID."""

    model_config = ConfigDict(extra="ignore")

    endpoint: str = Field(..., description="OpenAI v1-compatible base URL")
    api_key: SecretStr = Field(..., description="API key, masked in str() and repr()")
    deployment: str = Field(..., description="Provider-side deployment name")


class CredentialManager(BaseSettings):
    """Model credentials loaded from environment variables or an `.env` file.

    Construct with ``_env_file=None`` in tests so a developer's real ``.env``
    can never influence an assertion (D16).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    fast_endpoint: str = Field(..., alias="HSE_MODEL_FAST_ENDPOINT")
    fast_api_key: SecretStr = Field(..., alias="HSE_MODEL_FAST_API_KEY")
    fast_deployment: str = Field(default=FAST_MODEL_ID, alias="HSE_MODEL_FAST_DEPLOYMENT")
    strong_endpoint: str = Field(..., alias="HSE_MODEL_STRONG_ENDPOINT")
    strong_api_key: SecretStr = Field(..., alias="HSE_MODEL_STRONG_API_KEY")
    strong_deployment: str = Field(default=STRONG_MODEL_ID, alias="HSE_MODEL_STRONG_DEPLOYMENT")

    def for_model(self, model_id: str) -> ModelCredentials:
        """Return the credential slot bound to ``model_id``.

        Args:
            model_id: A pipeline model ID from ARCHITECTURE §3.

        Returns:
            The resolved :class:`ModelCredentials` for that model.

        Raises:
            ValueError: If ``model_id`` is not a known pipeline model ID.
        """
        if model_id == FAST_MODEL_ID:
            return ModelCredentials(
                endpoint=self.fast_endpoint,
                api_key=self.fast_api_key,
                deployment=self.fast_deployment,
            )
        if model_id == STRONG_MODEL_ID:
            return ModelCredentials(
                endpoint=self.strong_endpoint,
                api_key=self.strong_api_key,
                deployment=self.strong_deployment,
            )
        raise ValueError(
            f"Unknown pipeline model ID {model_id!r}; expected one of {FAST_MODEL_ID!r}, {STRONG_MODEL_ID!r}."
        )


class ReasoningSettings(BaseSettings):
    """Per-role reasoning effort overrides, read from the environment (D24).

    Deliberately **not** fields on :class:`CredentialManager`. That class's
    endpoint and key fields are required, so constructing it inside
    ``execute_pipeline`` would raise in every offline test — and the whole point
    of the ``model_builder`` seam is that scripted scenarios never touch
    credentials. It is also keyed by model ID through ``for_model``, which cannot
    tell the Writer from QA-Legal: both are ``gpt-5.4``.

    Every field is optional, so this constructs cleanly with no ``.env`` file and
    no credentials present. An unset *or empty* value falls through to the role
    constant in :mod:`src.agents` — plain ``or`` semantics, which is worth stating
    because leaving a variable blank in ``.env`` is a realistic way to try to
    "turn it off" and does not do that.

    Construct with ``_env_file=None`` in tests so a developer's real ``.env`` can
    never influence an assertion (D16), and populate through the **aliases** —
    ``populate_by_name`` is deliberately not set, so the accepted configuration
    surface is exactly the two names D24 and ``.env.example`` document. Allowing
    the field names too would make the bare variables ``WRITER`` and ``QA_LEGAL``
    live configuration, which are generic enough to be set on a developer's shell
    for entirely unrelated reasons, and would be inconsistent with
    :class:`CredentialManager` and ``CostSettings``, neither of which sets it.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    writer: str | None = Field(default=None, alias="HSE_MODEL_WRITER_REASONING_EFFORT")
    qa_legal: str | None = Field(default=None, alias="HSE_MODEL_QA_REASONING_EFFORT")
