import re
from datetime import date
from pathlib import Path

import pytest

from src.schemas import (
    AgentTelemetry,
    ArticleDraft,
    DraftMetadata,
    ModelRate,
    QAReport,
    StageTelemetry,
    ToolInvocation,
)
from src.template_engine import (
    format_citations_list,
    format_model_rates,
    format_review_notes,
    format_stage_telemetry,
    generate_draft_id,
    render_draft,
    save_draft,
)


def test_generate_draft_id_initial(tmp_path):
    drafts_dir = tmp_path / "drafts"
    draft_id = generate_draft_id(date(2026, 9, 11), drafts_dir)
    assert draft_id == "draft_20260911_001"
    assert drafts_dir.exists()


def test_generate_draft_id_sequential(tmp_path):
    drafts_dir = tmp_path / "drafts"
    drafts_dir.mkdir()
    (drafts_dir / "draft_20260911_001.md").touch()
    
    draft_id = generate_draft_id(date(2026, 9, 11), drafts_dir)
    assert draft_id == "draft_20260911_002"


def test_generate_draft_id_collision_prevention(tmp_path):
    drafts_dir = tmp_path / "drafts"
    drafts_dir.mkdir()
    (drafts_dir / "draft_20260911_001.md").touch()
    (drafts_dir / "draft_20260911_003.md").touch()
    
    draft_id = generate_draft_id(date(2026, 9, 11), drafts_dir)
    assert draft_id == "draft_20260911_004"


def test_generate_draft_id_custom_and_default_dates(tmp_path):
    drafts_dir = tmp_path / "drafts"
    
    # Test explicit date
    custom_date = date(2025, 1, 1)
    draft_id_custom = generate_draft_id(custom_date, drafts_dir)
    assert draft_id_custom == "draft_20250101_001"
    
    # Test default date
    draft_id_default = generate_draft_id(drafts_dir=drafts_dir)
    today_str = date.today().strftime("%Y%m%d")
    assert draft_id_default == f"draft_{today_str}_001"


def test_render_draft_success():
    draft = ArticleDraft(
        source_doc_id="inail-2024-circ-calore",
        headline="Test Headline",
        executive_summary="Summary",
        article_body="Body",
        tdi_cta="CTA"
    )
    metadata = DraftMetadata(
        draft_id="draft_20260911_001",
        source_name="EUR_LEX",
        publication_date="2026-09-11",
        source_document_title="Title",
        approach_name="Approach 1",
        qa_report=QAReport(status="PASS", verified_citations=["Ref A"], review_notes="All good"),
        attempts=1,
        latency_seconds=1.234,
        estimated_cost=0.005,
        total_tokens=100,
        unresolved_errors=[]
    )
    
    # Mock template matching the exact placeholders mentioned in the plan
    template_content = (
        "# {headline}\n"
        "**Draft ID:** {draft_id}\n"
        "## 📌 Executive Summary\n"
        "{brief_summary_for_managers}\n"
        "## 📖 Article Body\n"
        "{full_article_content}\n"
        "## 💼 Next Steps & TDI Specialist Support\n"
        "{tdi_lead_generation_call_to_action}\n"
        "--- \n"
        "## 📋 Source & Approach Details\n"
        "* **Source:** {source_name} ({publication_date}) — *{source_document_title}*\n"
        "* **Approach:** {approach_name}\n"
        "--- \n"
        "## ⚖️ Legal & Compliance Review (QA-Legal)\n"
        "* **Status:** {PASS / WARNING / ERROR}\n"
        "* **Revision Attempts:** {attempt_count}\n"
        "* **Verified Citations:**\n"
        "  - {citation_1}\n"
        "  - {citation_2}\n"
        "* **Review Notes:** {any_warnings_or_notes}\n"
    )
    
    rendered = render_draft(draft, metadata, template_content=template_content)
    assert "# Test Headline" in rendered
    assert "**Draft ID:** draft_20260911_001" in rendered
    assert "Summary" in rendered
    assert "Body" in rendered
    assert "CTA" in rendered
    assert "EUR_LEX" in rendered
    assert "2026-09-11" in rendered
    assert "Title" in rendered
    assert "Approach 1" in rendered
    assert "* **Status:** PASS" in rendered
    assert "* **Revision Attempts:** 1" in rendered
    assert "  - Ref A" in rendered
    assert "* **Review Notes:** All good" in rendered
    assert "{headline}" not in rendered


