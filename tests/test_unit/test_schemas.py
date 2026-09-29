"""Unit tests for HSE Easy Pydantic v2 schemas and data contracts.

Batch 1: Substrate data models (RegulatoryUpdateSummary, RegulatoryDocument,
CitationVerificationResult, TDIServiceOffering).
"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from src.schemas import (
    AgentTelemetry,
    ArticleDraft,
    CitationVerificationResult,
    DraftMetadata,
    DraftResult,
    FailureRecord,
    ModelRate,
    PipelineConfig,
    PipelineExitCode,
    PipelineScope,
    QAReport,
    RegulatoryDocument,
    RegulatoryUpdateSummary,
    RemoteErrorDetail,
    StageTelemetry,
    TDIServiceOffering,
)

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
# Batch 2: Internal Pipeline Models & Revision Payload Tests
# ============================================================================


def test_pipeline_scope_defaults_and_unconstrained() -> None:
    """Test PipelineScope default unconstrained ceiling (max_drafts=None) and sources filtering."""
    scope = PipelineScope(time_window="past_3_months", date_from="2026-06-22", date_to="2026-09-22")
    assert scope.time_window == "past_3_months"
    assert scope.max_drafts is None  # Mandatory default per Rule 4
    assert scope.sources == []
    assert scope.sector_constraints == []

    # Valid with constrained ceiling and sources
    custom_scope = PipelineScope(
        time_window="30_days",
        date_from="2026-08-23",
        date_to="2026-09-22",
        sources=["INAIL", "EUR_LEX"],
        sector_constraints=["construction"],
        max_drafts=3,
    )
    assert custom_scope.max_drafts == 3
    assert len(custom_scope.sources) == 2

    # Invalid source literal
    with pytest.raises(ValidationError) as exc_info:
        PipelineScope(
            time_window="30_days",
            date_from="2026-08-23",
            date_to="2026-09-22",
            sources=["UNKNOWN_SOURCE"],  # type: ignore[list-item]
        )
    assert "sources" in str(exc_info.value)


def test_pipeline_scope_carries_absolute_date_bounds() -> None:
    """The window is resolved upstream: the scope carries absolute ISO bounds.

    ``time_window`` stays the human-readable form the "searched window" notice
    reports; ``date_from`` / ``date_to`` are the machine form the Scout hands
    straight to ``list_regulatory_updates``. Both bounds are required, so a scope
    can never reach the Scout without them and leave it inferring "now".
    """
    scope = PipelineScope(time_window="past_3_months", date_from="2026-06-22", date_to="2026-09-22")
    assert scope.date_from == "2026-06-22"
    assert scope.date_to == "2026-09-22"

    with pytest.raises(ValidationError) as exc_info:
        PipelineScope(time_window="past_3_months")  # type: ignore[call-arg]
    message = str(exc_info.value)
    assert "date_from" in message
    assert "date_to" in message


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
    assert metadata.approach_name == "Approach 1 (Code-Orchestrated Pipeline)"
    assert metadata.unresolved_errors == []
    assert metadata.qa_report.status == "PASS"
    assert metadata.attempts == 1
    assert metadata.latency_seconds == 14.2
    assert metadata.estimated_cost == 0.045
    assert metadata.total_tokens == 1820


def test_pipeline_exit_codes() -> None:
    """Test PipelineExitCode integer values and mapping matching SPECIFICATIONS.md Section 6."""
    assert PipelineExitCode.SUCCESS == 0
    assert PipelineExitCode.NO_UPDATES == 1
    assert PipelineExitCode.MCP_ERROR == 2
    assert PipelineExitCode.PARSER_ERROR == 3
    assert PipelineExitCode.PERSISTENCE_ERROR == 4
    # QA-A12: the sixth code was unasserted. It exists because every other code
    # describes a run that started, and an unconfigured checkout must not exit on
    # Python's default status of 1 -- which is NO_UPDATES, a *clean* result.
    assert PipelineExitCode.CONFIG_ERROR == 5


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
    stage = StageTelemetry(stage="writer", attempt=2, telemetry=telemetry)

    round_tripped = StageTelemetry.model_validate_json(stage.model_dump_json())
    assert round_tripped.stage == "writer"
    assert round_tripped.attempt == 2
    assert round_tripped.telemetry.total_tokens == 15

    with pytest.raises(ValidationError):
        StageTelemetry(stage="orchestrator", telemetry=telemetry)


def test_stage_telemetry_attempt_defaults_to_one() -> None:
    """Stages outside the revision loop are attempt 1 without saying so."""
    stage = StageTelemetry(stage="scout", telemetry=AgentTelemetry(model_id="gpt-5-mini"))

    assert stage.attempt == 1


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
        draft_id="draft_20260917_001",
        path=Path("drafts/draft_20260917_001.md"),
        doc_id="inail-2024-circ-calore",
        qa_status="WARNING",
        writer_invocations=2,
    )
    assert result.writer_invocations == 2


def test_failure_record_preserves_full_error_detail() -> None:
    """PLAN §2.10: nothing about a remote failure is truncated or dropped."""
    long_message = "Rate limit reached for gpt-5.4 in organization org-abc. " * 40

    minimal = FailureRecord(stage="writer", error_type="ValueError", message="boom")
    assert minimal.doc_id is None
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
