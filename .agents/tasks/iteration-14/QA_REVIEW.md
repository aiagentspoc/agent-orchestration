# Iteration 14 — QA review, round 1

**Verdict: CHANGES REQUIRED (FAIL for this round).** One Major finding must be fixed: QA-M1, a test-isolation leak that fails the default suite on a machine with a `.env` effort override. Everything else is Minor, and several Minor items are optional. All three acceptance criteria are met, the exit-code mapping is correct and well pinned, and no test can reach a real model.

## What I ran

| Command | Result |
| :--- | :--- |
| `uv run pytest -q` | **1408 passed**, 0 failed, 0 errors, 0 warnings, in 41.35 s |
| `uvx ruff check src tests --no-cache` | All checks passed |
| `uv run pytest -m live --collect-only -q` | No tests collected (1408 deselected); live tests arrive in Iteration 16 |
| `uv run python -m src.cli --help` | Exit 0; ASCII; prints `PROMPT`, `--max-drafts N`, `--log-level {DEBUG,INFO,WARNING,ERROR}`, `--drafts-dir DIR` |
| HEAD `35b4e92` collection (a `git archive` copy) | 1244 tests, which matches the baseline |

**Test counts.** The claimed 1408 is right for the moment it was claimed. The suite now collects 1409, because the docs test parametrises over every task record and the architect's `ARCHITECT_REVIEW.md` adds one case. This file will add one more, so the count at commit time will be 1410. Per file, against HEAD:

| File | HEAD | Now |
| :--- | :---: | :---: |
| `tests/test_integration/test_app.py` | — | 38 |
| `tests/test_unit/test_app.py` | — | 79 |
| `tests/test_unit/test_cli.py` | — | 22 |
| `tests/test_unit/test_isolation.py` | — | 4 |
| `tests/test_unit/test_supervisor.py` | **120** | 138 |
| `tests/test_unit/test_annotations.py` | — | +2 |
| `tests/test_unit/test_docs_consistency.py` | 244 | 246 |

The report says the Supervisor file went from "121 → 138". The real baseline is 120, so the file gained 18 tests, not 17 (QA-m2).

**Mutations.** I ran 22 mutations on a scratch copy and deleted it afterwards. Each was run against the four new test files.
- **18 killed:**
  - P13 removed (the literal §7.6 rule);
  - `session_lost` never set;
  - no `log_context`;
  - the summary never stored;
  - no `FatalStopHook`;
  - `finalise_run` called twice;
  - the Writer override ignored;
  - the Scout's effort made overridable;
  - the listed tool count replaced by 0;
  - F1 telemetry dropped;
  - CONFIG_ERROR mapped to 2;
  - `main` returning the enum;
  - the fast key redacted;
  - `drafts_dir` left unresolved;
  - no redaction key;
  - the prompt stripped;
  - no `configure_logging`;
  - the conftest reverted to its old pin.
- **1 equivalent mutant:** `no_candidates` without the `scope is not None` term. With `scope is None`, one of 3, 2 or 6 always holds and outranks 1.
- **3 survived** (QA-m1):
  - the configuration `except` widened to `Exception`;
  - the Supervisor `except` widened to `BaseException`;
  - `MCPClientNotConnectedError` dropped from `_SESSION_ERRORS`.

**Isolation check (AC3).** I put a populated `.env` (example.invalid endpoints, fake keys, a cost rate and two effort overrides) at the root of a scratch copy and ran the suite there.
- No test reached a model.
- The `CredentialManager`, `CostSettings` and `ReasoningSettings` pins hold, and `test_isolation.py` pins them.
- One test failed, which is QA-M1: `test_four_models_are_built_once_each_on_their_bindings_and_efforts[defaults]`.
- Ten docs tests also failed there, but only because the copy has no sibling `../code-orchestration/`; that is an artefact of the scratch location, not a defect.

**Hygiene.**
- No `--quiet --directory` substrate process was left after any run; the other `fastmcp` processes are the harness's own MCP servers.
- The repository's `drafts/` and `logs/` are empty.
- pytest printed no warnings.

## Gate matrix

