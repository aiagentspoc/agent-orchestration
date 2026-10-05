# Iteration 14 — Fixes

## Implementation

Iteration 13 carry-over (Q10 = A), applied test-first in `tests/test_unit/test_supervisor.py`. `src/supervisor.py` and the Supervisor prompt are unchanged. After every item, the real prompt still gives `[]` from every check at ceilings None, 1, 2 and 3. The count table of `test_article_work_instructions_catch_instructions_but_not_their_negation` still holds.

- **A1 / QA-m4 (resolved).** `_ARTICLE_WORK` and `_NEGATED_BEFORE` now match words with `[^\s,]+` in place of `\S+`. The guard test is `test_article_work_check_is_linear_on_comma_dense_text`.
  - **Red:** the guard run under the old pattern was killed by a 40 s timeout with no result.
  - **Timing on `"review" + " ," * n`:** old 31.7 ms at n=40 and 927.3 ms at n=80; new 0.0 ms at both.
- **A2 (resolved).** The verbs are now held as stems, and the suffix is `(?:e|es|ed|d|s|ing|ten)?`. The six inflection probes went from failing to passing.
- **A3 (resolved).** `_NEGATED_VERB` was added, and `_affirmative_matches` now takes its negation pattern. The article check uses `_NEGATED_VERB`; the Writer-feedback check keeps `_NEGATED_BEFORE`. The two probes "Never save before you review the draft." and "Don't save until you read the draft." went from failing to passing.
- **A4 / QA-m5 (resolved).** The text check now runs over the tool-result texts, in their JSON-escaped form, through `_leaked_article_fields`. The key check is kept.
  - **Red:** `test_leaked_article_fields_catches_article_text_in_a_tool_result` caught `['headline']` and missed `article_body`.
- **A5 (resolved).** The dead `\breturns an error\b` alternative was dropped. "If qa_tool returns an error, call it again." is still caught. A mutation that removed `\berrors?\b` as well failed that probe.
- **QA-m6 (partly applied, optional).** Not covered: the failed-call phrasings, "polish its headline" and "the third violation".
  - The changes:
    - number words (`_COUNT`) in the tool-call and violation bounds;
    - `exceed`;
    - `brief the Writer`, `explain to the Writer` and `(?:guidance|comments) (?:to|for) the Writer` in `_WRITER_FEEDBACK`.
  - **Red:** 7 new probes failed before the change and pass after it. The control "An initial draft plus up to two revisions." gives 0.

## Architect — round 1

Verdict: **APPROVED WITH RESERVATIONS.** One fix is required (m1), three are optional (m2–m4), and one item needs the user's decision (N1). It does not block the commit. The full review is in `ARCHITECT_REVIEW.md` in this folder.

Ruff, `uvx ruff check src tests --no-cache`: 0 in-scope findings (blocking) and 0 pre-existing debt (deferred). Pytest: 1408 passed.

### 🏛️ Architecture & System Boundaries

None blocking. The control flow, the single `with` session, the one `finalise_run`, the P6 and P13 mapping, benchmark parity and D-F all hold. See N1 under "Needs a decision" for the one lifecycle risk.

### 🧹 Code Quality & Conventions

- **m1 (🟢 Minor, required): remove the unreachable `None` fallbacks in `_log_run_completed`.**
  - **Where:** `src/app.py` l.346–364.
  - **Why:** `state.exit_code` is always set by the time this function runs, by `_ended_early` and by the end of `_run_once`. So `"-" if code is None else int(code)` and `"-" if code is None else code.name` (l.355–356) are dead branches that no test exercises, which goes against DoD-4 and Pillar 8.
  - **Change:**
    - `_run_once` returns the code it set, typed as `ExitCode`, alongside the state. For example, its return type becomes `tuple[RunState, ExitCode, RunFinalisation | None]`; both early-exit returns pass `ExitCode.CONFIG_ERROR` or `ExitCode.MCP_ERROR`, and the end of the function passes the `_exit_code(...)` result, which it still stores on `state.exit_code`.
    - `_log_run_completed(state, code: ExitCode, finalisation, wall_clock_seconds)` logs `int(code)` and `code.name` with no fallback.
    - `run` unpacks the three values.
    - Any equivalent restructure that leaves no unreachable branch is fine.
  - **Test:** none new is needed. The existing "Run completed" tests (`tests/test_integration/test_app.py` l.527–549 and l.589–607) must stay green.
