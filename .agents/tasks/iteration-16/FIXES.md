
## Architect — round 1

Verdict: **CHANGES REQUESTED**. Full review: `.agents/tasks/iteration-16/ARCHITECT_REVIEW.md`. Ruff: 0 in-scope findings, 0 pre-existing debt. Suite: 1508 passed, 4 deselected.

### 🏛️ Architecture & System Boundaries

- [ ] **M1 (🟡 Major): the runs table reports a metric outside Q8 = D.** `src/benchmark.py:482-486` renders a "Violations" column; `SPECIFICATIONS.md` D-B l.274 ("exactly Approach 1's metrics (Q8 = D)"), §8 Q8 ("D. Nothing extra") and `IMPLEMENTATION_PLAN.md` Iteration 16 l.789 ("it reports only Approach 1's metrics") exclude it. Change:
  - `src/benchmark.py:77`: read the field without capturing it, `r"Run completed: exit_code=(\d+) \((\w+)\) drafts_saved=(\d+) failures=(\d+) violations=\d+ "`, and renumber the groups at l.322-324 (`total_tokens` → group 5, `cost_usd` → 6, `wall_clock_seconds` → 7). Keep the anchor on `violations=` so the line format is still pinned.
  - `src/benchmark.py:136-161`: delete the `violations` attribute and its docstring line (l.145, l.158); delete `violations=None` (l.275) and `violations=int(completed.group(5))` (l.321).
  - `src/benchmark.py:482-486`: drop the `Violations` header cell, one `---:` alignment cell, and `| {_UNSET_CELL if run.violations is None else run.violations} `.
  - `tests/test_unit/test_benchmark.py`: remove `violations=` from the expected `RunRecord`s (l.206, l.329, l.415) and the `| — ` / violations cell from the expected run rows (e.g. l.472-473).
  - Exit code, drafts, failures, tokens and cost stay: each is a field of Approach 1's own "Pipeline run finished" line.

### 🧹 Code Quality & Conventions

- [ ] **M2 (🟡 Major, typing gap): `src/benchmark.py:199`** passes `status.group(1)` (`str`) to `qa_status: QAStatus`; pyright reports `reportArgumentType`. Change to `qa_status=cast(QAStatus, status.group(1))` with `cast` added to the `typing` import at l.17 (the regex admits only the three values), or build the record with `DraftRecord.model_validate({...})`.
- [ ] **m1 (🟢 Minor): the P15 footnote misstates one case.** `src/benchmark.py:89-90` says "Runs whose log lacks either Content Factory line show "not recorded"", but a "starting" line with no "finished" line yields no run (l.239-242; `test_a_start_with_no_finish_is_not_a_run`). Replace the last sentence with: `'A run whose log lacks its "Pipeline run starting" line shows "not recorded"; a "starting" line with no "finished" line, like a log with neither, contributes no run.'` Update the pinned text in `tests/test_unit/test_benchmark.py:476-487` to match.

Optional (not required): o1 pin `RESEARCH_ANALYST.approach_name == DraftMetadata.model_fields["approach_name"].default` in a test; o2 also assert `"agent-orchestration/.env" in skip.kwargs["reason"]` in `tests/test_unit/test_live_suite.py:53-54`; o3 make the status line at `src/benchmark.py:546-549` ASCII-safe for a non-ASCII `--out` path.

### For the orchestrator (plan text; not the implementer's scope, not blocking the fix round)

- [ ] `IMPLEMENTATION_PLAN.md` Iteration 16 l.785: "The corpus ends on 2024-07-24, so the default 3-month window finds nothing; assert exit 1 (`NO_UPDATES`)" is superseded by P14; restate it as P14's assertions (scope `date_to`/`date_from`/`sources`, exit 0 or 1).
- [ ] `IMPLEMENTATION_PLAN.md` Iteration 16 l.787-788: the three-option CLI and "each run's 'Run completed' log line" are superseded by P15; add `[--a1-logs DIR] [--a2-logs DIR]` and "Content Factory's run wall-clock from its start and finish log lines (P15)".
- [ ] `IMPLEMENTATION_PLAN.md` §6 Traceability l.824-828: add rows for P11 (11), P12 (11, 14), P13 (14), P14 (16) and P15 (16).

## QA — round 1

Verdict: **CHANGES REQUIRED**. The full review is in `.agents/tasks/iteration-16/QA_REVIEW.md`.

Real numbers:
* `uv run pytest -q`: **1508 passed, 4 deselected**.
* `uvx ruff check src tests`: `All checks passed!`.
* `uv run pytest -m live --collect-only -q`: 4 tests listed.

