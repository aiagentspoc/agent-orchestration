# Iteration 16 — Architect review, round 1

**Scope:** the uncommitted diff on `approach-2/implementation` (HEAD `e8d0fa9`): `src/benchmark.py` (new), `tests/test_live/`, `tests/support/{role_bleed,live_checks}.py`, `tests/fixtures/`, four new unit test modules, the edits to `tests/conftest.py`, `tests/test_unit/{test_isolation,test_module_structure,test_docs_consistency}.py`, `README.md`, the P14/P15 rows in `SPECIFICATIONS.md`, and the one-line range text in `AGENTS.md`, `CLAUDE.md`, the three `.claude/agents/*.md` files and both review criteria files. The `IMPLEMENTATION_PLAN.md` and `QUESTIONS.md` diffs are the orchestrator's (P14/P15 rows, Q14/Q15, the §3 status) and are reviewed only for consistency.

**Commands run (no live call):**
* `uv run pytest -q`: **1508 passed, 4 deselected** (86.6 s). Baseline 1437, +71.
* `uv run pytest -m live --collect-only -q`: 4 tests collected (`test_prompt_a_runs_to_sound_drafts`, `test_prompt_b_applies_the_recency_rule`, `test_no_sub_agent_calls_a_tool_its_prompt_declares_a_non_goal[prompt-a|prompt-b]`), 1508 deselected. No other `-m live` command, no `python -m src.cli PROMPT`, no `.agents/docs/BENCHMARK.md` generated.
* `uvx ruff check src tests --no-cache`: All checks passed. **In-scope: 0. Pre-existing debt: 0.**
* `uvx pyright src/benchmark.py tests/test_live tests/support/role_bleed.py tests/support/live_checks.py` (not part of the DoD): 1 error, `src/benchmark.py:199` (finding M2).
* `cmp` of `tests/fixtures/draft_20260918_001.md` and `draft_20260924_002.md` against `../code-orchestration/drafts/`: byte-identical.
* `git status --short` / `git diff --stat`: the only `src/` change is the new `src/benchmark.py`.

---

## 1. Overall verdict

**CHANGES REQUESTED** (skill scale: `APPROVED WITH RESERVATIONS`; no architecture violation).

The architecture is sound: nothing sequences the sub-agents, the live tests drive the real production path with every benchmark constant left alone, the isolation opt-out is keyed on `live` alone and proven with positive and negative controls, and the role-bleed table matches the prompts. Three small fixes are required in `src/benchmark.py`: one extra metric in the runs table (Q8 = D), one typing gap, and one inaccurate footnote sentence.

---

## 2. Pillar audit

### 1. An agent owns the flow — ✅
* `tests/test_live/test_live_e2e.py:78-98` drives `src.cli.main([prompt, "--drafts-dir", …], runner=<wrapper>, log_dir=…)`; the wrapper (l.88-91) calls `run(run_prompt, config)` and only captures the returned `RunState`. Nothing calls a tool, picks a candidate or orders sub-agents.
* The assertions are outcomes, guardrails and role boundaries (D-J testing principle, `SPECIFICATIONS.md` l.528), never a call sequence.
* `src/benchmark.py` reads files only; it imports nothing from `src`.

### 2. Division of labour — ✅ (not touched in `src/`)
* `tests/support/role_bleed.py:59-61` adds the Q10 = B structural check: no substrate tool recorded against the `supervisor` stage; proven offline in `tests/test_unit/test_role_bleed.py:158-162`.

### 3. Custom agent tools — not touched by this iteration.

### 4. Guardrails and attempt state — ✅ (not touched in `src/`)
* Prompt A (`test_live_e2e.py:109-121`) tolerates violations, lists them in the failure message (`_outcome`, l.101-106), and asserts only that none ended the run (`exit_code is SUCCESS`, `fatal_error is None`), as the plan and AGENTS.md Rule 3 require.
* `tests/support/live_checks.py:136-142` checks `attempts_used <= MAX_ATTEMPTS_PER_DOC` and that the rendered "Revision Attempts" equals it.

