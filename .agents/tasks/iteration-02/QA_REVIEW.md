# QA Review — Iteration 2: Reused modules and triaged tests (round 1)

**Reviewer:** QA and Verification Agent · **Date:** 2026-09-29 · **Branch:** `approach-2/implementation` (uncommitted working tree)

## 1. Summary and verdict

**Verdict: PASSED**

Iteration 2 delivers what `IMPLEMENTATION_PLAN.md` §5 promises:
* the eight modules, as verbatim copies apart from the planned removals;
* the triaged tests;
* the harness copy, with `scripted_model_builder` deferred;
* P8's template, and the P7/P8 records.

I ran every check myself. Every number in the implementer's report matches the real output. All four acceptance criteria hold, and so do DoD-1 to DoD-5. DoD-6 is the orchestrator's checkpoint step.

I found no blocker and no major. I report three minor findings, all non-blocking, and two informational notes. Two of the minors need a decision the sources do not settle, so I opened them under "Needs a decision" in `FIXES.md`.

### Commands run and real output

| Command | Real result |
| :--- | :--- |
| `uv run pytest -q` | `317 passed in 28.23s`. It matches the report: 199 from Iteration 1 plus 118 new |
| `uv run pytest -q -p no:cacheprovider`, grepped for `warn` | No warning lines, so the output is clean |
| `uvx ruff check src tests --no-cache` | `All checks passed!` |
| `uv run pytest -m live --collect-only -q` | `no tests collected (317 deselected)`. This was the only live command run |
| `uv run pytest -q -rA` over the nine copied or moved files | `118 passed`. The per-file counts are in §3, AC1 |
| `uvx ruff check src tests --no-cache --select ANN,E402` | 75 ANN findings and 0 E402. By file: `src/mcp_client.py` 9, `tests/support/scripted.py` 21 (all ANN401 on `Any`), `tests/test_integration/test_mcp_client.py` 21, `tests/test_unit/test_template_engine.py` 24. Every one is in code copied verbatim; `src/telemetry.py` and every edited file have none |
| `diff --strip-trailing-cr ../code-orchestration/src/<m>.py src/<m>.py`, for each of the seven copied modules | 0 lines for `costs`, `credentials`, `model_factory`, `diagnostics`, `mcp_client` and `template_engine`. `schemas` shows deletions only; see AC4 |
| `sed -n 165,325p ../code-orchestration/src/orchestrator.py` against `tail -n +15 src/telemetry.py`, CR stripped | 0 lines: `src/telemetry.py` is byte-identical to Approach 1 from its first function on |
| `diff --strip-trailing-cr` for `.agents/templates/draft.md` (P8) | 0 lines. The file is LF, with a final newline |
| Process snapshot (`tasklist`, `python.exe`, `uv.exe`, `fastmcp.exe`) before and after `uv run pytest tests/test_integration` (30 passed) | The two sets are identical, so no subprocess was orphaned. The processes listed belong to the harness's own MCP servers |
| `hse-easy-mock` tools: `list_regulatory_updates`, `get_document_by_id`, `verify_legal_citation`, `get_tdi_service_offerings` | Every field matches `SPECIFICATIONS.md` §6.1 and the `src/schemas.py` substrate models |

I ran nothing inside `../code-orchestration/` or `../mcp-server/`. Every Approach 1 comparison was a read or a `diff`.

## 2. Gate matrix

