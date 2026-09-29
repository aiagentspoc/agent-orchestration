# Iteration 5 — Architect Review (Stage 3, round 1)

**Reviewer:** Lead Architect, 2026-09-29.
**Scope:** the uncommitted working tree on `approach-2/implementation` against `f24f774` (Iteration 04):
* new, untracked: `src/guardrails.py` and `tests/test_unit/test_guardrails.py`;
* modified: `tests/test_unit/test_docs_consistency.py` and `tests/test_unit/test_module_structure.py`;
* the orchestrator's own edit to `IMPLEMENTATION_PLAN.md`, which is only its §3 row (`⏳ Pending` → `🔄 In progress`).

**Criteria:**
* `.agents/skills/architect-review/SKILL.md` and `.agents/skills/code-reviewer/SKILL.md`;
* `AGENTS.md`;
* `IMPLEMENTATION_PLAN.md` §1, §2 (P1–P10), §4 and Iteration 5;
* `SPECIFICATIONS.md` D-C, §6.2, §6.4–§6.7, §7.1 and §7.3;
* `DESIGN.md`;
* Approach 1's `_validate_scope_bounds` (`../code-orchestration/src/orchestrator.py:436-477`, read only).

## 1. Overall verdict

**APPROVED WITH RESERVATIONS**

`src/guardrails.py` does what Iteration 5 asks, and nothing more:
* four pure check functions over `RunState`;
* the exact §7.3 order;
* all 12 `GuardrailName` values produced;
* no mutation, no logging and no I/O;
* no code that chooses or suggests a next step.

The data sources are the ones D-C and §7.3 prescribe. The `invalid_scope` date logic is Approach 1's, with the same round-trip and the same strict `>`. Nothing blocks.

The one reservation is Minor, A-m1. Pyright reports 4 type errors in the new test file, at `tests/test_unit/test_guardrails.py:148` and `:661`. They come from `**dict` keyword unpacking and from reading back `pytest.param(...).values`. The production module is pyright-clean. The fix is in `FIXES.md`.

**Verified independently:**
* `uv run pytest`: **629 passed**, 0 failed, 0 errors. That is 416 at `f24f774` plus 213 new, matching the implementer's report.
* `uvx ruff check src tests --no-cache`: **All checks passed**. That is 0 in-scope findings and 0 pre-existing.
* `uv run pytest -m live --collect-only`: 0 collected, 629 deselected.
* `uvx pyright src/guardrails.py`: 0 errors. `uvx pyright tests/test_unit/test_guardrails.py`: 4 errors (A-m1).
  * Across `src tests`, pyright reports 134 errors. The other 130 are in files this iteration did not touch; they are pre-existing and are not assessed here.
* `grep` of `src/guardrails.py` for `logging`, `open(`, `print(`, `.append` and `state.<field> =`: no hit, apart from the word "logging" in the module docstring.
* The imports are `datetime`, `typing`, `pydantic` and `.schemas` only: no `strands`, no `mcp_client` and no `mcp_server`.

## 2. Pillar audit

### Pillar 1 — An agent owns the flow: ✅
* **The checks only return refusals.** Each check returns a `GuardrailViolation` or `None`; `check_scout` returns the built `PipelineScope`. No check calls a tool, picks a document, or branches on a QA status to choose an action.
  * The status branches (`src/guardrails.py:161` and `:222`) exist only to refuse: `revise_after_pass`, and `error_with_attempts_remaining`.
* **No message names a next call.** I read all twelve messages (`:78`, `:91`/`:116`/`:119`, `:146-147`, `:157`, `:166`, `:190`, `:196-197`, `:227-229`, `:238-239`, `:255`, `:262-263` and `:275`).
  * Each one restates the D-C rule and the state that tripped it: "3 of 3 attempts used", "ERROR may be saved only when no attempts remain", "a PASS is never revised", and so on.
  * The phrases closest to guidance are "revise=false is for the first draft only" and "ERROR may be saved only when no attempts remain". Both are rules 6 and 9 as stated, and the second is also in the §7.1 `save_draft` description the Supervisor already sees. Neither prescribes a call.
  * The module docstring (`:5-6`) states this constraint explicitly.
