"""Unit tests for HSE Easy Pydantic v2 schemas and data contracts.

Batch 1: Substrate data models (RegulatoryUpdateSummary, RegulatoryDocument,
CitationVerificationResult, TDIServiceOffering). The Approach 2 contracts of
SPECIFICATIONS.md §6 (IMPLEMENTATION_PLAN.md Iteration 4) follow the reused ones.
"""

import inspect
import json
from datetime import date
from enum import IntEnum
from pathlib import Path
from typing import Any, get_args

import pytest
from pydantic import BaseModel, ValidationError

from src import schemas
from src.schemas import (
    MAX_ATTEMPTS_PER_DOC,
    AgentContext,
    AgentTelemetry,
    ArticleDraft,
    AttemptRecord,
    CitationVerificationResult,
    DocumentRecord,
    DraftMetadata,
    DraftResult,
    ExitCode,
    FailureRecord,
    FailureStage,
    GuardrailName,
    GuardrailViolation,
    ModelRate,
    PipelineConfig,
    PipelineScope,
    QAReport,
    RegulatoryDocument,
    RegulatoryUpdateSummary,
    RemoteErrorDetail,
    RunContext,
    RunState,
    ScoutCandidate,
    ScoutReport,
    StageTelemetry,
    TDIServiceOffering,
    ToolResult,
)
from tests.support.scripted import DEFAULT_DOC_ID, DRAFT_ARGS, pipeline_config, qa_args, scout_candidate_args

# ============================================================================
# Batch 1: Substrate Models Tests
# ============================================================================


def test_regulatory_update_summary_validation() -> None:
    """Test valid instantiation, literal constraints, and defaults of RegulatoryUpdateSummary."""
    valid_payload = {
        "doc_id": "inail-2024-circ-calore",
        "source": "INAIL",
        "doc_type": "circular",
        "official_reference": "Circolare INAIL n. 28/2024",
        "title": "Linee guida per la gestione del rischio calore nei luoghi di lavoro",
        "publication_date": "2024-07-01",
        "impact_level": "high",
        "summary": "Misure precauzionali e tutela dei lavoratori esposti ad elevate temperature ambientali.",
        "canonical_url": "https://www.inail.it/atti/circolare-28-2024.html",
    }
    model = RegulatoryUpdateSummary(**valid_payload)
    assert model.doc_id == "inail-2024-circ-calore"
    assert model.source == "INAIL"
    assert model.doc_type == "circular"
    assert model.impact_level == "high"
    assert model.effective_date is None
    assert model.topic_tags == []

    # Test invalid literal for source
    with pytest.raises(ValidationError) as exc_info:
        RegulatoryUpdateSummary(**{**valid_payload, "source": "INVALID_SOURCE"})
    assert "source" in str(exc_info.value)

    # Test invalid literal for impact_level
    with pytest.raises(ValidationError) as exc_info:
        RegulatoryUpdateSummary(**{**valid_payload, "impact_level": "extreme"})
    assert "impact_level" in str(exc_info.value)

    # Test missing mandatory field
    incomplete_payload = valid_payload.copy()
    del incomplete_payload["doc_id"]
    with pytest.raises(ValidationError) as exc_info:
        RegulatoryUpdateSummary(**incomplete_payload)
    assert "doc_id" in str(exc_info.value)


def test_regulatory_document_inheritance_and_fields() -> None:
    """Test RegulatoryDocument inherits from RegulatoryUpdateSummary and validates tier 2 fields."""
    valid_doc_payload = {
        "doc_id": "gu-2024-dl-preposti",
        "source": "GAZZETTA_UFFICIALE",
        "doc_type": "decree",
        "official_reference": "D.Lgs. 81/2008 Art. 19",
        "title": "Modifiche e integrazioni alle attribuzioni del preposto per la sicurezza",
        "publication_date": "2024-05-15",
        "effective_date": "2024-06-01",
        "impact_level": "critical",
        "topic_tags": ["workplace_safety", "preposti"],
        "summary": "Nuovi obblighi di vigilanza e interruzione temporanea delle lavorazioni.",
        "canonical_url": "https://www.gazzettaufficiale.it/eli/id/2024/05/15/24G00088/sg",
        "status": "in_force",
        "target_sectors": ["manufacturing", "construction"],
        "key_obligations": [
            "Sovrintendere e vigilare sulla conformità alle norme di prevenzione",
            "Interrompere l'attività lavorativa in caso di pericolo grave e immediato",
        ],
        "penalties_summary": "Arresto fino a 2 mesi o ammenda da 491,40 a 1.474,21 euro",
        "related_citations": ["D.Lgs. 81/2008 Art. 19", "D.Lgs. 81/2008 Art. 37"],
        "content_markdown": "# Modifiche D.Lgs. 81/2008\n\nTesto coordinato con le novità...",
    }
    model = RegulatoryDocument(**valid_doc_payload)
    assert isinstance(model, RegulatoryUpdateSummary)
    assert model.status == "in_force"
    assert len(model.target_sectors) == 2
    assert len(model.key_obligations) == 2
    assert model.penalties_summary is not None
    assert "preposti" in model.topic_tags
    assert "# Modifiche" in model.content_markdown

    # Test invalid status literal
    with pytest.raises(ValidationError) as exc_info:
        RegulatoryDocument(**{**valid_doc_payload, "status": "deprecated"})
    assert "status" in str(exc_info.value)


def test_citation_verification_result_validation() -> None:
    """Test CitationVerificationResult fields, status literals, and optional fields."""
    valid_citation = {
        "citation_input": "D.Lgs. 81/2008 Art. 37",
        "is_valid": True,
        "status": "in_force",
        "canonical_citation": "Decreto Legislativo 9 aprile 2008, n. 81 - Articolo 37",
        "official_reference": "D.Lgs. 81/2008",
        "official_url": "https://www.normattiva.it/uri-res/N2Ls?urn:nir:stato:decreto.legislativo:2008-04-09;81!art37",
        "verified_against_doc_id": "gu-2008-dlgs-81",
        "notes": "Formazione obbligatoria dei lavoratori e loro rappresentanti.",
    }
    model = CitationVerificationResult(**valid_citation)
    assert model.citation_input == "D.Lgs. 81/2008 Art. 37"
    assert model.is_valid is True
    assert model.status == "in_force"

    # Test unrecognized status
    unrecognized_citation = {
        "citation_input": "Regolamento Fantasma 99/9999",
        "is_valid": False,
        "status": "unrecognized",
        "canonical_citation": "Non riconosciuto",
    }
    model_unrec = CitationVerificationResult(**unrecognized_citation)
    assert model_unrec.is_valid is False
    assert model_unrec.status == "unrecognized"
    assert model_unrec.official_reference is None