| Gate | Topic | Status | Notes |
| :--- | :--- | :---: | :--- |
| 1 | Strict TDD | ✅ | **Red steps.** The report gives a Red for each of the eight modules. Seven are `ModuleNotFoundError` on the module itself. The eighth, P7/P8, is two named docs-test failures. **Ordering.** The ordering is sound: `conftest.py` came after `src.credentials`, since it imports `ReasoningSettings`, and `tests/support/` before the telemetry Red, so that Red fails on `src.telemetry` and not on the harness. **Coverage.** The copied modules bring Approach 1's own tests. For `src/telemetry.py` I ran three mutations from a scratchpad plugin: remainder given to the last draft, floor-only shares, and the cap removed. Each was caught, so the private `_share` and `_share_capped` are covered without direct tests. The only weakened test is QA-m1 |
| 2 | Zero-token testing | ✅ | The autouse `_isolate_environment` fixture strips all 14 variables and pins `ReasoningSettings.model_config["env_file"]` to `None`. No `.env` exists, and every settings construction in the tests passes `_env_file=None` or a `tmp_path` file. No test builds an `Agent`. `test_model_factory.py` patches `socket.socket.connect` and `socket.create_connection` to prove that construction opens no socket. `addopts = "-m 'not live'"` holds, and there are no `live` tests yet. `model_builder` is not in play until Iteration 7 |
| 3 | Pydantic v2 contracts | ✅ | All 19 models in `src.schemas` have `extra="ignore"`, which I checked by introspection. `RevisionPayload` and `PipelineRun` are removed from `src` and `tests`, with 0 grep hits. `PipelineExitCode` stays, as the plan requires ("every other Approach 1 model stays as it is for now"); Iteration 4 renames it. The only `dict[str, Any]` in `src` is in verbatim `mcp_client.py` (the `MCPToolExecutionError.result` payload) and in a local of `model_factory.py`. AC4 requires both to stay; see note N2. The substrate drift test passes against the on-disk `../mcp-server/server.py` |
| 4 | Guardrails and attempt cap | n/a in this iteration | |
| 5 | Strands integration and telemetry | ✅ (partial) | `estimate_cost`, `amortise_shared_telemetry` and `aggregate_draft_totals` are moved verbatim, and the cost basis is unchanged, 13 tests. `extract_telemetry` and the ledger arrive in Iterations 6 and 7, so the `get_summary()` key check is n/a in this iteration |
| 6 | No article text for the Supervisor | n/a in this iteration | |
| 7 | Drafts and logging | ✅ (template only) | The template is content-identical to Approach 1's (P8). All 22 `test_template_engine.py` tests pass against this repository's `.agents/templates/draft.md`, through `REAL_TEMPLATE_PATH`, including `test_real_template_renders_with_no_unresolved_placeholders`. The run left nothing in `drafts/` or `logs/`. Logging is n/a until Iteration 3 |
| 8 | Python and subprocess safety | ✅ with a minor finding | 0 E402. `src/telemetry.py` is fully annotated. The MCP session closes and no process is orphaned. `pathlib.Path` is used throughout the new code. The pytest output has no warnings. The 9 ANN gaps in verbatim `src/mcp_client.py` are QA-m3 |

## 3. Acceptance criteria and Definition of Done

