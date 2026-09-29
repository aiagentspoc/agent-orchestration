# Iteration 2 — Architect Review

**Iteration:** 2, Reused modules and triaged tests
**Stage:** 3, round 1
**Reviewer:** Lead Architect (architect subagent)
**Date:** 2026-09-29
**Criteria:** `.agents/skills/architect-review/SKILL.md` (eight pillars) and `.agents/skills/code-reviewer/SKILL.md` (gates and severities)

---

## 1. Overall verdict: **APPROVED WITH RESERVATIONS**

Nothing blocks this iteration. The copies are faithful:

* Six modules are byte-identical to Approach 1, ignoring CRLF.
* `schemas.py` differs only by the two removed models.
* `telemetry.py` holds exactly the five moved functions, byte for byte.
* The template is content-identical to Approach 1's (P8).
* No orchestrator code or control flow has leaked in.
* `uv run pytest` passes 317 tests and ruff is clean.

There are three reservations, all 🟢 Minor. Each is a stale P7/P8 mention in a file the orchestrator owns (`IMPLEMENTATION_PLAN.md`, `CLAUDE.md`, `.claude/agents/`). They are listed in `FIXES.md` as A1 and A2; A2 is the same item as QA's Q6. `FIXES.md` A3 records, for information only, that the Approach 1 baseline moved during the iteration. None of these is for the implementer. Five forward directives follow in §5. They cannot be done in this iteration, but they must reach the walkthrough so that Iterations 4, 6 and 7 pick them up.

---

## 2. What I verified myself

| Check | Method | Result |
| :--- | :--- | :--- |
| AC4 for the six copied modules | `diff <(tr -d '\r' < ../code-orchestration/src/$m.py) <(tr -d '\r' < src/$m.py)` for `costs`, `credentials`, `model_factory`, `diagnostics`, `mcp_client` and `template_engine` | All six identical |
| AC4 for `schemas.py` | Same `diff` | Deletions only: `18d17` and `31d29` (two `__all__` entries), `194,204d191` (`RevisionPayload`), `412,428d398` (`PipelineRun`) and `452d421` (`PipelineRun.model_rebuild()`). No other change |
| `telemetry.py` holds only the moved code | `diff <(sed -n '15,$p' src/telemetry.py) <(sed -n '165,325p' ../code-orchestration/src/orchestrator.py)` | Byte-identical. `grep '^def '` finds exactly `estimate_cost`, `_share`, `_share_capped`, `amortise_shared_telemetry` and `aggregate_draft_totals`. Lines 1 to 14 hold only the module docstring, the imports (`Mapping`, `Sequence`, `AgentTelemetry`, `ModelRate`, `StageTelemetry`) and `__all__`. Neither of the constants just before the span (`MAX_WRITER_ATTEMPTS`, `_SOURCE_FETCH_TOOL`, `orchestrator.py:158-162`) was copied |
| Template (P8) | `diff` of `.agents/templates/draft.md` against `../code-orchestration/.agents/templates/draft.md`, ignoring CR | Identical. LF, with a final newline |
| Copied tests | `diff` of each file against `../code-orchestration/tests/` | Byte-identical: `test_diagnostics`, `test_model_factory`, `test_template_engine`, `test_credentials`, `test_mcp_client`, `test_substrate_compatibility`, `conftest.py` and `support/__init__.py`. `test_costs.py` and `support/scripted.py` differ only by the model-ID repointing, and `scripted.py` also drops `ModelBuilder` and `scripted_model_builder`. `test_schemas.py` differs only by the triage |
| Model IDs are unchanged in value | `../code-orchestration/src/agents.py:71-74` against `src/credentials.py:25-26` | `SCOPE_PARSER_MODEL_ID` and `SCOUT_MODEL_ID` are `"gpt-5-mini"`, which is `FAST_MODEL_ID`. `WRITER_MODEL_ID` and `QA_LEGAL_MODEL_ID` are `"gpt-5.4"`, which is `STRONG_MODEL_ID`. `TEST_RATES` had four keys but only two distinct values, so the two-key dictionary is equal to it. No rate and no cost figure changed |
| Moved telemetry tests | Approach 1 `test_orchestrator.py:125-431`, with the ID substitution applied, diffed against `tests/test_unit/test_telemetry.py:20-` | Identical, except for the dropped "Batch 3" banner and the two unmoved agent-bound tests: `test_fresh_agent_per_invocation_reports_per_call_telemetry` and `test_scripted_agent_reports_zero_provider_latency_like_the_real_provider` |
| AC3 | `grep -rn "orchestrator" src tests` | Only docstrings and comments. No import of `src.orchestrator`, and no import of `src.agents` |
| Removed models | `grep -rn "RevisionPayload\|PipelineRun\b" src tests` | None outside `test_docs_consistency.py` |
| DoD-1 | `uv run pytest` | **317 passed**, 28.6 s. Per-file counts match the implementer's AC1 table (118 copied or moved tests) |
| DoD-2 | `uvx ruff check src tests --no-cache` | All checks passed |
| Subprocess hygiene | `Get-CimInstance Win32_Process` | Every live `uv`, `fastmcp` and `python` process is an MCP server whose parent is a `claude.exe` harness session. None is orphaned by pytest |
| Dependencies | `git diff --stat` | `pyproject.toml` and `uv.lock` are untouched |
| Sibling repositories | `find ../code-orchestration ../mcp-server -newermt …` | Nothing was written by this iteration. See §4.3 for a baseline change made outside it |