def test_render_verified_citations():
    assert format_citations_list(["Ref A", "Ref B"]) == "  - Ref A\n  - Ref B"
    assert format_citations_list([]) == "  - (No citations verified)"


def test_render_draft_with_unresolved_alert():
    qa_report = QAReport(status="ERROR", review_notes="Original note", verified_citations=[])
    notes = format_review_notes(qa_report, ["Error 1"])
    assert "[UNRESOLVED COMPLIANCE ALERT]" in notes
    assert "Original note" in notes


def test_render_draft_missing_placeholder_validation():
    draft = ArticleDraft(
        source_doc_id="inail-2024-circ-calore", headline="H", executive_summary="S", article_body="B", tdi_cta="C"
    )
    metadata = DraftMetadata(
        draft_id="ID", source_name="SN", publication_date="2026",
        source_document_title="Title", approach_name="Approach",
        qa_report=QAReport(status="PASS", verified_citations=[], review_notes=""),
        attempts=1, latency_seconds=1.0, estimated_cost=0.1, total_tokens=10,
        unresolved_errors=[]
    )
    
    # Template has a placeholder not in replacement map
    template_content = "{headline} and {unknown_placeholder}"
    with pytest.raises(ValueError, match="Unresolved placeholder found"):
        render_draft(draft, metadata, template_content=template_content)


def test_render_telemetry_formatting():
    draft = ArticleDraft(
        source_doc_id="inail-2024-circ-calore", headline="H", executive_summary="S", article_body="B", tdi_cta="C"
    )
    metadata = DraftMetadata(
        draft_id="ID", source_name="SN", publication_date="2026",
        source_document_title="Title", approach_name="Approach",
        qa_report=QAReport(status="PASS", verified_citations=[], review_notes=""),
        attempts=1, latency_seconds=1.239, estimated_cost=0.00421, total_tokens=100,
        unresolved_errors=[]
    )
    template_content = "{latency_seconds}s ${estimated_cost} {total_tokens}"
    rendered = render_draft(draft, metadata, template_content=template_content)
    assert "1.24s" in rendered
    assert "$0.0042" in rendered
    assert "100" in rendered


def test_save_draft_persistence(tmp_path):
    out_dir = tmp_path / "drafts"
    content = "Hello World"
    draft_id = "draft_20260911_001"
    saved_path = save_draft(content, draft_id, output_dir=out_dir)
    
    assert saved_path.exists()
    assert saved_path.name == f"{draft_id}.md"
    assert saved_path.read_text(encoding="utf-8") == "Hello World"
    assert out_dir.exists()


REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_TEMPLATE_PATH = REPO_ROOT / ".agents" / "templates" / "draft.md"


def _metadata(**overrides) -> DraftMetadata:
    """Build a fully-populated ``DraftMetadata`` for real-template rendering."""
    values = dict(
        draft_id="draft_20261010_005",
        source_name="INAIL",
        publication_date="2026-10-10",
        source_document_title="INAIL Circular",
        approach_name="Approach 2",
        qa_report=QAReport(status="PASS", verified_citations=["Cite 1", "Cite 2"], review_notes="Looks great"),
        attempts=2,
        latency_seconds=3.1415,
        estimated_cost=0.01234,
        total_tokens=456,
        unresolved_errors=[],
    )
    values.update(overrides)
    return DraftMetadata(**values)


def test_template_engine_e2e_flow(tmp_path):
    """End-to-end render and persist against the **real** shipped template.

    Bound to ``.agents/templates/draft.md`` itself rather than a hand-copied
    replica: a duplicate silently goes stale the moment the canonical template
    changes, which is exactly the drift this test exists to catch.
    """
    draft = ArticleDraft(
        source_doc_id="inail-2024-circ-calore",
        headline="My Final Headline",
        executive_summary="Final Summary",
        article_body="Final Body",
        tdi_cta="Final CTA",
    )
    metadata = _metadata()

    out_dir = tmp_path / "drafts"
    rendered = render_draft(draft, metadata, template_path=REAL_TEMPLATE_PATH)
    saved_path = save_draft(rendered, metadata.draft_id, output_dir=out_dir)

    content = saved_path.read_text(encoding="utf-8")
    assert "# My Final Headline" in content
    assert "**Draft ID:** draft_20261010_005" in content
    assert "Final Summary" in content
    assert "Final Body" in content
    assert "Final CTA" in content
    assert "INAIL" in content
    assert "2026-10-10" in content
    assert "Approach 2" in content
    assert "PASS" in content
    assert "  - Cite 1\n  - Cite 2" in content
    assert "Looks great" in content
    assert "3.14s" in content
    assert "$0.0123" in content
    assert "456 tokens" in content

    # Assert no curly braces are left unrendered
    assert "{" not in content
    assert "}" not in content


