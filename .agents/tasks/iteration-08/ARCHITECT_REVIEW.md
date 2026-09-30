# Iteration 08 — `writer_tool`: Architect review, round 1

**Reviewer:** architect (Stage 3, round 1), against `.agents/skills/architect-review/SKILL.md` and `.agents/skills/code-reviewer/SKILL.md`.
**Scope:** the uncommitted diff on `approach-2/implementation`:
* `src/tools.py` (modified);
* `tests/test_unit/test_tools_writer.py` (new, 69 tests);
* `tests/support/scripted.py` (modified: `FORBIDDEN_SUPERVISOR_KEYS` and `json_keys` moved in);
* `tests/test_unit/test_tools_scout.py` (modified: shared helpers imported, the `writer_tool` placeholder row removed);
* `.agents/docs/IMPLEMENTATION_PLAN.md` (tracker row set to "In progress" only).

**Commands run:**
* `uv run pytest -q` gives **918 passed**.
* `uvx ruff check src tests --no-cache` gives "All checks passed!".
* `uv run --with pyright pyright` on the four changed Python files gives 0 errors in `src/tools.py`, `test_tools_writer.py` and `test_tools_scout.py`. It reports 3 errors in `tests/support/scripted.py`, at lines 143, 305 and 463, all from commit `5b6ae080` (Iteration 2). None is on a line this diff touches.

No live command was run (P4).

---

## 1. Overall verdict

**APPROVED**

`writer_tool` follows D-A, D-C rules 1 to 7 and D-E exactly, ports Approach 1's rule 2 check unchanged, never returns article text (D-F), and moves no control flow out of the Supervisor. There are no blocking findings and no items that need a decision. The three observations in §4 need no change in this iteration.

---

## 2. Pillar audit

### Pillar 1: An agent owns the flow — ✅
* `writer_tool` (`src/tools.py:200-232`) makes exactly one Writer call per Supervisor call. It never calls `qa_tool`, never loops, and never reads a QA status to decide what runs next.
* The only branch on `revise` (`src/tools.py:216`) picks **which record the Writer receives**, as D-E prescribes: the new record for a first draft, the latest drafted record for a revision. It is input assembly. The Supervisor chose `revise`.
* A refusal returns immediately through `_refuse` (`src/tools.py:204-206`). A failure is returned as an error string. Neither suggests a next step: `_one_line_error` names only the exception types.

### Pillar 2: Division of labour and D-F — ✅
* The result is `ToolResult[AttemptRecord](result=record, …).for_supervisor()` (`src/tools.py:232`). `for_supervisor()` applies `supervisor_view()` (`src/schemas.py:519-525, 603-604`), which excludes `draft` and `candidate`.
* The rule 2 error string is `writer_tool failed: src.tools.WriterSourceFetchError`, the type only. The full `WriterSourceFetchError` message, which quotes `source_doc_id`, stays in the `FailureRecord` and in the log. The Supervisor already holds every `doc_id` from the `ScoutReport`, so nothing new leaks even in principle.
* AC2 is enforced structurally. Every tool call in `test_tools_writer.py` goes through `_CheckedTool` → `_assert_supervisor_view` (lines 113-145), which checks:
  * the exact key set;
  * that `qa_report` is null;
  * that no forbidden key appears at any depth;
  * that no headline, summary, body or CTA the run holds appears **anywhere in the string**.

  `test_the_supervisor_view_check_rejects_every_way_article_text_could_leak` (lines 865-884) proves the checker is not vacuous. `test_through_a_strands_agent_the_supervisor_receives_exactly_the_checked_string` (lines 887-903) proves that the checked string is what a Strands agent sees.

