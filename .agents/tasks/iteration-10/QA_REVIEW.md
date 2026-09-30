# QA Review: Iteration 10, `save_draft` and draft ID allocation (round 1)

Reviewer: `qa` subagent (criteria in `.agents/skills/code-reviewer/SKILL.md`). Reviewed against the uncommitted working tree on `approach-2/implementation`, on top of `b729c46`.

## 1. Summary and verdict

**Verdict: PASSED.**

I ran the suite and lint myself and the implementer's figures match:

| Command | Result |
| :--- | :--- |
| `uv run pytest -q -p no:cacheprovider` | **1032 passed**, 0 failed, 0 errors, no warnings summary (32.6 s) |
| `uvx ruff check src tests --no-cache` | `All checks passed!` |
| `uv run pytest -m live --collect-only -q` | `no tests collected (1032 deselected)`. That is expected until Iteration 16 |

The claimed count adds up: 999 + 4 (`test_rendering.py`) + 29 (`test_tools_save.py`) + 1 (`test_annotations[rendering.py]`) − 1 (the removed placeholder) = 1032. The diff matches the report. `src/rendering.py` has `allocate_draft_id` and `_sequence`. `src/tools.py` has the `save_draft` body and `_save_target`. `src.rendering` was appended to `EXPECTED_MODULES`, and the Iteration 10 placeholder test was removed. The only other change is the tracker row in `IMPLEMENTATION_PLAN.md` §3, which the orchestrator edited.

I found no blocker and no major finding. There is one minor finding, and it is optional.

## 2. Gate matrix

| Gate | Topic | Status | Notes |
| :--- | :--- | :---: | :--- |
| 1 | Strict TDD | ✅ | The report gives a Red step for each of 11 behaviours: `ModuleNotFoundError`, then `NotImplementedError`, a wrong ID (`_001`), 16 refusal failures, "nothing logged" and `AttributeError`. Where a test passed on its first run (behaviours 4, 8, 9 and 10), the report names the mutation that proved it. I did my own mutation run on a scratch copy, and **13 of 13 mutations were killed** (see §5). Every new branch is exercised: absent or present folder, other-date or malformed ID, each refusal, and the broken-invariant `RuntimeError` |
| 2 | Zero-token testing | ✅ | `save_draft` builds no sub-agent. Every tool set is built over `offline_client(OfflineSubstrateSession())` with `ScriptedModel`s. The P2 test drives the real `writer_tool` and `qa_tool` through scripted turns only. Nothing is marked `live`, and no live command was run |
| 3 | Pydantic v2 contracts | ✅ | `DraftResult` is unchanged, has `ConfigDict(extra="ignore")` and matches §6.4 field for field. The new code adds no model and no `dict[str, Any]`. `allocate_draft_id(state: RunState) -> str` and `_save_target(...) -> tuple[AttemptRecord, QAReport]` are typed. No removed model has come back |
| 4 | Guardrails and attempt cap | ✅ | `check_save` runs first, and its §7.3 order was verified in Iteration 5 by `test_guardrails.py::test_check_save`. Tool-level tests cover every `save_draft` guardrail: `not_a_candidate`, `already_saved`, `not_audited` (three cases), `error_with_attempts_remaining` (attempts 1 and 2) and `draft_ceiling` (`max_drafts=1`). Each test asserts that the violation is stored, logged at WARNING with correlation `(run_id, doc_id, "-")` and returned with `result=None`, and that nothing is saved, spent or allocated. An `ERROR` at the cap is saved (`error-at-the-cap`). P2 is also shown through the real tools: after a save, `writer_tool(revise=True)`, `writer_tool(revise=False)` and `qa_tool` each return `already_saved` and spend nothing |
| 5 | Strands integration and telemetry | n/a in this iteration | `save_draft` is plain Python. Tests assert that it adds no ledger entry |
| 6 | No article text for the Supervisor | ✅ | Every `save_draft` call in `test_tools_save.py` goes through `_CheckedTool`, which checks four things. The result has exactly the keys `result`, `run` and `error`. `run` equals the state's snapshot. `result` is the stored `DraftResult` with keys `{doc_id, draft_id, path, qa_status}`. `FORBIDDEN_SUPERVISOR_KEYS` appear at no depth, and no article text appears in the returned string |
| 7 | Drafts and logging | ✅ | **AC1** is enforced: the drafts folder, whether present or absent, is byte-identical before and after every `save_draft` call. With no folder, the allocator creates none, because of the `is_dir()` guard, and mutation M2 proves the guard is needed. The ID date is `state.context.today`, and the tests pin a date other than the system date. IDs count both the disk and the run, and follow save order. The D-I "Document marked saved" event is logged at INFO with `doc_id`, the draft ID, the QA status and `attempts=attempts_used`, and the correlation `attempt` is the saved draft's. Rendering is correctly deferred to Iteration 11 |
| 8 | Python and subprocess safety | ✅ | Annotations are complete (`test_annotations[rendering.py]` passes) and imports are at the top of each file. Paths use `pathlib.Path` (`drafts_dir / f"{draft_id}.md"`). No orphaned process was left: the only `python.exe` and `uv.exe` processes after the run were the harness's own MCP servers, which were started before it. The scratch copy has been removed |