### 5. Benchmark parity — ✅
* **Real production path, benchmark constants intact.** The runner calls `run(run_prompt, config)` with no keyword arguments, so `client_factory=HSEMockMCPClient`, `model_builder=build_model`, `clock=date.today` and `reasoning_settings=None` (read from `.env`) all hold (`src/app.py:107`). No `--max-drafts`; `--log-level` stays `INFO`; the template is `REPO_ROOT/.agents/templates/draft.md` via `src/cli.py:build_config`. Only drafts and logs are redirected to `tmp_path_factory`.
* **`.env`.** `_read_the_repository_dotenv` (l.67-75) pins `env_file` to `REPO_ROOT/.env` on all three settings classes, so `CostSettings` and `ReasoningSettings` are the user's and the cost basis is not silently the defaults. The README states the cost-basis caveat ($2.50/$0.250/$15.00 vs $1.25/$0.125/$10.00), which I checked against `src/costs.py:39-41` and the Cost Basis line of `../code-orchestration/drafts/draft_20260924_002.md:134`.
* **Role-bleed table (P1).** `tests/support/role_bleed.py:27-31` equals Approach 1's `NON_GOAL_TOOLS` (`../code-orchestration/tests/test_integration/test_e2e.py:591-611`) without the `scope_parser` row. Each row rests on a clause of this repo's prompts: `src/agents.py:142` and `:136` (Scout), `:282` (Writer), `:402` (QA-Legal); `qa_legal` correctly omits `search_regulatory_docs` (permitted at `:346`). `test_role_bleed.py:121-133` pins each clause, `:106-112` is the positive control for every listed non-goal, and `:136-149` proves structured-output entries (`ScoutReport`, `ArticleDraft`, `QAReport`) are not mistaken for substrate tools.
* **Prompts:** `PROMPT_A` and `PROMPT_B` match the plan and are pinned by `test_live_suite.py:57-63`.

### 6. Substrate isolation and lifecycle — ✅
* The live run uses the real `HSEMockMCPClient` through the default `client_factory`; `src/app.py` is unchanged.
* **Isolation opt-out.** `tests/conftest.py:72-73` returns early only when `request.node.get_closest_marker("live")` is set. `tests/test_unit/test_isolation.py:60-94` runs the real fixture in a `pytester` inner session with one `live` test (variable and `env_file` survive) and one unmarked test (both stripped): positive and negative control, no model built. The default run never reaches a `live` test (`addopts = "-m 'not live'"`, `pyproject.toml:45`), and `test_live_suite.py:38-44` checks every module under `tests/test_live/` carries the module-level `live` mark.
* `pytest_plugins = ["pytester"]` (`tests/conftest.py:27`) is in the initial conftest under `testpaths = ["tests"]`; fine.

### 7. Rendering, telemetry and logging — ✅ with M1 and m1
* **Q8 = D summary.** The summary table (`src/benchmark.py:368-387`) has exactly: drafts parsed, cost/time/tokens per draft, QA status, revision attempts, run wall-clock. Correct.
* **Q9 = C labels.** `CONTENT_FACTORY` / `RESEARCH_ANALYST` (l.111-115) carry "Content Factory" / "Research Analyst" and the `approach_name` each folder's drafts must state (§3.3); a mismatch is a usage error (exit 2).
* **P15.** Content Factory: `src.orchestrator` header lines only; wall-clock is "finished" minus the latest unpaired "starting", `None` otherwise (l.236-281). I confirmed in `../code-orchestration/src/orchestrator.py:972` and `:913`, with `:1189`, that both lines are logged inside the `with client_factory()` block, so the footnote's description of the span is accurate. Research Analyst: anchored `_A2_COMPLETED` stopping at `summary=` (l.76-79), filtered to logger `src.app`, with a contract test through the real `configure_logging` and `src.app._log_run_completed` (`test_benchmark.py:315-335`). Logs default to `<drafts>/../logs`, with `--a1-logs`/`--a2-logs`. The wall-clock range covers exit-0 runs only, and every run is listed (recorded decision).
* **M1:** the runs table adds a **Violations** column (l.482-486), a Research-Analyst-only measure that is not one of Approach 1's metrics.
* **m1:** one footnote sentence does not match the parser's behaviour for a "starting" line with no "finished" line.

