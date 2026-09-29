"""Unit tests for per-draft cost and the amortisation of shared telemetry (D-J; Approach 1 D20, D21, Q2).

Moved from Approach 1's ``tests/test_integration/test_orchestrator.py`` with the functions they test, which now
live in :mod:`src.telemetry`. The test bodies are unchanged apart from Approach 1's ScopeParser model ID, which
names the Scout's here: the ScopeParser is gone (Q12 = A), and both ran on ``gpt-5-mini``, so each rate lookup is
the same.

Rates are the fixed ``TEST_RATES`` of the scripted harness, so no test reads ``.env`` (D16), and no test builds an
agent or a model.
"""

import pytest

from src.agents import QA_LEGAL_MODEL_ID, SCOUT_MODEL_ID, WRITER_MODEL_ID
from src.schemas import AgentTelemetry, StageTelemetry, ToolInvocation
from src.telemetry import aggregate_draft_totals, amortise_shared_telemetry, estimate_cost
from tests.support.scripted import TEST_RATES


def _telemetry(
    model_id: str = WRITER_MODEL_ID,
    *,
    input_tokens: int = 0,
    cache_read_input_tokens: int = 0,
    output_tokens: int = 0,
    total_tokens: int | None = None,
    latency_ms: int = 0,
    total_duration_seconds: float = 0.0,
    reasoning_effort: str | None = None,
) -> AgentTelemetry:
    """Build an ``AgentTelemetry`` with explicit token counts for arithmetic tests."""
    return AgentTelemetry(
        model_id=model_id,
        reasoning_effort=reasoning_effort,
        input_tokens=input_tokens,
        cache_read_input_tokens=cache_read_input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens if total_tokens is None else total_tokens,
        latency_ms=latency_ms,
        total_duration_seconds=total_duration_seconds,
    )


def test_estimate_cost_applies_per_model_rates() -> None:
    """Cost is keyed off the telemetry's own ``model_id``, never a single global rate."""
    strong = _telemetry(WRITER_MODEL_ID, input_tokens=1000, output_tokens=500)
    fast = _telemetry(SCOUT_MODEL_ID, input_tokens=1000, output_tokens=500)

    assert estimate_cost(strong, TEST_RATES) == pytest.approx(1000 / 1e6 * 1.25 + 500 / 1e6 * 10.0)
    assert estimate_cost(fast, TEST_RATES) == pytest.approx(1000 / 1e6 * 0.25 + 500 / 1e6 * 2.0)
    assert estimate_cost(strong, TEST_RATES) > estimate_cost(fast, TEST_RATES)


def test_estimate_cost_excludes_cached_tokens_from_full_input_rate() -> None:
    """PLAN §2.6, the counting trap: ``inputTokens`` is inclusive of the cached prefix.

    Adding the cached term on top of the full input term bills the same tokens twice.
    """
    telemetry = _telemetry(WRITER_MODEL_ID, input_tokens=1000, cache_read_input_tokens=400, output_tokens=500)

    expected = 600 / 1e6 * 1.25 + 400 / 1e6 * 0.125 + 500 / 1e6 * 10.0
    assert estimate_cost(telemetry, TEST_RATES) == pytest.approx(expected)

    double_counted = 1000 / 1e6 * 1.25 + 400 / 1e6 * 0.125 + 500 / 1e6 * 10.0
    assert estimate_cost(telemetry, TEST_RATES) < double_counted


def test_estimate_cost_is_cheaper_when_tokens_are_cached() -> None:
    """Caching must reduce the bill, and billable input must never go negative."""
    uncached = _telemetry(WRITER_MODEL_ID, input_tokens=1000, output_tokens=100)
    fully_cached = _telemetry(WRITER_MODEL_ID, input_tokens=1000, cache_read_input_tokens=1000, output_tokens=100)

    assert estimate_cost(fully_cached, TEST_RATES) < estimate_cost(uncached, TEST_RATES)

    # Defensive: an upstream inconsistency must not produce a negative charge.
    impossible = _telemetry(WRITER_MODEL_ID, input_tokens=100, cache_read_input_tokens=400, output_tokens=0)
    assert estimate_cost(impossible, TEST_RATES) == pytest.approx(400 / 1e6 * 0.125)
    assert estimate_cost(impossible, TEST_RATES) >= 0.0


def test_estimate_cost_rejects_unknown_model_id() -> None:
    """A typo'd or renamed model must fail loudly rather than silently bill zero."""
    with pytest.raises(ValueError, match="gpt-4o"):
        estimate_cost(_telemetry("gpt-4o", input_tokens=10), TEST_RATES)