def test_tdi_service_offering_validation() -> None:
    """Test TDIServiceOffering fields and pre-approved CTA templates."""
    offering_data = {
        "service_id": "tdi-audit-calore",
        "service_name": "Audit e Valutazione Microclima e Rischio Calore",
        "topic_category": "thermal_stress",
        "applicable_sectors": ["construction", "agriculture", "foundry"],
        "value_proposition": "Valutazione strumentale con sonde WBGT e protocolli operativi certificati.",
        "cta_headline": "Proteggi i tuoi lavoratori dal rischio stress termico estivo",
        "cta_body": "Contatta gli esperti HSE di TDI per pianificare la valutazione strumentale del microclima.",
        "landing_page_url": "https://www.tdi.it/servizi/valutazione-rischio-calore",
    }
    offering = TDIServiceOffering(**offering_data)
    assert offering.service_id == "tdi-audit-calore"
    assert offering.topic_category == "thermal_stress"
    assert len(offering.applicable_sectors) == 3


def test_substrate_models_extra_ignore() -> None:
    """Test that all substrate models ignore extraneous fields (extra='ignore')."""
    payload = {
        "doc_id": "eurlex-2024-dir-1234",
        "source": "EUR_LEX",
        "doc_type": "directive",
        "official_reference": "Direttiva (UE) 2024/1234",
        "title": "Direttiva sulle emissioni industriali",
        "publication_date": "2024-04-10",
        "impact_level": "medium",
        "summary": "Nuove soglie di emissione per impianti di combustione.",
        "canonical_url": "https://eur-lex.europa.eu/legal-content/IT/TXT/?uri=CELEX:32024L1234",
        "unexpected_backend_internal_flag": True,
        "legacy_metadata_v1": {"random_key": "random_value"},
    }
    summary = RegulatoryUpdateSummary(**payload)
    assert not hasattr(summary, "unexpected_backend_internal_flag")
    assert not hasattr(summary, "legacy_metadata_v1")


# ============================================================================
# Batch 2: Internal Pipeline Models Tests
# ============================================================================


def test_pipeline_scope_defaults_and_unconstrained() -> None:
    """DM2: the scope carries ``context`` and five fields; ``max_drafts`` defaults to unconstrained."""
    context = AgentContext(today=date(2026, 9, 22))
    scope = PipelineScope(context=context, date_from="2026-06-22", date_to="2026-09-22")
    assert scope.context is context
    assert scope.max_drafts is None  # Mandatory default per Rule 4
    assert scope.sources == []
    assert scope.sector_constraints == []
    assert list(PipelineScope.model_fields) == [
        "context", "date_from", "date_to", "sources", "sector_constraints", "max_drafts",
    ]

    # Valid with constrained ceiling and every one of the three sources
    custom_scope = PipelineScope(
        context=context,
        date_from="2026-08-23",
        date_to="2026-09-22",
        sources=["INAIL", "EUR_LEX", "GAZZETTA_UFFICIALE"],
        sector_constraints=["construction"],
        max_drafts=3,
    )
    assert custom_scope.max_drafts == 3
    assert custom_scope.sources == ["INAIL", "EUR_LEX", "GAZZETTA_UFFICIALE"]

    # Invalid source literal
    with pytest.raises(ValidationError) as exc_info:
        PipelineScope(
            context=context,
            date_from="2026-08-23",
            date_to="2026-09-22",
            sources=["UNKNOWN_SOURCE"],  # type: ignore[list-item]
        )
    assert "sources" in str(exc_info.value)


def test_pipeline_scope_requires_context_and_absolute_date_bounds() -> None:
    """The scope carries absolute ISO bounds and the context code fills in; none of the three is optional."""
    scope = PipelineScope(context=AgentContext(today=TODAY), date_from="2026-06-22", date_to="2026-09-22")
    assert scope.date_from == "2026-06-22"
    assert scope.date_to == "2026-09-22"

    with pytest.raises(ValidationError) as exc_info:
        PipelineScope()  # type: ignore[call-arg]
    message = str(exc_info.value)
    assert "context" in message
    assert "date_from" in message
    assert "date_to" in message


def test_pipeline_scope_ignores_the_dropped_window_fields() -> None:
    """DM2: the two window fields Approach 1's parser filled are gone, and ``extra="ignore"`` drops them."""
    scope = PipelineScope.model_validate(
        {
            "context": {"today": "2026-09-22"},
            "date_from": "2026-06-22",
            "date_to": "2026-09-22",
            "time_window": "past_3_months",
            "time_window_specified": True,
        }
    )

    assert scope.context.today == date(2026, 9, 22)
    assert "time_window" not in PipelineScope.model_fields
    assert "time_window_specified" not in PipelineScope.model_fields
    assert not hasattr(scope, "time_window")
    assert not hasattr(scope, "time_window_specified")
    assert "time_window" not in scope.model_dump_json()


def test_article_draft_fields() -> None:
    """Test ArticleDraft requires all 5 mandatory components from Writer agent."""
    valid_draft = {
        "source_doc_id": "inail-2024-circ-calore",
        "headline": "Nuove Linee Guida INAIL sul Rischio Calore nei Cantieri",
        "executive_summary": "Sintesi per i responsabili RSPP sulle misure contro lo stress termico.",
        "article_body": "## Dettagli tecnici\nL'INAIL ha pubblicato le indicazioni operative...",
        "tdi_cta": "Contatta TDI per la redazione del Piano di Emergenza Calore.",
    }
    draft = ArticleDraft(**valid_draft)
    assert draft.headline.startswith("Nuove Linee")
    assert draft.tdi_cta.startswith("Contatta TDI")

    # Missing field raises ValidationError
    incomplete = valid_draft.copy()
    del incomplete["tdi_cta"]
    with pytest.raises(ValidationError) as exc_info:
        ArticleDraft(**incomplete)
    assert "tdi_cta" in str(exc_info.value)


def test_qa_report_tri_state_and_defaults() -> None:
    """Test QAReport status literals (PASS/WARNING/ERROR) and default collections."""
    report_pass = QAReport(status="PASS", verified_citations=["D.Lgs. 81/2008 Art. 37"])
    assert report_pass.status == "PASS"
    assert report_pass.issues == []
    assert report_pass.review_notes == ""

    report_error = QAReport(
        status="ERROR",
        issues=["Citazione non valida o abrogata: Art. 999"],
        review_notes="Correggere riferimento normativo.",
    )
    assert report_error.status == "ERROR"
    assert len(report_error.issues) == 1

    report_warning = QAReport(status="WARNING", review_notes="Raccomandazione prudenziale")
    assert report_warning.status == "WARNING"

    with pytest.raises(ValidationError) as exc_info:
        QAReport(status="FAILED")  # type: ignore[arg-type]
    assert "status" in str(exc_info.value)


# ============================================================================
# Batch 3: Composite Metadata, Exit Codes & Serialization Roundtrip Tests
# ============================================================================


