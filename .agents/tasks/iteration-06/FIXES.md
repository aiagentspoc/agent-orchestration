
## 🏛️ Architecture & System Boundaries

_Architect, round 1: no architecture or boundary defects found in Iteration 6._

## 🧹 Code Quality & Conventions

_A-1 resolved (fix round 1): `_defined_models` docstring replaced with the architect's wording; the WALKTHROUGH *Deviations* note is the orchestrator's._

## 🧪 QA & Verification

_QA, round 1. Verdict in `QA_REVIEW.md`: CHANGES REQUIRED, with one blocker and two minor findings._

_Q-1 resolved (fix round 1): `test_builder_without_a_client_builds_a_tool_free_agent` added (3 cases, characterisation); a scratch mutant deleting the branch survived without it and fails all 3 with it. The WALKTHROUGH characterisation note is the orchestrator's._

### Q-2 (🟢 Minor): the triage split in the report is not what landed

**Evidence:** I compared the source text of every test function in `tests/test_unit/test_agents.py` with Approach 1's `tests/test_unit/test_agents.py`, by name.

| Group | Count |
| :--- | :---: |
| Same-name functions, textually identical | 34 |
| Same-name functions, changed | 25 |
| Renamed and adapted functions | 3 |
| Dropped ScopeParser functions | 16 |

**The three renamed functions:**
* `test_writer_accepts_revision_payload` became `test_writer_accepts_a_drafted_and_audited_record`;
* `test_run_writer_requires_the_current_date_as_a_keyword` became `test_run_writer_takes_the_current_date_from_the_record`;
* `test_run_qa_legal_requires_the_current_date_as_a_keyword` became `test_run_qa_legal_takes_the_current_date_from_the_record`.

The report says "kept verbatim 32; adapted 30". The totals it gives are right: 78, 16 dropped, 62 carried, 85 collected.

**Fix:** in `WALKTHROUGH.md`, record the triage as follows: 16 dropped, 34 kept verbatim, 28 adapted (25 same-name, 3 renamed), and 2 restored for F2. If a different definition of "verbatim" was meant, state it. No code change.

### Q-3 (🟢 Minor): the user-turn rewordings are not recorded as deviations

**Evidence:** report item 4 says the revision test "asserts Approach 1's own sentences". It asserts them reworded:

```text
Approach 1: Rewrite the previous draft below so that every issue in its QA audit is resolved. Preserve everything the audit did not object to.
Now:        Rewrite the previous draft in the record below so that every issue in its QA report is resolved. Preserve everything the audit did not object to.
```

Every user-turn change names the new input. None changes an instruction, so none is a stop condition. But only the system prompt has a declared substitution list, so these rewordings are recorded nowhere.

**Fix:** in `WALKTHROUGH.md`, under *Deviations*, list the user-turn changes against Approach 1. They are the ones in `QA_REVIEW.md` §4.5:
* **Scout.** The wording is unchanged. The JSON gains `context` and loses the two window fields.
* **Writer, first draft.**
  * "update below" becomes "update in the AttemptRecord below".
  * "on its update.doc_id" becomes "on its candidate.update.doc_id".
  * The section header becomes `## AttemptRecord`.
* **Writer, revision.**
  * "the previous draft below" becomes "the previous draft in the record below".
  * "QA audit" becomes "QA report".
  * The instruction now precedes the one record.
* **QA-Legal.**
  * "the article draft below" becomes "the article draft in the AttemptRecord below".
  * The section header becomes `## AttemptRecord`.

No code change.

<!-- Architect, Stage 3 round 2, 2026-09-29. Appended; other reviewers' sections are left as written. -->

## 🏛️ Architecture & System Boundaries

Round 2: no new findings. Q-1's fix covers the `client is None` branch through the public builders, keeps `_resolve_tools` AST-identical to Approach 1's, and leaves the P1 binding unchanged.

## 🧹 Code Quality & Conventions

Round 2:
* A-1 is verified resolved (`tests/test_unit/test_schemas.py:1173–1179`).
* The suite gives 741 passed.
* Ruff reports all checks passed, with 0 in-scope and 0 pre-existing findings.
* Prompt and constant parity with Approach 1 was re-verified by AST.
* There are no new findings.
* Q-2, Q-3 and A-1's *Deviations* note are accepted as the orchestrator's `WALKTHROUGH.md` items for Stage 4.

<!-- QA, Stage 3 round 2, 2026-09-29. Appended; other reviewers' sections are left as written. -->

## 🧪 QA & Verification

Round 2: verdict **PASSED**. There are no new findings.
* **Q-1** is verified resolved. 741 passed; ruff reports all checks passed. The trace of `src/agents.py` hits 146 of 146 statements, and 145 of 146 with the new test deselected, the one miss being line 487. The in-memory branch-deletion mutant is killed by exactly the 3 new cases.
* **Q-2** and **Q-3** are accepted as the orchestrator's `WALKTHROUGH.md` items for Stage 4. The exact text to record is in `QA_REVIEW.md` §R2.6.

---

**Orchestrator, Stage 4 (2026-09-29):** Q-2 and Q-3 are resolved in `WALKTHROUGH.md`: the corrected triage split in §3, and the user-turn rewordings under *Deviations* in §6. A-1's corrected cause is also recorded in §6.
