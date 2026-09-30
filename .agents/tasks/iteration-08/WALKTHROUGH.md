# Iteration 8 — `writer_tool`: walkthrough

**Date:** 2026-09-30 · **Branch:** `approach-2/implementation` · **Plan section:** `IMPLEMENTATION_PLAN.md` §5, Iteration 8

## 1. Overview

Iteration 8 replaces the `writer_tool` stub from Iteration 7 with the real tool: writing and revising one candidate, with the attempt counter held in code (D-C rules 1 to 7, D-E).

* **Guardrails first.** `check_writer` runs before anything changes. A refusal is stored, logged at WARNING and returned with `result=None`, through Iteration 7's `_refuse`.
* **The attempt counts before the Writer runs (rule 3).** A new `AttemptRecord` is appended with `attempt = attempts_used + 1` and the document's own `candidate` object. It stays on the document whether the call then succeeds, fails or is rejected by rule 2.
* **The Writer's input follows D-E.** For `revise=False` it gets the new record. For `revise=True` it gets the latest drafted record, with its draft and QA report. The output always goes on the new record.
* **Rule 2 is ported from Approach 1.** `_verify_writer_dereferenced_source` and `WriterSourceFetchError` have the same checks and message text as Approach 1's. A draft that fails is not kept, and a `FailureRecord(stage="fetch_document")` is stored.
* **One ledger entry per allowed call,** on every path, through Iteration 7's `_invoke_sub_agent`.
* **The Supervisor sees no article text (D-F).** The result is `ToolResult[AttemptRecord].for_supervisor()`: the attempt's `{doc_id, context, attempt, qa_report}` and the `RunContext` snapshot.

## 2. Files changed

| File | Status | Responsibility |
| :--- | :--- | :--- |
| `src/tools.py` | Edited, +171 / −6 lines | `writer_tool` and its private helpers; see below |
| `tests/test_unit/test_tools_writer.py` | New, 72 tests | Every behaviour of `writer_tool`, AC1 and AC2 |
| `tests/support/scripted.py` | Edited, +20 lines | `FORBIDDEN_SUPERVISOR_KEYS` and `json_keys`, moved here from `test_tools_scout.py` so both tool test files share them |
| `tests/test_unit/test_tools_scout.py` | Edited | Imports the two moved helpers, and drops the `writer_tool` / "Iteration 8" row from the placeholder test `test_the_later_tools_are_declared_but_not_yet_built` |
| `.agents/docs/IMPLEMENTATION_PLAN.md` | Edited by the orchestrator | The §3 tracker only |
| `.agents/tasks/iteration-08/` | New | `ARCHITECT_REVIEW.md`, `QA_REVIEW.md`, `FIXES.md` and this walkthrough |

**What `src/tools.py` gains:**
* **Imports:** `WRITER_MODEL_ID`, `build_writer_agent` and `run_writer` from `.agents`; `check_writer` from `.guardrails`; `AgentContext`, `ArticleDraft`, `AttemptRecord` and `QAReport` from `.schemas`.
* **`_SOURCE_FETCH_TOOL: Final[str] = "get_document_by_id"`,** the tool rule 2 looks for in the Writer's telemetry.
* **`WriterSourceFetchError(RuntimeError)`,** exported in `__all__`. It is raised by `writer_tool`, never by `src/agents.py`.
* **`writer_tool(doc_id, revise)`**, entirely inside `log_context(run_id=state.run_id, doc_id=doc_id)`:
  1. `check_writer(state, doc_id, revise)`. A violation goes to `_refuse`.
  2. For `revise=True`, `_revision_source(document)` resolves what is being revised, **before** the append.
  3. Build the new `AttemptRecord(context=AgentContext(today=state.context.today), candidate=document.candidate, attempt=document.attempts_used + 1)` and append it.
  4. Inside `log_context(attempt=record.attempt)`: choose the Writer's input (`_revision_input` for a revision, which also logs "Revision requested"), then call `_invoke_sub_agent` with `stage="writer"`, a fresh `build_writer_agent(models.writer, client, hooks=hooks)` and `run_writer(..., model_id=WRITER_MODEL_ID, reasoning_effort=efforts.writer)`, labelled with `doc_id` and the new attempt.
  5. On a `_SubAgentFailure`, the error is its one-line summary. Otherwise `_store_draft` applies rule 2 and returns `None` or the one-line error.
  6. Return `ToolResult[AttemptRecord](result=record, run=state.snapshot(), error=error).for_supervisor()`.
