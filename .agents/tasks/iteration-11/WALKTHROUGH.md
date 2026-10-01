# Iteration 11 — End-of-run reconciliation and rendering: walkthrough

**Dates:** 2026-09-30 to 2026-10-01 · **Branch:** `approach-2/implementation` · **Plan section:** `IMPLEMENTATION_PLAN.md` §5, Iteration 11

## 1. Overview

Iteration 11 adds `finalise_run`, everything code does once the Supervisor has finished (D-B, D-C "Unfinished candidates", SPECIFICATIONS.md §6.8). It decides nothing; it reconciles and renders.

1. **The Supervisor's ledger entry.** `finalise_run` appends one `StageTelemetry(stage="supervisor")`. If the Supervisor's telemetry is missing, it logs a WARNING and adds nothing.
2. **Unsaved candidates.** Each candidate left unsaved is logged at WARNING with its last state.
3. **Rendering, in save order.** Each saved draft is rendered with its own Writer and QA-Legal entries plus an equal share of the Scout and the Supervisor, then written to its allocated path. A render or write failure is recorded and logged at ERROR, and the next draft is still written.
4. **Run totals.** It returns `RunFinalisation(persistence_failed, total_tokens, estimated_cost)` over the whole ledger. Iteration 14's "Run completed" logs these figures (P12).

The iteration was blocked once at pre-flight on two questions, which the user answered on 2026-10-01:
* **Q8 → P11:** per-draft latency counts only the Supervisor's own time.
* **Q9 → P12:** run totals are logged once, on "Run completed".

## 2. Files changed

| File | Status | Responsibility |
| :--- | :--- | :--- |
| `src/rendering.py` | Edited, +302 lines | `RunFinalisation`, `finalise_run` and their private helpers; see below |
| `tests/test_unit/test_rendering.py` | Edited, +26 tests (32 in all) | `finalise_run` end to end, over hand-built `RunState`s, with no model |
| `tests/test_unit/test_docs_consistency.py` | Edited | `IMPLEMENTATION_DECISIONS` gains P11 and P12; two docstrings now say "P1 to P12" |
| `.agents/docs/SPECIFICATIONS.md` | Edited by the implementer | §8.3 gains the P11 and P12 rows, under the heading (P1–P12). The status line and the §8 index now say P1–P12. D-B "Latency and totals" states P12 and P11. The D-I "Run completed" row cites P12. The §6.8 `latency_seconds` comment now carries the P11 formula. "P13 and so on" names the next decision |
| `AGENTS.md`, `CLAUDE.md`, `.agents/skills/architect-review/SKILL.md`, `.agents/skills/code-reviewer/SKILL.md`, `.claude/agents/architect.md`, `implementation.md`, `qa.md` | Edited by the implementer, range text only | "P1 to P10" (or "P1–P10") becomes P12, on one line each. This follows the precedent of Q6 and P10 |
| `.agents/docs/IMPLEMENTATION_PLAN.md` | Edited by the orchestrator | §2 gains P11 and P12; the §3 tracker row |
| `.agents/tasks/QUESTIONS.md` | Edited by the orchestrator | Q8 and Q9, raised and then answered |
| `.agents/tasks/iteration-11/` | New | `ARCHITECT_REVIEW.md`, `QA_REVIEW.md`, `FIXES.md` and this walkthrough |

**What `src/rendering.py` gains:**
* **`RunFinalisation`,** a public frozen dataclass: `persistence_failed: bool`, `total_tokens: int`, `estimated_cost: float`. It is not a pydantic model, because `schemas.py` stays at 27 models.
* **`finalise_run(state, *, supervisor_telemetry: AgentTelemetry | None, rates: Mapping[str, ModelRate]) -> RunFinalisation`.** The signature is as planned (P12). Inside `log_context(run_id=…)`, in order:
  1. append the Supervisor's entry, or log WARNING `Supervisor telemetry unavailable at run end: …`;
  2. `_log_unsaved`: WARNING `Candidate left unsaved at run end: doc_id=… last_state=…` for each unsaved document, in rank order, under `log_context(doc_id=…)`;
  3. `_in_save_order`: sort the saved documents by `_sequence(draft_id)`, never by the ID text, so `_999` sorts before `_1000`;
  4. split the Scout and Supervisor entries with `amortise_shared_telemetry(shared, n)`, where the first saved draft takes the token remainder;
  5. `_render_and_write` for each saved draft;
  6. `aggregate_draft_totals(state.ledger, [], rates)` for the run totals, which include unsaved documents, failed calls, the Scout and the Supervisor.
