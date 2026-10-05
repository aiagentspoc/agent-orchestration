# QA Review — Iteration 15: Scripted end-to-end scenarios (round 1)

## 1. Summary and verdict

**Verdict: PASSED.** No blocker and no major finding. There is one minor robustness gap in the AC2 self-check. The architect raised it too (its item 4), and my mutation T1 confirms it. Every scenario wires its key correctly today, so AC2 holds.

The diff contains one new file, `tests/test_integration/test_supervisor_e2e.py` (1193 lines, 19 tests), and the orchestrator's tracker row in `IMPLEMENTATION_PLAN.md`. There is no change under `src/` (`git diff --stat -- src` is empty).

### Commands run by QA

| Command | Real result |
| :--- | :--- |
| `uv run pytest -q` | **1433 passed** in 84.12 s; 0 failed, 0 errors, no warnings summary. This matches the implementer's claim (1414 + 19) |
| `uvx ruff check src tests --no-cache` | `All checks passed!` |
| `uv run pytest -m live --collect-only -q` | `no tests collected (1433 deselected)` |
| `uv run pytest tests/test_integration/test_supervisor_e2e.py -q --durations=0`, three times | 19 passed each time (40.77 s, 44.13 s and 49.28 s); the slowest call was 2.97 s (s15) |
| Subsets (`-k "every_catalogue or s10 or x01"`; s15 with `tests/test_unit/test_logging.py`) | 3 passed; 40 passed. There is no order dependence, and `restore_logging` holds across modules |

## 2. Gate matrix

| Gate | Topic | Status | Notes |
| :--- | :--- | :---: | :--- |
| 1 | Strict TDD | ✅ | The iteration adds tests only, over existing code. The implementer's report gives a Red-by-mutation for every scenario. My own 8 production mutations were all killed, each by the expected scenario (§5) |
| 2 | Zero-token testing | ✅ | Every model is a `ScriptedModel` from `scripted_model_builder_by_effort`, which fails on an unscripted key. x01's builder raises before any model is built. `_isolate_environment` is autouse. The 429 in s11 is built in memory on an `.invalid` host, with no request made. `addopts = "-m 'not live'"` is in place |
| 3 | Pydantic v2 contracts | n/a in this iteration | No `src/` change. The tests read `RunState`, `FailureRecord` and `GuardrailViolation` through their real fields |
| 4 | Guardrails and attempt cap | ✅ | End to end, through the Supervisor's real tool path: `already_audited`, `revise_after_pass`, `initial_draft_exists`, `not_a_candidate`, `already_saved` (P2 on `writer_tool`), `error_with_attempts_remaining`, `draft_ceiling`, `scout_already_run` ×5 and `invalid_scope`. Each is returned (`result is None`, `error.guardrail`), logged at WARNING on its own `doc_id`, and stored. The cap of 3 is covered by s02 and s07. `attempt_limit`, `not_audited` and `no_draft` stay covered by the Gate 4 unit and tool tests (recorded decision 9) |
| 5 | Strands integration and telemetry | ✅ | Token identity: Σ drafts' `total_tokens` + unsaved documents' own ledger tokens == "Run completed total_tokens" == Σ ledger. s01 checks it with an unsaved term of 0, s08 with a non-zero one |
| 6 | No article text for the Supervisor | ✅ | s15 walks every string leaf of every `received_messages` entry, then parses each `toolResult` JSON. There is no sentinel and no `FORBIDDEN_SUPERVISOR_KEYS`, across a success, a revision, a failure summary and a violation. Mutation M5 (the `draft` leaked by `supervisor_view`) is killed |
| 7 | Drafts and logging | ✅ | Drafts are checked on disk: names, Status, Revision Attempts, the banner, and the text of the earlier draft (s06). s14 checks no overwrite and max+1. Every `src.*` line carries the run's `run_id`. Each declared D-I event is matched at the catalogue level |
| 8 | Python and subprocess safety | ✅ | Files use `pathlib.Path`, full annotations, imports at the top and the `Final` constants. A PID diff around three e2e runs shows no new python, uv or fastmcp process of mine; the two survivors were a concurrent reviewer's `pytest -q` and its child. The repo's `drafts/` and `logs/` hold only `.gitkeep` |

## 3. Acceptance criteria and Definition of Done

### The plan's "Key assertions", row by row

