# Iteration 13 — Supervisor agent: walkthrough

**Dates:** 2026-10-01 to 2026-10-05 · **Branch:** `approach-2/implementation` · **Plan section:** `IMPLEMENTATION_PLAN.md` §5, Iteration 13

## 1. Overview

Iteration 13 adds the agent that owns the flow, `src/supervisor.py`. It has three parts:

* **The system prompt.** It holds every §7.4 item:
  * the role;
  * the four tools;
  * the scope rules, adapted from Approach 1's ScopeParser;
  * D-C's decision table, row for row;
  * the never-compare rule;
  * the run-level priorities;
  * the limits;
  * violations;
  * finishing.

  It never holds the current date, and never tells the Supervisor to work on article text.
* **`build_supervisor_agent(model, tools, *, max_drafts, hooks)`.** It builds the Supervisor with:
  * `SequentialToolExecutor`;
  * exactly the four tools;
  * one `LoggingHooks("supervisor")`, followed by the caller's hooks;
  * no console callback.
* **`run_supervisor(agent, prompt, *, today, …)`.** It makes one invocation with the user turn `Current date: YYYY-MM-DD`, a blank line, then the raw prompt. It returns the final text and the Supervisor's `AgentTelemetry`.

Code still enforces every hard rule; the prompt only states them. Nothing in the module calls a tool or chooses a step.

The iteration was held once after review round 2 (Q10). The user answered on 2026-10-05: complete Iteration 13 now, and carry the minor test-side items into Iteration 14.

## 2. Files changed

| File | Status | Responsibility |
| :--- | :--- | :--- |
| `src/supervisor.py` | New, 308 lines | The constants, the prompt sections and `build_supervisor_prompt`, `build_supervisor_agent`, `SupervisorOutput` and `run_supervisor` |
| `tests/test_unit/test_supervisor.py` | New, 120 tests | The builder, the prompt items, the forbidden-content checks (with their own hit and no-hit tests), `run_supervisor`, the scripted end-to-end flow, the fatal-stop and provider-error cases |
| `tests/test_unit/test_docs_consistency.py` | Edited, +7 tests | AC1 (the decision table byte for byte) and AC3 (the priorities exactly, and the attempt cap D-C states), each for no ceiling and for a ceiling; a check that an invented third priority is caught |
| `tests/test_unit/test_module_structure.py` | Edited, +1 test | `EXPECTED_MODULES` gains `src.supervisor`. `src.supervisor` imports no substrate client and no concrete model |
| `.agents/docs/IMPLEMENTATION_PLAN.md` | Edited by the orchestrator | The §3 tracker only |
| `.agents/tasks/QUESTIONS.md` | Edited by the orchestrator | Q10, raised and answered |
| `.agents/tasks/iteration-13/` | New | `ARCHITECT_REVIEW.md`, `QA_REVIEW.md`, `FIXES.md` and this walkthrough |

**What `src/supervisor.py` holds:**
* `SUPERVISOR_MODEL_ID = "gpt-5.4"` and `SUPERVISOR_REASONING_EFFORT = "medium"`.
* **The prompt** is built from `Final` sections joined with line breaks. Only `_limits(max_drafts)` depends on the run. The sections:
  * **Role.** The Supervisor supervises agents, not drafts. It never reads, judges or edits article text, never writes feedback for the Writer, never writes Markdown, and has no substrate access.
  * **Tools.** The four tools, named from the `src.guardrails` constants. Their §7.1 descriptions reach the model in each tool's own specification, so they are not repeated.
  * **Scope rules.** Approach 1's ScopeParser rules, adapted to the five `PipelineScope` fields:
    * dates are resolved against the current date in the user turn;
    * the default window is the past 3 months;
    * `date_to` is the current date unless the user named an end;
    * an empty `sources` means all sources;
    * `sector_constraints` are lowercase;
    * `max_drafts` is set only for a stated count or a singular definite request;
    * DM3: the scope's limit comes from the user's words, never from the `--max-drafts` ceiling.
  * **Decision policy:**
    * the D-C basis;
    * the never-compare rule;
    * the free-text nature of `issues`;
    * D-C's ten-row decision table, rendered from its cells by `_markdown_table`;
    * D-C's sentence on how a failed Writer call is shown;
    * the two run-level priorities, rendered by `_numbered_list`.
  * **Limits.** `MAX_ATTEMPTS_PER_DOC` Writer attempts per document, and this run's draft ceiling or "no ceiling".
  * **Violations** and **Finishing**.