def test_draft_metadata_composition() -> None:
    """Test DraftMetadata schema composition, defaults, and telemetry fields."""
    qa_report = QAReport(
        status="PASS",
        verified_citations=["D.Lgs. 81/2008 Art. 37"],
        issues=[],
        review_notes="Nessuna non conformità rilevata.",
    )
    metadata = DraftMetadata(
        draft_id="draft_20260910_001",
        source_name="INAIL",
        publication_date="2024-07-01",
        source_document_title="Circolare INAIL n. 28/2024",
        qa_report=qa_report,
        attempts=1,
        latency_seconds=14.2,
        estimated_cost=0.045,
        total_tokens=1820,
    )
    assert metadata.draft_id == "draft_20260910_001"
    assert metadata.approach_name == "Approach 2 (Research Analyst)"  # Q9 = C, DM15
    assert metadata.unresolved_errors == []
    assert metadata.qa_report.status == "PASS"
    assert metadata.attempts == 1
    assert metadata.latency_seconds == 14.2
    assert metadata.estimated_cost == 0.045
    assert metadata.total_tokens == 1820


def test_exit_codes() -> None:
    """``ExitCode`` values, SPECIFICATIONS.md §6.10: Approach 1's 0 to 5 unchanged, plus ``SUPERVISOR_ERROR``."""
    assert ExitCode.SUCCESS == 0
    assert ExitCode.NO_UPDATES == 1
    assert ExitCode.MCP_ERROR == 2
    assert ExitCode.PARSER_ERROR == 3
    assert ExitCode.PERSISTENCE_ERROR == 4
    # QA-A12: the sixth code was unasserted. It exists because every other code
    # describes a run that started, and an unconfigured checkout must not exit on
    # Python's default status of 1 -- which is NO_UPDATES, a *clean* result.
    assert ExitCode.CONFIG_ERROR == 5
    # P6: the most severe code, so the numeric maximum keeps it.
    assert ExitCode.SUPERVISOR_ERROR == 6
    assert [code.value for code in ExitCode] == [0, 1, 2, 3, 4, 5, 6]


def test_the_old_exit_code_name_no_longer_exists() -> None:
    """§6 "Removed": the enum was renamed, with no alias left behind."""
    assert not hasattr(schemas, "PipelineExitCode")
    assert "PipelineExitCode" not in schemas.__all__


def test_schema_json_serialization_roundtrip() -> None:
    """Test the model_dump_json and model_validate_json roundtrip of DraftMetadata."""
    qa_report = QAReport(
        status="WARNING",
        verified_citations=["Direttiva 2024/1234"],
        issues=["Circolare ministeriale non ancora pubblicata in GU"],
        review_notes="Pubblicare con nota di cautela.",
    )
    metadata = DraftMetadata(
        draft_id="draft_20260910_002",
        source_name="EUR_LEX",
        publication_date="2024-04-10",
        source_document_title="Direttiva sulle emissioni",
        qa_report=qa_report,
        attempts=2,
        latency_seconds=28.5,
        estimated_cost=0.082,
        total_tokens=3500,
        unresolved_errors=[],
    )
    json_str = metadata.model_dump_json()
    reconstructed = DraftMetadata.model_validate_json(json_str)
    assert reconstructed.draft_id == metadata.draft_id
    assert reconstructed.qa_report.status == "WARNING"
    assert reconstructed.qa_report.verified_citations == ["Direttiva 2024/1234"]
    assert reconstructed.latency_seconds == 28.5




# ============================================================================
# Phase 6: Orchestrator contracts (PLAN Batch 2)
# ============================================================================


def test_agent_telemetry_captures_cache_read_tokens() -> None:
    """Cache-aware costing needs the cached half of ``inputTokens`` (PLAN §2.6)."""
    assert AgentTelemetry(model_id="gpt-5-mini").cache_read_input_tokens == 0

    telemetry = AgentTelemetry(model_id="gpt-5.4", input_tokens=1000, cache_read_input_tokens=640)

    assert telemetry.cache_read_input_tokens == 640
    assert telemetry.input_tokens == 1000


def test_stage_telemetry_labels_worker_stage() -> None:
    """``StageTelemetry`` attributes one telemetry record to one named worker."""
    telemetry = AgentTelemetry(model_id="gpt-5.4", input_tokens=10, output_tokens=5, total_tokens=15)
    stage = StageTelemetry(stage="writer", doc_id=DEFAULT_DOC_ID, attempt=2, telemetry=telemetry)

    round_tripped = StageTelemetry.model_validate_json(stage.model_dump_json())
    assert round_tripped.stage == "writer"
    assert round_tripped.doc_id == DEFAULT_DOC_ID
    assert round_tripped.attempt == 2
    assert round_tripped.telemetry.total_tokens == 15

    with pytest.raises(ValidationError):
        StageTelemetry(stage="orchestrator", telemetry=telemetry)


def test_stage_telemetry_labels_the_four_approach_2_stages_only() -> None:
    """§6.6: the Supervisor has a stage of its own; Approach 1's parser stage is gone."""
    telemetry = AgentTelemetry(model_id="gpt-5.4")
    for name in ("supervisor", "scout", "writer", "qa_legal"):
        assert StageTelemetry(stage=name, telemetry=telemetry).stage == name  # type: ignore[arg-type]

    with pytest.raises(ValidationError) as exc_info:
        StageTelemetry(stage="scope_parser", telemetry=telemetry)  # type: ignore[arg-type]
    assert "stage" in str(exc_info.value)


def test_stage_telemetry_document_and_attempt_default_to_none() -> None:
    """The Supervisor and the Scout belong to no document and no attempt, and say so as ``None``."""
    stage = StageTelemetry(stage="scout", telemetry=AgentTelemetry(model_id="gpt-5-mini"))

    assert stage.doc_id is None
    assert stage.attempt is None
    assert list(StageTelemetry.model_fields) == ["stage", "doc_id", "attempt", "telemetry"]


def test_draft_metadata_fields_are_unchanged_apart_from_the_approach_default() -> None:
    """DM15: only ``approach_name``'s default changes, so the template and its placeholders stay as they are."""
    assert list(DraftMetadata.model_fields) == [
        "draft_id", "source_name", "publication_date", "source_document_title", "approach_name", "qa_report",
        "attempts", "latency_seconds", "estimated_cost", "total_tokens", "unresolved_errors", "stage_telemetry",
        "model_rates_used",
    ]
    assert DraftMetadata.model_fields["approach_name"].default == "Approach 2 (Research Analyst)"


