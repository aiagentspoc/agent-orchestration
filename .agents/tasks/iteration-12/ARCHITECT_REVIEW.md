# Iteration 12 — Architect review, round 1

**Scope audited:** the uncommitted diff (`git diff`, `git status --short`) and the three new files, `src/hooks.py`, `tests/test_unit/test_sdk_contract.py` and `tests/test_unit/test_hooks.py`. The SDK claims were checked against the installed `strands-agents` 1.55.1 under `.venv`.

**Commands run:** `uv run pytest -q` gave 1105 passed in 33 s. `uvx ruff check src tests --no-cache` gave "All checks passed!". No live command was run (P4).

## 1. Overall verdict

**APPROVED**

There are no blocking findings. Three optional suggestions are listed in §5 and appended to `FIXES.md` under "Architect — round 1", each marked optional.

## 2. Pillar audit

### Pillar 1. An agent owns the flow, within guardrails enforced in code: pass

* `FatalStopHook._after_tool_call` (`src/hooks.py:147-161`) only reads `state.fatal_error`, logs once, and calls `event.agent.cancel()`.
  * It does not set `cancel_tool`, `retry`, `end_turn` or any tool selection.
  * It does not touch `fatal_error`.
  * It does not choose a next step. It stops the run and never reroutes it, which is the D-D requirement.
* `LoggingHooks` (`src/hooks.py:48-125`) only reads its events. No writable event field is assigned anywhere in the module.
* No code in the diff sequences the sub-agents. The spike's scripted "supervisor" in the tests is a `ScriptedModel`, so the model decides the calls.

### Pillar 2. Division of labour, no article text: pass

* Every hook line writes these fields:
  * the tool name;
  * the role;
  * the SDK status;
  * the exception's qualified type, or the hook-set cancel message;
  * the duration;
  * the token figures;
  * on the Supervisor only, its own turn text.
* `tool_use["input"]` is never logged. `_correlation` (`src/hooks.py:113-125`) reads only the Supervisor's `doc_id` argument and never a sub-agent's arguments.
* The Writer's `ArticleDraft` and QA-Legal's `QAReport` structured-output tool calls are therefore logged by name only.
* The Supervisor's turn text is the Supervisor's own output, which is what D-I asks for. D-F keeps article text out of the context it writes from.

### Pillar 3. Custom agent tools: pass

* `LoggingHooks(<role>)` is built inside each `build=` lambda (`src/tools.py:211, 245, 272-274`), so every fresh sub-agent gets a fresh instance (D-G).
* The caller's `hooks` follow the role hook, as the docstring at `src/tools.py:177-179` says.
* No `as_tool`, `delegate`, `preserve_context` or agent-in-`tools=` was introduced.

### Pillar 4. Guardrails and attempt state: not touched by this iteration

The AC2 test confirms that the dead-transport `writer_tool` call still appends its attempt before the build (`attempts_used == 1`) and records no violation.

### Pillar 5. Benchmark parity: pass

Iteration 12 leaves these unchanged:
* prompts;
* models and efforts;
* tool binding (P1);
* template and cost basis;
* the sub-agent executor.

Approach 1's sub-agents (`../code-orchestration/src/agents.py:618, 687, 746, 837`) are built with no hooks and the default executor. Approach 2's are now built with an observation-only hook and still the default executor, so nothing the models see changes.

§8.4's "the sub-agents keep [`ConcurrentToolExecutor`]" matches Approach 1. D-H's `SequentialToolExecutor` binds the Supervisor, which Iteration 13 builds.

### Pillar 6. Substrate isolation and lifecycle (D-D): pass

* The mechanism is settled and evidenced. I checked each SDK claim in §8.4 against 1.55.1:
  * `Agent.cancel()` sets `_cancel_signal` (`strands/agent/agent.py:699-734`).
  * `SequentialToolExecutor._execute` checks `agent._observe_cancellation()` before each tool, and answers with "Tool execution cancelled" (`strands/tools/executors/sequential.py:50-59`).
  * The event loop returns `EventLoopStopEvent("cancelled", …)` before recursing into the next model call (`strands/event_loop/event_loop.py:998-1005`).
  * The signal is cleared when an invocation completes (the `cancel_signal` property docstring).