def test_amortise_shared_telemetry_splits_evenly_across_drafts() -> None:
    """Q2: ScopeParser and Scout run once per run and are shared equally by the drafts."""
    shared = [
        StageTelemetry(
            stage="scout",
            telemetry=_telemetry(SCOUT_MODEL_ID, input_tokens=600, output_tokens=300, total_tokens=900),
        )
    ]

    shares = amortise_shared_telemetry(shared, 3)

    assert len(shares) == 3
    for share in shares:
        assert len(share) == 1
        assert share[0].stage == "scout"
        assert share[0].telemetry.total_tokens == 300
        assert share[0].telemetry.input_tokens == 200
        assert share[0].telemetry.output_tokens == 100
    assert sum(s[0].telemetry.total_tokens for s in shares) == 900


def test_amortise_shared_telemetry_assigns_remainder_to_first_draft() -> None:
    """The integer remainder goes to the first draft so the run total is preserved exactly."""
    shared = [
        StageTelemetry(
            stage="scout",
            telemetry=_telemetry(SCOUT_MODEL_ID, input_tokens=100, output_tokens=0, total_tokens=100),
        )
    ]

    shares = amortise_shared_telemetry(shared, 3)

    assert [s[0].telemetry.total_tokens for s in shares] == [34, 33, 33]
    assert [s[0].telemetry.input_tokens for s in shares] == [34, 33, 33]
    assert sum(s[0].telemetry.total_tokens for s in shares) == 100


def test_amortise_never_gives_a_draft_more_cached_than_input_tokens() -> None:
    """D21 / SPECIFICATIONS §3.4: ``cache_read_input_tokens`` is a subset of ``input_tokens``.

    Sharing the two fields' remainders independently breaks that on the amortised
    record: with ``input=3, cached=2`` over three drafts, draft 0 takes the whole
    cached remainder and ends up with more cached tokens than input tokens. That
    is not cosmetic — ``estimate_cost`` prices the billable remainder as
    ``max(input - cached, 0)``, so the clamp silently mis-prices the batch and
    ``Σ per-draft cost`` stops matching the run cost.
    """
    shared = [
        StageTelemetry(
            stage="scout",
            telemetry=_telemetry(
                SCOUT_MODEL_ID,
                input_tokens=3,
                cache_read_input_tokens=2,
                output_tokens=1,
            ),
        )
    ]

    shares = amortise_shared_telemetry(shared, 3)

    for index, share in enumerate(shares):
        telemetry = share[0].telemetry
        assert telemetry.cache_read_input_tokens <= telemetry.input_tokens, f"draft {index}"
    # The cap never invents cached tokens either.
    assert sum(s[0].telemetry.cache_read_input_tokens for s in shares) <= 2
    # Token conservation on the additive field is untouched by the cap.
    assert sum(s[0].telemetry.total_tokens for s in shares) == 4


def test_amortised_cost_sums_to_the_run_cost_and_never_under_prices() -> None:
    """What the ``cache_read_input_tokens`` clamp actually costs, measured not assumed.

    Written after the fix, from the measurement PLAN §3.2's Refactor step asked
    for, so the residual is recorded rather than glossed:

    * Whenever the cached remainder divides without being clamped — every
      realistic split — ``Σ per-draft cost`` equals the run cost **exactly**.
    * In the degenerate case where the clamp bites, a cached token goes
      unattributed and the sum errs *upward*: the batch is marginally
      over-priced, never under-priced, because an unattributed cached token is
      simply billed at the full input rate somewhere.

    Over-pricing is the safe direction for a benchmark, and it is strictly better
    than the pre-fix behaviour, which broke ``cached <= input`` outright.
    """
    divides_evenly = [
        StageTelemetry(
            stage="scout",
            telemetry=_telemetry(SCOUT_MODEL_ID, input_tokens=100, cache_read_input_tokens=40, output_tokens=20),
        )
    ]
    run_cost = estimate_cost(divides_evenly[0].telemetry, TEST_RATES)
    shares = amortise_shared_telemetry(divides_evenly, 2)

    assert sum(estimate_cost(s[0].telemetry, TEST_RATES) for s in shares) == pytest.approx(run_cost)

    clamped = [
        StageTelemetry(
            stage="scout",
            telemetry=_telemetry(SCOUT_MODEL_ID, input_tokens=3, cache_read_input_tokens=2, output_tokens=1),
        )
    ]
    clamped_run_cost = estimate_cost(clamped[0].telemetry, TEST_RATES)
    clamped_shares = amortise_shared_telemetry(clamped, 3)

    assert sum(estimate_cost(s[0].telemetry, TEST_RATES) for s in clamped_shares) >= clamped_run_cost