| # | Criterion | Status | Evidence |
| :---: | :--- | :---: | :--- |
| AC1 | Every copied test passes, and the per-file counts are recorded | ✅ | `-rA` passes: `test_costs` 4, `test_credentials` 13, `test_diagnostics` 8, `test_model_factory` 8, `test_template_engine` 22, `test_schemas` 20, `test_telemetry` 13, `test_mcp_client` 24, `test_substrate_compatibility` 6, for 118 in total. Each matches the report. The test-function counts equal Approach 1's in every file, except `test_schemas`, which has 21 there and 20 here: one function deleted. Recording the counts in the walkthrough is the orchestrator's step |
| AC2 | `test_substrate_compatibility.py` passes against the live local substrate | ✅ | 6 passed. The test imports `server`, which resolves to `C:\Users\Saksham\Git\poc\AIAgents\mcp-server\server.py`, the on-disk baseline under P7. It calls that server's tools directly and through `server.mcp.call_tool`, in process. The stdio transport is exercised separately, by `test_mcp_client.py` (24 passed). See QA-m2 on the report's wording |
| AC3 | `grep -rn "orchestrator" src tests` finds no import of `src.orchestrator` | ✅ | The only hits are docstrings and comments. An import-pattern grep, `^\s*(from\|import)\s+src\.orchestrator`, returns nothing. `src.agents` is not imported anywhere either |
| AC4 | The copied modules differ from Approach 1's only in import lines; `schemas.py` differs by the two removed models | ✅ | Six modules have a 0-line diff. The `schemas.py` diff is deletions only: `18d17` and `31d29` (the two `__all__` entries), `194,204d191` (`RevisionPayload`), `412,428d398` (`PipelineRun`) and `452d421` (`PipelineRun.model_rebuild()`). `telemetry.py` is Approach 1's `orchestrator.py` lines 165 to 325, byte for byte, below a new docstring and `__all__` |
| DoD-1 | Full suite passes | ✅ | `317 passed`, 0 failures, 0 errors |
| DoD-2 | Lint is clean | ✅ | `All checks passed!` |
| DoD-3 | No live model call | ✅ | See Gate 2. The only external process is the local substrate over stdio |
| DoD-4 | Every new `src/` function is exercised | ✅ | The copied modules come with their original tests. Every function in `telemetry.py`, private helpers included, is exercised and mutation-checked |
| DoD-5 | Docs match code | ✅ | The docs test passes inside the 317. P7 and P8 are pinned in `IMPLEMENTATION_DECISIONS` and appear in both records |
| DoD-6 | Record written | ⏳ | `WALKTHROUGH.md` is the orchestrator's checkpoint step. It is not yet present, which is expected at this stage |

### Triage checks the orchestrator asked for

**`test_schemas.py`: only `RevisionPayload` and `PipelineRun` behaviour was removed.** I compared it line by line with Approach 1's file.
* **`test_revision_payload_structure`** is deleted.
* **The roundtrip test.** Its `RevisionPayload` half is deleted, and its docstring now names `DraftMetadata`.
* **The renamed test,** `test_pipeline_config_and_draft_result_are_typed_contracts`.
  * It keeps every `PipelineConfig` assertion.
  * It keeps the `DraftResult` construction, and now asserts `writer_invocations == 2` directly on the result.
  * It loses the `PipelineRun` assertions. The two non-`PipelineRun` facts those assertions carried are still covered elsewhere: `PERSISTENCE_ERROR == 4` at line 321, and `time_window="past_3_months"` at lines 189 and 226.
* **Imports.** The two imports are gone, and nothing else changed.
* **The rest are kept, as Iteration 4 requires:** `time_window`, `writer_invocations`, `PipelineExitCode` and the `StageTelemetry` stage-literal rejection test (line 384).

**`test_telemetry.py`: the right 13 tests, still meaningful.**
* **Selection.** I parsed Approach 1's `tests/test_integration/test_orchestrator.py` with `ast` and listed every test whose body calls one of the three functions. There are exactly 13, lines 154 to 415, and they are the 13 moved. Approach 1 has no direct `_share` or `_share_capped` test. The two neighbours that were not moved, `test_fresh_agent_per_invocation_reports_per_call_telemetry` and `test_scripted_agent_reports_zero_provider_latency_like_the_real_provider`, call none of the three functions and depend on `src.agents`.
* **Changes.** An AST diff of each moved function and of the `_telemetry` helper shows only one kind of change: a role model-ID constant replaced by its value-equal `FAST_MODEL_ID` or `STRONG_MODEL_ID`. In Approach 1, `SCOPE_PARSER_MODEL_ID` and `SCOUT_MODEL_ID` are `"gpt-5-mini"`, and `WRITER_MODEL_ID` and `QA_LEGAL_MODEL_ID` are `"gpt-5.4"`, at `src/agents.py:71-74`. They equal `src/credentials.py:25-26`. No number, rate or assertion changed.
* **Meaning.** The mutation probe in Gate 1 shows that the tests fail when the arithmetic is wrong.

