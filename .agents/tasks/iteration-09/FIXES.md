## Architect — round 1

**Verdict: CHANGES REQUESTED** (in skill terms, APPROVED WITH RESERVATIONS: no architectural violation). There is one 🟡 Major item and one optional 🟢 Minor. Ruff: 0 in-scope, 0 pre-existing. Real results: `uv run pytest -q` gives 991 passed. Full review: `ARCHITECT_REVIEW.md`.

### 🏛️ Architecture & System Boundaries

None. `qa_tool` follows D-A, D-C rule 8 and §7.3, keeps the cap out of QA-Legal's view (DM7), returns only `supervisor_view()` (D-F), and sequences nothing.

### 🧹 Code Quality & Conventions

- **M1 (🟡 Major, required): QA-Legal's hooks are untested.** `src/tools.py:266` passes `hooks=hooks` to `build_qa_legal_agent`, but no test asserts it.
  * With `hooks=hooks` removed, all 222 tests in `tests/test_unit/test_tools_*.py` still pass (mutation checked in a scratch copy).
  * The Scout (`tests/test_unit/test_tools_scout.py:404-416`) and the Writer (`tests/test_unit/test_tools_writer.py:255-274`) each have this test. D-I requires the logging hook on every sub-agent.
  * **Change:** in `tests/test_unit/test_tools_qa.py`, add `hooks: tuple[HookProvider, ...] = ()` to `_tools` (lines 175-192) and `_qa_tool` (lines 195-203), and pass it to `build_tools`.
  * Add a test with a `HookProvider` that counts `BeforeInvocationEvent`s. Assert 1 after one allowed `qa_tool` call and 0 after a refused one.
  * Confirm that the test fails with `hooks=hooks` removed from `src/tools.py:266`, then restore the line. No `src/` change is needed.
  * Sources: D-I, `IMPLEMENTATION_PLAN.md` §1.3 DoD-4, and the code-reviewer Gate 1.
