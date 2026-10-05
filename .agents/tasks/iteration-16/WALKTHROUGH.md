# Iteration 16 — Live end-to-end tests and benchmark report (built, not run): walkthrough

**Date:** 2026-10-05 · **Branch:** `approach-2/implementation` · **Plan section:** `IMPLEMENTATION_PLAN.md` §5, Iteration 16

> **The live run is pending the user's trigger.** The live tests, the CLI benchmark run and the benchmark report are built, but none was run in this iteration. No live test and no live CLI command were executed. The only `-m live` command used was `uv run pytest -m live --collect-only -q`, which only collects tests and calls no model. Section 8 lists the user's commands.

## 1. Overview

This iteration builds everything the user needs to run the live benchmark.

* **`tests/test_live/test_live_e2e.py`** holds four tests, all marked `live`. They are deselected by default and skipped with a reason when `agent-orchestration/.env` is absent. Each one drives the real `src.cli.main` and the real `src.app.run`, with the benchmark constants untouched: the default `build_model`, the `.env` efforts and rates, the system clock, and no `--max-drafts`.
  * **Prompt A** is Approach 1's benchmark prompt.
  * **Prompt B** checks the recency rule (P14).
  * **The role-bleed audit (P1)** runs over both prompts' runs.
* **The isolation opt-out.** `tests/conftest.py`'s autouse isolation now steps aside for tests carrying the `live` marker, and only for those. The live module pins `.env` to `agent-orchestration/.env` for all three settings classes, so it works from any working directory.
* **`src/benchmark.py`** builds the comparison report: `python -m src.benchmark --a1 DIR --a2 DIR --out FILE [--a1-logs DIR] [--a2-logs DIR]`.
  * It parses each draft's bullets, Content Factory's run log timestamps (P15) and the Research Analyst's "Run completed" lines (P12).
  * It reports only Approach 1's metrics (Q8 = D), under the labels *Content Factory* and *Research Analyst* (Q9 = C).
  * Its unit tests run offline, against fixture drafts in `tests/fixtures/`.
* **`README.md`** covers setup, `.env`, the cost basis, the CLI, the exit codes, the tests and "Running the live benchmark".

Two questions came up at pre-flight, and the user answered both:
* **Q14** became **P14**: Prompt B checks the recency rule, not an empty window.
* **Q15** became **P15**: Content Factory's run wall-clock comes from its log timestamps.

## 2. Files changed

| File | Status | Responsibility |
| :--- | :--- | :--- |
| `src/benchmark.py` | New, 570 lines | Parsing records, the two log parsers, `render_report`, and the `main` CLI |
| `tests/test_live/__init__.py`, `tests/test_live/test_live_e2e.py` | New, 4 live tests | Prompt A, Prompt B (P14), and the role-bleed audit for each prompt. Each prompt runs once per session through a cache, and a failed run is not run again |
| `tests/support/role_bleed.py` | New | `NON_GOAL_TOOLS`: Approach 1's table without the ScopeParser row. Each row is tied to a clause in `src/agents.py`. Also the detector, which intersects with the substrate tools first so structured-output entries are not counted, and the Supervisor substrate check |
| `tests/support/live_checks.py` | New | `months_before`, standard library only, clamping the day. `saved_draft_problems` checks: at least one draft; files match the saved drafts; no template token; at most 3 attempts, matching the rendered count; the Approach 2 bullet; the banner on every `ERROR` draft |
| `tests/test_unit/test_benchmark.py` | New, 38 tests | The benchmark, offline. Logs are built as strings under `tmp_path`; there are no committed log fixtures |
| `tests/test_unit/test_role_bleed.py` | New, 13 tests | The detector, with a positive control for every listed non-goal, and the prompt clauses pinned |
| `tests/test_unit/test_live_checks.py` | New, 14 tests | The live checks, offline, with a negative control: a real `ERROR` draft carrying its banner passes |
| `tests/test_unit/test_live_suite.py` | New, 6 tests | Every `tests/test_live/` module has a module-level `live` mark, has tests, and has the `.env` skip rule pinned to `REPO_ROOT/.env`. The failed-run cache works offline. The README states the user's live commands |
| `tests/fixtures/draft_20260918_001.md`, `draft_20260924_002.md` | New | Byte-for-byte copies of two Approach 1 drafts: the oldest layout (`ERROR`, banner, attempts 2) and the current layout (`PASS`, attempts 1) |
| `tests/fixtures/draft_20261005_001.md` | New | An Approach 2 draft rendered once by the real `render_draft`: `WARNING`, attempts 2, Supervisor and Scout rows with `None` in the Attempt column, and an Effort column |
| `tests/conftest.py` | Edited | The `live` opt-out, `pytest_plugins = ["pytester"]`, and docstrings |
| `tests/test_unit/test_isolation.py` | Edited, +1 test | A `pytester` inner session shows that only a `live`-marked test keeps the environment |
| `tests/test_unit/test_module_structure.py` | Edited | `EXPECTED_MODULES` gains `src.benchmark` |
| `tests/test_unit/test_docs_consistency.py` | Edited | `IMPLEMENTATION_DECISIONS` gains P14 and P15; two docstrings now say "P1 to P15" |
| `.agents/docs/SPECIFICATIONS.md` | Edited by the implementer | The status line and the §8 index say P1–P15. The §8.3 heading and the P14 and P15 rows are added. The next decision is named P16. D-B notes P15 |
| `AGENTS.md`, `CLAUDE.md`, both `.agents/skills/*/SKILL.md`, the three `.claude/agents/*.md` | Edited, range text only | "P1 to P13" becomes P15 (Q13 = A, standing approval) |
| `README.md` | Rewritten | Was a one-line stub |
| `.agents/docs/IMPLEMENTATION_PLAN.md` | Edited by the orchestrator | §2 gains P14 and P15; the §3 tracker |
| `.agents/tasks/QUESTIONS.md` | Edited by the orchestrator | Q14 and Q15, raised and answered |
| `.agents/tasks/iteration-16/` | New | `ARCHITECT_REVIEW.md`, `QA_REVIEW.md`, `FIXES.md` and this walkthrough |

