# Iteration 11 — QA Review (Stage 3, round 1)

**Reviewer:** qa subagent · **Date:** 2026-10-01 · **Scope:** the uncommitted diff on `approach-2/implementation` (13 modified files, no untracked files)

## 1. Summary and verdict

**Verdict: PASSED.** No blocker and no major finding.

`finalise_run` does what the plan, P11 and P12 require, and every branch was checked by a mutation that the suite killed. The implementer's counts match what I measured:

| Check | Claimed | Measured by QA |
| :--- | :--- | :--- |
| `uv run pytest -q` | 1063 passed (baseline 1038, +25) | **1063 passed** in 34.0 s, 0 failed, 0 errors, no warnings summary |
| `uvx ruff check src tests --no-cache` | All checks passed | **All checks passed!** |
| `uv run pytest -m live --collect-only -q` | — | no tests collected (1063 deselected) |
| `uvx pyright src/rendering.py tests/test_unit/test_rendering.py` | 0 errors | **0 errors, 0 warnings, 0 informations** |
| New tests in `test_rendering.py` | 25 | **25** (31 in the file: 6 from Iteration 10, plus 24 functions with one of them parametrised twice) |

## 2. Gate matrix

| Gate | Topic | Status | Notes |
| :--- | :--- | :---: | :--- |
| 1 | Strict TDD | ✅ | The Red failures reported for each behaviour are plausible and specific: ImportError, missing warnings, the unpack ValueError and FileNotFoundError, latency 0.0 against 32.0, rank order against save order, and exceptions that escaped. Where a test passed on its first run (7a, 8b, 10), the implementer ran mutations, as the protocol requires. QA ran 21 more mutations of its own (§5), and all 21 were killed. |
| 2 | Zero-token testing | ✅ | Every state is built by hand from `AgentTelemetry` values, and no model is constructed. `finalise_run` imports no runner or model. The default run deselects `live` tests, and every file is written under `tmp_path`. |
| 3 | Pydantic v2 contracts | ✅ | No model was added or changed. `RunFinalisation` is a frozen dataclass, the same pattern as the four in `src/tools.py`. `DraftMetadata` is built field for field per §6.8. No `dict[str, Any]` crosses a module boundary, and no removed model came back. |
| 4 | Guardrails and attempt cap | ✅ (render side only) | No guardrail changed. An `ERROR` saved at the cap renders the `[UNRESOLVED COMPLIANCE ALERT]` banner through `format_review_notes` and logs the D-I WARNING. Tested in `test_an_error_draft_saved_at_the_cap_…`. |
| 5 | Strands integration and telemetry | ✅ | The Supervisor gets exactly one ledger entry, or a WARNING and no entry when its telemetry is `None`. Shares come from the unchanged `amortise_shared_telemetry`. Per-draft cost is checked against `estimate_cost` over `stage_telemetry` to 1e-9 (AC3). Per-draft tokens add up to the saved documents' own entries plus all shared entries, with an odd shared total so the remainder rule is exercised. The run total covers the whole ledger. `extract_telemetry` is untouched. |
| 6 | No article text for the Supervisor | n/a in this iteration | `finalise_run` runs after the Supervisor and returns nothing to it. |
| 7 | Drafts and logging | ✅ | Markdown only, rendered at run end with `config.template_path`. No template token is left (AC1, against the shipped template). Files are written in save order by sequence number, with `_999` before `_1000`. The D-I events are asserted with their `(run_id, doc_id, attempt)` correlation: "Draft rendered", the compliance-alert WARNING, "Candidate left unsaved", and "Draft render or write failure" with `exc_info`. No totals line is logged (P12). |
| 8 | Python and subprocess safety | ✅ | Annotations are complete, there is no E402, and every path is a `pathlib.Path`. Pytest output is clean. Every running `python.exe` and `uv.exe` is a Claude Code MCP server (`hse-easy-mock` or `strands-agents-mcp-server`) started on 2026-09-29 or 2026-09-30, so none is an orphan from this review's runs. |

## 3. Acceptance criteria

