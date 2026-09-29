import pytest
from mcp.shared.exceptions import MCPError as TransportProtocolError
from strands.types.exceptions import MCPClientInitializationError

from src.mcp_client import (
    HSEMockMCPClient,
    MCPClientError,
    MCPClientNotConnectedError,
    MCPConnectionError,
    MCPToolExecutionError,
)
from src.schemas import (
    CitationVerificationResult,
    RegulatoryDocument,
    RegulatoryUpdateSummary,
    TDIServiceOffering,
)


def test_mcp_client_connection_handshake():
    """Verify client connects over stdio and lists registered tools."""
    client = HSEMockMCPClient()
    client.start()
    try:
        tools = [tool.tool_name for tool in client.mcp_client.list_tools_sync()]
        assert "list_regulatory_updates" in tools
        assert "search_regulatory_docs" in tools
        assert "get_document_by_id" in tools
        assert "verify_legal_citation" in tools
        assert "get_tdi_service_offerings" in tools
    finally:
        client.stop()

def test_mcp_client_context_manager_lifecycle():
    """Verify context manager enters cleanly, exposes functional tools, and tears down subprocess on exit."""
    with HSEMockMCPClient() as client:
        tools = [tool.tool_name for tool in client.mcp_client.list_tools_sync()]
        assert "list_regulatory_updates" in tools

def test_mcp_client_absolute_path_resolution(monkeypatch):
    """Verify client resolves the server directory as an absolute path via HSE_MCP_SERVER_PATH."""
    monkeypatch.setenv("HSE_MCP_SERVER_PATH", "/tmp/custom-mcp-server")
    client = HSEMockMCPClient()
    assert client.server_dir == "/tmp/custom-mcp-server"

    monkeypatch.delenv("HSE_MCP_SERVER_PATH", raising=False)
    client2 = HSEMockMCPClient()
    assert client2.server_dir == r"C:\Users\Saksham\Git\poc\AIAgents\mcp-server"

def test_client_list_regulatory_updates():
    """Call list_regulatory_updates and verify returns List[RegulatoryUpdateSummary]."""
    with HSEMockMCPClient() as client:
        updates = client.list_regulatory_updates(source="INAIL", limit=5)
        assert isinstance(updates, list)
        assert len(updates) > 0
        for u in updates:
            assert isinstance(u, RegulatoryUpdateSummary)
            assert u.source == "INAIL"

def test_client_search_regulatory_docs():
    """Call search_regulatory_docs and verify returns List[RegulatoryUpdateSummary]."""
    with HSEMockMCPClient() as client:
        updates = client.search_regulatory_docs(query="calore")
        assert isinstance(updates, list)
        assert len(updates) > 0
        for u in updates:
            assert isinstance(u, RegulatoryUpdateSummary)

def test_client_get_document_by_id():
    """Call get_document_by_id and verify returns RegulatoryDocument."""
    with HSEMockMCPClient() as client:
        doc = client.get_document_by_id("gu-2024-dl-preposti")
        assert isinstance(doc, RegulatoryDocument)
        assert doc.content_markdown
        assert doc.key_obligations
        assert doc.penalties_summary

def test_client_verify_legal_citation_valid():
    """Call verify_legal_citation and assert is_valid is True."""
    with HSEMockMCPClient() as client:
        res = client.verify_legal_citation("D.Lgs. 81/2008 Art. 37")
        assert isinstance(res, CitationVerificationResult)
        assert res.is_valid is True
        assert res.status == "in_force"

def test_client_verify_legal_citation_invalid():
    """Call verify_legal_citation and assert is_valid is False."""
    with HSEMockMCPClient() as client:
        res = client.verify_legal_citation("Invalid Citation XYZ")
        assert isinstance(res, CitationVerificationResult)
        assert res.is_valid is False
        assert res.status == "unrecognized"


def test_client_get_tdi_service_offerings():
    with HSEMockMCPClient() as client:
        res = client.get_tdi_service_offerings(topic="workplace_safety")
        assert isinstance(res, list)
        assert len(res) > 0
        assert isinstance(res[0], TDIServiceOffering)

def test_scoped_tool_lists_share_one_session():
    """Three per-agent tool scopes resolve off a single live substrate session."""
    with HSEMockMCPClient() as client:
        all_tools = client.list_all_tools()
        assert {t.tool_name for t in all_tools} == {
            "list_regulatory_updates",
            "search_regulatory_docs",
            "get_document_by_id",
            "verify_legal_citation",
            "get_tdi_service_offerings",
        }

        scout_scope = client.load_scoped_tools(
            ["list_regulatory_updates", "search_regulatory_docs", "get_document_by_id"]
        )
        writer_scope = client.load_scoped_tools(["get_tdi_service_offerings", "get_document_by_id"])
        qa_scope = client.load_scoped_tools(["verify_legal_citation"])

        assert {t.tool_name for t in scout_scope} == {
            "list_regulatory_updates",
            "search_regulatory_docs",
            "get_document_by_id",
        }
        assert {t.tool_name for t in writer_scope} == {"get_tdi_service_offerings", "get_document_by_id"}
        assert {t.tool_name for t in qa_scope} == {"verify_legal_citation"}

        # The same session still serves unscoped listings afterwards.
        assert len(client.list_all_tools()) == 5

