# Iteration 1 — Fixes

<!-- Appended by the architect, Stage 3 round 1. -->

## 🏛️ Architecture & System Boundaries

* **A1** (`AGENTS.md` Rule 1 cites the wrong section for log events): resolved in fix round 1.

## 🧹 Code Quality & Conventions

* **C1** (the cap extractor misses common rewordings of the cap, number words included): resolved in fix round 1.
* **C2** (the P1 phrase list misses common ways of saying a sub-agent holds only some tools): resolved in fix round 1.

## 🧪 QA & Verification

Round 1, QA and Verification Agent, 2026-09-28. Verdict **PASSED** (see `QA_REVIEW.md`).

* **QA-m1** (pin the D-C decision table row for row, not by fragments): resolved in fix round 1.
* **QA-m2** (pin each P1–P6 decision's statement, in both documents that record it): resolved in fix round 1.
* **QA-m3** (`REMOVED_MODELS` omits five of the models that SPECIFICATIONS.md §6 lists as removed): resolved in fix round 1.

Round 2, QA and Verification Agent, 2026-09-28. Verdict **PASSED** (see `QA_REVIEW.md`, round 2). All six round-1 items were verified by in-memory probes. One new non-blocking item:

* **QA-m4** (🟢 Minor, non-blocking): `PARTIAL_BINDING_PHRASES` still misses the architect's round-1 probe sentence.
  * **Where.** `tests/test_unit/test_docs_consistency.py:125-138` and `465-468`, with the synthetic cases at `744-751`.
  * **Failing probe,** verbatim:

    ```text
    >>> _partial_binding_claims("The Scout is limited to the list and search tools.")
    []
    ```

  * **Fix.**
    1. Add a tool-anchored pattern alongside the phrase list, and report its matches from `_partial_binding_claims`:

       ```python
       re.compile(r"\b(?:is|are) (?:limited|restricted) to\b[^.\n]{0,60}?\btools\b", re.IGNORECASE)
       ```

    2. Add two synthetic cases to `test_partial_binding_claims_flags_restricted_tool_sets_but_not_prompt_boundaries`:
       * "The Scout is limited to the list and search tools." is flagged;
       * "The Scout is limited to the top 5 candidates." returns `[]`.
    3. Keep the existing "prompt limits it to the tools" case at `[]`.
  * **Verified.** This pattern has zero hits on the 11 documents today.
  * **Red.** The first new case fails with `assert [] == [...]`.

---

**Orchestrator, 2026-09-28:** QA-m4 is deferred to Iteration 4 by the user's answer to Q2 (option A). It is not resolved here; Iteration 4's brief carries it.