### 8. Code quality — ✅ with M2
* Imports at the top, grouped; zero E402; ruff clean; full annotations; Pydantic v2 models with `ConfigDict(extra="ignore")`; no `dict[str, Any]` across a boundary; `pathlib.Path` throughout; UTF-8 explicit on every read and write; `__main__` guard, no import-time side effects; no logger (so no `__name__` logger to trip `test_logging`).
* **M2:** `src/benchmark.py:199` passes a `str` to the `QAStatus` Literal field (pyright `reportArgumentType`).

---

## 3. Code review findings

| ID | Severity | Location | Finding |
| :--- | :---: | :--- | :--- |
| M1 | 🟡 Major | `src/benchmark.py:77`, `:136-161`, `:275`, `:321`, `:482-486` | The runs table reports guardrail **violations** per run. `SPECIFICATIONS.md` D-B l.274 ("exactly Approach 1's metrics (Q8 = D)"), §8 Q8 ("D. Nothing extra") and the plan's Iteration 16 line 789 ("it reports only Approach 1's metrics") exclude it: Approach 1 has no guardrails, and a Supervisor-behaviour count is the kind of extra metric Q8 = D declined. Exit code, drafts, failures, tokens and cost are all fields of Approach 1's own "Pipeline run finished" line, so they may stay |
| M2 | 🟡 Major (typing gap, per the code-reviewer taxonomy; one-line fix) | `src/benchmark.py:199` | `qa_status=status.group(1)` gives a `str` to a `Literal["PASS", "WARNING", "ERROR"]` field. Pydantic validates it at runtime, but the annotation is not honoured statically (pyright: `Type "str" is not assignable to type "QAStatus"`) |
| m1 | 🟢 Minor | `src/benchmark.py:89-90`; `tests/test_unit/test_benchmark.py:476-487` | The footnote says "Runs whose log lacks either Content Factory line show "not recorded"". The parser (l.239-242, `test_a_start_with_no_finish_is_not_a_run`) lists **no** run for a "starting" line with no "finished" line, so only a missing "starting" line gives "not recorded". The README's last sentence states it correctly; the report must too. (The wording came from the pre-flight brief; the brief was wrong, not the implementer.) |

Optional (not required for approval):
* **o1.** `RESEARCH_ANALYST.approach_name` (`src/benchmark.py:115`) restates the literal default of `DraftMetadata.approach_name`. A one-line test pinning `RESEARCH_ANALYST.approach_name == DraftMetadata.model_fields["approach_name"].default` would catch drift without making `benchmark.py` import `src.schemas`.
* **o2.** `test_live_suite.py:53` compares the skip condition's boolean value with a recomputed one, which any condition of the same truth value passes. Asserting `"agent-orchestration/.env" in skip.kwargs["reason"]` as well would tie it to the right file.
* **o3.** `src/benchmark.py:546-549` prints the `--out` path unencoded; a non-ASCII path on a legacy Windows code page would raise after the report is written. `src/cli.py` avoids this by printing ASCII only.

---

## 4. Anti-patterns and risks