---

## 3. Pillar audit

1. **An agent owns the flow: ✅, with no leak.** `telemetry.py` is pure arithmetic over `Sequence[StageTelemetry]`. It loops over stages and drafts, never over sub-agents. It does not branch on status and holds no attempt counter; `MAX_WRITER_ATTEMPTS` was not carried over. `amortise_shared_telemetry` copies `stage.stage` through and does not interpret it (`src/telemetry.py:117-140`). The harness in `scripted.py` sequences nothing: `scripted_model_builder`, the one helper that encoded Approach 1's pipeline order ("consume turns in strict pipeline order"), is deferred.
2. **Division of labour: not touched by this iteration.** No `ToolResult` and no Supervisor exist yet.
3. **Custom agent tools: not touched by this iteration.** One forward risk: the D20 fresh-agent regression test was not moved (§5, F2).
4. **Guardrails and attempt state: not touched by this iteration.**
5. **Benchmark parity: ✅.**
   * The cost basis is reused unchanged: `costs.py` is identical, and the `estimate_cost` and amortisation bodies are byte-identical.
   * The template is content-identical (P8).
   * The model IDs are unchanged: `credentials.py` is identical.
   * Prompts and tool binding are not touched until Iteration 6.
6. **Substrate isolation and lifecycle: ✅** as far as it goes. `mcp_client.py` is identical. The only `import server` is in the drift test, `tests/test_integration/test_substrate_compatibility.py:12`, which is the sanctioned use; business logic never imports `mcp-server`. The substrate tests closed their sessions.
7. **Rendering, telemetry and logging: ✅** for the parts this iteration moves.
   * `extract_telemetry` is not here, correctly: it stays in `agents.py`, for Iteration 6.
   * The equal-share rule and `aggregate_draft_totals` are Approach 1's.
   * Logging is not touched until Iteration 3.
8. **Code quality: ✅.** Ruff (configured) reports 0 findings. `telemetry.py` has no findings under `--select ANN,E402`, its imports are grouped and at the top of the file, it has an honest module docstring citing D-J and `SPECIFICATIONS.md` §2.1, and its `__all__` lists exactly the three public functions. The new `test_telemetry.py` is fully annotated and its docstring states the ID repointing honestly.

### Code-reviewer gates, where they apply

| Gate | Status | Notes |
| :---: | :---: | :--- |
| 1 TDD | ✅ | Each Red was a `ModuleNotFoundError` on the module under test. For telemetry, the harness was copied first, so the Red failed on `src.telemetry` and not on a fixture: a legitimate Red |
| 2 Zero-token | ✅ | Only `ScriptedModel` and `FailingModel` are used. The D16 autouse isolation in `tests/conftest.py` is active. `-m 'not live'` is still in `addopts` |
| 3 Contracts | ✅ for this iteration | `RevisionPayload` and `PipelineRun` are gone. **Stated explicitly:** `PipelineExitCode` and the `scope_parser` stage literal (`src/schemas.py:297`) still exist. Gate 3 lists `PipelineExitCode` as removed, but `IMPLEMENTATION_PLAN.md:312` says "Every other Approach 1 model stays as it is for now", and Iteration 4 does the rename. This is transitional by plan, not a defect |
| 4 Guardrails | n/a in this iteration | |
| 5 Telemetry | ✅ | This is the cost arithmetic only |
| 6 No article text for the Supervisor | n/a in this iteration | |
| 7 Drafts and logging | ✅ | The template is copied. Everything else is n/a in this iteration |
| 8 Python and subprocess safety | ✅ | No orphaned subprocess. `pathlib.Path` throughout the copied harness |

