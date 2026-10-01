# QA Review — Iteration 12: SDK spike, fatal stop and logging hooks (round 1)

## 1. Summary and verdict

**Verdict: PASSED.**

I re-ran everything myself:

* **`uv run pytest -q`:** 1105 passed, 0 failed, 0 errors, in 32.13s, with no warnings summary. This matches the implementer's claim of 1068 + 37.
* **`uvx ruff check src tests --no-cache`:** "All checks passed!".
* **`uv run pytest -m live --collect-only -q`:** "no tests collected (1105 deselected)". No live run was made.
* **Flakiness:** the new files and `test_scripted_support.py` passed 41 of 41 in each of 10 consecutive runs. The new files also pass under `-W error`.
* **Mutation testing:** 28 mutants were run on a scratch copy under the session scratchpad. 27 were killed. The one survivor is a minor gap in log-field coverage (F1).

Each of these claims holds against the installed `strands-agents 1.55.1`:

* **SDK basis (§8.4):**
  * `Agent.cancel()` sets `_cancel_signal` (`agent/agent.py:699-734`).
  * `SequentialToolExecutor` calls `agent._observe_cancellation()` before each tool, and answers the tool with "Tool execution cancelled" (`tools/executors/sequential.py:51-58`).
  * The event loop checks the signal again after the tools (`event_loop/event_loop.py:952`, `998`).
* **Executor import path:** `strands.tools.executors` exports both `SequentialToolExecutor` and `ConcurrentToolExecutor`.

## 2. Gate matrix

| Gate | Topic | Status | Notes |
| :--- | :--- | :---: | :--- |
| 1 | Strict TDD | ✅ | The Red steps carry their expected reasons: an ImportError or ModuleNotFoundError of `src.hooks`, "no line logged", or `AssertionError: scout` on 0 model-call lines. Characterisation tests that pass first are each backed by a mutation, and I reproduced those mutations (§4). Every new branch of `src/hooks.py` is killed by a mutant, apart from F1 |
| 2 | Zero-token testing | ✅ | Every new test uses `ScriptedModel`. Hand-built events use `Agent(model=ScriptedModel([]))` and are never invoked. No `live` marker was added, and the live collect-only run collects nothing |
| 3 | Pydantic v2 contracts | n/a in this iteration | No model was added or changed. `_correlation` returns a private `dict[str, str] \| None` that is passed as a log `extra` and never crosses a module boundary |
| 4 | Guardrails and attempt cap | n/a in this iteration | Not touched. AC2 asserts `attempts_used == 1` and `violations == []` on a fatal stop |
| 5 | Strands integration and telemetry | ✅ | Tokens are read from `stop_response.message["metadata"]["usage"]`, and `test_event_loop_metrics_lag_one_call_behind…` pins why. `extract_telemetry` remains the only reader of the metrics summary. `LoggingHooks(<role>)` is prepended in all three build lambdas, and the caller's hooks are kept: M16 to M22 are all killed. The Supervisor builder is Iteration 13 |
| 6 | No article text for the Supervisor | n/a in this iteration | No tool result shape changed. "Tool call completed" logs the status, never the result |
| 7 | Drafts and logging | ✅ | The new D-I events are each asserted by exact message: "Model HTTP call", "Tool call started / completed", "Supervisor turn completed" and "Fatal abort triggered (D-D)". Correlation is asserted through `CorrelationFilter`. F1 is a gap in field coverage |
| 8 | Python and subprocess safety | ✅ | Annotations are complete (`test_annotations[hooks.py]`) and imports are at the top. The new tests take paths from `tmp_path`. No orphaned process was left: every python or uv process running is a harness MCP server started on 2026-09-29 or 2026-09-30, and none dates from today's runs |

## 3. Acceptance criteria and Definition of Done