* **The returns carry no routing hint.** Beyond the violation or `None`, the functions return nothing, so no "next step" field exists.

### Pillar 2 — Division of labour, D-F: ✅
* **The messages carry no article or candidate text.** The only interpolated values are:
  * `doc_id` and `draft_id`;
  * attempt numbers and the QA status literal;
  * counts and the ceiling;
  * the Supervisor's own date strings;
  * pydantic's `loc: msg` pairs.
* **`_validation_summary`** (`:94-98`) uses `exc.errors(include_url=False)` and emits only `loc` and `msg`, never `input`. The Supervisor-supplied value is therefore not echoed through pydantic, and no pydantic help URL leaks. The test at `test_guardrails.py:177` pins the URL exclusion.
* **Headline, body, summary and rationale are never read.** `candidate` is touched only through `state.documents.get(doc_id)`.

### Pillar 3 — Custom agent tools (D-A, D-G): not touched by this iteration
No tool or sub-agent is built here. One forward note, which is not a finding:
* `ScoutArgs` and the four tool-name constants (`:38-55`) are the integration surface for Iteration 7.
* The dependency direction `tools → guardrails → schemas` is acyclic, and it is the right one.

### Pillar 4 — Guardrails and attempt state (D-C, P2, P3): ✅
* **The order matches §7.3 exactly.**

  | Tool | Order in the code |
  | :--- | :--- |
  | `scout_tool` | `scout_already_run` (`:73`) → pydantic validation (`:81-84`) → window (`:85-86`) |
  | `writer_tool` | `_open_document` (`not_a_candidate` → `already_saved`, `:249-264`) → `attempt_limit` (`:141`) → `initial_draft_exists` if `revise=False` (`:150-158`), otherwise `not_audited` (`:159`) → `revise_after_pass` (`:161`) |
  | `qa_tool` | `_open_document` → `no_draft` (`:189`) → `already_audited` (`:191`) |
  | `save_draft` | `_open_document` → `not_audited` (`:220`) → `error_with_attempts_remaining` (`:222`) → `draft_ceiling` (`:233`) |

  Sharing `_open_document` is sound, because rules 1 and 10 have the same position and the same order in all three per-document rows.
* **P2 and P3 hold.** `already_saved` guards all three per-document tools, and an unknown `doc_id` is `not_a_candidate` on all three. Both are tested in each table (`WRITER_CASES`, `QA_CASES` and `SAVE_CASES`, the `unknown-doc` rows and the `already_saved` rows).
* **Each check reads the right data source.**
  * **The attempt cap** is `MAX_ATTEMPTS_PER_DOC`, read through `DocumentRecord.attempts_used` (`:141`) and `attempts_remaining` (`:222`), never `context.max_attempts_per_doc`. The test at `test_guardrails.py:377-393` pins it by giving the context copy a different value.
  * **`drafts_saved`** is `state.snapshot().drafts_saved` (`:232`), which is counted from `documents` (`src/schemas.py:680-686`). The stored `context.drafts_saved` is ignored, and `test_guardrails.py:490-499` pins this.
  * **The ceiling** is `state.config.max_drafts` (`:231`), not `context.max_drafts` or `scope.max_drafts`; `test_guardrails.py:502-514` pins it.
  * `snapshot()` goes through `model_copy`, so it does not mutate the state.
* **The latest draft** is `DocumentRecord.latest_drafted`, the last attempt with a draft.
  * A failed call therefore leaves the earlier draft the latest, per rule 8.
  * A mutant that reads `attempts[-1]` would fail the walk-through (`test_guardrails.py:679-720`).