- **m2 (🟢 Minor, optional): `_SESSION_ERRORS` duplicates `src/tools.py` l.94 `_FATAL_ERRORS`.**
  - **Where:** `src/app.py` l.60–61.
  - **Change:** either export one public tuple from `src/tools.py`, for example `SESSION_ERRORS` in `__all__`, and import it in `src/app.py`, as was done for `failure_record`; or leave it as it is. The behaviour is identical either way.
- **m3 (🟢 Minor, optional): trim an overclaiming test docstring.**
  - **Where:** `tests/test_integration/test_app.py` l.837.
  - **Change:** drop "and the draft ID". This test saves no draft; the SUCCESS test at l.179 pins the draft ID's date.
- **m4 (🟢 Minor, optional): note a private-attribute read.**
  - **Where:** `tests/test_integration/test_app.py` l.1028, `clients[0]._connected`.
  - **Change:** none required, since P9 freezes the client. A one-line comment saying why the private attribute is read would help a later reader.

### ❓ Needs a decision

## Q12 (Iteration 14): Should a session that fails as it closes, after the Supervisor has returned, still render the saved drafts and exit MCP_ERROR when the SDK raises a plain RuntimeError?
**Background:** Strands 1.55.1 `MCPClient.stop()` raises `RuntimeError("Connection to the MCP server was closed")` when its background session task failed after the handshake (`strands/tools/mcp/mcp_client.py` l.713–716, l.1531–1544). `HSEMockMCPClient.stop()` maps nothing, and P9 forbids changing it. That error is not in `src/app.py`'s `_SESSION_ERRORS`, so it would escape the `with` and skip `finalise_run`, so drafts already saved would not be rendered. It would also skip "Run completed", and `main` would exit 1, the NO_UPDATES number. That contradicts §7.6 ("reconciliation and rendering always run once a `RunState` exists"). The close-time tests cover the branch with `MCPConnectionError`, which the real client never raises at close. An architect probe on the local substrate showed that a plain subprocess kill does not reach this path: it surfaces as `MCPConnectionError` at the next listing, and `stop()` returns cleanly. So D-D's fatal stop and rendering work, and the risk is latent. Approach 1 has the same exit-code exposure, but it had already written its drafts inside the `with`.
**Recommendation:** B. It upholds §7.6's "rendering always runs" with a small change that can be tested with `OfflineSubstrateSession(fail_exit_with=RuntimeError(...))`. It does not touch `mcp_client.py` (P9), and the mapping follows §6.10's own wording for `MCP_ERROR` ("died mid-run"). This does not block committing Iteration 14. If B is chosen, apply it test-first as a follow-up, before or in Iteration 15.
**Options:** A. Record it as a known limit in the walkthrough and change no code (Approach 1 parity for the exit code) · B. In `_run_once`, treat any `Exception` raised while closing the session, once the `with` body has completed and a `RunState` exists, as a lost session: record a `FailureRecord(stage="mcp_session")` and set `session_lost=True`, so `finalise_run` still renders and the run exits `MCP_ERROR` under P6. An exception raised inside the body keeps propagating as it does today · C. Re-raise after rendering: call `finalise_run` in a `finally` and let the error escape, keeping the drafts but leaving the exit code unmapped


## QA — round 1

Verdict: **CHANGES REQUIRED.** There is one Major item (QA-M1), which must be fixed, plus one required Minor item (QA-m1), and the rest are optional. The full review is in `QA_REVIEW.md` in this folder.

Real numbers:
- `uv run pytest -q`: 1408 passed, 0 failed. The suite now collects 1409, because the docs test parametrises over the task records.
- `uvx ruff check src tests --no-cache`: all checks passed.
- AC1, AC2 and AC3 are met.

### 🧪 Quality Assurance & Test Verification

