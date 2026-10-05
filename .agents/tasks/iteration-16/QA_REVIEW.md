# Iteration 16 — QA review, round 1

**Iteration:** 16, Live end-to-end tests and benchmark report (built, not run)
**Reviewer:** qa subagent, criteria from `.agents/skills/code-reviewer/SKILL.md`
**Date:** 2026-10-05

## 1. Summary and verdict

**Verdict: `CHANGES REQUIRED`** (no blocker; one Major test-quality gap, three Minor).

The implementer's claims hold where I could check them:
* The suite numbers match exactly.
* The fixtures are what the report says they are.
* The live module is collected but never run by default.
* The isolation opt-out cannot leak a `.env` into a test that is not live.

The live checks, the role-bleed detector and the benchmark are well tested: 30 of 33 mutants were killed. The three survivors show one real coverage gap, which is Major. The Approach 1 log parser's logger filter (`src/benchmark.py:255`) is not exercised: its test claims to cover "another logger's line quoting 'Pipeline run finished:'", but the quoted text in that test never reaches the filter.

I verified everything below myself. No live test and no live CLI command was run.

### Real numbers

| Command | Result |
| :--- | :--- |
| `uv run pytest -q` | **1508 passed, 4 deselected** in 87.09 s; no warnings summary. The implementer reported the same (baseline 1437, +71) |
| `uvx ruff check src tests --no-cache` and `uvx ruff check src tests` | `All checks passed!` (both) |
| `uv run pytest -m live --collect-only -q` | 4 tests listed (`test_prompt_a_runs_to_sound_drafts`, `test_prompt_b_applies_the_recency_rule`, `test_no_sub_agent_calls_a_tool_its_prompt_declares_a_non_goal[prompt-a]` and `[prompt-b]`); `4/1512 tests collected (1508 deselected)` |
| `uv run pytest --collect-only tests/test_unit/test_benchmark.py` | 35 tests, as claimed |

## 2. Gate matrix

| Gate | Topic | Status | Notes |
| :--- | :--- | :---: | :--- |
| 1 | Strict TDD | ❌ | The TDD log gives an expected Red for each of the 13 behaviours. The tests are meaningful: 30 of 33 mutants were killed. **Q-M1:** the Approach 1 logger filter is untested, and the report's mutation claim for row 5 does not match what I observe. Q-m1 and Q-m2 are smaller gaps. |
| 2 | Zero-token testing | ✅ | Every test in `tests/test_live/` carries a module-level `live` mark, enforced by `test_live_suite.py`; removing the mark kills that test. The default run deselects all 4. The opt-out applies to the `live` marker only: three conftest mutants (no opt-out, opt-out for all, opt-out on any marker) were killed by the pytester test. The full default suite also passes from a foreign working directory that held a populated `.env` (unroutable endpoints, cost 99, efforts `low`), with `HSE_MODEL_STRONG_API_KEY` and `HSE_COST_STRONG_INPUT_USD_PER_MTOK` set in the OS environment: 1508 passed, 4 deselected. The directory was deleted afterwards. |
| 3 | Pydantic v2 contracts | ✅ | `DraftRecord`, `RunRecord`, `ApproachResults` and `Approach` (frozen) use `ConfigDict(extra="ignore")`, and no `dict[str, Any]` crosses a boundary. The architect's M2 already covers the `str` → `QAStatus` typing gap at `src/benchmark.py:199`, so I do not repeat it. No `src/` model changed. |
| 4 | Guardrails and attempt cap | n/a in this iteration | The live checks assert `attempts_used <= MAX_ATTEMPTS_PER_DOC` (3) and that the rendered count equals the attempts used. Off-by-one and disabled-check mutants were killed. |
| 5 | Strands integration and telemetry | n/a in this iteration | The role-bleed audit reads `StageTelemetry.telemetry.tool_invocations` and intersects it with `SUBSTRATE_TOOL_NAMES` before judging, so `ScoutReport` and `QAReport` are excluded. Mutant killed. `NON_GOAL_TOOLS` matches Approach 1's table (`../code-orchestration/tests/test_integration/test_e2e.py`) minus the ScopeParser row, and each row is tied to a clause in `src/agents.py`. |
| 6 | No article text for the Supervisor | n/a in this iteration | No tool or Supervisor code changed. |
| 7 | Drafts and logging | ✅ | `saved_draft_problems` checks the template's own tokens through `_template_tokens`, the `Approach 2 (Research Analyst)` bullet and the banner on `ERROR` drafts. Every disabled check was killed. The Research Analyst parser is pinned to the real formatter: `test_the_run_completed_line_src_app_writes_parses_back_field_for_field` writes through `configure_logging` and `src.app._log_run_completed`. |
| 8 | Python and subprocess safety | ✅ | `pathlib.Path` throughout, UTF-8 reads and writes, and an ASCII status line (tested). No `python.exe` or `uv.exe` process postdates the test runs; the only ones created today were started at 14:01 by the harness's MCP servers. No `.env` and no `.agents/docs/BENCHMARK.md` exist in the repository. |

