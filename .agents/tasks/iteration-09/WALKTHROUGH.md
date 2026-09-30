# Iteration 9 — `qa_tool`: walkthrough

**Date:** 2026-09-30 · **Branch:** `approach-2/implementation` · **Plan section:** `IMPLEMENTATION_PLAN.md` §5, Iteration 9

## 1. Overview

Iteration 9 replaces the `qa_tool` stub with the real tool: auditing the latest draft of one document, once (D-C rule 8), with the attempt cap kept out of QA-Legal's view (DM7).

* **Guardrails first.** `check_qa` runs before anything else. A refusal (`not_a_candidate`, `already_saved`, `no_draft`, `already_audited`) goes through Iteration 7's `_refuse`.
* **The audit target is resolved before any agent is built.** `_audit_target` returns `latest_drafted`, and raises `RuntimeError` if the guardrail's invariant is ever broken, so nothing is spent.
* **QA-Legal gets `latest.qa_view()`,** through the unchanged `run_qa_legal`: `{doc_id, context, attempt, draft}`, with no candidate, no earlier report and no cap.
* **The report is stored as issued** on that same record, with `set_qa_report`. The verdict is logged at its D-I level; the status changes nothing else.
* **The Supervisor gets the audited record** without draft or candidate, with its full `QAReport`, and the `RunContext` snapshot. A failed call returns the still-unaudited record and a one-line error, and a retry is allowed.

## 2. Files changed

| File | Status | Responsibility |
| :--- | :--- | :--- |
| `src/tools.py` | Edited, +77 / −4 lines | `qa_tool` and two private helpers; see below |
| `tests/test_unit/test_tools_qa.py` | New, 71 tests | Every behaviour of `qa_tool`, AC1 and AC2 |
| `tests/test_unit/test_tools_scout.py` | Edited | Drops the `qa_tool` / "Iteration 9" row from the placeholder test; only `save_draft` remains in it |
| `.agents/docs/IMPLEMENTATION_PLAN.md` | Edited by the orchestrator | The §3 tracker only |
| `.agents/tasks/iteration-09/` | New | `ARCHITECT_REVIEW.md`, `QA_REVIEW.md`, `FIXES.md` and this walkthrough |

**What `src/tools.py` gains:**
* **Imports:** `QA_LEGAL_MODEL_ID`, `build_qa_legal_agent` and `run_qa_legal` from `.agents`; `check_qa` from `.guardrails`. The `.guardrails` import is now wrapped over several lines to stay within the line limit.
* **`qa_tool(doc_id)`**, entirely inside `log_context(run_id=state.run_id, doc_id=doc_id)`:
  1. `check_qa(state, doc_id)`. A violation goes to `_refuse`.
  2. `latest = _audit_target(state.documents[doc_id])`.
  3. Inside `log_context(attempt=latest.attempt)`: `_invoke_sub_agent` with `stage="qa_legal"`, a fresh `build_qa_legal_agent(models.qa_legal, client, hooks=hooks)` and `run_qa_legal(agent, latest, model_id=QA_LEGAL_MODEL_ID, reasoning_effort=efforts.qa_legal)`, labelled with `doc_id` and `latest.attempt`.
  4. On a `_SubAgentFailure`, `error` is its one-line summary; otherwise `_store_report(latest, output.payload)`.
  5. Return `ToolResult[AttemptRecord](result=latest, run=state.snapshot(), error=error).for_supervisor()`.
* **`_audit_target(document) -> AttemptRecord`** returns the latest drafted attempt. It raises `RuntimeError` if there is none or it already has a QA report, which `check_qa` makes unreachable through the tool. This is the counterpart of Iteration 8's `_revision_source`.
* **`_store_report(record, report) -> None`** calls `record.set_qa_report(report)`, then logs INFO `QA verdict PASS: doc_id=… attempt=…`, or WARNING `QA verdict <status>: doc_id=… attempt=… issues=[…]` with the full issues list.

`src/agents.py`, `src/schemas.py`, every prompt, the model IDs, the efforts, the tool binding, and `qa_tool`'s description and signature are unchanged.

## 3. TDD record

Against the Iteration 8 stub, which raised `NotImplementedError("qa_tool is built in Iteration 9.")`, every test in the new file that calls the tool fails. Several later behaviours were already met by the minimal Green, because it routes through the existing runner and `_invoke_sub_agent`. Those tests were checked with temporary, reverted mutations of `src/tools.py`, as recorded in the review artifacts.