## 3. Acceptance criteria and Definition of Done

| # | Criterion | Status | Evidence |
| :--- | :--- | :---: | :--- |
| Red-1 | `allocate_draft_id`: an empty folder gives `_001` then `_002`; with `_004.md` on disk, `_005` then `_006`; IDs allocated earlier in the run are counted; the date comes from `state.context.today` | ✅ | `test_rendering.py`, all 4 tests. Mutations M1, M3, M4 and M5 are killed |
| Red-2 | Success sets `saved = DraftResult(doc_id, draft_id, path, qa_status)` with `path == drafts_dir / f"{draft_id}.md"` | ✅ | `test_an_audited_draft_is_marked_saved_...[PASS, WARNING]`. M7 and M9 are killed |
| Red-3 | No file is created | ✅ | `_CheckedTool` compares a byte snapshot on every call, and the allocator tests assert `not drafts_dir.exists()` |
| Red-4 | `drafts_saved` rises by 1 in the returned snapshot | ✅ | Exact `run` dict asserted, plus `[1, 2]` across two saves |
| Red-5 | INFO "Document marked saved" with `doc_id`, the draft ID, the QA status and the attempts | ✅ | `test_a_save_is_logged_at_info_...`, 3 cases. M6 and M10 are killed |
| Red-6 | Every `check_save` violation has a test, `draft_ceiling` with max-drafts 1 and `error_with_attempts_remaining` included | ✅ | `REFUSALS`: 8 cases × 2 tests |
| Red-7 | An `ERROR` at the cap is saved | ✅ | `error-at-the-cap`, in both the log test and the save test |
| AC1 | `drafts_dir` holds no new file after any `save_draft` test | ✅ | `_CheckedTool` snapshot, and `test_with_004_on_disk_...` checks the folder listing |
| AC2 | The four tools are complete, and `test_module_structure.py` lists `src.tools`, `src.guardrails` and `src.rendering` | ✅ | `grep NotImplementedError src/` finds nothing, and `EXPECTED_MODULES` has all three |
| DoD-1 | Full suite passes | ✅ | 1032 passed |
| DoD-2 | Lint is clean | ✅ | `All checks passed!` |
| DoD-3 | No live model call | ✅ | Gate 2 |
| DoD-4 | Every new `src/` function is exercised | ✅ | `allocate_draft_id`, `_sequence`, the `save_draft` body and `_save_target`, both of its branches included |
| DoD-5 | Docs match code | ✅ | `test_docs_consistency.py` is inside the 1032 |
| DoD-6 | Record written | n/a | The orchestrator writes it at Stage 4 |

**Acceptance criteria: 9 of 9 passed** (Red-1 to Red-7, AC1 and AC2). **Definition of Done: 5 of 5 passed.** DoD-6 is pending at Stage 4.

## 4. Findings by severity

### 🔴 Blocker
None.

### 🟡 Major
None.

### 🟢 Minor (optional)

**QA-10-1 (optional). Past sequence 999, the allocator can fall back to `_001` and collide with a file on disk.**
* **Where:** `src/rendering.py:19`, `_DRAFT_ID_PATTERN = re.compile(r"^draft_(\d{8})_(\d{3})$")`.
* **What happens:** with `draft_{today}_999.md` on disk, `generate_draft_id` returns `draft_{today}_1000`. `_sequence` does not match that ID and returns `0`, so `disk_next = 0`. The result is then `max(0, run_highest + 1)`, which is `_001` when the run has saved nothing yet. `_001` may already exist on disk, which breaks Gate 7's "IDs never collide".
* **Reach:** it needs 999 or more drafts on a single day, so it is pathological. Approach 1 has a similar ceiling of its own: its `\d{3}` regex keeps returning `_1000`.
* **Suggested change:** widen the group to `(\d{3,})`. The `_0099` malformed-ID test would then need rethinking, because `0099` would parse as 99. Alternatively, treat a disk result that does not parse as an error and raise. This is optional, and not needed for PASS.

**Informational (no action for the implementer).** The plan's Iteration 10 goal (line 554) and Iteration 11 goal (line 578) cite "§7.8", which does not exist in `SPECIFICATIONS.md`. The implementer's docstrings correctly cite §6.8 "Draft IDs". The orchestrator has said it will record this.

## 5. Mutation checks (scratch copy, since deleted)

These were run on `test_rendering.py` and `test_tools_save.py`. Every mutation made at least one test fail.

