# Iteration 09 — `qa_tool`: Architect review, round 1

**Reviewer:** architect (Stage 3, round 1), against `.agents/skills/architect-review/SKILL.md` and `.agents/skills/code-reviewer/SKILL.md`.
**Scope:** the uncommitted diff on `approach-2/implementation`:
* `src/tools.py` (modified: the `qa_tool` body at lines 249-278, `_audit_target` at 615-632, `_store_report` at 635-647, and imports);
* `tests/test_unit/test_tools_qa.py` (new, 918 lines, 67 tests);
* `tests/test_unit/test_tools_scout.py` (modified: the `qa_tool` placeholder row removed at line 223);
* `.agents/docs/IMPLEMENTATION_PLAN.md` (the tracker row set to "In progress", nothing else).

`src/agents.py`, `src/schemas.py` and `src/guardrails.py` are unchanged, which I confirmed with `git status --short`.

**Commands run:**
* `uv run pytest -q` gives **991 passed** in 35.6 s.
* `uvx ruff check src tests --no-cache` gives "All checks passed!".
* `uv run --with pyright pyright src/tools.py tests/test_unit/test_tools_qa.py tests/test_unit/test_tools_scout.py` gives 0 errors, 0 warnings.
* `uvx ruff format --check` passes on `src/tools.py` and `test_tools_qa.py`. It reports drift in `test_tools_scout.py` at lines 515, 522, 631 and 930. I confirmed that the same drift is present in the `HEAD` version of that file, and none of those lines is in this diff. `ruff format` is not a DoD gate.
* **Mutation check**, in a scratch copy outside the repository: I removed `hooks=hooks` from `qa_tool`'s build lambda (`src/tools.py:266`) and ran the three `test_tools_*.py` files. They gave **222 passed**, so the mutation survived (see M1). A control mutation in the same copy, which lowered the PASS verdict log to DEBUG, failed 2 tests. That shows the scratch copy's `src` really was the one under test.

No live command was run (P4).

---

## 1. Overall verdict

**APPROVED WITH RESERVATIONS**, which means **CHANGES REQUESTED** for this round.

`qa_tool` follows D-A, D-C rule 8, §6.2, §6.4, §7.2 and §7.3 exactly. It keeps the attempt cap out of QA-Legal's view (DM7), never returns article text (D-F), and moves no control flow out of the Supervisor. There is no architectural violation.

There is one required fix, a 🟡 Major test gap:
* no test shows that the hooks given to `build_tools` reach QA-Legal;
* the Scout and the Writer each have that test;
* the mutation that drops them survives the whole suite.

There are no "Needs a decision" items.

---

## 2. Pillar audit

### Pillar 1: An agent owns the flow — ✅
* `qa_tool` (`src/tools.py:249-278`) makes at most one QA-Legal call per Supervisor call.
  * It calls no other tool and never loops.
  * It never chooses a next step from the verdict.
* The only branch on `QAReport.status` is in `_store_report` (`src/tools.py:642-647`), and it picks the log level alone. Its docstring says so (lines 638-639). No status-driven revision exists in code.
* A refusal returns at once through `_refuse` (line 255).
* A failure returns `_one_line_error`'s string, which names the exception types and no next step.

### Pillar 2: Division of labour and D-F — ✅
* The result is `ToolResult[AttemptRecord](result=latest, …).for_supervisor()` (line 278). `for_supervisor()` applies `supervisor_view()` (`src/schemas.py:519-525`), which excludes `draft` and `candidate`. The Supervisor gets `{doc_id, context, attempt, qa_report}` and the `RunContext`, as §6.4 and §7.2 require.
* On failure, `result` is the still unaudited record, and `error` is the one-line type chain. This matches §6.4 ("a failed call returns `result` when there is one"). The implementer's §1.5 note records it correctly, as the reading §6.4 settles, not as a free choice.
* The `QAReport` is QA-Legal's output, not article text. Returning it whole is D-F's stated design (§5 D-F, "the latest draft's `QAReport` only").
* **Structural enforcement.** Every call in the test file goes through `_CheckedTool` (`tests/test_unit/test_tools_qa.py:152-172`), which runs `_assert_supervisor_view` on every returned string. That check (lines 111-131) asserts:
  * the exact key set;
  * a result equal to the stored record's `supervisor_view()`;
  * a `qa_report` present exactly when `qa_tool` succeeded;
  * no forbidden key at any depth;
  * no article text the run holds anywhere in the string.

  Its own can-fail test (lines 858-879) covers six mutations. The Strands pass-through test (lines 882-896) proves the checked string is what the Supervisor's `toolResult` carries.