def test_client_error_handling_nonexistent_doc():
    with HSEMockMCPClient() as client:
        with pytest.raises(MCPToolExecutionError):
            client.get_document_by_id("nonexistent-slug")

def test_client_not_started_error():
    client = HSEMockMCPClient()
    with pytest.raises(MCPClientNotConnectedError):
        client.get_tdi_service_offerings(topic="workplace_safety")


# ============================================================================
# Phase 6: transport classification and full-fidelity error envelopes (D22)
# ============================================================================


class _DeadTransportSession:
    """Offline stand-in for a ``MCPClient`` whose subprocess never comes up."""

    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    def __enter__(self) -> "_DeadTransportSession":
        raise self.exc

    def __exit__(self, *exc_info: object) -> None:
        return None


class _ErroringSession:
    """Offline stand-in returning a multi-block MCP error envelope."""

    def __init__(self, result: dict) -> None:
        self.result = result

    def call_tool_sync(self, tool_use_id: str, name: str, arguments: dict) -> dict:
        return self.result


def _error_envelope() -> dict:
    """A server-side error result with two content blocks and structured content."""
    return {
        "status": "error",
        "toolUseId": "get_document_by_id_id",
        "isError": True,
        "content": [
            {"text": "Document not found: nonexistent-slug"},
            {"text": "Hint: call search_regulatory_docs to discover valid slugs."},
        ],
        "structuredContent": {"error": "document_not_found", "doc_id": "nonexistent-slug"},
    }


def test_mcp_client_wraps_transport_errors():
    """A dead transport raises the pipeline's own error type, cause chain intact (D13/D22).

    Without this the orchestrator would have to import ``strands.types.exceptions``
    directly to tell a dead subprocess from a server-side tool error.
    """
    original = MCPClientInitializationError("the client initialization failed")
    client = HSEMockMCPClient()
    client.mcp_client = _DeadTransportSession(original)

    with pytest.raises(MCPConnectionError) as excinfo:
        client.start()

    assert excinfo.value.__cause__ is original
    assert "the client initialization failed" in str(excinfo.value)
    assert isinstance(excinfo.value, MCPClientError)


def test_mcp_client_tool_error_still_raises_tool_execution_error():
    """Regression: a server-side failure keeps its class and must not be reclassified."""
    client = HSEMockMCPClient()
    client.mcp_client = _ErroringSession(_error_envelope())
    client._connected = True

    with pytest.raises(MCPToolExecutionError) as excinfo:
        client.get_document_by_id("nonexistent-slug")

    assert not isinstance(excinfo.value, MCPConnectionError)


def test_mcp_client_error_carries_full_envelope():
    """D22: nothing is flattened to ``content[0].text``; the whole result survives."""
    envelope = _error_envelope()
    client = HSEMockMCPClient()
    client.mcp_client = _ErroringSession(envelope)
    client._connected = True

    with pytest.raises(MCPToolExecutionError) as excinfo:
        client.get_document_by_id("nonexistent-slug")

    error = excinfo.value
    assert error.result == envelope
    assert error.tool_name == "get_document_by_id"
    message = str(error)
    assert "Document not found: nonexistent-slug" in message
    assert "Hint: call search_regulatory_docs" in message
    assert "document_not_found" in message


class _MidCallTransportDeathSession:
    """Offline stand-in for a session whose transport dies *after* connecting.

    ``_DeadTransportSession`` above covers the ``start()`` half. This one covers
    the half the orchestrator's batch-abort contract actually depends on: the
    transport surviving the handshake and then dying inside a tool call.
    """

    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    def call_tool_sync(self, tool_use_id: str, name: str, arguments: dict) -> dict:
        raise self.exc