---

## 4. Code review findings, anti-patterns and risks

### 4.1 Ruff

* **Configured rule set** (`uvx ruff check src tests --no-cache`): **0 in-scope findings (blocking) and 0 pre-existing (deferred).**
* **Opt-in `--select ANN,E402`**, for information only. There are 75 ANN findings and **0 E402**:
  * `tests/test_unit/test_template_engine.py`: 24;
  * `tests/support/scripted.py`: 21;
  * `tests/test_integration/test_mcp_client.py`: 21;
  * `src/mcp_client.py`: 9.

  By rule code: ANN201 38, ANN401 20, ANN001 11, ANN204 3, ANN003 2, ANN202 1. Every one of them is in code copied verbatim from Approach 1, which AC4 requires to stay byte-identical, so none blocks the iteration. None is in `telemetry.py`, `test_telemetry.py`, `test_module_structure.py`, `test_costs.py` or `test_schemas.py`.

### 4.2 Documentation consistency (P7 and P8)

* `SPECIFICATIONS.md` records P7 and P8 in five places, consistently with `IMPLEMENTATION_PLAN.md` §2:
  * line 4;
  * line 29, the contents row;
  * line 48, the Template row;
  * §8.3, the heading and the P7 and P8 rows;
  * the closing sentence, which now reads "P9, P10".
* The docs test pins both statements (`tests/test_unit/test_docs_consistency.py:184-185`) and checks the order of §8.3 against `IMPLEMENTATION_DECISIONS`.
* Citing "`QUESTIONS.md` Q1/Q3" in §8.3 avoids confusion with the design questions Q1 to Q12 in §8.1. This is a good call.
* **Remaining stale text**, all in files the orchestrator owns (`FIXES.md` A1 and A2):
  * `IMPLEMENTATION_PLAN.md:161` still calls the template "unchanged", which contradicts P8 and `SPECIFICATIONS.md:48`. `SPECIFICATIONS.md` wins, and I report the disagreement here as the skill requires.
  * `IMPLEMENTATION_PLAN.md:817` has no traceability row for P7 or P8.
  * `CLAUDE.md:14` and `.claude/agents/{architect,implementation,qa}.md` still say "P1 to P6".
* `IMPLEMENTATION_PLAN.md:262` ("P1 to P6") describes what Iteration 1's Red tested. It is history and should stay as written.

### 4.3 Risk: the Approach 1 baseline changed during this iteration (information, not a defect)

`../code-orchestration/` gained commit `1734096` on 2026-09-29 at 00:23 +0530 (author Saksham Agrawal, "fix(phase-7): one run clock, QA-Legal source fetch, and rewritten drafting prompts"). The working tree now equals that HEAD for `src/` and `tests/`.

* **Effect on Iteration 2: none.** The commit does not touch any of the modules copied here. In `orchestrator.py` it leaves the moved span (`estimate_cost` through `aggregate_draft_totals`) unchanged, and in `test_orchestrator.py` it changes only the unmoved fresh-agent test. Every copy matches the on-disk baseline, and would equally have matched `3b123e4`.
* **Effect downstream.** Two premises no longer hold:
  * **QUESTIONS.md Q4.** It assumes "12 stale prompt-text failures in `test_agents.py`", but the commit message says those twelve tests were re-pinned.
  * **The plan header's "221 tests" baseline.**

  The commit also rewrites `WRITER_SYSTEM_PROMPT` and `QA_LEGAL_SYSTEM_PROMPT` and widens `QA_LEGAL_TOOL_NAMES`. Under P7, Iteration 6 takes whatever is on disk, so this is settled and needs no decision. But the Iteration 6 pre-flight must re-derive the prompt-parity targets and the Q4 test triage from the new HEAD, not from Q4's text. I could not confirm that the Approach 1 suite now passes, because running tools inside `../code-orchestration/` is out of bounds for this audit.