| # | Mutation | Result |
| :---: | :--- | :--- |
| M1 | Ignore the run's saved IDs | 5 failed |
| M2 | Drop the `is_dir()` guard, so the scan creates the folder | 16 failed |
| M3 | Use the system date instead of `context.today` | 11 failed |
| M4 | Drop the date-stamp filter in `_sequence` | 1 failed |
| M5 | `disk_next + run_highest` instead of `max(...)` | 3 failed |
| M6 | Log `attempts=latest.attempt` instead of `attempts_used` | 1 failed |
| M7 | Hard-code `qa_status="PASS"` | 4 failed |
| M8 | Skip `check_save` | 16 failed |
| M9 | Build the path under `log_dir` | 2 failed |
| M10 | Drop the inner `log_context(attempt=...)` | 3 failed |
| M11 | Take the report from attempt 1 | 2 failed |
| M12 | Never scan the disk | 2 failed |
| M13 | `_save_target` never raises | 2 failed (`AttributeError` instead of `RuntimeError`) |

## 6. Substrate shapes

`save_draft` makes no substrate call, and this iteration adds no integration assertion about substrate shapes, so there was nothing to confirm with the `hse-easy-mock` tools.

**Verdict: PASS**

---

# QA Review: Iteration 10, round 2 (after fix round 1)

## R2.1 Summary and verdict

**Verdict: PASS.** QA-10-1 and architect M1, which were the same defect, are fixed and covered by tests that kill the old pattern. Architect m1 is fixed. The implementer declined m2, which was optional, and gave a reason; QA accepts that. Round 2 raises no new blocker or major finding.

I ran the checks myself:
* `uv run pytest -q` gives **1037 passed in 33.68s**, with no warnings. That matches the implementer's claimed 1037.
* `uvx ruff check src tests --no-cache` gives `All checks passed!`.
* `uv run pytest -m live --collect-only -q` gives `no tests collected (1037 deselected)`. This is the only live command I ran (P4).

## R2.2 Fix verification

| Item | Claim | Evidence | Result |
| :--- | :--- | :--- | :--- |
| M1 / QA-10-1 | The pattern now accepts IDs past 999 | `src/rendering.py:19` is `^draft_(\d{8})_(\d{3}\|[1-9]\d{3,})$`. The comment at lines 17-18 and the `Returns` docstring at line 35 are updated. | ✅ |
| M1, Red tests | Two new tests, `test_with_999_on_disk_the_next_id_is_1000_not_a_fallback_to_001` (`test_rendering.py:104`) and `test_a_run_already_holding_1000_allocates_1001_not_a_second_1000` (`:113`) | A scratch mutation back to `(\d{3})` fails exactly these two tests (2 failed, 4 passed), so they are real Red tests. | ✅ |
| M1, `_0099` still malformed | The `_0099` test is unchanged and still meaningful | Scratch mutations to `(\d{3,})` and to `(\d+)` each fail `test_the_run_ids_count_when_ahead_of_the_disk_and_only_those_on_the_runs_date` (1 failed, 5 passed). The leading-zero exclusion is therefore pinned. | ✅ |
| M1, `template_engine.py` untouched | Approach 1's verbatim module is not modified | `git status` shows no change to `src/template_engine.py`. | ✅ |
| m1 | `status: QAStatus` | `test_tools_save.py:30` imports `QAStatus`, and line 210 annotates the parameter with it. | ✅ |
| m2 | Not taken, with a reason | The reason is sound, and the item was optional. | Accepted |

I deleted the scratch copy after the mutation runs. The mutations ran in the foreground, so none of my runs left a process behind.

## R2.3 Acceptance criteria and Definition of Done, re-checked

| # | Criterion | Evidence | Result |
| :--- | :--- | :--- | :--- |
| AC1 | `drafts_dir` holds no new file after any `save_draft` test | `test_tools_save.py:157-161` compares `_folder_contents` before and after. The architect's round 1 mutation also confirmed it. Fix round 1 did not change `src/tools.py`. | ✅ |
| AC2 | The four tools are complete, and `test_module_structure.py` lists `src.tools`, `src.guardrails` and `src.rendering` | `test_module_structure.py:24-27` lists all three, and the suite passes. | ✅ |
| Red list | Allocator `_001`/`_002`, `_004.md` gives `_005`/`_006`, run-counted, the date from `context.today`; the `save_draft` success path, the no-file check, `drafts_saved`, the INFO log; every `check_save` violation; an ERROR saved at the cap | These are unchanged since round 1, where each was verified, and they still pass. | ✅ |
| DoD | The suite is green, ruff is clean, zero tokens, Markdown only, `pathlib.Path` | See R2.1. The fix touches only a regex, a comment and a type annotation. | ✅ |

**2 out of 2 acceptance criteria are met,** and every Definition of Done row still holds.

## R2.4 Findings by severity

* **🔴 Blocker:** none.
* **🟡 Major:** none.
* **🟢 Minor:** none new.

**Deferred, and not a finding against this iteration:** `generate_draft_id` in `src/template_engine.py:21` scans only 3-digit file names. A file `draft_{today}_1000.md` on disk is therefore invisible to it, and so to the allocator, whenever the run holds no ID at or above 1000. This is the inherited limit of Approach 1's verbatim module (D-J), and both reviewers agreed to defer it in round 1.

**Verdict: PASS**