## 3. Acceptance criteria and Definition of Done

| # | Criterion | Status | Evidence |
| :--- | :--- | :---: | :--- |
| AC1 | The default run deselects every live test | ✅ | `1508 passed, 4 deselected`. `test_every_live_module_marks_all_its_tests_live` fails if the mark is removed (mutant killed). |
| AC2 | `uv run pytest -m live --collect-only -q` lists them | ✅ | 4 listed, verbatim as in the report. The skip condition is evaluated at setup, so collection works without `.env`. |
| AC3 | The benchmark unit tests pass offline and can genuinely fail | ✅ | 35 tests, all under `tmp_path`. 17 of 20 `src/benchmark.py` mutants were killed. The survivors are covered by Q-M1, Q-m1 and Q-m2. |
| AC4 | Plan §3 shows every iteration complete; walkthrough says the live run is pending the user's trigger | n/a (Stage 4) | This is the orchestrator's step. Row 16 currently reads `🔄 In progress`. |
| — | Without `.env`, the live tests skip rather than fail | ✅ | Static proof, without running a live test. `pytestmark` is `['live', 'skipif', 'usefixtures']`, and the skip condition evaluates to `(True,)` because `REPO_ROOT/.env` is absent. A `skipif` is applied before any fixture runs, so `restore_logging`, `_read_the_repository_dotenv` and `cli.main` are never reached. A reason-text mutant was killed. |
| — | The isolation opt-out cannot leak `.env` into tests that are not live | ✅ | Gate 2 above: the foreign-directory run with a populated `.env`, plus three conftest mutants killed. |
| — | Fixtures are byte copies, or rendered by the real code | ✅ | `cmp` shows `draft_20260918_001.md` and `draft_20260924_002.md` identical to `../code-orchestration/drafts/` (both CRLF). I rebuilt `draft_20261005_001.md` with the real `render_draft` from its visible content and metadata, and the output is **byte-identical**. Its rows add up to 106,300 tokens (91,300 in + 15,000 out). |
| DoD-1 | Full default suite passes | ✅ | 1508 passed, 0 failed, 0 errors |
| DoD-2 | Lint is clean | ✅ | `All checks passed!` |
| DoD-3 | No live model call | ✅ | The live module was never executed. Importing it builds nothing, which `test_live_suite.py` checks by importing it under isolation. |
| DoD-4 | Every new `src/` function is exercised | ❌ | Every function is called, but one branch condition, `header.group(3) != _A1_LOGGER` at `src/benchmark.py:255`, is never decisive in any test (Q-M1). |
| DoD-5 | Docs match code | ✅ | `test_docs_consistency.py` passes, with P14 and P15 in both records. The range-text edits are one line each. |
| DoD-6 | Walkthrough written | n/a (Stage 4) | This is the orchestrator's step. |

**Acceptance criteria: 3 of 3 checkable criteria pass (AC1 to AC3). AC4 is the orchestrator's.** Definition of Done: 4 of 5 checkable rows pass. DoD-4 fails on Q-M1, and DoD-6 belongs to Stage 4.

### Other verifications

* **README claims.** All checked against the sources:
  * Approach 1's cost basis is gpt-5.4 $2.50/$0.250/$15.00 (its draft "Cost Basis" lines), and this project's defaults are $1.25/$0.125/$10.00 (`src/costs.py:39-41`).
  * Approach 1's `HSE_*` names are a subset of this project's.
  * The effort defaults are Writer `high` (`src/agents.py:74`), QA-Legal `medium` and Supervisor `medium`.
  * Approach 1's run took 511 s, about 8.5 minutes, and cost $0.78.