| # | Criterion | Status | Evidence |
| :--- | :--- | :---: | :--- |
| AC1 | A rendered test draft contains no unresolved template token | ✅ | `test_a_saved_draft_is_rendered_from_its_metadata_…` runs the regex `\{[^{}\n]+\}` and `[Article Headline Here]` over a render with `REAL_TEMPLATE_PATH`, and asserts the result is empty. The regex covers every token in `.agents/templates/draft.md`, including `{PASS / WARNING / ERROR}`. The template matches Approach 1's apart from CRLF line endings (`diff --strip-trailing-cr` is clean), and it is not in the diff. |
| AC2 | `approach_name` renders as `Approach 2 (Research Analyst)` | ✅ | `**Approach:** Approach 2 (Research Analyst)` is asserted in the content. `_draft_metadata` never passes `approach_name`. Mutation M21, which overrides it, was killed. |
| AC3 | Per-draft cost equals `estimate_cost` over its `stage_telemetry`, within 1e-9 | ✅ | `test_each_drafts_tokens_and_cost_are_those_of_its_stage_telemetry` checks both drafts with `abs=1e-9` and asserts a cost above 0. |

**Red items, Iteration 11 (§5):**

| Red item | Status | Evidence |
| :--- | :---: | :--- |
| Supervisor entry: one when telemetry is given; with `None`, a WARNING and no entry | ✅ | Two tests, which assert the full ledger and the warning's correlation `(run_id, "-", "-")`. Mutation M13 was killed. |
| Each unfinished candidate is logged at WARNING with its last state | ✅ | All three states (`not_drafted`, `drafted`, `audited`) appear, a failed-only document reads `not_drafted`, a saved document is excluded, the lines are in rank order, and each carries its `doc_id` correlation. Mutation M17 was killed. |
| `DraftMetadata` per saved document, in save order: source mapping, `qa_report`, `attempts = attempts_used`, `stage_telemetry` = own + amortised share, tokens and cost from those entries, `unresolved_errors` only for `ERROR` | ✅ | The mapping matches Approach 1's `_build_draft_metadata` (`orchestrator.py:706-741`), and the substrate fields `source`, `publication_date` and `title` are confirmed live on `hse-easy-mock`. Mutations M9, M10, M15 and M16 were killed. |
| Totals add up; tokens on unsaved documents appear only in the run total | ✅ | `test_per_draft_tokens_sum_…` and `test_the_run_totals_cover_the_whole_ledger_…`, whose hand sum is 2867. Mutation M12 was killed. |
| Rendering: `render_draft` with the template, written to `path`, the `ERROR` banner and WARNING, INFO "Draft rendered" with its fields | ✅ | Four tests. Mutations M8, M11 and M14 were killed. |
| Render or write failure: `FailureRecord(stage="render" \| "persist")`, ERROR, continue, persistence failure reported | ✅ | The render test monkeypatches `render_draft`. The write test puts a real directory at the draft's path. A broken invariant yields a `RuntimeError` render failure, tested both with no attempt and with an unaudited latest draft. Mutations M6, M7, M18, M19 and M20 were killed. |
| Run totals (superseded by P12): returned, not logged, not stored | ✅ | `RunFinalisation(persistence_failed, total_tokens, estimated_cost)`. A test asserts that the only INFO line is "Draft rendered:", that `exit_code` stays `None`, and that `RunState` changes only in `ledger` and `failures` (DM18). |
| The drafted text is right: the rendered draft is `latest_drafted` | ✅ | Two tests. `{A1 ERROR, A2 PASS}` renders A2. `{A1 WARNING, failed}` renders A1, with `attempts == 2`. |

**P11 arithmetic:** ✅.
- `_own_seconds` is computed from the **un-amortised** `supervisor_telemetry` argument, and then divided by `len(saved)`.
- Feeding the amortised Supervisor share instead (mutation M3) gives `max(50 − 70, 0) = 0` and was killed, because `tool_invocations` are not divided by `amortise_shared_telemetry`.
- Dropping the subtraction (M1), the floor (M2), the division (M4) or the Scout share (M5) was killed too.
- Hand check for doc-a:
  - own time is writer 10 s + QA 4 s = 14 s;
  - the Scout share is 6 s / 2 = 3 s;
  - the Supervisor share is (100 s − 70 s) / 2 = 15 s;
  - the total is **32.0 s**, and `**Time Taken:** 32.00s` renders.