def test_draft_metadata_carries_stage_telemetry_and_rates() -> None:
    """SPECIFICATIONS:245 — the draft must be able to surface per-stage tool usage."""
    base = dict(
        draft_id="draft_20260917_001",
        source_name="INAIL",
        publication_date="2026-09-17",
        source_document_title="Title",
        qa_report=QAReport(status="PASS"),
        attempts=1,
        latency_seconds=1.0,
        estimated_cost=0.01,
        total_tokens=100,
    )

    empty = DraftMetadata(**base)
    assert empty.stage_telemetry == []
    assert empty.model_rates_used == {}

    stage = StageTelemetry(stage="qa_legal", telemetry=AgentTelemetry(model_id="gpt-5.4"))
    rate = ModelRate(input_usd_per_mtok=1.25, cached_input_usd_per_mtok=0.125, output_usd_per_mtok=10.0)
    populated = DraftMetadata(**base, stage_telemetry=[stage], model_rates_used={"gpt-5.4": rate})

    assert populated.stage_telemetry[0].stage == "qa_legal"
    assert populated.model_rates_used["gpt-5.4"].output_usd_per_mtok == 10.0


def test_model_rate_holds_three_per_mtok_prices() -> None:
    """Three rates, not four: the OpenAI provider populates only the read side (PLAN §2.6)."""
    rate = ModelRate(input_usd_per_mtok=0.25, cached_input_usd_per_mtok=0.025, output_usd_per_mtok=2.0)

    assert rate.input_usd_per_mtok == 0.25
    assert rate.cached_input_usd_per_mtok == 0.025
    assert rate.output_usd_per_mtok == 2.0
    assert ModelRate(input_usd_per_mtok=1.0, output_usd_per_mtok=2.0).cached_input_usd_per_mtok == 0.0

    with pytest.raises(ValidationError):
        ModelRate(input_usd_per_mtok=-0.1, output_usd_per_mtok=2.0)
    with pytest.raises(ValidationError):
        ModelRate(input_usd_per_mtok=1.0, cached_input_usd_per_mtok=-0.5, output_usd_per_mtok=2.0)


def test_pipeline_config_and_draft_result_are_typed_contracts() -> None:
    """Rule 2: the run configuration and a saved draft's result cross module boundaries as models, not dicts."""
    config = PipelineConfig(
        drafts_dir=Path("drafts"),
        template_path=Path(".agents/templates/draft.md"),
        log_dir=Path("logs"),
    )
    assert config.max_drafts is None
    assert config.log_level == "INFO"
    assert isinstance(config.drafts_dir, Path)

    result = DraftResult(
        doc_id="inail-2024-circ-calore",
        draft_id="draft_20260917_001",
        path=Path("drafts/draft_20260917_001.md"),
        qa_status="WARNING",
    )
    assert result.qa_status == "WARNING"
    assert isinstance(result.path, Path)


def test_draft_result_is_the_slim_save_result() -> None:
    """§6.4: ``doc_id``, ``draft_id``, ``path`` and ``qa_status``, in that order; the attempt count is not repeated."""
    assert list(DraftResult.model_fields) == ["doc_id", "draft_id", "path", "qa_status"]

    result = DraftResult.model_validate(
        {
            "doc_id": DEFAULT_DOC_ID,
            "draft_id": "draft_20260929_001",
            "path": "drafts/draft_20260929_001.md",
            "qa_status": "PASS",
            "writer_invocations": 2,
        }
    )
    assert not hasattr(result, "writer_invocations")
    assert list(json.loads(result.model_dump_json())) == ["doc_id", "draft_id", "path", "qa_status"]

    with pytest.raises(ValidationError) as exc_info:
        DraftResult(doc_id=DEFAULT_DOC_ID, draft_id="d", path=Path("d.md"), qa_status="FAILED")  # type: ignore[arg-type]
    assert "qa_status" in str(exc_info.value)


def test_failure_record_preserves_full_error_detail() -> None:
    """PLAN §2.10: nothing about a remote failure is truncated or dropped."""
    long_message = "Rate limit reached for gpt-5.4 in organization org-abc. " * 40

    minimal = FailureRecord(stage="writer", error_type="ValueError", message="boom")
    assert minimal.doc_id is None
    assert minimal.attempt is None
    assert minimal.remote is None
    assert minimal.traceback is None

    remote = RemoteErrorDetail(
        status_code=429,
        provider_code="rate_limit_exceeded",
        provider_type="rate_limit_error",
        request_id="req_abc123",
        body='{"error": {"message": "Rate limit reached"}}',
        cause_chain=["openai.RateLimitError: Rate limit reached"],
    )
    record = FailureRecord(
        doc_id="inail-2024-circ-calore",
        stage="qa_legal",
        error_type="openai.RateLimitError",
        message=long_message,
        remote=remote,
        traceback="Traceback (most recent call last):\n  ...",
    )

    assert record.message == long_message
    assert len(record.message) == len(long_message)
    assert record.remote is not None
    assert record.remote.status_code == 429
    assert record.remote.request_id == "req_abc123"
    assert record.remote.cause_chain == ["openai.RateLimitError: Rate limit reached"]
    assert record.traceback is not None and record.traceback.startswith("Traceback")

    with pytest.raises(ValidationError):
        FailureRecord(stage="not_a_stage", error_type="ValueError", message="boom")


def test_failure_stages_are_the_nine_of_the_specification_in_order() -> None:
    """§6.7: ``supervisor`` added and Approach 1's parser stage removed."""
    assert get_args(FailureStage) == (
        "configuration",
        "mcp_session",
        "supervisor",
        "scout",
        "fetch_document",
        "writer",
        "qa_legal",
        "render",
        "persist",
    )
    with pytest.raises(ValidationError) as exc_info:
        FailureRecord(stage="scope_parser", error_type="ValueError", message="boom")  # type: ignore[arg-type]
    assert "stage" in str(exc_info.value)


def test_failure_record_ties_a_failed_writer_call_to_its_attempt() -> None:
    """DM13: ``attempt`` sits after ``doc_id``, so a failed call points at its ``AttemptRecord``."""
    record = FailureRecord(
        doc_id=DEFAULT_DOC_ID, attempt=2, stage="fetch_document", error_type="FetchNotCalled", message="no fetch"
    )

    assert record.attempt == 2
    assert list(FailureRecord.model_fields)[:3] == ["doc_id", "attempt", "stage"]
    assert FailureRecord(stage="supervisor", error_type="openai.APIError", message="boom").stage == "supervisor"

