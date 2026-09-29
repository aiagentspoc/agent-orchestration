# QA Review: Iteration 5, Guardrail checks (Stage 3, round 1)

*QA and verification subagent, 2026-09-29. Criteria: `.agents/skills/code-reviewer/SKILL.md`, `IMPLEMENTATION_PLAN.md` §1.3, §1.4, §2 and Iteration 5, `SPECIFICATIONS.md` D-C (including "How rule 8 plays out"), §6.5, §6.7 and §7.3, `DESIGN.md`, `AGENTS.md`, and Approach 1's `_validate_scope_bounds` (`../code-orchestration/src/orchestrator.py:436`).*

## 1. Summary and verdict

**Verdict: PASSED.** No blocker and no major finding.

The four checks implement every §7.3 row in order, and all 12 guardrails are produced. Each check is pure. The attempt cap is read from `MAX_ATTEMPTS_PER_DOC`, the ceiling from `config.max_drafts`, and `drafts_saved` is counted from the documents. The rule 8 walk-through is one sequential test.

I ran my own 36 mutants against the new tests. 34 were killed. One of the two survivors is an equivalent mutant; the other exposes a code comment that no test pins (Q-m1, minor).

The only other open item is the architect's pyright finding A-m1 (minor), which I confirmed and concur with. I do not repeat it in `FIXES.md`.

### What I ran myself

| Command | Real result | Claimed | Match |
| :--- | :--- | :--- | :---: |
| `uv run pytest -q` | **629 passed**, 0 failed, 0 errors, 31.55 s | 629 passed | ✅ |
| `uv run pytest -q -W error` | 629 passed; no warning escalated | clean output | ✅ |
| `uvx ruff check src tests --no-cache` | `All checks passed!` | clean | ✅ |
| `uv run pytest -m live --collect-only -q` | `no tests collected (629 deselected)` | 0 collected, 629 deselected | ✅ |
| `uv run pytest -q tests/test_unit/test_guardrails.py` | 209 passed | 209 | ✅ |
| `test_docs_consistency.py` def-count, HEAD vs working tree | 41 → 45 test functions (+4) | +4 (196 → 200) | ✅ |

The total depends on how many files are in `.agents/tasks/`, because `test_document_uses_no_forbidden_term` is parametrized per document:
* my first full run gave 629, before the architect's two artifacts existed;
* once they landed, the docs file collects 202;
* this file adds one more document.

This is not a discrepancy. The orchestrator's final count at commit will be 629 plus one per review artifact.

## 2. Gate matrix

| Gate | Topic | Status | Notes |
| :--- | :--- | :---: | :--- |
| 1 | Strict TDD | ✅ | See §5 for the behaviour-by-behaviour check. Behaviours 1–5 and 10 each report a genuine Red. Behaviours 6–9 were written against existing code; the report says so, and the Red evidence is by mutant, which I reproduced independently. One TDD slip is stated (the writer `already_saved` branch landed in behaviour 3, before its test). Every statement in `src/guardrails.py` runs under the new tests (my `sys.settrace` probe); the only line never hit, `:110`, is a bare annotation. |
| 2 | Zero-token testing | ✅ | `src/guardrails.py` imports only `datetime`, `typing`, `pydantic` and `.schemas`. The tests build `RunState` by hand, with no model, agent or substrate. The `live` collection is empty. |
| 3 | Pydantic v2 contracts | ✅ | No model added or changed. `ScoutArgs` is a total `TypedDict` of the five §6.4 keys, typed and not a loose dictionary. No `Any` in `src/guardrails.py`. None of the removed models appears in `src/`. Violations fill all four `GuardrailViolation` fields; the table asserts `(guardrail, tool_name, doc_id)` on every refusal. |
| 4 | Guardrails and attempt cap | ✅ (pure checks) | All 12 names are produced by pure-check tests, and a set-equality test pins them (AC1). The check order matches §7.3, and the precedence tests prove it. The cap is `MAX_ATTEMPTS_PER_DOC`, not the Supervisor's copy of it. `already_saved` guards writer, QA and save (P2), and an unknown `doc_id` is `not_a_candidate` on all three (P3). "Through its tool", the WARNING log and storage on `RunState.violations` belong to Iterations 7–10: n/a in this iteration. |
| 5 | Strands integration and telemetry | n/a in this iteration | |
| 6 | No article text for the Supervisor | n/a in this iteration | I dumped every message; none carries candidate or draft text. They name only the `doc_id`, the attempt number, the QA status and the draft ID. |
| 7 | Drafts and logging | n/a in this iteration | `src/guardrails.py` does no logging and no I/O, which D-C and the module docstring require. |
| 8 | Python and subprocess safety | ✅ (one minor) | Annotations are complete, imports are at the top, and `pathlib.Path` is used in the tests. No subprocess is involved: every `python`, `uv` or `fastmcp` process running belongs to a `claude` harness MCP server started before my runs. Pyright: `src/guardrails.py` is clean, and the new test file adds 4 `reportArgumentType` errors, which is the architect's A-m1 (confirmed). The repository-wide baseline is already 130 other pyright errors, and pyright is not a DoD gate, hence minor. |

