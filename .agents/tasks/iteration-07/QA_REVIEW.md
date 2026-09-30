# QA Review: Iteration 7, Tool wrapper core and `scout_tool` (Stage 3, round 1)

*QA and verification subagent, 2026-09-30. Criteria: `.agents/skills/code-reviewer/SKILL.md`, `IMPLEMENTATION_PLAN.md` §1.3, §1.4, §2 (P1, P4, P9) and Iteration 7, `SPECIFICATIONS.md` D-A, D-B, D-C, D-D, D-F, D-I, §6.4 to §6.7, §7.1 to §7.3, `DESIGN.md`, `AGENTS.md`, and Approach 1's `src/mcp_client.py`, `src/orchestrator.py` and `tests/support/scripted.py` (read only, never as a working directory).*

## 1. Summary and verdict

**Verdict: CHANGES REQUIRED.** There is one blocker and three minor findings, and no major finding. The blocker is a record fix, not a code fix.

The code is sound, and what was claimed holds, with one exception:
* both acceptance criteria are met, and every bullet of the Red list;
* `src/tools.py` has 100% line and branch coverage from its own test file;
* 25 of 27 mutation probes on `src/tools.py` are killed. One of the two survivors is equivalent in this iteration, and the other shows an untested docstring claim (Q-2);
* the `mcp_client.py` diff against Approach 1 is annotations only (P9);
* no test can reach a model endpoint.

The exception is one per-file count in the implementer's report, which is wrong (Q-1). The findings are Q-1 to Q-4 in §5.

### What I ran myself

