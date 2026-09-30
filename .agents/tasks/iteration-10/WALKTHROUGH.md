# Iteration 10 — `save_draft` and draft ID allocation: walkthrough

**Date:** 2026-09-30 · **Branch:** `approach-2/implementation` · **Plan section:** `IMPLEMENTATION_PLAN.md` §5, Iteration 10

## 1. Overview

Iteration 10 completes the Supervisor's four tools. `save_draft` marks one audited document saved and allocates its draft ID, and it writes nothing to disk; the drafts are rendered at run end, in Iteration 11 (D-B, AGENTS.md Rule 5).

* **`allocate_draft_id(state)`**, in the new `src/rendering.py`, numbers drafts past both the files on disk and the IDs this run has already allocated. It dates them from `state.context.today`.
* **`save_draft(doc_id)`** runs `check_save` first. It then resolves the latest audited draft, allocates an ID and sets `DocumentRecord.saved = DraftResult(...)`, logs "Document marked saved", and returns `ToolResult[DraftResult]`.
* **A saved document is closed (P2).** This is now proven through the real tools: after a save, `writer_tool` and `qa_tool` both refuse the document with `already_saved`.

## 2. Files changed

| File | Status | Responsibility |
| :--- | :--- | :--- |
| `src/rendering.py` | New, 58 lines | `allocate_draft_id` and the private `_sequence` and `_DRAFT_ID_PATTERN` |
| `src/tools.py` | Edited, +48 / −1 lines | The `save_draft` body and the private `_save_target`; imports `check_save`, `allocate_draft_id` and `DraftResult` |
| `tests/test_unit/test_rendering.py` | New, 6 tests | The allocator |
| `tests/test_unit/test_tools_save.py` | New, 29 tests | `save_draft` through the tool, AC1 on every call |
| `tests/test_unit/test_module_structure.py` | Edited | `EXPECTED_MODULES` gains `src.rendering` |
| `tests/test_unit/test_tools_scout.py` | Edited | Deletes the placeholder test `test_the_later_tools_are_declared_but_not_yet_built`. Its last row was `save_draft`, and an empty parameter list would leave a permanently skipped test |
| `.agents/docs/IMPLEMENTATION_PLAN.md` | Edited by the orchestrator | The §3 tracker only |
| `.agents/tasks/iteration-10/` | New | `ARCHITECT_REVIEW.md`, `QA_REVIEW.md`, `FIXES.md` and this walkthrough |

**`allocate_draft_id(state: RunState) -> str`:**
* The stamp is `state.context.today` formatted `%Y%m%d`, never the system clock.
* **Disk:** `generate_draft_id(today, drafts_dir)`, Approach 1's unchanged scan, is called only when `drafts_dir.is_dir()`. Called on a missing folder it would create the folder, so a missing folder counts as "next is 1".
* **Run:** the highest sequence among the saved documents' `draft_id`s that are dated today.
* **Result:** `f"draft_{stamp}_{max(disk_next, run_highest + 1):03d}"`. IDs therefore rise in save order.
* **`_sequence(draft_id, stamp)`** parses an ID with `^draft_(\d{8})_(\d{3}|[1-9]\d{3,})$`: three digits zero-padded, or four or more past 999. An ID of another date, or one that is not of that form (such as `_0099`), counts as 0.
* It imports only `generate_draft_id` from `template_engine`, not the file writer, so the §4 name clash cannot arise. `template_engine.py` is unchanged.

**`save_draft(doc_id)`**, entirely inside `log_context(run_id=state.run_id, doc_id=doc_id)`:
1. `check_save(state, doc_id)`. A violation goes to `_refuse`.
2. `_save_target(document)` returns the latest drafted attempt and its report. It raises `RuntimeError` if either is missing, which `check_save`'s `not_audited` makes unreachable through the tool.
3. `allocate_draft_id(state)`, called before `saved` is set.
4. `document.saved = DraftResult(doc_id, draft_id, state.config.drafts_dir / f"{draft_id}.md", report.status)`.
5. Inside `log_context(attempt=latest.attempt)`, INFO `Document marked saved: doc_id=… draft_id=… qa_status=… attempts=<attempts_used> (the draft of attempt <n>)`.
6. Return `ToolResult[DraftResult](result=document.saved, run=state.snapshot()).for_supervisor()`. The snapshot is taken after the save, so `drafts_saved` has risen by 1.

It builds no sub-agent, writes no ledger entry and records no failure. Its name, description and parameter schema are unchanged.

## 3. TDD record

