# Iteration 11 — Architect Review (Stage 3, round 1)

**Scope audited:** `git diff` and `git status --short` on `approach-2/implementation` (uncommitted): `src/rendering.py`, `tests/test_unit/test_rendering.py`, `tests/test_unit/test_docs_consistency.py`, `.agents/docs/SPECIFICATIONS.md`, `.agents/docs/IMPLEMENTATION_PLAN.md` (P11/P12 rows and the §3 status, written by the orchestrator), `.agents/tasks/QUESTIONS.md` (Q8, Q9), and the range-text edits in `AGENTS.md`, `CLAUDE.md`, both review skills and `.claude/agents/{architect,implementation,qa}.md`.

**Verification run by the architect:**
- `uv run pytest -q`: **1063 passed** (baseline 1038, +25).
- `uvx ruff check src tests --no-cache`: **All checks passed**. That is 0 in-scope findings and 0 pre-existing debt.
- `uvx pyright src/rendering.py tests/test_unit/test_rendering.py`: 0 errors, 0 warnings.
- `git diff --quiet HEAD -- src/telemetry.py src/template_engine.py src/diagnostics.py`: unchanged. `src/template_engine.py` matches `../code-orchestration/src/template_engine.py` in content; only the line endings differ.
- A repository-wide grep finds no remaining "P1 to P10", "P1–P10" or "P1-P10" outside the task records.

---

## 1. Overall verdict

**APPROVED WITH RESERVATIONS.** The design is sound and faithful to the architecture. I found one Minor hygiene defect (dead code), filed in `FIXES.md`. Final verdict line: **CHANGES REQUESTED**, for that one Minor item only.

---

## 2. Pillar audit

### Pillar 1: An agent owns the flow. ✅
`finalise_run` (`src/rendering.py:109-150`) runs only after the Supervisor has finished. It calls no sub-agent, retries nothing and makes no choice about which draft or document comes next.
- The only loops are over saved documents, for rendering (`:143-146`), and over unsaved documents, for logging (`:155-158`).
- No Graph, Swarm or Workflow. No import of `src.tools`; the module docstring states the constraint at `:12`.
- A render or write failure is recorded and absorbed (`:190-192`). It never reroutes anything.

### Pillar 2: Division of labour. ✅
- Article text is read here only to render it into the file (`:187`). Nothing returns to the Supervisor: `RunFinalisation` (`:92-106`) holds only a bool, an int and a float.
- Code writes no banner text. `unresolved_errors` is filled for `ERROR` only (`:248`), and the reused `format_review_notes` adds the banner, as Approach 1 does (`orchestrator.py:726`).

### Pillar 3: Custom agent tools. Not touched by this iteration.

### Pillar 4: Guardrails and attempt state. ✅ (read-only use)
- `attempts = document.attempts_used` (`:244`, §6.8, D-C rule 11). Failed Writer calls count; this is tested at `test_rendering.py:658`.
- The rendered draft is `latest_drafted` (`:206-217`, §6.8 "Which draft is rendered", P2). Mutation-checked by the implementer, and covered by tests at `:641` and `:658`.
- No `AttemptRecord` slot is written.

### Pillar 5: Benchmark parity. ✅
- **Template.** It renders through the reused `render_draft`, with `config.template_path` (`:187`, test `:433`).
- **Cost basis.** `src/telemetry.py` is byte-identical to Approach 1's. No adapter was added, which is the right call; the plan only allowed one "if needed".
- **Metadata.** The mapping matches Approach 1's `_build_draft_metadata` (`orchestrator.py:706-741`) field for field: source fields from `candidate.update`, `qa_report`, `unresolved_errors` on `ERROR` only, `stage_telemetry = own + share`, and `model_rates_used=dict(rates)`.
- **Approach name.** `approach_name` keeps the model default, "Approach 2 (Research Analyst)" (AC2, test `:421`, `:428`).
- **Cost placement (deviation).** `aggregate_draft_totals` runs before the try (`:179`), matching `_persist_builds` (`orchestrator.py:772`, outside `_stage("render")`). It is justified and tested at `:831`.
- **Amortisation.** It uses `amortise_shared_telemetry` unchanged, and the first saved draft takes the remainder, as in Approach 1 (Q2). Tested at `:603`.
- **Attempt column.** The "None" shown in the Agent Tool Usage table for the scout and supervisor rows is Approach 1's own rendering of `stage.attempt`, since its scout row also has `attempt=None`. It is parity, not drift; the implementer correctly forwarded it to Iteration 16.

### Pillar 6: Substrate isolation and lifecycle. ✅ (not touched, compatible)
No MCP use. `finalise_run` depends on nothing the substrate provides, so it can render after `MCP_ERROR` and `SUPERVISOR_ERROR`, as the plan's Iteration 14 (`IMPLEMENTATION_PLAN.md:716`) requires.

### Pillar 7: Rendering, telemetry and logging. ✅

**D-B.**
- The Supervisor gets one ledger entry at run end (`:137`).
- With `None`, a WARNING is logged and the gap is never filled with zeros (`:134-135`).
- Each per-draft `stage_telemetry` is its own entries plus an equal share (`:178`, `:249`). AC3 holds to 1e-9 (test `:519`).
- Tokens add up exactly across drafts, with an odd remainder exercised (test `:538`).