* **`scout_already_run`** keys on `state.scope is not None`. §6.5 defines `scope` as "set by the one successful scout_tool call". "Only a successful earlier call counts" is therefore met, provided Iteration 7 sets `scope` only after the Scout succeeds, which the implementer's forward note records. A stored `invalid_scope` violation does not block a corrected scope (`test_guardrails.py:203-213`).
* **`invalid_scope` is Approach 1's logic.** `_window_problem` (`:101-120`) matches `_validate_scope_bounds` (`orchestrator.py:436-477`) point for point:
  * `date.fromisoformat`;
  * a round-trip check against the raw string, which rejects `20260622`, and also `2026-W26-1`, which Approach 1 rejects for the same reason;
  * `date_from` then `date_to`, first failure reported;
  * a strict `>`, so a one-day window is allowed.

  The exceptions become return values rather than `_StageError`, as a pure check requires.
* **Validation before dates is the right order.** Validation runs first (`:82`), so an unknown source or a wrongly typed field is caught as `ValidationError` and mapped to `invalid_scope` with the pydantic message, as the plan's Green line and §7.3's fourth bullet require.
  * `context` is spread last, so the Supervisor cannot inject a date.
  * `PipelineScope`'s `extra="ignore"` drops any unknown key.
  * The date checks need a built scope to read from, so this order is the natural one. §7.3 does not order the sub-cases of `invalid_scope`.
* **Purity (AC2).** Every per-document case is run twice, plain and with `fatal_error` set, and the Python-mode `model_dump()` is compared before and after (`test_guardrails.py:600-611`). `check_scout` has 5 purity cases (`:614-639`), which also check `state.scope is scope_before` and that `violations == []`.
* **Coverage (AC1).** `test_the_cases_produce_every_one_of_the_twelve_guardrails` (`:647-666`) derives the produced set by running the tables, not from a hand-kept list, and compares it with `set(get_args(GuardrailName))`.
* **Rule 8 walk-through.** It is one sequential test, with the "Or instead" fork taken from a deep copy.
  * It asserts `error_with_attempts_remaining` on "save A1", per rule 9, as my pre-flight directed.
  * I agree with that reading, and I do not re-raise it; the orchestrator owns the doc correction.
* **Tool-level tests are later.** Gate 4 asks for every guardrail to be tested twice, the second time through its tool. That second test belongs to Iterations 7 to 10, so it is n/a here.

### Pillar 5 — Benchmark parity: not touched by this iteration
No prompt, model, effort, tool binding, template or cost code changed. `git diff --stat` touches only three test files and the plan's §3 row.

### Pillar 6 — Substrate isolation and lifecycle: not touched by this iteration
The guardrails import nothing from the substrate. `fatal_error` is read by no check, correctly: D-D's stop mechanism is Iteration 12.

### Pillar 7 — Rendering, telemetry and logging: not touched by this iteration
There is deliberately no logging: D-I's WARNING for a violation belongs to the calling tool. The module docstring (`:4-5`) says so.

### Pillar 8 — Code quality and conventions: ✅ with one Minor (A-m1)
* **Imports.** Top of file, grouped stdlib / third-party / local; zero E402; ruff's `I` rules pass.
* **`src/guardrails.py` is fully annotated and pyright-clean.**
  * `Final[str]` constants;
  * `ScoutArgs(TypedDict)`, `total=True`, with exactly the five §6.4 keys;
  * return unions in PEP 604 form.

  No `dict[str, Any]` crosses the boundary. `ScoutArgs` is a structured type, not a new model, so Iteration 4's inventory of 27 models is unchanged.