- The floor case gives 17.0 s, and the `None` case gives 17.0 s and 15.0 s.
- `stage_telemetry` stays exactly as amortised: the Supervisor share's duration is 50.0, and its `tool_invocations` are in full.

**P12:** ✅. The signature is `finalise_run(state, *, supervisor_telemetry, rates)` and is unchanged. The function returns its persistence flag and totals, and logs no totals line.

**Definition of Done:**

| # | Status | Evidence |
| :---: | :---: | :--- |
| DoD-1 | ✅ | 1063 passed, 0 failed, 0 errors |
| DoD-2 | ✅ | `ruff` clean |
| DoD-3 | ✅ | No model is built in the new tests; the live suite is deselected |
| DoD-4 | ✅ | Every new function and branch in `src/rendering.py` is exercised; 21 of 21 QA mutations were killed |
| DoD-5 | ✅ | `test_docs_consistency.py` passes with the P11 and P12 rows in both records |
| DoD-6 | pending | `WALKTHROUGH.md` is written at Stage 4 by the orchestrating agent |

**Total:** 3/3 acceptance criteria, 8/8 Red items and 5/5 applicable DoD rows (DoD-6 pending, Stage 4).

## 4. Findings by severity

**🔴 Blocker:** none.

**🟡 Major:** none.

**🟢 Minor:**

- **Q-1 (report accuracy, informational).**
  - The report's "Not touched: IMPLEMENTATION_PLAN.md" is not literally true of the working tree. `git diff` shows the P11 and P12 rows added to §2 and the §3 tracker row set to `🔄 In progress`.
  - These edits match the Q8 and Q9 answers and the protocol's §1.1, so they are most likely the orchestrating agent's. The content is correct.
  - No fix is needed. The walkthrough should credit these edits to whoever made them.
- **Q-2 (concurs with architect A-1).** I confirm that `_RenderedAttempt.attempt` is never read in production code. My mutation M10 was the only reader, and it was a mutant.

**Optional (non-blocking):**

- **O-Q1.** The plan's Iteration 11 Red bullet "Run totals. Tokens, cost and wall-clock are logged once at INFO" still reads as before.
  - P12 states that D-I wins over that wording, so this is settled.
  - A short "(superseded by P12)" note after the bullet would stop a later reader from tripping on it. This is an orchestrator edit to the plan, not an implementer fix.
- **O-Q2, for Iteration 14.** An unknown model ID raises `ValueError` from `aggregate_draft_totals` before that draft's render stage. This is deliberate, matches Approach 1's `_persist_builds:772`, and is documented under `Raises:`.
  - When it fires, the drafts earlier in save order are already written and the later ones are not, and `finalise_run` returns nothing.
  - The composition root must treat this as a configuration-class failure, since rates are resolved at start-up. Iteration 14 should test that path.
- **O-Q3, for Iteration 16, informational.** As the implementer noted, the Scout and Supervisor rows of Agent Tool Usage print `None` in the Attempt column. The benchmark parser must accept this.

## 5. QA mutation log

All mutations were run on a scratch copy outside the repository, using the project's `.venv` interpreter and with `-p no:cacheprovider`. Each was restored afterwards, and the repository was never modified.