**P11.**
- `_own_seconds` (`:302-311`) computes `max(duration − Σ tool_invocations.total_time_seconds, 0)`.
- `_latency_seconds` (`:314-324`) adds own durations, the Scout share and the Supervisor's own-time share. The `stage_telemetry` entries stay exactly as `amortise_shared_telemetry` produces them.
- Pinned by tests at 32.0, 17.0 (floored) and 17.0/15.0 (`None`), and by "Time Taken: 32.00s" in the rendered file.

**P12 and DM18.**
- `RunFinalisation` returns `persistence_failed`, `total_tokens` and `estimated_cost` over the whole ledger (`:147`). That includes failed calls, unsaved documents and the Supervisor; the hand sum is tested at `:850`.
- No totals line is logged, and `exit_code` and `supervisor_summary` are not set. The test at `:884` asserts that only `ledger` and `failures` change.

**D-I events.**
- **Draft rendered (INFO):** draft ID, path, `doc_id`, tokens and cost.
- **Compliance-alert WARNING:** draft ID, `doc_id`, attempts used and issues.
- **Candidate left unsaved (WARNING):** `doc_id` and last state, in rank order.
- **Draft render or write failure (ERROR):** draft ID, path, and the full error via `exc_info`.
- **Correlation.** Every line carries `(run_id, doc_id, attempt)`, asserted through the real `CorrelationFilter`.

**Save order.** It sorts on the sequence number, not the string, so `_999` comes before `_1000` (`:327-335`, test `:619`). This is consistent with `allocate_draft_id`.

### Pillar 8: Code quality. ⚠️ One Minor
- Imports are at the top and grouped; `save_draft as write_draft_file` follows §4's name-clash rule (`:38`).
- Every signature is annotated, and no `dict[str, Any]` crosses a module boundary.
- Frozen dataclasses for internal records follow the convention already in `src/tools.py:135,144,331,534`.
- **Finding A-1 (🟢 Minor, dead code):** `_RenderedAttempt.attempt` (`src/rendering.py:201`) is assigned at `:217` and never read. `_render_and_write` takes the correlation and failure attempt from `latest.attempt` at `:180-181`, before `_rendered_attempt` can raise, so the field is redundant.

---

## 3. Code review findings

| ID | Severity | File:lines | Finding |
| :--- | :---: | :--- | :--- |
| A-1 | 🟢 Minor | `src/rendering.py:197-203, 217` | `_RenderedAttempt.attempt` is never read (dead field, Pillar 8 "no dead code") |

Optional suggestions, which do not block:
- **O-1 (optional).** `_draft_metadata` (`:220-229`) takes 8 positional parameters, and `_render_and_write` (`:161-168`) takes 6. Making the trailing parameters keyword-only (`*,` after `rendered`, and after `share` respectively) would stop the call sites at `:144` and `:186` from silently swapping `own` and `share`, which have the same type.
- **O-2 (optional).** `SPECIFICATIONS.md:1037` still reads "New decisions made during implementation are added … as P11, P12 and so on". Now that both exist, "as P13 and so on" would read better. The docs test does not pin this sentence.
- **O-3 (optional).** `write_draft_file` returns the path it wrote, and `:189` discards it. An assertion against `result.path` would catch a future divergence between the allocated path and `output_dir / f"{draft_id}.md"`. Today the two are equal by construction in `save_draft` (Iteration 10).

---

## 4. Anti-patterns and risks

- **Autonomy leaks:** none.
- **Article text towards the Supervisor:** none.
- **Parity drift:** none.
- **State coupling:** none. Only `ledger` and `failures` are mutated, as tested.
- **Carried to Iteration 14 (not a defect here).** `finalise_run` lets a `ValueError` from `estimate_cost` propagate, as Approach 1 does. Drafts after the failing one are then not written, and no `RunFinalisation` is returned. It cannot be reached today: `load_model_rates` (`src/costs.py:93-110`) prices both `FAST_MODEL_ID` and `STRONG_MODEL_ID`, and every role, the Supervisor included, runs on one of them. Iteration 14's composition root must still not swallow the error silently, and must keep the Supervisor on the strong binding.
- **Carried to Iteration 14.** Call `finalise_run` exactly once per run. A second call appends a second Supervisor entry; the docstring at `:119-120` says so.

---

## 5. Remediation directives

1. **A-1.** Remove the unread `attempt` field from `_RenderedAttempt`, in `src/rendering.py` lines 197-203 and 217. Adjust its docstring to match. No test change is needed; the suite must stay green. The basis is the architect-review skill, Pillar 8 ("no dead code"), and `IMPLEMENTATION_PLAN.md` §1.3 DoD-4 in spirit.

No "Needs a decision" items.

---

# Iteration 11 — Architect Review (Stage 3, round 2)

**Scope re-audited:** the fix-round-1 changes in `src/rendering.py`, `tests/test_unit/test_rendering.py` and `.agents/docs/SPECIFICATIONS.md`, and everything they touch: the `_render_and_write` call site in `finalise_run`, `_rendered_attempt`, `_draft_metadata`, and the failure path through `_record_failure`.