| Command | Real result | Claimed | Match |
| :--- | :--- | :--- | :---: |
| `uv run pytest -q` (before any Iteration 7 review file existed) | **845 passed**, 0 failed, 0 errors, 40.01 s | 845 passed | ✅ |
| `uv run pytest -q -W error` (after the architect's two files landed) | **847 passed**; no warning escalated | — | ✅ |
| `uvx ruff check src tests --no-cache` | `All checks passed!` | no findings | ✅ |
| `uvx ruff check src --select ANN --no-cache` | `All checks passed!` | ANN 0 | ✅ |
| `uv run pytest -m live --collect-only -q` | `no tests collected (845 deselected)` | — | ✅ |
| `--collect-only` on `test_tools_scout.py` | 84 | 84 | ✅ |
| `--collect-only` on `test_scripted_support.py` | 6 | 6 | ✅ |
| `--collect-only` on `test_annotations.py` | **13** | **12** | ❌ Q-1 |
| Delta against Iteration 6 | 845 − 742 = 103 = 84 + 6 + 13 | 103 | ✅ |
| `uv run --with coverage coverage run --branch --source=src.tools -m pytest tests/test_unit/test_tools_scout.py` (ephemeral; coverage data kept in my scratchpad) | `src\tools.py 135 0 20 0 100%` | 135 statements, 20 branches, 100% | ✅ |
| `uvx pyright` on `src/tools.py` and the three new test files | 0 errors | 0 errors | ✅ |

The suite count depends on how many documents are in `.agents/tasks/`: `test_document_uses_no_forbidden_term` is parametrised per document. The architect's `ARCHITECT_REVIEW.md` and `FIXES.md` took the count from 845 to 847. This file, and the architect's, add one test each.

`pyproject.toml` and `uv.lock` are unchanged. `git status --short` shows only the files the report lists.

## 2. Gate matrix

| Gate | Topic | Status | Notes |
| :--- | :--- | :---: | :--- |
| 1 | Strict TDD | ✅ | 100% line and branch coverage of `src/tools.py`, and 25 of 27 mutants killed (§4.3). Behaviours 9, 10 and 12 passed on their first run; they were characterised by deliberate breakage, and the record should call them that (Q-4). One docstring invariant is untested (Q-2) |
| 2 | Zero-token testing | ✅ | Every model is a `ScriptedModel` or `FailingModel`. No `build_model` call, no `OpenAIModel`, and no network: the one URL, `fast.example.invalid`, is only an `httpx.Request` label for a constructed `RateLimitError`. The substrate is the real `HSEMockMCPClient` over `OfflineSubstrateSession`. The `_isolate_environment` autouse fixture is active. No live test is collected |
| 3 | Pydantic v2 contracts | ✅ | No new pydantic model. `SubAgentModels` and `SubAgentEfforts` are frozen dataclasses holding run wiring, not §6 data. No `dict[str, Any]` crosses a module boundary: the tools return `str`, and `build_tools` returns `list[AgentTool]` |
| 4 | Guardrails and attempt cap | ✅ for this iteration's two | `scout_already_run` and `invalid_scope` (all four §7.3 cases) are produced through `scout_tool`. Each is stored, logged at WARNING with guardrail, tool, `doc_id` and message, and returned with `result=None`. Checks run before any build. The attempt cap and `already_saved` are Iterations 8 to 10 |
| 5 | Strands integration and telemetry | ✅ | A fresh agent per call (the retry test sees an empty conversation and a second unfiltered listing). One `scout` ledger entry on success and on every failure path. Failure telemetry is read from `event_loop_metrics` through `extract_telemetry`; 1.55.1's `reset_usage_metrics` only appends an invocation, so a fresh agent's accumulated usage survives a raise (§4.4) |
| 6 | No article text for the Supervisor | ✅ | `_CheckedTool` checks every result string in the file: the key set is `{result, run, error}`, `run` equals the snapshot, `result` is `{candidates}`, and no forbidden key appears at any depth. The checker's own negative tests stop it passing vacuously, and a real Strands `Agent` test confirms the checked string is what the Supervisor receives |
| 7 | Drafts and logging | ✅ | Every header line of `run_YYYYMMDD.log` at DEBUG carries `run_id`, `strands` lines included, across a failure, a success and a refusal. The D-I events are asserted with their fields (§4.2). Drafts are n/a in this iteration |
| 8 | Python and subprocess safety | ✅ | P9 annotations landed, and a new AST test holds all 13 `src` modules to full annotation. `pathlib.Path` throughout. Clean output under `-W error`. No orphaned process: the only `uv`, `fastmcp` and `python` processes date from 2026-09-28 and are this harness's MCP servers, launched without `--quiet`, whereas `HSEMockMCPClient` uses `--quiet` |

## 3. Acceptance criteria, Red list and Definition of Done

### 3.1 Acceptance criteria: 2 of 2 met

| # | Criterion | Status | Evidence |
| :---: | :--- | :---: | :--- |
| AC1 | The tests pass, and every branch of `_invoke_sub_agent` is covered | ✅ | 84 of 84 pass. Ephemeral branch coverage gives `src/tools.py` 135 of 135 statements and 20 of 20 branches. Both arms of `except`, of `agent is None` and of `fatal is not None` are exercised: never-built (3 cases), built-then-raised (recoverable and fatal), and success |
| AC2 | No `ToolResult` JSON exceeds its `ScoutReport` plus `RunContext`, checked by key set | ✅ | `_assert_supervisor_view` checks every call's result. `test_a_success_result_is_the_report_and_the_run_context_and_nothing_more` checks level by level against `ScoutReport`, `ScoutCandidate` and `RunContext` `model_fields`. Mutant M18 (§4.3) is equivalent because `drafts_saved` is always 0 here |

### 3.2 Red list: 10 of 10 met

| Bullet | Status | Evidence |
| :--- | :---: | :--- |
| `build_tools` returns the four named tools, with the §6.4 schemas | ✅ | Order is asserted, and each whole `tool_spec` is pinned. The descriptions are compared with `SUPERVISOR_TOOL_DESCRIPTIONS`, which `test_docs_consistency.py` parses out of §7.1 itself |
| `sources` is `list[str]` | ✅ | The schema items are `{"type": "string"}` with no enum. `OSHA` becomes `invalid_scope`. The WALKTHROUGH must record it (the plan asks for this) |
| Success stores the scope, one `DocumentRecord` per candidate in Scout order, and one scout ledger entry; returns the full report and snapshot; logs the four events | ✅ | Non-descending scores keep the Scout's order. The ledger entry carries `SCOUT_MODEL_ID` and the injected effort. The exact returned JSON is asserted. The INFO sequence `Scope built`, `started`, `completed`, `Scout result` is asserted |
| Second call → `scout_already_run`; invalid scope → `invalid_scope`, not a run | ✅ | No listing, no model turn and no ledger entry. `scope` is unchanged. A corrected scope then runs |
| Every violation is logged at WARNING, stored and returned with `result=None` | ✅ | `_assert_refused` checks all three; mutants M7 and M14 are killed |
| An ordinary failure gives a `FailureRecord(stage="scout")` with `RemoteErrorDetail` and traceback, a one-line error and the WARNING; a retry is allowed | ✅ | Four cases: build, first turn, after a tool cycle (`EventLoopException`), and a real `openai.RateLimitError` giving 429 and its request ID. The error has no newline, traceback or provider text. `exc_info` is set |
| `MCPConnectionError` or `MCPClientNotConnectedError` at build or during the call sets `fatal_error`, records `mcp_session`, logs at ERROR and returns an error | ✅ | Four cases, including one wrapped by Strands. The slot holds the MCP exception itself (M16 killed), and the first is kept (M5 killed). The ERROR line names `server_dir` and Approach 1's `MCP_LAUNCH_COMMAND`, character for character |
| A failed call records its telemetry, from `event_loop_metrics` once built | ✅ | 8 failure cases append one entry each. Never-built calls give zero usage. Built-then-raised calls keep 100/7/107 and `list_regulatory_updates x1`; M2 and M3 are killed |
| Every log line during the call carries `run_id` | ✅ | The real `configure_logging("DEBUG", …)` file, with `strands` lines, is checked; M4 is killed |
| Green: `ModelBuilder` moves to `model_factory.py`, and the deferred helper is restored (F5) | ✅ | The `Protocol` is Approach 1's `orchestrator.py:104-124` verbatim. `scripted_model_builder` is restored, and `scripted_model_builder_by_effort` meets F5's per-effort keying |

### 3.3 Definition of Done

| # | Status | Evidence |
| :---: | :---: | :--- |
| DoD-1 | ✅ | 845 passed (847 after the architect's files), 0 failures, 0 errors |
| DoD-2 | ✅ | `All checks passed!` |
| DoD-3 | ✅ | Gate 2 |
| DoD-4 | ✅ | `src/tools.py` has 100% line and branch coverage. `ModelBuilder` is exercised by `test_scripted_support.py`. `mcp_client.py` changed annotations only |
| DoD-5 | ✅ | `test_docs_consistency.py` passes within the full run |
| DoD-6 | ⏳ | `WALKTHROUGH.md` is the orchestrator's, at checkpoint. It must carry Q-1's corrected count and Q-4's note |

## 4. Verification detail

### 4.1 P9: the `mcp_client.py` diff

`diff ../code-orchestration/src/mcp_client.py src/mcp_client.py` shows only these lines, and HEAD's copy was verbatim:
* `from types import TracebackType`;
* six `def` lines: `__init__`, `start`, `stop`, `__enter__`, `__exit__` (reflowed across three lines) and `_ensure_connected`.

These are nine annotations. `tests/test_integration/test_mcp_client.py` is byte-identical to HEAD. Pyright's six errors in `mcp_client.py` are on body lines Approach 1 wrote, which P9 does not let this project touch.

### 4.2 D-I events and their fields

| Event | Level | Fields in the line | Asserted by |
| :--- | :---: | :--- | :--- |
| Scope built by the Supervisor | INFO | The validated `PipelineScope`, with `context` | `test_a_successful_call_logs_the_scope_…` |
| Sub-agent invocation started / completed | INFO | Role, model, effort, tokens, duration and substrate tools; `doc_id` and `attempt` through the correlation filter | The same test, plus `test_the_completed_line_names_the_substrate_tools_…` (M23 and M24 killed) |
| Scout result | INFO | Count, `doc_id`s and scores, or "No qualifying updates" | Two tests |
| Guardrail violation | WARNING | Guardrail, tool, `doc_id`, message | `_assert_refused` |
| Recoverable tool failure returned to the Supervisor | WARNING | Tool, `doc_id`, `attempt`, and `exc_info` with the full chain | 4 cases (M12 and M19 killed) |
| MCP session failed to open, or died mid-run | ERROR | Tool, `server_dir`, launch command, `exc_info` | 4 cases (M13 killed) |

Approach 1 logs failures the same way: the message plus `exc_info=exc` (`orchestrator.py:424-430`). A failed call's tokens and duration appear only in its ledger entry, not in a log line. D-I does not ask for them on the failure event, so this is not a finding.

### 4.3 Mutation probes

I ran these on a scratch copy of the repository in my scratchpad, with this project's `.venv` interpreter, against `tests/test_unit/test_tools_scout.py`. `src/tools.py` in the repository was never touched, and the baseline passes.

| Mutant | Result |
| :--- | :---: |
| M1 fatal classification disabled · M2 no ledger entry on failure · M3 failure telemetry always zero · M4 no `log_context(run_id)` · M5 fatal slot overwritten · M6 `str(exc)` in the one-line error · M7 violation not stored · M8 `__suppress_context__` ignored · M9 last duplicate wins · M10 hooks dropped · M11 Scout narrowed to three tools · M12, M13, M14 wrong log levels · M15 fatal stage `scout` · M16 fatal slot holds the wrapper · M17 scope not stored · M19 no `exc_info` · M20 status code dropped · M21 no traceback · M22 `remote=None` · M23 structured-output tool listed as used · M24 no completed log · M25 effort not recorded · M27 no scope log | 25 killed |
| M18 `run=state.context` in place of `state.snapshot()` on success | Survives: equivalent while `drafts_saved` is always 0. Iteration 10 must assert a snapshot taken after a save |
| M26 `except BaseException` in place of `except Exception` | Survives: Q-2 |

For M26, an in-memory probe confirms the current code is right: a `KeyboardInterrupt` raised from `list_tools_sync` propagates out of `scout_tool`, and nothing is recorded. No test pins it, however.

### 4.4 Telemetry against the installed SDK

For `strands-agents 1.55.1`, in `.venv/Lib/site-packages`:
* `EventLoopMetrics.get_summary()` returns `accumulated_usage`, `accumulated_metrics` and `tool_usage`, which are the keys `extract_telemetry` reads;
* `Agent` calls `reset_usage_metrics()` at the start of an invocation, and that only appends an `AgentInvocation`. The accumulated usage of a fresh per-call agent therefore holds exactly that call's spend when it raises.

`AgentResult(stop_reason, message, metrics, state)` is a valid construction for the wrapper in `_failed_call_telemetry`.

### 4.5 Substrate shape

`hse-easy-mock` `list_regulatory_updates(source="INAIL", limit=2)` returns objects with exactly `RegulatoryUpdateSummary`'s eleven fields. That is the shape of `UPDATE_FIXTURE` inside `scout_candidate_args`, which the scripted `ScoutReport`s nest.

### 4.6 Declared deviations

| Deviation | Assessment |
| :--- | :--- |
| D-A step order: ledger and log before the store | Matches the plan's Green order ("fresh agent → run → ledger → log → classify errors"), and it cannot be observed in a single-threaded call. The architect concurs. Record it only |
| P9 done here | This is the plan's own schedule (P9 names Iteration 7), not a deviation |
| Tests that passed on their first run | Q-4 |
| The direct call with `max_drafts="three"` bypasses Strands' schema check | Accepted. It is the only way to reach check_scout's "any validation error" case, which Strands' schema check would otherwise catch first |

## 5. Findings by severity

### 🔴 Blocker

* **Q-1: a claimed test count is wrong.**
  * The report gives `test_annotations.py (12)`. The real collection is **13**: the test is parametrised over `src/*.py`, and there are 13 modules now that `src/tools.py` exists.
  * The report's own breakdown, 84 + 6 + 12 = 102, contradicts its 103 new tests. The 103 is right.
  * Record fix only; no code change.

### 🟡 Major

None.

### 🟢 Minor

* **Q-2: an untested invariant.** `_invoke_sub_agent`'s docstring says `BaseException` is never caught, so an interrupt still stops the process. Mutant M26, widening the catch, survives all 84 tests.
* **Q-3: an extra blank line.** `tests/test_unit/test_tools_scout.py:811-813` has three blank lines before a section comment, where the file uses two everywhere else. The configured ruff rule set does not flag it.
* **Q-4: characterisation tests to record.** Behaviours 9, 10 and 12 (the `run_id` correlation, the D-F checker and chain classification) had no Red: the code under them already existed from behaviours 4 to 7.
  * The implementer disclosed this, and showed each test fails when its code is broken; my mutants M4, M8 and M16 agree.
  * The WALKTHROUGH should list them as characterisation tests under *Deviations*, as Iteration 6 recorded its Q-1 test.

## 6. Remediation

The exact instructions are in `FIXES.md` under `## 🧪 QA & Verification`. There are no "Needs a decision" items: every finding is settled by the sources.

---

# Round 2: re-review after fix round 1

*QA and verification subagent, 2026-09-30. The same criteria as round 1, applied to the fix round's changes: the new test in `tests/test_unit/test_tools_scout.py`, the widened `OfflineSubstrateSession.fail_listing_with` in `tests/support/scripted.py`, and the blank-line fix.*

## R2.1 Summary and verdict

**Verdict: PASSED.** Q-2 and Q-3 are fixed, and I confirmed both myself. I accept that the orchestrator closes Q-1 and Q-4 in `WALKTHROUGH.md`. Both are record fixes that need no code change, and the walkthrough is the orchestrator's document, so this is the right place for them. DoD-6 stays pending until the walkthrough is written; it must carry Q-1's count (13, and 84 + 6 + 13 = 103) and Q-4's characterisation note. There are no new findings and no "Needs a decision" items.

## R2.2 What I ran myself

| Command | Real result | Claimed | Match |
| :--- | :--- | :--- | :---: |
| `uv run pytest -q` | **849 passed**, 0 failed, 0 errors, 34.66 s | 849 passed | ✅ |
| `uv run pytest -q -W error` | **849 passed**; no warning escalated | — | ✅ |
| `uvx ruff check src tests --no-cache` | `All checks passed!` | All checks passed | ✅ |
| `uv run pytest -m live --collect-only -q` | `no tests collected (849 deselected)` | 0 (849 deselected) | ✅ |
| `--collect-only` on `test_tools_scout.py` | **85** | 85 | ✅ |
| `--collect-only` on `test_annotations.py` and `test_scripted_support.py` | 19 (13 + 6) | — | ✅ |
| Branch coverage of `src/tools.py` from `test_tools_scout.py` (scratch copy, ephemeral `coverage`) | `src\tools.py 135 0 20 0 100%` | unchanged | ✅ |

**How the count adds up.** 849 = 845 + 3 + 1:
* 845 is round 1's baseline;
* 3 is one `test_document_uses_no_forbidden_term` case for each of `ARCHITECT_REVIEW.md`, `FIXES.md` and `QA_REVIEW.md`;
* 1 is the new test.

`WALKTHROUGH.md` will add one more case, so the committed count should be 850. The orchestrator should record the count it actually runs at checkpoint.

## R2.3 Q-2: the `BaseException` invariant is now pinned

* **The test.** `test_an_interrupt_is_never_caught_so_it_stops_the_process_and_leaves_no_record` (line 725) raises `KeyboardInterrupt` from `list_tools_sync` during the build. That is inside the `try` of `_invoke_sub_agent`. The test asserts that the interrupt propagates out of `scout_tool`, and that `failures`, `fatal_error` and `ledger` stay empty. It sits at the end of the "Fatal failures" section, as the report says.
* **My re-probe.**
  * I ran it on a scratch copy in my scratchpad, using this project's `.venv` interpreter. The copy was deleted afterwards, and `src/tools.py` in the repository was never touched.
  * Unmutated, the result is `85 passed`.
  * With line 261 changed to `except BaseException as exc:`, the result is `1 failed, 84 passed`. The failure is `E       Failed: DID NOT RAISE KeyboardInterrupt` in `FAILED tests/test_unit/test_tools_scout.py::test_an_interrupt_is_never_caught_so_it_stops_the_process_and_leaves_no_record`.
  * This matches the implementer's Red. Round 1's surviving mutant, M26, is now killed, which makes it 26 of 27. M18 is still equivalent in this iteration; Iteration 10 must assert a snapshot taken after a save.
* **`src/tools.py` is unchanged.** It still has a single `except Exception as exc:`, at line 261, and coverage still reads 135 statements and 20 branches at 100%.
* **The harness change.** `fail_listing_with` is widened from `Exception | None` to `BaseException | None`, on both the parameter and the attribute, and nothing else changed.
  * This diverges from Approach 1's `tests/support/scripted.py:375,381`, but only in test support and only by widening a type. Every existing caller still type-checks.
  * `raise_with` stays `Exception | None`.
  * I accept it. It is the smallest change that lets the offline session raise an interrupt.

## R2.4 Q-3: blank lines

An `awk` scan of `test_tools_scout.py`, `tests/support/scripted.py` and `src/tools.py` finds no run of three or more blank lines. Resolved.

## R2.5 Gates and criteria after the fix round

* **Gates.** Every gate stands as in round 1 §2. Gate 1 is strengthened: the docstring's `BaseException` claim is now tested.
* **Hygiene.** Gate 8 still holds. No process launched with `--quiet`, which is how `HSEMockMCPClient` launches the substrate, is running, so no substrate process was orphaned. Every `uv`, `fastmcp` and `python` process present is one of this harness's MCP servers.
* **Criteria.**
  * Acceptance criteria: 2 of 2 met.
  * Red list: 10 of 10.
  * DoD-1 to DoD-5: ✅.
  * DoD-6: ⏳, the orchestrator's, at checkpoint.

## R2.6 Findings, round 2

* 🔴 Blocker: none new. Q-1 is carried to `WALKTHROUGH.md` for the orchestrator.
* 🟡 Major: none.
* 🟢 Minor: none new. Q-2 and Q-3 are resolved. Q-4 is carried to `WALKTHROUGH.md` for the orchestrator.