* **`build_supervisor_agent`** passes `hooks` as a required keyword argument, so the caller cannot forget `FatalStopHook`.
* **`SupervisorOutput(summary, telemetry)`** is a frozen dataclass, not one of §6's models.
* **`run_supervisor`:**
  * It makes exactly one `agent(user_turn)` call, catches nothing and does not branch on `stop_reason`.
  * The summary is the final message's text blocks, joined with `"\n"`.
  * The telemetry comes from `extract_telemetry`, labelled with `model_id` and `reasoning_effort`. These are keyword arguments, defaulting to the role constants.
  * It leaves `RunState` alone: no `supervisor_summary`, and no ledger entry. `finalise_run` appends the Supervisor's one entry.

`src/tools.py`, `src/agents.py`, `src/hooks.py`, the sub-agent prompts and every other `src` module are unchanged.

## 3. TDD record

Tests that passed on their first run were shown able to fail with temporary mutations, which were then reverted. Each mutation is recorded in the review artifacts.

| # | Behaviour | Red, or how the test was shown able to fail | Green added |
| :---: | :--- | :--- | :--- |
| 1 | Module and constants | `ModuleNotFoundError: src.supervisor`. Setting `gpt-5-mini`/`high` failed 2 tests | The two constants |
| 2 | Builder properties | `ImportError`. Removing the executor or `callback_handler=None` failed tests | `build_supervisor_agent` |
| 3 | Hooks | Mutations failed tests: caller hooks registered first, `LoggingHooks` registered twice, `hooks=()` as a default | Already in the builder |
| 4 | Prompt items, one at a time | Each was Red on its missing phrase: Role, Tools, six scope rules, the decision table (AC1), the basis and never-compare rule, the priorities (AC3), Limits (AC3; Red `caps == []`), Violations, Finishing. Rewording or deleting a table row, or rewording a priority, failed the docs tests | The prompt sections |
| 5 | Forbidden content | 11 forbidden sentences were injected one at a time, and each failed its own test | The checks, with synthetic-string tests |
| 6 | `run_supervisor` | `ImportError`. `prompt.strip()` failed the user-turn test; dropping `reasoning_effort` failed the telemetry tests | `run_supervisor` |
| 7 | Scripted flow | Mutations failed tests: binding three tools, an empty summary, leaking `draft` through `supervisor_view` | Already met |
| 8 | Cancelled and error cases | Mutations failed tests: catching `RuntimeError`, raising on `stop_reason == "cancelled"` | Already met |
| 9 | Import boundary | Adding an `mcp_client` import failed it | The structure test |
| 10 | Fix round 1, QA-M1 | All 15 realistic article-work probes and 4 Writer-feedback probes failed against the old patterns | Verb-inflected, determiner-tolerant patterns with a verb-scoped negation (`_affirmative_matches`), and hit and no-hit parametrized tests |
| 11 | Fix round 1, QA-m1 | 4 run-bound and 3 failed-call phrasings failed | Wider budget and violation-bound patterns; failed-call rules need a Scout or QA-Legal name with a lower-case failure word, so the `ERROR` status is spared |
| 12 | Fix round 1, QA-m2 | An invented third priority passed the old subset check | `_priorities_disagree` requires the prompt's list to equal D-C's exactly |
| 13 | Fix round 1, QA-m3 | — | The no-article-text check covers every article field, `tdi_cta` included |

`src/supervisor.py` was not changed by the fix round. The strengthened checks find nothing in the prompt at no ceiling or at ceilings 1, 2 and 3.

## 4. Test results

