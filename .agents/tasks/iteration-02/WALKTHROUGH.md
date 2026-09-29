# Iteration 2 — Reused modules and triaged tests: walkthrough

**Dates:** 2026-09-28 to 2026-09-29 · **Branch:** `approach-2/implementation` · **Plan section:** `IMPLEMENTATION_PLAN.md` §5, Iteration 2

## 1. Overview

Iteration 2 brings Approach 1's reusable modules and their tests into this project, as D-J describes.
* Six modules are copied unchanged. `schemas.py` is copied without `RevisionPayload` and `PipelineRun`.
* The five cost and amortisation functions move from Approach 1's orchestrator into a new `src/telemetry.py`.
* The scripted-model harness and the environment-isolation fixture are copied into `tests/`.
* 118 tests come across, each copied test file serving as the Red for its module.

It also applies three answers from `QUESTIONS.md`:
* **P7 (Q1):** the on-disk sibling trees are the baseline.
* **P8 (Q3):** the draft template is replaced by Approach 1's current one.
* **P9 (Q5):** annotations may be added to `mcp_client.py`, in Iteration 7.

It records P7 to P9 wherever the decision range is cited. No production logic is new: nothing here supervises, calls a model, or decides a route.

**Baseline.** P7 makes the on-disk trees the baseline. During this iteration the user committed both sibling repositories: `../code-orchestration/` is at `1734096` and `../mcp-server/` at `1ac6a55`, and both working trees now match those commits. Every file copied here was checked again against the current on-disk files, and is still identical.

## 2. Files changed

| File | Status | Responsibility |
| :--- | :--- | :--- |
| `src/costs.py`, `src/credentials.py`, `src/model_factory.py`, `src/diagnostics.py`, `src/mcp_client.py`, `src/template_engine.py` | New | Verbatim copies of Approach 1's modules: the three-rate cost model, `.env` credentials and the model IDs, `build_model`, remote-error capture, `HSEMockMCPClient`, and draft IDs and rendering. Identical to Approach 1's files once CRLF is ignored |
| `src/schemas.py` | New | Approach 1's schemas, minus the `RevisionPayload` and `PipelineRun` classes, their two `__all__` entries and `PipelineRun.model_rebuild()`. Every other model is unchanged for now: Iteration 4 amends them |
| `src/telemetry.py` | New | `estimate_cost`, `_share`, `_share_capped`, `amortise_shared_telemetry` and `aggregate_draft_totals`. From line 15 on it is byte-identical to Approach 1's `src/orchestrator.py`, lines 165–325. It adds a module docstring and `__all__` for the three public functions, and imports only `Mapping`, `Sequence` and three schema models |
| `.agents/templates/draft.md` | Replaced (P8) | Now content-identical to Approach 1's current template. It adds `* **Cost Basis:** {model_rates_used}` and an `#### Agent Tool Usage` section with `{stage_telemetry_markdown_table}`. LF endings, final newline kept |
| `tests/conftest.py` | New | Verbatim: the autouse fixture that removes 14 `HSE_*` variables and stops settings from reading `.env` |
| `tests/support/__init__.py`, `tests/support/scripted.py` | New | The scripted-model harness. `scripted_model_builder` and its `src.orchestrator` import are deferred to Iteration 7. `TEST_RATES` is rekeyed, keeping its values (see §6) |
| `tests/test_unit/test_credentials.py`, `test_diagnostics.py`, `test_model_factory.py`, `test_template_engine.py` | New | Verbatim copies |
| `tests/test_integration/test_mcp_client.py`, `test_substrate_compatibility.py` | New | Verbatim copies. The second is the §6.1 drift test |
| `tests/test_unit/test_costs.py` | New | A copy in which the model-ID import and six usage lines point to `src.credentials` instead of `src.agents` (see §6) |
| `tests/test_unit/test_schemas.py` | New | The triaged copy (see §3) |
| `tests/test_unit/test_telemetry.py` | New | The 13 cost and amortisation tests from Approach 1's `test_orchestrator.py`, with their `_telemetry` helper, pointed at `src.telemetry` |
| `tests/test_unit/test_module_structure.py` | Edited | `EXPECTED_MODULES` gains the eight new modules |
| `tests/test_unit/test_docs_consistency.py` | Edited | P7, P8 and P9 added to `IMPLEMENTATION_DECISIONS`; one test renamed to `test_specification_records_every_implementation_decision_in_order`; docstrings say "P1 to P9" |
| `.agents/docs/SPECIFICATIONS.md` | Edited | P7, P8 and P9 rows in §8.3. The heading, line 4 and the contents row say P1 to P9. The template row reads "identical to Approach 1's current template (P8)". Future decisions start at P10 |
| `.agents/docs/IMPLEMENTATION_PLAN.md` | Edited by the orchestrator | The P7, P8 and P9 rows in §2. With the user's approval (Q6): the §4 layout line for the template, and traceability rows for P7, P8 and P9. The §3 tracker |
| `AGENTS.md`, both review skills | Edited | "P1 to P9" |
| `CLAUDE.md`, `.claude/agents/architect.md`, `implementation.md`, `qa.md` | Edited by the orchestrator | "P1 to P9", one line each, under the user's answer to Q6. The implementer declined these as harness files |
| `.agents/tasks/QUESTIONS.md` | Edited | Answers to Q1 (recorded earlier) and Q3 to Q6 |