| Gate | Topic | Status | Notes |
| :--- | :--- | :---: | :--- |
| 1 | Strict TDD | ✅ | The report gives a Red for each behaviour, and a recorded mutation for each test that passed at once; my 18 kills confirm the tests can fail. Three narrow `except` tuples are not pinned (QA-m1) |
| 2 | Zero-token testing | ❌ | No live call is possible: every `run` uses a scripted, failing or unconfigured builder, and every `main` gets a runner. But one parametrize argument, `ReasoningSettings()` at `tests/test_integration/test_app.py` l.876, is built at collection time, outside the autouse isolation, so it reads a real `.env` (QA-M1) |
| 3 | Pydantic v2 contracts | ✅ | No new model. The private dataclasses stay inside `src/app.py`, and no `dict[str, Any]` crosses a module. `failure_record` and `failed_call_telemetry` are made public with no change in behaviour |
| 4 | Guardrails and attempt cap | n/a in this iteration | `draft_ceiling` through `--max-drafts 1` is exercised end to end (l.927–949) |
| 5 | Strands integration and telemetry | ✅ | `FatalStopHook` is on the Supervisor only, and there is one `LoggingHooks` (one "Supervisor turn completed" per turn). F1: 60 tokens are recovered after a provider error, and there is no entry when no agent was built. The ledger labels carry the resolved efforts |
| 6 | No article text for the Supervisor | ✅ | The user turn is the date and the prompt alone (l.952–962). A4's escaped-form leak check is proven by `test_leaked_article_fields_catches_article_text_in_a_tool_result`; `for_supervisor` uses `ensure_ascii=False`, as the check does |
| 7 | Drafts and logging | ✅ | The dated `run_YYYYMMDD.log` carries `run_id`, `doc_id` and `attempt` on every line (I checked it through `main`). Every D-I event this iteration adds is asserted. The key is redacted. Drafts are rendered after the session closes |
| 8 | Python and subprocess safety | ✅ | Annotations are complete (`test_annotations` covers `src.app` and `src.cli`), `pathlib.Path` is used throughout, and the live-substrate session is closed (`_connected is False`). No orphan process |

## Acceptance criteria and Definition of Done

| # | Criterion | Status | Evidence |
| :--- | :--- | :---: | :--- |
| AC1 | Every exit-code row has a test | ✅ | See the table below. Each P6/P13 combination is pinned by `test_p13_parser_error_needs_a_supervisor_that_ended_on_its_own` (the 7 brief rows), and all 64 combinations are covered. Every row except the 6-row asserts its failure stages exactly, so a "script exhausted" exit 6 cannot hide |
| AC2 | `--help` prints the four arguments | ✅ | I ran it; the subprocess test checks it in ASCII, and removing the `__main__` guard fails it |
| AC3 | The CLI tests make no live model call | ✅ | Every `main` test injects a `runner`; the one real-`run` test uses `_unconfigured_model_builder` and a factory that fails the test if called. The `.env` experiment shows no default construction can resolve credentials under test |
| DoD-1 | Suite passes | ✅ | 1408 passed |
| DoD-2 | Ruff clean | ✅ | All checks passed |
| DoD-3 | No live call | ✅ | As AC3. QA-M1 can fail a test, but it cannot spend a token |
| DoD-4 | Every new `src` function tested | ✅ | All functions are exercised. The unreachable `None` fallbacks in `_log_run_completed` are the architect's m1; the unpinned `except` widths are QA-m1 |
| DoD-5 | Docs test passes | ✅ | Passes, with 246 cases now |
| DoD-6 | Record written | n/a | It is the orchestrator's, at Stage 4 |

**AC1 row by row,** end to end through `run`:

| Row | Code | Tests (`tests/test_integration/test_app.py`) |
| :--- | :---: | :--- |
| Credentials, rates or effort unresolved | 5 | l.245, l.255, l.272, and `main` returns 5 (`test_cli.py` l.249) |
| Session fails to open | 2 | `__enter__` fails (l.301); the factory raises (l.313); the root's listing fails (l.333) |
| 2b: fatal stop mid-run | 2 | l.730: the first draft is rendered, the exit is never 6, and there is one Supervisor ledger entry |
| 2c: fatal stop at the Scout | 2 | l.762: `scope is None`, the Scout spent 0 turns, `tool=scout_tool` is in "Fatal abort triggered", the summary is `""` |
| Session lost at close | 2 or 3 | l.437 (2, the draft still rendered); l.463 (3: P13 + P6 combined with the lost session) |
| Provider or SDK error | 6 | l.366 (after a save, F1); l.394 (first turn, `scope is None`, still 6); l.412 (the builder raises, no entry) |
| Ended without the Scout, or with an invalid scope | 3 | l.640, l.651 |
| 4b: a Scout failure never retried | 3 | l.665 |
| 4c: the retry succeeds | 1 | l.683 |
| Zero candidates | 1 | l.623 |
| Render failure | 4 | l.697 |
| Otherwise | 0 | One draft (l.164); zero drafts (l.714) |