* **Prompt B corpus claim (P14).** `hse-easy-mock` `list_regulatory_updates(INAIL, 2026-07-05, 2026-10-05)` returns `inail-2026-bando-isi` (2026-07-15) and `inail-2026-ot23` (2026-08-20), as the README and the docstring state.
* **Live module attributes.** The live module never runs offline, so I checked every attribute it touches against `src/schemas.py` and `src/cli.py`. All exist with the right names: `RunState.scope`, `.context.today`, `.supervisor_summary`, `.fatal_error`, `.documents`, `.ledger`; `PipelineScope.date_from`, `.date_to`, `.sources`; `FailureRecord.stage`, `.error_type`; `GuardrailViolation.guardrail`, `.tool_name`; `DraftResult.path`, `.draft_id`; and `cli.main(argv, *, runner, log_dir)` with `Runner = Callable[[str, PipelineConfig], RunState]`.
* **Parser against real logs.** The Approach 1 log format matches `_A1_HEADER` and `_A1_FINISHED` against the real lines in `../code-orchestration/logs/pipeline_20260923.log` and `pipeline_20260924.log`.

## 4. Findings by severity

### 🔴 Blocker
None.

### 🟡 Major

**Q-M1. The Approach 1 logger filter is untested, and its test does not prove what its docstring claims.**

Mutant: `src/benchmark.py:255`, `if header is None or header.group(3) != _A1_LOGGER:` → `if header is None:`. The 5 target files still give `71 passed`.

`test_only_the_orchestrators_own_header_lines_count` (`tests/test_unit/test_benchmark.py:246-262`) feeds this line from another logger:

`2026-09-24 13:10:00,000 WARNING  src.agents: echoed: Pipeline run finished: exit code 9 ...`

Its message starts with `echoed: `, so `_A1_FINISHED.match(message)` already rejects it, and the logger filter is never what excludes it. The same holds for a foreign "Pipeline run starting: " line: one would silently move the pairing start, and no test catches that. The pre-flight brief required "another logger's line quoting 'Pipeline run finished:' ignored".

The report's row 5 claim ("Mutation: removing the 'skip other `src.orchestrator` lines' branch fails the test") does not match what I observe for the logger condition.

### 🟢 Minor

**Q-m1. The Research Analyst line is not shown to be anchored at its message start for `src.app` lines.**

Mutant: `src/benchmark.py:310`, `_A2_COMPLETED.match(header.group(5))` → `_A2_COMPLETED.search(line)`. It survives.

No test feeds a `src.app` header line whose message *contains*, rather than starts with, a full "Run completed: …" text. This could really happen: "Run started" logs the raw prompt.

**Q-m2. "mean" is not distinguishable from "median".**

Mutant: `src/benchmark.py:437`, `statistics.fmean` → `statistics.median`. It survives, because every multi-value spread in the tests has exactly two values, and for two values mean equals median.

**Q-m3. The skip-rule test does not pin which `.env` is checked.**

`tests/test_unit/test_live_suite.py:53` asserts `skip.args == (not (REPO_ROOT / ".env").is_file(),)`. It compares the module's condition with the same expression evaluated now, so a module whose condition used a working-directory-relative `Path(".env")` would pass whenever pytest starts from the repository. This overlaps the architect's optional o2.

### Optional (not required)

* **o-1.** `tests/test_unit/test_live_checks.py` has no negative control for the banner. Nothing shows that an `ERROR` draft rendered by the real `render_draft`, which carries the banner in its Review Notes, yields no problem. A false positive would surface only in a paid run.
* **o-2.** `_live_run` caches only successful runs. If Prompt A's `main` raises, the parametrised role-bleed test runs Prompt A again and pays a second time. One way to stop that: store the exception in `_RUNS` and re-raise it on reuse.

## 5. Remediation

The exact instructions are in `.agents/tasks/iteration-16/FIXES.md` under `## QA — round 1`. In short:

* **Q-M1.** In `tests/test_unit/test_benchmark.py:254-255`, make the foreign line's message *start* with the exact prefix, for example `"2026-09-24 13:10:00,000 WARNING  src.agents: Pipeline run finished: exit code 9 (X), 9 draft(s) written, 9 failure(s), 9 total tokens, $9.0000 estimated cost"`. Also add `"2026-09-24 13:12:00,000 INFO     src.agents: Pipeline run starting: prompt 'x'"` between the real start and finish. The existing assertion `(223970, 511.14)` then kills both logger-filter mutants.
* **Q-m1.** In `test_only_src_apps_own_run_completed_line_is_a_run`, add `f"2026-10-05 09:00:00,004 INFO     [run_id=a doc_id=- attempt=-] src.app: Run started: prompt='{quoted}'"`.
* **Q-m2.** Add a three-value spread, for example three `DraftRecord`s costing 0.10, 0.20 and 0.60, and assert `"$0.1000 – $0.6000 (mean $0.3000)"`.
* **Q-m3.** In `test_the_live_tests_skip_with_a_reason_when_the_dotenv_is_absent`, also assert `module.DOTENV == REPO_ROOT / ".env"` and `"agent-orchestration/.env" in skip.kwargs["reason"]`.

