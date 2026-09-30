# QA Review — Iteration 9 (`qa_tool`), round 1

**Reviewer:** qa subagent, against `.agents/skills/code-reviewer/SKILL.md`.
**Scope:** the uncommitted diff on `approach-2/implementation`: `src/tools.py` (M), `tests/test_unit/test_tools_scout.py` (M, one placeholder row removed), `tests/test_unit/test_tools_qa.py` (new, 67 tests), `.agents/docs/IMPLEMENTATION_PLAN.md` (M, tracker row set to In progress).

## 1. Summary and verdict

**Verdict: CHANGES REQUIRED (FAIL, round 1).** One Major finding: DoD-4 is not fully met.

The implementation is correct and closely tested. The suite, lint, guardrails, D-F views, telemetry and logging all check out against the spec, and both acceptance criteria hold. The one gap is that `qa_tool` forwards `hooks=hooks` to `build_qa_legal_agent`, and no test exercises it. Dropping it survives the whole suite, though the equivalent argument is tested for `scout_tool` (Iteration 7) and `writer_tool` (Iteration 8). The fix is one test.

**What I ran myself:**

| Command | Result | Claimed |
| :--- | :--- | :--- |
| `uv run pytest -q` | **991 passed**, 0 failed, 0 errors, 0 warnings, 32.5 s | 991 passed |
| `uv run pytest tests/test_unit/test_tools_qa.py -q` | **67 passed** | 67 new tests |
| `uvx ruff check src tests --no-cache` | **All checks passed!** | same |
| `uvx ruff format --check src/tools.py tests/test_unit/test_tools_qa.py` | 2 files already formatted | same |
| `uv run pytest -m live --collect-only -q` | no tests collected (991 deselected) | same |

Every count claimed in the implementer's report matches the real output: 925 − 1 + 67 = 991.

**Mutation checks** were run on a scratch copy under the session scratchpad, which has since been deleted. The import path was confirmed to resolve to the scratch `src/tools.py`.

| Mutation | Result |
| :--- | :--- |
| `qa_tool` builds QA-Legal without `hooks=hooks` | **Survived:** 0 of 222 tool tests failed, and no behavioural test failed in the full suite |
| `run_qa_legal(...)` without `reasoning_effort=efforts.qa_legal` (positive control) | Killed: 1 failed |
| PASS verdict logged at WARNING instead of INFO (positive control) | Killed: 1 failed |

After the checks, no orphaned process was left behind. Every running `python.exe` and `uv.exe` is a harness MCP server started at session start: `uv run --directory …mcp-server fastmcp run server.py` without `--quiet`, and `strands-agents-mcp-server`. None is a product client, which launches with `--quiet`.

## 2. Gate matrix

| Gate | Topic | Status | Notes |
| :--- | :--- | :---: | :--- |
| 1 | Strict TDD | ❌ | The Red steps state expected failures: steps 1, 4, 6 and 8. The characterisation steps (2, 3, 5, 7, 9, 10) were each checked with a reverted mutation. One test in step 7 first failed for a fixture reason, a Strands `EventLoopException` wrap, and was relaxed. It is characterisation, so no Red is lost. **The `hooks=hooks` argument on the QA-Legal build is untested (F-1).** Every other new line and branch is exercised: `_audit_target` (both raise branches), `_store_report` (the PASS and non-PASS branches), and the qa_tool success, failure and refusal paths |
| 2 | Zero-token testing | ✅ | Every QA-Legal model is a `ScriptedModel` or `FailingModel`. The substrate is `OfflineSubstrateSession` through the real `HSEMockMCPClient`, and no endpoint is reachable. The live suite is deselected (991 deselected), and no `live` marker was added |
| 3 | Pydantic v2 contracts | ✅ | No model was added or changed, `src/schemas.py` is untouched, and no removed model appears in `src/`. The result is `ToolResult[AttemptRecord]`, serialised by `for_supervisor()` (§6.4, §7.2). No new `dict[str, Any]` crosses a module boundary |
| 4 | Guardrails and attempt cap | ❌ (F-1 only; the guardrails themselves pass) | `check_qa` runs first, in the §7.3 order `not_a_candidate` → `already_saved` → `no_draft` → `already_audited`. Its 4 guardrails are reached through the tool in 7 cases: `already_saved` both after a WARNING save and with an unaudited latest draft, which is P2 before rule 8. Each violation is logged at WARNING, appended to `state.violations` and returned with `result=None`. A refusal changes no attempt and spends nothing. `qa_tool` never appends an attempt, so the cap is untouched |
| 5 | Strands integration and telemetry | ✅ (bar F-1) | QA-Legal is built fresh per call (the retry test shows a one-message conversation) with all five substrate tools (P1: `tool_filters_seen == [None]`) and the QA-Legal system prompt. It uses `structured_output_model` through the existing runner. There is one `StageTelemetry(stage="qa_legal", doc_id, attempt=latest.attempt)` on success and on every failure case, with `QA_LEGAL_MODEL_ID` and the resolved effort. `extract_telemetry` is unchanged in this iteration |
| 6 | No article text for the Supervisor | ✅ | Every tool call in the file passes through `_CheckedTool`, which runs `_assert_supervisor_view`. That check covers the exact key set, the result equal to the stored `supervisor_view()`, no forbidden key at any depth and no article text anywhere in the string. It also has a can-fail test with 6 mutations and a Strands pass-through test |
| 7 | Drafts and logging | ✅ | No drafts are involved. D-I "QA verdict PASS" is logged at INFO with `doc_id` and `attempt`. "QA verdict WARNING or ERROR" is logged at WARNING with every issue. The recoverable failure is logged at WARNING with `exc_info`, and the lost session at ERROR. Correlation `(run_id, doc_id, attempt)` is asserted on every `src.tools` record, and `attempt` is `-` on refusals |
| 8 | Python and subprocess safety | ✅ | Full annotations, imports at the top, and `pathlib.Path` in the tests. The pytest output is clean, with no warnings, and no stray processes remain |