| # | Criterion | Status | Evidence |
| :--- | :--- | :---: | :--- |
| AC1 | The SDK contract tests pass and are kept permanently, so an SDK change fails loudly | ✅ | `tests/test_unit/test_sdk_contract.py`, 14 of 14 passing; 14 collected, as claimed. Each part was proved able to fail: removing `cancel()` from the stub (M27) fails 3 tests; using the production hook in the control (M25) fails it; dropping `SequentialToolExecutor` from the harness (M26) fails the 3 same-turn tests; running the sequential test concurrently (M24) and the barrier test sequentially (M28) each fail their test |
| AC2 | `writer_tool` on a dying stub transport stops a scripted Supervisor within one tool call | ✅ | `test_writer_tool_on_a_dead_transport_stops_a_scripted_supervisor_within_one_tool_call[next-turn\|same-turn]`. It runs the real `build_tools`, with `OfflineSubstrateSession(fail_listing_with=MCPClientInitializationError)` mapped to `MCPConnectionError` by `src/mcp_client.py:100-167`. It asserts `stop_reason == "cancelled"`, Supervisor `turns_consumed == 1` with trailing turns still scripted, one listing, Writer `turns_consumed == 0`, one attempt, failures `["mcp_session"]`, no violations, and a single ERROR line. Removing `cancel()` (M01) fails both parameters, as does moving the hook to `BeforeToolCallEvent` (M14) |
| Spike | Candidates tried in order, with a control | ✅ | Candidate 1 is a stub that is independent of production (`_CancelOnFatal`). It passed every one of the plan's four assertions in both shapes, so candidates 2 and 3 were correctly not built ("keep the first that passes"). The no-hook control runs both tools and plays the script to its end. The production `FatalStopHook` runs through the same scenario |
| Spike (b) | `AfterModelCallEvent` is once per call; usage is read from the event; tool events fire in the Supervisor and inside a sub-agent; executors | ✅ | Four model-call tests, including the failure path. The tool-event test uses the real `build_tools` and the Scout's substrate and structured-output tools. Two executor tests. The token source is recorded in §8.4 |
| Docs | D-D and §8.4 record D-D.1 | ✅ | D-D's new bold paragraph and §8.4 are pinned by `test_specification_records_the_fatal_stop_the_iteration_12_spike_chose`. The docs and module-structure tests pass, 235 passed |
| DoD-1 | Full suite passes | ✅ | 1105 passed |
| DoD-2 | Lint clean | ✅ | "All checks passed!" |
| DoD-3 | No live model call | ✅ | Gate 2 |
| DoD-4 | Every new `src/` function is exercised | ✅ | 23 production mutants were each killed by an existing test, apart from F1, which is the value of one log field, not an untested branch |
| DoD-5 | Docs match code | ✅ | Docs tests pass |
| DoD-6 | `WALKTHROUGH.md` | n/a | Written at Stage 4 by the orchestrating agent |

**Passed: 10 of 10** applicable rows. DoD-6 is excluded as not yet due.

## 4. Mutation results (scratch copy, reverted after each run)

| Killed (27) | Survived (1) |
| :--- | :--- |
| M01 removing `cancel()`; M02 logging the abort every time; M03 writing the turn line for every role; M04 reading the arguments of sub-agent calls; M05 dropping the dict guard; M06 passing a `None` `doc_id`; M07 logging a `None` duration as 0; M08 and M09 dropping the exception and cancel outcomes; M10 reading the wrong cache key; M11 inverting the unknown/exception test; M12 never advancing the turn counter; M13 dropping the correlation extra; M14 moving the hook to `BeforeToolCallEvent`; M15 logging an unqualified cause; M16 to M18 removing `LoggingHooks` per role; M19 mislabelling the role; M20 to M22 dropping the caller's hooks (M21 and M22 are killed by `test_tools_writer.py` and `test_tools_qa.py`); M24 to M28 test-side mutations of the spike harness, executors, control and stub | M23: hard-coding `tool="writer_tool"` in the fatal abort log line (F1) |

**Flakiness.** The sequential test is deterministic, because the 0.2s hold only gives a concurrent mutant a chance to fail. The concurrent test is gated by `threading.Barrier(2, timeout=5)`:

* If the barrier breaks, the tool raises, and the test fails on the error status rather than hanging. Under M28 it failed in about 8s.
* `order[:2]` is deterministic once both threads have passed the barrier.

There is no flakiness risk beyond a thread-pool stall of more than 5s.

## 5. Findings by severity

* **🔴 Blocker:** none.
* **🟡 Major:** none.
* **🟢 Minor (1):**
  * **F1.** The `tool=` field of "Fatal abort triggered (D-D)" is unpinned; mutant M23 survives. Test-only fix in `FIXES.md`.
* **Optional (2):**
  * **O1.** Note in §8.4 that a same-turn tool skipped by the fatal stop produces no "Tool call started / completed" line. `SequentialToolExecutor` answers it before any hook fires.
  * **O2.** Iteration 13 must build the Supervisor with `SequentialToolExecutor`, which M26 shows the same-turn stop depends on. Its test should fail without it.

## 6. Remediation

See `FIXES.md`, under "QA — round 1". F1 needs one parametrised case, or one extra assertion naming a tool other than `writer_tool`. It needs no production change.

**Verdict: PASS**

---

# QA Review — round 2 (fix-round 1 re-check)

## 1. Summary and verdict

**Verdict: PASSED.**

I re-ran everything myself:

* **`uv run pytest -q`:** 1110 passed, 0 failed, 0 errors, in 35.58s, with no warnings summary. This matches the implementer's claim. 1110 is 1105 plus 1 new parameter case of the fatal-abort test, 1 new structure test, and 3 docs forbidden-term cases for the three iteration-12 review files.
* **`uvx ruff check src tests --no-cache`:** "All checks passed!".
* **`uv run pytest -m live --collect-only -q`:** "no tests collected (1110 deselected)". No live run was made.
* **Warnings as errors:** the SDK contract, AC2, docs and structure tests pass under `-W error` (84 passed).