## 3. Acceptance criteria and Definition of Done

| # | Criterion | Status | Evidence |
| :--- | :--- | :---: | :--- |
| AC1 | Each of the 12 `GuardrailName` values is produced by a test, and the produced set equals `get_args(GuardrailName)` | ✅ | `test_the_cases_produce_every_one_of_the_twelve_guardrails` runs the cases and compares the set it collects, with `len == 12`. My mutants that remove a guardrail (`revise_after_pass` never tripped; `initial_draft_exists` never tripped) are killed. |
| AC2 | No function mutates `RunState` (`model_dump()` before and after) | ✅ | `test_per_document_checks_never_change_the_run_state` covers 59 cases (19 writer, 10 QA, 22 save, 8 precedence) × {plain, with `fatal_error`}. `test_check_scout_never_changes_the_run_state` covers 5 cases and also asserts `state.scope` identity. My mutants that sync `context.drafts_saved` or store the scope in `check_scout` are killed. `src/guardrails.py` has no assignment or append to `state`. |
| AC3 | The §7.3 check order matches the plan's Iteration 5 table | ✅ | `test_specification_states_the_guardrail_check_order` and `test_plan_iteration_5_table_states_the_same_check_order_as_the_specification` both pin `GUARDRAIL_CHECK_ORDER`. The escaped-pipe fix to `_table_rows` is needed for the plan's `PipelineScope \| GuardrailViolation` cell. `grep -F '\|'` finds that as the only escaped pipe in any table of a scanned document, so no other table's parse changed. |
| DoD-1 | Full suite passes | ✅ | 629 passed, 0 failed, 0 errors |
| DoD-2 | Lint clean | ✅ | `All checks passed!` |
| DoD-3 | No live model call | ✅ | See Gate 2 |
| DoD-4 | Every new `src/` function is tested | ✅ | Every statement is covered, and the mutants are killed (§4) |
| DoD-5 | Docs match code | ✅ | `test_docs_consistency.py`: 202 passed, counted with the review artifacts now present |
| DoD-6 | `WALKTHROUGH.md` written | n/a at Stage 3 | Written by the orchestrator at step 8 |

**Result: 3 of 3 acceptance criteria, and 5 of 5 DoD rows applicable at this stage.**

### The plan's Iteration 5 table, row by row

| Function | Required | Test IDs (parametrized) | Status |
| :--- | :--- | :--- | :---: |
| `check_scout` | `scout_already_run`, counting only a successful earlier call | `refuses_once_a_scope_is_set`, `allows_a_corrected_scope_after_an_invalid_one`; my mutant that counted stored violations is killed | ✅ |
| | `invalid_scope`: not ISO, including `20260622` | 5 forms × 2 fields: day-first, prose, basic, week, empty | ✅ |
| | `invalid_scope`: `date_from` after `date_to` | `refuses_an_inverted_window_and_names_both_dates`; equal dates allowed (`one_day_window`) | ✅ |
| | `invalid_scope`: unknown source | `refuses_an_unknown_source_with_the_pydantic_message` | ✅ |
| | `invalid_scope`: any validation error | 3 wrong-type cases; the re-raise mutant is killed | ✅ |
| | Allowed: valid scope with `context` filled in | `returns_a_valid_scope_with_its_context_filled_in` | ✅ |
| | Allowed: corrected scope after `invalid_scope` | `allows_a_corrected_scope_after_an_invalid_one` | ✅ |
| `check_writer` | `not_a_candidate`, `already_saved`, `attempt_limit`, `initial_draft_exists`, `not_audited` (no draft; no report), `revise_after_pass` | 12 refusal rows | ✅ |
| | Allowed: first draft; retry after a failed first call; revise `ERROR` or `WARNING`; revise after a failed revision | `allowed-*`, 7 rows | ✅ |
| `check_qa` | `not_a_candidate`, `already_saved`, `no_draft`, `already_audited` | 7 refusal rows | ✅ |
| | Allowed: audit the latest draft; audit after a successful revision | 3 rows | ✅ |
| `check_save` | `not_a_candidate`, `already_saved`, `not_audited`, `error_with_attempts_remaining`, `draft_ceiling` | 11 refusal rows | ✅ |
| | Allowed: `PASS` or `WARNING` at attempts 1, 2 and 3; `ERROR` at 3 of 3; an earlier audited draft after a failed call; no ceiling when `max_drafts is None` | 11 rows | ✅ |
| All | Precedence, when two checks fail | 8 per-document cases and 2 Scout cases; my 3 extra order mutants (ceiling before ERROR, ceiling before `not_audited`, dates before model validation) are killed | ✅ |
| All | Each message names its rule and any limit | Checked against a dump of every message; see §4 | ✅ |
| D-C | Rule 8 walk-through as one sequential test | `test_rule_8_walk_through_for_one_document`, with a deep-copy fork for "Or instead" | ✅ (see the note under §6) |

