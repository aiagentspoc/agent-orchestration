# Iteration 2 — Fixes

## 🧪 QA & Verification

All three items are 🟢 minor and non-blocking; the verdict is PASSED (see `QA_REVIEW.md`). None needs a code change in `src/`.

### QA-m1 (🟢 minor): a cost test is near-tautological after the model-ID repointing
**Where:** `tests/test_unit/test_costs.py:33-45`, `test_default_model_rates_cover_every_worker_model_id`.
**Evidence:**
```text
< from src.agents import QA_LEGAL_MODEL_ID, SCOPE_PARSER_MODEL_ID, SCOUT_MODEL_ID, WRITER_MODEL_ID
> from src.credentials import FAST_MODEL_ID, STRONG_MODEL_ID
<     worker_model_ids = {SCOPE_PARSER_MODEL_ID, SCOUT_MODEL_ID, WRITER_MODEL_ID, QA_LEGAL_MODEL_ID}
>     worker_model_ids = {FAST_MODEL_ID, STRONG_MODEL_ID}
```
**The problem.** `DEFAULT_MODEL_RATES` is keyed by `FAST_MODEL_ID` and `STRONG_MODEL_ID` (`src/costs.py:32-40`). So `worker_model_ids <= set(DEFAULT_MODEL_RATES)` can no longer fail on a role-model rename, which is the regression the test's own docstring says it exists to catch.
**Why it is not a defect now.** The repointing is value-preserving, and it was forced: `src.agents` does not exist until Iteration 6.
**Fix:** two parts, neither touching `src/`.
1. **Now.** Record this in the Iteration 2 `WALKTHROUGH.md`, under *Deviations* ("Copy as is" was not possible for `test_costs.py`), and in the Iteration 6 carry-forward. Iteration 6 then repoints these three places back to the role model-ID constants of the new `src/agents.py`, restoring the four-key form:
   * `tests/test_unit/test_costs.py` (the import at line 13 and lines 35, 54-57, 66-67);
   * `TEST_RATES` in `tests/support/scripted.py` (the import at line 24, and lines 488-499);
   * the model-ID constants in `tests/test_unit/test_telemetry.py`.
2. **Optional, now.** Add a one-line comment above line 35 of `test_costs.py`: `# Repointed to the two pipeline IDs until src.agents exists (Iteration 6 restores the role IDs).`

### QA-m2 (🟢 minor): the implementer's AC2 wording overstates the transport
**Evidence.** The report says the drift test ran "6 passed against local hse-easy-mock over stdio". But `tests/test_integration/test_substrate_compatibility.py:12` is `import server`, which resolves to `C:\Users\Saksham\Git\poc\AIAgents\mcp-server\server.py`. The tests call `server.<tool>()` and `server.mcp.call_tool(...)` in process.
**Fix.** In `WALKTHROUGH.md`, state AC2 as: "the drift test passes against the on-disk `../mcp-server/server.py` (P7), imported in process; the stdio transport is covered by `test_mcp_client.py`". No code change.

### QA-m3: resolved (fix round 1)
P9 is recorded in `SPECIFICATIONS.md` §8.3 and pinned in `test_docs_consistency.py`; `src/mcp_client.py` stays verbatim until Iteration 7.

## ❓ Needs a decision

Moved by the orchestrator to `.agents/tasks/QUESTIONS.md` on 2026-09-29: QA's Q5 as **Q5 (Iteration 07)**, and QA's Q6 merged with architect A1 and A2 as **Q6 (Iteration 02)**.

<!-- Appended by the architect, Stage 3 round 1, 2026-09-29. Verdict APPROVED WITH RESERVATIONS (see ARCHITECT_REVIEW.md). -->

## 🏛️ Architecture & System Boundaries

All items are 🟢 Minor and non-blocking, and all are **owned by the orchestrator**. None is for the implementer, and none touches `src/` or `tests/`.

### A1 (🟢 Minor): the §4 layout still calls the template "unchanged", which contradicts P8
**Where:** `.agents/docs/IMPLEMENTATION_PLAN.md:161`, which reads `│   ├── templates/   draft.md (already present; unchanged)`.
**The problem.** Iteration 2 replaced the template under P8. `SPECIFICATIONS.md:48` now reads "identical to Approach 1's current template (P8)". Where the two documents disagree, `SPECIFICATIONS.md` wins, and the skill requires the disagreement to be reported.
**Fix.** Replace the line with:
```text
│   ├── templates/   draft.md (Approach 1's current template, P8)
```

### A2 (🟢 Minor): the traceability row and the harness pointers still say P1 to P6
**Where:** `IMPLEMENTATION_PLAN.md:817`, `CLAUDE.md:14`, `.claude/agents/architect.md:18`, `.claude/agents/implementation.md:16` and `.claude/agents/qa.md:18`.
This is the same item as QA's **Q6**, below. I concur with its option A. For the traceability row, I suggest two separate rows after the existing one: `| P7 | 2, 6, 16 |` (every copy from Approach 1 and every parity check reads the on-disk tree) and `| P8 | 2 |`. Leave `IMPLEMENTATION_PLAN.md:262` as it is: it records what Iteration 1 tested.

**Fix round 1 (implementer):** the P9 ranges in `SPECIFICATIONS.md`, `AGENTS.md` and both review skills now read P1 to P9. The four harness files (`CLAUDE.md`, `.claude/agents/*.md`) were **not** edited: the implementer does not change `CLAUDE.md` or `.claude/` configuration on an agent's relay of consent. Still open for the orchestrator or the user.