def test_real_template_renders_with_no_unresolved_placeholders():
    """Standing guard: every placeholder in the shipped template has a mapping.

    Not a Red-Green cycle — it passes today. Its value is prospective: it fails
    the moment ``.agents/templates/draft.md`` gains a placeholder that
    ``render_draft`` does not know how to substitute.
    """
    draft = ArticleDraft(
        source_doc_id="inail-2024-circ-calore",
        headline="Guard Headline",
        executive_summary="Guard Summary",
        article_body="Guard Body",
        tdi_cta="Guard CTA",
    )

    rendered = render_draft(draft, _metadata(), template_path=REAL_TEMPLATE_PATH)

    for section in (
        "## 📌 Executive Summary",
        "## 📖 Article Body",
        "## 💼 Next Steps & TDI Specialist Support",
        "## 📋 Source & Approach Details",
        "## ⚖️ Legal & Compliance Review (QA-Legal)",
        "### ⏱️ Run Telemetry (For Benchmark)",
    ):
        assert section in rendered
    assert not re.findall(r"\{[a-zA-Z0-9_]+\}", rendered)


# ============================================================================
# Phase 6, Batch 4: telemetry surface (SPECIFICATIONS:245 / D19)
# ============================================================================


def _stage(
    stage: str,
    model_id: str,
    *,
    attempt: int = 1,
    input_tokens: int = 0,
    cache_read_input_tokens: int = 0,
    output_tokens: int = 0,
    reasoning_effort: str | None = None,
    tools: list[ToolInvocation] | None = None,
) -> StageTelemetry:
    """Build one labelled stage telemetry record for the formatter tests."""
    return StageTelemetry(
        stage=stage,
        attempt=attempt,
        telemetry=AgentTelemetry(
            model_id=model_id,
            input_tokens=input_tokens,
            cache_read_input_tokens=cache_read_input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            reasoning_effort=reasoning_effort,
            tool_invocations=tools or [],
        ),
    )


def test_format_stage_telemetry_renders_markdown_table():
    """One header plus one row per stage, carrying the per-stage token split."""
    stages = [
        _stage("scout", "gpt-5-mini", input_tokens=120, output_tokens=40),
        _stage(
            "writer",
            "gpt-5.4",
            attempt=2,
            input_tokens=2000,
            cache_read_input_tokens=800,
            output_tokens=900,
            reasoning_effort="high",
        ),
    ]

    table = format_stage_telemetry(stages)
    lines = table.splitlines()

    assert lines[0].startswith("| Stage |")
    for column in ("Attempt", "Model", "Effort", "Input", "Cached", "Output", "Tools"):
        assert column in lines[0]
    assert set(lines[1].replace("|", "").replace(" ", "")) <= {":", "-"}
    assert len(lines) == 4

    # The Scout runs at no declared effort, so its cell is an em dash, never blank.
    assert "| scout | 1 | gpt-5-mini | — | 120 | 0 | 40 |" in lines[2]
    assert "| writer | 2 | gpt-5.4 | high | 2000 | 800 | 900 |" in lines[3]


def test_format_stage_telemetry_lists_tool_invocations_with_counts():
    """D19's role-bleed detector is only useful if the draft shows who called what."""
    stages = [
        _stage(
            "qa_legal",
            "gpt-5.4",
            input_tokens=500,
            output_tokens=200,
            tools=[
                ToolInvocation(tool_name="verify_legal_citation", call_count=3, success_count=3),
                ToolInvocation(tool_name="get_document_by_id", call_count=1, success_count=1),
            ],
        )
    ]

    table = format_stage_telemetry(stages)

    assert "verify_legal_citation×3" in table
    assert "get_document_by_id×1" in table
    # Rendered on the stage's own row, so the reader can attribute the call.
    row = [line for line in table.splitlines() if "qa_legal" in line][0]
    assert "verify_legal_citation×3" in row


