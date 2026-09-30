# Iteration 10 — `save_draft` and draft ID allocation: Architect review, round 1

**Reviewer:** architect (Stage 3, round 1). The criteria are `.agents/skills/architect-review/SKILL.md` and `.agents/skills/code-reviewer/SKILL.md`.

**Scope:** the uncommitted diff on `approach-2/implementation`. I checked it with `git status --short` and `git diff`, and read the new files directly.
* `src/rendering.py`: new, 57 lines. It holds `allocate_draft_id`, `_sequence` and `_DRAFT_ID_PATTERN`.
* `src/tools.py`: modified.
  * The `save_draft` body is at lines 283-310.
  * `_save_target` is at lines 677-693.
  * Three imports were added, at lines 45, 51 and 58.
* `tests/test_unit/test_rendering.py`: new, 4 tests.
* `tests/test_unit/test_tools_save.py`: new, 29 tests.
* `tests/test_unit/test_module_structure.py`: `"src.rendering"` appended.
* `tests/test_unit/test_tools_scout.py`: the `save_draft` placeholder test was removed.
* `.agents/docs/IMPLEMENTATION_PLAN.md`: only the tracker row changed, to "In progress".

`src/schemas.py`, `src/guardrails.py`, `src/agents.py`, `src/template_engine.py` and `.agents/templates/draft.md` are unchanged. `src/template_engine.py` matches `../code-orchestration/src/template_engine.py` except for line endings (`diff --strip-trailing-cr`).

**Commands run.** No live command was run (P4).
* `uv run pytest -q` gives **1032 passed** in 37.3 s.
* `uvx ruff check src tests --no-cache` gives `All checks passed!`.
* `uv run --with pyright pyright src/rendering.py src/tools.py tests/test_unit/test_rendering.py tests/test_unit/test_tools_save.py` gives **1 error**, at `tests/test_unit/test_tools_save.py:216` (see m1).
  * The whole tree has 185 pyright errors. The other 184 are pre-existing, in reused modules and tests this iteration did not touch.
  * Pyright is not a DoD gate.
* **Mutation check,** in a scratch copy outside the repository. I removed the `if drafts_dir.is_dir() else 1` guard at `src/rendering.py:40`, so `generate_draft_id` would create the folder. Then I ran `test_rendering.py` and `test_tools_save.py`: **16 failed, 17 passed**. The "no file, no folder" claim behind AC1 is really enforced.
* **Edge probe,** a script in the scratchpad. With `draft_20260314_999.md` on disk, `allocate_draft_id` returns **`draft_20260314_001`** (see M1).

---

## 1. Overall verdict

**APPROVED WITH RESERVATIONS**, which means **CHANGES REQUESTED** for this round.

`save_draft` does what the sources require:
* It follows D-B, D-C rules 9 to 11, §6.4, §6.8 and §7.3.
* It writes no file.
* It returns only a `DraftResult` (D-F).
* It moves no control flow out of the Supervisor.

There is no architectural violation.

There is one required fix, **M1 (🟡 Major)**. The new allocator misreads `generate_draft_id`'s result past sequence 999. It then falls back to `_001`, an ID that can already exist on disk, so the draft at run end would overwrite it. That breaks Gate 7 ("IDs never collide with files on disk"), and it contradicts the allocator's own docstring.
* **Likelihood:** very low, because it needs 999 drafts on one date.
* **Why it is still required:** the defect is in new code, it makes the allocator worse than the function it reuses, and the fix is one line plus one test.
* **Severity versus QA:** QA found the same defect independently (QA-10-1) and rated it Minor and optional. I rate it higher for the reasons above. The orchestrator should note the difference.

There are two optional 🟢 Minor items. There are no "Needs a decision" items.

---

## 2. Pillar audit

### Pillar 1: An agent owns the flow — ✅
* `save_draft` (`src/tools.py:283-310`) is plain Python.
  * It calls no other tool and no sub-agent, and it never loops.
  * It never chooses a next step.
* A refusal returns at once through `_refuse` (line 289), with the violation and `result=None`.
* `_save_target` (lines 677-693) raises `RuntimeError` only on a broken guardrail invariant. It never reroutes. This matches the style of its siblings `_revision_source` (line 542) and `_audit_target` (line 642).

### Pillar 2: Division of labour and D-F — ✅
* The result is `ToolResult[DraftResult](result=document.saved, run=state.snapshot())`. Its only keys are `doc_id`, `draft_id`, `path` and `qa_status` (§6.4), so no article text can reach the Supervisor.
* Every `save_draft` call in `test_tools_save.py` goes through `_CheckedTool` (lines 142-161), which applies `_assert_supervisor_view` (lines 122-139). That check covers:
  * the exact key set;
  * a `run` equal to the snapshot;
  * a `result` equal to the stored `DraftResult`;
  * no forbidden key at any depth;
  * none of the run's article text anywhere in the string.