| # | Behaviour | Red asserted | Green added |
| :---: | :--- | :--- | :--- |
| 1 | The report is stored on the latest drafted record | PASS, WARNING and ERROR are stored as issued on the one drafted attempt. With a later draft-less attempt, the report goes to the drafted one. Failed on the stub | The minimal body: invoke QA-Legal on `latest_drafted`, `set_qa_report`, return. The placeholder row in `test_tools_scout.py` was removed |
| 2 | QA-Legal receives `qa_view()` | Keys exactly `{doc_id, context, attempt, draft}`, `context == {today}`, no candidate triage text; a revised #2 carries none of #1's report, issues or headline | Already met by Iteration 6's runner. Checked by sending `attempts[0]` instead, which failed it |
| 3 | The success result | The full `QAReport`, the run snapshot, `error: null`, `max_attempts_per_doc == 3` | Already met. Checked by returning `result=None`, which failed it |
| 4 | The verdict log | INFO "QA verdict PASS", after the invocation pair; WARNING "QA verdict WARNING/ERROR" with every issue; correlation `(run_id, doc_id, attempt)` | The verdict lines |
| 5 | Telemetry and binding | One `qa_legal` ledger entry for the audited attempt (not the attempt count), with `QA_LEGAL_MODEL_ID` and the configured effort; all five substrate tools; QA-Legal's system prompt | Already met. Checked by hard-coding the effort, which failed it |
| 6 | Every `check_qa` refusal through the tool | 7 cases × 2 tests: stored, logged at WARNING with `attempt=-`, returned with `result=None`; no build, turn, ledger entry, failure or verdict. Cases: `not_a_candidate`; `already_saved` twice (saved after a WARNING, and saved with an unaudited latest draft, showing P2 comes before rule 8); `no_draft` twice (no attempts, only a failed attempt); `already_audited` twice (audited latest, after a failed revision). All failed, for example with `KeyError` for the unknown ID and `set_qa_report`'s `ValueError` after tokens were spent | `check_qa` → `_refuse` first |
| 7 | Failed calls | Build, provider error and late `RuntimeError` record `FailureRecord(stage="qa_legal")` on the audited attempt, log WARNING and no verdict; a lost session records `mcp_session`, sets `state.fatal_error` and logs ERROR; the report stays empty; the result is the unaudited record with a one-line error holding no exception text; the ledger entry is still written; a retry audits the same draft on a fresh agent | Already met by `_invoke_sub_agent`. Checked by returning `result=None` on failure, which failed it |
| 8 | The invariant helper | With `check_qa` patched to allow everything: no draft, and already audited, each raise `RuntimeError` with no build, turn, ledger entry, failure or log line | `_audit_target` |
| 9 | AC2 | Every QA-Legal user turn in the file is checked after every call for the cap's phrasing and the `RunContext` keys; an attempt-3 case; the checker can fail | Already met. Checked by making `qa_view()` append `max_attempts_per_doc`, which failed 24 tests |
| 10 | AC1 | The rule 8 table through the real `writer_tool` and `qa_tool` | Already met by behaviours 1–8 |
| 11 | Fix round 1, M1 / F-1 | The hooks `build_tools` is given reach QA-Legal: 1 `BeforeInvocationEvent` on an allowed call, 0 on a refusal. Removing `hooks=hooks` fails the `[allowed]` case | No production change; the test was missing |

**Refactor:** the store and the verdict log moved into `_store_report`, the counterpart of `_store_draft`, keeping one `ToolResult` return. In fix round 1 the test helpers' model parameters were typed `Model` in place of `Any`.

## 4. Test results

Fresh run by the orchestrator, after this walkthrough was written:

* `uv run pytest -q`: **999 passed**, 0 failed, 0 errors.
* `uv run pytest tests/test_unit/test_tools_qa.py -q`: **71 passed**.
* Tests added by this iteration: **+74 net** over Iteration 8's 925.
  * 71 in `test_tools_qa.py`;
  * −1 in `test_tools_scout.py`, the removed placeholder row;
  * +4 in `test_docs_consistency.py::test_document_uses_no_forbidden_term`, one per new `.md` file in `iteration-09/`.
* `uvx ruff check src tests`: **All checks passed!**
* No live test or live command was run. Every QA-Legal and Writer model is a `ScriptedModel` or `FailingModel` over an `OfflineSubstrateSession`.

## 5. Acceptance criteria

