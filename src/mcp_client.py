"""Typed FastMCP stdio client wrapper for HSE-Easy-Mock substrate.

Error handling follows D22: nothing about a substrate failure is flattened,
truncated or swallowed. A dead transport and a server-side tool failure are
deliberately distinct exception types, because the orchestrator must treat
them differently — the first aborts the batch, the second costs one candidate
(ARCHITECTURE §7) — and classifying them here keeps ``strands`` and ``mcp``
exception imports out of ``src/orchestrator.py`` (D13).
"""

import json
import os
from collections.abc import Sequence
from types import TracebackType
from typing import Any

from mcp.shared.exceptions import MCPError as TransportProtocolError
from strands.tools.mcp import MCPClient
from strands.tools.mcp.mcp_agent_tool import MCPAgentTool
from strands.types.exceptions import MCPClientInitializationError

from .schemas import CitationVerificationResult, RegulatoryDocument, RegulatoryUpdateSummary, TDIServiceOffering


class MCPClientError(Exception):
    """Base exception for MCP client errors."""

class MCPClientNotConnectedError(MCPClientError):
    """Raised when calling methods before start() or outside with block."""

class MCPConnectionError(MCPClientError):
    """Raised when the substrate transport itself fails: subprocess or protocol.

    Distinct from :class:`MCPToolExecutionError`, which means the server was
    reached and answered with a failure. This one means there is no longer a
    server to talk to, so the orchestrator aborts the batch rather than skipping
    one candidate. The original exception is always preserved as ``__cause__``.
    """


class MCPToolExecutionError(MCPClientError):
    """Raised when a tool fails on the server side, carrying the whole result.

    The full ``MCPToolResult`` envelope — status, ``isError``, **every** content
    block and any structured content — is retained on the exception and rendered
    into its message, rather than being reduced to ``content[0]["text"]`` (D22).
    """

    def __init__(self, message: str, result: dict[str, Any] | None = None, tool_name: str | None = None) -> None:
        super().__init__(message)
        self.result: dict[str, Any] | None = result
        self.tool_name: str | None = tool_name

def _describe_tool_result(tool_name: str, result: dict[str, Any]) -> str:
    """Render a failed tool result in full, verbatim (D22).

    Every content block is included, not just the first, along with the status
    flags and any structured content: an error envelope's later blocks routinely
    carry the actionable half of the diagnosis.
    """
    blocks = [
        str(block.get("text"))
        for block in result.get("content", [])
        if isinstance(block, dict) and block.get("text") is not None
    ]
    parts = [f"Substrate tool {tool_name!r} failed"]
    parts.append(f"status={result.get('status')!r} isError={result.get('isError')!r}")
    parts.append("content=[" + " | ".join(blocks) + "]" if blocks else "content=[]")
    structured = result.get("structuredContent")
    if structured is not None:
        parts.append(f"structuredContent={structured!r}")
    return "; ".join(parts)


