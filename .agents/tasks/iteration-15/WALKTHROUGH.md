# Iteration 15 — Scripted end-to-end scenarios: walkthrough

**Date:** 2026-10-05 · **Branch:** `approach-2/implementation` · **Plan section:** `IMPLEMENTATION_PLAN.md` §5, Iteration 15

## 1. Overview

Iteration 15 tests the whole system end to end with zero tokens. Each scenario calls `src.app.run` once:
* over one real stdio session with the local `hse-easy-mock` substrate;
* with a scripted Supervisor;
* with scripted sub-agents for the Scout, the Writer and QA-Legal.

The path is decided at runtime (D-J). So the scenarios never assert exact call sequences. They assert:
* guardrails;
* persisted outcomes (draft files, `RunState.violations`, `RunState.failures`, the exit code);
* the D-I events, read back from the run's log file.

The Supervisor's choices are its scripted turns alone, and nothing in the test module decides which tool runs next.

This iteration is **tests only**: nothing under `src/` changed.

## 2. Files changed

| File | Status | Responsibility |
| :--- | :--- | :--- |
| `tests/test_integration/test_supervisor_e2e.py` | New, 1202 lines, 19 tests | The 15 plan scenarios (13 split into `s13a` and `s13b`), two extra runs (`x01`, `x02`) and the catalogue-coverage test |
| `.agents/docs/IMPLEMENTATION_PLAN.md` | Edited by the orchestrator | The §3 tracker only |
| `.agents/tasks/iteration-15/` | New | `ARCHITECT_REVIEW.md`, `QA_REVIEW.md`, `FIXES.md` and this walkthrough |

**How the module works:**
* **One run per scenario.** `_run` calls `run(PROMPT, config, client_factory=…, model_builder=…, clock=lambda: TODAY, reasoning_settings=…)` with these settings:
  * `client_factory` defaults to the real `HSEMockMCPClient`.
  * `model_builder` is `scripted_model_builder_by_effort`, which gives each role its own `ScriptedModel`.
  * `reasoning_settings` sets the Supervisor's effort to `low`, so its model is built apart from QA-Legal's (both use `gpt-5.4`).
* **Real documents.** It uses the corpus IDs `inail-2024-circ-calore` and `inail-2026-ot23`, so the Writer's live `get_document_by_id` returns a real document.
* **The run log.** An autouse fixture uses `restore_logging` and calls `configure_logging` into `tmp_path`, as `cli.main` does.
  * `_read_log` parses each header line and attaches continuation lines (tracebacks, pydantic reports) to the record above.
  * Each record stores its position.
  * The file is found by pattern, because its name uses the real date, not the injected clock.
* **Checks every scenario makes:**
  * the exit code, and the exact `violations` and `failures`;
  * the draft files, with their **Status** and **Revision Attempts** lines;
  * each role's turns replayed exactly (`_assert_consumed`), so an exhausted script cannot pass silently;
  * the one "Run completed" line: it agrees with `state.exit_code`, its `violations=` and `failures=` counts are exact, and its logged wall-clock is under 60 s;
  * `run_id` on every `src.*` line;
  * the scenario's own D-I events at the catalogue's levels, through `_assert_events(result, "<key>")`.
* **Catalogue coverage.** Each scenario's events are declared in the static `_SCENARIO_EVENTS`.

## 3. TDD record

Every scenario passed as soon as it was written, because the production code already existed. Each one was then shown able to fail. The method: make a temporary change to production or test code, see the expected failure, and restore the file from a byte-for-byte backup.

