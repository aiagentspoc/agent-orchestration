
## Architect — round 1

**Verdict: APPROVED.** No blocking items: no 🔴 or 🟡 findings. Ruff: 0 in-scope findings, 0 pre-existing debt. Every item below is **optional** (🟢 Minor), for the implementer's discretion under §1.5 (test organisation). Full review: `.agents/tasks/iteration-15/ARCHITECT_REVIEW.md`.

### 🏛️ Architecture & System Boundaries

No findings.
* No test code sequences the Supervisor.
* Scenario 10's session stop is a clean `MCPClient.stop()`: it leaves `_close_exception` unset, so the outer `with` exits without the Q12 `RuntimeError`.
* No `src/` change.

### 🧹 Code Quality & Conventions

All four items are in `tests/test_integration/test_supervisor_e2e.py`.

1. **(optional) `_Run.index` compares log records by value** (l.208–210).
   * **Problem.** `_LogLine` drops the timestamp (l.172), so two identical records resolve to the first one.
   * **Change.** Record each line's position when parsing and compare positions. For example:
     * add a `position: int` field to `_LogLine`, filled from the `records` length in `_read_log`; then
     * make `index` return `line.position`.
2. **(optional) Exact counter checks in `_assert_run_completed`** (l.300–301).
   * **Problem.** The substring checks `f"violations={n}"` and `f"failures={n}"` would also accept `violations=12` when `n` is 1.
   * **Change.** Replace them with:
     * `assert _field(completed, "violations") == str(len(state.violations))`;
     * `assert _field(completed, "failures") == str(len(state.failures))`.
3. **(optional) Build repeated turns fresh** (l.779 and l.532).
   * **Problem.** The list multiplication shares one turn's event dicts across turns, because `ScriptedModel` copies only the outer list.
   * **Change.** Build each turn on its own:
     * `[_scout_call() for _ in range(1 + repeats)]`;
     * `[_verdict("ERROR", ERROR_ISSUE) for _ in range(3)]`.
4. **(optional) Prove each scenario asserts its own events** (l.1191–1193).
   * **Problem.** The AC2 test checks that each scenario key has one `test_<key>_` function, but not that the function asserts that key's events.
   * **Change.** Also assert that `f'_assert_events(result, "{scenario}")'` appears in `inspect.getsource(globals()[name])` for the matching test. This needs `import inspect` at the top of the file.

## QA — round 1

**Verdict: PASSED.** No blocker or major findings; nothing below blocks the commit. Full review: `.agents/tasks/iteration-15/QA_REVIEW.md`.

The QA runs:
* `uv run pytest -q`: 1433 passed.
* `uvx ruff check src tests --no-cache`: clean.
* The e2e file, run three times: 19 passed each time, slowest call 2.97 s.
* Mutations: 9 of 10 were killed.

### 🧪 Quality Assurance & Test Verification

1. **QA-1 (🟢 Minor, optional; corroborates architect item 4). The AC2 coverage test does not prove each scenario asserts its own key.**
   * **Location.** `tests/test_integration/test_supervisor_e2e.py` l.1191–1193.
   * **Evidence.** I deleted `    _assert_events(result, "x01")` from `test_x01_…` on a scratch copy. The e2e file still reported, verbatim:
     ```text
     19 passed in 42.41s
     ```
     So the "Configuration failure" event lost its catalogue-level check, and the AC2 test did not notice.
   * **Current state.** All 18 scenarios do call `_assert_events(result, "<own key>")` exactly once today; I checked their source. AC2 is met.
   * **Fix.** Inside the loop over `_SCENARIO_EVENTS`, use the matching test function's source:
     ```python
     [name] = [name for name in tests if name.startswith(f"test_{scenario}_")]
     assert f'_assert_events(result, "{scenario}")' in inspect.getsource(globals()[name]), scenario
     ```
     This replaces the current `len(...) == 1` assertion, since the unpacking already requires exactly one match. Add `import inspect` at the top of the file.

No item needs a user decision.

## Implementation — fix round 1

