
## QA — round 1

I verified it myself: `uv run pytest -q` gives **1032 passed**, and `uvx ruff check src tests` gives `All checks passed!`. I found no blocker and no major finding, so there is **no required fix**. The full review is in `QA_REVIEW.md`.

### 🧪 Quality Assurance & Test Verification

- **QA-10-1 (Minor, OPTIONAL, not required for PASS).** Past sequence 999, the allocator can fall back to `_001` and collide with a file on disk.
  * **Where:** `src/rendering.py:19`, `_DRAFT_ID_PATTERN = re.compile(r"^draft_(\d{8})_(\d{3})$")`.
  * **What happens:** with `draft_{today}_999.md` on disk, `generate_draft_id` returns `draft_{today}_1000`. `_sequence` returns `0` for that ID, so `disk_next = 0`. With no earlier save in the run, `allocate_draft_id` then returns `draft_{today}_001`, which may already exist on disk.
  * **Fix, if taken:** widen the sequence group to `(\d{3,})`, or raise when the disk result does not parse, and add a Red test with `_999.md` on disk. Rethink the `_0099` case in `test_the_run_ids_count_when_ahead_of_the_disk_and_only_those_on_the_runs_date` accordingly.

## ❓ Needs a decision

None from QA.

## Architect — round 1

**Verdict: CHANGES REQUESTED.** In the architecture review's terms this is APPROVED WITH RESERVATIONS, because there is no architectural violation.
* There is one required item, 🟡 Major, and two optional 🟢 Minor items.
* **Ruff:** 0 in-scope findings and 0 pre-existing debt.
* `uv run pytest -q` gives 1032 passed.
* The full review is in `ARCHITECT_REVIEW.md`.

### 🏛️ Architecture & System Boundaries

None. `save_draft` is plain Python and sequences nothing:
* it runs `check_save` first, in the §7.3 order;
* it allocates the ID before `saved` is set;
* it writes no file (AC1, which a mutation check confirmed);
* it returns only a `DraftResult` (D-F).

### 🧹 Code Quality & Conventions

- **M1 (🟡 Major, required): past sequence 999, the allocator falls back to `_001` and collides.** This is the same defect as QA-10-1. I found it independently, and I rate it higher: it breaks Gate 7 ("IDs never collide with files on disk or with IDs allocated earlier in the run") in new code, and the fix is one line.
  * **Where:** `src/rendering.py:19`. `_DRAFT_ID_PATTERN` accepts exactly `\d{3}`.
  * **Disk side.** With `draft_{today}_999.md` on disk, `generate_draft_id` returns `_1000`, and `_sequence` maps it to `0`. With no earlier save in the run, the call returns `draft_{today}_001`; I confirmed this by running it.
  * **Run side.** Once the run has allocated `_1000`, `_sequence` also gives `0` for it, so the next save can get `_1000` again.
  * **Change:**
    1. Red, in `tests/test_unit/test_rendering.py`, write two tests:
       * `draft_{STAMP}_999.md` on disk: the call gives `draft_{STAMP}_1000`;
       * a document already saved as `draft_{STAMP}_1000`: the call gives `draft_{STAMP}_1001`.
       Both fail today, with `_001` and `_001`.
    2. Green: change line 19 to `re.compile(r"^draft_(\d{8})_(\d{3}|[1-9]\d{3,})$")`. That accepts exactly what `f"{n:03d}"` produces for `n ≥ 1`. The `_0099` case at `tests/test_unit/test_rendering.py:95` stays malformed, and that test stays valid unchanged.
    3. Update the comment at lines 17-18 to match.
  * **Do not change `src/template_engine.py`.** Its own `\d{3}` file scan at line 21 is Approach 1's verbatim module (D-J). The remaining limit there, that a `_1000.md` file on disk is invisible to the scan, is inherited and deferred.
  * **Sources:** code-reviewer Gate 7, `SPECIFICATIONS.md` §6.8 "Draft IDs", and the `allocate_draft_id` docstring ("past every draft on disk and every ID this run allocated").
- **m1 (🟢 Minor, optional): one pyright error.** At `tests/test_unit/test_tools_save.py:216`, a parameter typed `status: str` (line 208) is passed to `DraftResult(qa_status=...)`, which expects `QAStatus`. Annotate the parameter as `status: QAStatus`, imported from `src.schemas`. The other `test_tools_*.py` files are pyright-clean. Pyright is not a DoD gate.
- **m2 (🟢 Minor, optional): `_save_target` repeats `_revision_source`'s lookup.** They are at `src/tools.py:677-693` and `542-558`, and both look for the latest drafted attempt that has a QA report, else raise `RuntimeError`. A shared private helper could serve both. Leave it unless you are editing those lines anyway.