### 4.4 Anti-patterns

None found. No autonomy leak, no parity drift, no state coupling, and no article-text path.

---

## 5. Remediation directives

**For this iteration** (`FIXES.md` A1 and A2, plus A3 for information): A1 and A2 are 🟢 Minor, non-blocking and orchestrator-owned. The implementer must not edit these files, which is consistent with its brief.

* A1 is the §4 template line.
* A2 is the traceability row and the four harness pointers. It is the same item as QA's Q6, and I concur with its option A. On QA's Q5, I concur with option A.

**Forward directives.** They cannot be done in this iteration, and the orchestrator should copy them into `WALKTHROUGH.md` under *Deviations* and *Forward notes*.

* **F1 (Iteration 6): one cost test is temporarily a tautology.** `test_costs.py::test_default_model_rates_cover_every_worker_model_id` guards against "a model rename that outruns the rate table". Keyed on `FAST_MODEL_ID` and `STRONG_MODEL_ID`, it is now a tautology, because `DEFAULT_MODEL_RATES` is built from those same two constants (`src/costs.py:32-40`). Once `src/agents.py` exists, repoint `test_costs.py:13,35`, `tests/support/scripted.py:24,496-499` and `test_telemetry.py:14` back to the role IDs. In Iteration 13, add the Supervisor's model ID to the covered set. (`SPECIFICATIONS.md` §1, cost basis; D-J.)
* **F2 (Iteration 6 or 7): restore two unmoved tests.** Restore `test_fresh_agent_per_invocation_reports_per_call_telemetry`, Approach 1's D20 guard, against the adapted runners. `aggregate_draft_totals` is correct only if every sub-agent is fresh per call (see its own docstring, `src/telemetry.py:151-154`), and pillar 3 requires exactly that. Restore `test_scripted_agent_reports_zero_provider_latency_like_the_real_provider` alongside it.
* **F3 (Iteration 4): isolate the Supervisor's effort variable.** Add `HSE_MODEL_SUPERVISOR_REASONING_EFFORT` to `_ISOLATED_ENV_VARS` in `tests/conftest.py:26-41`, in the same Red that adds the Supervisor effort to `ReasoningSettings`, or D16 isolation has a gap.
* **F4 (Iteration 4): adapt three tests to the narrowed stage literal.** Narrowing `StageTelemetry.stage` breaks:
  * `test_template_engine.py::test_format_stage_telemetry_renders_markdown_table`;
  * `test_telemetry.py::test_amortise_shared_telemetry_assigns_remainder_to_first_draft`;
  * `test_telemetry.py::test_amortise_never_gives_a_draft_more_cached_than_input_tokens`.

  All three use `stage="scope_parser"`. Changing that data to `"scout"` or `"supervisor"` is a test-data adaptation that §1.5 allows. `scripted.VALID_SCOPE_ARGS` carries `time_window` and must follow the `PipelineScope` amendment.
* **F5 (Iteration 7): restore the deferred helper.** Restore `scripted_model_builder` against a `ModelBuilder` alias in the new modules. Key it per role or per effort, not per model ID alone, if the Supervisor, the Writer and QA-Legal must be scriptable independently: all three are `gpt-5.4`.

---

## Round 2 (re-review after fix round 1), 2026-09-29

### R2.1 Verdict: **APPROVED**

A1 and A2 are closed on disk, and Q5 is recorded consistently as P9. Nothing regressed: the six copied modules and the template are still identical to Approach 1, `uv run pytest` passes 320 tests, and ruff is clean. One new 🟢 Minor item, A4, is open for the orchestrator. It concerns the Iteration 7 section of the plan and does not block this iteration.

### R2.2 Verification of the round-1 items