All four optional items were applied, covering five reviewer entries (architect 4 and QA-1 are the same fix). Every change is test-side, in `tests/test_integration/test_supervisor_e2e.py`, with no `src/` change. Each weakness was first shown on the unchanged code, and then shown to be closed.

1. **Architect 1, `_Run.index` by position.**
   * **Change.** `_LogLine` has a new `position: int` field, which `_read_log` fills from `len(records)`; `index` returns `line.position`.
   * **Evidence.** In a scratch log `(dup, other, dup)`, the old `index` put the second duplicate at `0`; the new one puts it at `2`.
2. **Architect 2, exact counters.**
   * **Change.** `_assert_run_completed` now asserts `_field(completed, "violations") == str(len(state.violations))`, and does the same for `failures`. s09's own `f"violations={repeats}" in …` check got the same change.
   * **Evidence.** On a message carrying `violations=12 failures=10`, the old substring checks accepted `violations=1` and `failures=1` (`True`). The exact checks reject both (`False`).
3. **Architect 3, fresh turns.**
   * **Change.** s02 now uses `[_verdict("ERROR", ERROR_ISSUE) for _ in range(3)]`, and s09 uses `[*(_scout_call() for _ in range(1 + repeats)), text_turn(…)]`.
   * **Evidence.** Under list multiplication, the first event dict was the same object in every turn (`is` → `True`). Each turn is now built on its own (`False`).
4. **Architect 4 and QA-1, the AC2 test proves each scenario asserts its own key.**
   * **Change.** `import inspect` is at the top of the file. The coverage test now unpacks `[name] = […]`, so exactly one matching test is still required, and asserts that `f'_assert_events(result, "{scenario}")'` is in `inspect.getsource(globals()[name])`.
   * **Evidence.** I deleted `    _assert_events(result, "x01")` temporarily. The coverage test then failed with `AssertionError: x01`, `1 failed`. After the revert it gave `1 passed`.

**Close-out**
* `uv run pytest -q`: 1436 passed.
* The e2e file: 19 passed.
* `uvx ruff check src tests`: all checks passed.
* `drafts/` and `logs/` hold only `.gitkeep`.

## Architect — round 2

**Verdict: APPROVED.** All four round 1 items, and QA-1, are verified as applied and effective. No new findings: no 🔴, 🟡 or 🟢 items. Ruff: 0 in-scope findings, 0 pre-existing debt. Full review: `.agents/tasks/iteration-15/ARCHITECT_REVIEW.md`, round 2 section.

### 🏛️ Architecture & System Boundaries

No findings. `git diff --stat -- src` is empty, and the fixes are test-side only.

### 🧹 Code Quality & Conventions

No findings. Every round 1 item is closed:

1. **`_Run.index` by position.** Closed (l.145–177, l.211–214).
2. **Exact counters.** Closed (l.304–305, l.797).
3. **Fresh turns.** Closed (l.536, l.784).
4. **Each scenario asserts its own events (QA-1).** Closed (l.18, l.1199–1202).

No item needs a user decision.

## QA — round 2

**Verdict: PASSED.** Every round-1 item is closed and verified independently. No new finding. Full review: `.agents/tasks/iteration-15/QA_REVIEW.md`, section "Round 2".

### 🧪 Quality Assurance & Test Verification

No open items.
* **QA-1 / architect 4.** Closed. On a scratch copy, deleting `_assert_events(result, "x01")` now fails the coverage test with `AssertionError: x01` (`1 failed`). Two further mutations fail it too: x01 asserting the `"x02"` key (`AssertionError: x01`), and deleting s10's call (`AssertionError: s10`).
* **Architect 1.** Closed. `_read_log` on a scratch log `(dup, other, dup, …)` gives positions `0, 1, 2, 3`.
* **Architect 2.** Closed. `_field` on `violations=12` returns `'12'`; `== "1"` is `False`.
* **Architect 3.** Closed (l.536, l.784). The only remaining `[...] * n` lists are expected values (l.792, l.800), not scripted turns.

### ❓ Needs a decision

None.