**Verification run by the architect:**
- `uv run pytest -q`: **1067 passed**. That is 1063 in round 1, plus the new O-3 test, plus 3 instances of `test_document_uses_no_forbidden_term` that the docs test parametrises over this folder's `ARCHITECT_REVIEW.md`, `FIXES.md` and `QA_REVIEW.md`. It matches the implementer's report.
- `uvx ruff check src tests --no-cache`: **All checks passed**. That is 0 in-scope findings and 0 pre-existing debt.
- `git diff HEAD --stat -- src/template_engine.py src/tools.py src/schemas.py`: unchanged.
- `IMPLEMENTATION_PLAN.md` diff: only the orchestrator's P11/P12 rows and the §3 status change. The implementer made no edit there.

## 1. Overall verdict

**APPROVED.** A-1 is resolved, and O-1, O-2 and O-3 are applied correctly. No new defect.

## 2. Round-1 items

| ID | Status | Evidence |
| :--- | :---: | :--- |
| A-1 | ✅ Resolved | `_RenderedAttempt` (`src/rendering.py:213-218`) now has only `draft` and `qa_report`, and its docstring is accurate. The constructor is at `:232`. No reference to the removed field remains in `src/` or `tests/`. The correlation and failure attempt still come from `latest.attempt` (`:183-185`), before `_rendered_attempt` can raise. |
| O-1 | ✅ Applied | `_render_and_write(state, document, result, *, share, supervisor_share_seconds, rates)` is at `:163-171`. `_draft_metadata(document, result, rendered, *, own, share, totals, supervisor_share_seconds, rates)` is at `:235-245`. Both call sites pass by name (`:144-146`, `:189-198`), so `own` and `share` cannot be swapped silently. |
| O-2 | ✅ Applied | `SPECIFICATIONS.md:1037` now reads "as P13 and so on". |
| O-3 | ✅ Applied, sound | See §3. |

## 3. Is the O-3 check sound as placed?

**Yes.** The code is at `src/rendering.py:200-205`, and the test is `test_rendering.py:804-822`.

**What it can detect.**
- `write_draft_file` (Approach 1's `save_draft`, `src/template_engine.py:212-217`, unchanged) returns `Path(output_dir) / f"{draft_id}.md"`, and `output_dir` is `result.path.parent`.
- So the comparison fails in two cases: when `result.path.name` is not `f"{draft_id}.md"`, or when a future template engine stops building the path that way.
- Today `save_draft` sets `path=state.config.drafts_dir / f"{draft_id}.md"` (`src/tools.py:298`), so the check guards a state that is impossible by construction. That is the purpose of O-3.

**How a failure is handled.**
- The `RuntimeError` is raised inside the `persist` stage, inside the same `try` as the write.
- It is recorded in full and logged at ERROR with the traceback, like every other write failure. The draft counts towards `persistence_failed`, and the next draft is still written.
- This is the D-I "Draft render or write failure" path, so it adds no new failure mode. Control flow is untouched: code records the failure and goes on in save order, with no rerouting and no retry.

**The side effect of checking after the write.**
- On a mismatch, the file has already been written at `result.path.parent / f"{draft_id}.md"`.
- That is the convention path (`draft_{YYYYMMDD}_{XXX}.md`, Gate 7) in the same folder. It cannot collide, because `allocate_draft_id` numbered past the disk and the run.
- It preserves the content, and the failure message names both paths.
- A check before the write would discard the draft and would not cover a change in the template engine. Checking after the write is the better trade-off for a backstop.

**Test quality.**
- The test asserts the persist stage, `doc-b`, attempt 1, `builtins.RuntimeError`, the allocated path in the message, the single ERROR log with `stage=persist`, and that `doc-a` is still written.
- It does not pin where the file actually landed. That is an optional note (O-4), not a defect.

## 4. Pillar audit (delta from round 1)

- **Pillar 1 (flow).** ✅ Unchanged. The new branch only refuses, and records the refusal.
- **Pillar 2 (division of labour).** ✅ Unchanged. No new data reaches the Supervisor.
- **Pillars 3 and 6.** Not touched by this iteration.
- **Pillar 4 (attempt state).** ✅ Read-only, unchanged.
- **Pillar 5 (parity).** ✅ The template engine is unchanged, and the metadata mapping is unchanged.
- **Pillar 7 (rendering and logging).** ✅ The new failure goes through the existing D-I ERROR event, with `(run_id, doc_id, attempt)` correlation.
- **Pillar 8 (code quality).** ✅ The dead field is gone, and keyword-only parameters harden the internal calls. Annotations are complete, imports are unchanged, and ruff is clean.

## 5. Remediation directives

None required. Optional, non-blocking:
- **O-4.** In `test_a_draft_written_anywhere_but_its_allocated_path_is_a_persist_failure`, also assert `(saved_b.path.parent / f"{saved_b.draft_id}.md").is_file()`. That pins the trade-off the implementer accepted, namely that the content survives under its draft ID.

No "Needs a decision" items.

**Verdict: APPROVED**