* The "known limit" is accurate. `MCPClient.call_tool_async` catches every in-flight exception and returns an error result (`strands/tools/mcp/mcp_client.py:1117-1138`). Even its "session not running" raise happens inside the tool's stream, which the executor turns into an error result.
* `src/` makes no direct substrate call (`client.get_document_by_id` and the like appear nowhere in `src/tools.py` or `src/agents.py`). The only fatal path is therefore tool resolution at the next build, and AC2 exercises exactly that path.
* AC2 holds in both shapes:
  * `stop_reason == "cancelled"`;
  * `turns_consumed == 1`;
  * one listing;
  * the Writer is never called;
  * failures are `["mcp_session"]`;
  * there are no violations;
  * `fatal_error` is an `MCPConnectionError`;
  * one ERROR line.

### Pillar 7. Rendering, telemetry and logging (D-I): pass

* **Hook events.** The four hook events of the D-I catalogue are produced and asserted by tests, with their key fields:
  * "Model HTTP call";
  * "Tool call started / completed";
  * "Supervisor turn completed";
  * "Fatal abort triggered (D-D)", with cause, tool and exit code.
* **Correlation.** Correlation goes through `CorrelationFilter`, which keeps an `extra=` field (`src/logging_setup.py:104-119`). Sub-agent lines inherit the wrapper's `log_context`, and Supervisor lines take `doc_id` from the call.
* **`src.hooks` logger.** It is under the routed `src` logger (`src/logging_setup.py:39`).
* **Reading metrics.**
  * Rule 6 is preserved: `src/hooks.py` never reads `event_loop_metrics` or `get_summary()`.
  * The one-call lag that justifies reading usage from the event is pinned by `test_event_loop_metrics_lag_one_call_behind_the_after_model_call_event`.

### Pillar 8. Code quality and Python conventions: pass

* Imports are at the top of the file, grouped stdlib, then third-party, then local, with zero E402.
* `src/hooks.py` imports only `strands.hooks`, `strands.types.event_loop`, `strands.types.tools`, `.diagnostics` and `.schemas`. **It does not import `src.tools`.** The dependency runs one way, `tools → hooks`, with no cycle.
* Every function and method is fully annotated, `test_annotations[hooks.py]` passes, and `__all__` is declared.
* The SDK types used are public: `HookProvider`, the event classes, `AfterModelCallEvent.ModelStopResponse`, `Usage` and `ToolUse`.
* There is no dead code, and the docstrings are honest.
* Every branch is tested:
  * the no-usage response;
  * the response-less event with and without an exception;
  * the non-dict input;
  * the sub-agent role skipping its arguments;
  * the cancel-message and exception outcomes;
  * the empty and set fatal slot;
  * the once-only log.

## 3. Code review findings

There are no convention, typing or hygiene defects. The minor observations below are optional.

* **`src/hooks.py:34`.** `AgentRole` repeats the inline `Literal["supervisor", "scout", "writer", "qa_legal"]` of `StageTelemetry.stage` (`src/schemas.py:327`). The two can drift. This is optional; see `FIXES.md`.
* **`tests/support/scripted.py:72-96`.** `tool_uses_turn` has no `cache_read_input_tokens` parameter, unlike `tool_use_turn`. No test needs it today, so no change is requested.

## 4. Anti-patterns and risks

* **No autonomy leak and no parity drift.** No article text reaches the Supervisor or the log through the hooks.
* **Risk handed to Iteration 13.**
  * **Same-turn stop needs Sequential.** D-D.1's same-turn guarantee depends on the Supervisor being built with `SequentialToolExecutor`. Under the default concurrent executor, a same-turn second tool may already be running when `cancel()` is called.
  * **The logged tool name has the same dependency.** The "tool" field of "Fatal abort triggered" is the name of the first Supervisor tool to complete after the slot is set. That is the tool that set the slot only under sequential execution.
  * **Pinned by tests.** Iteration 13's planned test that `build_supervisor_agent` uses `SequentialToolExecutor` is therefore load-bearing for D-D.