The orchestrator ran the suite fresh, after this walkthrough was written:

* `uv run pytest -q`: **1244 passed**, 0 failed, 0 errors.
* `uv run pytest tests/test_unit/test_supervisor.py -q`: **120 passed**.
* Tests added by this iteration: **+133 net** over Iteration 12's 1111:
  * 120 in `test_supervisor.py`;
  * 7 new in `test_docs_consistency.py`, plus 4 forbidden-term cases, one per new `.md` in `iteration-13/`;
  * 1 in `test_module_structure.py`;
  * 1 `test_annotations.py` case for `src/supervisor.py`.
* `uvx ruff check src tests`: **All checks passed!**
* **Runtime.** The full suite took about 115–120 s in review, against about 32 s before. Both reviewers traced the difference to the 13 `test_mcp_client.py` integration tests, each 6–8 s spent starting the substrate server on a loaded machine. Those tests are unchanged since Iteration 2. The unit tests alone run in about 30 s, and the new checks take milliseconds on the real prompt. The orchestrator's fresh run on 2026-10-05 took 37.6 s for the whole suite.
* No live test or live command was run. Every model is a `ScriptedModel` or `FailingModel`.

## 5. Acceptance criteria

| Criterion | Status | Evidence |
| :--- | :---: | :--- |
| Red: the builder uses `SequentialToolExecutor`, exactly the four tools, the strong binding with the `ReasoningSettings.supervisor` effort, `callback_handler=None` | ✅ | The builder tests. The binding and effort are pinned through the constants, the settings default and `agent.model is model`; the model itself is built in Iteration 14 |
| Red: the system prompt contains every listed element | ✅ | `test_prompt_covers_the_section_7_4_item`, 17 items × 2 ceilings; `test_prompt_states_the_draft_ceiling_or_no_ceiling` |
| Red: no current date, and no instruction to review, score or improve article text | ✅ | `test_prompt_holds_no_date`, `test_supervisor_module_never_reads_the_clock`, `test_prompt_never_tells_the_supervisor_to_work_on_article_text` and the other forbidden-content tests |
| Red: `run_supervisor` user turn and return | ✅ | `test_user_turn_is_the_current_date_then_the_raw_prompt_verbatim`, `test_run_supervisor_returns_the_final_text_as_the_summary`, the telemetry tests |
| Red: the scripted flow leaves one saved `DocumentRecord` | ✅ | `test_scripted_supervisor_takes_one_document_from_scout_to_save`, `…telemetry_counts_each_of_the_four_tools`, `…never_receives_article_text` |
| **AC1:** each decision-table row appears in the prompt, checked against the rows taken from `SPECIFICATIONS.md` | ✅ | `test_supervisor_prompt_copies_the_d_c_decision_table_row_for_row`: one table, every line byte for byte |
| **AC2:** the tool descriptions match §7.1 word for word, and the prompt covers every §7.4 item | ✅ | `test_supervisor_model_receives_the_section_7_1_descriptions_word_for_word`, and the §7.4 item tests |
| **AC3:** D-C and the prompt agree on the attempt cap and the priorities | ✅ | `test_supervisor_prompt_states_the_attempt_cap_d_c_states`, `test_supervisor_prompt_states_the_d_c_run_level_priorities_verbatim`, `test_priorities_check_catches_an_invented_extra_priority` |
| Stop condition: a table row that cannot be written without a new rule | Not met | Every row maps to an existing guardrail or view (pre-flight §2.4) |
| DoD-1 to DoD-6 | ✅ | §4 above; every new function and branch is tested; the docs test passes; this file |

## 6. Decisions and deviations

