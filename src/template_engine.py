"""Markdown template compiler and telemetry renderer for HSE Easy drafts."""

import re
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Final

from .schemas import ArticleDraft, DraftMetadata, ModelRate, QAReport, StageTelemetry


def generate_draft_id(date_val: date | None = None, drafts_dir: Path | str = "drafts") -> str:
    if date_val is None:
        date_val = date.today()
    
    date_str = date_val.strftime("%Y%m%d")
    drafts_path = Path(drafts_dir)
    drafts_path.mkdir(parents=True, exist_ok=True)
    
    max_seq = 0
    pattern = re.compile(rf"^draft_{date_str}_(\d{{3}})\.md$")
    
    for file_path in drafts_path.glob(f"draft_{date_str}_*.md"):
        match = pattern.match(file_path.name)
        if match:
            seq = int(match.group(1))
            if seq > max_seq:
                max_seq = seq
                
    return f"draft_{date_str}_{max_seq + 1:03d}"


DEFAULT_TEMPLATE_PATH: Path = Path(".agents/templates/draft.md")

#: Brace placeholders the template declares. Deliberately ``[^{}]+`` and not
#: ``[a-zA-Z0-9_]+``: ``{PASS / WARNING / ERROR}`` is a real token that the
#: narrower pattern cannot see, so a guard built on it was blind to a genuinely
#: unresolved placeholder.
_TEMPLATE_TOKEN_PATTERN: Final[re.Pattern[str]] = re.compile(r"\{[^{}]+\}")

#: The one placeholder the shipped template writes in bracket form. Listed
#: literally rather than matched by a broad ``\[...\]`` pattern, which would also
#: claim every Markdown link a future template might legitimately contain.
_BRACKET_TEMPLATE_TOKENS: Final[tuple[str, ...]] = ("[Article Headline Here]",)


def _template_tokens(template: str) -> set[str]:
    """Return the placeholder tokens the template itself declares.

    The guard in :func:`render_draft` must be computed from the *template*, never
    from the rendered output: LLM-generated prose may legitimately contain
    braces, and scanning the substituted text turns an Italian form name like
    ``{modello_A}`` into a lost draft — ``ValueError`` becomes a ``render`` stage
    failure and the pipeline exits ``PERSISTENCE_ERROR`` (4) without ever writing
    the file.

    Args:
        template: The raw template text, before any substitution.

    Returns:
        Every placeholder token present in ``template``, brace and bracket alike.
    """
    tokens = set(_TEMPLATE_TOKEN_PATTERN.findall(template))
    tokens.update(token for token in _BRACKET_TEMPLATE_TOKENS if token in template)
    return tokens


def format_citations_list(citations: list[str]) -> str:
    if not citations:
        return "  - (No citations verified)"
    return "\n".join(f"  - {citation}" for citation in citations)


def format_review_notes(qa_report: QAReport, unresolved_errors: list[str]) -> str:
    alert_prefix = "[UNRESOLVED COMPLIANCE ALERT]\n\n"
    has_errors = qa_report.status == "ERROR" or len(unresolved_errors) > 0
    notes = qa_report.review_notes or ""
    if has_errors:
        return alert_prefix + notes
    return notes


_NO_TOOLS = "—"
#: Rendered in any table cell whose value was never recorded, so a column never
#: renders blank and an absent value is visibly absent rather than overlooked.
#: It shares :data:`_NO_TOOLS`'s glyph and not its meaning — "this worker called
#: no tools" and "this worker had no effort configured" are different facts — so
#: the duplication is deliberate and must not be collapsed into one constant.
_UNSET_CELL: Final[str] = "—"
_TOOL_SEPARATOR = ", "