- **QA-M1 (🟡 Major, required): a collection-time `ReasoningSettings()` reads a real `.env`.**
  - **Where:** `tests/test_integration/test_app.py` l.872–888, the parametrize of `test_four_models_are_built_once_each_on_their_bindings_and_efforts`.
  - **Why:** the decorator builds `ReasoningSettings()` at import time, before the autouse `_isolate_environment` pins `env_file=None`. So a `.env` in the working directory is read. Reproduced with `HSE_MODEL_WRITER_REASONING_EFFORT=low` in a `.env` at the root of a scratch copy:
    ```text
    E       AssertionError: assert [('gpt-5-mini...4', 'medium')] == [('gpt-5-mini...4', 'medium')]
    E         At index 1 diff: ('gpt-5.4', 'low') != ('gpt-5.4', 'high')
    FAILED tests/test_integration/test_app.py::test_four_models_are_built_once_each_on_their_bindings_and_efforts[defaults]
    ```
  - **Fix:** parametrize over the override keywords, a `dict[str, str]` (`{}` for the defaults case, and the three `HSE_MODEL_*_REASONING_EFFORT` entries for the overrides case). Build `settings = ReasoningSettings(**overrides)` inside the test body, where the pin is active.
  - **Verify:**
    - Red: with a `.env` holding `HSE_MODEL_WRITER_REASONING_EFFORT=low` in the working directory, the defaults case fails before the fix.
    - Green: it passes after the fix.
    - Remove the `.env` afterwards. Use a scratch copy or `tmp_path` with `monkeypatch.chdir`, never the repository root.
  - **Optional guard:** add a test to `tests/test_unit/test_isolation.py` that asserts no `ReasoningSettings`, `CostSettings` or `CredentialManager` instance is built at module level in `tests/`. A simple AST scan of decorator and module-level calls would do. This is optional.
- **QA-m1 (🟢 Minor, required): pin the width of the three `except` clauses in `src/app.py`.** Each of these mutations leaves all 143 new tests green:
  - `except (ValidationError, ValueError)` → `except Exception` (l.174);
  - `except Exception` → `except BaseException` (l.260);
  - `(MCPConnectionError, MCPClientNotConnectedError)` → `(MCPConnectionError,)` (l.61).

  Add three tests to `tests/test_integration/test_app.py`:
  1. A `model_builder` that raises `RuntimeError("builder defect")` makes `run` raise `RuntimeError` (`pytest.raises`). It must not exit 5. This is the brief's "an `AssertionError` from a scripted builder must surface".
  2. Monkeypatch `src.app.run_supervisor` to raise `KeyboardInterrupt()`. Then `pytest.raises(KeyboardInterrupt)` out of `run`, and the offline session's `events == ["enter", "exit"]`.
  3. Parametrize `test_a_client_that_cannot_be_built_exits_mcp_error` over `MCPConnectionError` and `MCPClientNotConnectedError`; both must exit 2.

  Red for each: apply the mutation above and see the new test fail.
- **QA-m2 (🟢 Minor, for the walkthrough): the baseline count.** `tests/test_unit/test_supervisor.py` has 120 tests at HEAD `35b4e92`, not 121. It now has 138, so 18 were added. Record 120 → 138. Record the suite count as it stands at commit time; it rises by one for each new `.md` file in this folder (1410 with both review files).
- **QA-m3 (🟢 Minor, record only): close-time errors.** I concur with the architect's Q12; nothing is added here.
- **QA-m4 (🟢 optional, record only):** the redaction-key WARNING goes to stderr, not to the log file. `_resolve_redaction_key()` is evaluated before `configure_logging` runs. This is Approach 1 parity (orchestrator.py l.1440), so record it as a known limit and change nothing.
- **QA-m5 (🟢 optional):** in `## Implementation` above, QA-m6 is described as "resolved". It is partly applied: the failed-call phrasings, "polish its headline" and "the third violation" are not covered. Reword it to "partly applied", or add those probes test-first. The real prompt must still give `[]`.
- **QA-m6 (🟢 optional):** `_conditions_holding` (`tests/test_unit/test_app.py` l.78–91) copies `_exit_code`'s logic. Either derive the oracle independently, for example from a per-code predicate table written from §7.6's wording, or note in its docstring that the two explicit tables are the independent check.
- **QA-m7 (🟢, for the orchestrator, not the implementer):** "P1 to P12" ("P1–P12") is still in four harness files:
  - `CLAUDE.md` l.14;
  - `.claude/agents/architect.md` l.19;
  - `.claude/agents/implementation.md` l.17;
  - `.claude/agents/qa.md` l.19.

  Apply the one-line range edits only with the user's consent (the Q6 and Iteration 11 precedent), or record the unmet D3 grep check as a deviation.