* **`_Revision`** is a private frozen dataclass holding the latest drafted `AttemptRecord` and its `QAReport`.
* **`_revision_source(document)`** returns a `_Revision`, or raises `RuntimeError` if there is no latest draft or it has no QA report. `check_writer`'s `not_audited` makes that unreachable through the tool; resolving it before the append means a broken invariant would leave no attempt behind.
* **`_revision_input(revision, record)`** logs INFO `Revision requested: doc_id=… attempt=… follows=<status> (the QA report on attempt k)` and returns the latest drafted record.
* **`_store_draft(state, record, output)`** runs `_verify_writer_dereferenced_source`. On `WriterSourceFetchError` it records the failure through `_recoverable_failure(stage="fetch_document")` and returns its one-line error; otherwise it calls `record.set_draft(output.payload)`. It writes no second ledger entry: `_invoke_sub_agent` has already written it.
* **`_verify_writer_dereferenced_source(draft, telemetry, doc_id)`** is Approach 1's check. It fails if no `tool_invocations` entry named `get_document_by_id` has `call_count > 0`, or if `draft.source_doc_id != doc_id`, an empty ID included. It does not check the fetch's argument.
* **`_recoverable_failure`** now takes `stage: FailureStage` rather than the sub-agent-only stage type, so it can record `fetch_document`. Its docstring says so.

`src/agents.py`, every prompt, the model IDs, the efforts, the tool binding, and `writer_tool`'s description and signature are unchanged.

## 3. TDD record

Against the Iteration 7 stub, which raised `NotImplementedError("writer_tool is built in Iteration 8.")`, every test in the new file that calls the tool fails. The behaviours were built in this order; the Red and Green notes for each come from the diff, and the mutation checks are those recorded in the review artifacts.

