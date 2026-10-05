"""Shared offline test harness for the HSE Easy pipeline (D16: zero LLM cost).

Everything here replays pre-recorded behaviour through the **real** Strands event
loop and the **real** ``HSEMockMCPClient`` surface, so tests exercise production
code paths without a network call, a subprocess or a credential.

Extracted from ``tests/test_unit/test_agents.py`` in Phase 6 so the orchestrator
integration suite can drive the same scripted models and substrate stubs, and
consolidated further in Phase 7 so ``tests/test_integration/test_e2e.py`` reuses
one definition of every scripted payload rather than adding a third copy.
"""

import copy
import json
import re
from collections.abc import AsyncIterator, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from strands import tool
from strands.models.model import Model
from strands.types.tools import AgentTool

from src.agents import QA_LEGAL_MODEL_ID, SCOUT_MODEL_ID, WRITER_MODEL_ID
from src.mcp_client import HSEMockMCPClient
from src.model_factory import ModelBuilder
from src.schemas import ModelRate, PipelineConfig

# ---------------------------------------------------------------------------
# Scripted stream-event fixtures
# ---------------------------------------------------------------------------


def tool_use_turn(
    name: str,
    args: dict[str, Any],
    *,
    input_tokens: int = 10,
    output_tokens: int = 5,
    cache_read_input_tokens: int = 0,
    latency_ms: int = 100,
) -> list[dict[str, Any]]:
    """Build one model turn that invokes ``name`` with ``args``.

    The structured-output tool is named after the Pydantic model class, so a
    turn naming ``PipelineScope`` produces structured output while a turn
    naming ``list_regulatory_updates`` produces a real substrate tool call.

    ``cache_read_input_tokens`` is emitted only when non-zero, exactly as the
    OpenAI provider does — it sets ``cacheReadInputTokens`` from
    ``prompt_tokens_details.cached_tokens`` and omits the key otherwise. It is a
    *subset of* ``input_tokens`` (D21), so it is deliberately not added into
    ``totalTokens``.
    """
    usage: dict[str, Any] = {
        "inputTokens": input_tokens,
        "outputTokens": output_tokens,
        "totalTokens": input_tokens + output_tokens,
    }
    if cache_read_input_tokens:
        usage["cacheReadInputTokens"] = cache_read_input_tokens
    return [
        {"messageStart": {"role": "assistant"}},
        {"contentBlockStart": {"start": {"toolUse": {"name": name, "toolUseId": f"{name}-1"}}}},
        {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(args)}}}},
        {"contentBlockStop": {}},
        {"messageStop": {"stopReason": "tool_use"}},
        {"metadata": {"usage": usage, "metrics": {"latencyMs": latency_ms}}},
    ]


def tool_uses_turn(
    *calls: tuple[str, dict[str, Any]],
    input_tokens: int = 10,
    output_tokens: int = 5,
    latency_ms: int = 100,
) -> list[dict[str, Any]]:
    """Build one model turn that requests every ``(name, args)`` call in ``calls``, in order.

    The same-turn counterpart of :func:`tool_use_turn`: one assistant message carrying one ``toolUse`` block per
    call, which is what a model asking for several tools at once sends. Each block gets its own ``toolUseId``,
    ``f"{name}-{position}"``, so the event loop can pair every result with its request even when a name repeats.
    """
    events: list[dict[str, Any]] = [{"messageStart": {"role": "assistant"}}]
    for position, (name, args) in enumerate(calls, start=1):
        events += [
            {"contentBlockStart": {"start": {"toolUse": {"name": name, "toolUseId": f"{name}-{position}"}}}},
            {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(args)}}}},
            {"contentBlockStop": {}},
        ]
    usage = {"inputTokens": input_tokens, "outputTokens": output_tokens, "totalTokens": input_tokens + output_tokens}
    events += [
        {"messageStop": {"stopReason": "tool_use"}},
        {"metadata": {"usage": usage, "metrics": {"latencyMs": latency_ms}}},
    ]
    return events


