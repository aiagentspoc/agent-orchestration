# Iteration 7 — Tool wrapper core and `scout_tool`: walkthrough

**Dates:** 2026-09-29 to 2026-09-30 · **Branch:** `approach-2/implementation` · **Plan section:** `IMPLEMENTATION_PLAN.md` §5, Iteration 7

## 1. Overview

Iteration 7 builds the shared custom-agent-tool pipeline (D-A) and the first tool on it.
* **`build_tools(state, …)` returns the Supervisor's four tools.** Each has its exact §7.1 description and §6.4 input schema, and returns a `ToolResult(...).for_supervisor()` string.
* **`scout_tool` is complete.**
  1. It checks its guardrails through `check_scout`.
  2. It runs a fresh Scout through a private `_invoke_sub_agent` helper.
  3. On success it stores the scope and one `DocumentRecord` per candidate, in the Scout's order.
  4. It writes a ledger entry on every call, success or failure.
  5. It sorts failures into recoverable and fatal (D-D, recording only).
  6. It logs the D-I events, with `run_id` on every line.
* **`writer_tool`, `qa_tool` and `save_draft`** have their final names, signatures and descriptions. Their bodies raise `NotImplementedError` until Iterations 8 to 10.

Two carried items land here too:
* **P9:** the 9 missing annotations are added to `src/mcp_client.py`, and nothing else changes in it.
* **F5:** `ModelBuilder` moves to `src/model_factory.py`, and the scripted model builders are restored in the test harness.

## 2. Files changed

| File | Status | Responsibility |
| :--- | :--- | :--- |
| `src/tools.py` | New, 436 lines | See below |
| `src/mcp_client.py` | Edited (P9) | Annotations only: `-> None` on `__init__`, `start`, `stop` and `_ensure_connected`; `__enter__ -> "HSEMockMCPClient"`; the three `__exit__` parameters and its return; plus `from types import TracebackType`. `diff --strip-trailing-cr` against Approach 1 shows only these lines |
| `src/model_factory.py` | Edited (F5) | Adds Approach 1's `ModelBuilder` `Protocol`, byte-identical to `../code-orchestration/src/orchestrator.py:104-127`, and exports it |
| `tests/support/scripted.py` | Edited | Adds `scripted_model_builder(fast, strong)`, one model per model ID as in Approach 1. Adds `scripted_model_builder_by_effort(mapping)`, keyed on model ID and effort, which fails on a key the test did not script. `offline_client` now accepts an `OfflineSubstrateSession`. `fail_listing_with` is widened to `BaseException \| None` |
| `tests/test_unit/test_tools_scout.py` | New, 85 tests | The four tool specs; `scout_tool`'s success, refusal, recoverable-failure and fatal-failure paths; telemetry on failure; `run_id` on every line; the AC2 and D-F result checks |
| `tests/test_unit/test_scripted_support.py` | New, 6 tests | The two restored builders |
| `tests/test_unit/test_annotations.py` | New, 13 tests | An AST guard: every function in every `src` module is fully annotated. There is one test per module |
| `tests/test_unit/test_module_structure.py` | Edited | Adds `"src.tools"` |
| `.agents/docs/IMPLEMENTATION_PLAN.md` | Edited by the orchestrator | The §3 tracker only |

**What `src/tools.py` contains:**
* **Tool descriptions.** `SCOUT_TOOL_DESCRIPTION`, `WRITER_TOOL_DESCRIPTION`, `QA_TOOL_DESCRIPTION` and `SAVE_DRAFT_TOOL_DESCRIPTION` hold the §7.1 text, word for word. The tests compare them with the copies already pinned in `test_docs_consistency.py`.
* **Other constants.** `MCP_LAUNCH_COMMAND`, mirroring Approach 1's, and the fatal set `(MCPConnectionError, MCPClientNotConnectedError)`.
* **`SubAgentModels(scout, writer, qa_legal)` and `SubAgentEfforts(scout, writer, qa_legal)`.** Frozen dataclasses. The efforts default to the `agents.py` constants.
* **`build_tools(state, *, client, models, efforts, hooks=()) -> list[AgentTool]`.**
  * `state` is bound by closure.
  * The tools are nested `@tool(name=…, description=…)` functions with no `Args:` docstring, so the Supervisor sees Strands' default `Parameter <name>` descriptions and no text written by this project. Each full `tool_spec` is pinned in a test.
  * `sources` is declared as `list[str]`, as §6.4 and the plan require, so that an unknown source reaches `check_scout` and becomes `invalid_scope` instead of being rejected by the schema before the wrapper runs.