### Pillar 3: Custom agent tools (D-A, D-G) — ✅
* **Order.** `check_qa` (step 1), then `_audit_target`, then `_invoke_sub_agent`: a fresh build (step 2), a run with the typed input and `structured_output_model` (step 3), the ledger (step 5) and the log (step 6). Then `_store_report` (step 4), and `ToolResult` (step 7).
  * The ledger comes before the store. That is the D-A step 4/5 ordering accepted in Iteration 7 (`iteration-07/WALKTHROUGH.md:136`) and carried into Iteration 8, so it is not a new deviation.
  * In practice, nothing reads state between the two steps, and execution is sequential (D-H).
* **Fresh per call.** `build=lambda: build_qa_legal_agent(models.qa_legal, client, hooks=hooks)` (line 266) runs inside each call. The retry test (lines 673-686) shows the second call starts from an empty conversation.
* **One typed input.** `run_qa_legal(agent, latest, …)` receives the `AttemptRecord` that `_audit_target` resolved. The runner (unchanged since Iteration 6) sends `record.qa_view()` and requests `QAReport`.
* **No `preserve_context`, `delegate`, `as_tool` or agent in `tools=`.**
* **Keyed by `doc_id`.**
* **`_audit_target`** (lines 615-632) resolves the target **before** anything is built, and raises `RuntimeError` if `check_qa`'s invariant were ever broken. This mirrors Iteration 8's `_revision_source` (lines 515-531), accepted in its fix round 1. The test at lines 694-712 shows that a broken invariant spends nothing and leaves no trace.
* ⚠️ **Hooks.** `hooks=hooks` is passed correctly, but nothing tests it: see M1.

### Pillar 4: Guardrails and attempt state (D-C, P2, P3) — ✅
* `check_qa` (`src/guardrails.py:171-199`, unchanged) runs first, in the §7.3 order: `not_a_candidate` → `already_saved` → `no_draft` → `already_audited`.
* All four `check_qa` violations are reached through the tool, in 7 cases × 2 tests (lines 509-560), including:
  * P3, the unknown `doc_id`;
  * P2, both a saved `WARNING` document and a saved document with an unaudited later draft, which proves `already_saved` comes before rule 8;
  * rule 8 row 5, `already_audited` after a failed revision.
* Each violation is stored, logged at WARNING with `attempt=-`, and returned with `result=None`. The refusal builds no agent and spends nothing.
* **Slots are set once.** `set_qa_report` fills the one empty slot on `latest` itself. `latest` is the object held in `DocumentRecord.attempts`, as the identity checks at lines 269-270 and 282-283 show. Nothing is removed, and no attempt is appended.
* **The report goes to `latest_drafted`,** not to a later attempt with no draft (lines 275-283 and 435-442).
* **AC1** is reproduced through the real `writer_tool` and `qa_tool` from one `build_tools` call (lines 776-838):
  * rows 1 to 4 of the rule 8 table, with the `already_audited` repeat spending nothing;
  * row 5, then a successful revision #3 that is audited.

### Pillar 5: Benchmark parity — ✅
* `QA_LEGAL_MODEL_ID` (`gpt-5.4`) and `efforts.qa_legal` (default `medium`) label the call. The effort comes from `SubAgentEfforts`, so an `.env` override reaches the telemetry (lines 420-432, 623-633).
* **P1.** No `tool_names` is passed. The test at lines 445-455 asserts `tool_filters_seen == [None]`, that all five substrate specs reach the model, and that the system prompt is `QA_LEGAL_SYSTEM_PROMPT`.
* **Prompts.** The QA-Legal prompt and runner are unchanged in this diff, and Iteration 6's parity tests still pass.
* **DM7 and AC2.**
  * `_CheckedTool` checks every QA-Legal user turn after every call, against the cap phrasings and `RunContext` keys (lines 135-172).
  * The attempt-3 case (lines 720-732) is covered.
  * The check has its own can-fail test (lines 735-741).
  * Excluding the digit alone is right: §7.2's `qa_view()` deliberately carries `attempt`.
* Template, cost basis and sequential execution: not touched by this iteration.

### Pillar 6: Substrate isolation and lifecycle (D-D) — ✅
* A lost session inside QA-Legal's turn records `FailureRecord(stage="mcp_session", doc_id, attempt)`, sets `state.fatal_error` and logs at ERROR, through Iteration 7's `_fatal_failure` (test at lines 657-670).
* The stop itself is Iteration 12's, as the plan says.
* `src.tools` imports only the reused `mcp_client` module.

