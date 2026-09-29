# Iteration 5 — Guardrail checks: walkthrough

**Date:** 2026-09-29 · **Branch:** `approach-2/implementation` · **Plan section:** `IMPLEMENTATION_PLAN.md` §5, Iteration 5

## 1. Overview

Iteration 5 implements the D-C rules as four pure functions over `RunState`, in a new `src/guardrails.py`. Every one of the 12 `GuardrailName` values is produced by at least one test.
* **No agents, no I/O.** The functions log nothing and mutate nothing. Storing a violation and logging it at WARNING are left to Iteration 7's tool wrappers.
* **The first failing check wins,** in the order of `SPECIFICATIONS.md` §7.3.
* **Each violation's message** states the rule and any limit, for example "3 of 3 attempts used", and never names a next call.

## 2. Files changed

| File | Status | Responsibility |
| :--- | :--- | :--- |
| `src/guardrails.py` | New, 275 lines | The public surface below, plus private helpers |
| `tests/test_unit/test_guardrails.py` | New, 210 tests | Table-driven refusal and allowed cases for each check; precedence cases; purity over every case, with and without `fatal_error`; the AC1 set test; the rule-8 walk-through |
| `tests/test_unit/test_docs_consistency.py` | Edited | `GUARDRAIL_CHECK_ORDER` is pinned against the §7.3 table and against column 2 of the plan's Iteration 5 table (AC3). `_table_rows` now splits only on unescaped `\|` |
| `tests/test_unit/test_module_structure.py` | Edited | Adds `"src.guardrails"` |
| `.agents/docs/IMPLEMENTATION_PLAN.md` | Edited by the orchestrator | The §3 tracker only |

**The public surface of `src/guardrails.py`:**
* **Tool names:** the constants `SCOUT_TOOL`, `WRITER_TOOL`, `QA_TOOL` and `SAVE_DRAFT_TOOL` hold the §7.1 names, for Iteration 7 to reuse.
* **`ScoutArgs`:** a `TypedDict` with `total=True` and exactly the five §6.4 `scout_tool` arguments: `date_from`, `date_to`, `sources: list[str]`, `sector_constraints` and `max_drafts`.
* **The four checks:**
  * `check_scout(state, raw_scope) -> PipelineScope | GuardrailViolation`;
  * `check_writer(state, doc_id, revise) -> GuardrailViolation | None`;
  * `check_qa(state, doc_id) -> GuardrailViolation | None`;
  * `check_save(state, doc_id) -> GuardrailViolation | None`.
* **Private helpers:**
  * `_violation` builds every violation.
  * `_open_document` runs `not_a_candidate` then `already_saved`, the shared first two checks.
  * `_not_audited` builds the `not_audited` refusal.
  * `_invalid_scope`, `_validation_summary` and `_window_problem` handle the scope.

**How each rule reads the state:**
* **`scout_already_run`:** `state.scope is not None`. Only a successful call sets the scope, so an earlier `invalid_scope` does not count.
* **`invalid_scope`:** `check_scout` first builds `PipelineScope.model_validate({**raw_scope, "context": AgentContext(today=state.context.today)})`.
  * `context` comes last, so the code's value always wins.
  * A pydantic `ValidationError` becomes `invalid_scope`, reported as `loc: msg` pairs with no URL.
  * Then it applies Approach 1's `_validate_scope_bounds` logic:
    * `date.fromisoformat`;
    * a round trip, which rejects the basic form `20260622` and the week form `2026-W26-1`;
    * `date_from > date_to`.
  * Equal dates are allowed.
* **`attempt_limit` and `error_with_attempts_remaining`:** they read `MAX_ATTEMPTS_PER_DOC` through `DocumentRecord.attempts_used` and `attempts_remaining`, never `context.max_attempts_per_doc`.
* **`draft_ceiling`:** it reads `state.config.max_drafts` and counts `drafts_saved` from `documents` through `snapshot()`. It never reads the stored `context.drafts_saved`, `context.max_drafts` or `scope.max_drafts` (DM3).
* **"No draft" on the writer and on save** is reported as `not_audited`. `no_draft` is the QA-only name.

## 3. TDD record