@pytest.mark.parametrize(
    "original",
    [
        MCPClientInitializationError("client session is not running"),
        TransportProtocolError(code=-32000, message="connection closed by peer"),
    ],
    ids=["strands-initialization", "mcp-protocol"],
)
def test_mcp_client_wraps_mid_call_transport_errors(original: Exception) -> None:
    """A transport that dies mid-call is classified as a connection failure, not a tool error.

    The orchestrator separates the two by class alone: ``MCPConnectionError``
    aborts the whole batch (ARCHITECTURE §7 row 2) while ``MCPToolExecutionError``
    costs a single candidate. Neither raw SDK class is in the orchestrator's
    transport tuple, so if this wrap were lost a dead transport would be
    downgraded to a per-candidate failure and the batch would keep calling it.
    """
    client = HSEMockMCPClient()
    client.mcp_client = _MidCallTransportDeathSession(original)
    client._connected = True

    with pytest.raises(MCPConnectionError) as excinfo:
        client.get_document_by_id("inail-2024-circ-calore")

    assert excinfo.value.__cause__ is original
    assert "get_document_by_id" in str(excinfo.value)
    assert str(original) in str(excinfo.value)
    assert not isinstance(excinfo.value, MCPToolExecutionError)


# ============================================================================
# Item 1: the citation -> related-document resolution path the Writer is told to use
# ============================================================================


def test_related_citations_are_citation_text_not_substrate_ids():
    """The premise behind the Writer's old Method was false, and this pins it.

    ``RegulatoryDocument.related_citations`` holds human citation *strings*, so
    "call ``get_document_by_id`` for each related instrument" has no ID to pass.
    Minting one from the text — ``messaggio-inps-2729-2023`` — is what produced
    three ``ValueError``s in the Phase 7 live run.
    """
    with HSEMockMCPClient() as client:
        doc = client.get_document_by_id("inail-2024-circ-calore")

        assert "D.Lgs. 81/2008 Art. 28" in doc.related_citations
        # Not one of them is a substrate slug, so none can be fetched directly.
        assert all(" " in citation for citation in doc.related_citations)

        invented = "messaggio-inps-2729-2023"
        assert invented not in doc.related_citations
        with pytest.raises(MCPToolExecutionError):
            client.get_document_by_id(invented)


def test_verified_against_doc_id_is_the_route_to_a_related_document():
    """``verify_legal_citation`` -> ``verified_against_doc_id`` -> ``get_document_by_id``.

    This is the resolution path the Writer prompt now prescribes, asserted against
    the live substrate rather than against a fixture, so the prompt cannot describe
    a round trip the corpus does not actually support.
    """
    with HSEMockMCPClient() as client:
        result = client.verify_legal_citation("D.Lgs. 81/2008 Art. 28")

        assert result.is_valid is True
        assert result.status == "in_force"
        assert result.verified_against_doc_id is not None

        related = client.get_document_by_id(result.verified_against_doc_id)
        assert isinstance(related, RegulatoryDocument)
        assert related.doc_id == result.verified_against_doc_id


def test_unrecognised_related_citations_resolve_to_no_document():
    """A source document's own related citations may be unknown to the registry.

    Two of ``inail-2024-circ-calore``'s are, which is why the Writer must assert no
    legal effect on an unverified reference instead of treating the source's own
    metadata as self-verifying.
    """
    with HSEMockMCPClient() as client:
        for citation in ("Messaggio INPS n. 2729/2023", "D.L. 98/2023"):
            result = client.verify_legal_citation(citation)

            assert result.is_valid is False
            assert result.status == "unrecognized"
            assert result.verified_against_doc_id is None


class _DeadListingSession:
    """A session whose ``list_tools_sync`` raises, as a dead transport really does."""

    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    def list_tools_sync(self, tool_filters: dict | None = None, **kwargs) -> list:
        raise self.exc


@pytest.mark.parametrize(
    "original",
    [
        MCPClientInitializationError("client session is not running"),
        TransportProtocolError(code=-32000, message="connection closed by peer"),
    ],
    ids=["strands-initialization", "mcp-protocol"],
)
@pytest.mark.parametrize(
    "listing",
    [
        lambda client: client.list_all_tools(),
        lambda client: client.load_scoped_tools(["get_document_by_id"]),
    ],
    ids=["list_all_tools", "load_scoped_tools"],
)
def test_mcp_client_wraps_transport_errors_raised_while_listing_tools(listing, original: Exception) -> None:
    """Tool *listing* classifies a dead transport exactly as tool *calling* does.

    D20 rebuilds a Strands ``Agent`` per worker invocation and every build costs
    one ``list_tools_sync`` round trip, so once document dereferencing moved into
    the Writer (D23) the listing became the orchestrator's only per-candidate
    substrate touch. Without this wrap, a transport that dies between candidates
    surfaces as a raw SDK exception, which is not in the orchestrator's transport
    tuple: the batch would downgrade it to a single-candidate failure and keep
    building agents against a dead session instead of aborting (ARCHITECTURE §7
    row 2).
    """
    client = HSEMockMCPClient()
    client.mcp_client = _DeadListingSession(original)
    client._connected = True

    with pytest.raises(MCPConnectionError) as excinfo:
        listing(client)

    assert excinfo.value.__cause__ is original
    assert str(original) in str(excinfo.value)
    assert not isinstance(excinfo.value, MCPToolExecutionError)