## 3. Acceptance criteria and Definition of Done

| # | Criterion | Status | Evidence |
| :--- | :--- | :---: | :--- |
| Red-1 | QA-Legal receives `latest_drafted.qa_view()`: no candidate, no cap | ✅ | `test_qa_legal_receives_the_latest_drafted_records_qa_view_and_nothing_of_its_candidate`: the keys are exactly `{doc_id, context, attempt, draft}`, `context == {today}`, and there is no rationale or score. `test_a_revised_draft_is_audited_without_the_earlier_attempts_report` also passes. `run_qa_legal` sends `record.qa_view()` (`src/agents.py:766`) |
| Red-2 | Report stored with `set_qa_report` on the latest drafted record | ✅ | The parametrised PASS/WARNING/ERROR test, and `…not_to_a_later_draftless_attempt`. `_store_report` calls `record.set_qa_report` (`src/tools.py:641`) |
| Red-3 | Result: the record with its `qa_report`, no draft or candidate, plus `RunContext` | ✅ | `test_a_successful_audit_returns_the_record_with_its_full_report_the_run_and_no_error` checks for exact equality, and `max_attempts_per_doc == 3` |
| Red-4 | Verdict logged at the D-I levels | ✅ | `test_a_pass_verdict_is_logged_at_info…` and `test_a_warning_or_error_verdict_is_logged_at_warning_with_every_issue`. The PASS→WARNING level mutation is killed |
| Red-5 | `StageTelemetry(stage="qa_legal", doc_id, attempt)` appended | ✅ | Success, plus 4 failure cases. The entry names the audited attempt, not the attempt count |
| Red-6 | `not_a_candidate`, `already_saved`, `no_draft` and `already_audited` each tested | ✅ | `REFUSALS`, 7 cases × 2 tests |
| Red-7 | A failed call stores `FailureRecord(qa_legal, attempt)`, leaves `qa_report` empty (retry allowed) and returns an error string | ✅ | Recoverable cases for build, provider error and late RuntimeError; a fatal case for `mcp_session` with the fatal slot set; and the retry test |
| AC1 | After a successful revision, `qa_tool` is allowed again; after a failed revision it returns `already_audited` | ✅ | `test_the_rule_8_table_draft_error_revision_pass_through_both_tools` and `test_the_rule_8_table_after_a_failed_revision_qa_tool_returns_already_audited` run through the real `writer_tool` and `qa_tool` |
| AC2 | No QA-Legal user turn in the tests contains the attempt cap | ✅ | `_CheckedTool` checks every QA-Legal user turn after every call, with an explicit attempt-3 test and a can-fail test (8 phrases) |
| DoD-1 | Full suite passes | ✅ | 991 passed, 0 failed, 0 errors |
| DoD-2 | Lint clean | ✅ | `All checks passed!` |
| DoD-3 | No live model call | ✅ | Only scripted or failing models; live collect-only deselects all 991 |
| DoD-4 | Every new `src/` function is exercised by a test | ❌ | The `hooks=hooks` forwarding in `qa_tool`'s build lambda is untested; a mutation removing it survives (F-1) |
| DoD-5 | Docs match code | ✅ | `test_docs_consistency.py` passes within the full run |
| DoD-6 | `WALKTHROUGH.md` | n/a | The orchestrator's, at Stage 4 |