def test_article_draft_carries_its_source_doc_id() -> None:
    """The draft names the substrate document it was written from.

    Without this field ``ArticleDraft`` is four strings and carries no provenance
    at all, which is what made ``QA_LEGAL_SYSTEM_PROMPT``'s instruction to "call
    ``get_document_by_id`` for the source instrument" unfulfillable: the auditor
    was handed the draft and nothing to fetch with. It is a plain ``str`` rather
    than a nested ``RegulatoryUpdateSummary`` deliberately — the Writer echoes it,
    and echoing a whole nested record invites corruption.
    """
    draft = ArticleDraft(
        headline="Circolare INAIL 28/2024",
        executive_summary="Sintesi",
        article_body="Corpo",
        tdi_cta="CTA",
        source_doc_id="inail-2024-circ-calore",
    )
    assert draft.source_doc_id == "inail-2024-circ-calore"

    # Required: a draft with no provenance must not validate.
    with pytest.raises(ValidationError) as exc_info:
        ArticleDraft(
            headline="H",
            executive_summary="S",
            article_body="B",
            tdi_cta="C",
        )
    assert "source_doc_id" in str(exc_info.value)

    # The empty string is valid and meaningful: it is how the Writer reports that
    # its ``get_document_by_id`` call failed rather than inventing an article.
    failed = ArticleDraft(
        headline="H",
        executive_summary="S",
        article_body="B",
        tdi_cta="C",
        source_doc_id="",
    )
    assert failed.source_doc_id == ""


# ============================================================================
# Approach 2 contracts (SPECIFICATIONS.md §6; IMPLEMENTATION_PLAN.md Iteration 4)
# ============================================================================

TODAY = date(2026, 9, 29)


def test_agent_context_holds_today_only() -> None:
    """DM5: the run facts a sub-agent may know are the date, and never a budget or the attempt cap."""
    context = AgentContext(today=TODAY)

    assert context.today == TODAY
    assert list(AgentContext.model_fields) == ["today"]
    assert AgentContext(today="2026-09-29").today == TODAY  # type: ignore[arg-type]
    # extra="ignore": a budget handed in by mistake is dropped, not carried to the sub-agent.
    assert not hasattr(AgentContext(today=TODAY, max_attempts_per_doc=3), "max_attempts_per_doc")  # type: ignore[call-arg]
    with pytest.raises(ValidationError) as exc_info:
        AgentContext()  # type: ignore[call-arg]
    assert "today" in str(exc_info.value)


def _candidate(doc_id: str = DEFAULT_DOC_ID) -> ScoutCandidate:
    """Build the scripted Scout candidate for ``doc_id``."""
    return ScoutCandidate.model_validate(scout_candidate_args(doc_id, 0.9, f"Obblighi immediati ({doc_id})."))


def _draft(doc_id: str = DEFAULT_DOC_ID) -> ArticleDraft:
    """Build the scripted Writer draft whose provenance is ``doc_id``."""
    return ArticleDraft.model_validate({**DRAFT_ARGS, "source_doc_id": doc_id})


def _qa(status: str = "WARNING") -> QAReport:
    """Build a scripted QA-Legal report with ``status`` and one issue."""
    return QAReport.model_validate(qa_args(status=status, issues=["Art. 28 citato senza comma."], notes="Nota."))


def _attempt(attempt: int = 1, *, candidate: ScoutCandidate | None = None) -> AttemptRecord:
    """Build an undrafted attempt on ``candidate``, or on a fresh scripted candidate."""
    return AttemptRecord(
        context=AgentContext(today=TODAY),
        candidate=candidate if candidate is not None else _candidate(),
        attempt=attempt,
    )


def test_attempt_record_holds_its_candidate_by_identity_and_starts_empty() -> None:
    """DM6: the record keeps the very ``ScoutCandidate`` it was given, so no copy of it is ever made."""
    candidate = _candidate()
    record = _attempt(1, candidate=candidate)

    assert record.candidate is candidate
    assert record.attempt == 1
    assert record.context.today == TODAY
    assert record.draft is None
    assert record.qa_report is None


def test_attempt_record_doc_id_is_derived_from_its_candidate_and_in_every_dump() -> None:
    """``doc_id`` is ``candidate.update.doc_id``, computed rather than stored, and present in every dump."""
    record = _attempt(2, candidate=_candidate("gu-2026-dm-cantieri"))

    assert record.doc_id == "gu-2026-dm-cantieri"
    assert "doc_id" not in AttemptRecord.model_fields
    assert record.model_dump()["doc_id"] == "gu-2026-dm-cantieri"
    assert json.loads(record.model_dump_json())["doc_id"] == "gu-2026-dm-cantieri"


def test_attempt_record_sets_its_draft_once() -> None:
    """D-C: each slot is set once; a second draft for the same attempt is refused, not overwritten."""
    record = _attempt()
    first = _draft()

    record.set_draft(first)
    assert record.draft is first

    with pytest.raises(ValueError, match="draft"):
        record.set_draft(_draft())
    assert record.draft is first


def test_attempt_record_sets_its_qa_report_once() -> None:
    """D-C rule 8: a draft is audited once; a second report for it is refused, not overwritten."""
    record = _attempt()
    record.set_draft(_draft())
    report = _qa("ERROR")

    record.set_qa_report(report)
    assert record.qa_report is report

    with pytest.raises(ValueError, match="QA report"):
        record.set_qa_report(_qa("PASS"))
    assert record.qa_report is report


def _audited_attempt(attempt: int = 1, status: str = "WARNING") -> AttemptRecord:
    """Build an attempt holding both a draft and a QA report, so no view test can pass vacuously."""
    record = _attempt(attempt)
    record.set_draft(_draft())
    record.set_qa_report(_qa(status))
    return record


def test_writer_view_is_the_whole_record_as_json() -> None:
    """§7.2: the Writer's user turn carries the whole record, candidate, draft and report included."""
    record = _audited_attempt()

    view = json.loads(record.writer_view())

    assert set(view) == {"doc_id", "context", "candidate", "attempt", "draft", "qa_report"}
    assert view == json.loads(record.model_dump_json())
    assert view["candidate"]["rationale"] == record.candidate.rationale
    assert view["context"] == {"today": "2026-09-29"}


def test_qa_view_omits_the_candidate_and_carries_the_draft() -> None:
    """§7.2: QA-Legal sees ``{doc_id, context, attempt, draft}``: a draft to audit, as in Approach 1."""
    record = _audited_attempt(2)

    view = json.loads(record.qa_view())

    assert set(view) == {"doc_id", "context", "attempt", "draft"}
    assert view["doc_id"] == DEFAULT_DOC_ID
    assert view["attempt"] == 2
    assert view["context"] == {"today": "2026-09-29"}
    assert record.draft is not None
    assert view["draft"] == json.loads(record.draft.model_dump_json())


def test_supervisor_view_omits_the_draft_and_candidate_and_carries_the_report() -> None:
    """§7.2, D-F: the Supervisor's view is ``{doc_id, context, attempt, qa_report}``, JSON-ready."""
    record = _audited_attempt(3, "ERROR")

    view = record.supervisor_view()

    assert set(view) == {"doc_id", "context", "attempt", "qa_report"}
    assert view["doc_id"] == DEFAULT_DOC_ID
    assert view["attempt"] == 3
    assert view["context"] == {"today": "2026-09-29"}
    assert view["qa_report"]["status"] == "ERROR"
    assert json.loads(json.dumps(view)) == view  # plain JSON types only