def test_format_stage_telemetry_handles_empty_and_toolless_stages():
    """Never render an empty string into the draft: the section must stay legible."""
    empty = format_stage_telemetry([])
    assert empty.strip() != ""
    assert "no telemetry" in empty.lower()

    toolless = format_stage_telemetry([_stage("scout", "gpt-5-mini", input_tokens=10, output_tokens=5)])
    row = [line for line in toolless.splitlines() if "scout" in line][0]
    assert row.rstrip().endswith("— |")


def test_format_model_rates_renders_configured_rates():
    """The cost basis is recorded in the draft so a benchmark stays auditable (D21)."""
    rates = {
        "gpt-5-mini": ModelRate(
            input_usd_per_mtok=0.25, cached_input_usd_per_mtok=0.025, output_usd_per_mtok=2.0
        ),
        "gpt-5.4": ModelRate(
            input_usd_per_mtok=1.25, cached_input_usd_per_mtok=0.125, output_usd_per_mtok=10.0
        ),
    }

    rendered = format_model_rates(rates)

    assert "\n" not in rendered
    assert "gpt-5-mini" in rendered and "gpt-5.4" in rendered
    assert "0.25" in rendered and "0.025" in rendered and "2.00" in rendered
    assert "1.25" in rendered and "0.125" in rendered and "10.00" in rendered
    assert "in/cached/out" in rendered

    assert format_model_rates({}).strip() != ""


def test_render_draft_substitutes_telemetry_placeholders():
    """Both new placeholders resolve against the **real** shipped template."""
    draft = ArticleDraft(
        source_doc_id="inail-2024-circ-calore",
        headline="Telemetry Headline",
        executive_summary="Telemetry Summary",
        article_body="Telemetry Body",
        tdi_cta="Telemetry CTA",
    )
    metadata = _metadata(
        stage_telemetry=[
            _stage(
                "scout",
                "gpt-5-mini",
                input_tokens=300,
                output_tokens=120,
                tools=[ToolInvocation(tool_name="list_regulatory_updates", call_count=2, success_count=2)],
            ),
            _stage("writer", "gpt-5.4", input_tokens=2000, output_tokens=900),
        ],
        model_rates_used={
            "gpt-5.4": ModelRate(
                input_usd_per_mtok=1.25, cached_input_usd_per_mtok=0.125, output_usd_per_mtok=10.0
            )
        },
    )

    rendered = render_draft(draft, metadata, template_path=REAL_TEMPLATE_PATH)

    assert "#### Agent Tool Usage" in rendered
    assert "| Stage |" in rendered
    assert "list_regulatory_updates×2" in rendered
    assert "| writer | 1 | gpt-5.4 | — | 2000 | 0 | 900 |" in rendered
    assert "**Cost Basis:**" in rendered
    assert "gpt-5.4" in rendered
    assert not re.findall(r"\{[a-zA-Z0-9_]+\}", rendered)


# ============================================================================
# Phase 7, Batch 2: the unresolved-placeholder guard (PLAN §6 Q3)
# ============================================================================


def test_render_draft_allows_braces_in_generated_prose() -> None:
    """Q3: LLM prose may legitimately contain braces, and must never cost a draft.

    The guard must be computed from the *template's* own pre-substitution tokens,
    not by re-scanning the rendered output for a brace shape. Scanning the output
    turns an Italian form name like ``{modello_A}`` into
    ``ValueError`` -> ``_StageError("render")`` -> ``PERSISTENCE_ERROR`` (exit 4),
    and the draft is never written at all.
    """
    draft = ArticleDraft(
        source_doc_id="inail-2024-circ-calore",
        headline="Modulistica aggiornata",
        executive_summary="Usare il modulo {modello_A} per la notifica.",
        article_body="## Adempimenti\nCompilare {modello_A} e allegare il campo {codice_fiscale}.",
        tdi_cta="Richiedi il supporto TDI.",
    )

    rendered = render_draft(draft, _metadata(), template_path=REAL_TEMPLATE_PATH)

    assert "Usare il modulo {modello_A} per la notifica." in rendered
    assert "Compilare {modello_A} e allegare il campo {codice_fiscale}." in rendered