- **m1 (🟢 Minor, optional, non-blocking): `Any` model parameters in the test helpers.** They are at `tests/test_unit/test_tools_qa.py:160` (`_CheckedTool.__init__`'s `qa`), 178-179 (`_tools`' `qa` and `writer`) and 568 (the first element of `_failing_qa`'s return tuple).
  * They could be narrowed to `ScriptedModel | FailingModel`, or to `strands.models.model.Model`.
  * Pyright is clean as is, and Iterations 7 and 8 use the same style, so leave it unless you are already editing these helpers for M1.

### ❓ Needs a decision

None.

## QA — round 1

**Verdict: FAIL (CHANGES REQUIRED).** There is one 🟡 Major item, and no Blockers. Real results:
* `uv run pytest -q` gives 991 passed, 0 failed, 0 warnings.
* `uvx ruff check src tests --no-cache` gives All checks passed!
* Acceptance criteria: 15 of 16 checkable rows pass. DoD-4 fails; DoD-6 is the orchestrator's.

Full review: `QA_REVIEW.md`.

### 🧪 Quality Assurance & Test Verification

- **F-1 (🟡 Major, required): the `hooks=hooks` forwarding to QA-Legal is untested (DoD-4).** This is the same defect as the architect's **M1**. It was found independently, and one fix closes both.
  * **Evidence.** In a scratch copy, I changed `src/tools.py:266` to `build=lambda: build_qa_legal_agent(models.qa_legal, client),` and ran the three tool test files. Verbatim output:
    ```
    222 passed in 5.80s
    ```
    The full suite on that mutant fails only on environment-bound tests, whose repo documents, lock file and template sit outside the scratch copy. It fails no tool or behaviour test.
  * **Fix, tests only.**
    * Give `_tools` and `_qa_tool` a `hooks: tuple[HookProvider, ...] = ()` parameter and forward it to `build_tools`. They are in `tests/test_unit/test_tools_qa.py`, lines 175-203.
    * Add one test, modelled on `tests/test_unit/test_tools_scout.py:404-416` (`_RecordingHooks`, which counts `BeforeInvocationEvent`). Assert that the count is 1 after one allowed `qa_tool` call, and 0 after a refused call, such as `already_audited`.
    * Confirm the Red by removing `hooks=hooks` at `src/tools.py:266`: the new test must fail on the count. Then restore the line.
    * No `src/` change is needed.
- **Optional, non-blocking (O-1).** `_CAP_PHRASES` could also list `"remaining"` and `"of 3"`. The exact `qa_view()` key-set assertions already prove that AC2 holds.

### ❓ Needs a decision

None.

## Implementation — fix round 1

- **M1 / F-1 (required): resolved, tests only.** `tests/test_unit/test_tools_qa.py`:
  * `_tools` and `_qa_tool` take `hooks: tuple[HookProvider, ...] = ()` and forward it to `build_tools`.
  * New `_RecordingHooks` counts `BeforeInvocationEvent`s.
  * New test `test_the_hooks_given_to_build_tools_reach_qa_legal_and_only_when_it_is_built`, with two cases: `allowed` (one unaudited draft; count 1) and `already_audited` (count 0).
  * Mutation evidence: with `hooks=hooks` removed from `src/tools.py:266`, `[allowed]` fails with `assert 0 == 1` (1 failed, 1 passed). The line was restored, and `cmp` against the backup reports it byte-identical. No `src/` change was made.
- **m1 (optional): applied.** The QA-Legal and Writer model parameters of `_CheckedTool.__init__`, `_tools`, `_qa_tool` and `_failing_qa` are now typed `strands.models.model.Model`, which is the type `SubAgentModels` declares and the base class of `ScriptedModel` and `FailingModel`. Ruff and `ruff format --check` are clean.
- **O-1 (optional): applied.** `_CAP_PHRASES` also lists `"remaining"` and `"of 3"`. The vacuity test gains two cases, and every checked call in the file still passes.
- **O-2:** left alone, as instructed.

Results: `uv run pytest -q` gives 998 passed. That is 991, plus 4 new cases in `test_tools_qa.py` (67 to 71), plus 3 forbidden-term cases for this iteration's three review `.md` files. `uvx ruff check src tests` reports All checks passed!

## Architect — round 2

**Verdict: APPROVED.** M1 and QA's F-1 are closed, and m1 and O-1 are applied. My own run gives 998 passed, and `uvx ruff check src tests --no-cache` gives All checks passed! (0 in-scope, 0 pre-existing).

My independent mutation check removed `hooks=hooks` at `src/tools.py:266`. The three `test_tools_*.py` files then gave 1 failed, 225 passed, where round 1 gave 222 passed. The mutant is killed. Full review: `ARCHITECT_REVIEW.md`, round 2.

### 🏛️ Architecture & System Boundaries

None. `src/` is unchanged since round 1.

### 🧹 Code Quality & Conventions

None.

### ❓ Needs a decision

None.

## QA — round 2

**Verdict: PASS.** No findings. Real results:
* `uv run pytest -q` gives 998 passed, 0 failed; under `-W error`, also 998 passed.
* `uvx ruff check src tests --no-cache` gives All checks passed!
* Acceptance criteria: 16 of 16 checkable rows pass, DoD-4 included. DoD-6 is the orchestrator's.

Full review: `QA_REVIEW.md`, round 2.

### 🧪 Quality Assurance & Test Verification

- **F-1: closed.** I reproduced the mutation independently in a scratch copy, removing `hooks=hooks` from `src/tools.py:266`. Verbatim output: `1 failed, 70 passed`, with `test_the_hooks_given_to_build_tools_reach_qa_legal_and_only_when_it_is_built[allowed]` failing on `assert 0 == 1`. In round 1 the same mutant survived.
- **O-1: applied and verified.** Each of the 10 phrases has its own can-fail case.
- **m1: applied and verified.**
- No new defects.

### ❓ Needs a decision

None.