**Inside `src/benchmark.py`:**
* **Drafts.** `parse_draft` reads the five bullets every layout shares: Approach, Status, Revision Attempts, Time Taken, and Estimated Cost with tokens. It does not read the tool table (Q8 = D). It handles CRLF and LF, and Approach 1's three layouts as well as Approach 2's. `load_drafts` reads only `draft_*.md`, in name order. It raises `BenchmarkError` for a missing folder, or for a draft that names the other approach.
* **Content Factory runs (P15).** Only `src.orchestrator` header lines are read. A run is one "Pipeline run finished" line. Its wall-clock is that line's timestamp minus the latest unpaired "Pipeline run starting" in the same file, or `None` ("not recorded"). A "starting" with no "finished" is not a run.
* **Research Analyst runs (P12).** Only `src.app` "Run completed" lines are read, with a regex anchored at the message start that stops at `summary=`. Text inside the `%r` summary is therefore never read as a field. `violations=` is required as an anchor but not reported.
* **`render_report`.** It produces three things:
  * A summary table, `Metric | Content Factory | Research Analyst`, with "min – max (mean …)" per-draft cost, time and tokens, QA status counts, attempts, and run wall-clock. "n/a" appears when there is nothing.
  * The run wall-clock row, which counts only runs that exited 0 with a recorded wall-clock, plus the P15 footnote "¹".
  * A drafts table and an eight-column runs table for each approach. The runs table lists every run with its exit code.
* **`main`.** Each logs folder defaults to `<drafts>/../logs`. A missing or mismatched drafts folder is a usage error (exit 2, through `parser.error`). A missing logs folder means zero runs. It prints one ASCII status line, escaping a non-ASCII `--out` path.

## 3. TDD record

| # | Behaviour | Red | Green |
| :---: | :--- | :--- | :--- |
| 1 | P14 and P15 in the decision records | The §8.3 order test failed (§8.3 stopped at P13), and the §8.3 statement test failed with `['P14','P15'] == []` | The `SPECIFICATIONS.md` rows and the range text |
| 2 | `src.benchmark` module | `ModuleNotFoundError` | The module |
| 3 | `parse_draft` | `ImportError`; then the three layouts, CRLF and LF, and a missing bullet named in the error | Five anchored bullet regexes |
| 4 | `load_drafts`, the labels | `ImportError` | `draft_*.md` only; empty folder `[]`; a missing folder or the other approach raises |
| 5 | Content Factory logs | `ImportError` | The 0924 run gives 511.14 s; finished with no start gives `None`; a dangling start gives no run; two runs pair correctly |
| 6 | Research Analyst logs | `ImportError`, including a contract test that writes a real "Run completed" line through `configure_logging` and `src.app._log_run_completed` and parses it back | The anchored regex |
| 7 | `render_report` | `ImportError` | Summary, footnote, tables, "n/a", "not recorded" |
| 8 | `main` | `ImportError` | Log defaults and overrides; exit 2 for a missing or mismatched folder; `--help` lists five options |
| 9 | Isolation opt-out | `pytester`: `{'failed': 1} != {'failed': 0}`; the live inner test still saw the variable stripped | `_isolate_environment(request, monkeypatch)` returns early for `live` |
| 10 | Role-bleed detector | `ModuleNotFoundError` | The table and detector; removing the substrate intersection failed 2 tests |
| 11 | Live checks | `ModuleNotFoundError` | `months_before`, `saved_draft_problems` |
| 12 | Live module and its offline contract (AC1) | 4 failures with no `tests/test_live/`; two loop tests first passed vacuously, so they were made to require a module, and then failed | The live module |
| 13 | README | `'## Running the live benchmark'` was absent | The README |
| 14 | Fix round 1, M1 (Q8 = D) | 5 failures pinning the eight-column runs table and the `RunRecord` field set | The "Violations" column and field were removed |
| 15 | Fix round 1, M2 | pyright `reportArgumentType` | `cast(QAStatus, …)`; pyright now reports 0 errors |
| 16 | Fix round 1, m1 | The pinned footnote test failed | Accurate footnote: a "starting" with no "finished" contributes no run |
| 17 | Fix round 1, Q-M1, Q-m1 to m3 | Each surviving mutant is now killed: the Approach 1 logger filter, `.search` for `.match`, `median` for `fmean`, and `Path(".env")` | Test fixes |
| 18 | Fix round 1, optional items | The non-ASCII `--out` failed `isascii()`; the failed-run cache let `main` run twice | ASCII status line; `_FAILED_RUNS`; the `approach_name` pin; the `ERROR`-banner negative control |