| # | Behaviour | Red |
| :---: | :--- | :--- |
| 1 | The module, the Scout's run-once rule, and a valid scope returned with its context | `ModuleNotFoundError: src.guardrails` |
| 2 | `invalid_scope`: five bad date forms for each field, an inverted window, an unknown source, three wrong types, and a corrected scope allowed after a stored violation | 16 failed: the bad dates came back as a `PipelineScope`, and pydantic errors escaped the check |
| 3 | `check_writer`: 11 refusals, 7 allowed cases, and the cap read from the constant | `ImportError`, then all refusals failed against an allow-everything stub |
| 4 | `check_qa`: 7 refusals, 3 allowed cases | The same pattern |
| 5 | `check_save`: 11 refusals and 11 allowed cases. The allowed cases include PASS and WARNING at attempts 1 to 3, ERROR at 3 of 3, and an earlier audited draft after a failed call. Two source tests: the ceiling trips with `context.drafts_saved` still 0, and `config.max_drafts` is read | `ImportError`, then the refusals and both source tests failed against the stub |
| 6 | Precedence: 8 per-document cases and 2 Scout cases where two checks both fail | The ordered code already existed, so the Red was shown with mutants: the attempt limit moved late, `already_saved` removed, the ceiling first, validation before run-once. Each was killed by 1 to 3 tests |
| 7 | Purity (AC2): Python-mode `model_dump()` before and after, on every case, with and without `fatal_error` | Mutants that store the scope, sync `drafts_saved`, append a violation or reorder attempts were killed |
| 8 | The AC1 set equals `get_args(GuardrailName)` | A mutant relabelling one guardrail was caught |
| 9 | The rule-8 walk-through, as one sequential test with a fork for the "Or instead" row | A mutant reading `attempts[-1]` in place of `latest_drafted` was caught |
| 10 | AC3: the check order in §7.3 and in the plan's table | A genuine Red: an escaped `\|` in the plan's table split a cell. Green: `_table_rows` splits only on unescaped pipes |

**A slip, recorded:** the writer's `already_saved` branch arrived with the shared helper before its own writer test existed. That test was added in behaviour 4, and passed on its first run.

**Fix round 1:**
* **A-m1.** Four pyright errors in the test file. The date test now picks the field explicitly, and one typed list, `_SCOUT_PURITY_INPUTS`, feeds both the purity cases and the AC1 loop. Pyright reports 0 errors.
* **Q-m1.** A new test proves that a Supervisor-sent `context` cannot override the run's. With the merge reversed, the test fails; on the real code it passes.

## 4. Test results

A fresh run at the checkpoint, after this walkthrough was written:

| Command | Result |
| :--- | :--- |
| `uv run pytest -q` | **634 passed**, 0 failed |
| Tests added by this iteration | 210 in `test_guardrails.py`, 4 in the docs test, plus one reserved-feature case per new record under `iteration-05/` |
| `uvx ruff check src tests --no-cache` | `All checks passed!` |
| `uvx pyright src/guardrails.py tests/test_unit/test_guardrails.py` (reviewers) | 0 errors |

## 5. Acceptance criteria

| # | Criterion | Result | Evidence |
| :---: | :--- | :---: | :--- |
| 1 | Each of the 12 guardrails is produced by a test, and the set produced equals `get_args(GuardrailName)` | ✅ | `test_the_cases_produce_every_one_of_the_twelve_guardrails` |
| 2 | No function mutates `RunState` | ✅ | `model_dump()` is compared before and after on every case, with and without `fatal_error`, and on 5 Scout cases. `guardrails.py` has no logging, assignments or appends |
| 3 | The §7.3 check order matches the plan's table | ✅ | `test_specification_states_the_guardrail_check_order` and `test_plan_iteration_5_table_states_the_same_check_order_as_the_specification` |

Definition of Done:
* **DoD-1** ✅, **DoD-2** ✅, **DoD-5** ✅ and **DoD-6** ✅ (this file).
* **DoD-3** ✅: the tests are pure; no model and no substrate.
* **DoD-4** ✅: QA found every statement in `guardrails.py` exercised, and killed 34 of its 36 mutants. The two survivors: one changes nothing, and the other was closed by Q-m1.

## 6. Decisions and deviations