## Iteration 13 carry-over (checked against `iteration-13/FIXES.md`)

| Item | Status | Evidence |
| :--- | :---: | :--- |
| A1 / QA-m4 | ✅ | `[^\s,]+` is in both patterns. The guard `"review " + ", " * 2000 + "x"` takes 0.3 ms, and 10,000 characters of `" ,"` take 0.7 ms |
| A2 | ✅ | The stems and suffix are exactly as specified, the comment is corrected, and the six probes are added |
| A3 | ✅ | `_NEGATED_VERB` is used for the article check only. `_NEGATED_BEFORE` stays for the Writer-feedback check, and "You never write feedback for the Writer." still gives `[]` |
| A4 / QA-m5 | ✅ | The escaped-form check runs over the tool-result texts, its proof test returns `['headline', 'article_body']` on an injected leak, and the key check is kept |
| A5 | ✅ | The dead alternative is dropped; "If qa_tool returns an error, call it again." is still caught |
| QA-m6 (optional) | ✅ partly | The cheap wins are in: number words, `exceed`, and three Writer-briefing phrasings. The failed-call phrasings ("If qa_tool raises…", "Should the Scout time out…", "If QA-Legal cannot audit…"), "polish its headline" and the ordinal "the third violation" are not covered. That is acceptable for an optional item, but "resolved" overstates it (QA-m5) |
| Real prompt | ✅ | Every check gives `[]` at ceilings None, 1, 2 and 3, which I ran myself |

## Findings

### 🔴 Blocker
None.

### 🟡 Major
- **QA-M1: a collection-time `ReasoningSettings()` reads a real `.env`.**
  - **Where:** `tests/test_integration/test_app.py` l.872–888.
  - **Problem:** `ReasoningSettings()` and `ReasoningSettings(...)` are built when the parametrize decorator runs, at import time. That is before `_isolate_environment` pins `env_file=None`, so a `.env` in the working directory is read.
  - **Effect:** a developer `.env` with `HSE_MODEL_WRITER_REASONING_EFFORT` (or the Supervisor or QA override) fails the default suite. Iteration 16's README tells the user to create exactly that file. I reproduced it:
    ```text
    E       AssertionError: assert [('gpt-5-mini...4', 'medium')] == [('gpt-5-mini...4', 'medium')]
    E         At index 1 diff: ('gpt-5.4', 'low') != ('gpt-5.4', 'high')
    FAILED tests/test_integration/test_app.py::test_four_models_are_built_once_each_on_their_bindings_and_efforts[defaults]
    ```
  - **Severity:** no token is spent, but it breaks Gate 2's isolation and DoD-1 on a configured machine. The fix is in `FIXES.md`.