class HSEMockMCPClient:
    """Mock MCP Client wrapping Strands MCPClient."""
    
    def __init__(self) -> None:
        self.server_dir = os.environ.get("HSE_MCP_SERVER_PATH", r"C:\Users\Saksham\Git\poc\AIAgents\mcp-server")
        clients = MCPClient.load_servers({
            "mock": {
                "command": "uv",
                "args": ["run", "--quiet", "--directory", self.server_dir, "fastmcp", "run", "server.py"],
                "env": {"PYTHONUNBUFFERED": "1"}
            }
        })
        self.mcp_client = clients[0]
        self._connected = False

    def start(self) -> None:
        """Explicitly start the MCP client subprocess.

        Raises:
            MCPConnectionError: If the subprocess or the MCP handshake fails. The
                original exception is chained, so the launch command, the OS error
                and the full traceback all reach the log (D22).
        """
        try:
            self.mcp_client.__enter__()
        except (MCPClientInitializationError, TransportProtocolError, OSError) as exc:
            raise MCPConnectionError(
                f"Could not start the hse-easy-mock substrate from {self.server_dir!r}: {exc}"
            ) from exc
        self._connected = True

    def stop(self) -> None:
        """Explicitly stop the MCP client subprocess."""
        self.mcp_client.__exit__(None, None, None)
        self._connected = False

    def __enter__(self) -> "HSEMockMCPClient":
        self.start()
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None
    ) -> None:
        self.stop()

    def _ensure_connected(self) -> None:
        if not self._connected:
            raise MCPClientNotConnectedError("Client not connected. Call start() or use context manager.")

    def _call_tool(self, tool_name: str, args: dict) -> dict:
        """Invoke one substrate tool and return its decoded JSON payload.

        Raises:
            MCPConnectionError: If the transport died mid-call.
            MCPToolExecutionError: If the server answered with an error result.
                The whole envelope is carried on the exception (D22).
        """
        self._ensure_connected()
        try:
            res = self.mcp_client.call_tool_sync(tool_name + "_id", tool_name, args)
        except (MCPClientInitializationError, TransportProtocolError) as exc:
            raise MCPConnectionError(
                f"The hse-easy-mock substrate transport failed during {tool_name!r}: {exc}"
            ) from exc
        if res.get("status") == "error" or res.get("isError"):
            raise MCPToolExecutionError(_describe_tool_result(tool_name, res), result=dict(res), tool_name=tool_name)
        return json.loads(res["content"][0]["text"])

    def _list_tools(self, tool_filters: dict | None = None) -> list[MCPAgentTool]:
        """List the advertised tools, classifying a dead transport as a connection failure.

        The same classification ``_call_tool`` applies, for the same reason: the
        orchestrator separates a dead transport from a server-side tool error by
        exception class alone, and a raw SDK exception belongs to neither tuple.
        Listing is the substrate touch every ``Agent`` build makes (D20), so once
        document dereferencing moved into the Writer (D23) it became the
        orchestrator's only per-candidate substrate call — leaving it unclassified
        would downgrade a dead session to a single-candidate failure and keep the
        batch talking to it.

        Args:
            tool_filters: ``list_tools_sync`` filters, or ``None`` for every tool.

        Returns:
            The advertised tools, filtered as requested.

        Raises:
            MCPConnectionError: If the transport died. The original exception is
                chained, so the full traceback survives (D22).
        """
        try:
            return list(self.mcp_client.list_tools_sync(tool_filters=tool_filters))
        except (MCPClientInitializationError, TransportProtocolError) as exc:
            raise MCPConnectionError(
                f"The hse-easy-mock substrate transport failed while listing tools: {exc}"
            ) from exc

    def list_all_tools(self) -> list[MCPAgentTool]:
        """Return every substrate tool advertised by the connected server."""
        self._ensure_connected()
        return self._list_tools()

    def load_scoped_tools(self, names: Sequence[str]) -> list[MCPAgentTool]:
        """Return only the named substrate tools, for per-agent tool scoping.

        The filter is applied per listing, so several scopes can be resolved
        off the one shared stdio session this client owns.
        """
        self._ensure_connected()
        return self._list_tools(tool_filters={"allowed": list(names)})

    def list_regulatory_updates(
        self, 
        source: str | None = None, 
        date_from: str | None = None, 
        date_to: str | None = None, 
        limit: int = 10
    ) -> list[RegulatoryUpdateSummary]:
        args = {"limit": limit}
        if source:
            args["source"] = source
        if date_from:
            args["date_from"] = date_from
        if date_to:
            args["date_to"] = date_to
        
        data = self._call_tool("list_regulatory_updates", args)
        return [RegulatoryUpdateSummary.model_validate(item) for item in data]

    def search_regulatory_docs(
        self, 
        query: str, 
        source: str | None = None, 
        topic: str | None = None, 
        sector: str | None = None
    ) -> list[RegulatoryUpdateSummary]:
        args = {"query": query}
        if source:
            args["source"] = source
        if topic:
            args["topic"] = topic
        if sector:
            args["sector"] = sector
        
        data = self._call_tool("search_regulatory_docs", args)
        return [RegulatoryUpdateSummary.model_validate(item) for item in data]

    def get_document_by_id(self, doc_id: str) -> RegulatoryDocument:
        data = self._call_tool("get_document_by_id", {"doc_id": doc_id})
        return RegulatoryDocument.model_validate(data)

    def verify_legal_citation(self, citation: str, source: str | None = None) -> CitationVerificationResult:
        args = {"citation": citation}
        if source:
            args["source"] = source
        data = self._call_tool("verify_legal_citation", args)
        return CitationVerificationResult.model_validate(data)

    def get_tdi_service_offerings(self, topic: str, sector: str | None = None) -> list[TDIServiceOffering]:
        args = {"topic": topic}
        if sector:
            args["sector"] = sector
        data = self._call_tool("get_tdi_service_offerings", args)
        return [TDIServiceOffering.model_validate(item) for item in data]
