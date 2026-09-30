# Iteration 08 — `writer_tool`: QA review, round 1

**Reviewer:** qa subagent (criteria: `.agents/skills/code-reviewer/SKILL.md`)
**Diff reviewed:** uncommitted working tree on `approach-2/implementation`, on top of `e8da783`:
`src/tools.py`, `tests/support/scripted.py`, `tests/test_unit/test_tools_scout.py`, `.agents/docs/IMPLEMENTATION_PLAN.md` (tracker row only) and the new `tests/test_unit/test_tools_writer.py`.

## 1. Summary and verdict

**Verdict: PASSED.**

`writer_tool` does what Iteration 8 promises. The call runs in this order:
1. `check_writer` → `_refuse`;
2. append a new `AttemptRecord` (`attempts_used + 1`, sharing the document's own candidate object);
3. the Writer's input: the new record, or on a revision the latest drafted record;
4. `_invoke_sub_agent`;
5. the rule 2 check → `set_draft`;
6. `ToolResult[AttemptRecord].for_supervisor()`.

Rule 2 is a faithful port of Approach 1's `_verify_writer_dereferenced_source`, with the same two checks, the same `call_count > 0` test and the same message text. I ran the suite and ruff myself, and both counts in the implementer's report match reality.

I found no blocker and no major. There are two minor, non-blocking observations (§5).

### Commands run and real output

| Command | Real result |
| :--- | :--- |
| `uv run pytest -q` | `918 passed in 31.56s`. No warnings summary, no errors |
| `uv run pytest tests/test_unit/test_tools_writer.py -q` | `69 passed` (the report claims 69 tests) |
| `uvx ruff check src tests --no-cache` | `All checks passed!` |
| `uv run pytest -m live --collect-only -q` | `no tests collected (918 deselected)` |

The only live command run was `--collect-only`. No CLI was run.

### Independent mutation check (on a scratch copy outside the repo)

I copied `src/` and `tests/` to the session scratchpad and ran `test_tools_writer.py` against 10 hand-made mutations of `src/tools.py`, using the project venv. Every mutation was killed:

| Mutation | Failing tests |
| :--- | :---: |
| Rule 2: fetch check disabled | 4 |
| Rule 2: `source_doc_id` check disabled | 8 |
| `revise=True` hands the Writer the new record | 6 |
| `check_writer` skipped | 16 |
| Draft kept despite a rule 2 failure | 3 |
| Rule 2 failure recorded as stage `writer` | 3 |
| Attempt number always 1 | 9 |
| Candidate copied, not shared | 2 |
| `doc_id` dropped from the outer log context | 13 |
| "Revision requested" wording changed | 1 |

The tests would not pass against a stub or a weakened implementation.

## 2. Gate matrix

| Gate | Topic | Status | Notes |
| :--- | :--- | :---: | :--- |
| 1 | Strict TDD | ✅ | The report gives nine TDD steps, each with its expected Red failure: the stub's `NotImplementedError`; a `KeyError` or no violation stored; the new empty record sent instead of #1; the draft kept with no failure. Tests that passed on first run (rule 3, telemetry, correlation) were each confirmed by a stated mutation, and my own mutations confirm the suite is non-vacuous. Every new `src/` function and branch is exercised: `writer_tool` (both `revise` values, refusal, success, recoverable and fatal paths), `_revision_input`, `_store_draft` (store and reject) and `_verify_writer_dereferenced_source` (both raises and the pass). The tests are unit tests only, which is correct for this iteration |
| 2 | Zero-token testing | ✅ | Every Writer is a `ScriptedModel` or `FailingModel`, over `offline_client(OfflineSubstrateSession())`. The one Strands `Agent` built directly (the pass-through test) uses a `ScriptedModel`. Environment isolation (`tests/conftest.py`) is unchanged. `addopts` deselects `live`, and 918 are deselected under `-m live` |
| 3 | Pydantic v2 contracts | ✅ | No model changed. `AttemptRecord`, `FailureRecord` and `ToolResult` are used as §6 defines them. `_recoverable_failure(stage: FailureStage)` is widened to the spec's `FailureStage` literal. No removed model reappears, and no new `dict[str, Any]` crosses a module boundary: the new `json_keys(value: Any)` is a test helper |
| 4 | Guardrails and attempt cap | ✅ | All 6 `check_writer` guardrails are reached through the tool: `not_a_candidate`, `already_saved` (P2, with a WARNING saved and then `revise=True`), `attempt_limit`, `initial_draft_exists`, `not_audited` (no draft; no report) and `revise_after_pass`. Each refusal is stored, logged at WARNING and returned with `result=None`, and uses no attempt, agent, ledger entry or failure. The check runs before the append (§7.3, D-A step 1). The append comes before the Writer runs (rule 3), shown by a `BeforeInvocationEvent` hook reading `state`. `MAX_ATTEMPTS_PER_DOC = 3`: three failed calls use every attempt, and a fourth call is `attempt_limit` |
| 5 | Strands integration and telemetry | ✅ | The Writer is built fresh per call through `build_writer_agent`; a retry starts from a one-message conversation. It is built with all five substrate tools (`tool_filters_seen == [None]`, P1). One `StageTelemetry(stage="writer", doc_id, attempt)` is recorded on every path: success, build failure, provider error, failure after the fetch, fatal, and a rule 2 rejection. Each is labelled `WRITER_MODEL_ID` and `efforts.writer`, and counts both round trips (300/45 tokens). `extract_telemetry` is unchanged and remains the only reader of `get_summary()` |
| 6 | No article text for the Supervisor | ✅ | Every call in the file goes through `_CheckedTool` / `_assert_supervisor_view`. It checks the key set `{doc_id, context, attempt, qa_report}`, `qa_report` null, no forbidden key at any depth, and none of the run's headline, summary, body or CTA strings in the returned text. A 5-case negative test proves the checker is non-vacuous, and a Strands pass-through test proves the checked string is what the Supervisor receives |
| 7 | Drafts and logging | ✅ | No drafts are rendered in this iteration (n/a). For logging: "Revision requested" is at INFO with `doc_id`, the new attempt and the QA status it follows, and is absent on a first draft. "Recoverable tool failure" is a WARNING with `exc_info`; "Guardrail violation" is a WARNING; the fatal path logs at ERROR. The run-log file test shows every line, SDK lines included, carrying `run_id`, `doc_id` and `attempt`, and a refusal reads `attempt=-` |
| 8 | Python and subprocess safety | ✅ | Complete annotations, imports at the top, ruff clean. There is no new path handling beyond `Path(...)` in tests. After the suite, the only `python.exe` and `uv.exe` processes left are the harness's own MCP servers (parents: `claude.exe`, started before this run); none belongs to pytest. The pytest output is clean |

## 3. Acceptance criteria and Definition of Done

| # | Criterion | Status | Evidence |
| :--- | :--- | :---: | :--- |
| Red-1 | Rule 3: the attempt is appended before the Writer runs | ✅ | `test_the_new_attempt_is_appended_before_the_writer_runs` (the hook sees `[(1, False)]`) |
| Red-2 | First draft: the Writer gets `{context, candidate, attempt: 1}`, the candidate is the same object, and the draft is set | ✅ | `test_a_first_draft_hands_the_writer_the_new_record_with_the_documents_own_candidate` (`is` identity) and `test_a_first_draft_stores_the_writers_draft_on_attempt_one` |
| Red-3 | Revision: the Writer gets the latest drafted record, output goes on attempt n + 1, and INFO "Revision requested" is logged | ✅ | `test_a_revision_hands_the_writer_…` (ERROR and WARNING), `test_a_revision_stores_the_new_draft_on_a_new_attempt_…`, `test_a_revision_after_a_failed_one_is_attempt_three_…` and `test_a_revision_logs_revision_requested_…` |
| Red-4 | Rule 2: no draft kept, `FailureRecord(stage="fetch_document", attempt=n)`, a one-line error, and a draft-less result | ✅ | Three cases (no fetch, another ID, empty ID) × 4 tests, plus the parity test that a fetch of another document with the right echoed ID is accepted. The message text matches Approach 1 word for word |
| Red-5 | Failed call: `FailureRecord(stage="writer", attempt=n)`, the attempt counts, a draft-less result and an error | ✅ | Build, provider and post-fetch failures. The fatal path gives `mcp_session` with `doc_id` and `attempt`, which is consistent with Iteration 7 |
| Red-6 | Supervisor result: `doc_id`, `attempt`, empty `qa_report`, plus `run.max_attempts_per_doc`; no draft, candidate or text | ✅ | `test_a_first_draft_returns_the_new_attempt_without_its_draft_and_no_error`, and `_assert_supervisor_view` on every call |
| Red-7 | `StageTelemetry(stage="writer", doc_id, attempt)` on success and on failure | ✅ | `test_every_allowed_call_appends_exactly_one_writer_ledger_entry` (6 cases) and `test_a_revisions_ledger_entry_carries_the_new_attempt_number` |
| Red-8 | Every `check_writer` violation through the tool, `already_saved` (P2) included | ✅ | `REFUSALS`: 7 cases × 2 tests |
| Red-9 | Log lines inside the call carry `doc_id` and `attempt` | ✅ | `test_every_src_tools_record_of_a_call_carries_…` and `test_every_line_a_call_writes_to_the_run_log_carries_…` |
| AC1 | The rule 8 table is reproduced through the real tools; a failed revision leaves the earlier draft the latest | ✅ | `test_the_rule_8_table_revise_after_error_then_pass` (rows 1–4) and `test_the_rule_8_table_a_failed_revision_leaves_the_earlier_draft_the_latest` (row 5, then a revision from A1 as #3). "`qa_tool` allowed?" is read from `check_qa`, which is legitimate while Iteration 9 is pending |
| AC2 | `writer_tool` never returns article text, asserted over every result in the file | ✅ | `_CheckedTool` wraps every call. The checker's non-vacuity is proven by 5 mutations |
| DoD-1 | Full suite passes | ✅ | 918 passed, 0 failed, 0 errors |
| DoD-2 | Lint is clean | ✅ | `All checks passed!` |
| DoD-3 | No live model call | ✅ | Only scripted or failing models over the offline substrate |
| DoD-4 | Every new `src/` function is tested | ✅ | See Gate 1 and the mutation table |
| DoD-5 | Docs match code | ✅ | `test_docs_consistency.py` is inside the passing 918 |
| DoD-6 | `WALKTHROUGH.md` written | ⏳ | Stage 4, the orchestrating agent's job; not yet due |

**Passed: 16 of 16 applicable** (9 Red items, 2 ACs, DoD-1 to DoD-5). DoD-6 is pending by design.

### Spec parity checks

* **§7.3 check order:** `check_writer` (Iteration 5) is called first and unchanged.
* **§7.2:** the result keys match `supervisor_view()`, including `context`. The implementer was right to follow §7.2 over the plan's shorter list.
* **D-E:** the Writer's revision input is the latest drafted record itself (`attempt` = n), and the output goes on n + 1.
* **D-A order:** the ledger entry is written before the store. This deviation was accepted in Iteration 7 and is repeated knowingly.
* **Approach 1 parity:** the `WriterSourceFetchError` docstring semantics, `_SOURCE_FETCH_TOOL`, the `call_count > 0` test and both messages are identical to `../code-orchestration/src/orchestrator.py`.
* **Substrate:** the fixture document `inail-2026-ot23` exists in the live `hse-easy-mock` (checked with `get_document_by_id`). The shapes the tests rely on are the offline session's, which is unchanged in this iteration.

## 4. Findings by severity

* **Blocker:** none.
* **Major:** none.
* **Minor:** 2 (below). Neither requires a change before the iteration is marked complete.

## 5. Minor observations

**m1: rule 2 is not exercised on the `revise=True` path.** File: `tests/test_unit/test_tools_writer.py`, rule 2 section.
* All `RULE_2_CASES` run with `revise=False`. The code path is shared (`_store_draft` does not depend on `revise`), so this is not untested production code.
* A revision rejected by rule 2 is, however, exactly the rule 8 table's row 5 by another route: attempt #2 with no draft, and A1 still the latest and audited.
* Optional fix: add one test that arranges `_add_attempt(state, DOC_ID, status="ERROR")`, calls `writer_tool(revise=True)` with `[tool_use_turn("ArticleDraft", _REVISED)]` (no fetch), and asserts:
  * `latest_drafted` is attempt #1;
  * `check_qa(state, DOC_ID)` is `already_audited`;
  * the failure is `("fetch_document", DOC_ID, 2)`.

**m2: the only `assert` in `src/` sits after the append and outside `_invoke_sub_agent`'s `try`.** File: `src/tools.py`, `_revision_input`, around line 474.
* The invariant holds today, because `check_writer` refuses `revise=True` without an audited latest draft.
* If the invariant were ever broken, the attempt would be consumed with no ledger entry and no `FailureRecord`, and an `AssertionError` would escape into the Supervisor's event loop. Under `python -O` it would become an `AttributeError` instead.
* The implementer flagged this and asked for a view. My view: acceptable as written for a proof of concept.
* Optional alternative: resolve `document.latest_drafted` before the append, and raise a `RuntimeError` in its place. The log line still needs the new attempt number, so it can stay after the append.

Not a finding: a telemetry entry named `get_document_by_id` with `call_count == 0` is not exercised as its own case. Strands never reports one, and the condition is Approach 1's, kept for parity.

---

# Round 2: re-review after fix round 1

**Verdict: PASSED.** Both round 1 minors are resolved, and the fix introduces no new finding.

## R2.1 Commands run and real output

| Command | Real result |
| :--- | :--- |
| `uv run pytest -q` | `924 passed in 35.47s`. No warnings summary, no errors. This matches the report's 924 |
| `uv run pytest tests/test_unit/test_tools_writer.py -q` | `72 passed`, matching the report's 69 → 72 |
| `uvx ruff check src tests --no-cache` | `All checks passed!` |
| `uv run pytest -m live --collect-only -q` | `no tests collected (924 deselected)` |

The suite grew by 6: the writer file's 3 tests, plus 3 from `test_docs_consistency.py`, which parametrizes over the new review files in this folder. The only live command run was `--collect-only`.

## R2.2 Fix verification

**m1 (rule 2 on `revise=True`): resolved.**
* `test_an_undereferenced_revision_is_not_kept_and_the_audited_draft_stays_the_latest` goes through `_CheckedTool`, so the D-F Supervisor-view check also covers it.
* It asserts:
  * the failure `("fetch_document", DOC_ID, 2)`;
  * the draft-less result for attempt #2;
  * the one-line `WriterSourceFetchError` error;
  * `latest_drafted is` the audited #1;
  * `check_qa` returns `already_audited`.
* This is the rule 8 table's row 5, reached by the rule 2 route.
* Independent mutation (scratch copy): with `_verify_writer_dereferenced_source` made a no-op, the test fails.

**m2 (`assert` after the append): resolved.**
* `writer_tool` now calls `_revision_source(document)` before `document.attempts.append(record)` (`src/tools.py:210`). It still runs after `check_writer` → `_refuse`, so the §7.3 order is unchanged.
* `_revision_source` raises `RuntimeError` naming the `doc_id` and `check_writer` when there is no latest draft, or when that draft has no report.
* A grep of `src/` finds no `assert` statement.
* "Revision requested" is still logged after the append, from `_revision_input`, with the same wording. The existing event-order test still passes: "Revision requested", then "Sub-agent invocation started", then "Sub-agent invocation completed".
* `test_a_revision_past_a_broken_not_audited_invariant_raises_before_using_an_attempt` covers both cases, no draft and a draft without a report. Its `check_writer` monkeypatch targets `src.tools.check_writer`, the name the tool resolves at call time. It asserts:
  * the attempts are unchanged;
  * the Writer consumed 0 turns;
  * the ledger and failures are empty;
  * no `src.tools` record was logged.
* Independent mutation (scratch copy): with the `_revision_source` call moved back to after the append, both cases fail.
* `_Revision` is a private frozen dataclass inside `src/tools.py`. It crosses no module boundary and is not a §6 contract, so Gate 3 is unaffected.
* Letting the `RuntimeError` escape to the Supervisor's event loop is correct. It marks a broken code invariant, not a recoverable call failure, and it cannot happen while `check_writer` holds.

## R2.3 Gates and acceptance criteria

* All eight gates are still ✅. The changes touch only Gate 1 (two new tests with a Red for m2 and a mutation for m1), Gate 4 (a refusal still comes before the append; the invariant now fails before it) and Gate 8 (after my own run, no `python.exe` or `uv.exe` younger than 30 minutes was running).
* One process note: during this review a mistyped mutation command of mine left a stray `python -` reading stdin. I found its process tree by PID, killed it, and confirmed it was gone. It did not come from the suite.
* Acceptance criteria: **16 of 16 applicable still pass** (Red-1 to Red-9, AC1, AC2, DoD-1 to DoD-5). The evidence from round 1 still applies, and the new tests strengthen Red-3, Red-4 and AC1. DoD-6 (`WALKTHROUGH.md`) is still Stage 4's.

## R2.4 Findings

* Blocker: 0. Major: 0. Minor: 0.
* No `FIXES.md` items and no "Needs a decision" items.