| Criterion | Status | Evidence |
| :--- | :---: | :--- |
| Red: QA-Legal receives `latest_drafted.qa_view()`, with no candidate and no cap | ✅ | `test_qa_legal_receives_the_latest_drafted_records_qa_view_and_nothing_of_its_candidate`, `test_a_revised_draft_is_audited_without_the_earlier_attempts_report`, `test_the_audit_of_a_third_attempt_names_its_number_and_nothing_of_the_cap` |
| Red: the `QAReport` is stored with `set_qa_report` on the latest drafted record | ✅ | `test_a_successful_audit_stores_the_report_as_issued_on_the_latest_drafted_record[PASS/WARNING/ERROR]`, `test_the_report_goes_to_the_latest_drafted_record_not_to_a_later_draftless_attempt` |
| Red: the result holds the record with its `qa_report`, without draft or candidate, plus `RunContext` | ✅ | `test_a_successful_audit_returns_the_record_with_its_full_report_the_run_and_no_error`, and `_assert_supervisor_view` on every call, which also requires the result to equal the stored record's `supervisor_view()` |
| Red: the verdict is logged at the D-I levels | ✅ | `test_a_pass_verdict_is_logged_at_info_with_its_document_and_attempt`, `test_a_warning_or_error_verdict_is_logged_at_warning_with_every_issue[WARNING/ERROR]` |
| Red: `StageTelemetry(stage="qa_legal", doc_id, attempt)` is appended | ✅ | `test_a_successful_audit_appends_one_qa_legal_ledger_entry_for_its_attempt`, `test_the_ledger_entry_belongs_to_the_audited_attempt_not_to_the_attempt_count`, `test_a_failed_audit_still_appends_its_one_qa_legal_ledger_entry` × 4 |
| Red: `not_a_candidate`, `already_saved`, `no_draft` and `already_audited` each have a test | ✅ | `test_a_refused_audit_is_stored_logged_and_returned_with_no_result` and `test_a_refused_audit_builds_no_qa_legal_changes_no_attempt_and_spends_nothing`, each × 7 cases |
| Red: a failed call stores `FailureRecord(stage="qa_legal", attempt)`, leaves `qa_report` empty so a retry is allowed, and returns an error string | ✅ | `test_a_failed_audit_records_a_qa_legal_failure_on_the_audited_attempt` × 3, `test_a_failed_audit_leaves_the_report_empty_and_returns_the_record_and_a_one_line_error` × 4, `test_an_audit_may_be_retried_after_a_failed_call_on_the_same_attempt` |
| **AC1:** after a successful revision `qa_tool` is allowed again; after a failed revision it returns `already_audited` | ✅ | `test_the_rule_8_table_draft_error_revision_pass_through_both_tools` and `test_the_rule_8_table_after_a_failed_revision_qa_tool_returns_already_audited`, through the real `writer_tool` and `qa_tool` from one `build_tools` call |
| **AC2:** no QA-Legal user turn in the tests contains the attempt cap | ✅ | `_CheckedTool` checks every QA-Legal user turn after every call in the file against `_CAP_PHRASES`; `test_the_attempt_cap_check_rejects_every_way_the_cap_could_be_phrased` × 10 shows the check can fail |
| DoD-1 to DoD-5 | ✅ | §4 above; only scripted models; every new function and branch is tested, `hooks` forwarding included since fix round 1; the docs test passes |
| DoD-6 | ✅ | This file |

## 6. Decisions and deviations

**Decisions (§1.5, or settled from the sources in the pre-flight):**
* **A failed call returns the unaudited record,** not `result=None`. The plan says only "returns an error string"; D-C rule 5 ("every `writer_tool` and `qa_tool` result carries the `AttemptRecord`") and §6.4 ("a failed call returns `result` when there is one") settle it.
* **The ledger and failure attempt number is `latest.attempt`,** the audited attempt, never `attempts_used`.
* **Verdict log wording:** `QA verdict PASS: doc_id=%s attempt=%d` and `QA verdict %s: doc_id=%s attempt=%d issues=%s`, with the full issues list rather than Approach 1's count. Approach 1 logged every verdict at INFO; D-I sets WARNING for `WARNING` and `ERROR`, and logging is not a benchmark constant.
* **Private names:** `_audit_target`, `_store_report`.
* **Test organisation:** a local `qa_turns(doc_id, …)` helper; `_CheckedTool` takes the tool's name so `writer_tool` results in AC1 are checked as unaudited, and also runs the cap check; `already_saved` is set up by assigning `DocumentRecord.saved` directly, since `save_draft` comes in Iteration 10.

**Deviations:**
* **Ledger before store,** carried over from Iterations 7 and 8: `_invoke_sub_agent` writes the ledger entry before `_store_report` runs.
* No other deviation from the plan.

## 7. Review

Two rounds were used.

**Round 1.**
* **Architect: CHANGES REQUESTED.**
  * **M1 (Major):** no test showed that `qa_tool` passes `hooks=hooks` to `build_qa_legal_agent`. With the argument removed, all 222 tool tests still passed. **Resolved** by `test_the_hooks_given_to_build_tools_reach_qa_legal_and_only_when_it_is_built[allowed, already_audited]`, which fails when the argument is removed.
  * **m1 (optional):** `Any`-typed model parameters in the test helpers. **Resolved:** typed `strands.models.model.Model`.
* **QA: FAIL.**
  * **F-1 (Major):** the same defect as M1, found independently. **Resolved** by the same test.
  * **O-1 (optional):** two more cap phrases. **Resolved:** `"remaining"` and `"of 3"` added to `_CAP_PHRASES`, each with its own can-fail case.
  * **O-2 (information):** `ruff format` drift in lines of `test_tools_scout.py` this iteration did not touch. Left as it is; formatting is not a DoD check.

**Round 2.**
* **Architect: APPROVED,** no findings.
* **QA: PASS,** no findings.

No item needed a decision. The risk carried over from Iteration 7 still stands: after a fatal error, a later tool call still builds an agent until Iteration 12 adds the stop.