## 4. Findings by severity

### 🔴 Blocker

None.

### 🟡 Major

None.

### 🟢 Minor

**QA-m1. A cost test is near-tautological after the model-ID repointing** (`tests/test_unit/test_costs.py:33-45`).
* **What it guarded.** `test_default_model_rates_cover_every_worker_model_id` guarded that the four role model IDs in `src.agents` all have a rate: "a model rename that outruns the rate table must fail here".
* **What it checks now.** It checks `{FAST_MODEL_ID, STRONG_MODEL_ID} <= set(DEFAULT_MODEL_RATES)`. But `DEFAULT_MODEL_RATES` is keyed by those two constants (`src/costs.py:32-40`), so the subset check cannot fail on a rename. The rate-positivity assertions still bite.
* **Why it is not a defect.** The repointing was forced, because `src.agents` does not exist until Iteration 6, and it preserves every value.
* **The risk.** Iteration 6 might forget to restore the guard. The same applies to `TEST_RATES` in `tests/support/scripted.py:496-499` and to the constants in `test_telemetry.py`.
* **Fix:** see `FIXES.md`.

**QA-m2. The report's AC2 wording** says the drift test ran "against local hse-easy-mock over stdio".
* **What actually happens.** The test imports the on-disk `server.py` in process; it does not use stdio.
* **What still holds.** AC2 is met either way, since the local substrate is used.
* **Fix.** The walkthrough should state it accurately, so a later reader does not rely on the drift test for transport coverage. That coverage comes from `test_mcp_client.py`.

**QA-m3. There are 9 annotation gaps in verbatim `src/mcp_client.py`**, at lines 77, 89, 105, 110, 114 (four findings), and 117.
* **The conflict.** AGENTS.md Rule 7 and Gate 8 require complete annotations, while AC4 requires the module to stay identical to Approach 1's.
* **Why it is not a defect here.** Iteration 2 is right to follow AC4.
* **The open question.** No later iteration is scheduled to touch the file, so the gap would persist indefinitely. It is opened as a decision.

### Informational (no action)

**N1. The P7 baseline is now committed.**
* **What changed.** `../code-orchestration/` is at `1734096`, one commit after the `3b123e4` that Q1 and Q3 cite, and `../mcp-server/` is at `1ac6a55`.
* **The trees.** Both working trees have no tracked modifications. The only untracked entries are Approach 1's drafts and logs, and `Claude outputs/` in the server.
* **The effect.** The on-disk baseline that every AC4 diff above compared against is therefore identical to those two commits.
* **Suggestion.** Recording both SHAs in the walkthrough, as provenance, costs nothing and makes future drift visible. P7 itself is unaffected.

**N2. The two `dict[str, Any]` uses** in `src/mcp_client.py` and `src/model_factory.py` are verbatim Approach 1 code.
* **`mcp_client.py`.** Its use is the raw MCP tool-result payload carried on an exception.
* **`model_factory.py`.** Its use is a local that holds provider parameters.
* **Verdict.** Neither is a model contract crossing a boundary in the sense of Rule 1, and AC4 requires both to stay. It is noted only for the architect's awareness.

**Test-count note for the orchestrator.** `test_document_uses_no_forbidden_term` is parametrized over every Markdown file in the repository, task records included. The review files written in this stage, this one, `FIXES.md` and the architect's, therefore raise the suite count above 317. Re-count at the checkpoint.

## 5. Forward notes, verified

The implementer's forward notes are accurate:
* `conftest.py` lacks `HSE_MODEL_SUPERVISOR_REASONING_EFFORT`, which Iteration 4 must add alongside `ReasoningSettings.supervisor`.
* `scripted.VALID_SCOPE_ARGS` still carries `time_window`.
* `scripted_model_builder` and its `ModelBuilder` import are the only deferred helpers; Iteration 7 restores them.
* The three `StageTelemetry.stage` tests that Iteration 4's narrowing will break are the ones named in the report.

