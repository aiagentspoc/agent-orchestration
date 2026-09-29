"""Integration tests verifying substrate model compatibility with hse-easy-mock MCP server.

Verifies that the Pydantic v2 substrate models defined in src.schemas
(RegulatoryUpdateSummary, RegulatoryDocument, CitationVerificationResult, TDIServiceOffering)
seamlessly parse, validate, and serialize actual live payload responses emitted by
the hse-easy-mock server (both via direct tool functions and FastMCP call_tool interface).
"""

import json

import pytest
import server

from src.schemas import (
    CitationVerificationResult,
    RegulatoryDocument,
    RegulatoryUpdateSummary,
    TDIServiceOffering,
)

# ============================================================================
# 1. Direct Server Tool Return Deserialization
# ============================================================================


def test_list_regulatory_updates_live_compatibility() -> None:
    """Verify RegulatoryUpdateSummary compatibility with server.list_regulatory_updates()."""
    updates = server.list_regulatory_updates()
    assert len(updates) > 0

    validated_updates: list[RegulatoryUpdateSummary] = []
    for item in updates:
        # Test model_validate from dict dump
        validated = RegulatoryUpdateSummary.model_validate(item.model_dump())
        assert validated.doc_id is not None
        assert validated.source in ("EUR_LEX", "GAZZETTA_UFFICIALE", "INAIL")
        assert validated.doc_type in ("directive", "regulation", "decree", "circular", "guideline")
        assert validated.impact_level in ("critical", "high", "medium", "low")
        assert validated.title
        assert validated.publication_date
        assert validated.canonical_url.startswith("http")

        # Test model_validate_json from raw json serialization
        validated_from_json = RegulatoryUpdateSummary.model_validate_json(item.model_dump_json())
        assert validated_from_json.doc_id == validated.doc_id

        validated_updates.append(validated)

    assert len(validated_updates) == len(updates)


def test_search_regulatory_docs_live_compatibility() -> None:
    """Verify RegulatoryUpdateSummary compatibility with server.search_regulatory_docs()."""
    queries = ["calore", "sicurezza", "preposti", "piombo"]
    for q in queries:
        results = server.search_regulatory_docs(query=q)
        assert len(results) > 0
        for item in results:
            validated = RegulatoryUpdateSummary.model_validate(item.model_dump())
            assert isinstance(validated, RegulatoryUpdateSummary)
            assert validated.doc_id


def test_get_document_by_id_all_docs_compatibility() -> None:
    """Verify RegulatoryDocument compatibility across all regulatory documents in the mock database."""
    # Retrieve all document summaries to obtain IDs
    summaries = server.list_regulatory_updates(limit=50)
    assert len(summaries) > 0

    for summary in summaries:
        doc = server.get_document_by_id(summary.doc_id)
        assert doc is not None

        # Validate with src.schemas.RegulatoryDocument
        validated_doc = RegulatoryDocument.model_validate(doc.model_dump())
        assert isinstance(validated_doc, RegulatoryDocument)
        assert isinstance(validated_doc, RegulatoryUpdateSummary)
        assert validated_doc.doc_id == summary.doc_id
        assert validated_doc.status in ("in_force", "amended", "repealed", "proposed")
        assert isinstance(validated_doc.target_sectors, list)
        assert isinstance(validated_doc.key_obligations, list)
        assert len(validated_doc.content_markdown) > 0

        # Validate JSON roundtrip
        json_str = validated_doc.model_dump_json()
        roundtripped = RegulatoryDocument.model_validate_json(json_str)
        assert roundtripped.doc_id == validated_doc.doc_id
        assert roundtripped.status == validated_doc.status