There are no blockers, and nothing needs a decision.

### 🧪 Quality Assurance & Test Verification

- [ ] **Q-M1 (🟡 Major): the Approach 1 logger filter is untested.**
  - **Mutant.** In `src/benchmark.py:255`, change
    ```
    if header is None or header.group(3) != _A1_LOGGER:
    ```
    to
    ```
    if header is None:
    ```
    The 5 iteration test files still pass:
    ```
    71 passed in 2.75s
    ```
  - **Why it survives.** `tests/test_unit/test_benchmark.py:254-255` quotes "Pipeline run finished:" behind `echoed: `, so `_A1_FINISHED.match` already rejects the line before the logger filter matters. The report's row 5 mutation claim does not hold for this condition.
  - **Fix.** In `test_only_the_orchestrators_own_header_lines_count`, replace the `src.agents` line (l.254-255) with one whose message **starts** with the prefix:
    ```python
    "2026-09-24 13:10:00,000 WARNING  src.agents: Pipeline run finished: exit code 9 (X), 9 draft(s) written, "
    "9 failure(s), 9 total tokens, $9.0000 estimated cost",
    ```
    Then add, between `A1_START_0924` and `A1_FINISH_0924`, a foreign start line:
    ```python
    "2026-09-24 13:12:00,000 INFO     src.agents: Pipeline run starting: prompt 'x'",
    ```
    The existing assertion `(run.total_tokens, run.wall_clock_seconds) == (223970, 511.14)` with `(run,) = …` then fails under the mutant: two runs, or a 252.231 s wall-clock. Confirm by applying the mutant once.

- [ ] **Q-m1 (🟢 Minor): the anchor on `src.app` lines is not shown.**
  - **Mutant.** In `src/benchmark.py:310`, `_A2_COMPLETED.match(header.group(5))` → `_A2_COMPLETED.search(line)` survives.
  - **Fix.** In `test_only_src_apps_own_run_completed_line_is_a_run` (`tests/test_unit/test_benchmark.py:371-380`), add:
    ```python
    f"2026-10-05 09:00:00,004 INFO     [run_id=a doc_id=- attempt=-] src.app: Run started: prompt='{quoted}'",
    ```
    "Run started" logs the raw prompt, so this case can really happen.

- [ ] **Q-m2 (🟢 Minor): "mean" is not distinguishable from "median".**
  - **Mutant.** In `src/benchmark.py:437`, `statistics.fmean` → `statistics.median` survives: every multi-value spread in the tests has two values.
  - **Fix.** Add a test rendering three `DraftRecord`s with `cost_usd` 0.10, 0.20 and 0.60, and assert the summary cell:
    ```
    $0.1000 – $0.6000 (mean $0.3000)
    ```

- [ ] **Q-m3 (🟢 Minor): the skip-rule test does not pin which `.env` is checked.**
  - **Problem.** `tests/test_unit/test_live_suite.py:53` compares the condition with the same expression evaluated now, so a working-directory-relative `Path(".env")` in the live module would pass when pytest starts from the repository.
  - **Fix.** Add:
    ```python
    assert module.DOTENV == REPO_ROOT / ".env"
    assert "agent-orchestration/.env" in skip.kwargs["reason"]
    ```
    The second assertion is the architect's optional o2; one change covers both.

Optional (not required):
- **o-1.** Add a negative control in `tests/test_unit/test_live_checks.py`: an `ERROR` draft rendered by the real `render_draft` (banner in its Review Notes) yields `[]`.
- **o-2.** In `tests/test_live/test_live_e2e.py:85-98`, cache a failed run's exception in `_RUNS` and re-raise it on reuse, so a Prompt A crash is not paid for twice by the role-bleed test.

## Implementation — fix round 1

Every required item is applied. Each one was shown Red first, by a failing test or by a mutant the new test kills. Final numbers: `uv run pytest -q` gave 1516 passed, 4 deselected. `uvx ruff check src tests` passed with no findings. `uvx pyright src/benchmark.py` reported 0 errors.