### 🟢 Minor
- **QA-m1: the widths of three `except` clauses are not pinned.** These mutations survive:
  - the configuration `except (ValidationError, ValueError)` widened to `except Exception` (the brief's "an `AssertionError` from a scripted builder must surface");
  - the Supervisor `except Exception` widened to `BaseException`;
  - `MCPClientNotConnectedError` dropped from `_SESSION_ERRORS`.
- **QA-m2: the report misstates one baseline count.**
  - It says `test_supervisor.py` went from 121 to 138; HEAD has 120, so 18 tests were added. The headline 1408 is correct, so this is a record error, not a run error.
  - The walkthrough should use 120 → 138, and the suite count at commit time (1410 once both review files exist).
- **QA-m3: I concur with the architect's Q12** on close-time errors. The close-time tests inject `MCPConnectionError` through `fail_exit_with`, which the real `HSEMockMCPClient.stop()` never raises; the realistic `RuntimeError` escapes `run`. Nothing is added here beyond Q12.
- **QA-m4 (optional, record only):** `_resolve_redaction_key()` runs as an argument to `configure_logging`, so its WARNING and traceback go to stderr through Python's last-resort handler and never reach the log file. It is a verbatim port of Approach 1's `main` (orchestrator.py l.1440), so this is parity. Note it in the walkthrough; do not change it.
- **QA-m5 (optional):** in `FIXES.md` § Implementation, QA-m6 reads "resolved, optional". It is partly applied (see above). Reword it to "partly applied", or add the remaining probes.
- **QA-m6 (optional):** `_conditions_holding` in `tests/test_unit/test_app.py` l.78–91 mirrors `_exit_code` line for line, so the 64-case test checks the code against a copy of itself. The two explicit tables are the independent oracle. Keep the 64 cases if you wish, but do not count them as independent evidence.
- **QA-m7 (orchestrator, not the implementer):** "P1 to P12" ("P1–P12") is still in `CLAUDE.md` l.14, `.claude/agents/architect.md` l.19, `.claude/agents/implementation.md` l.17 and `.claude/agents/qa.md` l.19. The brief's D3 grep check is therefore unmet. These are harness files; the implementer rightly did not edit them on an agent's say-so. The orchestrator should apply the one-line range edits only with the user's consent, as under the Q6 and Iteration 11 precedent, or record the deviation.

## Remediation

Precise instructions are in `.agents/tasks/iteration-14/FIXES.md` under `## QA — round 1`.

---

# Iteration 14 — QA review, round 2

**Verdict: PASSED.** QA-M1 and QA-m1 are fixed, and I verified each fix myself. The architect's m1 to m4 and the optional QA-m5 and QA-m6 are applied as the report states. All three acceptance criteria and every Definition of Done row still hold. No new finding. Q12 = A (a known limit) and Q13 = A (applied) are settled by the user, and neither is raised again here.

## What I ran

| Command | Result |
| :--- | :--- |
| `uv run pytest -q` | **1413 passed**, 0 failed, 0 errors, 0 warnings, in 42.09 s |
| `uvx ruff check src tests --no-cache` | All checks passed |
| `uv run pytest -m live --collect-only -q` | No tests collected (1413 deselected) |
| `uv run python -m src.cli --help` | Exit 0; prints `PROMPT`, `--max-drafts N`, `--log-level {DEBUG,INFO,WARNING,ERROR}`, `--drafts-dir DIR` |

**Test counts.** The claimed 1413 is right. `tests/test_integration/test_app.py` went from 38 to 41: the builder-defect test, the interrupt test, and a second case of the parametrized client-factory test. The other new files are unchanged: `test_unit/test_app.py` 79, `test_cli.py` 22, `test_isolation.py` 4. This section adds no file, so the count at commit time stays 1413 unless another record is added to this folder.

## QA-M1: verified

- **Setup.** I used a scratch working directory with a populated `.env`: `example.invalid` endpoints, fake keys, one cost rate, and effort overrides for the Writer (`low`), QA-Legal (`high`) and the Supervisor (`low`). I ran the repository's own tests from that directory, with `uv run --project <repo> pytest <repo>/tests`.
- **The `.env` is read.** An unpinned `ReasoningSettings()` built in that directory printed `writer='low' qa_legal='high' supervisor='low'`, so the setup would expose a collection-time read.
- **Green.** The whole suite passed there: 1413 passed, 0 failed.
- **Red, by mutation.** On a scratch copy holding the same `.env`, I re-introduced a module-level `ReasoningSettings()` used by the `defaults` case. It failed `test_four_models_are_built_once_each_on_their_bindings_and_efforts[defaults]`. So the test catches the leak, and the fix is what makes it pass.
- Both scratch directories and both `.env` files are deleted, and the repository has no `.env`.

## QA-m1 and the architect's items: verified by mutation

There were seven mutations on a scratch copy. Each was applied alone, run against the four Iteration 14 test files, then reverted; the copy is deleted.

| Mutation | Result | Killing test |
| :--- | :---: | :--- |
| Configuration `except (ValidationError, ValueError)` → `except Exception` | Killed | `test_a_model_builder_defect_is_not_a_configuration_failure` |
| `_supervise` `except Exception` → `except BaseException` | Killed | `test_an_interrupt_during_the_supervisor_leaves_run_and_still_closes_the_session` |
| `src/tools.py` `SESSION_ERRORS` narrowed to `(MCPConnectionError,)` | Killed | `test_a_client_that_cannot_be_built_exits_mcp_error[MCPClientNotConnectedError]` |
| `src/app.py` catches only `SESSION_ERRORS[:1]` | Killed | the same case |
| m4: `HSEMockMCPClient.stop()` leaves the client marked connected | Killed | `test_a_run_over_the_live_substrate_opens_one_session_and_closes_it` |
| m1: "Run completed" logs a fixed `0` in place of `int(code)` | Killed | `test_an_early_exit_still_logs_run_completed_with_nothing_spent[configuration]` |
| QA-M1 reverted: settings built at import time | Killed | `test_four_models_are_built_once_each_on_their_bindings_and_efforts[defaults]` |

Code reading:
- **m1.** `_run_once` returns `tuple[RunState, ExitCode, RunFinalisation | None]`, and `_log_run_completed` has no `None` fallback for the code.
- **m2.** `_SESSION_ERRORS` and `_FATAL_ERRORS` are gone from `src/` and `tests/`; `SESSION_ERRORS` is in `src/tools.py` `__all__` and is imported by `src/app.py`.
- **m3.** The docstring is fixed.
- **m4.** `_connected` is no longer read by `tests/test_integration/test_app.py`. The one remaining test read, `tests/support/scripted.py` l.333, is the offline client's own setup from earlier iterations.
- **The `effort=low` lines.** They appear in the mutation logs because of the test's own `SUPERVISOR_EFFORT = "low"` constant (l.70), not the scratch `.env`.

## Gate matrix

| Gate | Topic | Status | Notes |
| :--- | :--- | :---: | :--- |
| 1 | Strict TDD | ✅ | A Red is reported for each fix, and all seven of my mutations are killed. The three `except` widths are now pinned |
| 2 | Zero-token testing | ✅ | QA-M1 is fixed: the suite passes from a directory whose `.env` an unpinned settings object does read. No test can reach a model |
| 3 | Pydantic v2 contracts | ✅ | No model changed. `SESSION_ERRORS` is a typed `Final` tuple of exception types |
| 4 | Guardrails and attempt cap | n/a in this iteration | Unchanged since round 1 |
| 5 | Strands integration and telemetry | ✅ | Unchanged; the F1 recovery and the ledger tests still pass |
| 6 | No article text for the Supervisor | ✅ | Unchanged since round 1 |
| 7 | Drafts and logging | ✅ | "Run completed" logs the real code on every path, as the m1 mutation proves. The repository's `drafts/` and `logs/` are empty |
| 8 | Python and subprocess safety | ✅ | The closed session is checked through the client's public behaviour. No `--quiet --directory` substrate process is left; the `uv run --directory … fastmcp` processes are the harness's own MCP servers. pytest prints no warnings |

## Acceptance criteria and Definition of Done

| # | Criterion | Status | Evidence |
| :--- | :--- | :---: | :--- |
| AC1 | Every exit-code row has a test | ✅ | The round 1 row table still holds. Row 5 now also has a test for the opposite case, a builder defect that is not CONFIG_ERROR. Row 2 covers both lost-session types at the factory |
| AC2 | `--help` prints the four arguments | ✅ | Run above |
| AC3 | The CLI tests make no live model call | ✅ | Unchanged injection, and the suite passes with a populated `.env` in the working directory |
| DoD-1 | Suite passes | ✅ | 1413 passed |
| DoD-2 | Ruff clean | ✅ | All checks passed |
| DoD-3 | No live call | ✅ | As AC3 |
| DoD-4 | Every new `src` function tested | ✅ | m1's dead branches are removed, and the `except` widths are pinned |
| DoD-5 | Docs test passes | ✅ | Within the 1413 |
| DoD-6 | Record written | n/a | The orchestrator's, at Stage 4 |

Q13's range edits are applied: a grep for `P1 to P12`, `P1–P12` and `P1-P12` in every `.md` outside `.agents/tasks/` finds nothing, and each of the four harness files has a one-line diff.

## Findings

- 🔴 Blocker: none.
- 🟡 Major: none.
- 🟢 Minor: none new. For the walkthrough, the record-only items still stand: QA-m2 (`test_supervisor.py` 120 → 138), QA-m4 (the redaction-key WARNING goes to stderr; Approach 1 parity), and Q12 = A (a known limit).