### Pillar 3: Custom agent tools (D-A, D-G) — ✅
* **Fresh agent per call.** `build=lambda: build_writer_agent(models.writer, client, hooks=hooks)` (`src/tools.py:224`) runs once per `_invoke_sub_agent` call. `test_a_first_draft_may_be_retried_after_a_failed_call_as_attempt_two` (line 547) confirms the retry starts from an empty conversation.
* **One typed input.** An `AttemptRecord` goes to `run_writer` (`src/agents.py:663`), which sends `writer_view()` with `structured_output_model`. No `preserve_context`, `delegate`, `as_tool()` or agent-in-`tools=`.
* **Keyed by `doc_id`**, with no handles.
* **Ledger on every path.** One `StageTelemetry(stage="writer", doc_id, attempt)` is written on every path, by the reused `_invoke_sub_agent`. That covers success, recoverable failure, fatal failure and rule 2 failure. `_store_draft` deliberately adds no second entry (`src/tools.py:485-508`). `test_every_allowed_call_appends_exactly_one_writer_ledger_entry` covers all six paths, with the effort label.
* **Step order.** The ledger entry and "completed" log come before the store. This is the D-A ordering deviation already accepted in Iteration 7 (`.agents/tasks/iteration-07/WALKTHROUGH.md:136`), carried over unchanged. No state is read in between, and nothing runs concurrently.

### Pillar 4: Guardrails and attempt state (D-C, P2, P3) — ✅
* **Check first.** `check_writer` runs before any mutation (`src/tools.py:204`). Its §7.3 order was locked in Iteration 5. All six `check_writer` guardrails, in seven cases, are reached through the tool. Each has one test that the violation is stored, logged and returned, and one that nothing was spent (lines 640-700). This includes `already_saved` on a saved `WARNING` (P2) and an unknown `doc_id` as `not_a_candidate` (P3).
* **Rule 3.** The attempt is appended before the Writer runs (`src/tools.py:209-214`), proved by a `BeforeInvocationEvent` hook that reads `state` (lines 255-274).
* **The counter.** It is `attempts_used + 1`, so a revision after a failed revision is #3, as D-C rules 3 and 4 require. `test_a_fourth_call_is_refused_whatever_became_of_the_first_three` shows three failed calls exhaust the cap.
* **Slots are set once.** The new record's `draft` is set only through `set_draft`, and the revised record is never written to (`test_a_revision_stores_the_new_draft_on_a_new_attempt_and_leaves_the_audited_one_untouched`).
* **Rule 2 is in `writer_tool`.** It is a byte-for-byte port of Approach 1's `_verify_writer_dereferenced_source` and `WriterSourceFetchError` (`../code-orchestration/src/orchestrator.py:162, 358-367, 485-535`). The logic, the `call_count > 0` test and both messages are identical. Only the docstrings are reworded for the new owner. As in Approach 1, it runs on every Writer call, revisions included (Approach 1 checks inside its revision loop, `orchestrator.py:595-596`). The parity test at line 452 guards against strengthening the check.
* **AC1.** Rows 1 to 5 of the rule 8 table are reproduced through the real `writer_tool` and `set_qa_report`, with "qa_tool allowed?" read from the real `check_qa` (lines 788-837).

### Pillar 5: Benchmark parity — ✅
* `src/agents.py` is not in the diff: the prompts, model IDs and efforts are unchanged.
* The Writer is labelled `WRITER_MODEL_ID` and `efforts.writer`.
* **P1.** `build_writer_agent` is called without `tool_names`, so all five substrate tools are attached. `test_the_writer_is_built_with_all_five_substrate_tools` checks both `tool_filters_seen == [None]` and the tool specs the model received.
* `WRITER_TOOL_DESCRIPTION` and the `(doc_id: str, revise: bool)` signature are unchanged, and match §7.1 and §6.4 word for word.

### Pillar 6: Substrate isolation and lifecycle (D-D) — ✅ (within this iteration's scope)
* A lost session inside a Writer call sets `state.fatal_error`, records `FailureRecord(stage="mcp_session", doc_id, attempt)`, logs at ERROR, and returns the draft-less record with an error. This is the reused Iteration 7 path, tested at line 507.
* The stop itself is Iteration 12's.
* No `mcp-server` import is added.

### Pillar 7: Rendering, telemetry and logging (D-B, D-I) — ✅
* **"Revision requested"** is logged at INFO. It carries `doc_id`, the new attempt, and the QA status it follows (`src/tools.py:475-481`). It is logged after the append, inside `log_context(attempt=n)`, and before "Sub-agent invocation started" (test at line 333).
* **Correlation.** Every `src.tools` record of a call carries `(run_id, doc_id, attempt)`, and so do the run-log-file lines, SDK lines included. A refusal carries `doc_id` and `attempt=-` (lines 711-747).
* **Rule 2 failures** are logged as the D-I WARNING "Recoverable tool failure returned to the Supervisor", with `exc_info`.
* No rendering is touched.

