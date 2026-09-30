"""The single module in `src/` permitted to import a concrete model provider.

Every other module — notably :mod:`src.agents` — sees only the abstract
:class:`strands.models.model.Model`. Swapping providers therefore means editing
this file alone.

The configured endpoints are the OpenAI **v1-compatible surface** of Azure AI
Foundry, so this is a plain ``base_url`` + ``api_key`` pass-through: no path
rewriting and no ``api-version`` handling. Construction opens no socket;
Strands builds a fresh HTTP client per request.
"""

from typing import Any, Final, Protocol

from strands.models.model import Model
from strands.models.openai import OpenAIModel

from .credentials import CredentialManager

__all__ = ["ModelBuilder", "build_model"]

#: The provider's accepted reasoning-effort values, per ``openai``'s
#: ``CompletionCreateParamsBase``. The set lives here because this module's
#: docstring makes it the only one permitted to encode provider specifics —
#: importing the provider's ``ReasoningEffort`` literal anywhere else would break
#: that isolation.
_REASONING_EFFORTS: Final[frozenset[str]] = frozenset(
    {"none", "minimal", "low", "medium", "high", "xhigh", "max"}
)


class ModelBuilder(Protocol):
    """Builds the ``Model`` for one pipeline role.

    A ``Protocol`` rather than the former ``Callable[[str], Model]`` alias because
    D24 makes reasoning effort a property of the *role*, not of the model ID: the
    Writer and QA-Legal both bind ``gpt-5.4`` and want different efforts, so the
    effort has to travel with the construction request.
    """

    def __call__(self, model_id: str, *, reasoning_effort: str | None = None) -> Model:
        """Return the model for ``model_id``, built at ``reasoning_effort``.

        Args:
            model_id: A pipeline model ID from ARCHITECTURE §3.
            reasoning_effort: The already-resolved effort for the role being
                built, or ``None`` to leave it off the request entirely.

        Returns:
            A provider-agnostic ``Model``.
        """
        ...


def build_model(
    model_id: str,
    credentials: CredentialManager | None = None,
    *,
    reasoning_effort: str | None = None,
) -> Model:
    """Construct a Strands ``Model`` for the given pipeline model ID.

    Deliberately mechanical about ``reasoning_effort``: it applies precisely the
    value it is handed and resolves no override of its own (D24). Had it consulted
    the environment itself, the orchestrator would still be reporting the role
    constant in each draft's telemetry, and a run under an ``.env`` override would
    record an effort it did not run at.

    ``params`` reaches both provider call paths — ``stream()`` and
    ``structured_output()`` both go through ``format_request`` — which matters
    because every worker terminates in a structured-output call. When the effort
    is ``None`` no ``params`` key is constructed at all, so the request body is
    byte-identical to one built before D24.

    Args:
        model_id: A pipeline model ID from ARCHITECTURE §3 (``gpt-5-mini`` or ``gpt-5.4``).
        credentials: Pre-resolved credentials. When omitted, they are loaded
            from the environment and the project ``.env`` file.
        reasoning_effort: The already-resolved effort for the role this model
            serves, or ``None`` to leave it off the request entirely.

    Returns:
        A provider-agnostic ``Model`` pointed at the configured endpoint.

    Raises:
        ValueError: If ``model_id`` is not a known pipeline model ID, or if
            ``reasoning_effort`` is not one of :data:`_REASONING_EFFORTS`. The
            effort is checked **first**, and before credentials are resolved, so a
            typo in ``.env`` surfaces as ``CONFIG_ERROR`` before any token is spent
            rather than as a 400 mid-run.
    """
    if reasoning_effort is not None and reasoning_effort not in _REASONING_EFFORTS:
        raise ValueError(
            f"Unknown reasoning effort {reasoning_effort!r} for model ID {model_id!r}; "
            f"accepted values: {sorted(_REASONING_EFFORTS)}."
        )
    resolved = (credentials or CredentialManager()).for_model(model_id)
    extra: dict[str, Any] = {} if reasoning_effort is None else {"params": {"reasoning_effort": reasoning_effort}}
    return OpenAIModel(
        client_args={
            "base_url": resolved.endpoint,
            "api_key": resolved.api_key.get_secret_value(),
        },
        model_id=resolved.deployment,
        **extra,
    )
