# Iteration 11 — Fixes

## Architect — round 1

### 🏛️ Architecture & System Boundaries

No findings.
- Control flow stays with the Supervisor.
- No article text reaches it.
- Parity holds: telemetry and the template engine are unchanged, and the metadata mapping matches Approach 1's `_build_draft_metadata`.
- P11 and P12 are implemented as decided.

### 🧹 Code Quality & Conventions

- [ ] **A-1 (🟢 Minor, dead code). `src/rendering.py` lines 197-203 and 217.**
  - **Defect.** `_RenderedAttempt.attempt` is assigned and never read. `_render_and_write` takes the attempt for the log context and for `FailureRecord.attempt` from `latest.attempt`, at lines 180-181, because it must be known before `_rendered_attempt` can raise.
  - **Change.** Remove the field and its constructor argument:
    ```diff
     @dataclass(frozen=True)
     class _RenderedAttempt:
    -    """The attempt a saved document is rendered from, with the two slots a saved draft must have filled."""
    +    """The draft and QA report a saved document is rendered from, the two slots a saved draft must have filled."""

    -    attempt: int
         draft: ArticleDraft
         qa_report: QAReport
    ...
    -    return _RenderedAttempt(attempt=latest.attempt, draft=latest.draft, qa_report=latest.qa_report)
    +    return _RenderedAttempt(draft=latest.draft, qa_report=latest.qa_report)
    ```
  - **Check.** No test change is needed. `uv run pytest -q` and `uvx ruff check src tests` stay green.

Optional, non-blocking (see ARCHITECT_REVIEW.md §3):
- **O-1.** Make the trailing parameters of `_draft_metadata` (lines 220-229) and `_render_and_write` (lines 161-168) keyword-only, so `own` and `share` cannot be swapped.
- **O-2.** `SPECIFICATIONS.md:1037`: change "as P11, P12 and so on" to "as P13 and so on".
- **O-3.** At line 189, assert that the path `write_draft_file` returns equals `result.path`.

## ❓ Needs a decision

None from the architect.

## QA — round 1

### 🧪 Quality Assurance & Test Verification

No actionable defects. The verdict is PASS; see `QA_REVIEW.md`.
- Measured: `uv run pytest -q` gives 1063 passed, and `uvx ruff check src tests --no-cache` gives All checks passed. Both match the implementer's report.
- QA ran 21 mutations of `src/rendering.py` on a scratch copy, and all 21 were killed.
- QA concurs with A-1: `_RenderedAttempt.attempt` is never read.

Optional, non-blocking (see `QA_REVIEW.md` §4):
- **O-Q1.** In `IMPLEMENTATION_PLAN.md`, after the Iteration 11 Red bullet "Run totals …", add a "(superseded by P12)" note. This is an orchestrator edit.
- **O-Q2.** Iteration 14: test the path where `finalise_run` raises `ValueError` for an unpriced model ID. Earlier drafts are already written, and the composition root must map the failure.
- **O-Q3.** Iteration 16: the benchmark parser must accept `None` in the Attempt column for the Scout and Supervisor rows.

### ❓ Needs a decision (QA)

None from QA.

## Implementation — fix round 1

- **A-1, resolved.** The `attempt` field of `_RenderedAttempt` and its constructor argument are removed, and the docstring is reworded as proposed. No test referred to the field. The suite stayed green after this change on its own: 1066 passed.
- **O-1, taken.** The parameters after `result` in `_render_and_write`, and after `rendered` in `_draft_metadata`, are now keyword-only, and both call sites pass them by name. This was a refactor, and the suite stayed green: 1066 passed.
- **O-2, taken.** `SPECIFICATIONS.md` now reads "as P13 and so on".
- **O-3, taken, test first.** New test: `test_a_draft_written_anywhere_but_its_allocated_path_is_a_persist_failure`. Red: it failed with `assert False is True` on `persistence_failed`, because the mismatch was reported as success. Green: `_render_and_write` compares the path `write_draft_file` returns with `result.path`, and on a mismatch raises `RuntimeError` inside the `persist` stage. It is then recorded and logged like any other write failure, and the next draft is still written. Because the check runs after the write, a mismatched file is already on disk at the wrong path. That is accepted, since the failure record names both paths.
- **O-Q1, O-Q2, O-Q3: not applied.** They are out of scope for this pass, as directed.
- **Final results.** `uv run pytest -q`: 1067 passed. `uvx ruff check src tests`: All checks passed.

## Architect — round 2

### 🏛️ Architecture & System Boundaries

No findings.
- **O-3 is sound as placed** (`src/rendering.py:200-205`). The mismatch is raised inside the `persist` stage. It is then recorded, logged at ERROR and absorbed, like any write failure, and nothing is rerouted.
- **Checking after the write is acceptable.** The file lands at the convention path, `result.path.parent / f"{draft_id}.md"`, so the content is kept, and the record names both paths.

### 🧹 Code Quality & Conventions

- **A-1, verified resolved.** `_RenderedAttempt` is at `src/rendering.py:213-218`, and its constructor at `:232`.
- **O-1 and O-2, verified applied.** `rendering.py:163-171` and `:235-245`, and `SPECIFICATIONS.md:1037`.
- **Ruff.** 0 in-scope findings and 0 pre-existing debt.
- **Tests.** `uv run pytest -q` gives 1067 passed.

Optional, non-blocking:
- **O-4.** In `tests/test_unit/test_rendering.py:816`, also assert `(saved_b.path.parent / f"{saved_b.draft_id}.md").is_file()`. That pins the accepted trade-off.

### ❓ Needs a decision (architect, round 2)

None.

**Architect round 2 verdict: APPROVED**

## QA — round 2

### 🧪 Quality Assurance & Test Verification

No actionable defects. The verdict is PASS; see `QA_REVIEW.md` round 2.
- **Measured.** `uv run pytest -q` gives 1067 passed. `uvx ruff check src tests --no-cache` gives All checks passed. `uvx pyright` on the changed files gives 0 errors.
- **The count gap is explained.** Round 1 measured 1063; now there are 1067. That is +1 for the O-3 test, plus +3 from `test_document_uses_no_forbidden_term`, which now also runs over this folder's three review files.
- **Fixes verified.** A-1, O-1, O-2 and O-3 are all verified.
- **Mutations.** Four QA mutations of the O-3 check ran on a scratch copy (M22 to M25), and all four were killed.
- **Acceptance.** 3/3 acceptance criteria and 8/8 Red items still hold.
- **QA concurs with architect O-4** as an optional pin of the trade-off. It is not required.

### ❓ Needs a decision (QA, round 2)

None.