* **`_render_and_write`** works on one draft:
  * It computes the draft's own entries and its tokens and cost **before** the failure stages, so an unknown model ID raises as it does in Approach 1.
  * The `render` stage resolves the saved draft (`_rendered_attempt`), builds `DraftMetadata` (`_draft_metadata`) and calls `render_draft(..., template_path=state.config.template_path)`.
  * The `persist` stage calls `write_draft_file(content, draft_id, output_dir=result.path.parent)`. It fails if the returned path is not `result.path`.
  * A failure goes to `_record_failure`, which writes a `FailureRecord` with the stage, `doc_id`, the rendered draft's attempt, the type, message, remote detail and traceback. It also logs ERROR `Draft render or write failure: …` with `exc_info`.
  * A success goes to `_log_rendered`, which logs INFO `Draft rendered: draft_id=… path=… doc_id=… tokens=… cost=…`. For an `ERROR` draft it also logs WARNING `Draft rendered with [UNRESOLVED COMPLIANCE ALERT]: …`.
* **`_draft_metadata`** maps fields as Approach 1's `_build_draft_metadata` does:
  * the source fields come from `candidate.update`;
  * `qa_report` comes from the saved draft;
  * `attempts = attempts_used`;
  * `stage_telemetry` is the draft's own entries followed by its share;
  * `unresolved_errors` holds the issues only for `ERROR`;
  * `model_rates_used = dict(rates)`;
  * `approach_name` is left at its default, "Approach 2 (Research Analyst)".

  The compliance banner comes from the unchanged `format_review_notes`; this code never writes the banner text.
* **`_own_seconds` and `_latency_seconds` (P11).** `latency_seconds` is the sum of three parts:
  * the draft's own Writer and QA-Legal durations;
  * its share of the Scout's duration;
  * `max(supervisor.total_duration_seconds − Σ tool_invocations.total_time_seconds, 0) / n`, computed from the **un-amortised** Supervisor telemetry.

`src/telemetry.py`, `src/template_engine.py`, `src/diagnostics.py`, `src/tools.py` and `src/schemas.py` are unchanged.

## 3. TDD record

Before this iteration, `finalise_run` did not exist. Tests that passed on their first run were checked with temporary mutations, each reverted, as the review artefacts record.