- **M1.** Red: 5 failures, from the RunRecords that lacked the required `violations` field, the run rows that still had the cell, and the new `test_the_runs_table_reports_only_approach_1s_run_metrics`. Fix: `RunRecord.violations` and the table column are gone. `_A2_COMPLETED` still matches `violations=\d+` but no longer captures it, and the groups are renumbered 5 to 7.
- **M2.** Red: pyright reported `reportArgumentType` at l.198. Fix: `cast(QAStatus, status.group(1))`. Pyright now reports 0 errors.
- **m1.** Red: the pinned footnote test failed. Fix: the footnote now uses the architect's exact sentence.
- **Q-M1.** Applied QA's two-line test change. With the mutant `if header is None:`, the test fails with `ValueError: too many values to unpack` (two runs). The mutant was reverted.
- **Q-m1.** Added a `src.app` "Run started" line, shaped like the real `run_id=… prompt=… today=…` line, that quotes the "Run completed" text. With the mutant `.search(line)`, the test fails (one run where none was expected). Reverted.
- **Q-m2.** Added `test_the_spread_states_the_mean_not_the_median`, with costs 0.10, 0.20 and 0.60. With the `median` mutant, the cell reads "mean $0.2000" and the test fails. Reverted.
- **Q-m3 / o2.** Added `module.DOTENV == REPO_ROOT / ".env"` and `"agent-orchestration/.env" in reason`. With the mutant `DOTENV = Path(".env")`, the test fails. Reverted.
- **Optional o1.** Pinned `RESEARCH_ANALYST.approach_name` to the default of `DraftMetadata.approach_name`.
- **Optional o3.** Red: a new test writes to an `--out` path containing "é" and asserts that the status line is ASCII. The path is now printed with `backslashreplace`.
- **Optional QA o-1.** Added a negative control: an `ERROR` draft rendered by the real `render_draft` carries the banner and yields `[]`.
- **Optional QA o-2.** The live module now caches a failed run in `_FAILED_RUNS`. Later callers raise `AssertionError("…already failed…")` without running it again. This is proven offline by patching the live module's `main` to raise; it ran once. Red: before the fix, `main` ran twice.

## Architect — round 2

Verdict: **APPROVED**. Full review: `.agents/tasks/iteration-16/ARCHITECT_REVIEW.md` (round 2 section). Suite: 1516 passed, 4 deselected. Ruff: 0 in-scope findings, 0 pre-existing debt. Pyright on `src/benchmark.py`, `tests/test_live` and the two support modules: 0 errors. Live collect-only: 4 tests.

### 🏛️ Architecture & System Boundaries

- [x] M1: resolved. `RunRecord.violations` and the column are removed, and `violations=\d+` is matched but not captured. The groups are renumbered and pinned by the real-logger contract test.
- The restructured live module keeps the real production path: `run(run_prompt, config)` with no overrides, behind the unchanged `src.cli.main`. `_FAILED_RUNS` caches only `Exception`, so skips and interrupts pass through. No new item.

### 🧹 Code Quality & Conventions

- [x] M2: resolved (`cast(QAStatus, …)`; pyright reports 0 errors).
- [x] m1: resolved (the footnote is verbatim and pinned).
- Optional, not required: **o4.** `tests/test_unit/test_benchmark.py:599-600` expects the unescaped `f"Wrote {out}: …"`. On a host whose temp path is non-ASCII, these lines would fail although `main` is correct. Build the expected text with `str(out).encode("ascii", "backslashreplace").decode("ascii")`.

### ❓ Needs a decision

None.

### For the orchestrator (carried over from round 1; plan text, non-blocking)

- [ ] The three `IMPLEMENTATION_PLAN.md` items are still open: Iteration 16 l.785 (P14), l.788 (P15) and the §6 Traceability rows for P11–P15.

## QA — round 2

Verdict: **APPROVED**. The full review is in `.agents/tasks/iteration-16/QA_REVIEW.md`, under "QA review, round 2".

Real numbers:
* `uv run pytest -q`: **1516 passed, 4 deselected**.
* `uvx ruff check src tests`: `All checks passed!`.
* `uv run pytest -m live --collect-only -q`: 4 listed.
* `uvx pyright src/benchmark.py`: 0 errors.

### 🧪 Quality Assurance & Test Verification

- [x] **Q-M1.** Verified: the `if header is None:` mutant is now killed by `test_only_the_orchestrators_own_header_lines_count`.
- [x] **Q-m1.** Verified: both the `.search(line)` and the `.search(header.group(5))` mutants are killed.
- [x] **Q-m2.** Verified: the `statistics.median` mutant is killed by `test_the_spread_states_the_mean_not_the_median`.
- [x] **Q-m3.** Verified: the `DOTENV = Path(".env")` mutant is killed.
- [x] **o-1 and o-2.** Verified: the banner false-positive mutant and the no-cache mutant are both killed.

No new findings. No items are open.

## ❓ Needs a decision

None from QA.