def test_supervisor_view_of_an_undrafted_attempt_still_has_every_key() -> None:
    """A failed Writer call still reaches the Supervisor as an attempt, with an empty report slot."""
    view = _attempt().supervisor_view()

    assert view == {"doc_id": DEFAULT_DOC_ID, "context": {"today": "2026-09-29"}, "attempt": 1, "qa_report": None}


def test_max_attempts_per_doc_is_three() -> None:
    """D-C rule 4: an initial draft plus up to two revisions (Approach 1 D10)."""
    assert MAX_ATTEMPTS_PER_DOC == 3


def test_run_context_is_the_budget_the_supervisor_sees() -> None:
    """DM10: today, the attempt cap, the draft ceiling and the drafts saved so far."""
    context = RunContext(today=TODAY, max_drafts=2, drafts_saved=1)

    assert context.today == TODAY
    assert context.max_attempts_per_doc == MAX_ATTEMPTS_PER_DOC
    assert context.max_drafts == 2
    assert context.drafts_saved == 1
    assert list(RunContext.model_fields) == ["today", "max_attempts_per_doc", "max_drafts", "drafts_saved"]
    assert json.loads(context.model_dump_json()) == {
        "today": "2026-09-29", "max_attempts_per_doc": 3, "max_drafts": 2, "drafts_saved": 1,
    }


def test_run_context_states_an_unconstrained_ceiling_explicitly() -> None:
    """§6.4 gives ``max_drafts`` and ``drafts_saved`` no default: code states both, ``None`` meaning no ceiling."""
    assert RunContext(today=TODAY, max_drafts=None, drafts_saved=0).max_drafts is None

    with pytest.raises(ValidationError) as exc_info:
        RunContext(today=TODAY)  # type: ignore[call-arg]
    message = str(exc_info.value)
    assert "max_drafts" in message
    assert "drafts_saved" in message


def test_guardrail_names_are_the_twelve_of_the_specification_in_order() -> None:
    """§6.7 / DM13: exactly 12 names, in the order Iteration 5's table-driven tests enumerate."""
    assert get_args(GuardrailName) == (
        "invalid_scope",
        "scout_already_run",
        "not_a_candidate",
        "attempt_limit",
        "initial_draft_exists",
        "not_audited",
        "revise_after_pass",
        "no_draft",
        "already_audited",
        "already_saved",
        "error_with_attempts_remaining",
        "draft_ceiling",
    )


def test_guardrail_violation_names_the_rule_the_tool_and_the_document() -> None:
    """A violation holds ``guardrail``, ``tool_name``, ``doc_id`` and a message the Supervisor can act on."""
    violation = GuardrailViolation(
        guardrail="attempt_limit",
        tool_name="writer_tool",
        doc_id=DEFAULT_DOC_ID,
        message="attempt_limit: 3 of 3 attempts used.",
    )

    assert list(GuardrailViolation.model_fields) == ["guardrail", "tool_name", "doc_id", "message"]
    assert json.loads(violation.model_dump_json()) == {
        "guardrail": "attempt_limit",
        "tool_name": "writer_tool",
        "doc_id": DEFAULT_DOC_ID,
        "message": "attempt_limit: 3 of 3 attempts used.",
    }
    # A run-level guardrail names no document, and says so explicitly.
    run_level = GuardrailViolation(guardrail="scout_already_run", tool_name="scout_tool", doc_id=None, message="m")
    assert run_level.doc_id is None

    with pytest.raises(ValidationError) as exc_info:
        GuardrailViolation(guardrail="budget_exceeded", tool_name="t", doc_id=None, message="m")  # type: ignore[arg-type]
    assert "guardrail" in str(exc_info.value)
    with pytest.raises(ValidationError) as exc_info:
        GuardrailViolation(guardrail="no_draft", tool_name="qa_tool", message="m")  # type: ignore[call-arg]
    assert "doc_id" in str(exc_info.value)


#: D-F: keys that would carry article text, or the candidate the Supervisor already has, into its context.
FORBIDDEN_SUPERVISOR_KEYS: frozenset[str] = frozenset(
    {"draft", "candidate", "headline", "article_body", "executive_summary"}
)


def _all_keys(value: Any) -> set[str]:
    """Return every object key in a decoded JSON value, at any depth."""
    if isinstance(value, dict):
        return set(value) | {key for item in value.values() for key in _all_keys(item)}
    if isinstance(value, list):
        return {key for item in value for key in _all_keys(item)}
    return set()


def _run(drafts_saved: int = 0) -> RunContext:
    """Build a run snapshot with a draft ceiling of 2."""
    return RunContext(today=TODAY, max_drafts=2, drafts_saved=drafts_saved)


def test_tool_result_is_generic_over_the_three_supervisor_results() -> None:
    """§6.4: ``ToolResult[T]`` wraps a ``ScoutReport``, an ``AttemptRecord`` or a ``DraftResult``."""
    report = ScoutReport(candidates=[_candidate()])
    record = _audited_attempt()
    saved = DraftResult(doc_id=DEFAULT_DOC_ID, draft_id="draft_20260929_001", path=Path("d.md"), qa_status="PASS")

    assert ToolResult[ScoutReport](result=report, run=_run()).result is report
    # The wrapper holds the stored attempt itself, so nothing about it is copied or re-validated.
    assert ToolResult[AttemptRecord](result=record, run=_run()).result is record
    assert ToolResult[DraftResult](result=saved, run=_run(1)).result is saved
    assert ToolResult[DraftResult](result=None, run=_run()).error is None
    assert list(ToolResult.model_fields) == ["result", "run", "error"]

    with pytest.raises(ValidationError) as exc_info:
        ToolResult[ScoutReport](result=record, run=_run())
    assert "result" in str(exc_info.value)
    with pytest.raises(ValidationError) as exc_info:
        ToolResult[ScoutReport](run=_run())  # type: ignore[call-arg]
    assert "result" in str(exc_info.value)


def test_tool_result_error_is_a_violation_a_summary_or_nothing() -> None:
    """``error`` holds a ``GuardrailViolation``, a one-line failure summary, or ``None``."""
    violation = GuardrailViolation(guardrail="no_draft", tool_name="qa_tool", doc_id=DEFAULT_DOC_ID, message="m")

    refused = ToolResult[AttemptRecord](result=None, run=_run(), error=violation)
    failed = ToolResult[AttemptRecord](result=_attempt(), run=_run(), error="Writer call failed: RateLimitError")
    from_dict = ToolResult[AttemptRecord].model_validate(
        {"result": None, "run": _run().model_dump(), "error": violation.model_dump()}
    )

    assert refused.error is violation
    assert failed.error == "Writer call failed: RateLimitError"
    assert isinstance(from_dict.error, GuardrailViolation)
    assert from_dict.error.guardrail == "no_draft"