| Item | Check | Result |
| :--- | :--- | :--- |
| A1 | `IMPLEMENTATION_PLAN.md:162` | Reads `draft.md (Approach 1's current template, P8)`. It is now consistent with P8 (`IMPLEMENTATION_PLAN.md:118`) and `SPECIFICATIONS.md:48`. **Closed** |
| A2, traceability | `IMPLEMENTATION_PLAN.md:818-821` | `P1 to P6`, then `| P7 | 2, 6, 16 |`, `| P8 | 2 |` and `| P9 | 7 |`. **Closed** |
| A2, harness pointers | `git diff --unified=0 CLAUDE.md .claude/agents/` | Exactly one line changed in each of the four files, P1–P6 (or P1 to P6) to P1–P9 (or P1 to P9), at `CLAUDE.md:14`, `architect.md:18`, `implementation.md:16` and `qa.md:18`. There is no other change. This was done by the orchestrator under the user's own answer to Q6 (`QUESTIONS.md:63`). The implementer was right to decline them. **Closed** |
| Q5 to P9 | Plan §2 row (`IMPLEMENTATION_PLAN.md:119`) and `SPECIFICATIONS.md` §8.3 row (line 1030) | Both have the same bold statement. `SPECIFICATIONS.md` has P1 to P9 at line 4, line 29 (the contents row) and line 1016 (the §8.3 heading). Its closing sentence reads "P10, P11". `AGENTS.md:15` and both skills say P1 to P9. A search of the repository finds no "P1 to P8" or "P9, P10". The remaining "P1 to P6" at `IMPLEMENTATION_PLAN.md:263` records what Iteration 1 tested, and `.agents/scratchpad/plan.md:4` is superseded history. Both are correct as they stand |
| P9 pinned | `tests/test_unit/test_docs_consistency.py:177-187` | `IMPLEMENTATION_DECISIONS` gains P7 to P9. `re.escape` handles the backticks in the P9 statement. Both the order test and the per-record statement test cover P9. The Red the implementer reported (a missing §8.3 row) is a legitimate Red, not a typo |
| `src/mcp_client.py` still verbatim | `diff` against `../code-orchestration/src/mcp_client.py`, ignoring CR | Identical. It still has 9 ANN findings, which are the ones P9 schedules for Iteration 7 |
| No regression in the copies | The same `diff` for `costs`, `credentials`, `model_factory`, `diagnostics`, `template_engine` and `.agents/templates/draft.md` | All identical. The Approach 1 HEAD is still `1734096` |
| DoD-1 | `uv run pytest -q` | **320 passed**, 29.1 s. This is 317 from round 1 plus 3, from the parametrised P7 to P9 rows |
| DoD-2 | `uvx ruff check src tests --no-cache` | All checks passed |
| Dependencies | `git diff --stat -- pyproject.toml uv.lock` | Untouched |

### R2.3 Pillar audit (delta)

There is no change to `src/` since round 1, so pillars 1 to 8 stand as assessed in §3. The fix round touched only documents and one docs test. Pillar 5 (parity) is reinforced: P9 limits the one permitted divergence from Approach 1's `mcp_client.py` to annotations, and the plan row says "behaviour and every result shape stay identical".

### R2.4 New finding

* **A4 (🟢 Minor, orchestrator-owned, non-blocking): the Iteration 7 section does not carry P9.**
  * P9 names Iteration 7 in three places: its §2 row, its "applies to" column and its traceability row (`IMPLEMENTATION_PLAN.md:119, 821`). But the Iteration 7 section (`IMPLEMENTATION_PLAN.md:450-496`) has no step or acceptance criterion for the annotations.
  * Every other iteration-bound decision is cited inline in its section, for example P1 in Iteration 6 and P2 in Iteration 8.
  * Without an inline step, the Iteration 7 implementer's brief can miss the work. The remedy is in `FIXES.md`. It can be applied now, in the Iteration 2 commit, or at the Iteration 7 pre-flight. Either way it is forward note **F6**.

### R2.5 Disposition of the walkthrough-owned items

I accept that QA-m1, QA-m2, A3 and F1 to F5 are recorded by the orchestrator in `WALKTHROUGH.md` at Stage 4, under *Deviations* and *Forward notes*. None of them needs a change to `src/` or `tests/` in this iteration. Add F6 (A4) to the same list if the orchestrator does not fix the plan now.

### R2.6 Ruff

* **Configured rule set:** **0 in-scope (blocking) and 0 pre-existing (deferred).**
* **Opt-in `--select ANN,E402`**, for information only: 75 ANN findings and 0 E402, unchanged from round 1. By rule code: ANN201 38, ANN401 20, ANN001 11, ANN204 3, ANN003 2, ANN202 1. All of them are in verbatim copies. The 9 in `src/mcp_client.py` are scheduled by P9.