* **`scout_tool`**, entirely inside `log_context(run_id=state.run_id)`:
  1. `check_scout(state, ScoutArgs(...))`. A violation goes to `_refuse`, which appends it to `state.violations`, logs it at WARNING and returns it with `result=None`.
  2. Log "Scope built by the Supervisor".
  3. `_invoke_sub_agent`.
  4. On success, `_record_scout_success` sets `state.scope` and creates the documents. For a duplicate `doc_id`, the first occurrence wins and a WARNING is logged; the report itself is not changed.
  5. Log "Scout result", or "No qualifying updates" when the report is empty.
  6. Return `ToolResult[ScoutReport](result=report, run=state.snapshot()).for_supervisor()`.
* **`_invoke_sub_agent`:**
  1. Log "Sub-agent invocation started", with the role, model and effort.
  2. Build a fresh agent: `build_scout_agent(models.scout, client, hooks=hooks)`. It never passes `tool_names`, so all five tools are attached (P1).
  3. Run it with `run_scout(..., model_id=SCOUT_MODEL_ID, reasoning_effort=efforts.scout)`.
  4. Append `StageTelemetry(stage="scout")`, taken from the output on success. On failure it is read from `agent.event_loop_metrics` through the unchanged `extract_telemetry`, or is a zero-usage entry when no agent was built.
  5. Log "completed" with tokens, duration and the substrate tools used, or classify the failure. Only `Exception` is caught; interrupts propagate.
* **Classifying a failure.** `_fatal_cause` walks the exception chain through `__cause__` and `__context__`, honouring `__suppress_context__` and guarding against cycles. Strands wraps a model error raised after a tool cycle in `EventLoopException`.
  * **Fatal:**
    * `state.fatal_error` is set to the MCP exception itself; the first fatal error is kept;
    * `FailureRecord(stage="mcp_session")`;
    * an ERROR log with `server_dir`, the launch command and the full chain.
  * **Recoverable:**
    * `FailureRecord(stage="scout")`, with the full `RemoteErrorDetail` and the traceback;
    * a WARNING "Recoverable tool failure" with `exc_info`.
  * **Both:** the tool returns a one-line error, `"<tool> failed: <type> <- <type> … (HTTP <code>)"`. It is built from the qualified exception types, never from `str(exc)`, and it never names a next call.

## 3. TDD record

| # | Behaviour | Red |
| :---: | :--- | :--- |
| 1 | P9: every `src` function is annotated | The AST guard failed on `mcp_client.py` only, with exactly the 9 expected gaps |
| 2 | F5: `ModelBuilder` and the scripted builders | `ImportError: cannot import name 'ModelBuilder'` |
| 3 | `build_tools` returns the four tools, with their pinned specs; the three later tools raise `NotImplementedError` | `ModuleNotFoundError: src.tools` |
| 4 | A successful Scout call: scope, documents, ledger, result, logs, all five tools, hooks | 10 tests failed on the placeholder body |
| 5 | Refusals: `scout_already_run` and four `invalid_scope` cases. Each is stored, logged and returned; there is no build and no ledger entry; a corrected scope can retry | 6 tests failed |
| 6 | Recoverable failures: at build, on the first turn, wrapped in `EventLoopException`, and a real `openai.RateLimitError`. A retry builds a fresh agent | 17 tests failed: the exception escaped the tool |
| 7 | Fatal failures: `MCPConnectionError` and `MCPClientNotConnectedError`, at build, on the first turn and wrapped | 13 tests failed (fatal slot `None`, stage `scout`, WARNING not ERROR) |
| 8 | A failed call still records telemetry: zero usage when not built, otherwise from `event_loop_metrics` | 13 tests failed on an empty ledger |
| 11 | A duplicate `doc_id` from the Scout: the first occurrence wins | `0.7 == 0.9`: the later one overwrote it |
| Fix | Interrupts are never caught (Q-2) | On a scratch copy, widening the catch to `BaseException` survived the other 84 tests. The new test fails with `DID NOT RAISE KeyboardInterrupt` |