| # | Key assertion | Status | Evidence |
| :---: | :--- | :---: | :--- |
| 1 | Two drafts; exit 0; per-draft tokens plus unsaved tokens equal the run total | ✅ | s01: `_001` and `_002` in save order, `SUCCESS`, `_assert_tokens_add_up` |
| 2 | One draft with the banner; attempts 3; WARNING "Draft rendered with [UNRESOLVED COMPLIANCE ALERT]" | ✅ | s02: Status ERROR, attempts 3, the banner in the text, and the banner line at WARNING (`_assert_events`), with `attempts_used=3` and the issue. Mutation M4 is killed |
| 3 | Attempts 2; "Revision requested" follows `WARNING` | ✅ | s03: `attempt=2 follows=WARNING`, and the WARNING verdict's index < the revision's index. Mutation M2 is killed |
| 4 | Attempts 1; status `WARNING` | ✅ | s04, plus no "Revision requested" and `qa_status=WARNING attempts=1` on the saved line |
| 5 | `FailureRecord(stage="writer", attempt=1)`; attempts 2 | ✅ | s05: failures `[("writer", A, 1)]`, the draft at attempts 2, no `initial_draft_exists` |
| 6 | The rendered text is the earlier draft's; attempts 2 | ✅ | s06: the revision is rejected by rule 2 (`fetch_document@2`). Attempt 1's headline and body are present and the rejected text is absent |
| 7 | No draft; WARNING "Candidate left unsaved" | ✅ | s07: three `writer` failures, no draft, `last_state=not_drafted` at WARNING. Mutation M8 is killed |
| 8 | Each violation returned, logged at WARNING and stored; exit 0 | ✅ | s08: all 7 named violations in order, checked three ways, under `max_drafts=1`. Mutation M1 is killed |
| 9 | All five logged and stored; none is bounded (DM16) | ✅ | s09: `scout_already_run` ×5 stored and logged, `violations=5`, and the whole script consumed |
| 10 | The saved draft rendered; exit 2; no model call after the fatal tool | ✅ | s10: `MCP_ERROR`, `fatal_error` an `MCPConnectionError`, Supervisor `turns_consumed == 5`, and the last supervisor "Model HTTP call" before "Fatal abort". Mutation M3 is killed |
| 11 | The saved draft rendered; exit 6; ERROR "Supervisor invocation failed" with `RemoteErrorDetail` | ✅ | s11: `remote` JSON carries `status_code 429` and `request_id`, with the traceback in the continuation. It uses a `ScriptedModel` exception turn instead of the plan's `FailingModel`, which fails on every call and so cannot fail "after one save". This deviation is recorded (implementer decision 2) and does not weaken the key assertion |
| 12 | Exit 1; no draft | ✅ | s12. Mutation M6 is killed |
| 13 | Exit 3; in the second case, the retry succeeds | ✅ | s13a: `PARSER_ERROR`, `scope is None`. s13b: `invalid_scope`, then the scope is set and a draft saved, exit 0 |
| 14 | New IDs continue the sequence, with no overwrite | ✅ | s14: `_001` and `_003` exist, so the run saves `_004` and `_005`, and the existing files are byte-identical. Mutation M7 is killed |
| 15 | No message the Supervisor received contains Writer article text | ✅ | s15 (see Gate 6) |

### Acceptance criteria and DoD