* Code makes no editorial decision. Which draft is saved is fixed by D-C rule 9: the `latest_drafted` attempt, with its own report.

### Pillar 3: Custom agent tools — ✅
* `save_draft` is the plain-Python tool of D-A, so it builds no agent and writes no ledger entry. `test_the_save_takes_the_latest_drafted_attempts_report_and_spends_nothing` asserts that the ledger, the failures and the violations all stay empty.
* The tool is keyed by `doc_id`.
* The name, the §7.1 description and the `(doc_id: str)` schema are unchanged from Iteration 7. `SAVE_DRAFT_TOOL_DESCRIPTION` (lines 120-123) matches §7.1 word for word.

### Pillar 4: Guardrails and attempt state — ✅
* `check_save` (Iteration 5, `src/guardrails.py:202-241`) runs first, in the §7.3 order. The tool adds no guardrail, so the count stays at 12.
* Each `check_save` violation is reached through the tool, parametrised in `REFUSALS` (`test_tools_save.py:285-294`):
  * `not_a_candidate` (P3);
  * `already_saved`, from a second save through the tool (P2);
  * `not_audited`, in three shapes;
  * `error_with_attempts_remaining` at attempts 1 and 2;
  * `draft_ceiling` with `max_drafts=1`.
* Two tests check that each refusal is complete:
  * the first checks that it is stored, logged at WARNING with `(run_id, doc_id, "-")`, and returned with `result=None`;
  * the second checks that nothing is marked saved and `drafts_saved` does not change.
* An `ERROR` at the cap is saved (`_error_at_the_cap`, SAVES row 2), as the plan requires.
* P2 through the real tools: `test_after_a_save_writer_tool_and_qa_tool_refuse_the_document_with_already_saved` (lines 467-495) drafts, audits and saves a document. It then shows that `writer_tool` with `revise=True`, `writer_tool` with `revise=False` and `qa_tool` are each refused with `already_saved`. None of them uses an attempt or writes a ledger entry.
* A save uses no attempt, as `attempts_used` shows before and after.

### Pillar 5: Benchmark parity — ✅
* No prompt, model, effort, tool binding, template or cost file changed.
* `generate_draft_id` is reused as it is. `src/rendering.py` does not copy it; it calls it (§4, "reusing `generate_draft_id`'s disk scan").
* The name-clash rule of §4 holds. Neither module imports `template_engine.save_draft`, and Iteration 11 will import it as `write_draft_file`.

### Pillar 6: Substrate isolation and lifecycle — not touched by this iteration
`save_draft` does not touch the MCP client.

### Pillar 7: Rendering, telemetry and logging — ✅, apart from M1
* **No file is written.**
  * `allocate_draft_id` scans the folder only if it already exists (`src/rendering.py:40`), because `generate_draft_id` would otherwise create it (`src/template_engine.py:18`).
  * `_CheckedTool` compares the folder's bytes before and after every `save_draft` call.
  * The mutation check above shows the guard is load-bearing. AC1 holds.
* **Draft IDs are run-aware** (§6.8).
  * The date is `state.context.today`, never the clock. `test_rendering.py:47` and `:75` guard against a clock-read.
  * The next number is `max(disk_next, run_highest + 1)`, over the documents already saved on the run's date.
  * `allocate_draft_id` runs before `saved` is set (line 294), so a document never counts its own ID.
  * IDs follow save order, not Scout rank (`test_draft_ids_follow_save_order_not_scout_rank`).
* **The D-I "Document marked saved" event** is at INFO (lines 301-309). It carries `doc_id`, `draft_id`, `qa_status` and `attempts=attempts_used`, as D-C rule 11 requires.
  * Its correlation `attempt` is the saved draft's attempt. That is a sound reading, and a test pins it (the attempt-2 draft after a failed third call).
  * The refusal lines carry `attempt="-"`.
  * The D-I line "`writer_tool` and `save_draft` log the QA status of the latest draft" is met.
* **The M1 defect:** the collision guarantee fails past sequence 999. See §3.

### Pillar 8: Code quality and Python conventions — ✅, apart from m1
* The imports are at the top and grouped: standard library, then local (`src/rendering.py:9-13`). Ruff reports zero E402.
* Every signature is fully annotated.
  * `_DRAFT_ID_PATTERN: Final[re.Pattern[str]]`.
  * `_save_target(...) -> tuple[AttemptRecord, QAReport]`.