The `save_draft` stub raised `NotImplementedError("save_draft is built in Iteration 10.")`, and `src.rendering` did not exist. Tests that passed on their first run were checked with temporary, reverted mutations, as recorded in the review artifacts.

| # | Behaviour | Red asserted | Green added |
| :---: | :--- | :--- | :--- |
| 1 | First ID, no folder | `_001` on the run's date (not the system date); the folder is still absent. Failed with `ModuleNotFoundError`, then `NotImplementedError` against a skeleton | Stamp from `context.today` plus `_001` |
| 2 | Two saves in one run | `_001` then `_002`. The second returned `_001` | Count the run's saved IDs |
| 3 | Files on disk | With `_002.md` and `_004.md` on disk: `_005` then `_006`; a file named for the system date is ignored; the folder is byte-identical. Got `_001` | The `generate_draft_id` scan, guarded by `is_dir()` |
| 4 | Run ahead of disk; other dates | The run's `_007` beats the disk's `_003`; another date's ID and `_0099` count for nothing | Already met by the prefix filter; refactored into `_sequence` with the regex |
| 5 | A successful save | PASS and WARNING: `saved` is the exact `DraftResult`, returned whole, with `drafts_saved` 1. Failed on the stub | The minimal body; the placeholder test deleted |
| 6 | Every `check_save` refusal | 8 cases × 2 tests: stored, WARNING with `attempt=-`, `result=None`, nothing saved, `drafts_saved` unchanged, no ledger entry or failure. 16 failures: forbidden saves went through, or the call crashed | `check_save` → `_refuse` first |
| 7 | The save log | "Document marked saved" with `doc_id`, `draft_id`, `qa_status` and `attempts = attempts_used`; the correlation `attempt` is the saved draft's. Nothing was logged | The log line |
| 8 | Which report is saved | PASS at attempt 1, ERROR at the cap, and the WARNING of attempt 2 after a failed third call; no attempt used, no ledger entry | Already met; checked by saving attempt 1's report instead |
| 9 | IDs through the tool | Save order, not rank; `_005` and `_006` past a `_004.md`, with the folder listing unchanged | Already met; checked by numbering from the rank index |
| 10 | P2 through the real tools | After draft, WARNING audit and save, `writer_tool(revise=True)`, `writer_tool(revise=False)` and `qa_tool` each return `already_saved` and spend nothing | Already met by the earlier guardrails; checked by never storing `saved` |
| 11 | The invariant helper | With `check_save` patched to allow and no audited draft, the call raises `RuntimeError` and changes, logs and creates nothing. It failed with `AttributeError` | `_save_target` |
| 12 | Fix round 1, M1 | `_999.md` on disk gives `_1000`; a run holding `_1000` gives `_1001`. Both got `_001`, because the three-digit pattern read `_1000` as 0 | The pattern `^draft_(\d{8})_(\d{3}\|[1-9]\d{3,})$` |

## 4. Test results

Fresh run by the orchestrator, after this walkthrough was written:

* `uv run pytest -q`: **1038 passed**, 0 failed, 0 errors.
* Tests added by this iteration: **+39 net** over Iteration 9's 999.
  * 6 in `test_rendering.py` and 29 in `test_tools_save.py`;
  * +1 `test_annotations.py` case, which picks up the new `src/rendering.py`;
  * −1, the deleted placeholder test in `test_tools_scout.py`;
  * +4 `test_docs_consistency.py::test_document_uses_no_forbidden_term` cases, one per new `.md` in `iteration-10/`.
* `uvx ruff check src tests`: **All checks passed!**
* No live test or live command was run. `save_draft` uses no model; the P2 test uses `ScriptedModel`s over an `OfflineSubstrateSession`.

## 5. Acceptance criteria