def test_for_supervisor_applies_the_supervisor_view_to_an_attempt() -> None:
    """§7.2, D-F: an attempt reaches the Supervisor as ``supervisor_view()``, with ``run`` and ``error`` alongside."""
    record = _audited_attempt(2, "ERROR")

    sent = json.loads(ToolResult[AttemptRecord](result=record, run=_run(1)).for_supervisor())

    assert list(sent) == ["result", "run", "error"]
    assert sent["result"] == record.supervisor_view()
    assert sent["run"] == {"today": "2026-09-29", "max_attempts_per_doc": 3, "max_drafts": 2, "drafts_saved": 1}
    assert sent["error"] is None


def test_for_supervisor_never_carries_article_text_or_the_candidate() -> None:
    """D-F, Gate 6: no forbidden key at any depth, and none of the draft's text, even under a failure summary."""
    record = _audited_attempt(1, "WARNING")
    violation = GuardrailViolation(
        guardrail="already_audited", tool_name="qa_tool", doc_id=DEFAULT_DOC_ID, message="Attempt 1 is audited."
    )

    for result in (
        ToolResult[AttemptRecord](result=record, run=_run()),
        ToolResult[AttemptRecord](result=record, run=_run(), error="QA-Legal call failed: timeout"),
        ToolResult[AttemptRecord](result=None, run=_run(), error=violation),
    ):
        text = result.for_supervisor()
        assert _all_keys(json.loads(text)).isdisjoint(FORBIDDEN_SUPERVISOR_KEYS)
        for article_text in (DRAFT_ARGS["headline"], DRAFT_ARGS["executive_summary"], DRAFT_ARGS["article_body"]):
            assert article_text not in text
        assert record.candidate.rationale not in text

    # The plain dump does leak both, which is why for_supervisor() is the only Supervisor serialisation.
    plain_dump = ToolResult[AttemptRecord](result=record, run=_run()).model_dump_json()
    assert {"draft", "candidate"} <= _all_keys(json.loads(plain_dump))


def test_for_supervisor_serialises_a_scout_report_and_a_draft_result_whole() -> None:
    """§7.2: the ``ScoutReport`` and the ``DraftResult`` are sent whole, and an error keeps its shape."""
    report = ScoutReport(candidates=[_candidate(), _candidate("gu-2026-dm-cantieri")])
    saved = DraftResult(
        doc_id=DEFAULT_DOC_ID,
        draft_id="draft_20260929_001",
        path=Path("drafts/draft_20260929_001.md"),
        qa_status="PASS",
    )
    violation = GuardrailViolation(guardrail="draft_ceiling", tool_name="save_draft", doc_id="x", message="2 of 2.")

    scout_sent = json.loads(ToolResult[ScoutReport](result=report, run=_run()).for_supervisor())
    save_sent = json.loads(ToolResult[DraftResult](result=saved, run=_run(1)).for_supervisor())
    refused_sent = json.loads(ToolResult[DraftResult](result=None, run=_run(2), error=violation).for_supervisor())

    assert scout_sent["result"] == report.model_dump(mode="json")
    assert _all_keys(scout_sent).isdisjoint(FORBIDDEN_SUPERVISOR_KEYS)
    assert save_sent["result"] == saved.model_dump(mode="json")
    assert save_sent["error"] is None
    assert refused_sent == {
        "result": None,
        "run": _run(2).model_dump(mode="json"),
        "error": violation.model_dump(mode="json"),
    }
    failed_scout = ToolResult[ScoutReport](result=None, run=_run(), error="Scout failed.")
    assert json.loads(failed_scout.for_supervisor())["error"] == "Scout failed."


def _saved(doc_id: str = DEFAULT_DOC_ID, status: str = "PASS") -> DraftResult:
    """Build the result of saving ``doc_id``."""
    return DraftResult(doc_id=doc_id, draft_id="draft_20260929_001", path=Path("d.md"), qa_status=status)  # type: ignore[arg-type]


def test_document_record_starts_not_drafted_with_every_attempt_remaining() -> None:
    """§6.5: a new document has no attempts, all three remaining, no latest draft and state ``not_drafted``."""
    candidate = _candidate()
    document = DocumentRecord(candidate=candidate)

    assert document.candidate is candidate
    assert document.attempts == []
    assert document.saved is None
    assert document.attempts_used == 0
    assert document.attempts_remaining == MAX_ATTEMPTS_PER_DOC
    assert document.latest_drafted is None
    assert document.state == "not_drafted"


def test_document_record_derives_its_state_from_its_attempts() -> None:
    """``drafted`` once a draft exists, ``audited`` once it has a report, ``saved`` once ``saved`` is set."""
    first = _attempt(1)
    document = DocumentRecord(candidate=first.candidate, attempts=[first])
    assert document.attempts[0] is first
    assert (document.attempts_used, document.attempts_remaining) == (1, 2)
    assert document.latest_drafted is None
    assert document.state == "not_drafted"  # the only call so far failed

    first.set_draft(_draft())
    assert document.latest_drafted is first
    assert document.state == "drafted"

    first.set_qa_report(_qa("WARNING"))
    assert document.state == "audited"

    document.saved = _saved(status="WARNING")
    assert document.state == "saved"


def test_document_record_state_is_saved_whatever_its_attempts() -> None:
    """§6.5: ``saved`` is read first, so a saved document reads ``saved`` with no attempts or a failed latest one."""
    assert DocumentRecord(candidate=_candidate(), saved=_saved()).state == "saved"

    audited = _audited_attempt(1, "WARNING")
    failed = _attempt(2, candidate=audited.candidate)
    document = DocumentRecord(candidate=audited.candidate, attempts=[audited, failed], saved=_saved(status="WARNING"))
    assert document.state == "saved"


def test_document_record_latest_drafted_skips_a_failed_latest_attempt() -> None:
    """D-C rule 8: when the newest call failed, the latest draft is still the earlier, audited one."""
    audited = _audited_attempt(1, "ERROR")
    failed = _attempt(2, candidate=audited.candidate)
    document = DocumentRecord(candidate=audited.candidate, attempts=[audited, failed])

    assert document.latest_drafted is audited
    assert document.state == "audited"
    assert (document.attempts_used, document.attempts_remaining) == (2, 1)

    revised = _attempt(3, candidate=audited.candidate)
    revised.set_draft(_draft())
    document.attempts.append(revised)
    assert document.latest_drafted is revised
    assert document.state == "drafted"
    assert document.attempts_remaining == 0