## 4. Independent verification

**Mutation probes.** I ran these on a scratch copy outside the repository, against `tests/test_unit/test_guardrails.py`; the copy was restored afterwards, and `diff -r` shows it identical to `src/`. Killed, 34 of 36:
* **Comparison operators:** `>` for `>=` in the attempt cap and in the ceiling, and `>= 0` or `> 1` for `attempts_remaining > 0`.
* **Hardcoded cap:** a literal in place of `MAX_ATTEMPTS_PER_DOC`.
* **Wrong data source:** the ceiling read from `context.max_drafts`, or `drafts_saved` read from `context`.
* **Latest draft:** read as `attempts[-1]` in `check_qa`.
* **Date logic:** no round-trip; the inverted window allowed; `>=` in the window check.
* **Scout context:** the wrong `today`.
* **Guardrails removed or widened:** `already_saved` removed; `revise_after_pass` removed or widened to `WARNING`; `initial_draft_exists` never trips, or keyed on `attempts_used`; `not_audited` narrowed to "no draft" in writer or save; the ERROR save rule widened to `WARNING`.
* **Violation fields:** the wrong `tool_name`; `doc_id` dropped.
* **Validation errors:** re-raised instead of mapped to `invalid_scope`.
* **State mutation:** `drafts_saved` synced into `context`; the scope stored in `state`.
* **Message content:** a message stripped of its limit (`attempt_limit`, `draft_ceiling`, `error_with_attempts_remaining`) or of its rule (`scout_already_run`).
* **Check order:** the ceiling before the ERROR rule, the ceiling before `not_audited`, dates before model validation.

Survived, 2:
* `exc.errors()` without `include_url=False`. This is equivalent: only `loc` and `msg` are formatted, so no URL can reach the message.
* Putting `context` first in the `model_validate` merge. Real: the comment at `src/guardrails.py:81` claims an ordering that no test pins (Q-m1).

**Messages.** I dumped the message for each of the 19 (tool, guardrail) pairs the tables produce. Each carries:
* the `doc_id` in `repr` form, for the per-document checks;
* the rule, such as "revise=false is for the first draft only" or "each draft is audited once";
* the limit where there is one: "3 of 3 attempts used", "ERROR with 2 of 3 attempts remaining", "2 of 2 drafts saved (max_drafts 2)", "expected YYYY-MM-DD".

None names a next call, which keeps "code only refuses".

**Substrate cross-check (`hse-easy-mock`).** `list_regulatory_updates(date_from="20260101", …)` is refused with "Expected strict hyphenated YYYY-MM-DD format", while the extended form returns results. That confirms why the round-trip in `_window_problem` is needed. The `Source` values in the tool schema are `EUR_LEX`, `GAZZETTA_UFFICIALE` and `INAIL`, which match the pydantic message the unknown-source test pins.

**Approach 1 parity.** `_window_problem` follows `_validate_scope_bounds` exactly:
* `fromisoformat` is checked with a round-trip;
* both bounds are checked before the order;
* equal bounds are allowed.

## 5. Test-first discipline

| Behaviour | Red evidence in report | Assessment |
| :--- | :--- | :--- |
| 1 Module, run-once, valid scope | `ModuleNotFoundError src.guardrails` | Genuine |
| 2 `invalid_scope` subcases | 16 failed: a `PipelineScope` returned, or `ValidationError` escaped | Genuine and specific |
| 3 `check_writer` | `ImportError`, then a stub that allows every call fails the 11 refusals and the constant test | Genuine; the stated slip (writer `already_saved` untested until behaviour 4) is minor and disclosed |
| 4 `check_qa` | `ImportError`, then the stub fails the 7 refusals | Genuine |
| 5 `check_save` | `ImportError`, then the stub fails the 11 refusals and both source tests | Genuine |
| 6–9 Precedence, purity, AC1 set, rule 8 | Passed when written; Red by mutants | Characterisation tests of existing code, disclosed. Acceptable, because my own independent mutants are killed by them |
| 10 AC3 docs | The plan's scout row parsed as `()` through the escaped pipe | Genuine; the fix is minimal and has its own helper test |