* **Autonomy leaks:** none. No code outside the Supervisor chooses a tool; the live tests and the benchmark only observe.
* **Parity drift:** none in the run path. The live tests leave the model builder, efforts, clock, ceiling, template, tool binding and cost settings exactly as a user's run has them.
* **Article text towards the Supervisor:** not affected; `src/` other than `benchmark.py` is unchanged.
* **Zero tokens:** held. Importing the live module only evaluates `DOTENV.is_file()`, which `test_live_suite.py` exercises under the default isolation; the `pytester` inner session builds no model.
* **Stale plan text (orchestrator's, not the implementer's).** `IMPLEMENTATION_PLAN.md` Iteration 16 l.785 still says "The corpus ends on 2024-07-24 … assert exit 1", and l.787-788 give the three-option CLI and "each run's 'Run completed' log line", all superseded by P14 and P15 (same file, l.124-125). §6 Traceability (l.805-828) has no rows for P11–P15. These are recorded in `FIXES.md` for the orchestrator.

---

## 5. Remediation directives

1. **M1 (Q8 = D; `SPECIFICATIONS.md` D-B l.274, §8 Q8; plan Iteration 16 l.789).** Remove the Violations column from `_runs_table` and drop `RunRecord.violations`; read `violations=\d+` without capturing it in `_A2_COMPLETED`. Update the affected assertions in `tests/test_unit/test_benchmark.py`. Details in `FIXES.md`.
2. **M2 (Pillar 8; code-reviewer Gate 8).** Make the `QAStatus` value type-correct at `src/benchmark.py:199`, via `typing.cast` or `DraftRecord.model_validate`.
3. **m1 (P15).** Reword the footnote's last sentence to match the parser, and update the pinned text in `test_the_wall_clock_footnote_states_what_each_approach_measures`.

Verdict: **CHANGES REQUESTED**

---

# Iteration 16 — Architect review, round 2

**Scope:** the implementer's fix round 1: `src/benchmark.py`, `tests/test_unit/{test_benchmark,test_live_suite,test_live_checks}.py`, `tests/test_live/test_live_e2e.py`.

**Commands run (no live call):**
* `uv run pytest -q`: **1516 passed, 4 deselected** (91.3 s), +8 on round 1.
* `uvx ruff check src tests --no-cache`: All checks passed. **In-scope: 0. Pre-existing debt: 0.**
* `uv run pytest -m live --collect-only -q`: the same 4 live tests, 1516 deselected.
* `uvx pyright src/benchmark.py tests/test_live tests/support/role_bleed.py tests/support/live_checks.py`: 0 errors (round 1: 1).
* `git status --short src`: `src/benchmark.py` is still the only `src/` change. No `.env`, no `.agents/docs/BENCHMARK.md`.

## 1. Overall verdict

**APPROVED.** Every round-1 item is resolved as directed, and the restructured live module still drives the real production path with every benchmark constant intact.

## 2. Verification of round-1 findings