### Pillar 7: Rendering, telemetry and logging (D-B, D-I) — ✅
* **Ledger.** There is one `StageTelemetry(stage="qa_legal", doc_id, attempt=latest.attempt)` per allowed call, on success and on every failure path (lines 420-442 and 623-633). The failed-call telemetry comes from `event_loop_metrics` through `_failed_call_telemetry`.
* **D-I events.**
  * "QA verdict PASS" is logged at INFO with `doc_id` and `attempt` (lines 373-391).
  * "QA verdict WARNING/ERROR" is logged at WARNING with every issue, not a count (lines 394-412).
  * The "Sub-agent invocation started / completed" pair is logged.
  * On failure, the "Recoverable tool failure" WARNING is logged, and no verdict.
* **Correlation.** Every `src.tools` line of an audit carries `(run_id, doc_id, attempt)` from the nested `log_context` (lines 904-918).
* Rendering: not touched by this iteration.

### Pillar 8: Code quality and Python conventions — ✅ with one test gap
* Imports are at the top and grouped. The multi-line `from .guardrails import (...)` is a `ruff format` wrap. There is no E402.
* Every new signature is annotated: `_audit_target(document: DocumentRecord) -> AttemptRecord` and `_store_report(record: AttemptRecord, report: QAReport) -> None`. Pyright gives 0 errors.
* The docstrings are honest. `_audit_target`'s explains why it runs before the build, and `_store_report`'s states that the status decides only the log level.
* There is no dead code. The `NotImplementedError` stub is gone, and so is its placeholder row in `test_tools_scout.py`; the `save_draft` row stays.
* Ruff: **0 in-scope, 0 pre-existing.**
* **Style note, no change needed.** `qa_tool` builds `error` with an `if`/`else` (lines 273-277), where `writer_tool` uses a conditional expression (line 246). The difference is justified: the success branch here has a side effect and no return value.

---

## 3. Code review findings

