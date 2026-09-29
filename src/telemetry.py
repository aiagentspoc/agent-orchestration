"""Per-draft cost and the equal share of run-level telemetry (D-J; SPECIFICATIONS.md §2.1).

Moved verbatim from Approach 1's ``src/orchestrator.py``, which is not copied: the three-rate cost model (its D21)
and the amortisation that gives every draft an equal integer share of the stages that serve the whole run (its Q2).
The cost basis is a benchmark constant, so the function bodies are Approach 1's, byte for byte.
"""

from collections.abc import Mapping, Sequence

from .schemas import AgentTelemetry, ModelRate, StageTelemetry

__all__ = ["aggregate_draft_totals", "amortise_shared_telemetry", "estimate_cost"]


def estimate_cost(telemetry: AgentTelemetry, rates: Mapping[str, ModelRate]) -> float:
    """Price one worker invocation in USD.

    ``inputTokens`` is **inclusive** of the cached prefix: OpenAI reports
    ``prompt_tokens`` as the total and ``prompt_tokens_details.cached_tokens`` as
    the part of it served from cache, and Strands maps ``inputTokens =
    prompt_tokens``. Charging both the full input rate on ``input_tokens`` and the
    cached rate on ``cache_read_input_tokens`` therefore bills the cached prefix
    twice, so the full rate applies only to the billable remainder.

    Args:
        telemetry: One worker invocation's token counts, carrying its own model ID.
        rates: The resolved cost basis, keyed by pipeline model ID.

    Returns:
        The estimated cost in USD.

    Raises:
        ValueError: If ``telemetry.model_id`` has no rate. A renamed or typo'd
            model must fail loudly rather than silently price the run at zero.
    """
    rate = rates.get(telemetry.model_id)
    if rate is None:
        raise ValueError(
            f"No cost rate configured for model ID {telemetry.model_id!r}; "
            f"known models: {sorted(rates)}."
        )
    billable_input = max(telemetry.input_tokens - telemetry.cache_read_input_tokens, 0)
    return (
        billable_input / 1e6 * rate.input_usd_per_mtok
        + telemetry.cache_read_input_tokens / 1e6 * rate.cached_input_usd_per_mtok
        + telemetry.output_tokens / 1e6 * rate.output_usd_per_mtok
    )


def _share(total: int, parts: int, index: int) -> int:
    """Return draft ``index``'s integer share of ``total`` split ``parts`` ways.

    The remainder goes to the first draft, so the shares sum back to ``total``
    exactly and ``Σ per-draft tokens == run total`` holds (Q2).
    """
    base, remainder = divmod(total, parts)
    return base + remainder if index == 0 else base


def _share_capped(total: int, cap: int, parts: int, index: int) -> int:
    """Like :func:`_share`, but never exceeding this draft's share of ``cap``.

    ``cache_read_input_tokens`` is a *subset of* ``input_tokens`` (D21,
    SPECIFICATIONS §3.4). Sharing the two fields' remainders independently hands
    draft 0 the whole cached remainder, which can leave it holding more cached
    tokens than input tokens — breaking ``max(input - cached, 0)`` in
    :func:`estimate_cost` and mis-summing the per-draft cost.

    The clamp is applied to the cached field only, so exact ``total_tokens``
    conservation is untouched. It can leave a cached token unattributed, which is
    the right direction: cached tokens move *cost*, never token totals, so an
    unattributed one slightly over-prices a draft rather than inventing input
    the draft never had.

    Args:
        total: The run-level value being split.
        cap: The field this one is a subset of, split the same way.
        parts: How many drafts the run produced.
        index: Which draft's share to return.

    Returns:
        This draft's share of ``total``, never above its share of ``cap``.
    """
    return min(_share(total, parts, index), _share(cap, parts, index))


def amortise_shared_telemetry(
    shared: Sequence[StageTelemetry],
    draft_count: int,
) -> list[list[StageTelemetry]]:
    """Split run-level telemetry equally across the drafts it produced.

    The ScopeParser and the Scout run once per run but serve every draft, so
    attributing their tokens to the first draft alone would misprice a batch.
    Each draft receives an equal integer share, the remainder going to the first,
    which keeps the per-draft figures summing exactly to the run total (Q2). The
    one exception is ``cache_read_input_tokens``, which is clamped by
    :func:`_share_capped` so a draft never receives more cached tokens than input
    tokens; that field is a subset of ``input_tokens`` and affects cost only.

    ``tool_invocations`` are **not** divided: they are diagnostic rather than
    additive — D19 makes them the role-bleed detector (SPECIFICATIONS §3.4) — and
    a fractional call count would say nothing. Each draft therefore sees the
    shared stages' tool usage in full.

    Args:
        shared: The run-level stage telemetry (ScopeParser, Scout).
        draft_count: How many drafts the run produced.

    Returns:
        One list of amortised :class:`~src.schemas.StageTelemetry` per draft, in
        draft order. Empty when ``draft_count`` is zero.
    """
    if draft_count <= 0:
        return []

    shares: list[list[StageTelemetry]] = []
    for index in range(draft_count):
        per_draft: list[StageTelemetry] = []
        for stage in shared:
            source = stage.telemetry
            per_draft.append(
                StageTelemetry(
                    stage=stage.stage,
                    attempt=stage.attempt,
                    telemetry=AgentTelemetry(
                        model_id=source.model_id,
                        reasoning_effort=source.reasoning_effort,
                        input_tokens=_share(source.input_tokens, draft_count, index),
                        cache_read_input_tokens=_share_capped(
                            source.cache_read_input_tokens, source.input_tokens, draft_count, index
                        ),
                        output_tokens=_share(source.output_tokens, draft_count, index),
                        total_tokens=_share(source.total_tokens, draft_count, index),
                        latency_ms=_share(source.latency_ms, draft_count, index),
                        total_duration_seconds=source.total_duration_seconds / draft_count,
                        cycles=source.cycles,
                        tool_invocations=[inv.model_copy(deep=True) for inv in source.tool_invocations],
                    ),
                )
            )
        shares.append(per_draft)
    return shares


def aggregate_draft_totals(
    own: Sequence[StageTelemetry],
    shared_share: Sequence[StageTelemetry],
    rates: Mapping[str, ModelRate],
) -> tuple[int, float]:
    """Total one draft's tokens and cost across its own and its shared stages.

    ``own`` is that draft's Writer and QA-Legal calls across every attempt, which
    is only correct because each invocation used a fresh ``Agent`` (D20):
    ``EventLoopMetrics`` accumulate per agent object, so a reused agent would
    report call 2 as call 1 plus call 2.

    Provider ``latency_ms`` is deliberately absent from this calculation — the
    OpenAI provider hardcodes it to zero (PLAN §2.9), so wall-clock timing is the
    only honest duration.

    Args:
        own: Stage telemetry produced for this draft alone.
        shared_share: This draft's amortised share of the run-level stages.
        rates: The resolved cost basis, keyed by pipeline model ID.

    Returns:
        ``(total_tokens, estimated_cost_usd)``.
    """
    total_tokens = 0
    cost = 0.0
    for stage in list(own) + list(shared_share):
        total_tokens += stage.telemetry.total_tokens
        cost += estimate_cost(stage.telemetry, rates)
    return total_tokens, cost