Verdict: **FAIL** (CHANGES REQUIRED). Q-M1 must be fixed; the Minor items are small test additions.

---

# Iteration 16 — QA review, round 2

**Reviewer:** qa subagent, criteria from `.agents/skills/code-reviewer/SKILL.md`
**Date:** 2026-10-05
**Scope:** I re-verified fix round 1: the architect's M1, M2 and m1, my Q-M1 and Q-m1 to Q-m3, and the optional o1, o3, o-1 and o-2. No live test and no live CLI command was run.

## R2.1 Summary and verdict

**Verdict: `APPROVED`.** I found no blocker, no Major and no Minor.

* All 7 required items and 4 optional items landed as reported.
* Each round 1 survivor is now killed on a scratch copy.
* The implementer's numbers match mine exactly.

### Real numbers

| Command | Result |
| :--- | :--- |
| `uv run pytest -q` | **1516 passed, 4 deselected** in 89.44 s, with no warnings summary. That is +8 over round 1's 1508, as claimed |
| `uvx ruff check src tests --no-cache` and `uvx ruff check src tests` | `All checks passed!` (both) |
| `uv run pytest -m live --collect-only -q` | The same 4 live tests are listed, `4/1520 tests collected (1516 deselected)` |
| `uvx pyright src/benchmark.py` | `0 errors, 0 warnings, 0 informations`, as claimed |

## R2.2 Mutation re-run

Each mutant below was applied to a scratch copy of `src/`, `tests/` and the documents, outside the repository. Each run covered `test_benchmark.py`, `test_live_suite.py`, `test_live_checks.py` and `test_role_bleed.py`; their baseline is 71 passed. The scratch copy was deleted afterwards.

| Item | Mutant | Result | Killing test |
| :--- | :--- | :---: | :--- |
| Q-M1 | `src/benchmark.py:255` → `if header is None:` | Killed | `test_only_the_orchestrators_own_header_lines_count` |
| Q-M1 (pairing) | The "starting" branch is disabled | Killed | `test_the_benchmark_prompt_run_spans_its_start_and_finish_lines` |
| Q-m1 | `:309` `.match(header.group(5))` → `.search(line)` | Killed | `test_only_src_apps_own_run_completed_line_is_a_run` |
| Q-m1 (variant) | `.match(header.group(5))` → `.search(header.group(5))` | Killed | same |
| Q-m2 | `:435` `statistics.fmean` → `statistics.median` | Killed | `test_the_spread_states_the_mean_not_the_median` |
| Q-m3 | Live module `DOTENV = Path(".env")` | Killed | `test_the_live_tests_skip_with_a_reason_when_the_dotenv_is_absent` |
| A2 logger filter | `:307` → `if header is None:` | Killed | `test_only_src_apps_own_run_completed_line_is_a_run` |
| M1 | `violations=\d+ ` deleted from `_A2_COMPLETED` | Killed (6 failures) | The real-formatter round trip and the fixtures |
| o3 | `shown_out = str(out)` | Killed | `test_main_prints_an_ascii_status_line_for_a_non_ascii_out_path` |
| o-2 | `_FAILED_RUNS[prompt] = exc` removed | Killed | `test_a_failed_live_run_is_not_paid_for_twice` |
| o-1 | The banner check flags every `ERROR` draft | Killed | `test_an_error_draft_rendered_with_its_banner_has_no_problem` |
| o1 | `RESEARCH_ANALYST.approach_name` altered | Killed | `test_the_approaches_carry_the_project_labels_and_their_drafts_approach_names` |
| m1 | Footnote wording altered | Killed | `test_the_wall_clock_footnote_states_what_each_approach_measures` |