def test_document_record_derived_fields_are_not_stored() -> None:
    """The four derived fields are properties: not fields, and absent from every dump."""
    document = DocumentRecord(candidate=_candidate(), attempts=[_audited_attempt()])

    derived = {"attempts_used", "attempts_remaining", "latest_drafted", "state"}
    assert derived.isdisjoint(DocumentRecord.model_fields)
    assert derived.isdisjoint(document.model_dump())
    assert list(DocumentRecord.model_fields) == ["candidate", "attempts", "saved"]


def _run_state(tmp_path: Path, *doc_ids: str) -> RunState:
    """Build a fresh run state with a draft ceiling of 2 and one not-drafted document per ``doc_id``."""
    return RunState(
        run_id="run-0001",
        config=pipeline_config(tmp_path, max_drafts=2),
        context=RunContext(today=TODAY, max_drafts=2, drafts_saved=0),
        documents={doc_id: DocumentRecord(candidate=_candidate(doc_id)) for doc_id in doc_ids},
    )


def test_run_state_holds_the_fields_of_the_specification(tmp_path: Path) -> None:
    """§6.5: configuration, context and documents are given; everything else starts empty."""
    state = _run_state(tmp_path, DEFAULT_DOC_ID)

    assert list(RunState.model_fields) == [
        "run_id", "config", "context", "scope", "documents", "ledger", "failures", "violations",
        "fatal_error", "exit_code", "supervisor_summary",
    ]
    assert state.run_id == "run-0001"
    assert state.config.max_drafts == 2
    assert list(state.documents) == [DEFAULT_DOC_ID]
    assert state.scope is None
    assert (state.ledger, state.failures, state.violations) == ([], [], [])
    assert (state.fatal_error, state.exit_code, state.supervisor_summary) == (None, None, None)

    state.exit_code = ExitCode.SUPERVISOR_ERROR
    assert state.exit_code == 6

    validated = RunState.model_validate({
        "run_id": "r",
        "config": pipeline_config(tmp_path),
        "context": _run(),
        "documents": {DEFAULT_DOC_ID: {"candidate": scout_candidate_args(DEFAULT_DOC_ID, 0.9, "r")}},
    })
    assert isinstance(validated.documents[DEFAULT_DOC_ID], DocumentRecord)


def test_run_state_holds_the_fatal_exception_itself(tmp_path: Path) -> None:
    """D-D: ``arbitrary_types_allowed`` lets the fatal slot hold the exception object, not a rendering of it."""
    assert RunState.model_config.get("arbitrary_types_allowed") is True
    assert RunState.model_config.get("extra") == "ignore"
    error = ConnectionError("MCP transport closed")

    state = _run_state(tmp_path)
    state.fatal_error = error
    built = RunState(run_id="r", config=pipeline_config(tmp_path), context=_run(), fatal_error=error)

    assert state.fatal_error is error
    assert built.fatal_error is error

    with pytest.raises(ValidationError) as rendered:
        RunState(run_id="r", config=pipeline_config(tmp_path), context=_run(), fatal_error="boom")
    assert "fatal_error" in str(rendered.value)


def test_run_state_snapshot_counts_saved_documents_into_a_new_context(tmp_path: Path) -> None:
    """``snapshot()`` returns a fresh ``RunContext`` whose ``drafts_saved`` is counted from ``documents``."""
    state = _run_state(tmp_path, "doc-a", "doc-b", "doc-c")
    state.documents["doc-a"].saved = _saved("doc-a")
    state.documents["doc-c"].saved = _saved("doc-c", "WARNING")

    snapshot = state.snapshot()

    assert snapshot is not state.context
    assert snapshot.drafts_saved == 2
    assert (snapshot.today, snapshot.max_attempts_per_doc, snapshot.max_drafts) == (TODAY, 3, 2)
    assert state.context.drafts_saved == 0  # the stored context is never mutated

    state.documents["doc-b"].saved = _saved("doc-b")
    assert state.snapshot().drafts_saved == 3
    assert snapshot.drafts_saved == 2  # an earlier snapshot is a copy, not a view


#: SPECIFICATIONS.md §6: the 27 models, section by section (§6.1 to §6.10), and the seven marked [New].
SPEC_MODELS: frozenset[str] = frozenset(
    {
        "RegulatoryUpdateSummary", "RegulatoryDocument", "CitationVerificationResult", "TDIServiceOffering",
        "AgentContext", "PipelineScope", "AttemptRecord",
        "ScoutCandidate", "ScoutReport", "ArticleDraft", "QAReport", "WorkerOutput",
        "RunContext", "DraftResult", "ToolResult",
        "DocumentRecord", "RunState",
        "ToolInvocation", "AgentTelemetry", "StageTelemetry", "ModelRate",
        "RemoteErrorDetail", "FailureRecord", "GuardrailViolation",
        "DraftMetadata",
        "PipelineConfig",
        "ExitCode",
    }
)
SPEC_NEW_MODELS: frozenset[str] = frozenset(
    {"AgentContext", "AttemptRecord", "RunContext", "ToolResult", "DocumentRecord", "RunState", "GuardrailViolation"}
)


def _defined_models() -> dict[str, type]:
    """Return the ``BaseModel`` and ``IntEnum`` classes ``src.schemas`` defines itself, by name.

    Pydantic writes every parametrised generic evaluated at a module's global scope, such as the return
    annotation ``WorkerOutput[ScoutReport]`` in ``src.agents``, into the generic's own module namespace under a
    name like ``"WorkerOutput[ScoutReport]"``. Those are not definitions, and their names are not identifiers,
    so they are skipped; otherwise the result would depend on whether ``src.agents`` was imported first.
    """
    return {
        name: value
        for name, value in vars(schemas).items()
        if name.isidentifier()
        and inspect.isclass(value)
        and value.__module__ == schemas.__name__
        and (issubclass(value, BaseModel) or issubclass(value, IntEnum))
    }


def test_schemas_defines_exactly_the_27_models_of_the_specification() -> None:
    """Iteration 4 AC1: 27 models, the seven new ones among them, every one exported."""
    defined = _defined_models()

    assert len(SPEC_MODELS) == 27
    assert set(defined) == SPEC_MODELS
    assert SPEC_NEW_MODELS <= set(defined)
    assert SPEC_MODELS <= set(schemas.__all__)


def test_every_model_ignores_extra_fields_and_only_run_state_allows_arbitrary_types() -> None:
    """Rule 1: ``extra="ignore"`` everywhere; ``arbitrary_types_allowed`` on ``RunState`` alone."""
    models = {name: cls for name, cls in _defined_models().items() if issubclass(cls, BaseModel)}

    assert {name for name, cls in models.items() if cls.model_config.get("extra") != "ignore"} == set()
    assert {name for name, cls in models.items() if cls.model_config.get("arbitrary_types_allowed")} == {"RunState"}
    # The new models populate through their field names only; only reused models keep populate_by_name.
    assert {name for name in SPEC_NEW_MODELS if models[name].model_config.get("populate_by_name")} == set()