### Pillar 8: Code quality and conventions — ✅
* All imports are at the top of the file and grouped (zero E402).
* Every new signature is fully annotated, and no `dict[str, Any]` crosses a module boundary.
* `_SOURCE_FETCH_TOOL` is a `Final` constant.
* `WriterSourceFetchError` is exported in `__all__` (`src/tools.py:64`), as Approach 1 exported it.
* Widening `_recoverable_failure(stage=…)` from `_SubAgentStage` to `FailureStage` (`src/tools.py:392`) is the minimum change that lets rule 2 record `fetch_document`. The docstring was updated to match.
* Moving `FORBIDDEN_SUPERVISOR_KEYS` and `json_keys` into `tests/support/scripted.py` gives both tool test files one shared copy, rather than having one test module import from another.

---

## 3. Code review findings

**Ruff:**
* In-scope findings (blocking): **0**.
* Pre-existing debt (deferred): **0**.

**Pyright:** 0 in scope. The 3 errors in `tests/support/scripted.py` (lines 143, 305 and 463) are inherited from Iteration 2 and are outside this diff.

**Severity count:** 0 blocker, 0 major, 0 minor.

---

## 4. Anti-patterns and risks

None found. These three observations need no action in this iteration:

1. **A plan wording gap (informational).**
   * **What the sources say.** `IMPLEMENTATION_PLAN.md:516` lists the result as "`doc_id`, `attempt` and an empty `qa_report`" without `context`. `SPECIFICATIONS.md` §7.2 defines `supervisor_view()` as `{doc_id, context, attempt, qa_report}`.
   * **What the code does.** It follows §7.2, which wins under the skill's precedence rule. The implementer recorded this as a decision.
   * **Is it a stop condition?** No. The two sources do not conflict on a contract, because the plan is under-specified rather than contradictory.
2. **The `assert` in `_revision_input` (`src/tools.py:474`).**
   * **What it does.** It states the `not_audited` invariant that `check_writer` has already enforced, so the types narrow without a dead branch. It is the only `assert` under `src/`, and it is unreachable through the tool.
   * **The caveat.** It runs after the append. If a future change to `check_writer` ever broke the invariant, the call would leave an attempt with no ledger entry.
   * **When to act.** This is acceptable as written. If Iteration 9 or 13 touches this function, resolving `latest` before the append would make the invariant failure side-effect-free. This is not a defect today.
3. **Iteration 12 dependency (carried forward).** After a fatal failure, a later `writer_tool` call still builds an agent against the dead session. It records a second `mcp_session` failure, and `fatal_error` keeps the first. Iteration 12's stop mechanism removes this. It is the risk the Iteration 7 review already recorded.

---

## 5. Remediation directives

None. No `FIXES.md` items and no "Needs a decision" items are opened by this review.

---

# Round 2: re-review after fix round 1

**Reviewer:** architect (Stage 3, round 2), against the same two skills.
**Scope:** what fix round 1 changed:
* `src/tools.py`: `writer_tool` now calls `_revision_source(document)` before the append (lines 209-210). The new private frozen dataclass `_Revision` is at lines 469-474, `_revision_source` at lines 477-493, and the reworked `_revision_input` at lines 496-508. `QAReport` is imported from `.schemas`.
* `tests/test_unit/test_tools_writer.py`, with two new tests:
  * `test_a_revision_past_a_broken_not_audited_invariant_raises_before_using_an_attempt` (lines 352-369, two parametrized cases);
  * `test_an_undereferenced_revision_is_not_kept_and_the_audited_draft_stays_the_latest` (lines 472-484).

**Commands run:**
* `uv run pytest -q` gives **924 passed**.
* `uvx ruff check src tests --no-cache` gives "All checks passed!".
* `uv run --with pyright pyright src/tools.py tests/test_unit/test_tools_writer.py` gives 0 errors and 0 warnings.

No live command was run (P4).

## 1. Overall verdict

**APPROVED**

Both round 1 items are resolved. The fix changes no behaviour the Supervisor or a sub-agent can observe, and it opens no new finding.

## 2. Verification of the round 1 items