| Criterion | Status | Evidence |
| :--- | :---: | :--- |
| Red: `allocate_draft_id`, empty folder → `_001`, `_002`; `_004.md` on disk → `_005`, `_006`; run IDs counted; date from `state.context.today` | ✅ | The six tests of `test_rendering.py` |
| Red: success sets `saved = DraftResult(doc_id, draft_id, path, qa_status)` with `path = drafts_dir / f"{draft_id}.md"` | ✅ | `test_an_audited_draft_is_marked_saved_with_its_draft_id_path_and_qa_status[PASS/WARNING]` |
| Red: no file is created | ✅ | `_CheckedTool` compares the drafts folder, absent or present, byte for byte before and after every `save_draft` call |
| Red: `drafts_saved` rises by 1 in the returned snapshot | ✅ | The success test, `test_draft_ids_follow_save_order_not_scout_rank` (1, then 2) |
| Red: INFO "Document marked saved" with `doc_id`, draft ID, QA status and attempts | ✅ | `test_a_save_is_logged_at_info_with_its_draft_id_qa_status_and_attempts_used` × 3 |
| Red: every `check_save` violation, including `draft_ceiling` with `--max-drafts 1` and `error_with_attempts_remaining` | ✅ | `test_a_refused_save_is_stored_logged_and_returned_with_no_result` and `test_a_refused_save_marks_nothing_saved_and_leaves_drafts_saved_unchanged`, each × 8: `not_a_candidate`, `already_saved`, `not_audited` × 3, `error_with_attempts_remaining` at attempts 1 and 2, `draft_ceiling` |
| Red: an `ERROR` at the cap is saved | ✅ | The `error-at-the-cap` case of both `SAVES` tests |
| **AC1:** `drafts_dir` holds no new file after any `save_draft` test | ✅ | `_CheckedTool`, on every call in `test_tools_save.py`; the allocator tests also assert the folder's absence or unchanged contents |
| **AC2:** the four tools are complete, and `test_module_structure.py` lists `src.tools`, `src.guardrails` and `src.rendering` | ✅ | No `NotImplementedError` remains in `src/tools.py`; `EXPECTED_MODULES` lists all three |
| DoD-1 to DoD-5 | ✅ | §4 above; every new function and branch is tested; the docs test passes |
| DoD-6 | ✅ | This file |

## 6. Decisions and deviations

**Decisions (§1.5, or settled from the sources in the pre-flight):**
* **`allocate_draft_id(state: RunState) -> str`** is internal and never seen by the Supervisor. The run's earlier IDs are read from `DocumentRecord.saved`; no field is added to `RunState` (§6.5, "nothing is stored twice").
* **The disk is scanned only if the drafts folder exists,** so that allocation creates nothing, while `template_engine.py` stays Approach 1's verbatim copy.
* **`attempts` in the save log is `attempts_used`** (D-C rule 11, the value `DraftMetadata.attempts` will carry). The line's correlation `attempt` is the saved draft's attempt, and the message names both.
* **Private names:** `_save_target`, `_sequence`, `_DRAFT_ID_PATTERN`.
* **The placeholder test was deleted** rather than left with an empty parameter list.
* **Test organisation:** `_CheckedTool` enforces AC1 and D-F on every `save_draft` call; the `draft_ceiling` case sets `max_drafts=1` on both `PipelineConfig` and `RunContext`, since `check_save` reads the first and the snapshot shows the second.
* **Optional m2 not taken:** `_save_target` and `_revision_source` look alike, but their error messages (one matched by a test), return shapes and invariants differ.

**Deviations and notes:**
* **Stale cross-reference in the plan.** Iteration 10's goal (plan line 554) and Iteration 11's (line 578) cite "§7.8", which does not exist in `SPECIFICATIONS.md`; the section meant is §6.8 "Draft rendering". The code's docstrings cite §6.8. The plan is left as it is, because this workflow edits only its §3 tracker and P-decisions.
* **Known limit inherited from Approach 1.** `generate_draft_id` scans only three-digit file names, so a `_1000.md` already on disk is invisible to it. It is Approach 1's module, kept verbatim, and both reviewers deferred this.
* **For Iteration 14:** the composition root must set both `PipelineConfig.max_drafts` and `RunContext.max_drafts` from `--max-drafts`.
* No other deviation.

## 7. Review

Two rounds were used.

**Round 1.**
* **Architect: CHANGES REQUESTED.** (Its round 1 run was interrupted by an API rate limit and was resumed to finish.)
  * **M1 (Major):** `_DRAFT_ID_PATTERN` accepted exactly three digits. With `_999.md` on disk the allocator returned `_001`, which could overwrite an existing draft at run end, and a run could issue `_1000` twice. **Resolved** by the widened pattern and two Red-first tests.
  * **m1 (optional):** a pyright error in `test_tools_save.py`, where `status: str` was passed for `QAStatus`. **Resolved.**
  * **m2 (optional):** `_save_target` duplicates `_revision_source`. **Not taken,** for the reason in §6.
* **QA: PASS,** with QA-10-1 (optional), the same defect as M1. **Resolved** with M1.

**Round 2.**
* **Architect: APPROVED,** no findings. Its scratch-copy check showed the two new tests fail when the old pattern is restored.
* **QA: PASS,** no findings. It confirmed the same, and that `(\d{3,})` or `(\d+)` would wrongly accept `_0099`.

No item needed a decision.