## 4. Test results

The orchestrator ran the suite fresh, after this walkthrough was written:

* `uv run pytest -q`: **1517 passed, 4 deselected**, 0 failed. The 4 deselected tests are the live tests (AC1).
* Tests added: **+80** over Iteration 15's 1437.
  * 38 in `test_benchmark.py`, 14 in `test_live_checks.py`, 6 in `test_live_suite.py` and 13 in `test_role_bleed.py`.
  * 1 in `test_isolation.py`.
  * 1 `test_annotations.py` case for `src/benchmark.py`.
  * 7 forbidden-term cases in `test_docs_consistency.py`: 3 for the new fixture drafts and 4 for the new `.md` files in `iteration-16/`.
* `uvx ruff check src tests`: **All checks passed!** `uvx pyright src/benchmark.py`: 0 errors.
* **AC2:** `uv run pytest -m live --collect-only -q` printed:
  ```text
  tests/test_live/test_live_e2e.py::test_prompt_a_runs_to_sound_drafts
  tests/test_live/test_live_e2e.py::test_prompt_b_applies_the_recency_rule
  tests/test_live/test_live_e2e.py::test_no_sub_agent_calls_a_tool_its_prompt_declares_a_non_goal[prompt-a]
  tests/test_live/test_live_e2e.py::test_no_sub_agent_calls_a_tool_its_prompt_declares_a_non_goal[prompt-b]
  ```
* **The benchmark, read-only, against Approach 1.** The implementer ran `src.benchmark` on `../code-orchestration/drafts`, with output to its scratchpad and not the repository. It parsed 10 drafts: $0.1792–$1.0409, 98.73–744.90 s and 63,317–294,621 tokens, which matches SPECIFICATIONS.md §2.3. It found 2 runs, 511.14 s and 1,377.85 s; the 0918, 0921 and 0922 logs contribute no run. No `.agents/docs/BENCHMARK.md` was generated.
* **No live call was made.** QA also ran the default suite from a scratch working directory holding a populated `.env`. It passed, and three mutants of the opt-out were killed, so a `.env` cannot leak into non-live tests.

## 5. Acceptance criteria

| Criterion | Status | Evidence |
| :--- | :---: | :--- |
| Red: every live test is marked `live`, opts out of isolation through the marker, and skips with a reason when `.env` is absent | ✅ | `pytestmark = [live, skipif(...), usefixtures("restore_logging")]`; the conftest opt-out; `test_live_suite.py`; the `pytester` test in `test_isolation.py` |
| Red: Prompt A assertions | ✅ | `test_prompt_a_runs_to_sound_drafts` asserts exit 0 and no fatal stop, then applies `saved_draft_problems`. That function's checks are proven offline in `test_live_checks.py` |
| Red: Prompt B, under **P14** | ✅ | `test_prompt_b_applies_the_recency_rule`, described in §1 |
| Red: role-bleed audit (P1) | ✅ | `test_no_sub_agent_calls_a_tool_its_prompt_declares_a_non_goal[prompt-a, prompt-b]`; the detector is proven offline with positive controls |
| Red: `src/benchmark.py` CLI, parsing, Q8 = D metrics, Q9 = C labels; unit tests against fixtures | ✅ | `test_benchmark.py`, 38 tests; the CLI gains `--a1-logs` and `--a2-logs` under P15 |
| Red: README setup, `.env`, CLI, "Running the live benchmark" with the user's commands | ✅ | `README.md`; `test_live_suite.py` pins the commands |
| **AC1:** the default run deselects every live test | ✅ | "1517 passed, 4 deselected"; no live test executed |
| **AC2:** `uv run pytest -m live --collect-only -q` lists the live tests | ✅ | §4; the skip rule is evaluated at setup, so collection works without `.env` |
| **AC3:** the benchmark unit tests pass offline | ✅ | `test_benchmark.py`; QA killed every mutant it ran on the fixed code |
| **AC4:** plan §3 shows every iteration `✅ Complete`, and the walkthrough says the live run is pending the user's trigger | ✅ | §3 is updated with this commit; the note at the top of this file |
| DoD-1 to DoD-6 | ✅ | §4 above; every function in `src/benchmark.py` is exercised; the docs test passes; this file |