| Test | Plan scenario | Temporary change → failure |
| :--- | :--- | :--- |
| s01 | Happy path, two `PASS` | "QA verdict PASS" logged at WARNING → level mismatch. Supervisor left out of the shared split → the token identity broke |
| s02 | `ERROR` three times | Banner WARNING never logged → no banner line |
| s03 | Substantive `WARNING` → revise → `PASS` | Revision always "follows=ERROR" → mismatch |
| s04 | Advisory `WARNING` → save | Rendered Status fixed to `PASS` → mismatch |
| s05 | Writer fails, retry | `initial_draft_exists` firing after any attempt → unexpected violation |
| s06 | Revision fails → earlier draft saved | A rejected draft still stored → `not_audited` violation |
| s07 | Writer fails three times | Draft-less unsaved candidates not logged → no "left unsaved" line. The first version of this change was too weak and survived; the second one failed |
| s08 | Guardrail violations | P2 removed for `writer_tool` → `revise_after_pass` where `already_saved` was expected. Violations logged at INFO → level mismatch |
| s09 | Same violation five times | At most 3 stored → 2 missing |
| s10 | Transport dies after one save | Fatal hook never cancels → the summary became `'must not be reached'` |
| s11 | Provider fails after one save | `remote=None` logged → JSON decode error |
| s12 | Scout finds nothing | NO_UPDATES rule disabled → exit 0 |
| s13a | Never calls `scout_tool` | PARSER_ERROR rule disabled → exit 0 |
| s13b | Invalid scope corrected | Any earlier violation counting as a Scout run → exit 3 |
| s14 | Existing drafts for today | Draft-ID allocation ignoring the disk → `_002` instead of `_005` |
| s15 | D-F | `supervisor_view` keeping the draft → sentinels found |
| coverage | AC2 | `x01`/`x02` removed from the event map → "never asserted"; an `_assert_events` call deleted → `AssertionError: x01` (after fix round 1) |

**Fix round 1 strengthened four test-side checks.** Each weakness was first shown on the unchanged code:
* `_Run.index` now uses each record's position instead of matching content.
* The `violations=` and `failures=` checks are exact, not substring matches.
* Repeated scripted turns are built fresh, not shared by `[turn] * n`.
* The coverage test checks, through `inspect.getsource`, that each scenario's test calls `_assert_events` with its own key.

## 4. Test results

The orchestrator ran the suite fresh, after this walkthrough was written:

* `uv run pytest -q`: **1437 passed**, 0 failed, 0 errors.
* Tests added: **+23** over Iteration 14's 1414.
  * 19 are in `test_supervisor_e2e.py`.
  * 4 are forbidden-term cases in `test_docs_consistency.py`, one for each new `.md` file in `iteration-15/`.
* `uvx ruff check src tests`: **All checks passed!**
* **AC1 timings.** These are the call phase of `uv run pytest tests/test_integration/test_supervisor_e2e.py --durations=0`, as the implementer measured them. Every scenario is well under 60 s.

  | Scenario | s01 | s02 | s03 | s04 | s05 | s06 | s07 | s08 | s09 | s10 | s11 | s12 | s13a | s13b | s14 | s15 | x02 | x01 |
  | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
  | Seconds | 2.95 | 2.06 | 1.99 | 1.93 | 1.95 | 1.99 | 1.93 | 2.03 | 1.89 | 1.94 | 1.91 | 1.89 | 1.89 | 2.06 | 2.01 | 2.04 | 2.04 | 0.02 |

  * The whole file took 35–50 s across the reviewers' runs.
  * The slowest single scenario in any reviewer run was 3.05 s.
  * QA ran the file three times in each round, with no failure and no order dependence.
* **No live model call.** Every model is a `ScriptedModel`, and `pytest -m live` was not run. Only the local substrate is used, which is allowed.
* **No stray processes,** and the repository's `drafts/` and `logs/` hold only `.gitkeep`.

## 5. Acceptance criteria

| Criterion | Status | Evidence |
| :--- | :---: | :--- |
| Each scenario asserts the drafts, their QA status and attempts, the violations, the failures, the exit code and its D-I events from the log file | ✅ | The common assertions in §2, made by every scenario |
| Scenarios 1–15, against the plan's "Key assertions" | ✅ | s01–s15. QA checked them row by row in round 1 |
| **AC1:** all 15 scenarios pass in the default run, each in under 60 s | ✅ | §4 timings. Each test also asserts its own logged wall-clock is under 60 s |
| **AC2:** every D-I catalogue event is asserted by at least one scenario; a test compares the catalogue with the set asserted | ✅ | See below |
| DoD-1 to DoD-6 | ✅ | §4 above; no `src/` change; this file |