**Characterisation tests (Q-4).** Three behaviours had no failing-first step, because the code they cover went in with an earlier behaviour:
* **9: `run_id` on every line** of the real `run_YYYYMMDD.log`, at DEBUG, strands lines included.
* **10: the AC2 and D-F checks.**
* **12: classification by the whole exception chain** (implicit `__context__`, `from None`, a cycle).

The four error-result tests in behaviour 7 also passed at once, because the recoverable path already returns the same shape.

Each was shown to catch a regression by breaking the code on purpose and restoring it:
* dropping `run_id` from the context: 2 failures;
* returning the model instead of its string: 15 failures;
* checking only the outer exception type: 4 failures.

**Coverage.** Measured with an ephemeral `uv run --with coverage`, which leaves `pyproject.toml` and `uv.lock` unchanged: `src/tools.py` is at 100% of lines and branches, 135 statements and 20 branches. QA's mutation probes killed 26 of 27. The survivor makes no difference yet: `drafts_saved` is always 0 in this iteration, so Iteration 10 must check a snapshot taken after a save.

## 4. Test results

A fresh run at the checkpoint, after this walkthrough was written:

| Command | Result |
| :--- | :--- |
| `uv run pytest -q` | **850 passed**, 0 failed |
| Tests added by this iteration | 104 code tests: 85 in `test_tools_scout.py`, 6 in `test_scripted_support.py` and 13 in `test_annotations.py`. Plus one reserved-feature docs case per new record under `iteration-07/` |
| `uvx ruff check src tests --no-cache` | `All checks passed!` |
| `uvx ruff check src/mcp_client.py --select ANN` | 0 findings |

## 5. Acceptance criteria

| # | Criterion | Result | Evidence |
| :---: | :--- | :---: | :--- |
| 1 | The tests pass, and every branch of `_invoke_sub_agent` is covered | ✅ | 100% line and branch coverage of `src/tools.py` from its own test file |
| 2 | No `ToolResult` JSON exceeds the `ScoutReport` plus the `RunContext`, checked by key set | ✅ | Every tool call in the file goes through a checker. It requires exactly the top-level keys `{"result","run","error"}` and `run` equal to the snapshot, and `result` must be a whole `ScoutReport` with keys `{"candidates"}`. None of `draft`, `candidate`, `headline`, `article_body` or `executive_summary` may appear as a key at any depth. A real Strands `Agent` test shows that the Supervisor receives exactly the returned string |

Definition of Done:
* **DoD-1** ✅, **DoD-2** ✅, **DoD-5** ✅ and **DoD-6** ✅ (this file).
* **DoD-3** ✅: `ScriptedModel` and `FailingModel` over the real client with an offline session. No network.
* **DoD-4** ✅: see the coverage above.
* **P9** ✅: annotations only, and `test_mcp_client.py` passes unchanged.

## 6. Decisions and deviations

**Decisions (§1.5):**
* **Types.** `SubAgentModels` and `SubAgentEfforts` are frozen dataclasses, not Pydantic models, because only `RunState` may hold arbitrary types.
* **Constants.** The descriptions and `MCP_LAUNCH_COMMAND` are exported `Final` constants in `tools.py`. The launch command is not in `mcp_client.py`, because P9 allows annotations only there.
* **The one-line error.** Its wording is given in §2. Like the guardrail messages, the Supervisor reads it.
* **Duplicate `doc_id`.** The first occurrence wins, with the WARNING "Duplicate Scout candidate ignored".
* **Correlation.** The invocation log lines take `doc_id` and `attempt` from the correlation fields.
* **"Substrate tools used"** leaves out Strands' structured-output tool.
* **Duration** is wall-clock time around the build and the run.
* **A call whose agent was never built** still appends a zero-usage ledger entry, with `model_id` and effort. This follows the plan and D-B, which say a failed call records its telemetry. A zero Scout row can therefore appear in a draft's telemetry table; cost is unaffected.
* **Tests.**
  * `test_tools_scout.py` imports the pinned §7.1 descriptions from `test_docs_consistency.py`, keeping one copy.
  * The AST annotation guard and the builder tests have their own files.