* **Naming and docstrings.** The names are clear, and the private helpers are prefixed. The docstrings are honest and cite the rule each check enforces.
* **No dead code.** Every helper is called, and every branch is exercised by the tables.
* **`__all__`** lists exactly the public surface.
* **The docs-test change** (`test_docs_consistency.py`).
  * **`_table_rows`** now splits on `(?<!\\)\|` (`_CELL_BORDER`). I checked every document the docs tests read:
    * `grep -F '\|'` finds exactly one escaped pipe inside a table, the plan's `check_scout` cell at `IMPLEMENTATION_PLAN.md:401`;
    * the other hit, `:386`, is a grep pattern in prose, not in a table.

    The change therefore alters no existing parse, and the 196 pre-existing docs tests still pass. It has its own synthetic test (`:777-780`).
  * **`_guardrails_in_order`** filters code spans against `GUARDRAIL_NAMES`, so `revise=False`, `YYYY-MM-DD` and `drafts_saved >= config.max_drafts` are skipped. It has its own test (`:783-786`).
  * **`GUARDRAIL_CHECK_ORDER`** is pinned once and compared with both §7.3 and the plan's column 2, which satisfies AC3.
* **A-m1 (Minor): pyright errors in the new test file.**
  * `tests/test_unit/test_guardrails.py:148`: `_scope_args(**{field: raw})` gives 3 errors, because pyright cannot type a `dict[str, str]` unpack against keyword-only parameters of different types.
  * `:655-661`: `param.values` is typed `Sequence[object | NotSetType]`, so `args` does not narrow to `ScoutArgs`, giving 1 error.

  Neither affects runtime, and ruff does not flag them. They are in a file this iteration created, though, and Iteration 4 held new files to pyright-clean. The remedy is in `FIXES.md`.

## 3. Code review findings

| ID | Severity | File and lines | Finding |
| :--- | :---: | :--- | :--- |
| A-m1 | 🟢 Minor | `tests/test_unit/test_guardrails.py:146-148`, `:614-620`, `:655-663` | 4 pyright `reportArgumentType` errors, from the `**{field: raw}` unpack and from reading back untyped `pytest.param(...).values` |

**Ruff:** 0 in-scope findings (blocking) and 0 pre-existing (deferred).

## 4. Anti-patterns and risks

* **Autonomy leak:** none. No sequencing, no status-driven action, and no hint of the next call.
* **Parity drift:** none. No benchmark constant was touched.
* **State coupling:** none. The checks read `state.scope`, `state.documents`, `state.config.max_drafts` and `state.context.today` only. `context.max_attempts_per_doc`, `context.max_drafts` and `context.drafts_saved` are deliberately not read, and tests pin that.
* **Article-text leakage:** none. The messages interpolate identifiers, counts, status literals and the Supervisor's own date strings only.
* **Forward risks, for the Iteration 7 to 10 pre-flights (not findings):**
  1. `scout_already_run` depends on `scout_tool` assigning `state.scope` **only after** a successful Scout call. If Iteration 7 assigned it before running the Scout, a failed Scout call would block its retry. The plan's Iteration 7 Red covers this ("The Scout has not succeeded, so a retry is allowed").
  2. `writer_tool` must call `check_writer` **before** it appends the new `AttemptRecord` (D-C rule 3 appends before the Writer runs, not before the check). Appending first would make `attempt_limit` trip one call early, because `attempts_used` would count the new, empty attempt.
  3. **Wording.** The violation wording is now what the Supervisor reads. Tests pin it only by substring, so later rewording should be treated as a Supervisor-visible change and recorded.
  4. **A stale comment.** The comment at `test_guardrails.py:717-719` calls SPECIFICATIONS.md's rule-8 "Or instead" row "illustrative". If the orchestrator's doc correction lands, that comment should be updated with it.

## 5. Remediation directives

* **A-m1:** make the new test file pyright-clean. The exact change is in `FIXES.md` under Code Quality. The requirement is `IMPLEMENTATION_PLAN.md` §1.2 step 4 and AGENTS.md rule 7: complete PEP 484 annotations. No production change is needed.

---

# Iteration 5 — Architect Review (Stage 3, round 2)