**How AC2 is checked.** `test_every_catalogue_event_is_asserted_by_a_scenario` does the following:
* reads the 23-event D-I table from `SPECIFICATIONS.md`, between "**Event catalogue:**" and "#### D-J.";
* checks that there is one recognition pattern per event;
* checks that the union of `_SCENARIO_EVENTS` equals the catalogue;
* checks that each declaration is used by exactly one test, and that this test calls `_assert_events` with its own key.

The catalogue has no DEBUG row, so nothing needs to be excluded.

## 6. Decisions and deviations

**Decisions (§1.5, test organisation):**
* **Two extra runs, `x01` and `x02`.** None of the 15 planned scenarios reaches two catalogue events, so these runs cover them for AC2:
  * "Configuration failure": `x01`, unresolved credentials, exit 5, with the pydantic report on the continuation lines;
  * "Draft render or write failure": `x02`, a missing template, exit 4.
* **Scenario 11 uses a `ScriptedModel`, not the plan's `FailingModel`.** It raises a genuine `openai.RateLimitError` (429, with a request ID) after one save. `FailingModel` fails on every call, so it can never fail "after one save". `ModelThrottledException` is never raised, because Strands retries it.
* **Scenario 13b runs on to a save and exits 0.** The plan says only "the retry succeeds".
* **"Model HTTP call": only the hook's half is asserted.** Scripted models make no HTTP request, so the httpx method, URL and status lines cannot appear in a zero-token run (P4).
* **"Sub-agent invocation started / completed"** also requires the Supervisor's own "Supervisor invocation started/completed" lines.
* **Scenario 10's mechanism.** A `ScriptedModel` subclass for the Supervisor stops the real inner substrate session just before its fifth turn. The next Writer build's listing then raises `MCPConnectionError`, which is the dead-transport case in §8.4. The outer session closes cleanly, so the Q12 close-time path is not reached, as Q12 = A requires. The architect traced this in Strands 1.55.1.
* **Not included (optional in the brief):**
  * extra decision-table variants at attempt 3: "WARNING / 0 → Save" and "Writer failed / 0 / earlier draft → Save";
  * end-to-end coverage of the `attempt_limit`, `not_audited` and `no_draft` guardrails, which keep their Gate 4 tests.

**Deviations:** two, both recorded above: scenario 11's model, and the two extra runs. Nothing under `src/` changed.

**Notes for Iteration 16:**
* **Accepted as brittle:** scenario 10 checks that "Fatal abort triggered" is logged before "Tool call completed". That order comes from Strands running `AfterToolCallEvent` callbacks in reverse.
* **Do not test:** the close-time plain `RuntimeError`, which stays a known limit (Q12 = A).

## 7. Review

Two rounds were used.

**Round 1.**
* **Architect: APPROVED.** It checked D-J, that `src/` was untouched, the control flow, scenario 10's mechanism, D-F and AC2. It raised four optional items, all **resolved** in the fix round:
  1. `_Run.index` matched log lines by content.
  2. The counter checks matched substrings.
  3. `[turn] * n` shared event data between turns.
  4. The coverage test did not check that each test asserts its own events.
* **QA: PASS.** QA confirmed every scenario row and both acceptance criteria. Eight of its mutations to production code were all caught. **QA-1** (optional) was the same point as architect item 4: deleting `x01`'s `_assert_events` call survived. **Resolved.**

A fix pass was run, because round 1 allowed it.

**Round 2.**
* **Architect: APPROVED**, no findings.
* **QA: PASS**, no findings. QA repeated its round 1 mutation, which now fails with `AssertionError: x01`, and two further mutations were also caught.

No item needed a decision.
