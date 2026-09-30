## Architect — round 1

**Verdict: APPROVED.** No findings. Ruff: 0 in-scope, 0 pre-existing.

### 🏛️ Architecture & System Boundaries

None.

### 🧹 Code Quality & Conventions

None.

### ❓ Needs a decision

None.

## QA — round 1

**Verdict: PASSED.** Real results: `uv run pytest -q` gave `918 passed`; `uvx ruff check src tests --no-cache` gave `All checks passed!`. Acceptance criteria: 16 of 16 applicable (DoD-6 is Stage 4's). Full review: `QA_REVIEW.md`.

### 🧪 Quality Assurance & Test Verification

No required fixes. Two optional, non-blocking minors, detailed in `QA_REVIEW.md` §5:
- **m1 (optional):** add one rule 2 test on the `revise=True` path in `tests/test_unit/test_tools_writer.py`.
  * Arrange attempt #1 with `ERROR`, then call `writer_tool(revise=True)` with a Writer that skips the fetch (`[tool_use_turn("ArticleDraft", _REVISED)]`).
  * Assert the failure is `("fetch_document", DOC_ID, 2)`, `latest_drafted` is still #1, and `check_qa` returns `already_audited`.
- **m2 (optional):** in `src/tools.py` `_revision_input` (around line 474), the `assert` runs after the append and outside `_invoke_sub_agent`'s `try`.
  * Acceptable as is, since `check_writer` guarantees the invariant.
  * If you want it replaced, resolve `latest_drafted` before the append and raise `RuntimeError` in place of the `assert`.

### ❓ Needs a decision

None.

## Implementation — fix round 1

- **m1, resolved.** Added `test_an_undereferenced_revision_is_not_kept_and_the_audited_draft_stays_the_latest` to `tests/test_unit/test_tools_writer.py`, routed through `_CheckedTool`. It arranges attempt #1 with `ERROR`, then calls `writer_tool(revise=True)` with a Writer that skips the fetch. It asserts that the failure is `("fetch_document", DOC_ID, 2)`, that the result is the draft-less attempt #2 with the one-line `WriterSourceFetchError` error, that `latest_drafted` is still #1, and that `check_qa` returns `already_audited`.
  * It passed on its first run, because the code path is shared with `revise=False`.
  * A mutation check confirmed it is not vacuous: with `_verify_writer_dereferenced_source` disabled, it fails on the failure assertion. The mutation was reverted, and the file was confirmed byte-identical.
- **m2, resolved.** `writer_tool` now resolves what a revision revises (`_revision_source`, which returns a `_Revision` of the latest drafted attempt and its `QAReport`) **before** the new attempt is appended.
  * A broken `not_audited` invariant now raises an explicit `RuntimeError`, which replaces the `assert`. No attempt, ledger entry, failure or log line is left behind.
  * "Revision requested" is still logged after the append, with the same wording, before "Sub-agent invocation started".
  * Nothing the Supervisor or a sub-agent sees has changed.
  * Test (Red first): `test_a_revision_past_a_broken_not_audited_invariant_raises_before_using_an_attempt`, parametrized over no draft and a draft without a report. It monkeypatches `src.tools.check_writer` to admit the call. Red showed an `AssertionError` escaping after the append. Green raises a `RuntimeError` with the attempts unchanged, and with no Writer turn, ledger entry, failure or `src.tools` log line.

## Architect — round 2

**Verdict: APPROVED.** Both fix round 1 items are verified in the diff:
* **m2.** `_revision_source` runs before the append (`src/tools.py:210`), and no `assert` remains under `src/`.
* **m1.** The test at `tests/test_unit/test_tools_writer.py:472-484` covers rule 2 on `revise=True`.

The fix changes nothing the Supervisor or a sub-agent sees, and the pillars touched are still met. Real results: `uv run pytest -q` gives 924 passed. Ruff gives 0 in-scope findings and 0 pre-existing. Full review: `ARCHITECT_REVIEW.md`, round 2.

### 🏛️ Architecture & System Boundaries

None.

### 🧹 Code Quality & Conventions

None.

### ❓ Needs a decision

None.

## QA — round 2

**Verdict: PASSED.** Real results: `uv run pytest -q` gave `924 passed`; `tests/test_unit/test_tools_writer.py` gave `72 passed`; `uvx ruff check src tests --no-cache` gave `All checks passed!`. Acceptance criteria: 16 of 16 applicable (DoD-6 is Stage 4's). Both fixes were independently mutation-checked:
* m1: disabling rule 2 fails the new revise-path test.
* m2: moving `_revision_source` back after the append fails both parametrized cases.

Full review: `QA_REVIEW.md`, round 2.

### 🧪 Quality Assurance & Test Verification

None.

### ❓ Needs a decision

None.