---

# QA Review — Iteration 2, round 2 (re-review after fix round 1)

**Reviewer:** QA and Verification Agent · **Date:** 2026-09-29 · **Branch:** `approach-2/implementation` (uncommitted working tree)

## R2.1 Verdict

**Verdict: PASSED**

Every round-1 item is resolved or has an accepted disposition. The fix round and the orchestrator's edits change only wording and pins; no `src/` file changed. I re-ran every check myself, and the real numbers match the implementer's fix-round report. There is no new blocker, major or minor. One informational forward note is below, as N3; it concurs with the architect's A4.

### Commands run and real output (round 2)

| Command | Real result |
| :--- | :--- |
| `uv run pytest -q` | `320 passed in 27.78s`. It matches the report's 320 |
| `uvx ruff check src tests --no-cache` | `All checks passed!`. It matches the report |
| `uv run pytest -m live --collect-only -q` | `no tests collected (320 deselected)`. This was the only live command run |
| The 317 to 320 delta | Exactly three new `test_document_uses_no_forbidden_term[...]` cases, for `iteration-02/ARCHITECT_REVIEW.md`, `FIXES.md` and `QA_REVIEW.md`. The P9 pin adds no test function. This matches the round-1 count note |
| `diff --strip-trailing-cr` against Approach 1, for the six verbatim modules and `draft.md` | 0 lines each. `src/mcp_client.py` is still verbatim, as P9 requires until Iteration 7 |
| The `schemas.py` diff, `telemetry.py` against `orchestrator.py` lines 165 to 325, and the AC3 import grep | Unchanged from round 1. `schemas.py` shows the same five deletion hunks, `telemetry.py` differs by 0 lines, and the grep finds 0 import hits |
| Process snapshot (`python`, `uv`, `fastmcp`) before and after `uv run pytest tests/test_integration` (30 passed) | Identical sets, 22 entries each, so nothing was orphaned |
| Baseline SHAs | `../code-orchestration/` is at `1734096` and `../mcp-server/` at `1ac6a55`, with no tracked modifications. Unchanged since round 1 (N1, A3) |

### The P9 pin catches drift (mutation probe)

The probe is a scratchpad pytest plugin that wraps `test_docs_consistency._read` and mutates the text it returns, so no repository file is touched. Run against `tests/test_unit/test_docs_consistency.py` (186 tests):

| Probe | Result | Failing test or tests |
| :--- | :--- | :--- |
| None (control) | 186 passed | none |
| The P9 statement in SPECIFICATIONS §8.3 is reworded | 1 failed | `…open_with_the_same_statement_in_both_records[SPECIFICATIONS.md §8.3]`, `['P9']` |
| The P9 statement in IMPLEMENTATION_PLAN §2 is reworded | 1 failed | `…[IMPLEMENTATION_PLAN.md §2]`, `['P9']` |
| The P9 row in §8.3 is deleted | 2 failed, 184 passed | `test_specification_records_every_implementation_decision_in_order`, and the §8.3 parametrization. This reproduces the implementer's claimed Red exactly |
| The P9 row in §2 is deleted | 1 failed | `…[IMPLEMENTATION_PLAN.md §2]`, `['P9']` |
| The P8 and P9 rows in §8.3 are swapped | 1 failed | `test_specification_records_every_implementation_decision_in_order` |

The pin is meaningful: it catches rewording, deletion and reordering, in both records.

## R2.2 Round-1 items: disposition