* **Risk handed to Iteration 13 and 14.** After a fatal stop the Supervisor returns `stop_reason="cancelled"`, and its last message is the tool-use turn, not a text summary. `run_supervisor` and the composition root must not treat that as a provider failure (exit 6) or require summary text. The implementer's forward notes record this.
* **Observability gap (by SDK design, acceptable).** A same-turn tool cancelled by the executor fires no `BeforeToolCallEvent` or `AfterToolCallEvent`, so it gets no "Tool call started / completed" line. The path stays traceable through "Supervisor turn completed" (`tools_requested=[writer_tool, qa_tool]`) and the "Fatal abort triggered" line.

## 5. Remediation directives (all optional)

1. **Optional. `.agents/docs/SPECIFICATIONS.md:403` (D-D).** The pre-existing sentence "Transport death surfaces when a fresh sub-agent's tools are resolved, or during its call" is now qualified by §8.4's verified known limit. A death during the call is returned to the sub-agent as an error tool result and becomes fatal only at the next build. Consider appending "(during a call it surfaces at the next build; §8.4, Known limit)" so D-D does not overstate the behaviour. This changes wording only and no contract.
2. **Optional. `src/hooks.py:34`.** Consider defining one shared `AgentRole` alias, for example in `src/schemas.py`, and using it for both `StageTelemetry.stage` and `LoggingHooks(role)`. Only do so if no `test_schemas` or docs test pins the inline literal; otherwise leave it.
3. **Optional. `tests/test_unit/test_module_structure.py`.** Consider a test asserting that `src.hooks` does not import `src.tools`. The test would pin the one-way dependency the forward notes rely on: hooks must stay importable by `src/supervisor.py` without pulling in the tools.

---

# Iteration 12 — Architect review, round 2

**Scope audited:** the fix-round-1 changes, which are `tests/test_unit/test_hooks.py`, `tests/test_unit/test_module_structure.py` and `.agents/docs/SPECIFICATIONS.md` (D-D and §8.4). I also re-read `src/hooks.py` and the `src/tools.py` diff to confirm that production code is unchanged since round 1.

**Commands run:** `uv run pytest -q` gave 1110 passed in 34.7 s. `uvx ruff check src tests --no-cache` gave "All checks passed!". No live command was run (P4).

## 1. Overall verdict

**APPROVED**

## 2. Pillar audit (delta from round 1)

| Pillar | Round 2 status |
| :--- | :--- |
| 1. An agent owns the flow | Pass. The fixes are tests and docs only, and `FatalStopHook` still only stops the run (`src/hooks.py:147-161`). |
| 2. Division of labour | Pass, unchanged. |
| 3. Custom agent tools | Pass, unchanged. Each `build=` lambda still gets a fresh `LoggingHooks(<role>)` (`src/tools.py:211, 245, 272-274`). |
| 4. Guardrails and attempt state | Not touched by this iteration. |
| 5. Benchmark parity | Pass, unchanged. |
| 6. Lifecycle (D-D) | Pass. D-D (`SPECIFICATIONS.md:403`) no longer overstates what happens on transport death, and now agrees with §8.4's Known limit. |
| 7. Logging (D-I) | Pass. The "Fatal abort triggered" `tool=` field is now pinned by a `scout_tool` case. The new "Skipped tools" bullet (`SPECIFICATIONS.md:1060`) matches `strands/tools/executors/sequential.py:50-59`: the cancelled branch `continue`s before `_stream_with_trace`, so neither tool hook fires. |
| 8. Code quality | Pass. `_imported_modules` (`tests/test_unit/test_module_structure.py:55-64`) is fully annotated. It uses `ast.walk`, so it also catches imports inside functions, and it resolves relative imports against `src`. Zero E402. |

## 3. Code review findings

None. Ruff found 0 in-scope findings and 0 pre-existing debt.

## 4. Anti-patterns and risks

No new risks. The round 1 forward risks for Iteration 13 still stand:
- the same-turn stop and the logged tool name both depend on `SequentialToolExecutor`;
- after a fatal stop, `stop_reason="cancelled"` must not be mapped to exit 6.

## 5. Remediation directives

None. I accept the decision to leave Architect 3 (the shared `AgentRole` alias) as it is. The item was optional, and doing it would require editing the §6 data-model listing.