| # | Behaviour | Red asserted | Green added | Refactor |
| :---: | :--- | :--- | :--- | :--- |
| 1 | First draft | The new attempt #1 holds the Writer's draft; the Writer received `{context, candidate, attempt: 1}` with the document's own candidate object; the result is `{doc_id, context, attempt: 1, qa_report: null}` with no error. Failed on the stub | The append, `_invoke_sub_agent` and `set_draft`, and the `for_supervisor()` return. The placeholder row in `test_tools_scout.py` was removed | — |
| 2 | Rule 3: append before the Writer runs | A `BeforeInvocationEvent` hook reading `state` sees `[(1, False)]` | Already met by step 1, since the record must exist to be passed. The test was checked by moving the append after the call, which made it fail | — |
| 3 | Every `check_writer` refusal through the tool | 7 cases × 2 tests: the violation is stored, logged at WARNING with `attempt=-`, and returned with `result=None`; no attempt, agent, token, ledger entry or failure | `check_writer` → `_refuse` before anything else | — |
| 4 | Revision | The Writer receives the latest drafted record (ERROR and WARNING), with the revision wording; the draft goes on the new attempt; a revision after a failed one is #3; INFO "Revision requested" with `doc_id`, the new attempt and the status it follows, before "Sub-agent invocation started" | Passing the latest drafted record; the log line | Folded into the revision helpers |
| 5 | Rule 2 | 3 cases (no fetch, another document's ID, empty ID) × 4 tests: no draft kept, a full `fetch_document` failure with Approach 1's message and a traceback, the draft-less result with `writer_tool failed: src.tools.WriterSourceFetchError`, one ledger entry and a WARNING "Recoverable tool failure". A parity test shows a fetch of another document with the right echoed ID still passes | `WriterSourceFetchError`, `_verify_writer_dereferenced_source`, `_store_draft`; `_recoverable_failure`'s `stage` widened to `FailureStage` | — |
| 6 | Failed calls and telemetry | Recoverable failures (build, provider error, after the fetch) record `stage="writer"` on the attempt and log WARNING; a lost session records `mcp_session`, sets `state.fatal_error` and logs ERROR; the attempt stays and the result is draft-less; a retry is attempt #2 on a fresh agent; exactly one ledger entry on every path, with `WRITER_MODEL_ID` and the configured effort; all five substrate tools attached (P1) | No new code: these run through Iteration 7's `_invoke_sub_agent`. The tests were checked by mutation (dropping the `doc_id`/`attempt` labels, returning `result=None` on failure) | — |
| 7 | Correlation | Every `src.tools` record carries `(run_id, doc_id, attempt)`; every run-log line, SDK lines included, carries its own document's attempt; a refusal reads `-` | The inner `log_context(attempt=…)`. Checked by mutation: without it, 6 tests fail | — |
| 8 | AC1 and AC2 | The rule 8 table through the real tool (rows 1–4, and row 5 then a further revision as #3); a fourth call refused after three failures; the AC2 checker rejects every leak it is built to catch; a Strands agent receives exactly the checked string | Behaviour already built; these passed on their first run | — |
| 9 | Fix round 1, m1 | Rule 2 on `revise=True`: #2 keeps no draft, A1 stays the latest, `check_qa` returns `already_audited` | No production change needed (shared path). Checked by disabling the rule 2 check, which made it fail | — |
| 10 | Fix round 1, m2 | With `check_writer` patched to admit an unaudited revision, the call raises `RuntimeError` and leaves no attempt, ledger entry, failure or log line (2 cases). It failed because the earlier `assert` fired after the append (`FIXES.md`) | `_Revision` and `_revision_source`, called before the append; `_revision_input` now takes the resolved `_Revision`. No `assert` remains under `src/` | Docstrings and annotations |

## 4. Test results

Fresh run by the orchestrator, after this walkthrough was written:

* `uv run pytest -q`: **925 passed**, 0 failed, 0 errors.
* `uv run pytest tests/test_unit/test_tools_writer.py -q`: **72 passed**.
* Tests added by this iteration: **+75 net** over Iteration 7's 850.
  * 72 in `test_tools_writer.py`;
  * −1 in `test_tools_scout.py`, the removed placeholder row;
  * +4 in `test_docs_consistency.py::test_document_uses_no_forbidden_term`, which is parametrized over task records and picks up the four new `.md` files in `iteration-08/`.
* `uvx ruff check src tests`: **All checks passed!**
* No live test or live command was run. Every Writer is a `ScriptedModel` or `FailingModel` over an `OfflineSubstrateSession`.

## 5. Acceptance criteria

| Criterion | Status | Evidence |
| :--- | :---: | :--- |
| Red: rule 3, the record is appended before the Writer runs | ✅ | `test_the_new_attempt_is_appended_before_the_writer_runs` |
| Red: first draft input and storage | ✅ | `test_a_first_draft_hands_the_writer_the_new_record_with_the_documents_own_candidate` asserts identity of `candidate`; `test_a_first_draft_stores_the_writers_draft_on_attempt_one` |
| Red: revision input, storage on attempt n + 1, "Revision requested" log | ✅ | `test_a_revision_hands_the_writer_the_latest_drafted_record_with_its_draft_and_report[ERROR/WARNING]`, `test_a_revision_stores_the_new_draft_on_a_new_attempt_and_leaves_the_audited_one_untouched`, `test_a_revision_logs_revision_requested_with_the_new_attempt_and_the_status_it_follows` |
| Red: rule 2, no draft kept, `FailureRecord(stage="fetch_document", attempt=n)`, one-line error, draft-less result | ✅ | The four `test_an_undereferenced_draft_*` tests × 3 cases, and `test_an_undereferenced_revision_is_not_kept_and_the_audited_draft_stays_the_latest` |
| Red: failed call, `FailureRecord(stage="writer", attempt=n)`, attempt still counts, draft-less result, error set | ✅ | `test_a_failed_call_records_a_writer_failure_on_its_attempt`, `test_a_failed_call_still_uses_its_attempt_and_returns_it_without_a_draft` |
| Red: the result holds `doc_id`, `attempt`, an empty `qa_report` and `run.max_attempts_per_doc`; no draft, candidate or article text | ✅ | `test_a_first_draft_returns_the_new_attempt_without_its_draft_and_no_error`, and `_assert_supervisor_view` on every call |
| Red: `StageTelemetry(stage="writer", doc_id, attempt)` on success and failure | ✅ | `test_every_allowed_call_appends_exactly_one_writer_ledger_entry` (success, 4 failure cases, rule 2), `test_a_revisions_ledger_entry_carries_the_new_attempt_number` |
| Red: every `check_writer` violation through the tool, `already_saved` (P2) included | ✅ | `test_a_refused_call_is_stored_logged_and_returned_with_no_result` and `test_a_refused_call_uses_no_attempt_builds_no_writer_and_spends_nothing`, each × 7: `not_a_candidate`, `already_saved`, `attempt_limit`, `initial_draft_exists`, `not_audited` (no draft; no report), `revise_after_pass` |
| Red: log lines inside the call carry `doc_id` and `attempt` | ✅ | `test_every_src_tools_record_of_a_call_carries_its_document_and_attempt`, `test_every_line_a_call_writes_to_the_run_log_carries_the_run_document_and_attempt` |
| **AC1:** the rule 8 table through the real tools; a failed revision leaves the earlier draft the latest | ✅ | `test_the_rule_8_table_revise_after_error_then_pass` (rows 1–4) and `test_the_rule_8_table_a_failed_revision_leaves_the_earlier_draft_the_latest` (row 5). QA reports are stored with `set_qa_report`, and "qa_tool allowed?" is read from `check_qa` |
| **AC2:** `writer_tool` never returns article text, asserted over every result in the file | ✅ | Every call goes through `_CheckedTool`, which applies `_assert_supervisor_view`: exact keys, no forbidden key at any depth, and no headline, summary, body or CTA the run holds anywhere in the string. `test_the_supervisor_view_check_rejects_every_way_article_text_could_leak` shows the check can fail |
| DoD-1 to DoD-5 | ✅ | §4 above; only scripted models; every new function and branch has a test; the docs test passes inside the suite |
| DoD-6 | ✅ | This file |

## 6. Decisions and deviations

**Decisions (§1.5, or settled from the sources in the pre-flight):**
* **The new attempt number is `attempts_used + 1`.** The plan's "attempt n + 1" read as "latest drafted + 1" would give a second #2 after a failed revision. D-C rules 3 and 4 make the counter the number of attempts, so a revision after a failed one is #3.
* **The result includes `context`.** The plan lists `doc_id`, `attempt` and `qa_report`; §7.2 and Iteration 4's `supervisor_view` include `context`, and the spec is followed.
* **A rule 2 failure is logged** as the D-I WARNING "Recoverable tool failure returned to the Supervisor", with `exc_info`. Its one-line error is `writer_tool failed: src.tools.WriterSourceFetchError`, which does not include the exception's text.
* **A fatal failure keeps `stage="mcp_session"`,** with `doc_id` and `attempt` set, as in D-D and Iteration 7.
* **Refused calls carry `doc_id` and `attempt=-`,** since no attempt was made.
* **"Revision requested" wording and position:** logged after the append and before "Sub-agent invocation started".
* **Private names:** `_SOURCE_FETCH_TOOL`, `_Revision`, `_revision_source`, `_revision_input`, `_store_draft`, `_verify_writer_dereferenced_source`.
* **Test organisation:** `FORBIDDEN_SUPERVISOR_KEYS` and `json_keys` moved to `tests/support/scripted.py`. `already_saved` is set up by assigning `DocumentRecord.saved` directly, and QA reports by `set_qa_report`, because `save_draft` and `qa_tool` are built in Iterations 10 and 9.

**Deviations:**
* **Ledger before store.** The ledger entry and the "completed" log are written by `_invoke_sub_agent` before `_store_draft` runs. This is the ordering already accepted in Iteration 7, carried over.
* **Rule 2's telemetry is kept.** In Approach 1, a Writer call rejected by this check lost its telemetry, because the ledger was written after the check. Here the one ledger entry is already written, as D-B requires.
* No other deviation from the plan.

## 7. Review

Two rounds were used.

**Round 1.**
* **Architect: APPROVED,** no findings. It observed that the `assert` in the then-`_revision_input` ran after the append, so a broken invariant would leave an attempt with no ledger entry.
* **QA: PASS,** with two optional minors:
  * **m1:** no rule 2 test on the `revise=True` path. **Resolved** by `test_an_undereferenced_revision_is_not_kept_and_the_audited_draft_stays_the_latest`.
  * **m2:** the same `assert` concern. **Resolved** by `_revision_source`, which runs before the append and raises `RuntimeError`, tested by `test_a_revision_past_a_broken_not_audited_invariant_raises_before_using_an_attempt[no-draft, draft-without-report]`.
* A fix pass was run to close both, since round 1 allowed it.

**Round 2.**
* **Architect: APPROVED,** no findings.
* **QA: PASS,** no findings.

No item needed a decision. The only risk still open is carried over from Iteration 7: after a fatal error, a later tool call still tries to build an agent until Iteration 12 adds the stop.