| Item | Round-2 status | Evidence |
| :--- | :--- | :--- |
| **QA-m1** (a cost test is near-tautological after the repointing) | **Accepted: walkthrough disposition** | I accept the orchestrator's plan. It records the item in `WALKTHROUGH.md` under *Deviations*, and as an Iteration 6 carry-forward that restores the role model-ID constants in `test_costs.py`, `scripted.TEST_RATES` and `test_telemetry.py` (see also F1). No Iteration 2 code change is needed |
| **QA-m2** (the AC2 transport wording) | **Accepted: walkthrough disposition** | I accept it. `WALKTHROUGH.md` should say that the drift test imports the on-disk `../mcp-server/server.py` in process (P7), and that `test_mcp_client.py` covers the stdio transport |
| **QA-m3, raised as Q5** (the `mcp_client.py` annotations) | **Resolved** | Q5 was answered A. P9 is in plan §2 (line 119) and in SPECIFICATIONS §8.3, opening with the same statement, and it is pinned in `IMPLEMENTATION_DECISIONS`. The traceability row `P9 \| 7` is present. `src/mcp_client.py` is untouched, with a 0-line diff |
| **Q6, with A1 and A2** (the stale ranges and template wording) | **Resolved** | Plan line 162 reads `draft.md (Approach 1's current template, P8)`. The traceability rows `P7 \| 2, 6, 16`, `P8 \| 2` and `P9 \| 7` are present, at lines 819 to 821. The P1 to P9 range now appears in `AGENTS.md:15`, in both review skills, in SPECIFICATIONS lines 4 and 29 and its §8.3 heading, in `CLAUDE.md:14`, and in `.claude/agents/architect.md:18`, `implementation.md:16` and `qa.md:18`. I checked every harness-file diff: each is the range change only. Three references remain, and each is correct: `IMPLEMENTATION_PLAN.md:263` records what Iteration 1 tested, as the architect advised; the P1-to-P6 traceability row is still true; and `.agents/scratchpad/plan.md:4` is superseded history |
| **A3 and N1** (the baseline at `1734096`) | **Information only** | Unchanged. Record both SHAs in the walkthrough |

## R2.3 Gate matrix and acceptance criteria (round 2)

The gates are unchanged from round 1:
* ✅ for Gates 1, 2, 3 and 8;
* ✅, partial as in round 1, for Gates 5 and 7;
* n/a in this iteration for Gates 4 and 6.

Two points changed:
* **Gate 1.** The fix round's Red is evidenced: the report quotes two named failures, and my probe reproduces them.
* **Gate 8.** The QA-m3 gap is no longer open; P9 now schedules it.

| # | Criterion | Status |
| :---: | :--- | :---: |
| AC1 | Every copied test passes; the per-file counts are recorded | ✅ All 118 are inside the 320. The walkthrough records the counts |
| AC2 | The drift test passes against the live local substrate | ✅ It is inside the 320. The wording point is QA-m2 |
| AC3 | No import of `src.orchestrator` | ✅ |
| AC4 | The copied modules differ only as planned | ✅ |
| DoD-1 to DoD-5 | The suite passes, lint is clean, there is no live call, every function is covered, and the docs match the code | ✅ |
| DoD-6 | The record is written | ⏳ This is the orchestrator's Stage 4 |

**Acceptance criteria: 4 of 4 pass. DoD: the 5 verifiable rows pass, and DoD-6 is pending by design.**

## R2.4 New findings

**None:** no blocker, major or minor.

**N3 (information only; a forward note for Iteration 7).** I concur with the architect's A4.
* **The gap.** The Iteration 7 section of `IMPLEMENTATION_PLAN.md` §5 (line 450 on) does not mention `src/mcp_client.py` or its annotations. P9 reaches Iteration 7 only through §2 and the traceability row `P9 | 7`.
* **What to do.** Carry the P9 work into the Iteration 7 brief, either as the plan edit A4 proposes or as the walkthrough's F6.
* **The check to apply there.** `uvx ruff check src/mcp_client.py --select ANN` returns 0. A diff against Approach 1's file shows annotation-only changes. `test_mcp_client.py` passes unchanged.
* **No `FIXES.md` item.** A4 already carries the fix, so I opened no duplicate item.