### m2 / architect observation 2: the `assert` in `_revision_input`, resolved
* No `assert` remains under `src/`, checked by a grep of `src/*.py`.
* **The invariant now fails before anything happens.** `_revision_source` runs after `check_writer` and before `document.attempts.append(record)` (`src/tools.py:205-217`). If the `not_audited` invariant were ever broken, the call would raise `RuntimeError` with no attempt used, no ledger entry, no failure record and no log line. The implementer's Red run observed exactly the defect this closes: the old `AssertionError` escaped after the append.
* **The input the Writer receives is unchanged.** D-E says the Writer gets the latest drafted record. The new record has no draft when it is appended, so `document.latest_drafted` is the same object whether it is read before or after the append. The existing revision tests (lines 286-331) still pass, which confirms it.
* **"Revision requested" is unchanged** (`src/tools.py:501-507`). It is still logged after the append, inside `log_context(attempt=n)`, with the same wording and fields, and before "Sub-agent invocation started". The test at line 333 still asserts that sequence.
* **The new test is sound.**
  * It patches the module global `src.tools.check_writer`, which `writer_tool` looks up at call time.
  * It covers both ways the invariant can break: no draft, and a draft without a report.
  * It asserts on every side-effect channel: `attempts`, Writer turns consumed, `ledger`, `failures`, and `src.tools` log records.
  * It is a legitimate test of a defensive branch. It does not need to be reachable through the real guardrail.
* **Conventions.** `_Revision` follows the module's existing precedent for a private carrier, `_SubAgentFailure` (`src/tools.py:266`): a private frozen dataclass placed next to its only user. Holding `report` separately from `source.qa_report` is what narrows the type without a cast, and the docstrings describe this honestly.

### m1: rule 2 on the `revise=True` path, resolved
* The test at lines 472-484 routes through `_CheckedTool`, so the D-F supervisor-view check also runs on this path. It asserts:
  * `FailureRecord("fetch_document", DOC_ID, 2)`;
  * the draft-less attempt #2 and the one-line type-only error;
  * that the audited attempt #1 is still `latest_drafted` (compared by identity);
  * that `check_qa` returns `already_audited`, which is AC1's "a failed revision leaves the earlier draft as the latest".
* The implementer's mutation check shows the test is not vacuous. No production change was needed, because the path is shared with `revise=False`.

## 3. Pillar re-check (only what the fix touched)

| Pillar | Status | Note |
| :--- | :---: | :--- |
| 1. An agent owns the flow | ✅ | `_revision_source` resolves an input or raises. It chooses no next step and calls no tool. |
| 2. Division of labour, D-F | ✅ | The `RuntimeError` message names only the `doc_id` and `check_writer`. It carries no article text, and it cannot be reached through the real guardrail. |
| 3. Custom agent tools | ✅ | There is still one fresh Writer per call, with one typed input. |
| 4. Guardrails and attempt state | ✅ | The guardrail still runs first. The append still comes before the Writer runs (rule 3). The failure case is now side-effect-free, which is stricter than before. |
| 5. Benchmark parity | ✅ | `src/agents.py`, the prompts, the models, the efforts and the tool binding are all untouched. Rule 2 is still Approach 1's check, unchanged. |
| 6. Substrate lifecycle | Not touched | |
| 7. Telemetry and logging | ✅ | The D-I "Revision requested" event is unchanged. A refused or invariant-broken call writes no ledger entry. |
| 8. Code quality | ✅ | Imports are at the top and grouped, with zero E402. The code is fully annotated, has no dead code, and ruff and pyright are clean. |

## 4. Code review findings

**Ruff:**
* In-scope findings (blocking): **0**.
* Pre-existing debt (deferred): **0**.

**Severity count:** 0 blocker, 0 major, 0 minor.

**Informational.** `uvx ruff format --check` reports 13 files that would be reformatted. That spans pre-existing files, formatting is not a Definition of Done check (`IMPLEMENTATION_PLAN.md` §1.3), and this is not a finding.

## 5. Anti-patterns, risks and remediation

There are no new ones. Round 1 observation 3, that Iteration 12 must stop a run after a fatal failure, is carried forward unchanged.

No `FIXES.md` items and no "Needs a decision" items are opened by this round.