def test_amortise_shared_telemetry_with_zero_drafts_returns_empty() -> None:
    """No drafts, nothing to attribute to — and no ZeroDivisionError."""
    shared = [StageTelemetry(stage="scout", telemetry=_telemetry(SCOUT_MODEL_ID, input_tokens=10))]

    assert amortise_shared_telemetry(shared, 0) == []
    assert amortise_shared_telemetry([], 2) == [[], []]


def test_amortise_shared_telemetry_keeps_tool_invocations_visible_in_every_draft() -> None:
    """Tool usage is diagnostic, not additive: a fractional call count means nothing.

    D19 makes ``tool_invocations`` the role-bleed detector, so it must remain
    legible in each draft rather than being divided into meaninglessness.
    """
    telemetry = _telemetry(SCOUT_MODEL_ID, input_tokens=10, total_tokens=10)
    telemetry.tool_invocations.append(
        ToolInvocation(tool_name="list_regulatory_updates", call_count=3, success_count=3)
    )

    shares = amortise_shared_telemetry([StageTelemetry(stage="scout", telemetry=telemetry)], 2)

    for share in shares:
        assert [inv.tool_name for inv in share[0].telemetry.tool_invocations] == ["list_regulatory_updates"]
        assert share[0].telemetry.tool_invocations[0].call_count == 3


def test_amortise_shared_telemetry_carries_the_reasoning_effort_through() -> None:
    """Splitting the numbers must not drop the configuration label (D24).

    Every share is a *new* ``AgentTelemetry``, so any field the rebuild does not
    name is silently lost. ``reasoning_effort`` is the only non-numeric,
    non-model field there, which makes it the one field that can go missing
    without a single arithmetic assertion noticing.
    """
    telemetry = _telemetry(SCOUT_MODEL_ID, input_tokens=120, output_tokens=40, reasoning_effort="low")

    shares = amortise_shared_telemetry([StageTelemetry(stage="scout", telemetry=telemetry)], 3)

    assert [share[0].telemetry.reasoning_effort for share in shares] == ["low", "low", "low"]


def test_aggregate_draft_totals_sums_own_and_shared() -> None:
    """A draft's totals are its own Writer/QA calls plus its amortised scope+scout share."""
    own = [
        StageTelemetry(stage="writer", telemetry=_telemetry(WRITER_MODEL_ID, input_tokens=1000, output_tokens=500)),
        StageTelemetry(
            stage="qa_legal",
            attempt=1,
            telemetry=_telemetry(QA_LEGAL_MODEL_ID, input_tokens=200, output_tokens=100),
        ),
    ]
    shared_share = [
        StageTelemetry(stage="scout", telemetry=_telemetry(SCOUT_MODEL_ID, input_tokens=400, output_tokens=200))
    ]

    total_tokens, cost = aggregate_draft_totals(own, shared_share, TEST_RATES)

    assert total_tokens == 1500 + 300 + 600
    expected_cost = (
        estimate_cost(own[0].telemetry, TEST_RATES)
        + estimate_cost(own[1].telemetry, TEST_RATES)
        + estimate_cost(shared_share[0].telemetry, TEST_RATES)
    )
    assert cost == pytest.approx(expected_cost)


def test_provider_latency_ms_is_not_used_for_duration() -> None:
    """PLAN §2.9: the OpenAI provider hardcodes ``latencyMs: 0``.

    ``accumulated_metrics.latencyMs`` is therefore structurally zero in production
    and must not feed any cost, duration or benchmark figure. Carried on the
    telemetry record, ignored by every calculation.
    """
    quiet = _telemetry(WRITER_MODEL_ID, input_tokens=1000, output_tokens=100, latency_ms=0)
    loud = _telemetry(WRITER_MODEL_ID, input_tokens=1000, output_tokens=100, latency_ms=987_654)

    assert estimate_cost(quiet, TEST_RATES) == estimate_cost(loud, TEST_RATES)

    own_quiet = [StageTelemetry(stage="writer", telemetry=quiet)]
    own_loud = [StageTelemetry(stage="writer", telemetry=loud)]
    assert aggregate_draft_totals(own_quiet, [], TEST_RATES) == aggregate_draft_totals(own_loud, [], TEST_RATES)