One extra mutant survived, and it is not a finding. Replacing `violations=\d+ ` with `\S+ ` gives a regex that is equivalent on every line `src.app` can write: `_log_run_completed` always emits `violations=%d` in that slot. If the field were dropped, `\S+` would consume `total_tokens=…`, and the next literal would then fail. So the format pin the architect asked for holds wherever it matters.

## R2.3 Fix verification

* **M1.** Implemented as specified.
  * `RunRecord` has no `violations` field (`src/benchmark.py:138-161`).
  * The runs table has 8 columns (`:480`).
  * `_A2_COMPLETED` matches `violations=\d+` without capturing it, and the groups are renumbered 5 to 7 (`:320-322`).
  * `test_the_runs_table_reports_only_approach_1s_run_metrics` pins the header, the absence of "Violations" and the exact field set.
  * Neither the README nor any test mentions a violations column.
* **M2.** `cast(QAStatus, status.group(1))` is at `:199`, and pyright is clean.
* **m1.** The footnote at `:86-93` is the reworded text, pinned by its test.
* **Q-M1.** The foreign `src.agents` lines now start with the exact prefixes (`tests/test_unit/test_benchmark.py:255-259`), and the mutant fails.
* **Q-m1.** The added `src.app` "Run started: run_id=a prompt='…' today=…" line (`:379-380`) has the shape `src/app.py:330` really logs.
* **Q-m2.** Costs of 0.10, 0.20 and 0.60 are asserted as `$0.1000 – $0.6000 (mean $0.3000)` (`:465-482`).
* **Q-m3 / o2.** `module.DOTENV == REPO_ROOT / ".env"` and the reason text are both asserted (`tests/test_unit/test_live_suite.py:54-56`).
* **o-2.** I checked the offline test for side effects.
  * It patches the live module's `main`, `_RUNS` and `_FAILED_RUNS` through `monkeypatch`, so nothing persists.
  * It is a unit test with no `live` mark, and the patched `main` raises before anything is built, so no endpoint can be reached.
  * Pytest's skip and fail outcomes derive from `BaseException`, so `except Exception` does not cache them.

## R2.4 Acceptance criteria and Definition of Done

| # | Criterion | Status | Evidence |
| :--- | :--- | :---: | :--- |
| AC1 | The default run deselects every live test | ✅ | `1516 passed, 4 deselected` |
| AC2 | `-m live --collect-only` lists them | ✅ | All 4 listed |
| AC3 | The benchmark unit tests pass offline and can genuinely fail | ✅ | The mutants above, all killed |
| AC4 | Plan §3 and walkthrough | n/a (Stage 4) | This is the orchestrator's step |
| DoD-1 | Suite passes | ✅ | 1516 passed, 0 failed |
| DoD-2 | Lint clean | ✅ | `All checks passed!` |
| DoD-3 | No live model call | ✅ | No live test or CLI was run. The o-2 test patches `main` |
| DoD-4 | Every new `src/` function is exercised | ✅ | The round 1 logger-filter gap is closed |
| DoD-5 | Docs match code | ✅ | `test_docs_consistency.py` passes within the full suite |
| DoD-6 | Walkthrough | n/a (Stage 4) | This is the orchestrator's step |

**Acceptance criteria: 3 of 3 checkable criteria pass.** Definition of Done: 5 of 5 checkable rows pass.

## R2.5 Gate matrix (round 2)

| Gate | Status | Note |
| :--- | :---: | :--- |
| 1 Strict TDD | ✅ | Q-M1, Q-m1 and Q-m2 are closed, and every mutant is killed |
| 2 Zero-token testing | ✅ | Unchanged from round 1. The new o-2 test cannot reach an endpoint |
| 3 Pydantic v2 contracts | ✅ | M2 is fixed. `RunRecord` reports only Q8 = D fields |
| 4 to 6 | n/a | No guardrail, telemetry or Supervisor code changed |
| 7 Drafts and logging | ✅ | The negative control for the `ERROR` banner is added |
| 8 Python and subprocess safety | ✅ | See the hygiene check below |

**Hygiene.**
* No `.env` and no `.agents/docs/BENCHMARK.md` exist.
* `pyproject.toml` and `uv.lock` are unchanged.
* `drafts/` and `logs/` hold only `.gitkeep`.
* No `python` or `uv` process postdates the MCP servers started at 14:01.
* The scratch copy is deleted.

## R2.6 Findings

* Blocker: none.
* Major: none.
* Minor: none.

Nothing needs a decision.

Verdict: **PASS** (APPROVED).
