# Iteration 12 — SDK spike: fatal stop and logging hooks: walkthrough

**Date:** 2026-10-01 · **Branch:** `approach-2/implementation` · **Plan section:** `IMPLEMENTATION_PLAN.md` §5, Iteration 12

## 1. Overview

This iteration answers the two SDK questions left open by D-D and D-I. Both are tested against the installed `strands-agents 1.55.1`, and the answers are built into the new module `src/hooks.py`.

* **Fatal stop (D-D.1): candidate 1, the first one tried, is the mechanism.** An `AfterToolCallEvent` hook calls `Agent.cancel()` once `RunState.fatal_error` is set. It passed every assertion, so candidates 2 and 3 were not built.
  * The Supervisor runs with `SequentialToolExecutor`. When the hook fires, no later tool runs, whether it was requested in the same model turn or the next. The model is not called again, and the call returns normally with `stop_reason="cancelled"`. `fatal_error` stays set.
  * It is built as `FatalStopHook(state)`.
* **Logging hooks (D-I).** `LoggingHooks(role)` writes three events:
  * "Model HTTP call";
  * "Tool call started / completed";
  * "Supervisor turn completed", on the Supervisor only.

  `build_tools` registers a `LoggingHooks` of the matching role on every sub-agent it builds.
* **SDK contract tests.** `tests/test_unit/test_sdk_contract.py` is kept permanently, so an SDK upgrade that changes any of these behaviours fails loudly.

## 2. Files changed

| File | Status | Responsibility |
| :--- | :--- | :--- |
| `src/hooks.py` | New, 178 lines | `AgentRole`, `LoggingHooks`, `FatalStopHook`, and the private helpers `_tool_outcome` and `_format_tokens` |
| `src/tools.py` | Edited, +12 / −6 lines | Each build lambda passes `hooks=(LoggingHooks("<role>"), *hooks)`. The docstrings of `build_tools`' `hooks` argument and of `_fatal_failure` now describe the stop |
| `tests/test_unit/test_sdk_contract.py` | New, 14 tests | The spike: the control and candidate 1 in two shapes, the production hook through the same scenario, `AfterModelCallEvent`, the tool events on the Supervisor and inside a sub-agent, and the two executors |
| `tests/test_unit/test_hooks.py` | New, 21 tests | `LoggingHooks`, `FatalStopHook`, the `build_tools` wiring for each role, and AC2 |
| `tests/support/scripted.py` | Edited | `tool_uses_turn(*calls)`: one model turn requesting several tools, each under its own `toolUseId` |
| `tests/test_unit/test_scripted_support.py` | Edited, +1 test | `tool_uses_turn` |
| `tests/test_unit/test_module_structure.py` | Edited, +1 test | `EXPECTED_MODULES` gains `src.hooks`. `test_hooks_does_not_import_tools` pins the one-way dependency, parsing `src/hooks.py` with `ast` |
| `tests/test_unit/test_docs_consistency.py` | Edited, +1 test | `test_specification_records_the_fatal_stop_the_iteration_12_spike_chose` |
| `.agents/docs/SPECIFICATIONS.md` | Edited by the implementer | D-D: the D-D.1 paragraph replaces "recorded here as D-D.1", and the transport-death wording points at the known limit. §8.4: the spike results replace "*Pending.*" |
| `.agents/docs/IMPLEMENTATION_PLAN.md` | Edited by the orchestrator | The §3 tracker only |
| `.agents/tasks/iteration-12/` | New | `ARCHITECT_REVIEW.md`, `QA_REVIEW.md`, `FIXES.md` and this walkthrough |

