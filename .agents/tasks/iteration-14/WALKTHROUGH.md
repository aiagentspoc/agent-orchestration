# Iteration 14 — Composition root and CLI: walkthrough

**Date:** 2026-10-05 · **Branch:** `approach-2/implementation` · **Plan section:** `IMPLEMENTATION_PLAN.md` §5, Iteration 14

## 1. Overview

Iteration 14 takes one run from the CLI prompt to its exit code, following the activity flow in SPECIFICATIONS.md §4.

* **`src/app.py`, `run(prompt, config, *, client_factory, model_builder, clock, reasoning_settings) -> RunState`.** In order, it:
  1. resolves the reasoning efforts;
  2. loads the rates and builds the four models, once each;
  3. opens exactly one substrate session;
  4. binds a fresh `RunState` into the four tools;
  5. invokes the Supervisor once;
  6. after the session has closed, renders the saved drafts with `finalise_run`;
  7. maps the outcome to an exit code (P6, P13).

  Every log line carries the `run_id`. "Run completed" closes every run, early exits included.
* **`src/cli.py`.** It holds `build_arg_parser()` (SPECIFICATIONS.md §7.5's four arguments) and `build_config`. It also holds `_resolve_redaction_key` and `main(argv, *, runner, log_dir, api_key) -> int`, both ported from Approach 1.
* **Carried in.** The Iteration 13 test-side items (Q10 = A) are applied in `tests/test_unit/test_supervisor.py`.

Three questions came up:
* **Q11** (pre-flight) became **P13**: `PARSER_ERROR` needs a Supervisor that ended on its own.
* **Q12** (review): a session that fails as it closes is recorded as a known limit.
* **Q13** (review): a standing approval for the range-text edits.

## 2. Files changed

| File | Status | Responsibility |
| :--- | :--- | :--- |
| `src/app.py` | New, 408 lines | `run`, `_run_once`, `_supervise`, `_exit_code` and their helpers; see below |
| `src/cli.py` | New, 151 lines | `REPO_ROOT`, `Runner`, `build_arg_parser`, `build_config`, `_resolve_redaction_key`, `main`, and the `__main__` guard |
| `src/tools.py` | Edited, names only | `_FATAL_ERRORS` → public `SESSION_ERRORS`, `_failed_call_telemetry` → `failed_call_telemetry`, `_failure_record` → `failure_record`. All three are in `__all__` and reused by `app.py`; no behaviour changes |
| `tests/test_integration/test_app.py` | New, 41 tests | Every exit-code row end to end through `run`, plus the session, models, logging and live-substrate tests |
| `tests/test_unit/test_app.py` | New, 79 tests | `_exit_code`: the brief's P6/P13 rows, the close-time-death edge, and all 64 flag combinations |
| `tests/test_unit/test_cli.py` | New, 22 tests | Parser, `build_config`, `main`, `_resolve_redaction_key`, and a `--help` subprocess test |
| `tests/test_unit/test_isolation.py` | New, 4 tests | A `.env` in the working directory reaches none of the three settings classes |
| `tests/conftest.py` | Edited | The autouse isolation now pins `env_file=None` on `CredentialManager`, `CostSettings` and `ReasoningSettings` (previously only the last) |
| `tests/support/scripted.py` | Edited | `OfflineSubstrateSession.__enter__/__exit__`, recording `events` and optionally raising `fail_enter_with` or `fail_exit_with`. The real `HSEMockMCPClient.__enter__/__exit__` therefore stay in the test path |
| `tests/test_unit/test_supervisor.py` | Edited, 120 → 138 tests | Iteration 13 carry-over A1–A5 and part of QA-m6 |
| `tests/test_unit/test_docs_consistency.py` | Edited | `IMPLEMENTATION_DECISIONS` gains P13; two docstrings now say "P1 to P13" |
| `tests/test_unit/test_module_structure.py` | Edited | `EXPECTED_MODULES` gains `src.app` and `src.cli` |
| `.agents/docs/SPECIFICATIONS.md` | Edited by the implementer | P13 is applied in five places: the status line and the §8 index; the §6.10 `PARSER_ERROR` comment; the §7.6 row and the paragraph under it; the §8.3 heading and the P13 row. The next decision is now named P14 |
| `AGENTS.md`, `CLAUDE.md`, both `.agents/skills/*/SKILL.md`, the three `.claude/agents/*.md` | Edited, range text only | "P1 to P12" (or "P1–P12") → P13. The harness files were changed under Q13 |
| `.agents/docs/IMPLEMENTATION_PLAN.md` | Edited by the orchestrator | §2 gains P13; the §3 tracker row |
| `.agents/tasks/QUESTIONS.md` | Edited by the orchestrator | Q11, Q12 and Q13, raised and answered |
| `.agents/tasks/iteration-14/` | New | `ARCHITECT_REVIEW.md`, `QA_REVIEW.md`, `FIXES.md` and this walkthrough |

**What `src/app.py` does, step by step.** The whole run sits inside `log_context(run_id=uuid4().hex)`, and the clock is read once.

1. **Efforts.** `_resolve_efforts` keeps the Scout at its constant. The other three roles take an `.env` override, or their constant when it is unset or empty. Each resolved effort both builds its model and labels its telemetry.

   "Run started" logs the run, the raw prompt (`%r`), the date, the ceiling, the log level, and the four model/effort pairs.
2. **Configuration, before any subprocess.**
   * `load_model_rates()` and `_build_models` build the Scout on `gpt-5-mini` and the Writer, QA-Legal and Supervisor on `gpt-5.4`.
   * Only `(ValidationError, ValueError)` is caught. It is logged as ERROR "Configuration failure" and recorded as `FailureRecord(stage="configuration")`. The run then returns early with `CONFIG_ERROR`, opens no session and does not call `finalise_run`.
3. **The session.** There is one `client_factory()` and one `with client:`.
   * Inside it: the composition root's own tool listing; INFO "MCP session opened" with the server directory, launch command and tool count; then `RunState(run_id, config, RunContext(today, max_drafts=config.max_drafts, drafts_saved=0))`; then `_supervise`.
   * `except SESSION_ERRORS` logs ERROR "MCP session failed to open, or died mid-run".
     * Before the state exists, it returns early with `MCP_ERROR`.
     * Afterwards, which only closing the session can cause, it records an `mcp_session` failure, sets `session_lost`, and lets the run end.
4. **`_supervise`.**
   * `build_tools(state, client=…, models=…, efforts=…)` gets no `hooks=`.
   * INFO "Supervisor invocation started" is logged.
   * The agent is built with `build_supervisor_agent(models.supervisor, tools, max_drafts=config.max_drafts, hooks=(FatalStopHook(state),))`.
   * **`run_supervisor` is called exactly once.**
   * If it raises an `Exception`, but not a `BaseException`, the run records `FailureRecord(stage="supervisor")` and logs ERROR "Supervisor invocation failed" with the full `RemoteErrorDetail`. It then recovers the telemetry from the agent's metrics through `failed_call_telemetry`, or uses `None` if no agent was built.
   * If it returns normally, INFO "Supervisor invocation completed" is logged.
5. **The run end, outside the `with`.**
   * `finalise_run` runs exactly once, and its `ValueError` for an unpriced model is not caught.
   * `supervisor_summary` is set to the summary exactly as returned (`""` after a typical fatal stop), or `None` if the Supervisor raised.
   * The code from `_exit_code` is stored on `state.exit_code`.
6. **`_log_run_completed`** logs:
   * the exit code and its name;
   * drafts saved, failures and violations;
   * the run's total tokens and cost from `RunFinalisation` (zero on an early exit);
   * the wall-clock;
   * the summary.

**`_exit_code(*, fatal_stop, session_lost, supervisor_raised, scout_succeeded, no_candidates, persistence_failed)`** is pure. It returns the numeric maximum (P6) of the conditions that hold, with `SUCCESS` as the floor:

| Condition | Code |
| :--- | :--- |
| `fatal_stop` or `session_lost` | `MCP_ERROR` (2) |
| `supervisor_raised` | `SUPERVISOR_ERROR` (6) |
| **P13:** not `supervisor_raised`, not `fatal_stop`, and not `scout_succeeded` | `PARSER_ERROR` (3) |
| `no_candidates` | `NO_UPDATES` (1) |
| `persistence_failed` | `PERSISTENCE_ERROR` (4) |

## 3. TDD record

Tests that passed on their first run were shown able to fail with temporary mutations, which were then reverted. Each mutation is recorded in the review artifacts.

| # | Behaviour | Red, or how the test was shown able to fail | Green added |
| :---: | :--- | :--- | :--- |
| 1 | P13 in the decision records | The docs test failed exactly twice: §8.3 stopped at P12, and §8.3 lacked P13's statement | The `SPECIFICATIONS.md` edits |
| 2 | Iteration 13 carry-over | A1: the guard was killed at a 40 s timeout under the old pattern; it now runs in 0.3 ms. A2: 6 probes failed. A3: 2 probes. A4: the old check missed `article_body`. A5: a behaviour-free removal, checked by mutation. QA-m6: 7 probes failed | The pattern fixes. The real prompt still gives `[]` at every ceiling |
| 3 | Isolation | With a `.env` in the working directory, `CredentialManager()` did not raise and `CostSettings()` read 99.0 | The `env_file=None` pins |
| 4 | `_exit_code` | `ModuleNotFoundError: src.app` | The pure helper. Dropping `not fatal_stop` failed 5 cases |
| 5 | Happy path | Cannot import `run` | The minimal `run` |
| 6 | `CONFIG_ERROR` | The `ValidationError` and `ValueError` escaped `run` (credentials, rates, effort) | The configuration `try` and the early return |
| 7 | Session fails to open | `MCPConnectionError` escaped; the opening-listing case gave 3 | The session block, the root's own listing, "MCP session opened" |
| 8 | `SUPERVISOR_ERROR` | The exception escaped `run` | `except Exception`, the failure record and the F1 telemetry recovery |
| 9 | Close-time death | `MCPConnectionError` escaped | `session_lost`. One test gives 2 after a save; another gives 3 (P13 + P6) |
| 10 | D-I logging | Events missing; lines carried `run_id=-` | `log_context(run_id)` around the whole run, "Run started/completed", "Supervisor invocation started/completed" |
| 11 | The other exit-code rows | Passed first. Five flag mutations each failed at least one row | — |
| 12 | Structure | Passed first. Seven mutations each failed a test: `finalise_run` inside the `with`, the clock read twice, a wrong effort, unlabelled telemetry, no ceiling, a second `LoggingHooks`, and a swallowed `ValueError` | — |
| 13 | Live substrate | Replacing the `with` by `start()` failed the close test | 2 tests over the real `hse-easy-mock` |
| 14–18 | CLI | Each failed at import first. The `exit_code is None` guard and the `__main__` guard were checked by mutation | Parser, `build_config`, `_resolve_redaction_key`, `main`, `--help` |
| 19 | Fix round 1, QA-M1 | From a working directory with a `.env` overriding the Writer effort, the `[defaults]` case failed: `('gpt-5.4', 'low') != ('gpt-5.4', 'high')` | The settings are built inside the test, from keyword overrides |
| 20 | Fix round 1, QA-m1 | Each `except` width was checked by its own mutation: widening the configuration `except` to `Exception`, widening the Supervisor `except` to `BaseException`, and narrowing the session-error tuple | Three tests: a builder `RuntimeError` escapes; `KeyboardInterrupt` escapes, and the session still closes; `MCPClientNotConnectedError` exits 2 |
| 21 | Fix round 1, m1 | Refactor; the "Run completed" tests stayed green | `_run_once` returns the `ExitCode`, and `_log_run_completed` takes it, with no dead fallback |

## 4. Test results

The orchestrator ran the suite fresh, after this walkthrough was written:

* `uv run pytest -q`: **1414 passed**, 0 failed, 0 errors.
* Tests added: **+170 net** over Iteration 13's 1244.
  * 41 in `tests/test_integration/test_app.py`;
  * 79 in `tests/test_unit/test_app.py`;
  * 22 in `test_cli.py` and 4 in `test_isolation.py`;
  * +18 in `test_supervisor.py`, from 120 to 138;
  * 2 `test_annotations.py` cases, for the two new modules;
  * 4 forbidden-term cases, one per new `.md` file in `iteration-14/`.
* `uvx ruff check src tests`: **All checks passed!**
* QA ran the whole suite from a working directory holding a populated `.env`, and it passed: no test can reach a model.
* No live model call was made, and `pytest -m live` was not run. Two integration tests use the local `hse-easy-mock` substrate over stdio, which is allowed.

## 5. Acceptance criteria

| Criterion | Status | Evidence |
| :--- | :---: | :--- |
| Red: `run` returns `RunState` with `exit_code` and `supervisor_summary` | ✅ | The `test_app.py` rows |
| Red: exactly one session per run, with the exit-code mapping outside the `with` | ✅ | The order test: enter, Supervisor completed, exit, Draft rendered, Run completed. The live close test |
| Red: four models built once (Scout fast; Writer `high`, QA-Legal `medium`, Supervisor `medium` strong); agents rebuilt per call | ✅ | The four-models test, at defaults and with overrides |
| Red: `run_id` per run, `log_context` around the run, "Run started", "Run completed" and "MCP session opened" | ✅ | The logging tests |
| Red: `finalise_run` always runs once a `RunState` exists, including after `SUPERVISOR_ERROR` and `MCP_ERROR` | ✅ | Rows 2b, 2c, 3 and the close-time cases render what was saved |
| Red: `build_arg_parser()` matches §7.5; `main` configures logging, calls the runner and returns `int`; `--help` exits 0 | ✅ | `test_cli.py` |
| **AC1:** every row of the exit-code table has a test | ✅ | Each row has an end-to-end test. The `_exit_code` unit table covers every P6/P13 row and all 64 combinations, and every non-6 row asserts no `supervisor` failure. See the cases below |
| **AC2:** `uv run python -m src.cli --help` prints the four arguments | ✅ | The subprocess test; QA also ran it by hand |
| **AC3:** the CLI tests make no live model call | ✅ | Every `main` test injects a `runner`. The one test through the real `run` uses an unconfigured builder and a client factory that fails the test if it is called |
| DoD-1 to DoD-6 | ✅ | §4 above; every new `src` branch is tested; the docs test passes; this file |

The AC1 cases, row by row:

| Code | Cases |
| :--- | :--- |
| 5 | Credentials, rates and effort, and again through `main` |
| 2 | The session fails to open (three ways, and with both session error types); fatal mid-run (2b); fatal at the Scout (2c); the session dies as it closes |
| 6 | A provider error after a save; a failure on the first turn; the builder raises |
| 3 | The Scout is never called; an invalid scope is never corrected; a Scout failure is never retried (4b); the close-time edge |
| 1 | No candidates; a retry that succeeds (4c) |
| 4 | Persistence fails |
| 0 | One draft saved; zero drafts saved |

## 6. Decisions and deviations

**Binding decisions applied:**
* **P13** (Q11 = A): `PARSER_ERROR` needs a Supervisor that ended on its own. A session lost at the Scout gives 2. A Scout failure that is never retried successfully gives 3. P13 is recorded in plan §2 and `SPECIFICATIONS.md` §6.10, §7.6 and §8.3.
* **Q13 = A**: a standing approval. When a P-decision is added, the implementer updates only the "P1 to Pn" range text in `CLAUDE.md` and the three `.claude/agents/*.md` files. It was applied here for P13.
* **Q10 = A**: the Iteration 13 carry-over items. A1–A5 are applied. QA-m6 is **partly** applied: the failed-call phrasings, "polish its headline" and "the third violation" are not covered.

**Decisions (§1.5, or settled from the sources in the pre-flight):**
* **`RunState` is created after the session opens,** as in §4's "Init" box. The two early exits (`CONFIG_ERROR`, and a session that fails to open) return a `RunState` that only carries the result, and do not call `finalise_run`; nothing was saved or spent.
* **"Run completed" is logged on every path,** with zero totals on an early exit.
* **F1:** the Supervisor's telemetry after a provider error is recovered from its agent's metrics (plan Iteration 11: `None` only when no metrics could be read). The helper is made public in `src/tools.py` (`failed_call_telemetry`) and not duplicated.
* **F2:** `supervisor_summary` holds the summary exactly as returned, `""` after a typical fatal stop. It is `None` when the Supervisor raised.
* **Most scripted runs give the Supervisor the effort `"low"`,** so the test builder can tell it from QA-Legal; one test covers the defaults, identifying the Supervisor by its system prompt.
* **`main` prints only ASCII lines:** the exit code, the candidates considered, each saved draft and each failure. The Supervisor's summary, which may be non-ASCII, goes to the log only. `main` raises `RuntimeError` if a runner ever returns no exit code.
* **`build_config` also resolves a `log_dir` override,** since §7.5 says every path is made absolute.
* **Log wording** is as given in the implementer's record in `FIXES.md`. The D-I fields are all present.

**Deviations and known limits:**
* **The plan's Iteration 14 exit-code row,** "The Supervisor finishes and `state.scope is None`" (plan l.712), is superseded by P13 in §2. It is left as written, because this workflow edits only plan §2 and §3.
* **Known limit (Q12 = A).** If the SDK's `MCPClient.stop()` raises a plain `RuntimeError` as the session closes, the error escapes `run`. This happens when its background task died after the handshake. In that case the saved drafts are not rendered, "Run completed" is not logged, and the CLI exits 1. A plain subprocess kill does not reach this path; it surfaces as `MCPConnectionError` at the next listing. No code was changed (Approach 1 parity).
* **Known limit.** `finalise_run`'s `ValueError` for an unpriced model escapes `run` and `main` (exit 1), as in Approach 1. The shipped rates cannot trigger it, and a test pins it.
* **Known limit.** argparse usage errors exit 2, the same number as `MCP_ERROR`, as in Approach 1. A usage error is not a run.
* **Known limit (QA-m4).** The redaction-key WARNING goes to stderr, not the log file, because it is evaluated before `configure_logging` (Approach 1 parity).
* **Not applied (architect m5, optional).** `run`'s docstring says the only exception let through is the unpriced-model `ValueError`. A builder `RuntimeError`, a `KeyboardInterrupt` and the Q12 case also escape, by design. Only the sentence is inaccurate; the behaviour is correct.

## 7. Review

The pre-flight was held once (Q11), and review used two rounds.

**Round 1.**
* **Architect: CHANGES REQUESTED.**
  * **m1 (required):** dead `"-" if code is None` fallbacks in `_log_run_completed`. **Resolved.**
  * **m2:** `_SESSION_ERRORS` duplicated `_FATAL_ERRORS`. **Resolved** with the shared public `SESSION_ERRORS`.
  * **m3:** a test docstring overclaimed. **Resolved.**
  * **m4:** a test read the private `_connected` attribute. **Resolved:** it now uses the public `MCPClientNotConnectedError` after close.
  * **Q12** (Needs a decision): the close-time plain `RuntimeError`. The user chose A, a known limit.
* **QA: FAIL.**
  * **QA-M1 (Major):** a parametrize built `ReasoningSettings()` at import time and read a real `.env`. **Resolved.**
  * **QA-m1:** three missing `except`-width tests. **Resolved.**
  * **QA-m2 to m7:** record-only or optional. QA-m5 and QA-m6 were applied as wording. QA-m7, the stale range text in four harness files, was covered by **Q13**, which the user approved.

**Round 2.**
* **Architect: APPROVED.** One optional item, m5, was left unapplied (§6).
* **QA: PASS**, with no new findings. It re-verified QA-M1 with a populated `.env`, and killed seven mutations of the fixes.