**Reviewer:** Lead Architect, 2026-09-29.
**Scope:** the fix round for A-m1 (mine) and Q-m1 (QA's). I re-checked the whole working tree for regressions.

## 1. Overall verdict

**APPROVED**

Both round-1 items are resolved, nothing regressed, and I open no new finding. The `SPECIFICATIONS.md:348` row stays with the orchestrator, as agreed; it is a doc correction, not a blocker.

## 2. Verification (my own runs)

* `uv run pytest -q`: **633 passed**, 0 failed, 0 errors.
  * 629 at round 1, plus 1 new guardrail test (Q-m1), plus 3 `test_document_uses_no_forbidden_term` cases.
  * The 3 cases are the per-file parametrisation over `.agents/tasks/iteration-05/ARCHITECT_REVIEW.md`, `FIXES.md` and `QA_REVIEW.md`, which I confirmed with `--collect-only`.
  * `tests/test_unit/test_guardrails.py` collects 210.
* `uvx ruff check src tests --no-cache`: **All checks passed**. That is 0 in-scope findings (blocking) and 0 pre-existing (deferred).
* `uv run pytest -m live --collect-only`: 0 collected, 633 deselected.
* `uvx pyright src/guardrails.py tests/test_unit/test_guardrails.py`: **0 errors, 0 warnings**. At round 1 this gave 4 errors.
* **Production code unchanged.** `src/guardrails.py` was last written at 14:40:35, before the round-1 review at 19:17. `test_docs_consistency.py` and `test_module_structure.py` are also unchanged since round 1, at 14:40 and 14:23. Only `tests/test_unit/test_guardrails.py` changed, at 19:27.

## 3. The two items

* **A-m1: resolved.**
  * **The `**{field: raw}` unpack.** It is gone. `test_guardrails.py:159` now picks the field explicitly: `_scope_args(date_from=raw) if field == "date_from" else _scope_args(date_to=raw)`. That keeps the 10 cases and their ids, and it type-checks against the keyword-only signature.
  * **The untyped `pytest.param(...).values`.** It is replaced by one typed source, `_SCOUT_PURITY_INPUTS: list[tuple[str, bool, ScoutArgs]]` (`:626-632`). It feeds both `SCOUT_PURITY_CASES` (`:633`) and the AC1 loop (`:668`).
  * **AC1 still has one source of truth.** Driving the purity cases and the coverage loop from the same list is better than before, because it removes the read-back of `param.values`. AC1 is still derived by running the checks, not from a hand-kept list.
* **Q-m1: resolved.**
  * **The new test.** `test_check_scout_fills_context_from_the_run_even_if_one_is_sent` (`:114-122`) sends a raw `context` of `{"today": "2000-01-01"}` and asserts `scope.context == AgentContext(today=TODAY)`.
  * **It kills the mutant.** Against the reversed merge, `{"context": ..., **raw_scope}`, the raw dict would win and pydantic would build `AgentContext(today=2000-01-01)`, so the assertion fails. This agrees with the implementer's scratch-copy Red.
  * **The one suppression is legitimate.** The `# type: ignore[typeddict-unknown-key]` at `:117` is narrow, and it is needed: sending a key that `ScoutArgs` does not declare is the whole point of the test. It follows the project's existing pattern of coded ignores in negative tests (for example `test_schemas.py:237` and `:249`), and pyright accepts it.

## 4. Pillars

No change from round 1. Pillars 1, 2, 4 and 8 are ✅; pillars 3, 5, 6 and 7 are not touched by this iteration. The fix round touched only test code, so no boundary, parity constant or guardrail order moved.

## 5. Open items

* **None of mine.** No new `FIXES.md` entry, and no "Needs a decision" item from me.
* **Round-1 forward notes 1 to 4 stand for the Iteration 7 to 10 pre-flights.** Note 4 is the "illustrative" comment in the rule-8 walk-through, now at `test_guardrails.py:730-732`. It changes only if the orchestrator's doc correction to `SPECIFICATIONS.md:348` lands.