| ID | Status | Evidence |
| :--- | :---: | :--- |
| M1 | ✅ | `RunRecord` (`src/benchmark.py:138-161`) has no `violations` field. `_runs_table` (l.475-488) has 8 header cells, 8 alignment cells and 8 row cells. `_A2_COMPLETED` (l.77-80) still requires `violations=\d+` but does not capture it. The groups are renumbered: tokens 5, cost 6, wall-clock 7 (l.320-322), which the real-logger contract test confirms (`test_benchmark.py:318-335`). `test_the_runs_table_reports_only_approach_1s_run_metrics` (l.499-517) pins the header, that "Violations" is absent, and the field set. No README or doc text mentions the column. |
| M2 | ✅ | `qa_status=cast(QAStatus, status.group(1))` (l.199); `cast` is imported at l.17; pyright reports 0 errors. |
| m1 | ✅ | The footnote (l.86-93) ends with the directed sentence, and `test_benchmark.py:520-532` pins it verbatim. It now matches `parse_content_factory_log` (l.259-266) and `test_a_start_with_no_finish_is_not_a_run`. |
| o1 | ✅ | `test_benchmark.py:143` pins `RESEARCH_ANALYST.approach_name` to `DraftMetadata.model_fields["approach_name"].default`. `benchmark.py` still imports nothing from `src`. |
| o2 / Q-m3 | ✅ | `test_live_suite.py:54` and `:56` pin `DOTENV == REPO_ROOT / ".env"` and the reason's `agent-orchestration/.env`. |
| o3 | ✅ | `src/benchmark.py:544` escapes the path with `backslashreplace`, and `test_benchmark.py:603-615` writes to a path containing "é" and asserts the line is ASCII. |
| Q-M1, Q-m1, Q-m2 | ✅ (QA's to confirm) | `test_benchmark.py:255-259`: the foreign logger's lines now start with the prefix. `:379-380`: a `src.app` "Run started" line quotes a "Run completed" line. `:465-482`: the costs 0.10/0.20/0.60 give a mean of $0.3000. Each closes the gap QA named. |

## 3. Re-check of what the fixes touched

### Pillars 1, 5 and 6: the restructured live module (`tests/test_live/test_live_e2e.py`)
* **The real production path is kept.** `_run_through_the_cli` (l.100-117) calls `main([prompt, "--drafts-dir", …], runner=runner, log_dir=root / "logs")`, and the wrapper calls `run(run_prompt, config)` with no keyword arguments (l.109). The defaults in `src/app.py:107-115` therefore all hold: `client_factory=HSEMockMCPClient`, `model_builder=build_model`, `clock=date.today` and `reasoning_settings=None`. There is no `--max-drafts` and no `--log-level` override, and `main`'s signature (`src/cli.py:109-113`) is unchanged.
* **Benchmark constants.** The `.env` pin for all three settings classes is unchanged (l.69-77). Prompts A and B are unchanged and still pinned (`test_live_suite.py:60-66`).
* **Failure caching (QA o-2).** `_live_run` (l.80-97) records only `Exception`. pytest's skip and fail outcomes and `KeyboardInterrupt` derive from `BaseException`, so a skip is never turned into a cached failure, and an interrupt still stops the session. The re-raise chains the original with `from failure`, so the cause stays visible.
* **Offline proof.** `test_a_failed_live_run_is_not_paid_for_twice` (`test_live_suite.py:69-90`) monkeypatches the module's `main`, `_RUNS` and `_FAILED_RUNS`, so the session's real caches are untouched. It runs in the default suite with no model built, and the live module's autouse `.env` fixture does not apply outside its own module.
* **No sequencing.** Nothing in the live module calls a tool or orders sub-agents. It only runs the command line and observes the `RunState`.
* The `live` mark, the skip rule and the isolation opt-out are unchanged.

### Pillar 7: report content (Q8 = D)
* The summary rows and the runs-table columns are now exactly Approach 1's metrics. The module docstring (l.3-5) and `render_report`'s docstring stay accurate.

### Pillar 8: code quality
* The imports are grouped and at the top. There is no dead code from the removed field: no `_UNSET_CELL` use is orphaned, since l.483 still uses it for `run_id`. Annotations are complete and ruff is clean.

### Pillars 2, 3 and 4
* Not touched by this fix round.

## 4. Findings

None required.

Optional (not required for approval):
* **o4.** `tests/test_unit/test_benchmark.py:599` compares the printed line with an unescaped `f"Wrote {out}: …"`. On a machine whose temp folder path is non-ASCII, l.599 and l.600 would fail even though `main` behaves correctly. Building the expected text with the same `encode("ascii", "backslashreplace")` would make it independent of the host. This does not affect this repository's environment.

## 5. Carried over for the orchestrator (not the implementer's scope; non-blocking)

The three plan-text items from round 1 are still open in `IMPLEMENTATION_PLAN.md`:
* Iteration 16, l.785: the "corpus ends on 2024-07-24 … assert exit 1" text versus P14.
* Iteration 16, l.788: "each run's 'Run completed' log line" versus P15 and the `--a1-logs`/`--a2-logs` options.
* §6 Traceability: no rows for P11–P15.

They concern the plan, not the code, and they belong in the orchestrator's walkthrough or tracker update.

Verdict: **APPROVED**