| # | Behaviour | Red asserted, and why it failed | Green added |
| :---: | :--- | :--- | :--- |
| 0 | P11 and P12 in the decision records | The docs test with the two new decisions failed twice, on the §8.3 row order and the §8.3 statement | The `SPECIFICATIONS.md` edits |
| 1 | The Supervisor's entry | One entry with no `doc_id` or attempt, or a WARNING and no entry for `None`. Failed with an `ImportError` | `finalise_run`, the entry |
| 2 | Unsaved candidates | One WARNING per unsaved document, in rank order, with its last state and `doc_id` correlation. No warnings were logged | `_log_unsaved` |
| 3 | Render and write | The metadata is mapped from `candidate.update` and the saved draft, rendered with `config.template_path` and written to `saved.path`. No template token remains, and the approach line reads Approach 2 (AC1, AC2). Nothing was rendered or written | Render and write |
| 4 | Per-draft telemetry and cost | `stage_telemetry` = own entries + share. Tokens and cost come from it, within 1e-9 (AC3). The per-draft tokens add up to own + all shared. The first Red was invalid (the fixture's shared total was even), so the fixture was fixed and the test re-run | `_draft_metadata`, `aggregate_draft_totals` per draft |
| 5 | P11 latency | doc-a gets 14 + 3 + 15 = **32.0** s and renders `Time Taken: 32.00s`; the literal sum would be 67. The Supervisor's own time floors at 0. Without Supervisor telemetry, latency is own + Scout. Latency was 0.0 | `_own_seconds`, `_latency_seconds` |
| 6 | Save order | The first draft saved takes the remainder and is written first; `_999` sorts before `_1000`. Rank order was used | `_in_save_order` |
| 7a | The right draft | `{A1 ERROR, A2 PASS}` renders A2; `{A1 WARNING, failed}` renders A1 with 2 attempts | Already met. Checked by using `attempts[0]` and `attempts[-1]`, which failed |
| 7b | Render logs | INFO "Draft rendered:" with its fields and correlation; an `ERROR` at the cap carries the banner and the compliance-alert WARNING. Neither line was logged | `_log_rendered` |
| 8 | Failures | A render failure, a write failure (a directory at `saved.path`) and a broken invariant (no attempt; an unaudited latest draft) are each recorded, logged at ERROR, and the next draft is still written. The exceptions escaped | The two stages and `_record_failure` |
| 8b | Unknown model ID | It raises `ValueError` and is not recorded as a render failure | Already met by computing the cost before the stages. Checked by moving the cost inside the render stage, which then did not raise |
| 9 | Run totals (P12) | `RunFinalisation` covers the whole ledger: a failed Scout entry, an unsaved document, a failed Writer call and the Supervisor (2867 tokens by hand), and also when nothing is saved. `total_tokens` was 0 | `RunFinalisation`, the totals |
| 10 | Nothing else | No INFO line besides "Draft rendered:"; `exit_code` stays `None`; only `ledger` and `failures` change | Already met. Checked by adding a "Run totals" INFO line and by setting `supervisor_summary`; both failed |
| 11 | Fix round 1, O-3 | A draft written anywhere but its allocated path fails the `persist` stage. It reported success | The returned-path check |

**Refactors:**
* `finalise_run` was split into `_log_unsaved` and `_render_and_write`.
* In fix round 1, the unused `_RenderedAttempt.attempt` field was removed (A-1), and the trailing parameters of `_draft_metadata` and `_render_and_write` were made keyword-only (O-1).

## 4. Test results

The orchestrator ran the suite fresh, after this walkthrough was written:

* `uv run pytest -q`: **1068 passed**, 0 failed, 0 errors.
* Tests added by this iteration: **+30** over Iteration 10's 1038.
  * 26 in `test_rendering.py`;
  * 4 more cases of `test_docs_consistency.py::test_document_uses_no_forbidden_term`, one for each new `.md` in `iteration-11/`.
* `uvx ruff check src tests`: **All checks passed!**
* No live test or live command was run. `finalise_run` needs no model, and every file stays inside `tmp_path`.

## 5. Acceptance criteria

| Criterion | Status | Evidence |
| :--- | :---: | :--- |
| Red: Supervisor entry; WARNING and no entry when `None` | ✅ | `test_the_supervisor_gets_one_ledger_entry_…`, `test_with_no_supervisor_telemetry_a_warning_is_logged_and_no_entry_is_added` |
| Red: unfinished candidates at WARNING with their last state | ✅ | `test_each_candidate_left_unsaved_is_logged_at_warning_with_its_last_state_in_rank_order` |
| Red: `DraftMetadata` per saved document in save order (source fields, report, attempts, `stage_telemetry`, cost, tokens, `unresolved_errors`) | ✅ | `test_a_saved_draft_is_rendered_from_its_metadata_…`, `test_each_drafts_stage_telemetry_is_…`, `test_drafts_are_rendered_in_save_order_…`, `test_save_order_reads_the_sequence_number_…`, the banner test |
| Red: totals add up; unsaved tokens appear only in the run total | ✅ | `test_per_draft_tokens_sum_to_…`, `test_the_run_totals_cover_the_whole_ledger_…` |
| Red: rendering through the template to the allocated path; `ERROR` banner and WARNING; INFO "Draft rendered" | ✅ | `test_a_saved_draft_is_rendered_…`, `test_the_draft_is_rendered_with_the_runs_configured_template_…`, `test_each_written_draft_is_logged_at_info_…`, `test_an_error_draft_saved_at_the_cap_carries_the_banner_…` |
| Red: render and persist failures are recorded, logged at ERROR, and the run continues; persistence failure is reported | ✅ | `test_a_render_failure_…`, `test_a_write_failure_…`, `test_a_draft_written_anywhere_but_its_allocated_path_…`, `test_a_saved_document_without_an_audited_latest_draft_…` × 2 |
| Red: run totals, read with P12 | ✅ | Returned in `RunFinalisation`; `test_finalise_run_logs_no_totals_line_…` shows no line is logged and nothing is stored (DM18) |
| Red: the rendered draft is the saved document's `latest_drafted` | ✅ | The two "after an error / a warning and a … revision" tests |
| P11: latency formula | ✅ | The three latency tests (32.0 and 30.0, the zero floor, no Supervisor telemetry) |
| **AC1:** no unresolved template token | ✅ | `_TEMPLATE_TOKEN` finds nothing in a draft rendered with the shipped template |
| **AC2:** `approach_name` renders as `Approach 2 (Research Analyst)` | ✅ | The same test; the field is never passed |
| **AC3:** per-draft cost = `estimate_cost` over its `stage_telemetry`, within 1e-9 | ✅ | `test_each_drafts_tokens_and_cost_are_those_of_its_stage_telemetry` |
| DoD-1 to DoD-6 | ✅ | §4 above; every new function and branch has a test; the docs test passes; this file |

## 6. Decisions and deviations

**Binding decisions applied:**
* **P11** and **P12**, recorded in `IMPLEMENTATION_PLAN.md` §2 and `SPECIFICATIONS.md` §8.3, and propagated to the "P1 to P12" range text.

**Decisions under §1.5:**
* The return type is named `RunFinalisation`.
* The failure helper `_record_failure` is local to `src/rendering.py`, because `src.tools` imports this module. A render or persist `FailureRecord` carries the rendered draft's attempt, or `None` when there is none, and the log context uses the same attempt.
* Log wording is as quoted in §2, on the `src.rendering` logger.
* The P11 helpers are private to `rendering.py`, so `telemetry.py` stays byte-identical to Approach 1.
* The compliance-alert WARNING fires on `status == "ERROR"`. `unresolved_errors` is filled only then, so a second condition could never fire on its own.
* The returned-path check (O-3) runs after the write, so on a mismatch a file is left in the drafts folder under its correct ID name. The failure record names both paths.

**Deviations:**
* **Cost before the failure stages.** The per-draft tokens and cost are computed before the `render` stage, not inside it. This is Approach 1's order in `_persist_builds`, and it keeps `estimate_cost`'s unknown-model `ValueError` from being swallowed as a render failure.
* **The plan's "Run totals" bullet is superseded by P12.** `finalise_run` logs no totals line. The plan's Iteration 11 text is left as written, because this workflow edits only §2 and §3 of the plan.
* **The plan's "§7.8"** means SPECIFICATIONS.md §6.8, as recorded in Iteration 10.

**Notes for later iterations:**
* **Iteration 14** must call `finalise_run` exactly once per run, and must not swallow its `ValueError` for an unpriced model ID. It should test that case after earlier drafts are written.
* **Iteration 16:** in a draft's Agent Tool Usage table, the Scout and Supervisor rows show `None` in the Attempt column. This is the unchanged `format_stage_telemetry` printing `attempt=None`, as in Approach 1. The benchmark parser must accept it.

## 7. Review

Two review rounds were used, after the pre-flight block on Q8 and Q9.

**Round 1.**
* **Architect: CHANGES REQUESTED.**
  * **A-1 (minor):** `_RenderedAttempt.attempt` was set but never read. **Resolved** by removing the field.
  * **O-1 (optional):** make the trailing parameters keyword-only, so `own` and `share` cannot be swapped. **Resolved.**
  * **O-2 (optional):** `SPECIFICATIONS.md` said "as P11, P12 and so on". **Resolved:** it now reads "P13 and so on".
  * **O-3 (optional):** check the path `write_draft_file` returns. **Resolved,** test-first.
* **QA: PASS.**
  * **Q-1:** the implementer's report said the plan was untouched; the plan's P11, P12 and tracker edits are the orchestrator's, as §2 above records.
  * **Q-2:** concurs with A-1.
  * **O-Q1:** mark the plan's "Run totals" bullet as superseded. Not applied: this is a plan edit outside §2 and §3. It is recorded in §6 instead.
  * **O-Q2, O-Q3:** notes for Iterations 14 and 16, recorded in §6.

**Round 2.**
* **Architect: APPROVED,** no findings. One optional item, **O-4**, was not applied: also assert the file left behind by the O-3 case.
* **QA: PASS,** no findings. All four of its mutations of the O-3 check were caught.

No item needed a decision beyond Q8 and Q9.