**Decisions (§1.5, or settled from the sources in the pre-flight):**
* **Tools item (X1).** The prompt names the four tools; it does not repeat or paraphrase their descriptions, which reach the model in each tool's specification.
* **Binding and effort (X2).** These are tested at this layer through the constants and the `ReasoningSettings` default, because the model is injected. Iteration 14 builds it.
* **`run_supervisor` signature and return (X3).** `model_id` and `reasoning_effort` are keyword arguments with defaults, as in `run_writer`, so an `.env` override is labelled correctly. The return is a frozen `SupervisorOutput`. The summary is the text blocks joined, not `str(result)`.
* **Hooks.** The builder registers `LoggingHooks("supervisor")` first, then the caller's hooks, and `hooks` is required.
* **Silence left unfilled (X4).** The sources give no rule for a failed `scout_tool` or `qa_tool` call, and the prompt adds none; a test pins that. This is recorded so the user can rule on it after the live runs, if it matters.
* **Rule numbers (X5)** inside the table rows are copied verbatim. No rules list is added.
* **The failed-Writer sentence (X6)** is D-C's, with "to the Supervisor" changed to "to you".
* **Recency words (X7).** "recent", "lately", "current", "latest" and "most recent" name no period, so they give the past 3 months. This was Approach 1's dropped `time_window_specified` rule; it is folded into the default-window rule, so Prompt B in Iteration 16 behaves as in Approach 1.
* **The `max_drafts` rule (X8)** keeps Approach 1's wording, and DM3 is stated explicitly.
* **Approach 1's worked scope example was dropped (architect O2).** It used `time_window` and literal dates, both of which the prompt must not carry. It is recorded here because prompt content is never a free decision.
* **Two clarifying phrases the reviewers accepted.** Both add no rule:
  * "(the `run` object of every result)" names the JSON key `RunContext` arrives under (§6.4);
  * "`issues` is free text…" is D-C's own sentence.

**Carried into Iteration 14 (Q10 = A):** minor items in `tests/test_unit/test_supervisor.py`, to be applied test-first there:
* **A1 / QA-m4:** the article-work pattern backtracks catastrophically on comma-heavy text. The fix is `\S+` → `[^\s,]+`. The real prompt is unaffected.
* **A2:** the pattern misses inflections such as "scoring" and "rewrote".
* **A3:** a nearby negation can cancel a different verb's match.
* **A4 / QA-m5:** the `article_body` text check can never fire. The key check still enforces D-F.
* **A5:** a dead regex alternative.
* **QA-m6:** further missed phrasings (optional).

**Forward notes for Iterations 14 and 15:**
* After a provider error the Supervisor returns no telemetry; the spec settles this only for sub-agents (§6.6).
* After a fatal stop the summary is `""`; Iteration 14 decides whether `supervisor_summary` stores `""` or `None`.
* In strands 1.55.1, `AfterToolCallEvent` callbacks run in reverse order, so "Fatal abort triggered" is logged before "Tool call completed" for the fatal tool.

**Deviations:** none from the plan.

## 7. Review

Two rounds were used. A rate limit interrupted both round 1 reviewers; each was resumed to finish.

**Round 1.**
* **Architect: APPROVED.** It had no blocking findings, and traced the prompt sentence by sentence to its sources. Its optional notes:
  * **O1:** keep the rule cross-references verbatim. Kept.
  * **O2:** record the dropped worked example. Recorded in §6.
  * **O3:** `SupervisorOutput` is fine.
* **QA: FAIL.** All findings were test-side; the prompt was correct.
  * **QA-M1 (Major):** the article-work and Writer-feedback checks missed all 12 realistic forbidden sentences tried. **Resolved.**
  * **QA-m1:** the tool-call-budget and failed-call checks missed common wordings. **Resolved.**
  * **QA-m2:** the priorities check missed an invented third priority. **Resolved.**
  * **QA-m3 (optional):** cover `tdi_cta`. **Resolved.**

**Round 2.**
* **Architect: APPROVED.** It raised minor items A1–A5 and confirmed `src/supervisor.py` was unchanged by the fix round. It traced the slower suite to the integration tests, not the new regexes.
* **QA: PASS.** It raised minor items QA-m4 to QA-m6, with no false positives on harmless sentences. The fix pass had replaced QA's round 1 items in `FIXES.md` with a pointer; QA restored them there as the record.

Items still open after round 2 led to **Q10**. The user chose to complete the iteration and carry the items into Iteration 14.