**Deviations from the plan:**
* **Order of steps against D-A.** D-A orders a call as store, then ledger, then log. The plan's helper order is followed instead: the ledger entry and the "completed" log come before `scout_tool` stores the scope and the documents. No state is read in between, and nothing runs concurrently, so the only observable difference is the order of two INFO lines.
* **P9 is done here.** The plan's Iteration 7 section does not list it; it was carried from Iteration 2 (F6) and answer Q5.
* **Behaviours 9, 10 and 12 are characterisation tests** (Q-4, §3).
* **One test calls the tool function directly.** The `invalid_scope` validation-error case (`max_drafts="three"`) does so, because Strands' schema check would reject that value first.
* **A widened harness type.** `OfflineSubstrateSession.fail_listing_with` now accepts `BaseException`, so a test can raise an interrupt during a build.

**Record correction (Q-1).** The implementer's report gave `test_annotations.py` as 12 tests. It has 13, one per `src` module now that `tools.py` exists, which makes 84 + 6 + 13 = 103 before the fix round, and 104 after it.

**Forward notes:**
* **Iteration 8:**
  * Reuse `_invoke_sub_agent`, which already takes `doc_id` and `attempt`, and `_refuse`.
  * Each per-document tool enters `log_context(doc_id=…, attempt=…)` itself, setting both together.
  * Build `AttemptRecord` with `candidate=doc.candidate`, to keep the object's identity.
  * Run `check_writer` before appending the new attempt.
* **Iteration 10:** test a snapshot after a save, so that `drafts_saved` is non-zero (QA's surviving mutant).
* **Iteration 12:**
  * A substrate tool that fails *inside* a sub-agent is turned by Strands into an error tool result, which never reaches the wrapper, so it is not classified as fatal. A dead transport surfaces at the next build. D-D's "during its call" holds only when the exception propagates. Approach 1 behaves the same way. The spike should check this.
* **Iteration 14:**
  * **Exit code.** §6.10 describes `PARSER_ERROR` as "without a valid scope reaching scout_tool". §6.5 and §7.6 give `PARSER_ERROR` whenever `scope is None`. So a run where a valid scope reached `scout_tool` but every Scout call failed exits 3 under §7.6. The pre-flight must settle this.
  * **Scripted builders.** `scripted_model_builder_by_effort` cannot separate QA-Legal from the Supervisor while both are `(gpt-5.4, medium)`.
  * **Logging.** `MCPClient` logs at construction, so the composition root must enter `log_context(run_id)` before it opens the session.

## 7. Review

**Two rounds were used.** Round 1 was interrupted by an API rate limit before either reviewer wrote anything, and was resumed.

| Round | Reviewer | Verdict | Findings | Resolution |
| :---: | :--- | :--- | :--- | :--- |
| 1 | Architect | APPROVED | None. Three observations: the D-A order, the Iteration 12 risk and the cross-module test import. Ruff: 0 in scope, 0 pre-existing. Pyright: 0 errors in `tools.py`, and 7 inherited errors in verbatim Approach 1 code | Recorded in §6 |
| 1 | QA | CHANGES REQUIRED | **Q-1 (blocker, record only):** a wrong per-file count. **Q-2:** interrupts not pinned by a test. **Q-3:** extra blank lines. **Q-4:** characterisation tests not listed | Q-2 and Q-3 were fixed in fix round 1. Q-1 and Q-4 are corrected in this walkthrough |
| 2 | Architect | APPROVED | None | — |
| 2 | QA | PASSED | None. The `BaseException` mutant is killed, and coverage is still 100% | — |