**Passed: 15 of 16 checkable rows** (DoD-6 excluded): Red-1 to Red-7, AC1, AC2 and DoD-1 to DoD-5, with DoD-4 failing.

## 4. Findings by severity

### 🔴 Blocker
None.

### 🟡 Major

**F-1. The hooks forwarding for QA-Legal is untested** (DoD-4, Gate 1).

`src/tools.py:266` builds QA-Legal with `build_qa_legal_agent(models.qa_legal, client, hooks=hooks)`. No test gives `build_tools` a hook and observes it on the QA-Legal agent. With the argument removed, the full suite still passes.

The same seam is locked for the other tools:
* `tests/test_unit/test_tools_scout.py::test_the_hooks_given_to_build_tools_reach_the_scout` (Iteration 7);
* `tests/test_unit/test_tools_writer.py`, `_AttemptsSeenByTheWriter` (Iteration 8).

Iteration 12 attaches the logging hooks and the fatal-stop hook through this argument (D-D, D-I). A regression here would silently drop the fatal stop and the tool-call log lines for every QA-Legal call. The remediation is in `FIXES.md`.

### 🟢 Minor
None blocking.

**Optional, non-blocking suggestions:**
* **O-1.** `_CAP_PHRASES` could also include the bare `"remaining"` and `"of 3"`, to widen AC2's net. This is not required: `qa_view()`'s exact key set already proves that no `RunContext` field reaches QA-Legal.
* **O-2.** `tests/test_unit/test_tools_scout.py` has pre-existing `ruff format` drift in untouched lines, as the implementer reported. It is outside this iteration's diff; leave it alone.

## 5. Other checks with no finding

* **D-A order.**
  * `check_qa` runs before anything is built.
  * `_audit_target` resolves the target before building, and its broken-invariant path is proven to build nothing, spend nothing and log nothing.
  * The ledger entry is written in `_invoke_sub_agent` before `_store_report`, the step 4/5 ordering accepted in Iteration 7.
  * A single `ToolResult` is returned.
* **§6.4 on failure.** The failed-call `result` is the unaudited `AttemptRecord`, not `None`. That is consistent with §6.4 ("A failed call returns `result` when there is one") and with `writer_tool`'s precedent. Only guardrail violations return `result=None`.
* **The decision stays with the Supervisor.** The QA status only chooses the log level; no code branches on it to pick a next step (AGENTS.md Rule 2).
* **Substrate.** `hse-easy-mock` `get_document_by_id("inail-2026-ot23")` returns a full `RegulatoryDocument` live. The unit tests are offline by design, and the unchanged substrate drift test covers shape parity.

**Verdict: FAIL (CHANGES REQUIRED): one Major finding (F-1), no Blockers.**

---

# QA Review — Iteration 9 (`qa_tool`), round 2

**Scope:** fix round 1. Only `tests/test_unit/test_tools_qa.py` changed; `src/tools.py` still carries `hooks=hooks` at line 266, as in round 1.

## R2.1 Summary and verdict