### ❓ Needs a decision

None from QA round 1. Q12 above, from the architect, covers the one lifecycle question I found.

## Implementation — fix round 1

Suite: `uv run pytest -q` 1413 passed (1410 before; +3 new test cases). `uvx ruff check src tests --no-cache`: all checks passed. No `.env` was left in the repository.

- **QA-M1 (resolved).** The parametrize of `test_four_models_are_built_once_each_on_their_bindings_and_efforts` now carries override keywords (`dict[str, str]`), and the test builds `ReasoningSettings(**overrides)` in its body, where the isolation pin is active.
  - **Red:** run from a scratch working directory holding a `.env` with `HSE_MODEL_WRITER_REASONING_EFFORT=low`, the `defaults` case failed: `At index 1 diff: ('gpt-5.4', 'low') != ('gpt-5.4', 'high')`.
  - **Green:** the same run passes both cases. The whole suite, run from that directory with that `.env`, gave 1410 passed. The scratch directory was deleted afterwards.
  - The optional AST guard was not added.
- **QA-m1 (resolved).** Three test cases in `tests/test_integration/test_app.py`. Each mutation was applied alone, killed exactly its test, and was reverted (`cmp` against a backup).
  - `test_a_model_builder_defect_is_not_a_configuration_failure`: a builder raising `RuntimeError("builder defect")` escapes `run`. Mutation `except (ValidationError, ValueError)` → `except Exception`: it failed.
  - `test_an_interrupt_during_the_supervisor_leaves_run_and_still_closes_the_session`: `run_supervisor` monkeypatched to raise `KeyboardInterrupt`; it escapes `run`, and the session's events are `["enter", "exit"]`. Mutation `except Exception` → `except BaseException` in `_supervise`: it failed (the interrupt was logged as a Supervisor failure).
  - `test_a_client_that_cannot_be_built_exits_mcp_error` is parametrized over `MCPConnectionError` and `MCPClientNotConnectedError`; both exit 2. Mutation narrowing the session tuple to `(MCPConnectionError,)`: the `MCPClientNotConnectedError` case failed. Re-run after m2 against the shared tuple in `src/tools.py`: it failed the same way.
- **Architect m1 (resolved, refactor).** `_run_once` returns `tuple[RunState, ExitCode, RunFinalisation | None]`: the two early exits return `CONFIG_ERROR` and `MCP_ERROR`, and the run end returns the `_exit_code(...)` result, still stored on `state.exit_code`. `_log_run_completed(state, code, finalisation, wall_clock_seconds)` logs `int(code)` and `code.name` with no fallback. The "Run completed" tests stayed green.
- **Architect m2 (resolved).** `src/tools.py`'s `_FATAL_ERRORS` became the public `SESSION_ERRORS`, in `__all__`. `src/app.py` imports it and drops its own `_SESSION_ERRORS` and the now-unused `mcp_client` error imports. The behaviour is unchanged.
- **Architect m3 (resolved).** The docstring at the clock test no longer claims the draft ID.
- **Architect m4 (resolved).** `HSEMockMCPClient` has no public "connected" property, but its public calls raise `MCPClientNotConnectedError` once the session is closed. So the live test now asserts that `clients[0].list_all_tools()` raises it, in place of reading `_connected`.
- **QA-m5 (resolved).** QA-m6 is reworded to "partly applied" in `## Implementation` above, naming the three uncovered phrasings. No probe was added and the Supervisor prompt is unchanged.
- **QA-m6 (resolved).** The docstring of `_conditions_holding` now says that it restates the helper's conditions and pins only the P6 maximum, and that the two explicit tables are the independent check.
- **Q13 = A (applied).** Only the range text changed: "P1 to P12" → "P1 to P13" in `.claude/agents/architect.md` l.19, `.claude/agents/implementation.md` l.17 and `.claude/agents/qa.md` l.19, and "P1–P12" → "P1–P13" in `CLAUDE.md` l.14. A grep for `P1 to P12`, `P1–P12` and `P1-P12` outside `.agents/tasks/` finds nothing.
- **Q12 = A.** No code change.
- **Record only:** QA-m2, QA-m3, QA-m4 and QA-m7 (QA-m7 is covered by Q13).