| # | Severity | File and lines | Finding |
| :---: | :---: | :--- | :--- |
| M1 | 🟡 Major | `src/tools.py:266`; `tests/test_unit/test_tools_qa.py` | `hooks=hooks` on QA-Legal's build is untested. Removing it leaves all 222 `test_tools_*.py` tests green. The Scout (`test_tools_scout.py:404-416`) and the Writer (`test_tools_writer.py:255-274`) each have the test. D-I requires the logging hook on every sub-agent, so a silent regression here would drop QA-Legal's tool-call logs, the substrate calls that verify citations. This falls under DoD-4 and the code-reviewer skill's "a test that would also pass against a stub is not coverage" |
| m1 | 🟢 Minor, **optional** | `tests/test_unit/test_tools_qa.py:160, 175-185, 568` | The model parameters of the test helpers are typed `Any` (`_CheckedTool.__init__`'s `qa`, `_tools`' `qa` and `writer`, and the first element of `_failing_qa`'s return tuple). `ScriptedModel \| FailingModel`, or `strands.models.model.Model`, would be more precise. Pyright is clean either way, and Iterations 7 and 8 use the same style, so this is non-blocking |

No other findings. Naming, PEP 8, dead code and path handling are clean in every file this iteration touched.

---

## 4. Anti-patterns and risks

* **Autonomy leak: none.** The verdict drives only the log level. There is no code path from `qa_tool` to `writer_tool` or `save_draft`.
* **Parity drift: none.** The model, effort, prompt, runner and tool binding are unchanged.
* **Article text towards the Supervisor: none.**
  * The result is the `supervisor_view()`, and the error is the type chain alone.
  * The `_audit_target` `RuntimeError`, if ever raised, would reach the Supervisor through Strands' tool-error path. Its message names only the `doc_id` and the guardrail, no article text. It is unreachable while `check_qa` holds.
* **State coupling.** `_store_report` writes to the `latest` object resolved before the call. Execution is sequential (D-H) and QA-Legal cannot change `RunState`, so the target cannot change between the resolution and the store.
* **Iteration 12 risk, carried forward.** A fatal failure still returns its error to the Supervisor. The stop is Iteration 12's spike, unchanged from Iterations 7 and 8.

---

## 5. Remediation directives

1. **M1 (required).** Add a test to `tests/test_unit/test_tools_qa.py` that proves the hooks given to `build_tools` reach QA-Legal.
   * Mirror `test_tools_writer.py:255-274` or `test_tools_scout.py:404-416`: a `HookProvider` that counts `BeforeInvocationEvent`s.
   * Let `_tools` and `_qa_tool` take `hooks: tuple[HookProvider, ...] = ()` and pass it to `build_tools`.
   * Assert exactly one invocation after one allowed `qa_tool` call, and zero after a refused one.
   * The test must fail with `hooks=hooks` removed from `src/tools.py:266`. Record that mutation check in the fix notes.
   * Source: D-I ("a logging hook … is attached to the Supervisor **and** to every sub-agent"), `IMPLEMENTATION_PLAN.md` §1.3 DoD-4, and Gate 1.
   * No `src/` change is needed.
2. **m1 (optional).** If you touch the helpers for M1, you may narrow the `Any` model parameters named in §3. This is not required.

**Verdict: CHANGES REQUESTED** (one 🟡 Major test gap; no architectural violation, no "Needs a decision").

---

# Iteration 09 — `qa_tool`: Architect review, round 2

**Reviewer:** architect (Stage 3, round 2), re-checking fix round 1 against the same two skills.
**Scope of the fix:** `tests/test_unit/test_tools_qa.py` only (918 → 952 lines, 67 → 71 tests).
* `src/tools.py` has the same three hunks as in round 1 (`@@ -20,19`, `@@ -237,7`, `@@ -574,6`). `hooks=hooks` is still at line 266.
* `tests/test_unit/test_tools_scout.py` still differs from `HEAD` by the one removed placeholder row.
* `.agents/docs/IMPLEMENTATION_PLAN.md` still differs by the tracker row alone.

**Commands run:**
* `uv run pytest -q` gives **998 passed** in 33.3 s. `tests/test_unit/test_tools_qa.py` alone gives 71 passed.
* `uvx ruff check src tests --no-cache` gives "All checks passed!".
* `uvx ruff format --check src/tools.py tests/test_unit/test_tools_qa.py` gives "2 files already formatted".
* **Mutation re-check**, in a scratch copy outside the repository:
  * I changed `src/tools.py:266` to `build_qa_legal_agent(models.qa_legal, client)`.
  * `import src.tools` resolved to the scratch copy, so the mutant was the code under test.
  * The three `test_tools_*.py` files gave **1 failed, 225 passed**. The failure is `test_the_hooks_given_to_build_tools_reach_qa_legal_and_only_when_it_is_built[allowed]` at line 489. In round 1, the same mutant gave 222 passed. **The mutation is now killed.**

No live command was run (P4).

## 1. Overall verdict

**APPROVED.** M1 is closed, and so is QA's F-1, which was the same defect. The optional m1 and O-1 are applied correctly. The fix introduces no new finding. There is no architectural change, and no "Needs a decision" item.

## 2. Verification of each round 1 item

| Item | Status | Evidence |
| :--- | :---: | :--- |
| **M1 / F-1** (🟡 Major, required) | ✅ Closed | `_tools` (lines 179-197) and `_qa_tool` (200-210) take `hooks: tuple[HookProvider, ...] = ()` and pass it to `build_tools`. `_RecordingHooks` (465-476) matches `test_tools_scout.py:398-409` line for line. The test (478-489) is parametrised over `allowed` (count 1, `error` is `None`) and `already_audited` (count 0, `error` set). That also proves a refusal builds no QA-Legal agent. It still goes through `_CheckedTool`, so the D-F and DM7 checks hold on both calls. My independent mutant is killed |
| **m1** (🟢 Minor, optional) | ✅ Applied | The model parameters are now typed `strands.models.model.Model` (import at line 19): `_CheckedTool.__init__` (164), `_tools` (182-183, with `writer: Model \| None`), `_qa_tool` (203) and `_failing_qa`'s tuple (602). This is the type `SubAgentModels` declares. The `isinstance(self._qa, ScriptedModel)` narrowing at line 173 is still correct. The `Any`s left are on arbitrary JSON and `**arguments`, and they are legitimate |
| **O-1** (QA, optional) | ✅ Applied | `_CAP_PHRASES` (137-148) gains `"remaining"` and `"of 3"`. Its can-fail test (769-775) is parametrised over the tuple, so both new phrases are proven to be rejected. The digit-only control, `{"attempt": 3}`, still passes. No QA-Legal user turn in the file contains either phrase |
| **O-2** (QA, info) | — Not touched, correct | The pre-existing `ruff format` drift in the untouched lines of `test_tools_scout.py` is out of scope, as round 1 recorded |

## 3. Re-check of what the fix touched

* **Pillars 1 to 7: unchanged since round 1.** No `src/` line moved. The fix adds no control flow, no article-text path towards the Supervisor, and no parity change.
* **Pillar 8.** The new code is fully annotated, its imports are at the top and grouped (`strands.hooks` and `strands.models.model` sit among the third-party imports), and there is no E402. Ruff gives **0 in-scope and 0 pre-existing** findings.
  * The implementer kept both `"attempts remaining"` and `"remaining"`. The first is now redundant, but it is harmless, and the implementer declared it. No change is needed.
* **Info, no action.** `_RecordingHooks` now exists, identical, in both `test_tools_scout.py:398` and `test_tools_qa.py:465`. A shared helper in `tests/support/` could replace them. Each test module in Iterations 7 and 8 keeps its own local helpers, so this follows the house style. It is not a finding, and I opened no `FIXES.md` item for it.

## 4. Remediation directives

None.

**Verdict: APPROVED**