## 3. TDD record

Each behaviour ran the same way:
1. Copy the test file and add the module to `EXPECTED_MODULES`.
2. Run it and see it fail on the missing module.
3. Copy the module.
4. Run the full suite.

| # | Module | Red | Full suite after Green |
| :---: | :--- | :--- | ---: |
| 1 | `credentials`, then `tests/conftest.py`, which imports `ReasoningSettings` | `ModuleNotFoundError: src.credentials` | 212 |
| 2 | `schemas` minus the two models, with the drift test (whose only `src` import is `src.schemas`) | `ModuleNotFoundError: src.schemas` in both files | 238 |
| 3 | `costs` | `ModuleNotFoundError: src.costs` | 242 |
| 4 | `diagnostics` | `ModuleNotFoundError: src.diagnostics` | 250 |
| 5 | `model_factory` | `ModuleNotFoundError: src.model_factory` | 258 |
| 6 | The P8 template, then `template_engine` | `ModuleNotFoundError: src.template_engine` | 280 |
| 7 | `mcp_client`, against the local substrate | `ModuleNotFoundError: src.mcp_client` | 304 |
| 8 | `telemetry`, with the harness copied first so the Red fails on `src.telemetry` | `ModuleNotFoundError: src.telemetry`, and the module-structure test failed on the same import | 317 |
| 9 | Recording P7 and P8 | Adding them to `IMPLEMENTATION_DECISIONS` failed exactly the two §8.3 tests. The plan-side check already passed | 317 (docs test 183) |
| 10 | Recording P9 (fix round) | Adding P9 failed the same two §8.3 tests: 2 failed, 184 passed | 320 |

**Triage of `test_schemas.py`:** Approach 1 has 21 tests here, and 20 remain.
* **Deleted:** `test_revision_payload_structure`.
* **Cut down:** the `RevisionPayload` half of `test_schema_json_serialization_roundtrip` is gone; the `DraftMetadata` half stays.
* **Renamed:** `test_pipeline_config_and_run_are_typed_contracts` is now `test_pipeline_config_and_draft_result_are_typed_contracts`. Its `PipelineRun` parts are removed; it keeps the `PipelineConfig` asserts and the `DraftResult` construction, now asserting `writer_invocations == 2`.
* **Kept:** the file has no test of behaviour specific to the ScopeParser. The `time_window` tests stay as the `PipelineScope` baseline that Iteration 4 amends.

**Refactor:** `EXPECTED_MODULES` was split over several lines (E501), and the import order in `test_costs.py` was fixed (I001).

## 4. Test results

A fresh run at the checkpoint, after this walkthrough was written:

| Command | Result |
| :--- | :--- |
| `uv run pytest -q` | **321 passed**, 0 failed |
| `uvx ruff check src tests --no-cache` | `All checks passed!` |
| Tests added by this iteration | 118 copied or moved tests, plus the reserved-feature check on this iteration's four new records |

| Copied test file | Tests |
| :--- | ---: |
| `test_costs.py` | 4 |
| `test_credentials.py` | 13 |
| `test_diagnostics.py` | 8 |
| `test_model_factory.py` | 8 |
| `test_template_engine.py` | 22 |
| `test_schemas.py` | 20 |
| `test_telemetry.py` | 13 |
| `test_mcp_client.py` | 24 |
| `test_substrate_compatibility.py` | 6 |
| **Total** | **118** |

**Missing annotations.** An optional `ruff --select ANN` run finds 75 missing annotations, all of them in verbatim copies: `mcp_client.py` 9, `scripted.py` 21, `test_mcp_client.py` 21 and `test_template_engine.py` 24. AC4 requires the copies to stay identical. P9 schedules the 9 in `src/mcp_client.py` for Iteration 7.

## 5. Acceptance criteria

| # | Criterion | Result | Evidence |
| :---: | :--- | :---: | :--- |
| 1 | Every copied test passes; counts recorded per file | ✅ | The table in §4, from my own collection run |
| 2 | `test_substrate_compatibility.py` passes against the local substrate | ✅ | 6 passed. The drift test loads `../mcp-server/server.py` **in process**, not over stdio. The stdio transport is exercised by `test_mcp_client.py` (24 passed) |
| 3 | No import of `src.orchestrator` | ✅ | A grep for `from`/`import` of `src.orchestrator` in `src` and `tests` finds nothing. The word appears only in docstrings and comments. Nothing imports `src.agents` either |
| 4 | Copied modules differ from Approach 1 only in import lines; `schemas.py` only by the two models | ✅ | `diff`, ignoring CRLF, against the current on-disk Approach 1: the six modules are identical, `schemas.py` has deletions only, and `telemetry.py` matches `orchestrator.py` lines 165–325 |

Definition of Done:
* **DoD-1** ✅, **DoD-2** ✅, **DoD-5** ✅ and **DoD-6** ✅ (this file).
* **DoD-3** ✅: no test builds a real model, the model-factory test forbids sockets, and `live` is deselected.
* **DoD-4** ✅: `telemetry.py`'s functions are covered by the 13 moved tests. QA injected three breakages into `_share` and `_share_capped`, and the tests caught each one.

## 6. Decisions and deviations

**Decisions (§1.5):**
* **`scripted.py`.** Only `scripted_model_builder` is deferred; it needs `ModelBuilder`, which Iteration 7 adds. `pipeline_config` is kept, because it needs only `PipelineConfig`.
* **`telemetry.py`** gains a module docstring and `__all__`, as Approach 1's other modules have.
* **Line endings.** All copies use LF.
* **How P7 to P9 are cited.** Their rows cite "`QUESTIONS.md` Q1/Q3/Q5", so they are not confused with the specification's own Q1–Q12.

**Deviations from the plan:**
* **Model IDs, values unchanged (QA-m1).** The plan says to copy `test_costs.py` "as is". But it, `scripted.py` and the moved telemetry tests import the role model IDs from `src.agents`, which arrives only in Iteration 6. They now use `src.credentials`: `FAST_MODEL_ID = "gpt-5-mini"` in place of the ScopeParser and Scout IDs, and `STRONG_MODEL_ID = "gpt-5.4"` in place of the Writer and QA-Legal IDs. `TEST_RATES` goes from four keys to those two. No rate, cost or model value changed.
  * **The cost:** `test_default_model_rates_cover_every_worker_model_id` can no longer catch a renamed role model, because it now checks the credentials constants against themselves. Iteration 6 must point this test, `TEST_RATES` and `test_telemetry.py` back at the role IDs in the new `src/agents.py`.