### ❓ Needs a decision

None from the architect.

**Note for the orchestrator's walkthrough, not a question:** `IMPLEMENTATION_PLAN.md:554` and `:578` cite "§7.8", which does not exist. The section meant is `SPECIFICATIONS.md` §6.8.

## Implementation — fix round 1

- **M1 / QA-10-1 (required): resolved.**
  * **Red:** two tests added to `tests/test_unit/test_rendering.py`:
    * `test_with_999_on_disk_the_next_id_is_1000_not_a_fallback_to_001`;
    * `test_a_run_already_holding_1000_allocates_1001_not_a_second_1000`.
    Both failed as predicted, returning `draft_20260314_001`.
  * **Green:** in `src/rendering.py`, `_DRAFT_ID_PATTERN` is now `^draft_(\d{8})_(\d{3}|[1-9]\d{3,})$`. That is exactly what `f"{n:03d}"` produces for `n >= 1`. I updated the comment and the `Returns` docstring to match.
  * The `_0099` malformed-ID test is unchanged and still passes.
  * `src/template_engine.py` is not modified. Its scan of `_1000.md` files on disk stays an inherited limit, deferred.
- **m1 (optional): resolved.** In `tests/test_unit/test_tools_save.py`, the parametrised `status` is now annotated `QAStatus`, imported from `src.schemas`. Pyright showed 1 error on the file before the change and 0 after.
- **m2 (optional): not taken, on purpose.** `_save_target` and `_revision_source` differ in three ways:
  * their `RuntimeError` messages name different tools and guardrails, and the `save_draft` message is matched by a test;
  * they return different shapes, a tuple and `_Revision`;
  * their docstrings state different invariants.
  A shared helper would need the message passed in and would save about four lines. That trade does not make the code clearer, so I left both functions as they are.

## QA — round 2

**Verdict: PASS.**
* `uv run pytest -q` gives 1037 passed.
* `uvx ruff check src tests --no-cache` gives `All checks passed!`.
* QA-10-1 / M1 is verified fixed. A scratch mutation back to `(\d{3})` fails both new tests. Mutations to `(\d{3,})` and `(\d+)` fail the `_0099` test, so the leading-zero exclusion is pinned.
* m1 is verified fixed. m2 was declined with a reason, and QA accepts that.

### 🧪 Quality Assurance & Test Verification

None. There is no new defect and no open fix.

### ❓ Needs a decision

None from QA.

## Architect — round 2

**Verdict: APPROVED.** The required item is resolved, and no new item is opened.
* `uv run pytest -q` gives **1037 passed**.
* **Ruff:** `uvx ruff check src tests --no-cache` reports 0 in-scope findings (blocking) and 0 pre-existing debt (deferred).
* The full review is in `ARCHITECT_REVIEW.md`, under "Round 2".

### 🏛️ Architecture & System Boundaries

None. The fix round changed only `src/rendering.py` and two test files. `src/tools.py` and `src/template_engine.py` are unchanged since round 1.

### 🧹 Code Quality & Conventions

- **M1: verified, closed.**
  * `src/rendering.py:19` is now `^draft_(\d{8})_(\d{3}|[1-9]\d{3,})$`.
  * A probe shows that `_sequence(f"draft_{stamp}_{n:03d}", stamp) == n` for every `n` from 1 to 20000, and that `_0099`, `_0100` and `_01` still count for nothing.
  * A mutation check in a scratch copy reverted the pattern to `\d{3}`. Exactly the two new tests failed (2 failed, 33 passed), so they are load-bearing.
- **m1: verified, closed.** Pyright reports 0 errors on `src/rendering.py`, `src/tools.py`, `tests/test_unit/test_rendering.py` and `tests/test_unit/test_tools_save.py`.
- **m2: the decision not to take it is accepted.** The item was optional, and the stated reasons hold: different messages, one of them matched by a test, different return shapes and different invariants.

### ❓ Needs a decision

None from the architect. The inherited `\d{3}` file scan in `src/template_engine.py:21` stays deferred, as recorded in round 1.