## 2. Round 1 items, re-verified

| Item | Status | Evidence |
| :--- | :---: | :--- |
| QA F1: the `tool=` field of "Fatal abort triggered (D-D)" | ✅ closed | On a scratch copy, I replaced only line 157 of `src/hooks.py` with the literal `"writer_tool"` (a 1-line diff), which is M23. I ran the same file set as round 1: `test_hooks.py`, `test_sdk_contract.py` and the four `test_tools_*.py` files. Round 1 had `288 passed`, with the mutant surviving. Now: `FAILED tests/test_unit/test_hooks.py::test_the_fatal_abort_is_logged_once_at_error_with_its_cause_the_tool_and_the_exit_code[scout_tool-writer_tool]`, `1 failed, 288 passed in 5.83s`. Killed. The scratch copy was deleted afterwards |
| Architect 1: the D-D wording | ✅ closed | `SPECIFICATIONS.md:403` now reads "(during a call it surfaces at the next build; §8.4, Known limit)", which agrees with §8.4's Known limit. No contract changed |
| Architect 2: `src.hooks` does not import `src.tools` | ✅ closed | `test_module_structure.py::test_hooks_does_not_import_tools` passes on the real file. On the scratch copy, I appended each of five mutant imports, the implementer's four and also `from src import tools`. Each one failed the test (`1 failed`), and the clean copy passed |
| Architect 3: unify `AgentRole` | Declined; accepted | It was optional. A shared alias needs a §6 data-model listing edit, which is outside fix-round scope. Not a QA finding |
| QA O1: §8.4 note on skipped tools | ✅ closed | The "Skipped tools" bullet under "Logging hooks (D-I)" matches the SDK behaviour verified in round 1 (`sequential.py:51-58`) |
| QA O2: Iteration 13 forward note | Skipped, as instructed | It stays a forward note. Iteration 13's `build_supervisor_agent` test must fail without `SequentialToolExecutor` |

## 3. Gate matrix

The gates are unchanged from round 1. Fix round 1 changed tests and docs only; `src/` is the same, apart from the files already reviewed.

| Gate | Topic | Status | Notes |
| :--- | :--- | :---: | :--- |
| 1 | Strict TDD | ✅ | The F1 test was shown able to fail against M23. The structure test was shown able to fail against five import mutants |
| 2 | Zero-token testing | ✅ | No live marker was added, and the live collect-only run collects 0 tests |
| 3 | Pydantic v2 contracts | n/a in this iteration | |
| 4 | Guardrails and attempt cap | n/a in this iteration | |
| 5 | Strands integration and telemetry | ✅ | As in round 1 |
| 6 | No article text for the Supervisor | n/a in this iteration | |
| 7 | Drafts and logging | ✅ | Every field of "Fatal abort triggered (D-D)" is now pinned |
| 8 | Python and subprocess safety | ✅ | No orphaned process. Every python, uv or uvx process running is a harness MCP server started on 2026-09-29 or 2026-09-30, and none dates from today (2026-10-01). The scratch copy was removed |

## 4. Acceptance criteria and Definition of Done

| # | Criterion | Status | Evidence |
| :--- | :--- | :---: | :--- |
| AC1 | The SDK contract tests pass and are kept permanently | ✅ | `tests/test_unit/test_sdk_contract.py`: 14 passed |
| AC2 | `writer_tool` on a dying stub transport stops a scripted Supervisor within one tool call | ✅ | `test_writer_tool_on_a_dead_transport_stops_a_scripted_supervisor_within_one_tool_call[next-turn\|same-turn]` passes, including under `-W error` |
| Spike (a) | The candidates were tried in order, with a control | ✅ | Unchanged since round 1 |
| Spike (b) | Model-call, tool-event and executor characterisations | ✅ | Unchanged since round 1 |
| Docs | D-D and §8.4 record D-D.1 | ✅ | The docs tests pass, and the D-D wording is now consistent with §8.4 |
| DoD-1 | Full suite passes | ✅ | 1110 passed |
| DoD-2 | Lint clean | ✅ | "All checks passed!" |
| DoD-3 | No live model call | ✅ | Gate 2 |
| DoD-4 | Every new `src/` function is exercised | ✅ | The round 1 survivor M23 is now killed, so all 23 production mutants are killed |
| DoD-5 | Docs match code | ✅ | The docs tests pass |
| DoD-6 | `WALKTHROUGH.md` | n/a | Written at Stage 4 |

**Passed: 10 of 10** applicable rows.

## 5. Findings by severity

* **🔴 Blocker:** none.
* **🟡 Major:** none.
* **🟢 Minor:** none.

No `FIXES.md` item and no "Needs a decision" item was opened.

**Verdict: PASS**