**What `src/hooks.py` does:**
* **`AgentRole`** is `Literal["supervisor", "scout", "writer", "qa_legal"]`, the same values as `StageTelemetry.stage`.
* **`LoggingHooks(role)`** registers on `AfterModelCallEvent`, `BeforeToolCallEvent` and `AfterToolCallEvent`. It only reads events: it sets no writable field.
  * **"Model HTTP call"** logs the agent, the stop reason and four token figures. The figures are read from `stop_response.message["metadata"]["usage"]`, never from `event_loop_metrics`. For a failed call it logs `outcome=error:<type>` and no tokens.
  * **"Tool call started" and "Tool call completed"** log the tool and the agent. "Completed" adds the SDK-measured duration (`-` when there is none) and the outcome: the status, plus the exception type or the cancel message when there is one. Neither line logs a tool's input or result, so no article text reaches the log.
  * **"Supervisor turn completed"** is logged on the Supervisor only. It carries the turn number, which counts successful responses only, the stop reason, the tools requested, the tokens and the turn's text.
  * **`doc_id` for Supervisor lines.** For `role == "supervisor"`, the tool events fire outside the wrapper's `log_context`. Their `doc_id` is therefore read from the call's `doc_id` argument and passed as a log `extra`. Sub-agent roles never read their arguments and keep the enclosing context.
* **`FatalStopHook(state)`** registers on `AfterToolCallEvent` only. If `state.fatal_error` is set, it logs ERROR `Fatal abort triggered (D-D): cause=<type> tool=<name> exit_code=2 (MCP_ERROR)`, once, and then calls `event.agent.cancel()`. It reads the state, never the event's exception, and it never changes `fatal_error`.
* **Imports.** The module imports only `strands`, `.diagnostics` and `.schemas`, so `src.tools` can import it without a cycle.

## 3. TDD record

The SDK characterisation tests pass on their first run by nature: they describe the SDK, not new code. Each was shown able to fail with a temporary mutation, reverted afterwards, as the review artifacts record.

| # | Behaviour | Red, or how the test was shown able to fail | Green added |
| :---: | :--- | :--- | :--- |
| 0 | `tool_uses_turn` | `ImportError` | The helper in `tests/support/scripted.py` |
| 1 | Spike (a): control and candidate 1 | Without a hook, the second tool runs and the script is consumed. With candidate 1, the second tool never runs, there is one model turn, `stop_reason="cancelled"`, no exception, and `fatal_error` is still set. Both shapes were tested. Replacing `cancel()` with `pass` failed the candidate tests, and adding the hook to the control failed the control | Test-only harness |
| 2 | `AfterModelCallEvent` | Fires once per call; usage is on the event's message metadata; the metrics lag one call; a failed call has no `stop_response`. Registering twice, or reading usage from the metrics, failed them | — |
| 3 | Tool events | Fire for `scout_tool` on the Supervisor and for `list_regulatory_updates` and `ScoutReport` inside the Scout, through the real `build_tools`. `hooks=()` failed it | — |
| 4 | Executors | Sequential runs tools in order (checked by an order log); the default Concurrent runs them together (checked by `threading.Barrier(2, timeout=5)`). Swapping the executors failed both | — |
| 5 | "Model HTTP call" | `ModuleNotFoundError: src.hooks` | `LoggingHooks._after_model_call`; `src.hooks` added to `EXPECTED_MODULES` |
| 6 | "Tool call started / completed" | No line was logged (5 tests). A later non-dict-input test was checked by removing the dict guard | `_before_tool_call`, `_after_tool_call`, `_correlation`, `_tool_outcome` |
| 7 | "Supervisor turn completed" | The two Supervisor tests had no line. The three sub-agent tests were checked with an `if True:` role mutation | `_log_supervisor_turn` |
| 8 | `FatalStopHook` | `ImportError`. Removing the once-only guard failed "logged once" | `FatalStopHook` |
| 9 | `build_tools` wiring | `AssertionError: scout` (no model-call lines). Removing the hook from each lambda in turn failed with that lambda's role | `hooks=(LoggingHooks("<role>"), *hooks)` in the three lambdas |
| 10 | AC2 | Checked by removing `FatalStopHook`: `'end_turn' == 'cancelled'` | — |
| 11 | SPECIFICATIONS D-D.1 and §8.4 | The new docs test failed while "recorded here as D-D.1" and "*Pending.*" remained | The two spec edits |
| 12 | Fix round 1, F1 | The fatal-abort test is parametrized over the recording tool. Hard-coding `"writer_tool"` failed the `scout_tool` case | Test only |
| 13 | Fix round 1, architect 2 | Four mutant imports of `src.tools` into `src/hooks.py` each failed `test_hooks_does_not_import_tools` | Test only |