* `__all__` is declared, and `pathlib.Path` is used throughout.
* No `dict[str, Any]` crosses a module boundary. `Any` appears only in test helpers.
* The docstrings are honest, with one exception: `allocate_draft_id`'s claim "past every draft on disk" is false past 999 (M1).
* There is no dead code. The removed placeholder test left no unused import, as ruff confirms.

---

## 3. Code review findings

### M1 (🟡 Major, required): past sequence 999, the allocator falls back to `_001`
* **Where:** `src/rendering.py:19`, where `_DRAFT_ID_PATTERN = re.compile(r"^draft_(\d{8})_(\d{3})$")` accepts exactly three digits. `_sequence` (lines 52-57) uses that pattern on both sides of the allocation.
* **Disk side.** With `draft_{today}_999.md` on disk:
  * `generate_draft_id` correctly returns `draft_{today}_1000`;
  * `_sequence` maps that to `0`, so `disk_next = 0`;
  * with no earlier save in the run, `max(0, 0 + 1)` gives **`_001`**. I confirmed this by running it.
  * If `_001.md` exists, the draft rendered at run end overwrites it without a warning.
* **Run side.** Once the run has allocated `_1000` (formatted by `:03d`), `_sequence("…_1000")` returns `0` as well. The run's maximum falls back, and the next save can be given `_1000` a second time. Two documents would then share one `path`.
* **Why it matters:** Gate 7 says "IDs never collide with files on disk or with IDs allocated earlier in the run". Approach 1's `generate_draft_id` gives `_1000` here, so the adapter is worse than the function it reuses.
* **Remedy:** see `FIXES.md` M1. Accept exactly what `f"{n:03d}"` produces for `n ≥ 1`, and nothing else. That way `_0099` stays malformed, and the existing test at `test_rendering.py:84-101` stays valid.
* **Inherited limit, deferred.** `generate_draft_id` has its own `\d{3}` file pattern (`src/template_engine.py:21`), so it ignores a `_1000.md` file on disk. A second run on the same date past 999 could therefore still collide. That is Approach 1's reused module, which stays verbatim (D-J), and the `XXX` format of §6.8 is three digits. It is not in this iteration's scope, and it needs no decision in a proof of concept.

### m1 (🟢 Minor, optional): one pyright error in the new test file
* **Where:** `tests/test_unit/test_tools_save.py:208`. The parametrised `status: str` is passed to `DraftResult(qa_status=status)` at line 216, where the type is `QAStatus`.
* The other `test_tools_*.py` files are pyright-clean.
* **Remedy:** annotate the parameter as `status: QAStatus`, importing `QAStatus` from `src.schemas`.

### m2 (🟢 Minor, optional): `_save_target` repeats `_revision_source`'s lookup
* **Where:** `src/tools.py:677-693` and `542-558`. Both resolve "the latest drafted attempt that has a QA report, else raise `RuntimeError`". They differ only in the return shape and the message.
* A shared private helper could serve both.
* The duplication is small, and it is consistent with `_audit_target`'s pattern, so leave it unless you are editing those lines anyway.

---

## 4. Anti-patterns and risks

* **Autonomy leaks:** none. No code sequences a sub-agent or chooses the Supervisor's next step.
* **Parity drift:** none.
* **Article text reaching the Supervisor:** none. `DraftResult` holds no text, and every call is checked structurally.
* **State coupling (a note for Iteration 11, not a finding).**
  * `check_save` compares `drafts_saved` with `state.config.max_drafts`, while the Supervisor sees `RunContext.max_drafts`. The tests set both.
  * The composition root in Iteration 14 must set them from the same `--max-drafts` value. This behaviour predates this iteration (Iteration 5).
* **Documentation (a note for the orchestrator, not a question).** `IMPLEMENTATION_PLAN.md:554` and `:578` cite "§7.8". `SPECIFICATIONS.md` has no §7.8; the draft-rendering section is §6.8.
  * The docstrings correctly cite §6.8.
  * No contract depends on the reference. Record it in the walkthrough as a stale cross-reference.

---

## 5. Remediation directives

1. **M1, required.** Change `src/rendering.py:19`, and write a Red test first, in `tests/test_unit/test_rendering.py`, for the disk case and the run case. Sources: Gate 7 of the code-reviewer skill, `SPECIFICATIONS.md` §6.8 "Draft IDs", and the allocator's own docstring.
2. **m1 and m2, optional.**

**Ruff:** 0 in-scope findings (blocking) and 0 pre-existing findings (deferred).