**Verdict: PASS.** F-1 (the architect's M1) is closed, and the new test is shown to fail when the defect comes back. The optional m1 and O-1 are applied correctly. O-2 was left alone, as agreed. There are no new findings.

**What I ran myself:**

| Command | Result | Claimed |
| :--- | :--- | :--- |
| `uv run pytest -q` | **998 passed**, 0 failed, 0 errors, 31.7 s | 998 passed |
| `uv run pytest -q -W error` | 998 passed (no warning escalated) | n/a |
| `uv run pytest tests/test_unit/test_tools_qa.py -q` | **71 passed** | 67 → 71 |
| `uvx ruff check src tests --no-cache` | **All checks passed!** | same |
| `uvx ruff format --check src/tools.py tests/test_unit/test_tools_qa.py` | 2 files already formatted | clean |
| `uv run pytest -m live --collect-only -q` | no tests collected (998 deselected) | n/a |
| `uv run pytest --collect-only -q` (grep `iteration-09`) | 3 `test_document_uses_no_forbidden_term` cases, one per review `.md` | +3 |

The counts add up: 991 + 4 (the QA file, 67 → 71: 2 hooks cases and 2 cap-phrase cases) + 3 (docs cases) = 998. Every count in the implementer's report matches.

**Mutation check,** done independently on a scratch copy that has since been deleted. `src.tools.__file__` resolved to the scratch copy. I removed `hooks=hooks` from the `build_qa_legal_agent(...)` call at `src/tools.py:266`. Verbatim output:

```
E       assert 0 == 1
FAILED tests/test_unit/test_tools_qa.py::test_the_hooks_given_to_build_tools_reach_qa_legal_and_only_when_it_is_built[allowed]
1 failed, 70 passed in 4.21s
```

The mutant is killed. In round 1 it survived all 222 tool tests.

**Processes:** every `python.exe` and `uv.exe` still running is a harness MCP server (`fastmcp run server.py` without `--quiet`, and `strands-agents-mcp-server`). None was left by this review.

## R2.2 Fix verification

| Item | Status | Evidence |
| :--- | :---: | :--- |
| F-1 / M1 | ✅ closed | `_tools` (l. 186) and `_qa_tool` (l. 207) take `hooks: tuple[HookProvider, ...] = ()` and forward it to `build_tools` (l. 196, 210). `_RecordingHooks` (l. 465) counts `BeforeInvocationEvent`. The parametrised test (l. 478-489) asserts count 1 with no error for an unaudited draft, and count 0 with the error set for `already_audited`, so it covers both the positive seam and "a refusal builds nothing". The mutant is killed (above) |
| m1 | ✅ applied | Model parameters are `strands.models.model.Model`: `_CheckedTool.__init__` (l. 164), `_tools` `qa` and `writer: Model \| None` (l. 181-182), `_qa_tool` (l. 204), and `_failing_qa`. The `isinstance(self._qa, ScriptedModel)` guard in `_CheckedTool.__call__` still narrows correctly. The remaining `Any` are JSON-decoded dicts and log-record tuples in test-local helpers, which do not cross a production module boundary |
| O-1 | ✅ applied | `_CAP_PHRASES` includes `"remaining"` and `"of 3"`. `test_the_attempt_cap_check_rejects_every_way_the_cap_could_be_phrased` is parametrised over the tuple, so each new phrase has its own can-fail case. Every checked QA-Legal user turn in the file passes with the wider net, including the attempt-3 case, so no current prompt says "remaining" or "of 3" |
| O-2 | n/a | Left alone, as agreed |

## R2.3 Acceptance criteria and Definition of Done (re-checked)

| # | Criterion | Status | Evidence (round 2) |
| :--- | :--- | :---: | :--- |
| Red-1 to Red-7 | As in round 1 | ✅ | Tests unchanged in substance; all 71 pass |
| AC1 | Rule 8 table through both tools | ✅ | Both rule 8 tests pass |
| AC2 | No attempt cap in any QA-Legal user turn | ✅ | Wider `_CAP_PHRASES` (10 phrases), each with a can-fail case |
| DoD-1 | Full suite passes | ✅ | 998 passed |
| DoD-2 | Lint clean | ✅ | All checks passed! |
| DoD-3 | No live model call | ✅ | Scripted or failing models only; live collect-only deselects all 998 |
| DoD-4 | Every new `src/` function exercised by a test | ✅ | The `hooks=hooks` forwarding is now covered, and its mutant is killed. The other branches were covered in round 1 |
| DoD-5 | Docs match code | ✅ | `test_docs_consistency.py` passes in the full run, including the three iteration-09 review files |
| DoD-6 | `WALKTHROUGH.md` | n/a | The orchestrator's, at Stage 4 |

**Passed: 16 of 16 checkable rows** (DoD-6 excluded).

## R2.4 Gate matrix (round 2)

| Gate | Status | Change since round 1 |
| :--- | :---: | :--- |
| 1 Strict TDD | ✅ | F-1 closed. The new test is characterisation of existing code, and its can-fail proof was reproduced here |
| 2 Zero-token testing | ✅ | Unchanged |
| 3 Pydantic v2 contracts | ✅ | Unchanged; no `src/` change |
| 4 Guardrails and attempt cap | ✅ | F-1 closed; a refusal is shown to build no QA-Legal agent through the hook count as well |
| 5 Strands integration and telemetry | ✅ | The hooks seam for QA-Legal is locked, matching the Scout and the Writer |
| 6 No article text for the Supervisor | ✅ | The new test's call also goes through `_CheckedTool` |
| 7 Drafts and logging | ✅ | Unchanged |
| 8 Python and subprocess safety | ✅ | Clean output under `-W error`; no stray processes |

## R2.5 Findings by severity

* 🔴 Blocker: none.
* 🟡 Major: none.
* 🟢 Minor: none. O-2, the pre-existing `ruff format` drift in `test_tools_scout.py`, remains out of scope.

**Verdict: PASS. No findings; 16 of 16 checkable criteria pass.**