| # | Mutation in `src/rendering.py` | Result |
| :---: | :--- | :---: |
| M1 | Supervisor own time = `total_duration_seconds` (no tool subtraction) | killed |
| M2 | No `max(…, 0)` floor | killed |
| M3 | Own time read from the amortised Supervisor share | killed |
| M4 | Supervisor own time not divided by the number of saved drafts | killed |
| M5 | Scout share dropped from latency | killed |
| M6 | Stage left at `render` for the write | killed |
| M7 | `persistence_failed` always `False` | killed |
| M8 | Compliance-alert WARNING on any non-`PASS` status | killed |
| M9 | `unresolved_errors` on any non-`PASS` status | killed |
| M10 | `attempts = rendered.attempt` instead of `attempts_used` | killed |
| M11 | `attempt` dropped from the per-draft log context | killed |
| M12 | Run total excludes the Supervisor | killed |
| M13 | Supervisor entry never appended | killed |
| M14 | `template_path=None` (default template) | killed |
| M15 | Rank order in place of save order | killed |
| M16 | Sorting by ID string | killed |
| M17 | `not_drafted` candidates not logged | killed |
| M18 | Failure re-raised, not absorbed | killed |
| M19 | `FailureRecord.attempt` forced to `None` | killed |
| M20 | `exc_info` dropped from the ERROR line | killed |
| M21 | `approach_name` overridden | killed |

Verdict: PASS

---

# Iteration 11 — QA Review (Stage 3, round 2)

**Reviewer:** qa subagent · **Date:** 2026-10-01 · **Scope:** fix round 1 (A-1, O-1, O-2, O-3) on top of the round-1 diff

## R2.1 Summary and verdict

**Verdict: PASSED.** No blocker, no major and no minor finding. All four fixes are in place, the O-3 check is tested and survives no mutation, and every acceptance criterion still holds.

| Check | Claimed | Measured by QA |
| :--- | :--- | :--- |
| `uv run pytest -q` | 1067 passed | **1067 passed** in 32.4 s, 0 failed, 0 errors, no warnings summary |
| `uvx ruff check src tests --no-cache` | All checks passed | **All checks passed!** |
| `uv run pytest -m live --collect-only -q` | — | no tests collected (1067 deselected) |
| `uvx pyright src/rendering.py tests/test_unit/test_rendering.py` | — | 0 errors, 0 warnings, 0 informations |
| `tests/test_unit/test_rendering.py` | 31 + 1 | **32** collected |

**Where the count changed between rounds.** Round 1 measured 1063, and the implementer reports 1066 before the O-3 test. The +3 is not from code. `test_document_uses_no_forbidden_term` is parametrised over every repository `.md`. It now collects `ARCHITECT_REVIEW.md`, `FIXES.md` and `QA_REVIEW.md` under `.agents/tasks/iteration-11/`, which did not exist when round 1 counted. Confirmed with `pytest --collect-only`. 1063 + 3 + 1 = 1067, so the claimed counts are consistent.

## R2.2 Fix verification

| Item | Status | Evidence |
| :--- | :---: | :--- |
| A-1, dead `_RenderedAttempt.attempt` | ✅ | `src/rendering.py:213-218`: the dataclass holds only `draft` and `qa_report`, and the docstring is reworded. `:232` constructs it without `attempt`. The only remaining `.attempt` read is `:184`, `latest.attempt`, for the log context and `FailureRecord.attempt`, as intended. |
| O-1, keyword-only parameters | ✅ | `_render_and_write(state, document, result, *, share, supervisor_share_seconds, rates)` at `:163-171`, and `_draft_metadata(document, result, rendered, *, own, share, totals, supervisor_share_seconds, rates)` at `:235-245`. Both call sites (`:144-146`, `:189-198`) pass by name. |
| O-2, SPECIFICATIONS.md wording | ✅ | §8.3 now ends "added to `IMPLEMENTATION_PLAN.md` §2 as P13 and so on, and recorded here." The docs-consistency tests pass. |
| O-3, written path checked against `result.path` | ✅ | `:201-205`. The comparison runs after `stage = "persist"`, so a mismatch is recorded as `persist`, logged at ERROR through `_record_failure` and absorbed. `template_engine.save_draft` returns `output_dir / f"{draft_id}.md"`, with `output_dir = result.path.parent`. The check therefore fires exactly when the path's name and the draft ID disagree. `tools.py:298` allocates `drafts_dir / f"{draft_id}.md"`, so production cannot trip it, and it is a pure invariant guard. The documented trade-off holds: the file has already been written at the ID-derived path when the check fires, and the message names both paths. |