def test_verify_legal_citation_live_compatibility() -> None:
    """Verify CitationVerificationResult compatibility on both valid and invalid legal citations."""
    # Test valid citation
    valid_result = server.verify_legal_citation(citation="D.Lgs. 81/2008 Art. 37")
    validated_valid = CitationVerificationResult.model_validate(valid_result.model_dump())
    assert validated_valid.citation_input == "D.Lgs. 81/2008 Art. 37"
    assert validated_valid.is_valid is True
    assert validated_valid.status == "in_force"
    assert validated_valid.canonical_citation
    assert validated_valid.official_reference is not None
    assert "D.Lgs." in validated_valid.official_reference and "81" in validated_valid.official_reference

    # Test invalid / unrecognized citation
    invalid_result = server.verify_legal_citation(citation="Norma Inesistente 999/2099 Art. 1")
    validated_invalid = CitationVerificationResult.model_validate(invalid_result.model_dump())
    assert validated_invalid.is_valid is False
    assert validated_invalid.status == "unrecognized"
    assert validated_invalid.canonical_citation == "Norma Inesistente 999/2099 Art. 1"


def test_get_tdi_service_offerings_live_compatibility() -> None:
    """Verify TDIServiceOffering compatibility across TDI consulting offerings."""
    topics = ["heat_stress", "machinery", "chemical_risk", "fire_safety", "workplace_safety", ""]
    for topic in topics:
        services = server.get_tdi_service_offerings(topic=topic)
        assert len(services) > 0
        for s in services:
            validated = TDIServiceOffering.model_validate(s.model_dump())
            assert validated.service_id.startswith("tdi-")
            assert validated.service_name
            assert validated.topic_category
            assert validated.value_proposition
            assert validated.cta_headline
            assert validated.cta_body
            assert validated.landing_page_url.startswith("https://")


# ============================================================================
# 2. FastMCP Tool Interface Deserialization (MCP JSON payload roundtrip)
# ============================================================================


@pytest.mark.asyncio
async def test_fastmcp_call_tool_json_payload_compatibility() -> None:
    """Verify that FastMCP call_tool() responses directly deserialize into src.schemas models."""
    # 1. list_regulatory_updates tool call
    res_list = await server.mcp.call_tool("list_regulatory_updates", {"limit": 10})
    assert not res_list.is_error
    raw_list_json = res_list.content[0].text
    list_items = json.loads(raw_list_json)
    parsed_updates = [RegulatoryUpdateSummary.model_validate(item) for item in list_items]
    assert len(parsed_updates) > 0
    assert all(isinstance(u, RegulatoryUpdateSummary) for u in parsed_updates)

    # 2. search_regulatory_docs tool call
    res_search = await server.mcp.call_tool("search_regulatory_docs", {"query": "calore"})
    assert not res_search.is_error
    search_items = json.loads(res_search.content[0].text)
    parsed_searches = [RegulatoryUpdateSummary.model_validate(item) for item in search_items]
    assert len(parsed_searches) > 0

    # 3. get_document_by_id tool call
    target_id = parsed_updates[0].doc_id
    res_doc = await server.mcp.call_tool("get_document_by_id", {"doc_id": target_id})
    assert not res_doc.is_error
    raw_doc_json = res_doc.content[0].text
    parsed_doc = RegulatoryDocument.model_validate_json(raw_doc_json)
    assert isinstance(parsed_doc, RegulatoryDocument)
    assert parsed_doc.doc_id == target_id
    assert parsed_doc.content_markdown

    # 4. verify_legal_citation tool call
    res_cit = await server.mcp.call_tool("verify_legal_citation", {"citation": "D.Lgs. 81/2008 Art. 37"})
    assert not res_cit.is_error
    raw_cit_json = res_cit.content[0].text
    parsed_cit = CitationVerificationResult.model_validate_json(raw_cit_json)
    assert parsed_cit.is_valid is True
    assert parsed_cit.status == "in_force"

    # 5. get_tdi_service_offerings tool call
    res_tdi = await server.mcp.call_tool("get_tdi_service_offerings", {"topic": "heat_stress"})
    assert not res_tdi.is_error
    raw_tdi_json = res_tdi.content[0].text
    tdi_items = json.loads(raw_tdi_json)
    parsed_tdi = [TDIServiceOffering.model_validate(item) for item in tdi_items]
    assert len(parsed_tdi) > 0
    assert parsed_tdi[0].cta_headline