**Decisions (§1.5):**
* **`ScoutArgs` is a `TypedDict` in `guardrails.py`,** not a model in `schemas.py`. The 27-model inventory stays as it is, and no loose dictionary crosses a module boundary.
* **Allowed returns `None`** for the three per-document checks. `check_scout` returns the built `PipelineScope`.
* **Tool-name constants** are named `SCOUT_TOOL`, `WRITER_TOOL` and so on, so they are not confused with the substrate `*_TOOL_NAMES` tuples.
* **Message wording.** These are the texts the Supervisor will read:

  | Guardrail | Message, in part |
  | :--- | :--- |
  | `attempt_limit` | "`<id>`: 3 of 3 attempts used; a document has at most 3 Writer attempts, failed calls included" |
  | `error_with_attempts_remaining` | "… has QA status ERROR with 1 of 3 attempts remaining; ERROR may be saved only when no attempts remain" |
  | `draft_ceiling` | "… 2 of 2 drafts saved (max_drafts 2) …" |
  | `scout_already_run` | "the Scout runs once per run" |
  | `invalid_scope` | "The scope is invalid: date_from '20260622' is not an ISO date; expected YYYY-MM-DD" |

  Every other message states its rule and names the `doc_id`. None names a next call or carries article or candidate text. Rewording any of them later changes what the Supervisor sees.
* **Tests are organised as a table.** A frozen `Case` dataclass is run by `_arrange`, `_call` and `_assert_outcome`. Slots are filled only through `set_draft` and `set_qa_report`.

**Deviations from the plan:**
* **A docs-test helper outside the new file changed.** `_table_rows` in `test_docs_consistency.py` had to learn escaped pipes before AC3 could read the plan's table. All the existing docs tests still pass.
* **Behaviours 6 to 9 had no first-run Red,** because the ordered, pure code already existed. The implementer and QA each showed with targeted mutants that every test catches the defect it guards against.

**A conflict in the specification, resolved toward the normative rule:**
* The "*Or instead*" row of D-C's "How rule 8 plays out" (`SPECIFICATIONS.md:348`) ends "The Supervisor may revise again from A1, **or save A1**". There, A1's report is `ERROR` and one attempt remains, so rule 9 refuses that save. So do §7.3, the decision table, the `save_draft` description the Supervisor sees, and `DESIGN.md`.
* The code implements rule 9. The walk-through asserts `already_audited` for QA, an allowed revision, and `error_with_attempts_remaining` for save. A comment at `tests/test_unit/test_guardrails.py:730-732` cites the row as illustrative.
* **An offer to the user:** reword that row to "…or, once no attempts remain, save A1". If that is done, also reword the test comment.

**Forward notes:**
* **Iteration 7:**
  * `scout_tool` sets `state.scope` only after a successful Scout call; `scout_already_run` depends on it.
  * The tool stores and logs every violation.
  * Reuse `ScoutArgs` and the tool-name constants.
  * Settle what happens when a valid scope's Scout call fails, given §6.10's `PARSER_ERROR` wording.
* **Iteration 8:** `writer_tool` must run `check_writer` **before** appending the new attempt, or `attempt_limit` trips one call early.
* **Iteration 14:** `RunContext.max_drafts` must be built from `PipelineConfig.max_drafts`.
* **Still carried:** the Iteration 4 notes for Iterations 7 to 11, and F1 to F6 from Iteration 2.

## 7. Review

**Two rounds were used.** Round 1 was interrupted once by an API rate limit, before either reviewer wrote anything, and was re-sent.

| Round | Reviewer | Verdict | Findings | Resolution |
| :---: | :--- | :--- | :--- | :--- |
| 1 | Architect | APPROVED WITH RESERVATIONS | **A-m1 (minor):** 4 pyright errors in the test file. Pillar 1, purity, the order and the data sources all hold. Ruff: 0 in scope, 0 pre-existing | Fixed in fix round 1 |
| 1 | QA | PASSED | **Q-m1 (minor):** the "context goes last" ordering was untested. 34 of 36 mutants killed | Fixed in fix round 1 |
| 2 | Architect | APPROVED | None | — |
| 2 | QA | PASSED | None. The context-order mutant is now killed | — |