## 6. Decisions and deviations

**Binding decisions applied:**
* **P14 (Q14 = A).** Prompt B asserts the scope and accepts exit 0 or 1. The corpus on disk holds INAIL updates dated 2026-07-15 and 2026-08-20 inside today's window, and the Scout's input has no topic.
* **P15 (Q15 = A).** Content Factory's run wall-clock is read from its log timestamps, with the footnote. Logs are read from `<drafts>/../logs` unless `--a1-logs` or `--a2-logs` is given.
* **Q13 = A.** The range text was updated in the harness files.

**Decisions (§1.5):**
* The role-bleed table, the detector and the live checks live in `tests/support/`, so the checks a paid run relies on are proven offline. The live module only calls them.
* Each prompt runs once per session through the `_RUNS` cache. The role-bleed test reuses those runs, so it costs nothing extra. A failed run is cached in `_FAILED_RUNS` and is not paid for twice.
* "Prompt A's draft checks" includes "at least one draft", so a Prompt B exit 0 with nothing saved fails.
* The template-token check uses the template's declared tokens (`_template_tokens`), not a raw brace regex, because braces the Writer writes are content.
* Benchmark aggregation:
  * per-draft values are shown as "min – max (mean …)";
  * the wall-clock summary counts only exit-0 runs with a recorded wall-clock, and every run appears in the runs table;
  * a "starting" with no "finished" is not a run;
  * a drafts folder holding the other approach's draft is a usage error.
* The report's record types are Pydantic models with `extra="ignore"`. `src/benchmark.py` has no logger.

**Deviations from the plan text:**
* The plan's Iteration 16 line "The corpus ends on 2024-07-24 … assert exit 1" is superseded by **P14**.
* The plan's three-option benchmark command is extended by **P15** (`--a1-logs`, `--a2-logs`).

Both are left as written in §5, because this workflow edits only plan §2 and §3. Separately, the plan's §6 traceability table has no rows for P10–P15; nothing tests it, and it is left for the user to update if wanted.
* `tests/test_unit/test_live_suite.py` also pins the README's live commands. That test is not in the plan's Red list.

**Known limits:**
* **Not applied (architect o4, optional):** two lines of a CLI test compare the printed status line with the unescaped path. They would fail on a machine whose temporary path contains non-ASCII characters, although `main` is correct.
* **Q12 = A still stands:** a session that fails as it closes with a plain `RuntimeError` is not rendered (Iteration 14).

## 7. Review

The pre-flight was held once (Q14, Q15), and review used two rounds.

**Round 1.**
* **Architect: CHANGES REQUESTED.**
  * **M1:** a "Violations" column in the runs table broke Q8 = D. **Resolved.**
  * **M2:** a `str` was passed to the `QAStatus` Literal. **Resolved.**
  * **m1:** the footnote said a "starting" line without a "finished" line shows "not recorded"; in fact it contributes no run. **Resolved.**
  * Optional o1 (the `approach_name` pin), o2 (the `.env` path in the skip test) and o3 (an ASCII status line). **Resolved.**
* **QA: FAIL.**
  * **Q-M1:** the Approach 1 logger filter was never exercised. **Resolved.**
  * **Q-m1:** "Run completed" anchoring. **Resolved.**
  * **Q-m2:** mean versus median. **Resolved.**
  * **Q-m3:** the skip rule's `.env` path. **Resolved.**
  * Two optional items: an `ERROR`-banner negative control and failed-run caching. **Resolved.**

**Round 2.**
* **Architect: APPROVED.** One optional item, o4, was left unapplied (see §6).
* **QA: PASS**, with no findings. All 13 of its re-run mutants were killed.

## 8. The user's live commands

Run these from `agent-orchestration/`, after `cp .env.example .env` and filling in the credentials. Copy Approach 1's `HSE_COST_*` values for a fair comparison, as the README explains.

```bash
uv run pytest -m live
uv run python -m src.cli "Analyze INAIL updates on heat stress published since 2024"
uv run python -m src.benchmark --a1 ../code-orchestration/drafts --a2 drafts --out .agents/docs/BENCHMARK.md
```

Approach 1's run of the benchmark prompt took about 8.5 minutes and cost $0.78.