## Architect — round 2

Verdict: **APPROVED.** Every round 1 item is verified as resolved (m1–m4, QA-M1, QA-m1, QA-m5, QA-m6 and Q13):
* the `SESSION_ERRORS` rename changes no behaviour;
* the four harness diffs are one line of range text each.

One optional minor item is opened, m5, with no "Needs a decision" item. The full review is in `ARCHITECT_REVIEW.md`, round 2.

Ruff, `uvx ruff check src tests --no-cache`: 0 in-scope findings (blocking) and 0 pre-existing debt (deferred). Pytest: 1413 passed. Pyright on `src/app.py` and `src/tools.py`: 0 errors.

### 🏛️ Architecture & System Boundaries

None. Control flow, the single `with` session, the one `finalise_run`, the P6 and P13 mapping, parity and D-F are unchanged by the fixes.

### 🧹 Code Quality & Conventions

- **m5 (🟢 Minor, optional): `run`'s docstring overclaims which exceptions leave it.**
  - **Where:** `src/app.py` l.119–120.
  - **Why:** it says "the one exception let through is the `ValueError` of a ledger entry with no cost rate". Fix round 1's own tests now pin two more:
    - a model-builder `RuntimeError`, in `test_a_model_builder_defect_is_not_a_configuration_failure`;
    - a `KeyboardInterrupt`, in `test_an_interrupt_during_the_supervisor_leaves_run_and_still_closes_the_session`.

    The Q12 = A known limit is another. The behaviour is correct; only the sentence is inaccurate.
  - **Change:** replace the sentence "Nothing raises ``SystemExit``; the one exception let through is the ``ValueError`` of a ledger entry with no cost rate, which the shipped rates never leave." with, for example: "Nothing raises ``SystemExit``. Only unresolved settings and a lost session are mapped to exit codes; anything else is a defect and leaves ``run`` unchanged, for example a model-builder error, the ``ValueError`` of a ledger entry with no cost rate (which the shipped rates never leave), or a ``BaseException`` such as an interrupt."
  - **Test:** none. It is a docstring.
  - **Priority:** apply it only if a fix round 2 happens for another reason; it does not hold the commit.

### ❓ Needs a decision

None.


## QA — round 2

Verdict: **PASSED.** The full review is in `QA_REVIEW.md` in this folder, under "QA review, round 2".

Real numbers:
- `uv run pytest -q`: 1413 passed, 0 failed, 0 warnings.
- The suite also passes, at 1413, from a scratch working directory whose populated `.env` an unpinned `ReasoningSettings()` reads.
- `uvx ruff check src tests --no-cache`: all checks passed.
- AC1, AC2 and AC3 are met: 3 of 3.

### 🧪 Quality Assurance & Test Verification

- **QA-M1: verified closed.** Re-introducing a module-level `ReasoningSettings()` fails the `[defaults]` case when a `.env` is present, and the fixed test passes.
- **QA-m1: verified closed.** Each of the three `except`-width mutations is killed by its new test. A further app-only narrowing of `SESSION_ERRORS` is also killed.
- **Architect m1 and m4: confirmed by mutation.**
  - m1: a fixed code in "Run completed" is killed.
  - m4: a client that stays marked connected after `stop()` is killed.
- **Architect m2 and m3: confirmed by reading.**
- No new defect.

### ❓ Needs a decision

None. Q12 and Q13 are answered (A and A).