The new test `test_a_draft_written_anywhere_but_its_allocated_path_is_a_persist_failure` (`tests/test_unit/test_rendering.py:804-822`) asserts:
- `persistence_failed`;
- doc-a written, and nothing at doc-b's allocated path;
- the failure tuple `("persist", "doc-b", 1)`;
- `builtins.RuntimeError`;
- the allocated path in the message;
- one ERROR line carrying `draft_id` and `stage=persist`.

It is a meaningful test, not one that a stub would pass.

**QA mutations on a scratch copy** (the project `.venv` interpreter, `-p no:cacheprovider`, restored and checked byte-identical with `cmp` afterwards):

| # | Mutation in `src/rendering.py` | Result |
| :---: | :--- | :---: |
| M22 | Path check removed (`if False:`) | killed |
| M23 | Allocated path omitted from the mismatch message | killed |
| M24 | Mismatch returns `True` (reported as success) | killed |
| M25 | `stage = "persist"` dropped, so the mismatch is recorded as `render` | killed |

M10 from round 1 (`attempts = rendered.attempt`) can no longer be written, because the field is gone. `attempts = document.attempts_used` is still pinned by `test_the_rendered_draft_is_latest_drafted_…` (`attempts == 2`).

## R2.3 Acceptance criteria and Red items, re-checked

| # | Criterion | Status | Evidence |
| :--- | :--- | :---: | :--- |
| AC1 | No unresolved template token | ✅ | The test is unchanged and green, against `REAL_TEMPLATE_PATH` (`test_rendering.py:430`) |
| AC2 | `approach_name` renders as `Approach 2 (Research Analyst)` | ✅ | `:421`, `:428`; green |
| AC3 | Per-draft cost equals `estimate_cost` over `stage_telemetry` within 1e-9 | ✅ | `:532`; green |

All 8 Red items from round 1 §3 still pass, and none of their tests changed. The P11 hand check (`**Time Taken:** 32.00s`, `:570`) and the P12 tests (run totals at `:885` and `:901`, no totals line logged) are green. The fix round did not touch `finalise_run`'s signature or arithmetic.

**Definition of Done:** DoD-1 to DoD-5 ✅ (1067 passed, ruff clean, zero-token, every new branch tested, docs-consistency green). DoD-6 is pending at Stage 4.

**Total:** 3/3 acceptance criteria, 8/8 Red items, 5/5 applicable DoD rows.

## R2.4 Gate matrix (round 2 delta)

| Gate | Topic | Status | Notes |
| :--- | :--- | :---: | :--- |
| 1 | Strict TDD | ✅ | O-3 went Red first (`assert False is True` on `persistence_failed` is the expected failure, since the mismatch was reported as success). A-1 and O-1 are refactors under a green suite. |
| 2 | Zero-token testing | ✅ | Unchanged; no model is built; live tests deselected |
| 3 | Pydantic v2 contracts | ✅ | No model changed |
| 4 | Guardrails and attempt cap | ✅ (render side) | Unchanged |
| 5 | Strands integration and telemetry | ✅ | Unchanged |
| 6 | No article text for the Supervisor | n/a in this iteration | |
| 7 | Drafts and logging | ✅ | The new persist failure carries the `(run_id, doc_id, attempt)` correlation and `exc_info` through the shared `_record_failure` |
| 8 | Python and subprocess safety | ✅ | pyright clean, `pathlib.Path` comparison. One of QA's own mutation scripts stalled on a bare `python -` call. Its process tree (PIDs 39272, 40192, 30208, 54804, 34576) was stopped, and a check afterwards found no `python.exe` or `uv.exe` started in the last 20 minutes. The only ones left are the Claude Code MCP servers from 2026-09-29 and 2026-09-30. |

## R2.5 Findings

**🔴 Blocker:** none. **🟡 Major:** none. **🟢 Minor:** none.

O-Q1, O-Q2 and O-Q3 from round 1 remain open as notes for the orchestrator and for Iterations 14 and 16. They do not block.

Verdict: PASS