## 4. Test results

The orchestrator ran the suite fresh, after this walkthrough was written:

* `uv run pytest -q`: **1111 passed**, 0 failed, 0 errors.
* This iteration adds **+43** tests over Iteration 11's 1068:
  * 14 in `test_sdk_contract.py` and 21 in `test_hooks.py`;
  * 1 each in `test_scripted_support.py` and `test_module_structure.py`;
  * 1 `test_annotations.py` case for the new `src/hooks.py`;
  * in `test_docs_consistency.py`, 1 new test, plus 4 forbidden-term cases, one per new `.md` in `iteration-12/`.
* `uvx ruff check src tests`: **All checks passed!**
* Run ten times, the new test files were stable (QA, round 1).
* No live test or live command was run. Every model is a `ScriptedModel` over an `OfflineSubstrateSession`.

## 5. Acceptance criteria

| Criterion | Status | Evidence |
| :--- | :---: | :--- |
| Spike (a): the candidates tried in order, keeping the first that passes every assertion | ✅ | Candidate 1 passes `test_candidate_1_an_after_tool_call_hook_calling_cancel_stops_the_supervisor[next-turn, same-turn]`: the second tool never runs, the model is not called again, there is no exception (`stop_reason="cancelled"`), and `fatal_error` is still set. The control `test_without_a_stop_hook_…` shows the scenario is meaningful |
| Spike (a): the mechanism and evidence recorded in D-D and §8.4 as D-D.1 | ✅ | The `SPECIFICATIONS.md` edits, pinned by `test_specification_records_the_fatal_stop_the_iteration_12_spike_chose` |
| Spike (b): `AfterModelCallEvent` once per call, with stop reason and usage readable, and the source used recorded | ✅ | The four `test_after_model_call_…` and `test_event_loop_metrics_lag_…` tests. The usage source is recorded in §8.4 |
| Spike (b): tool events for the Supervisor's tools and for the MCP tools inside a sub-agent | ✅ | `test_tool_call_events_fire_for_the_supervisors_tools_and_for_the_mcp_tools_inside_a_sub_agent` |
| Spike (b): `SequentialToolExecutor` runs tools sequentially, the default concurrently | ✅ | The two executor tests |
| `LoggingHooks(role)` writes the three events; `FatalStopHook(state)`; `build_tools` passes `LoggingHooks(<role>)` to every sub-agent | ✅ | `test_hooks.py`, including `test_every_sub_agent_a_tool_builds_logs_its_model_and_tool_calls_under_its_role` |
| **AC1:** the SDK contract tests pass and are kept permanently | ✅ | `tests/test_unit/test_sdk_contract.py`, 14 tests |
| **AC2:** `writer_tool` on a dying stub transport stops a scripted Supervisor within one tool call | ✅ | `test_writer_tool_on_a_dead_transport_stops_a_scripted_supervisor_within_one_tool_call[next-turn, same-turn]`: `stop_reason="cancelled"`, one Supervisor turn, one listing, the Writer never called, failures `["mcp_session"]`, an `MCPConnectionError` in the fatal slot, and the "Fatal abort triggered" ERROR |
| DoD-1 to DoD-6 | ✅ | §4 above; every new function and branch has a test; the docs test passes; this file |

## 6. Decisions and deviations