def text_turn(
    text: str,
    *,
    input_tokens: int = 3,
    output_tokens: int = 2,
    latency_ms: int = 50,
) -> list[dict[str, Any]]:
    """Build one model turn that emits plain text and stops."""
    return [
        {"messageStart": {"role": "assistant"}},
        {"contentBlockStart": {"start": {}}},
        {"contentBlockDelta": {"delta": {"text": text}}},
        {"contentBlockStop": {}},
        {"messageStop": {"stopReason": "end_turn"}},
        {
            "metadata": {
                "usage": {
                    "inputTokens": input_tokens,
                    "outputTokens": output_tokens,
                    "totalTokens": input_tokens + output_tokens,
                },
                "metrics": {"latencyMs": latency_ms},
            }
        },
    ]


class ScriptedModel(Model):
    """Deterministic offline ``Model`` replaying pre-scripted stream events.

    Turns are consumed in order. Exhausting the script raises rather than
    repeating the last turn, so an unexpected extra model round trip fails
    loudly instead of recursing.

    A turn may be a ``BaseException`` instead of a list of events, in which case
    it is raised when the event loop reaches it. That puts a genuine provider
    failure on a *chosen* round trip — the QA-Legal call of candidate 1, say —
    which :class:`FailingModel` cannot do because it fails on every invocation
    and the Writer and QA-Legal share one model object (ARCHITECTURE §3).
    """

    def __init__(self, turns: Sequence[Sequence[dict[str, Any]] | BaseException]) -> None:
        self._turns: list[list[dict[str, Any]] | BaseException] = [
            turn if isinstance(turn, BaseException) else list(turn) for turn in turns
        ]
        self._index: int = 0
        self.received_messages: list[list[dict[str, Any]]] = []
        self.received_tool_specs: list[list[dict[str, Any]] | None] = []
        self.received_system_prompts: list[str | None] = []
        self._config: dict[str, Any] = {"model_id": "scripted-test-model"}

    @property
    def turns_consumed(self) -> int:
        """Number of model round trips the event loop has driven so far."""
        return self._index

    def update_config(self, **model_config: Any) -> None:
        """Merge configuration overrides into the scripted config."""
        self._config.update(model_config)

    def get_config(self) -> dict[str, Any]:
        """Return the scripted model configuration."""
        return self._config

    def structured_output(self, output_model: Any, prompt: Any, system_prompt: str | None = None, **kwargs: Any) -> Any:
        """Fail loudly: the deprecated direct structured-output path is forbidden."""
        raise NotImplementedError(
            "ScriptedModel does not implement the deprecated Model.structured_output path; "
            "workers must use agent(prompt, structured_output_model=...)."
        )

    async def stream(
        self,
        messages: Any,
        tool_specs: Any = None,
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        """Replay the next scripted turn, capturing what the model received."""
        self.received_messages.append(copy.deepcopy(list(messages)))
        self.received_tool_specs.append(copy.deepcopy(tool_specs))
        self.received_system_prompts.append(system_prompt)
        if self._index >= len(self._turns):
            raise AssertionError(
                f"ScriptedModel script exhausted after {self._index} turn(s); the agent requested another."
            )
        turn = self._turns[self._index]
        self._index += 1
        if isinstance(turn, BaseException):
            raise turn
        for event in turn:
            yield event


# ---------------------------------------------------------------------------
# Stub substrate client — mirrors the HSEMockMCPClient tool-loading surface
# ---------------------------------------------------------------------------

SUBSTRATE_TOOL_NAMES: tuple[str, ...] = (
    "list_regulatory_updates",
    "search_regulatory_docs",
    "get_document_by_id",
    "verify_legal_citation",
    "get_tdi_service_offerings",
)

UPDATE_FIXTURE: dict[str, Any] = {
    "doc_id": "inail-2024-circ-calore",
    "source": "INAIL",
    "doc_type": "circular",
    "official_reference": "Circolare INAIL n. 28/2024",
    "title": "Circolare INAIL n. 28 del 24 luglio 2024: prevenzione delle patologie da calore",
    "publication_date": "2024-07-24",
    "effective_date": "2024-07-24",
    "impact_level": "high",
    "topic_tags": ["heat_stress", "construction_safety"],
    "summary": "Indicazioni operative per la prevenzione dello stress termico nei luoghi di lavoro all'aperto.",
    "canonical_url": "https://www.inail.it/circolare-inail-28-2024.html",
}


@tool
def list_regulatory_updates(source: str | None = None, limit: int = 10) -> str:
    """Stub substrate tool: list recent HSE regulatory updates."""
    return json.dumps([UPDATE_FIXTURE])


@tool
def search_regulatory_docs(query: str, topic: str | None = None) -> str:
    """Stub substrate tool: keyword search over the regulatory database."""
    return json.dumps([UPDATE_FIXTURE])


@tool
def get_document_by_id(doc_id: str) -> str:
    """Stub substrate tool: retrieve one full regulatory document."""
    return json.dumps(
        {
            **UPDATE_FIXTURE,
            "doc_id": doc_id,
            "status": "in_force",
            "target_sectors": ["construction", "agriculture"],
            "key_obligations": [
                "Riprogrammare i turni di lavoro nelle ore piu calde",
                "Garantire aree ombreggiate e dotazioni idriche",
            ],
            "penalties_summary": "Arresto o ammenda fino a 5.000 EUR per datori di lavoro e dirigenti.",
            "related_citations": ["D.Lgs. 81/2008 Art. 28"],
            "content_markdown": "# Circolare INAIL n. 28/2024",
        }
    )


@tool
def verify_legal_citation(citation: str) -> str:
    """Stub substrate tool: verify one legal citation."""
    return json.dumps(
        {
            "citation_input": citation,
            "is_valid": True,
            "status": "in_force",
            "canonical_citation": "D.Lgs. 9 aprile 2008, n. 81, Art. 37",
            "official_reference": "D.Lgs. 9 aprile 2008, n. 81",
            "official_url": "https://www.normattiva.it/urn:nir:stato:decreto.legislativo:2008-04-09;81~art37",
            "verified_against_doc_id": "gu-2024-dl-preposti",
            "notes": "Modificato da ultimo dal D.L. 19/2024.",
        }
    )


TDI_OFFERING_FIXTURE: dict[str, Any] = {
    "service_id": "tdi-srv-preposti-training",
    "service_name": "Corso di Formazione e Aggiornamento Preposti (D.Lgs. 81/08)",
    "topic_category": "workplace_safety",
    "applicable_sectors": ["construction", "manufacturing"],
    "value_proposition": "Percorsi formativi certificati per l'obbligo di aggiornamento biennale.",
    "cta_headline": "Adeguati ai nuovi obblighi formativi per i Preposti.",
    "cta_body": "Pianifica il piano formativo certificato con TDI.",
    "landing_page_url": "https://www.tdigroup.it/servizi/formazione-sicurezza-preposti",
}


@tool
def get_tdi_service_offerings(topic: str, sector: str | None = None) -> str:
    """Stub substrate tool: retrieve TDI consulting services and CTA templates."""
    return json.dumps([TDI_OFFERING_FIXTURE])


STUB_TOOLS: dict[str, AgentTool] = {
    "list_regulatory_updates": list_regulatory_updates,
    "search_regulatory_docs": search_regulatory_docs,
    "get_document_by_id": get_document_by_id,
    "verify_legal_citation": verify_legal_citation,
    "get_tdi_service_offerings": get_tdi_service_offerings,
}


class StubSubstrateClient:
    """Offline stand-in for ``HSEMockMCPClient``'s tool-loading surface."""

    def __init__(self) -> None:
        self.scope_requests: list[list[str]] = []
        self.list_all_calls: int = 0

    def list_all_tools(self) -> list[AgentTool]:
        """Return every substrate tool (the D19 default binding)."""
        self.list_all_calls += 1
        return list(STUB_TOOLS.values())

    def load_scoped_tools(self, names: Sequence[str]) -> list[AgentTool]:
        """Return only the named substrate tools."""
        self.scope_requests.append(list(names))
        return [STUB_TOOLS[name] for name in names]


class RecordingMCPSession:
    """Offline stand-in for ``strands.tools.mcp.MCPClient.list_tools_sync``."""

    def __init__(self) -> None:
        self.tool_filters_seen: list[dict[str, Any] | None] = []

    def list_tools_sync(self, tool_filters: dict[str, Any] | None = None, **kwargs: Any) -> list[AgentTool]:
        """Return the stub tools, honouring an ``allowed`` filter when given."""
        self.tool_filters_seen.append(tool_filters)
        allowed = (tool_filters or {}).get("allowed")
        if allowed is None:
            return list(STUB_TOOLS.values())
        return [tool_obj for name, tool_obj in STUB_TOOLS.items() if name in allowed]


def offline_client(session: "RecordingMCPSession | OfflineSubstrateSession") -> HSEMockMCPClient:
    """Build an ``HSEMockMCPClient`` wired to an offline session stub."""
    client = HSEMockMCPClient()
    client.mcp_client = session
    client._connected = True
    return client


#: The absolute bounds of a three-month lookback resolved against a current date of
#: 2026-09-22. Named so a test can assert that exactly these strings reached the
#: Scout's user turn rather than a re-derived pair.
SCOPE_DATE_FROM: Final[str] = "2026-06-22"
SCOPE_DATE_TO: Final[str] = "2026-09-22"

#: ``PipelineScope`` arguments as a scripted structured-output turn supplies them:
#: the five scope fields plus the ``context`` that code adds (DM2, DM5).
VALID_SCOPE_ARGS: dict[str, Any] = {
    "context": {"today": SCOPE_DATE_TO},
    "date_from": SCOPE_DATE_FROM,
    "date_to": SCOPE_DATE_TO,
    "sources": ["INAIL"],
    "sector_constraints": ["construction"],
}

# ---------------------------------------------------------------------------
# Phase 6 additions — offline substrate session and failing model
# ---------------------------------------------------------------------------


def mcp_envelope(payload: Any, tool_use_id: str = "call-1") -> dict[str, Any]:
    """Wrap ``payload`` in the MCP tool-result envelope ``call_tool_sync`` returns.

    Mirrors ``strands.tools.mcp.mcp_types.MCPToolResult``: a ``status``, a
    ``toolUseId`` and a list of content blocks whose ``text`` carries the JSON
    body that :meth:`HSEMockMCPClient._call_tool` parses.
    """
    return {
        "status": "success",
        "toolUseId": tool_use_id,
        "content": [{"text": json.dumps(payload, ensure_ascii=False)}],
    }


def document_fixture(doc_id: str) -> dict[str, Any]:
    """Return a full ``RegulatoryDocument`` payload for ``doc_id``."""
    return {
        **UPDATE_FIXTURE,
        "doc_id": doc_id,
        "status": "in_force",
        "target_sectors": ["construction", "agriculture"],
        "key_obligations": [
            "Riprogrammare i turni di lavoro nelle ore piu calde",
            "Garantire aree ombreggiate e dotazioni idriche",
        ],
        "penalties_summary": "Arresto o ammenda fino a 5.000 EUR per datori di lavoro e dirigenti.",
        "related_citations": ["D.Lgs. 81/2008 Art. 28"],
        "content_markdown": f"# Documento {doc_id}",
    }


class OfflineSubstrateSession:
    """Offline stand-in for the full ``MCPClient`` session surface.

    Supplies both halves the pipeline needs: ``list_tools_sync`` for agent tool
    binding and ``call_tool_sync`` for the orchestrator's own typed substrate
    calls. ``raise_on`` / ``raise_with`` let a test fail one named tool on a
    chosen call without touching production code.
    """

    def __init__(
        self,
        *,
        raise_on: set[str] | None = None,
        raise_with: Exception | None = None,
        raise_on_call_index: int | None = None,
        fail_listing_with: BaseException | None = None,
        fail_listing_on: Iterable[int] | None = None,
        fail_enter_with: BaseException | None = None,
        fail_exit_with: BaseException | None = None,
    ) -> None:
        self.fail_enter_with: BaseException | None = fail_enter_with
        self.fail_exit_with: BaseException | None = fail_exit_with
        #: Each ``"enter"`` and ``"exit"`` of the session, in order; a test may append its own markers alongside.
        self.events: list[str] = []
        self.raise_on: set[str] = set(raise_on or ())
        self.raise_with: Exception | None = raise_with
        self.raise_on_call_index: int | None = raise_on_call_index
        self.fail_listing_with: BaseException | None = fail_listing_with
        self.fail_listing_on: set[int] | None = None if fail_listing_on is None else set(fail_listing_on)
        self.tool_filters_seen: list[dict[str, Any] | None] = []
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.error_result: dict[str, Any] | None = None

    def __enter__(self) -> "OfflineSubstrateSession":
        """Open the session as ``HSEMockMCPClient.start()`` does, spawning nothing; or fail as a spawn can.

        ``fail_enter_with`` is raised from here, so ``start()`` classifies it exactly as it classifies a real spawn
        or handshake failure.
        """
        self.events.append("enter")
        if self.fail_enter_with is not None:
            raise self.fail_enter_with
        return self

    def __exit__(self, *exc_info: object) -> None:
        """Close the session as ``HSEMockMCPClient.stop()`` does; ``fail_exit_with`` makes it die as it closes."""
        self.events.append("exit")
        if self.fail_exit_with is not None:
            raise self.fail_exit_with

    def list_tools_sync(self, tool_filters: dict[str, Any] | None = None, **kwargs: Any) -> list[AgentTool]:
        """Return the stub substrate tools, honouring an ``allowed`` filter.

        ``fail_listing_with`` / ``fail_listing_on`` fail a chosen listing. That is
        the pipeline's only remaining per-candidate substrate call: D20 rebuilds an
        ``Agent`` per worker invocation and every build costs one ``list_tools_sync``
        round trip, so a substrate that dies between candidates surfaces here.
        """
        index = len(self.tool_filters_seen)
        self.tool_filters_seen.append(tool_filters)
        if self.fail_listing_with is not None and (self.fail_listing_on is None or index in self.fail_listing_on):
            raise self.fail_listing_with
        allowed = (tool_filters or {}).get("allowed")
        if allowed is None:
            return list(STUB_TOOLS.values())
        return [tool_obj for name, tool_obj in STUB_TOOLS.items() if name in allowed]

    def call_tool_sync(self, tool_use_id: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Return a fixture payload in MCP envelope shape, or raise/err on demand."""
        index = len(self.calls)
        self.calls.append((name, dict(arguments)))
        should_raise = name in self.raise_on and (
            self.raise_on_call_index is None or self.raise_on_call_index == index
        )
        if should_raise:
            if self.raise_with is not None:
                raise self.raise_with
            if self.error_result is not None:
                return self.error_result
            raise AssertionError(f"OfflineSubstrateSession asked to fail {name!r} with no exception configured")
        if name == "get_document_by_id":
            return mcp_envelope(document_fixture(arguments["doc_id"]), tool_use_id)
        if name in ("list_regulatory_updates", "search_regulatory_docs"):
            return mcp_envelope([UPDATE_FIXTURE], tool_use_id)
        if name == "get_tdi_service_offerings":
            return mcp_envelope([TDI_OFFERING_FIXTURE], tool_use_id)
        if name == "verify_legal_citation":
            return mcp_envelope(
                {
                    "citation_input": arguments.get("citation", ""),
                    "is_valid": True,
                    "status": "in_force",
                    "canonical_citation": "D.Lgs. 9 aprile 2008, n. 81, Art. 37",
                },
                tool_use_id,
            )
        raise AssertionError(f"OfflineSubstrateSession received an unknown tool {name!r}")


class FailingModel(Model):
    """A ``Model`` that raises ``exc`` the moment the event loop invokes it.

    Used by the full-fidelity diagnostics tests (PLAN §2.10) to put a genuine
    provider exception — ``openai.RateLimitError`` and friends — on the path the
    orchestrator actually catches.
    """

    def __init__(self, exc: Exception) -> None:
        self.exc = exc
        self.invocations: int = 0
        self._config: dict[str, Any] = {"model_id": "failing-test-model"}

    def update_config(self, **model_config: Any) -> None:
        """Merge configuration overrides into the failing model's config."""
        self._config.update(model_config)

    def get_config(self) -> dict[str, Any]:
        """Return the failing model's configuration."""
        return self._config

    def structured_output(self, output_model: Any, prompt: Any, system_prompt: str | None = None, **kwargs: Any):
        """Fail loudly: the deprecated direct structured-output path is forbidden."""
        raise NotImplementedError("FailingModel does not implement the deprecated structured_output path.")

    async def stream(
        self,
        messages: Any,
        tool_specs: Any = None,
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        """Raise the configured exception instead of streaming a turn."""
        self.invocations += 1
        raise self.exc
        yield {}  # pragma: no cover - unreachable, keeps the async generator type


# ---------------------------------------------------------------------------
# Phase 7 additions — the harness every pipeline test shares
#
# Consolidated here in Batch 0 so ``test_agents.py``, ``test_orchestrator.py``
# and ``test_e2e.py`` script the *same* payloads. Three divergent copies of a
# "draft" fixture make a cross-module assertion prove nothing.
# ---------------------------------------------------------------------------

#: Repository root, so every path a test touches is absolute (Windows).
REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]

#: The shipped template itself, never a hand-copied replica: a duplicate goes
#: stale the moment ``.agents/templates/draft.md`` changes.
REAL_TEMPLATE_PATH: Final[Path] = REPO_ROOT / ".agents" / "templates" / "draft.md"

#: Fixed cost rates, injected everywhere so no test reads ``.env`` (D16).
FAST_RATE: Final[ModelRate] = ModelRate(
    input_usd_per_mtok=0.25, cached_input_usd_per_mtok=0.025, output_usd_per_mtok=2.0
)
STRONG_RATE: Final[ModelRate] = ModelRate(
    input_usd_per_mtok=1.25, cached_input_usd_per_mtok=0.125, output_usd_per_mtok=10.0
)
TEST_RATES: Final[dict[str, ModelRate]] = {
    SCOUT_MODEL_ID: FAST_RATE,
    WRITER_MODEL_ID: STRONG_RATE,
    QA_LEGAL_MODEL_ID: STRONG_RATE,
}

#: ``PipelineScope`` structured-output arguments, derived from the schema-level
#: fixture so the two can never drift apart.
SCOPE_ARGS: dict[str, Any] = {**VALID_SCOPE_ARGS, "max_drafts": None}

#: The substrate slug every single-candidate scenario drafts from. ``DRAFT_ARGS``
#: carries it as its provenance, so a scripted Writer that simply replays
#: ``DRAFT_ARGS`` satisfies the orchestrator's ``source_doc_id`` check for that
#: candidate and fails it for any other — which is the point.
DEFAULT_DOC_ID: Final[str] = str(UPDATE_FIXTURE["doc_id"])

DRAFT_ARGS: dict[str, Any] = {
    "source_doc_id": DEFAULT_DOC_ID,
    "headline": "Circolare INAIL 28/2024: nuovi obblighi contro lo stress termico",
    "executive_summary": "I datori di lavoro devono riprogrammare i turni sopra i 35 gradi.",
    "article_body": "## Obblighi\nRiprogrammare i turni ai sensi di D.Lgs. 81/2008 Art. 28.",
    # Traceable to a real ``get_tdi_service_offerings`` result, as the Writer prompt requires.
    "tdi_cta": f"{TDI_OFFERING_FIXTURE['cta_headline']} Pianifica con TDI la valutazione del rischio calore.",
}

REVISED_DRAFT_ARGS: dict[str, Any] = {
    **DRAFT_ARGS,
    "headline": "Circolare INAIL 28/2024: obblighi corretti dopo l'audit legale",
    "article_body": (
        "## Obblighi\n"
        "Riprogrammare i turni ai sensi della Circolare INAIL n. 28/2024.\n"
        "Soglia di 35 gradi per l'attivazione della CIGO."
    ),
}

def draft_args(doc_id: str, **overrides: Any) -> dict[str, Any]:
    """Build ``ArticleDraft`` arguments whose provenance points at ``doc_id``.

    The orchestrator rejects a draft whose ``source_doc_id`` does not match the
    candidate it handed the Writer, so a multi-candidate scenario cannot replay
    one constant draft for every document.

    Args:
        doc_id: The substrate slug this draft was written from.
        **overrides: Any ``ArticleDraft`` field to replace.

    Returns:
        The scripted tool-use arguments for an ``ArticleDraft`` turn.
    """
    return {**DRAFT_ARGS, "source_doc_id": doc_id, **overrides}


def writer_turns(
    doc_id: str,
    *,
    draft: dict[str, Any] | None = None,
    fetch_doc_id: str | None = None,
    input_tokens: int = 10,
    output_tokens: int = 5,
    cache_read_input_tokens: int = 0,
    fetch_input_tokens: int = 10,
    fetch_output_tokens: int = 5,
) -> list[list[dict[str, Any]]]:
    """Script the two model round trips one **compliant** Writer invocation makes.

    ``WRITER_SYSTEM_PROMPT`` makes ``get_document_by_id(update.doc_id)`` a
    mandatory first step, and the orchestrator fails the candidate at
    ``fetch_document`` when that call is absent from the invocation's
    ``tool_invocations``. Every scenario that expects a draft therefore scripts
    the fetch turn before the ``ArticleDraft`` turn; omitting it is how a test
    exercises the detector rather than an oversight.

    Args:
        doc_id: The candidate slug the Writer was handed.
        draft: Explicit ``ArticleDraft`` arguments; defaults to
            :func:`draft_args` for ``doc_id``.
        fetch_doc_id: The slug the scripted fetch asks for; defaults to ``doc_id``.
        input_tokens: Input tokens reported by the ``ArticleDraft`` turn.
        output_tokens: Output tokens reported by the ``ArticleDraft`` turn.
        cache_read_input_tokens: Cached prefix reported by the ``ArticleDraft`` turn.
        fetch_input_tokens: Input tokens reported by the fetch turn.
        fetch_output_tokens: Output tokens reported by the fetch turn.

    Returns:
        The ``[fetch_turn, draft_turn]`` pair, in order.
    """
    return [
        tool_use_turn(
            "get_document_by_id",
            {"doc_id": doc_id if fetch_doc_id is None else fetch_doc_id},
            input_tokens=fetch_input_tokens,
            output_tokens=fetch_output_tokens,
        ),
        tool_use_turn(
            "ArticleDraft",
            draft if draft is not None else draft_args(doc_id),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_input_tokens=cache_read_input_tokens,
        ),
    ]


#: The canonical citation the scripted QA-Legal turns report as verified.
DEFAULT_VERIFIED_CITATIONS: Final[tuple[str, ...]] = ("D.Lgs. 9 aprile 2008, n. 81, Art. 28",)


def qa_args(
    *,
    status: str,
    citations: Sequence[str] = DEFAULT_VERIFIED_CITATIONS,
    issues: Sequence[str] | None = None,
    notes: str = "",
) -> dict[str, Any]:
    """Build ``QAReport`` structured-output arguments with a chosen verdict.

    Args:
        status: The tri-state verdict, ``PASS``, ``WARNING`` or ``ERROR``.
        citations: The citations the auditor reports as verified in force.
        issues: One entry per defect; ``None`` means a clean audit.
        notes: The reviewer note the draft renders.

    Returns:
        The scripted tool-use arguments for a ``QAReport`` turn.
    """
    return {
        "status": status,
        "verified_citations": list(citations),
        "issues": list(issues or []),
        "review_notes": notes,
    }


def scout_candidate_args(doc_id: str, score: float, rationale: str) -> dict[str, Any]:
    """Build one scripted ``ScoutCandidate`` payload for ``doc_id``.

    Args:
        doc_id: The substrate slug the candidate wraps.
        score: The newsworthiness score, in the closed interval [0.0, 1.0].
        rationale: Why the update qualifies for drafting.

    Returns:
        The scripted candidate arguments.
    """
    return {
        "update": {**UPDATE_FIXTURE, "doc_id": doc_id},
        "newsworthiness_score": score,
        "rationale": rationale,
    }


def scout_report_args(*doc_ids: str) -> dict[str, Any]:
    """Build ``ScoutReport`` arguments covering ``doc_ids``, ranked descending."""
    return {
        "candidates": [
            scout_candidate_args(
                doc_id,
                round(0.9 - 0.1 * index, 2),
                f"Obblighi immediati per i datori di lavoro ({doc_id}).",
            )
            for index, doc_id in enumerate(doc_ids)
        ]
    }


def sent_text(model: ScriptedModel, turn: int = 0) -> str:
    """Concatenate the text the model actually received on round trip ``turn``.

    Assertions are made against this rather than against a mocked runner: it is
    the literal prompt that reached the provider, so it cannot pass by proving
    the test called its own mock.
    """
    return "\n".join(
        block["text"]
        for message in model.received_messages[turn]
        for block in message.get("content", [])
        if isinstance(block, dict) and "text" in block
    )


#: The opening instruction each worker's user turn carries, used to tell one worker's
#: round trips from another's on the model they share (SPECIFICATIONS.md §1). Both
#: turns carry ``## AttemptRecord``, so the markers are sentences only one runner writes.
WRITER_PROMPT_SECTION: Final[str] = "Write a publication-ready HSE article"
QA_LEGAL_PROMPT_SECTION: Final[str] = "Audit the article draft"


def worker_prompts(model: ScriptedModel, section: str) -> list[str]:
    """Return the opening user turn of every invocation whose prompt names ``section``.

    D20 builds a fresh ``Agent`` per invocation, so an invocation's first round
    trip is the only one carrying exactly one message. Filtering on that, then on
    the runner's marker sentence, separates the Writer's turns from QA-Legal's on the strong
    model the two share — and gives a test the literal prompt that reached the
    provider rather than a mock's record of itself.

    Args:
        model: The scripted model the invocations ran against.
        section: ``WRITER_PROMPT_SECTION`` or ``QA_LEGAL_PROMPT_SECTION``.

    Returns:
        One prompt string per matching invocation, in invocation order.
    """
    prompts: list[str] = []
    for index, messages in enumerate(model.received_messages):
        if len(messages) != 1:
            continue
        text = sent_text(model, index)
        if section in text:
            prompts.append(text)
    return prompts


def rendered_total_tokens(text: str) -> int:
    """Read the token total a rendered draft's telemetry section reports.

    Args:
        text: The rendered Markdown of one draft.

    Returns:
        The integer ``{total_tokens}`` the draft carries.

    Raises:
        AssertionError: If the draft has no telemetry token total at all.
    """
    match = re.search(r"\((\d+) tokens\)", text)
    if match is None:
        raise AssertionError("draft is missing its telemetry token total")
    return int(match.group(1))


def pipeline_config(tmp_path: Path, **overrides: Any) -> PipelineConfig:
    """Build a run configuration rooted entirely inside ``tmp_path``.

    Nothing in the suite may write to the repository's own ``drafts/`` or
    ``logs/``, so both are redirected here by construction.
    """
    values: dict[str, Any] = {
        "drafts_dir": tmp_path / "drafts",
        "template_path": REAL_TEMPLATE_PATH,
        "log_dir": tmp_path / "logs",
    }
    values.update(overrides)
    return PipelineConfig(**values)


def scripted_model_builder(fast: Model, strong: Model) -> ModelBuilder:
    """Return a ``model_builder`` handing out one scripted model per model ID.

    Approach 1's form, restored against :class:`src.model_factory.ModelBuilder`: the Scout's ``gpt-5-mini`` gets
    ``fast`` and every ``gpt-5.4`` role gets ``strong``, so the roles sharing that ID consume one script in strict
    call order. ``reasoning_effort`` is accepted and ignored, which keeps that singleton.
    """

    def build(model_id: str, *, reasoning_effort: str | None = None) -> Model:
        return fast if model_id == SCOUT_MODEL_ID else strong

    return build


def scripted_model_builder_by_effort(models: Mapping[tuple[str, str | None], Model]) -> ModelBuilder:
    """Return a ``model_builder`` keyed on ``(model_id, reasoning_effort)``, failing on any key not scripted.

    At the default efforts this separates the Scout ``(gpt-5-mini, None)``, the Writer ``(gpt-5.4, high)`` and
    QA-Legal ``(gpt-5.4, medium)``. It cannot separate QA-Legal from the Supervisor, which is also
    ``(gpt-5.4, medium)`` by default: a test that needs both scripted apart must give one of them another effort.

    Args:
        models: The scripted model for each ``(model_id, reasoning_effort)`` a test expects to be built.

    Returns:
        The builder. Asking it for an unscripted key raises ``AssertionError`` naming the key.
    """

    def build(model_id: str, *, reasoning_effort: str | None = None) -> Model:
        key = (model_id, reasoning_effort)
        if key not in models:
            raise AssertionError(f"No scripted model for {key!r}; scripted: {sorted(models, key=repr)!r}")
        return models[key]

    return build


# ---------------------------------------------------------------------------
# What a Supervisor tool may return (SPECIFICATIONS.md D-F, §7.2)
# ---------------------------------------------------------------------------

#: Keys that would mean article text or a candidate reached the Supervisor. Matched as keys, at any depth, never as
#: substrings: ``candidates`` is the ``ScoutReport``'s own field.
FORBIDDEN_SUPERVISOR_KEYS: Final[frozenset[str]] = frozenset(
    {"draft", "candidate", "headline", "article_body", "executive_summary"}
)


def json_keys(value: Any) -> set[str]:
    """Every key of every JSON object in ``value``, at any depth."""
    if isinstance(value, dict):
        return set(value) | {key for item in value.values() for key in json_keys(item)}
    if isinstance(value, list):
        return {key for item in value for key in json_keys(item)}
    return set()
