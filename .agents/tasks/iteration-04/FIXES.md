# Iteration 4 — Fixes

<!-- Appended by the architect, Stage 3 round 1, 2026-09-29. Verdict APPROVED WITH RESERVATIONS (see ARCHITECT_REVIEW.md). -->

## 🏛️ Architecture & System Boundaries

No items. The D-F views and `for_supervisor()` carry no article text at any depth. The reused agent-facing JSON schemas are byte-identical to Approach 1's. The models hold no routing logic, and the identity of the candidate and the attempt is preserved.

## 🧹 Code Quality & Conventions

* A-M1: resolved in round 1 (a `mode="before"` validator on `supervisor` maps an empty value to `medium`; covered by `test_supervisor_reasoning_effort_resolves_to_medium_when_empty`).
* A-m1: resolved in round 1 (the two banners now cite `SPECIFICATIONS.md §6.3` and `§6.3, §6.6`).
* A-m2: resolved in round 1 (the `_partial_binding_claims` docstring is a one-line summary).

<!-- Appended by QA, Stage 3 round 1, 2026-09-29. Verdict CHANGES REQUIRED (see QA_REVIEW.md). -->

## 🧪 QA & Verification

* A-M1 (QA corroboration): resolved in round 1 (the new test covers the environment variable, an empty `.env` line, and a real `high` value).
* QA-m1: resolved in round 1 (`test_document_record_state_is_saved_whatever_its_attempts`; M28 killed on a scratch copy).
* QA-m2: resolved in round 1 (the `fatal_error` and `documents` type assertions; M24 and M41 killed on a scratch copy).

<!-- Appended by the architect, Stage 3 round 2, 2026-09-29. Verdict APPROVED (see ARCHITECT_REVIEW.md, round 2). -->

## 🏛️ Architecture & System Boundaries

No items (round 2).

## 🧹 Code Quality & Conventions

No items (round 2). The architect verified A-M1, A-m1 and A-m2 independently and found no new defect. Ruff: 0 in-scope findings, 0 pre-existing.

<!-- Appended by QA, Stage 3 round 2, 2026-09-29. Verdict PASSED (see QA_REVIEW.md, Round 2). -->

## 🧪 QA & Verification

No items (round 2).
* **Resolved.** QA verified A-M1, QA-m1 and QA-m2 independently.
* **The suite.** QA re-ran it: 415 passed, and ruff is clean.
* **The mutants.** M28, M24 and M41 are killed on a fresh scratch copy.
* **A-M1, probed directly.** Unset, empty in the environment, empty in `.env` and an explicit `None` all give `medium`, and `high` gives `high`. `writer` and `qa_legal` are unchanged.