def test_render_draft_still_rejects_an_unsubstituted_template_token() -> None:
    """Regression guard on the fix: a token the map does not cover still raises."""
    draft = ArticleDraft(
        source_doc_id="inail-2024-circ-calore", headline="H", executive_summary="S", article_body="B", tdi_cta="C"
    )

    with pytest.raises(ValueError, match="Unresolved placeholder found"):
        render_draft(draft, _metadata(), template_content="{headline} and {mystery_field}")


def test_render_draft_rejects_an_unsubstituted_non_word_token() -> None:
    r"""The old ``\{[a-zA-Z0-9_]+\}`` pattern could not see a token with spaces or slashes.

    ``{PASS / WARNING / ERROR}`` is exactly that shape and is a real template
    token, so a guard blind to it would let a genuinely unresolved placeholder
    ship inside a published draft.
    """
    draft = ArticleDraft(
        source_doc_id="inail-2024-circ-calore", headline="H", executive_summary="S", article_body="B", tdi_cta="C"
    )

    with pytest.raises(ValueError, match="Unresolved placeholder found"):
        render_draft(draft, _metadata(), template_content="{headline} then {UNMAPPED / TOKEN}")


# ============================================================================
# Item 2: the Run Telemetry table must be a standalone Markdown block
# ============================================================================


def _telemetry_render() -> str:
    """Render one draft through the real template with a two-row stage table."""
    draft = ArticleDraft(
        source_doc_id="inail-2024-circ-calore",
        headline="Telemetry Headline",
        executive_summary="Telemetry Summary",
        article_body="Telemetry Body",
        tdi_cta="Telemetry CTA",
    )
    metadata = _metadata(
        stage_telemetry=[
            _stage(
                "scout",
                "gpt-5-mini",
                input_tokens=300,
                output_tokens=120,
                tools=[ToolInvocation(tool_name="list_regulatory_updates", call_count=2, success_count=2)],
            ),
            _stage("writer", "gpt-5.4", input_tokens=2000, output_tokens=900),
        ],
        model_rates_used={
            "gpt-5.4": ModelRate(input_usd_per_mtok=1.25, cached_input_usd_per_mtok=0.125, output_usd_per_mtok=10.0)
        },
    )
    return render_draft(draft, metadata, template_path=REAL_TEMPLATE_PATH)


def test_telemetry_table_is_a_top_level_block_not_a_list_continuation() -> None:
    """A GFM table nested under a ``*`` bullet is literal text to every CommonMark renderer.

    The shipped template used to emit ``{stage_telemetry_markdown_table}`` on the
    line directly after ``* **Agent Tool Usage:**``, with no blank line and no
    indentation. CommonMark resolves that as a lazy continuation of the list
    item's paragraph, so the pipe rows render as prose — which is exactly what
    ``drafts/draft_20260918_001.md`` shows. The table must therefore start its own
    top-level block: preceded by a blank line, at column zero, and not attached to
    a bullet.
    """
    lines = _telemetry_render().splitlines()
    header_index = next(index for index, line in enumerate(lines) if line.startswith("| Stage |"))

    # Own block: a blank line immediately above, and the nearest non-blank line
    # above that is not a list item the table could be swallowed into.
    assert lines[header_index - 1].strip() == ""
    preceding = next(line for line in reversed(lines[:header_index]) if line.strip())
    assert not preceding.lstrip().startswith(("*", "-", "+"))

    # Unindented, and closed by a blank line or end of document.
    assert lines[header_index] == lines[header_index].lstrip()
    delimiter_index = header_index + 1
    assert lines[delimiter_index].lstrip().startswith("| :---")
    last_row = delimiter_index + 2
    assert lines[last_row].startswith("| writer |")
    assert last_row + 1 == len(lines) or lines[last_row + 1].strip() == ""


def test_telemetry_table_has_its_own_heading_and_cost_basis_stays_a_bullet() -> None:
    """``Agent Tool Usage`` is promoted to a heading; the other telemetry lines are unchanged."""
    rendered = _telemetry_render()

    assert "#### Agent Tool Usage" in rendered
    assert "* **Agent Tool Usage:**" not in rendered
    # Every other line of the section keeps its bullet form.
    assert "* **Time Taken:**" in rendered
    assert "* **Estimated Cost:**" in rendered
    assert "* **Cost Basis:** " in rendered
    # The token is still a single-line substitution, so the renderer itself is unchanged.
    assert "list_regulatory_updates×2" in rendered
    assert "| writer | 1 | gpt-5.4 | — | 2000 | 0 | 900 |" in rendered