| Item | Status | Evidence |
| :--- | :---: | :--- |
| AC1: all 15 scenarios pass by default, each under 60 s | ✅ | 19/19, three times. Slowest call 2.97 s. Each run also asserts the logged `wall_clock < 60`. The orchestrator must record the figures in WALKTHROUGH (the implementer's report lists them) |
| AC2: every D-I event asserted; a test compares names | ✅ | The catalogue is parsed from SPECIFICATIONS.md (23 rows, pinned). The pattern keys must equal the catalogue, and the union of the declarations must equal the catalogue. Mutation T2 (dropping one declaration) fails the test. "Configuration failure" and "Draft render or write failure" are reached by the supplementary x01 and x02. Only the hook half of "Model HTTP call" is assertable under P4 (recorded) |
| DoD-1 | ✅ | 1433 passed, 0 failed |
| DoD-2 | ✅ | ruff clean |
| DoD-3 | ✅ | No live call (Gate 2) |
| DoD-4 | ✅ | No new `src/` code |
| DoD-5 | ✅ | `test_docs_consistency.py` is part of the 1433 |
| DoD-6 | pending | WALKTHROUGH.md is written by the orchestrator at Stage 4 |

**Total: AC 2/2 and the 15/15 scenario rows hold; DoD 5/5 checkable now, with DoD-6 pending Stage 4.**

## 4. Findings by severity

**🔴 Blocker:** none.

**🟡 Major:** none.

**🟢 Minor**

* **QA-1 (optional; same as architect item 4). The AC2 test does not prove that each scenario asserts its declared key.**
  * `test_every_catalogue_event_is_asserted_by_a_scenario` (l.1191–1193) checks only that a `test_<key>_` function exists.
  * Mutation T1 deleted `_assert_events(result, "x01")` from x01, and all 19 tests still passed. The event's level (ERROR) then goes unchecked.
  * Today all 18 scenarios call `_assert_events(result, "<own key>")` exactly once, which I verified by inspecting their source. So AC2 is met, but its self-check is weaker than its docstring claims.
  * Fix in FIXES.md.

## 5. Mutation evidence (scratch copy, since removed)

Each mutation was applied to a scratch copy of `src/` and `tests/`, the e2e file was run, and the copy was restored.

| Mutation | Result |
| :--- | :--- |
| M1 `Guardrail violation` logged at INFO | Killed: s08, s09, s13b, s15 |
| M2 revision always `follows=ERROR` | Killed: s03 |
| M3 `FatalStopHook` never calls `cancel()` | Killed: s10 |
| M4 `unresolved_errors=[]` (no banner) | Killed: s02 |
| M5 `supervisor_view` keeps `draft` | Killed: s15 |
| M6 `NO_UPDATES` never mapped | Killed: s12 |
| M7 draft ID ignores the disk | Killed: s14 |
| M8 "Candidate left unsaved" at INFO | Killed: s07, s08, s10 |
| T1 x01 drops its `_assert_events` call | **Survived** (QA-1) |
| T2 s10 stops declaring "Fatal abort triggered (D-D)" | Killed: the AC2 test |

## 6. Remediation

See `FIXES.md`, section "QA — round 1". Every item is optional, and none blocks the commit.

---

# Round 2 — re-review after fix round 1

## R2.1 Summary and verdict

**Verdict: PASSED.** All four optional items (architect 1–4; QA-1 is the same as architect 4) are applied, test-side only, and each is verified independently below. There is no new finding. `git diff --stat -- src` is still empty.

### Commands run by QA

| Command | Real result |
| :--- | :--- |
| `uv run pytest -q` | **1436 passed** in 83.46 s; 0 failed, no warnings summary. This matches the implementer's claim. The +3 since round 1 are the docs-consistency cases for the three new review .md files |
| `uvx ruff check src tests --no-cache` | `All checks passed!` |
| `uv run pytest -m live --collect-only -q` | `no tests collected (1436 deselected)` |
| `uv run pytest tests/test_integration/test_supervisor_e2e.py -q --durations=1`, three times | 19 passed each time (36.57 s, 35.41 s, 35.28 s); slowest call 2.20 s. It is stable |

## R2.2 Verification of each fix

| Item | Status | Evidence |
| :--- | :---: | :--- |
| QA-1 / architect 4: each scenario asserts its own key | ✅ | Coverage test l.1199–1202 (`import inspect` at l.18). Scratch-copy mutations, each against the coverage test: **T1** deleting `_assert_events(result, "x01")` → `AssertionError: x01`, `1 failed` (it survived in round 1); **T3** x01 asserting `"x02"` instead → `AssertionError: x01`; **T4** deleting s10's call → `AssertionError: s10`. Baseline on the scratch copy: `1 passed` |
| Architect 1: `_Run.index` by position | ✅ | `_LogLine.position` (l.156) is filled from `len(records)` (l.174, l.177); `index` returns it (l.214). A scratch log `dup, other, dup, Run completed…` parsed to positions `0, 1, 2, 3`, so the second `dup` keeps its own place |
| Architect 2: exact counters | ✅ | l.304–305 and s09's l.797 use `_field(...) == str(n)`. `_field` matches `name=(\S+)` after a start or whitespace. On `violations=12 failures=10` it returns `'12'`, so `== "1"` is `False` and `== "12"` is `True` |
| Architect 3: fresh turns | ✅ | s02 l.536 and s09 l.784 build each turn in a comprehension. The only other `[...] * n` lists (l.792, l.800) are expected values, not scripted turns |

## R2.3 Acceptance criteria and Definition of Done

| Item | Status | Evidence |
| :--- | :---: | :--- |
| AC1: all 15 scenarios pass by default, each under 60 s | ✅ | 19/19, three runs; slowest call 2.20 s |
| AC2: every D-I event asserted; a test compares names | ✅ | The coverage test passes, and now also fails when a scenario stops asserting its own key (T1, T3, T4) |
| DoD-1 to DoD-5 | ✅ | 1436 passed; ruff clean; no live call; no `src/` change; docs tests included |
| DoD-6 | pending | WALKTHROUGH.md is Stage 4 |

**Total: AC 2/2; the 15/15 scenario rows still hold; DoD 5/5 checkable now, DoD-6 pending Stage 4.**

## R2.4 Findings by severity

**🔴 Blocker:** none. **🟡 Major:** none. **🟢 Minor:** none open.

## R2.5 Hygiene

* Mutations ran on a scratch mirror in the session scratchpad, using the project's venv. I removed it afterwards.
* The PIDs of python.exe and uv.exe after my runs are a subset of the baseline taken before them. I left no new process.
* `drafts/` and `logs/` hold only `.gitkeep`. `git status --short` is unchanged: the plan's tracker row, `iteration-15/` and the e2e file.

**Verdict: PASS**