## 6. Findings by severity

### 🔴 Blocker
None.

### 🟡 Major
None.

### 🟢 Minor
* **Q-m1:** an untested ordering claim in `check_scout`. The comment at `src/guardrails.py:81` says the run's date wins over anything the Supervisor sent, but a mutant that puts `context` first survives all 209 tests. This is defensive only: `ScoutArgs` has no `context` key, and the §6.4 `scout_tool` signature cannot pass one. Fix instructions are in `FIXES.md`.
* **A-m1 (architect, confirmed):** 4 pyright `reportArgumentType` errors in `tests/test_unit/test_guardrails.py` at `:148` (3) and `:661` (1). I reproduced them exactly, and `src/guardrails.py` is clean. I concur with the architect's remedy in `FIXES.md`, and do not duplicate it.

### Observations (no action)
* **Known conflict at `SPECIFICATIONS.md:348`.** The "Or instead" row's "or save A1" is implemented per rule 9: `error_with_attempts_remaining`, with 1 of 3 attempts remaining. The comment in the walk-through test at `tests/test_unit/test_guardrails.py:716-719` calls the table row "illustrative". If the user approves the doc correction, that comment should be reworded to cite the corrected row. If the user instead rules that the row is right, the guardrail and the test both change. The orchestrator is handling the question, so I open no duplicate decision item.
* **`max_drafts` in the scope is unbounded.** `check_scout` accepts `max_drafts` of `0`, `-1`, `True` or `"3"` (coerced to 1 or 3), because `PipelineScope.max_drafts: int | None` has no bound. This is identical to Approach 1's model, and §7.3 enumerates the `invalid_scope` cases without it, so it is not a defect of this iteration. It is recorded in case Iteration 7 or 13 finds the Supervisor sending such values.
* **Precedence cases rest on the shared helper.** A few precedence pairs are covered only through the shared `_open_document` helper, for example `already_saved` over `no_draft` in `check_qa`. That is adequate, since all three per-document checks call it first.

---

# QA Review: Iteration 5, round 2 (fix-round re-review)

*QA and verification subagent, 2026-09-29. Round 2 covers the implementer's fix round for A-m1 (architect) and Q-m1 (QA). I read the criteria again: `AGENTS.md`, `.agents/skills/code-reviewer/SKILL.md`, `IMPLEMENTATION_PLAN.md` §1.3, §1.4 and Iteration 5, and `SPECIFICATIONS.md` D-C and §7.3.*

## R2.1 Summary and verdict

**Verdict: PASSED.** Both round-1 items are resolved, and I verified each one myself. There are no new findings.

### What I ran myself

| Command | Real result | Claimed | Match |
| :--- | :--- | :--- | :---: |
| `uv run pytest -q` | **633 passed**, 0 failed, 0 errors, 29.43 s | 633 passed | ✅ |
| `uv run pytest -q -W error` | 633 passed; no warning escalated | n/a | ✅ |
| `uvx ruff check src tests --no-cache` | `All checks passed!` | clean | ✅ |
| `uv run pytest -m live --collect-only -q` | `no tests collected (633 deselected)` | 0 collected, 633 deselected | ✅ |
| `uv run pytest -q tests/test_unit/test_guardrails.py` | 210 passed | 210 | ✅ |
| `uvx pyright tests/test_unit/test_guardrails.py src/guardrails.py` | `0 errors, 0 warnings, 0 informations` | 0 errors | ✅ |

**The count reconciles.**
* Round 1's 629 was counted before any iteration-05 record existed.
* `test_document_uses_no_forbidden_term` now collects three iteration-05 cases, one each for `ARCHITECT_REVIEW.md`, `FIXES.md` and `QA_REVIEW.md`. I confirmed this with `--collect-only`.
* The fix adds 1 test.
* 629 + 3 + 1 = 633. This round-2 section adds no new file, so the count does not change.

## R2.2 The round-1 items