def format_stage_telemetry(stages: Sequence[StageTelemetry]) -> str:
    """Render per-worker telemetry as a Markdown table for the draft.

    SPECIFICATIONS §3.4 makes this a normative obligation on Phase 6: D19 stopped
    scoping substrate tools per worker, so ``tool_invocations`` is the compensating
    control that makes role bleed — "did the Writer audit its own citations?" —
    detectable after the fact. Surfacing it in the draft is what activates that
    detection; leaving it in memory only would make D19's detection half inert.

    Args:
        stages: The labelled telemetry records behind one draft.

    Returns:
        A Markdown table, or a placeholder line when there is nothing to report.
        Never the empty string, which would leave a blank bullet in the draft.
    """
    if not stages:
        return "_(no telemetry recorded)_"

    rows = [
        "| Stage | Attempt | Model | Effort | Input | Cached | Output | Tools |",
        "| :--- | ---: | :--- | :--- | ---: | ---: | ---: | :--- |",
    ]
    for stage in stages:
        telemetry = stage.telemetry
        tools = _TOOL_SEPARATOR.join(
            f"{invocation.tool_name}×{invocation.call_count}" for invocation in telemetry.tool_invocations
        )
        rows.append(
            f"| {stage.stage} | {stage.attempt} | {telemetry.model_id} "
            f"| {telemetry.reasoning_effort or _UNSET_CELL} "
            f"| {telemetry.input_tokens} | {telemetry.cache_read_input_tokens} | {telemetry.output_tokens} "
            f"| {tools or _NO_TOOLS} |"
        )
    return "\n".join(rows)


def format_model_rates(rates: Mapping[str, ModelRate]) -> str:
    """Render the cost basis a draft was priced with, on a single line (D21).

    Rates are deployment configuration and will change; recording them in the
    draft keeps the Phase 7 benchmark auditable long after the ``.env`` moved on.

    Args:
        rates: The resolved per-model rates used for this draft.

    Returns:
        A one-line summary, or a placeholder when no rates were recorded.
    """
    if not rates:
        return "(not recorded)"
    return "; ".join(
        f"{model_id} $"
        f"{rate.input_usd_per_mtok:.2f}/$"
        f"{rate.cached_input_usd_per_mtok:.3f}/$"
        f"{rate.output_usd_per_mtok:.2f} per 1M (in/cached/out)"
        for model_id, rate in sorted(rates.items())
    )


def render_draft(
    draft: ArticleDraft,
    metadata: DraftMetadata,
    template_path: Path | str | None = None,
    template_content: str | None = None
) -> str:
    if template_content is None:
        path = Path(template_path) if template_path else DEFAULT_TEMPLATE_PATH
        template_content = path.read_text(encoding="utf-8")

    # Captured before any substitution: these, and only these, are what the guard
    # below may complain about (Q3).
    declared_tokens = _template_tokens(template_content)

    citations_str = format_citations_list(metadata.qa_report.verified_citations)
    review_notes_str = format_review_notes(metadata.qa_report, metadata.unresolved_errors)
    
    # Substitute multi-line verified citations block if standard template placeholders exist
    template_content = template_content.replace(
        "  - {citation_1}\n  - {citation_2}", 
        citations_str
    )
    
    # Map draft and metadata fields to corresponding template placeholders
    replacements = {
        "{headline}": draft.headline,
        "[Article Headline Here]": draft.headline,
        "{draft_id}": metadata.draft_id,
        "{brief_summary_for_managers}": draft.executive_summary,
        "{full_article_content}": draft.article_body,
        "{tdi_lead_generation_call_to_action}": draft.tdi_cta,
        "{source_name}": metadata.source_name,
        "{publication_date}": metadata.publication_date,
        "{source_document_title}": metadata.source_document_title,
        "{approach_name}": metadata.approach_name,
        "{PASS / WARNING / ERROR}": metadata.qa_report.status,
        "{attempt_count}": str(metadata.attempts),
        "{any_warnings_or_notes}": review_notes_str,
        "{latency_seconds}": f"{metadata.latency_seconds:.2f}",
        "{estimated_cost}": f"{metadata.estimated_cost:.4f}",
        "{total_tokens}": str(metadata.total_tokens),
        "{stage_telemetry_markdown_table}": format_stage_telemetry(metadata.stage_telemetry),
        "{model_rates_used}": format_model_rates(metadata.model_rates_used),
    }
    
    rendered = template_content
    for placeholder, value in replacements.items():
        rendered = rendered.replace(placeholder, str(value))
        
    # Only a token the template itself declared can be "unresolved". A brace
    # sequence the model wrote into the article body is content, not a
    # placeholder, and must never cost the draft.
    unresolved = sorted(token for token in declared_tokens if token in rendered)
    if unresolved:
        raise ValueError(f"Unresolved placeholder found: {unresolved[0]}")

    return rendered


def save_draft(content: str, draft_id: str, output_dir: Path | str = "drafts") -> Path:
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    file_path = out_path / f"{draft_id}.md"
    file_path.write_text(content, encoding="utf-8")
    return file_path
