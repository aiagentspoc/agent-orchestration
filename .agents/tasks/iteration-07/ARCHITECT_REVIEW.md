# Iteration 7 — Architect Review (Stage 3, round 1)

**Scope audited:**
* New: `src/tools.py`, `tests/test_unit/test_tools_scout.py`, `tests/test_unit/test_annotations.py`, `tests/test_unit/test_scripted_support.py`.
* Modified: `src/mcp_client.py`, `src/model_factory.py`, `tests/support/scripted.py`, `tests/test_unit/test_module_structure.py`.
* Out of scope: the orchestrator's own §3 row edit in `IMPLEMENTATION_PLAN.md`.

**Baseline:** Approach 1 in `../code-orchestration/`, as it is on disk (P7). I only read it: no import, no write, no tool run inside it.

**My own checks** (I ran these myself; I did not take them from the implementer's report):

| Check | Result |
| :--- | :--- |
| `uv run pytest` | 845 passed, 0 failed |
| `uv run pytest -m live --collect-only` | nothing collected (845 deselected) |
| The four iteration test files, plus `tests/test_integration/test_mcp_client.py` | 127 passed |
| `uvx ruff check src tests --no-cache` | All checks passed: 0 in scope, 0 pre-existing |
| `uvx ruff check src/mcp_client.py --select ANN --no-cache` | All checks passed |
| `diff --strip-trailing-cr ../code-orchestration/src/mcp_client.py src/mcp_client.py` | Only 7 hunks: the `TracebackType` import and six `def` lines carrying the 9 annotations. No body line differs |
| `ModelBuilder`, extracted from `../code-orchestration/src/orchestrator.py:104` and from `src/model_factory.py` (my scratchpad script) | Byte-identical |
| `MCP_LAUNCH_COMMAND` against Approach 1's `orchestrator.py:148` | Identical string |
| `git diff HEAD -- pyproject.toml uv.lock` | Unchanged; no new dependency |
| `uvx pyright src/tools.py src/model_factory.py src/mcp_client.py` | 0 errors in `src/tools.py`. There are 7 errors in lines copied verbatim from Approach 1 (see §3) |

---

## 1. Overall verdict: **APPROVED**

`scout_tool` is a custom agent tool as D-A describes it:
* it checks its guardrails, then builds a fresh Scout, calls it once and records the outcome;
* it returns only `ToolResult[ScoutReport].for_supervisor()`;
* it neither sequences nor reroutes anything.

The P9 diff is annotations only, and `ModelBuilder` is verbatim. The fatal-error classification walks the whole exception chain. The ledger is written on every path.

I found no blocking or major defect. The two observations in §4 do not block, and neither needs a code change in this iteration.

---

## 2. Pillar audit

### Pillar 1: an agent owns the flow — ✅
* `scout_tool` (`src/tools.py:146-178`) calls exactly one sub-agent, the Scout, through `build_scout_agent` and `run_scout`. Nothing in the module chooses a next step.
* The other three tools raise `NotImplementedError`, naming Iterations 8, 9 and 10 (`:180-193`). Each sits inside its own `@tool`, so the Supervisor-facing specs exist and are pinned, while no code path runs them.
* **No truncation and no re-sort.**
  * The report passes to `ToolResult` unchanged (`:178`), and `DocumentRecord`s are inserted in the order the Scout returned them (`:423-428`).
  * The ceiling stays in `scope.max_drafts`, applied by the Scout, as in `run_scout`'s pass-through (`src/agents.py:629-641`).
* **No extra guardrail.**
  * The only refusals come from `check_scout` (`src/guardrails.py:63-86`), in §7.3's order (`scout_already_run`, then `invalid_scope`).
  * The duplicate-`doc_id` handling (`:425-427`) refuses nothing. The Supervisor still gets the whole report, and only the private `documents` map keeps the first entry. That decision is invisible to the Supervisor, so §1.5 allows it.
* **Fatal errors only record.** `_fatal_failure` (`:308-335`) sets the slot, records and logs the failure, and returns the error string. It stops and reroutes nothing, and it leaves the stop to Iteration 12, as the plan says.

### Pillar 2: division of labour and D-F — ✅
* **Only `for_supervisor()` strings leave the tool.** Every return statement goes through `ToolResult(...).for_supervisor()`: the refusal at `:211`, the failure at `:176` and the success at `:178`.
* **The one-line error never uses `str(exc)`.** `_one_line_error` (`:378-386`) is built from `qualified_type_name` over the exception chain, plus `HTTP <code>` when `RemoteErrorDetail` has one. The exception text (`str(exc)`) goes only into `FailureRecord.message` (`:372`) and the log. The line names no next step.
* **No parameter descriptions were written.**
  * The tool functions' docstrings are one line each, with no `Args:` section (`:150`, `:182`, `:187`, `:192`).
  * The pinned `tool_spec` (`test_tools_scout.py:66-98`) shows Strands' own `Parameter <name>` default for each parameter.
  * The `Args:` block at `:135-140` belongs to `build_tools`, which is not a tool.
* **The §7.1 descriptions match word for word.**
  * They are `Final` constants (`:77-96`).
  * The test compares them with `SUPERVISOR_TOOL_DESCRIPTIONS`, which `test_docs_consistency.py:774` pins to `SPECIFICATIONS.md` §7.1. The chain from the spec to the tests to the code is therefore closed.
* **AC2.** `_CheckedTool` (`test_tools_scout.py:154-170`) sends every call in the file through `_assert_supervisor_view`. That check requires exactly `{result, run, error}` at the top level, `run` equal to the snapshot, a `result` of exactly `{candidates}`, and no forbidden key at any depth. One more test goes through a real Strands `Agent` (`:857`).

### Pillar 3: custom agent tools (D-A, D-G) — ✅
* **Fresh agent per call.**
  * `_invoke_sub_agent` calls `build()` once per invocation (`:259`), and the `build` lambda constructs a new Scout each time (`:172`).
  * The retry test sees `tool_filters_seen == [None, None]`: two builds, both unfiltered.
* **One typed input, with structured output.** `run_scout(agent, checked, …)` receives the validated `PipelineScope`, and structured output is requested through `_run_worker`, which is unchanged from Iteration 6.
* Nothing uses `preserve_context`, `delegate` or `Agent.as_tool()`, and no agent is passed in `tools=`. I grepped `src/` to confirm.
* **The ledger on every path.**
  * On success, the entry is appended at `:268`.
  * On failure, it is appended at `:263`, before the call is classified. It holds zero usage when no agent was built (`:288-289`); otherwise it is read from `agent.event_loop_metrics` through `extract_telemetry` (`:290-296`). That keeps `extract_telemetry` the only reader of `get_summary()`.
* **D-A step order: a recorded deviation.** In the code, the ledger entry and the "completed" log (`:268-277`) come before the store (`_record_scout_success`, `:177`). §4 below covers it.

### Pillar 4: guardrails — ✅, as far as this iteration touches them
* **`_refuse` does all three things** (`:198-211`): it appends to `state.violations`, logs at WARNING with guardrail, tool, `doc_id` and message, and returns `result=None`.
* **A refused scope is not a run.** An invalid scope never sets `state.scope`, so it cannot trigger `scout_already_run`, and the corrected-scope test shows the retry runs.
* **Failed calls leave the Scout free to retry.** Neither a recoverable nor a fatal failure sets `state.scope`, so a later call is not refused.
* The attempt counter is not touched by this iteration.

### Pillar 5: benchmark parity — ✅
* **Prompts.** `src/agents.py` is unchanged in this iteration, so the prompts cannot have moved.
* **Models and efforts.**
  * The telemetry records `SCOUT_MODEL_ID`.
  * `SubAgentEfforts` defaults to the role constants from `src.agents` (`:108-118`), and the models come in through `SubAgentModels`.
* **Tool binding (P1).**
  * `build_scout_agent(models.scout, client, hooks=hooks)` passes no `tool_names`, so all five substrate tools are attached (`src/agents.py:486-489`).
  * `hooks` is passed by keyword.
  * A test asserts `tool_filters_seen == [None]` and all five tools.
* **The builder protocol.** `ModelBuilder` is byte-identical to Approach 1's. `scripted_model_builder` is Approach 1's builder, with `SCOPE_PARSER_MODEL_ID` replaced by `SCOUT_MODEL_ID`; both are `gpt-5-mini`, so the mapping is the same.

### Pillar 6: substrate isolation and lifecycle — ✅
* **Classified from the whole chain.** `_fatal_cause` (`:299-305`) walks `__cause__`, and walks `__context__` unless it is suppressed. It is cycle-safe (`:389-402`). It returns the first `MCPConnectionError` or `MCPClientNotConnectedError` it finds, however Strands wrapped it.
* **The first fatal error is kept** (`:324-325`). The `FailureRecord(stage="mcp_session")` is built from the exception as caught, so the Strands wrapper stays in its chain.
* **Only `Exception` is caught** (`:261`), so a `KeyboardInterrupt` still ends the process.
* **No session handling in the tools.** No module here opens a session or imports `mcp-server`, and `tools.py` receives the one client that the composition root owns.

### Pillar 7: telemetry and logging (D-I) — ✅
| D-I event | Where | Fields present |
| :--- | :--- | :--- |
| Scope built by the Supervisor | `:164` | The whole `PipelineScope` JSON |
| Sub-agent invocation started | `:255` | Role, model and effort. `doc_id` and `attempt` come from the correlation fields |
| Sub-agent invocation completed | `:269-277` | Role, model, effort, tokens, duration, and the substrate tools used, without Strands' structured-output tool |
| Scout result | `:429-436` | Count, `doc_id`s and scores; "No qualifying updates" when the report is empty |
| Guardrail violation | `:204-210` | Guardrail, tool, `doc_id`, message |
| Recoverable tool failure | `:353-359` | Tool, `doc_id`, attempt, and `exc_info` for the full chain and traceback. This matches Approach 1's `_record_failure` fidelity |
| MCP session died mid-run | `:328-334` | Tool, server directory, launch command, `exc_info` |

* **`run_id` on every line.** `scout_tool` enters `log_context(run_id=state.run_id)` (`:151`). The real-file test (`test_tools_scout.py:786`) checks every line at DEBUG, the `strands` lines included.
* **The logger name** is the literal `"src.tools"` (`:61`).

### Pillar 8: code quality — ✅
* **Imports.** They are at the top of each file, grouped as standard library, third-party, then local, with zero E402. ruff is clean.
* **Annotations.**
  * Every signature is annotated.
  * `test_annotations.py` guards this from now on. It walks every `FunctionDef` and `AsyncFunctionDef` with `ast`, nested ones included, and exempts only a leading `self` or `cls`.
  * The pyright errors are in verbatim Approach 1 lines, not in new code (§3).
* **No loose dictionaries.** No `dict[str, Any]` crosses a module boundary in `tools.py`.
* **Conventions.** Constants are `Final`, private helpers carry a leading underscore, and `__all__` lists exactly the public names. No model was added to `schemas.py`: `SubAgentModels`, `SubAgentEfforts` and `_SubAgentFailure` are frozen dataclasses, private to code, so `SPECIFICATIONS.md` §6 is unchanged.
* **Hygiene.** There is no dead code: the three placeholder tools are required by the plan's schema tests, and each names the iteration that fills it in.

---

## 3. Code review findings

**In scope:** none.

**Pre-existing, deferred and non-blocking:** `uvx pyright` reports 7 errors in code this iteration copied but did not write:
* `src/mcp_client.py`, 6 errors: lines 140, 141, 166, 195, 197 and 199, all in Approach 1's method bodies. P9 permits only the 9 annotations, so they stay as they are.
* `src/model_factory.py`, 1 error: line 97, the pydantic-settings construction pyright cannot see, which predates this iteration.

pyright is not a Definition of Done gate, so none of the 7 counts as a ruff finding.

---

## 4. Anti-patterns and risks

* **No autonomy leak, no parity drift, and no article text towards the Supervisor.**
* **Observation 1: D-A step order (a plan/spec disagreement, reported rather than settled silently).**
  * `SPECIFICATIONS.md` D-A lists "store (4) → ledger (5) → log (6)".
  * `IMPLEMENTATION_PLAN.md` Iteration 7's Green gives the helper as "fresh agent → run → ledger → log → classify errors", with the store left to the tool. The code follows the plan.
  * The Supervisor, the sub-agents and `RunState`'s final contents cannot tell the two apart. Only the order of two INFO lines changes: "completed" comes before "Scout result".
  * Step order inside a wrapper is not one of the §1.4 stop subjects (contract, guardrail, prompt, benchmark constant, exit code). **So it is not a stop and needs no fix.** WALKTHROUGH *Deviations* should record it, as the implementer's report already does.
* **Observation 2: forward risk for Iteration 12 (D-D).**
  * A substrate transport that dies while a sub-agent is calling an MCP tool is caught by Strands' MCP tool wrapper and handed to the model as an error tool result. It never reaches `_invoke_sub_agent`, so that call is not classified as fatal. The loss surfaces at the next build, when the tools are listed.
  * D-D says transport death surfaces "when a fresh sub-agent's tools are resolved, or during its call". The "during its call" half therefore holds only when the failure propagates.
  * The Iteration 12 spike, which adds hooks on the sub-agents too, should check whether an `AfterToolCallEvent` on a sub-agent can classify it. Approach 1 had the same behaviour, so this is not a parity drift and not a defect of this iteration.
* **Minor test hygiene, no fix required.** `test_tools_scout.py:45` imports `SUPERVISOR_TOOL_DESCRIPTIONS` from another test module. It works, because `tests/` is a package, and it keeps one pinned copy of §7.1. If a later iteration needs the table again, moving it into `tests/support/` would be tidier.

---

## 5. Remediation directives

None blocking, and nothing opened in `FIXES.md`. There are no "Needs a decision" items. For the orchestrator:
1. Record the D-A order deviation in `WALKTHROUGH.md` (Observation 1; `IMPLEMENTATION_PLAN.md` §1.1 "deviations from this plan, with their reason").
2. Record the `sources: list[str]` declaration in `WALKTHROUGH.md`, as Iteration 7's Red requires.
3. Carry Observation 2 into the Iteration 12 pre-flight.

---

# Iteration 7 — Architect Review (Stage 3, round 2)

**Scope re-audited:** the executor's fix round for QA's Q-2 and Q-3:
* `tests/test_unit/test_tools_scout.py`: one new test, plus the blank line deleted;
* `tests/support/scripted.py`: `OfflineSubstrateSession.fail_listing_with` widened.

I re-read `src/tools.py` to confirm it did not change.

**My own checks** (I ran these myself; I did not take them from the executor's report):

| Check | Result |
| :--- | :--- |
| `uv run pytest -q` | 849 passed, 0 failed |
| `uv run pytest -q --collect-only tests/test_unit/test_tools_scout.py` | 85 collected |
| `uv run pytest -m live --collect-only -q` | nothing collected (849 deselected) |
| `uvx ruff check src tests --no-cache` | All checks passed: 0 in scope, 0 pre-existing |
| `grep -n except src/tools.py` | One handler only, `except Exception as exc:` at `:261`. `build()` and `run()` both sit inside its `try` (`:258-260`) |
| A scan for three or more consecutive blank lines in `test_tools_scout.py`, `tests/support/scripted.py` and `src/tools.py` | None found |
| **The Q-2 mutant**, in a scratch copy in my scratchpad, deleted afterwards: `:261` changed to `except BaseException as exc:`, then `test_tools_scout.py` run with the project's interpreter | 1 failed and 84 passed. The only failure is `test_an_interrupt_is_never_caught_so_it_stops_the_process_and_leaves_no_record`, so the new test is the one that pins the behaviour |

## 1. Overall verdict: **APPROVED**

The round-1 verdict stands, and the fix round introduces no new defect.

## 2. Pillar audit (delta only)

* **Pillars 1 to 5 and 7:** not touched by the fix round. `src/` is unchanged.
* **Pillar 6: substrate isolation and lifecycle — ✅, and now pinned by a test.**
  * The round-1 claim "only `Exception` is caught, so a `KeyboardInterrupt` still ends the process" was true, but no test protected it. Now one does.
  * The new test is `test_tools_scout.py:725-733`. It raises the interrupt at the listing inside the fresh build, which is the D-D surface where a session loss would appear, and it goes through the same `_tools` path as every other call.
  * It then asserts that no failure, no fatal-error slot and no ledger entry were written. That is correct: an interrupt is not a run outcome that D-B or D-D records.
* **Pillar 8: code quality — ✅.**
  * The harness widening to `BaseException | None` at `tests/support/scripted.py:377` and `:383` is the narrowest change that lets the fake raise an interrupt. The `raise self.fail_listing_with` at `:400` is still type-correct.
  * The test is fully annotated and follows the file's naming and section conventions.
  * The Q-3 blank-line run is gone.

## 3. Code review findings

**In scope:** none. **Pre-existing:** none from ruff. The 7 verbatim-copy pyright items from round 1 are unchanged and stay deferred.

## 4. Anti-patterns and risks

None new. The round-1 observations stand:
* the D-A step order, to be recorded in the walkthrough;
* the Iteration 12 forward risk, for its pre-flight;
* the cross-test-module import, no fix required.

## 5. Remediation directives, and the orchestrator's items

* **None for the executor.**
* **I accept that the orchestrator handles Q-1 and Q-4 in `WALKTHROUGH.md`.**
  * Both are corrections to the iteration's record, not to code or tests. Q-1 is the count: `test_annotations.py` has 13 tests, and the split is 84 + 6 + 13 = 103. Q-4 is to list behaviours 9, 10 and 12 as characterisation tests.
  * `WALKTHROUGH.md` is the orchestrator's Stage 4 artefact, so neither item can be closed in the executor's scope.
  * **Q-1 needs updating for this fix round.** The counts are now:
    * **104 new code tests:** `test_tools_scout.py` 85, plus `test_scripted_support.py` 6, plus `test_annotations.py` 13.
    * **849 in total:** 742, plus those 104, plus 3.
    * The 3 are `test_docs_consistency.py::test_document_uses_no_forbidden_term`, parametrised over the three review artefacts in `iteration-07/`.
    * That parametrisation grows by one for each `.md` file added under `.agents/tasks/`. So once `WALKTHROUGH.md` exists, expect 850, and the walkthrough should quote whatever figure its final `uv run pytest` gives.