**Verdict: CHANGES REQUESTED**

---

# Round 2: re-review after fix round 1

**Reviewer:** architect (Stage 3, round 2).

**Scope:** the fix round's changes to `src/rendering.py`, `tests/test_unit/test_rendering.py` and `tests/test_unit/test_tools_save.py`.
* I read the files directly, because all three are untracked.
* The file timestamps and `git diff --stat` show that `src/tools.py` was not modified after round 1. `save_draft` is still at line 284, `_save_target` at 677 and `_revision_source` at 542.
* `git diff --quiet -- src/template_engine.py` confirms that the reused module is unchanged.

**Commands run.** No live command was run (P4).
* `uv run pytest -q` gives **1037 passed** in 35.4 s. That is round 1's 1032, plus the 2 new allocator tests, plus 3 docs tests that the new review files add.
* `uvx ruff check src tests --no-cache` gives `All checks passed!`.
* `uv run --with pyright pyright src/rendering.py src/tools.py tests/test_unit/test_rendering.py tests/test_unit/test_tools_save.py` gives **0 errors**.
* **Pattern probe.** For every `n` from 1 to 20000, `_sequence(f"draft_20260314_{n:03d}", "20260314") == n`.
  * `_0099`, `_0100`, `_01` and `_1000.md` all give 0.
  * `_000` also gives 0, and `f"{n:03d}"` never produces it for `n >= 1`.
* **Mutation check,** in a scratch copy outside the repository. I reverted line 19 to `(\d{3})$` and ran `test_rendering.py` and `test_tools_save.py`. **Exactly the two new tests failed** (2 failed, 33 passed), so the fix is pinned by tests.

## 1. Overall verdict

**APPROVED.**

## 2. Status of the round 1 findings

| ID | Severity | Status | Evidence |
| :--- | :--- | :--- | :--- |
| M1 | 🟡 Major, required | **Closed** | `src/rendering.py:19` accepts exactly what `f"{n:03d}"` produces for `n >= 1`. The disk case (`_999.md` gives `_1000`) and the run case (`_1000` held gives `_1001`) are covered by `test_rendering.py:104-123`. The mutation check confirms both tests. |
| m1 | 🟢 Minor, optional | **Closed** | `status: QAStatus` at `test_tools_save.py:210`, imported from `src.schemas` at line 30. Pyright reports 0 errors on the touched files. |
| m2 | 🟢 Minor, optional | **Not taken; accepted** | The two helpers differ in message (`save_draft`'s message is matched by a test), in return shape and in invariant. Merging them would save about four lines, which does not make the code clearer. |
| QA-10-1 | Minor, optional | **Closed** | The same defect as M1. |

## 3. Re-check of what the fix touched

* **Comment and docstring.**
  * The `#:` comment at lines 17-18 now states the accepted forms honestly, including that `_0099` is not a draft ID.
  * The `Returns` line (line 35) now says the sequence is "zero-padded to three digits and wider past 999", which matches line 49's `:03d`.
  * The claim "past every draft on disk and every ID this run allocated" is now true for every ID this run can issue.
  * It is true for disk files up to `_999`. The remaining gap is the inherited `\d{3}` file scan in `src/template_engine.py:21`, which stays deferred as recorded in round 1 (D-J).
* **The `_0099` test** (`test_rendering.py:84-101`) is unchanged, and it still passes against the new pattern. The alternation `[1-9]\d{3,}` is what keeps it valid; a plain `\d{3,}` would have broken it.
* **Pillars 1 to 7.** The fix is a regex and two tests, so no control flow, tool result, guardrail, prompt, model, template or cost file changed. The round 1 pillar audit stands unchanged.
* **Pillar 8.**
  * The import block of `test_tools_save.py` stays grouped and sorted, with zero E402.
  * The signature wrap at lines 209-211 respects the line length.
  * There is no dead code.
* **No new finding.** One observation that I did not raise as a finding: `re.match` with `$` also accepts a trailing `\n`. This does not matter here, because `_sequence` reads only IDs that the code itself built.

## 4. Anti-patterns and risks

None new. The Iteration 11 note from round 1 still holds: `check_save` reads `state.config.max_drafts`, while the Supervisor sees `RunContext.max_drafts`, so the composition root must set both. So does the walkthrough note: `IMPLEMENTATION_PLAN.md:554` and `:578` cite a "§7.8" that does not exist, and the section meant is §6.8.

## 5. Remediation directives

None.

**Ruff:** 0 in-scope findings (blocking) and 0 pre-existing findings (deferred).

**Verdict: APPROVED**