### A3 (information only): the Approach 1 baseline moved during this iteration
`../code-orchestration/` gained commit `1734096` (2026-09-29, 00:23 +0530), and its working tree now equals that HEAD.
* **What it changes:** `src/agents.py` (the Writer and QA-Legal prompts, and a widened `QA_LEGAL_TOOL_NAMES`), `src/orchestrator.py`, `test_agents.py` ("twelve prompt-contract tests … re-pinned") and `test_orchestrator.py`.
* **Iteration 2 is unaffected.** I checked that the span moved into `src/telemetry.py` and the moved tests are identical at `3b123e4` and at `1734096`.
* **What to do.** Under P7 no decision is needed. Record it in `WALKTHROUGH.md`, and have the Iteration 6 pre-flight re-derive two things from the new HEAD, not from `QUESTIONS.md` Q4's text:
  * the prompt-parity targets;
  * the `test_agents.py` triage. Q4's "12 stale failures" premise may no longer hold.

### Forward notes (not fixes; copy them into WALKTHROUGH.md)
Details are in `ARCHITECT_REVIEW.md` §5.
* **F1.** The same item as QA-m1; I concur.
* **F2 (Iteration 6 or 7).** Restore Approach 1's two unmoved telemetry tests: `test_fresh_agent_per_invocation_reports_per_call_telemetry` (the D20 fresh-agent guard) and `test_scripted_agent_reports_zero_provider_latency_like_the_real_provider`.
* **F3 (Iteration 4).** Add `HSE_MODEL_SUPERVISOR_REASONING_EFFORT` to `_ISOLATED_ENV_VARS` in `tests/conftest.py:26-41`.
* **F4 (Iteration 4).** Narrowing the stage literal breaks three tests that use `stage="scope_parser"`. Adapting their data is allowed by §1.5.
* **F5 (Iteration 7).** Restore `scripted_model_builder`, keyed so that the Supervisor, the Writer and QA-Legal (all `gpt-5.4`) can be scripted independently.

**Architect's view on QA's Q5.** I concur with option A. Annotations are neither a benchmark constant nor visible to any agent. Deferring them to Iteration 7 keeps this iteration's AC4 diff clean.

## 🧹 Code Quality & Conventions

No findings in round 1.
* `uvx ruff check src tests --no-cache` reports **0 in-scope findings and 0 pre-existing**.
* The opt-in `--select ANN,E402` run gives 75 ANN findings and **0 E402**. All 75 are in verbatim copies (`src/mcp_client.py` 9, `tests/support/scripted.py` 21, `tests/test_integration/test_mcp_client.py` 21, `tests/test_unit/test_template_engine.py` 24), so none blocks the iteration. For `src/`, see Q5.

<!-- Appended by the architect, Stage 3 round 2, 2026-09-29. Verdict APPROVED (see ARCHITECT_REVIEW.md, Round 2). -->

## 🏛️ Architecture & System Boundaries (round 2)

**Round-1 items**
* **A1: closed.** `IMPLEMENTATION_PLAN.md:162` now reads "Approach 1's current template, P8".
* **A2: closed.** The traceability rows are at `IMPLEMENTATION_PLAN.md:819-821`. The orchestrator updated the four harness pointers (`CLAUDE.md:14`, `.claude/agents/architect.md:18`, `implementation.md:16` and `qa.md:18`) to P1 to P9 under the user's Q6 answer, and each diff changes one line only.
* **A3 and F1 to F5:** accepted as walkthrough-owned, for Stage 4.

### A4 (🟢 Minor, orchestrator-owned, non-blocking): the Iteration 7 section does not list the P9 annotation work
**Where:** `.agents/docs/IMPLEMENTATION_PLAN.md:450-496`, Iteration 7, "Tool wrapper core and `scout_tool`".
**The problem.** P9 (`IMPLEMENTATION_PLAN.md:119`) and the traceability row `| P9 | 7 |` (line 821) assign the `mcp_client.py` annotations to Iteration 7. The Iteration 7 section itself has no step and no acceptance criterion for them, while other iterations cite their decisions inline (P1 in Iteration 6, P2 in Iteration 8). As a result, the Iteration 7 brief can miss the work.
**Fix.** Add to the Iteration 7 section, either now or at its pre-flight:
* **Green:** "Add the 9 missing type annotations to `src/mcp_client.py` (P9). Change no statement, default, message or result shape."
* **Acceptance criterion:** "`uvx ruff check src/mcp_client.py --select ANN` reports 0. After removing annotations, a diff of `src/mcp_client.py` against `../code-orchestration/src/mcp_client.py` shows no other change, and `tests/test_integration/test_mcp_client.py` still passes unchanged."

If the plan is not edited now, carry this into `WALKTHROUGH.md` as forward note **F6 (Iteration 7)**.

## 🧹 Code Quality & Conventions (round 2)

No findings. `uvx ruff check src tests --no-cache` reports **0 in-scope and 0 pre-existing** findings. The `test_docs_consistency.py` changes (lines 177-187, and the two docstrings) are annotated, have honest docstrings, and use `re.escape` for the P9 statement's backticks.

<!-- Appended by QA, Stage 3 round 2, 2026-09-29. Verdict PASSED (see QA_REVIEW.md, round 2). -->

## 🧪 Quality Assurance & Test Verification (round 2)

**No new actionable items.** `uv run pytest -q` reports `320 passed`, and `uvx ruff check src tests --no-cache` reports `All checks passed!`.
* **QA-m3 / Q5: resolved by P9.** I mutation-checked the pin: it catches rewording, deletion and reordering in both records.
* **Q6 (A1, A2): resolved.**
* **QA-m1 and QA-m2:** accepted as walkthrough items for the orchestrator at Stage 4. Neither needs a code change.
* **N3:** concurs with the architect's **A4**, the Iteration 7 section's missing P9 step. Its fix is already stated there, so I opened no duplicate item.