| Item | Claim | My check | Status |
| :--- | :--- | :--- | :---: |
| A-m1: 4 pyright `reportArgumentType` errors in the test file | Fixed with an explicit `date_from`/`date_to` branch and one typed `_SCOUT_PURITY_INPUTS: list[tuple[str, bool, ScoutArgs]]`; cases and IDs unchanged | Pyright reports 0 errors on both files. `test_check_scout_refuses_a_date_that_is_not_extended_iso` (`:157-170`) builds the args through `_scope_args(date_from=raw)` or `_scope_args(date_to=raw)`. `_SCOUT_PURITY_INPUTS` (`:626-633`) feeds both `SCOUT_PURITY_CASES` and the AC1 loop (`:668`). `--collect-only` lists the same 10 date IDs (5 forms × 2 fields) and the same 5 purity IDs as round 1 (`allowed`, `invalid-date`, `inverted-window`, `unknown-source`, `scout-already-run`). | ✅ resolved |
| Q-m1: the "context goes last" ordering in `check_scout` is untested | `test_check_scout_fills_context_from_the_run_even_if_one_is_sent` added | The test (`:114-122`) sends `context={"today": "2000-01-01"}` with otherwise valid args. It asserts that a `PipelineScope` comes back with `context == AgentContext(today=TODAY)`. **Re-probe:** on a scratch copy outside the repository, I rewrote `src/guardrails.py:82` to `{"context": AgentContext(today=state.context.today), **raw_scope}`. Unmutated baseline: 210 passed. With the mutant: `1 failed, 209 passed`, and the only failure is `test_check_scout_fills_context_from_the_run_even_if_one_is_sent`. I deleted the scratch copy afterwards. | ✅ resolved |

**Production code is unchanged.** `src/guardrails.py` was last modified at 14:40, before both round-1 reviews (19:17 and 19:25), so the claim "only test code changed" holds. The `# type: ignore[typeddict-unknown-key]` on `:117` is the mypy-style code. Pyright honours any `# type: ignore` comment, and the file already used the same style at `:205`. It is not a finding.

## R2.3 Gate matrix (round 2)

| Gate | Topic | Status | Notes |
| :--- | :--- | :---: | :--- |
| 1 | Strict TDD | ✅ | Both fixes were test-only. Q-m1's Red is a surviving mutant that the new test now kills, which I reproduced. A-m1's Red is the pyright output, and I confirmed the Green. |
| 2 | Zero-token testing | ✅ | No change to imports or fixtures. The live collection is empty (633 deselected). |
| 3 | Pydantic v2 contracts | ✅ | Unchanged from round 1 |
| 4 | Guardrails and attempt cap | ✅ (pure checks) | Unchanged from round 1. The context merge order is now pinned. |
| 5 | Strands integration and telemetry | n/a in this iteration | |
| 6 | No article text for the Supervisor | n/a in this iteration | |
| 7 | Drafts and logging | n/a in this iteration | |
| 8 | Python and subprocess safety | ✅ | Pyright is clean on the iteration's files, and the suite is clean under `-W error`. No pytest process is left running; every running `python`, `uv` or `fastmcp` process is a harness MCP server. |

## R2.4 Acceptance criteria and Definition of Done (round 2)

| # | Status | Evidence |
| :--- | :---: | :--- |
| AC1: all 12 guardrails produced; set equals `get_args(GuardrailName)` | ✅ | `test_the_cases_produce_every_one_of_the_twelve_guardrails` passes, now iterating the typed `_SCOUT_PURITY_INPUTS` |
| AC2: no function mutates `RunState` | ✅ | The purity tests pass with the same 5 Scout IDs and the same 59 × 2 per-document cases |
| AC3: the §7.3 order matches the plan table | ✅ | The docs-consistency order tests pass |
| DoD-1 | ✅ | 633 passed, 0 failed, 0 errors |
| DoD-2 | ✅ | `All checks passed!` |
| DoD-3 | ✅ | No model, agent or substrate in the changed tests |
| DoD-4 | ✅ | `src/` unchanged; round 1's full statement coverage stands |
| DoD-5 | ✅ | `test_docs_consistency.py` passes within the full run |
| DoD-6 | n/a at Stage 3 | Written by the orchestrator at step 8 |

**Result: 3 of 3 acceptance criteria, and 5 of 5 DoD rows applicable at this stage.**

## R2.5 Findings by severity (round 2)

* **🔴 Blocker:** none.
* **🟡 Major:** none.
* **🟢 Minor:** none new. A-m1 and Q-m1 are resolved.

**Still open, not a QA item:** the `SPECIFICATIONS.md:348` conflict ("or save A1" against rule 9) stays with the orchestrator, as in round 1. Whichever way it is decided, the comment at `tests/test_unit/test_guardrails.py:730-732` (at `:716-719` in round 1, before the new test shifted it) follows that decision, or the guardrail and the test do, if the row is kept. No `FIXES.md` item and no "Needs a decision" item were opened this round.