* **The template was replaced (P8).** This is the one Iteration 2 change that is not a copy of an Approach 1 module or test.
* **Wording outside the plan's file list.** `AGENTS.md`, the review skills, `CLAUDE.md` and the three subagent files were updated to "P1 to P9". The last four were edited under the user's answer to Q6.

**Answers recorded:**
* **Q3 (A)** became P8.
* **Q4 (A):** the prerequisite is met. Approach 1's copy set passed 106 of 106 there, but its full suite had 12 prompt-text failures in `test_agents.py`, and 324 tests rather than the plan's 221.
* **Q5 (A)** became P9.
* **Q6 (A):** the wording updates above.

**Forward notes:**
* **Iteration 4:**
  * **F3.** Add `HSE_MODEL_SUPERVISOR_REASONING_EFFORT` to the variables `tests/conftest.py` isolates.
  * **F4.** Narrowing `StageTelemetry.stage` to drop `scope_parser` breaks three tests whose data uses it: `test_template_engine.py::test_format_stage_telemetry_renders_markdown_table`, and two amortise tests in `test_telemetry.py`. Adapting that data is allowed by §1.5.
  * `scripted.VALID_SCOPE_ARGS` still carries `time_window`.
  * From Iteration 1: QA-m4, and the `.env.example` wording.
* **Iteration 6:**
  * **F1 / QA-m1.** Point the three test files back at the role IDs, as described above.
  * **A3.** Approach 1's commit `1734096` rewrote the Writer and QA-Legal prompts, widened `QA_LEGAL_TOOL_NAMES` and re-pinned the 12 prompt-text tests. The Iteration 6 pre-flight must work out the parity targets and the `test_agents.py` triage from the current tree, not from Q4's "12 stale failures".
  * **F2 (Iteration 6 or 7).** Restore Approach 1's two telemetry tests that need `src.agents`: `test_fresh_agent_per_invocation_reports_per_call_telemetry` (the D20 fresh-agent guard) and `test_scripted_agent_reports_zero_provider_latency_like_the_real_provider`.
* **Iteration 7:**
  * **F5.** Restore `scripted_model_builder`, keyed so that the Supervisor, the Writer and QA-Legal (all `gpt-5.4`) can each be scripted independently.
  * **F6 (A4 / N3).** Apply P9. The plan's Iteration 7 section does not mention it, so it must be in that iteration's brief. The check: `uvx ruff check src/mcp_client.py --select ANN` reports 0; a diff against Approach 1's file shows annotation changes only; and `test_mcp_client.py` passes unchanged.
* **Iteration 16:** the substrate corpus runs to 2026-08-20 (Iteration 0's note).

## 7. Review

**Two rounds were used.**

| Round | Reviewer | Verdict | Findings | Resolution |
| :---: | :--- | :--- | :--- | :--- |
| 1 | Architect | APPROVED WITH RESERVATIONS | **A1:** the plan's §4 still called the template "unchanged". **A2:** stale "P1 to P6" in the traceability row and the harness files. **A3:** information, the Approach 1 baseline moved. **F1–F5:** forward notes. Ruff: 0 in scope, 0 pre-existing | A1 and A2 raised as **Q6**; the user chose A and the orchestrator applied it. A3 and F1–F5 are recorded in §6 |
| 1 | QA | PASSED | **QA-m1:** the cost test became near-tautological. **QA-m2:** AC2 ran in process, not over stdio. **QA-m3:** annotations missing in `mcp_client.py`, raised as **Q5**, with Q6 | QA-m1 is a deviation above, with its Iteration 6 note. QA-m2 is corrected in §5. Q5 answered A, so P9 was recorded (fix round, with a Red) |
| 2 | Architect | APPROVED | **A4 (minor):** the plan's Iteration 7 section omits the P9 work | Carried as forward note F6. The orchestrator does not edit iteration sections |
| 2 | QA | PASSED | None. **N3** (information) is the same point as A4. QA probed the P9 pin with five kinds of drift, and all five failed | — |