**Decisions (§1.5):**
* **Log wording.** All lines are INFO, except the fatal abort at ERROR:
  * `Model HTTP call: agent=… stop_reason=… input_tokens=… cache_read_tokens=… output_tokens=… total_tokens=…`, or `… outcome=error:<type>`;
  * `Tool call started: tool=… agent=…`;
  * `Tool call completed: tool=… agent=… duration=… outcome=…`;
  * `Supervisor turn completed: turn=… stop_reason=… tools_requested=[…] <tokens> text=<repr>`;
  * `Fatal abort triggered (D-D): cause=… tool=… exit_code=2 (MCP_ERROR)`.
* **Where `doc_id` goes.** It travels in the correlation header, not in the message. Supervisor lines read it from the call's `doc_id` argument; sub-agent lines inherit the wrapper's context.
* **The fatal abort is logged by `FatalStopHook`, once per instance.** It is the only component that knows both the cause and the tool. `cancel()` is called on every completed tool call while the slot is set.
* **The Supervisor's turn counter** counts successful model responses only.
* **Not taken (architect 3, optional):** a shared alias for `AgentRole` and `StageTelemetry.stage`. It would make `src/schemas.py` differ from the `SPECIFICATIONS.md` §6 listing, or need a data-model edit.

**Deviations from the plan, and limits found:**
* **The usage source.** The plan says to read usage from `agent.event_loop_metrics` if it is not on the event. It is on the event, and inside the hook the metrics lag one call, so the fallback is not used; §8.4 records why.
* **Known limit.** A transport that dies *during* a sub-agent's MCP call is returned to that sub-agent as an error tool result, because Strands' MCP client catches it. The run stops at the next sub-agent build, when listing the tools raises `MCPConnectionError`, as in Approach 1. D-D's wording and §8.4 now say so.
* **Skipped tools.** A same-turn tool that the stop skips has no "Tool call started / completed" line. The SDK answers it before any tool hook fires. §8.4 records this.
* **Not used:** two other SDK stop paths in 1.55.1, `AfterToolsEvent.end_turn` and `BeforeToolsEvent.cancel`. They are not D-D candidates, and candidate 1 passed.

**Forward notes for Iterations 13 and 14:**
* The Supervisor builder must register `hooks=[LoggingHooks("supervisor"), FatalStopHook(state)]` and use `SequentialToolExecutor()`. The same-turn stop, and the tool named in the abort line, depend on that executor, so Iteration 13 should test that the builder uses it.
* After a fatal stop the Supervisor returns `stop_reason="cancelled"`, perhaps with no text. That is `MCP_ERROR`, never `SUPERVISOR_ERROR`, and its metrics are intact.
* Never pass `LoggingHooks` or `FatalStopHook` through `build_tools(hooks=…)`. The first would log every line twice, and the second belongs to the Supervisor only.

## 7. Review

Two rounds were used.

**Round 1.**
* **Architect: APPROVED**, with three optional items:
  1. D-D said transport death surfaces "or during its call". **Resolved**: the wording now points at the known limit.
  2. A structure test that `src.hooks` does not import `src.tools`. **Resolved** with `test_hooks_does_not_import_tools`.
  3. Unify `AgentRole` with `StageTelemetry.stage`. **Not taken**, for the reason in §6.
* **QA: PASS.** Of 28 mutants, 27 were killed.
  * **F1 (minor):** no test pinned which tool the "Fatal abort triggered" line names; a mutant hard-coding `writer_tool` survived. **Resolved** by parametrizing the test over the recording tool.
  * **O1 (optional):** document that skipped same-turn tools have no tool-call lines. **Resolved** in §8.4.
  * **O2:** a forward note for Iteration 13, recorded in §6.

**Round 2.**
* **Architect: APPROVED**, no findings.
* **QA: PASS**, no findings. The F1 mutant now fails the `scout_tool` case, and five mutant imports each fail the structure test.

No item needed a decision.
