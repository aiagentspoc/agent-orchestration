# Iteration 13 — Supervisor agent: architect review, round 1

**Reviewer:** architect (Stage 3, round 1), 2026-10-01
**Scope:** `src/supervisor.py` (new), `tests/test_unit/test_supervisor.py` (new), `tests/test_unit/test_docs_consistency.py` (+34 lines), `tests/test_unit/test_module_structure.py` (+8 lines). The `IMPLEMENTATION_PLAN.md` diff is the orchestrator's §3 status row only.
**Checks run:** `uv run pytest -q`: 1201 passed (baseline 1111, +90), 0 failures. `uvx ruff check src tests --no-cache`: all checks passed.

## 1. Overall verdict

**APPROVED.** No blocking finding. The Supervisor owns the flow: the module builds one agent and makes one call, and no code chooses a tool. I read the prompt rendered for `None` and for a ceiling of 2, section by section, against §7.4, D-C and Approach 1's `SCOPE_PARSER_SYSTEM_PROMPT` (`../code-orchestration/src/agents.py` l.110–170). Every sentence traces to a source. The two additions the implementer flagged add no rule. Three optional notes and three forward risks for Iterations 14 and 15 follow; none of them blocks.

## 2. Pillar audit

### Pillar 1: an agent owns the flow — ✅
* `run_supervisor` (`src/supervisor.py` l.306) makes one `agent(...)` call. There is no loop, no branch on `stop_reason` and no tool call from code. Exceptions propagate, as the docstring says (l.288–289).
* `build_supervisor_agent` (l.254–261) only assembles the agent. No Graph, Swarm or Workflow is imported anywhere.
* The scripted-flow tests (`test_supervisor.py` l.538–597) put the sequence in the Supervisor's script, `_flow_supervisor`. The code under test does not sequence anything.

### Pillar 2: division of labour and D-F — ✅
* **Prompt.** The Role (l.44–56) restates §1.1's "Never does" column: never read, judge or edit article text, no feedback for the Writer, no Markdown, and no substrate access (DESIGN.md §3). No clause asks the Supervisor to review, score or improve text. `test_prompt_never_tells_the_supervisor_to_work_on_article_text` and its synthetic cases (l.366–400) cover this, and they spare the Role's own negation.
* **The only text the Supervisor reads** is the QA report's `issues` ("Read the latest report's issue text to judge whether an issue is one the Writer can fix", l.172–173). This is D-C l.370 word for word, and it concerns QA text, not article text.
* **Context.** `test_scripted_supervisor_never_receives_article_text` (l.581–597) checks the real tool results the scripted Supervisor received:
  * no `DRAFT_ARGS` headline, body or summary appears in any message;
  * `FORBIDDEN_SUPERVISOR_KEYS` is absent from all four results.

  Gate 6's Supervisor-context scenario arrives early, ahead of Iteration 15.
* **Import boundary.** `src.supervisor` imports no `src.mcp_client`, no `src.model_factory` and no concrete provider (`test_module_structure.py`, new test).

### Pillar 3: custom agent tools — not touched by this iteration
The builder receives `build_tools`' four tools unchanged. `test_supervisor_agent_has_exactly_the_four_tools_and_no_substrate_tool` pins the names and their order.

### Pillar 4: guardrails and attempt state — ✅ (prompt side only)
* The prompt states the rules; code enforces them. The Decision policy comment (l.160–161) says so.
* There is no tool-call budget and no bound on violations (DM16). `test_prompt_sets_no_tool_call_budget_and_no_violation_bound` pins this.
* The attempt cap is interpolated from `MAX_ATTEMPTS_PER_DOC` (l.208–213), never typed as a literal.

### Pillar 5: benchmark parity — ✅
* **Model and effort.** `SUPERVISOR_MODEL_ID = "gpt-5.4"` equals `STRONG_MODEL_ID`. `SUPERVISOR_REASONING_EFFORT = "medium"` equals `ReasoningSettings.supervisor`'s default. Both are tested (l.106–114).
* **Effort in telemetry.** `run_supervisor` records the effort it is given, so an `.env` override is recorded as run. The pattern matches Approach 1's `run_scope_parser` (`../code-orchestration/src/agents.py` l.625–667).
* **Execution.** `SequentialToolExecutor` is used (D-H). The test asserts its type.
* **Tool descriptions (AC2).** The specs the scripted model received equal `SUPERVISOR_TOOL_DESCRIPTIONS`. That dict is pinned against §7.1 by `test_specification_states_the_four_supervisor_tool_descriptions_word_for_word`, so the chain to the spec is unbroken.
* **Prompt.** See §2a.

### Pillar 6: substrate isolation and lifecycle — ✅
* **Hook wiring.** Exactly one `LoggingHooks("supervisor")` is built per Supervisor, followed by the caller's hooks (l.259).
* **`FatalStopHook`** is passed by the caller, not built here. `hooks` is a required keyword-only argument, and a test pins that.
* **Fatal stop.** `test_fatal_stop_returns_an_empty_summary_with_the_telemetry_intact` shows that D-D.1 holds through the real builder:
  * one model call;
  * the second tool never runs;
  * `fatal_error` is still set;
  * no exception escapes.

### Pillar 7: rendering, telemetry and logging — ✅
* **Telemetry reader.** `extract_telemetry` is still the only reader of `get_summary()` (l.308).
* **No double ledger entry.**
  * `run_supervisor` leaves `state.ledger` and `state.supervisor_summary` alone; `test_run_supervisor_leaves_the_run_state_to_the_composition_root` and the telemetry test check this. The ledger after the flow holds only `scout`, `writer` and `qa_legal` entries.
  * The Supervisor's one entry is appended by `finalise_run` (`src/rendering.py` l.137), from the telemetry the composition root passes it.
* **Turn logging.** "Supervisor turn completed" is logged once per turn. The hook-order test counts 2 turns for 2 model calls, which shows there is one `LoggingHooks`.

### Pillar 8: code quality — ✅
* Imports are at the top, in stdlib, third-party, local groups, with zero E402. Every signature is annotated, and `__all__` is complete.
* **`SupervisorOutput`** is a frozen dataclass, not a §6 model. That follows the precedent of `RunFinalisation` (`src/rendering.py` l.92) and `SubAgentModels` (`src/tools.py` l.136), and no `dict[str, Any]` crosses a boundary.
* **Test imports.** `test_supervisor.py` imports `SUPERVISOR_TOOL_DESCRIPTIONS` from `test_docs_consistency`, as `test_tools_scout.py` l.47 already does. It imports no `test_*` name, so nothing is collected twice.
* Ruff: 0 in-scope findings and 0 pre-existing.

## 2a. Prompt audit (benchmark-sensitive)

| Section | Source | Verdict |
| :--- | :--- | :--- |
| Role | §1.1, D-F, DESIGN.md §3 | Faithful. "read each QA report and decide whether to request a revision or save" is §1.1's "Does" cell |
| Tools | §7.1, §7.4 | Names come from the `src.guardrails` constants. The descriptions are not repeated, and they reach the model through each tool's spec (X1). This is sound: it avoids a second copy that could drift |
| Scope rules | Approach 1 l.113–148, §7.4, DM2, DM3 | Copied verbatim where the field survives: `date_to`, `date_from` ≤ `date_to`, `sources`, `sector_constraints` and the whole `max_drafts` rule. Adapted where it named `time_window`. All five §7.4 bullets are present |
| Decision basis, never-compare | D-C l.358–370 | Verbatim, apart from the two flagged additions, which I accept (below) |
| Decision table | D-C l.374–385 | Byte for byte, header and separator included (docs test, AC1) |
| Failed-Writer sentence | D-C l.387 | Verbatim, with "to the Supervisor" changed to "to you" (X6) |
| Run-level priorities | D-C l.390–391 | Verbatim (docs test, AC3) |
| Limits | §7.4, D-C rules 3–4, §7.1 | The cap comes from the constant. "Every call counts" is rule 3 and the `writer_tool` description. The ceiling, or "no ceiling", appears |
| Violations, Finishing | §7.4 | Faithful |
| Never contains | §7.4 | No ISO date, no clock read, no `time_window`, no article field, no substrate tool name and no "verify" |

**The two flagged additions.**
1. "(the `run` object of every result)" names the JSON key under which `RunContext` arrives (§6.4 `ToolResult.run`). It maps a type name to the key the model sees, and it adds no rule. Accepted.
2. "`issues` is free text: QA-Legal does not tag issues by type." This is D-C l.370's first clause, verbatim apart from the punctuation. Accepted.

**Two judgement calls I checked and accept, with the reasoning stated rather than assumed.**
* **X7, recency words → the past 3 months.** The sentence comes from Approach 1's `time_window_specified` bullet, a field DM2 drops. Its effect, though, is the definition of "no window named" that Approach 1's default-window rule relied on: recency words gave `past_3_months`. Keeping it preserves Approach 1's resolved dates for "recent" and "latest" prompts. Dropping it would leave the Supervisor free to choose a narrower window, which would be parity drift. It falls under §7.4's bullet "default to the past 3 months when no window is named".
* **Approach 1's worked example is dropped** (l.129–132: "given a current date of 2025-04-15, `past_3_months` gives…"). The implementer's report does not mention this. The example is stated in `time_window` tokens and sits inside the sentence "These two are the machine-readable form of `time_window`", so it belongs to the `time_window` rules that §7.4 drops. `test_prompt_holds_no_date` would also reject it. Dropping it is the reading the sources support; note O2 asks for it to be recorded.

## 3. Code review findings

There are no blocking findings and no Major findings.

| # | Severity | Where | Note |
| :---: | :---: | :--- | :--- |
| O1 | Optional | `src/supervisor.py` l.105, l.126–127, l.134 | Three table rows cite "rule 7", "rule 9" and "rule 8", but the prompt carries no numbered rule list, so the references point at nothing the Supervisor can see. The rows are copied as AC1 and "row for row" require (X5), and each row reads correctly without its reference. **No change recommended.** Rewording would break AC1 and need a specification change |
| O2 | Optional (record) | Stage 4 `WALKTHROUGH.md`, *Decisions* | Record the dropped Approach 1 worked example next to X7, with the reason above. Under §1.5, prompt content is never a free decision, so the record should show that it was a deliberate reading |
| O3 | Optional | `src/supervisor.py` l.264–274 | `WorkerOutput[str]` (§6.3, "what every runner returns") could replace `SupervisorOutput`. The dataclass follows the `RunFinalisation` precedent and is acceptable as it stands |

## 4. Anti-patterns and risks

None found in this iteration: no autonomy leak, no parity drift, no state coupling, and no route for article text to reach the Supervisor. Three forward risks, for the pre-flights of the iterations they affect:

* **F1 (Iteration 14): the Supervisor's telemetry after a provider error.** `run_supervisor` raises, so no `AgentTelemetry` is returned. `finalise_run` accepts `supervisor_telemetry=None`. §6.6 covers this case for sub-agents only, reading `event_loop_metrics`, and the specification is silent for the Supervisor. Iteration 14's pre-flight should settle whether the composition root recovers it from `agent.event_loop_metrics` or records none.
* **F2 (Iteration 14): the summary after a fatal stop is `""`, not `None`.** `RunState.supervisor_summary` is `str | None`. The composition root should decide which of the two it stores, so that "Run completed" logs a consistent value.
* **F3 (Iteration 15): log order around a fatal stop.** `AfterToolCallEvent` callbacks run in reverse registration order in strands 1.55.1 (`strands/hooks/events.py` l.298–301, `should_reverse_callbacks = True`). So `FatalStopHook` logs "Fatal abort triggered" before `LoggingHooks` logs "Tool call completed" for the fatal tool. This is harmless, but Iteration 15's log assertions must not assume the opposite order.

## 5. Remediation directives

None required. O1–O3 are optional, and F1–F3 are inputs for later pre-flights. Nothing goes to `QUESTIONS.md`.

---

# Iteration 13 — Supervisor agent: architect review, round 2

**Reviewer:** architect (Stage 3, round 2), 2026-10-01
**Scope:** fix round 1, which was test-only. `tests/test_unit/test_supervisor.py` (l.321–407 helpers, l.410–588 tests, l.356 and l.720 for QA-m3) and `tests/test_unit/test_docs_consistency.py` (`_PRIORITIES_HEADING`, `_d_c_priorities`, `_priorities_disagree`, `test_priorities_check_catches_an_invented_extra_priority`).
**Checks run:**
* `uv run pytest -q`: 1243 passed in 114.1 s.
* `uv run pytest tests/test_unit`: 1213 passed in 30.5 s.
* `uv run pytest tests/test_integration`: 30 passed in 89.9 s.
* `test_supervisor.py` + `test_docs_consistency.py` with `--durations=10`: 363 passed in 10.5 s.
* `uvx ruff check src tests --no-cache`: all checks passed.
* `uv run pytest -m live --collect-only`: no tests collected, 1243 deselected.

Probes ran from the session scratchpad. They print only booleans, counts and timings, never the prompt.

## 1. Overall verdict

**APPROVED.** The production code and the prompt are unchanged, and the architecture is as approved in round 1. All four QA items are fixed as described. The fix round raised no architecture finding.

I found four Minor test-quality items and one nit, all in `tests/test_unit/test_supervisor.py`. They are A1–A5 in `FIXES.md` under *Architect — round 2*. None of them blocks, because the real prompt is clean under both the current patterns and the stronger ones I validated.

## 2. Verification of fix round 1

**Production unchanged.**
* `src/supervisor.py` was last written at 16:04:27, before my round-1 review at 16:13:57. Its round-1 anchors still hold: the `agent(...)` call is at l.306 and the `Agent(...)` assembly at l.254–261. Its SHA-256 is `08cd9c41…e791`.
* `tests/test_unit/test_module_structure.py` is unchanged since 16:03.
* Only the two test files listed in the scope changed.

**The prompt is still clean.** For `build_supervisor_prompt(None | 1 | 2 | 3)`, all four helpers find nothing: article work 0, Writer feedback 0, failed-call rules 0 and run bounds 0.

| QA item | Verified | Note |
| :--- | :---: | :--- |
| QA-M1 | ✅ | `_ARTICLE_WORK` and `_NEGATED_BEFORE` are QA's patterns, verbatim (l.322–338). `_affirmative_matches` (l.369–376) applies the negation to each match, not to each clause. All 15 probes pass, and so do the 5 feedback hits and 3 feedback spares. Gaps remain; see A1–A3 |
| QA-m1 | ✅ | All five `_RUN_BOUNDS` patterns (l.344–352) are disjoint, so there is no double count: "Make at most 12 calls. Stop after 3 violations." gives 2. `_failed_call_rules` (l.400–402) scopes the failure word to a Scout or QA-Legal clause, case-sensitively, and spares `ERROR` |
| QA-m2 | ✅ | `_priorities_disagree` takes the numbered list under the heading, up to the first blank line, and requires it to equal D-C's list exactly. A missing heading counts as a disagreement. `_d_c_priorities` is guarded by `len == 2`. The M7 mutation test injects after the real last priority, which it asserts is present, so the test cannot pass vacuously |
| QA-m3 | ✅ (partial) | `tdi_cta` is now checked (l.356, l.720). But the same line's check of `article_body` cannot fire; see A4 |

**Architecture.** Pillars 1–7 are unchanged from round 1: no production code changed, so nothing new can sequence the sub-agents or leak article text. In pillar 8 the new helpers are fully annotated, with imports at the top and no E402. The one hygiene point, the dead alternative in `_FAILURE`, is A5.

## 3. The runtime jump (~32 s → ~114 s): environment, not the new regexes

* **The changed files are fast.** `test_supervisor.py` and `test_docs_consistency.py` run 363 tests in 10.5 s. The slowest is 0.26 s, a prompt-equality test that takes no regex path.
* **The helpers on the real prompt cost about 5 ms.** 200 full scans with all four helpers took 1.09 s.
* **All of the growth is in the substrate integration tests.**
  * The unit suite runs in 30.5 s, which is the round-1 figure for the whole suite.
  * `tests/test_integration` takes 89.9 s. Each of the 13 `test_mcp_client.py` tests takes 5.6–7.6 s, and each one spawns `hse-easy-mock` over stdio.
  * Those tests and `src/mcp_client.py` are unchanged since commit 5b6ae08.
  * In the substrate's own environment, `import fastmcp` alone takes 2.25 s (`-X importtime`), and `import fastmcp, server` takes 4.7 s wall time. `uv run` itself starts in 0.4 s.
* **The machine was loaded.**
  * 27 `python`/`uv` processes are alive, most of them stale MCP servers from 29 and 30 September.
  * During my run, a scratchpad process outside this review (`probe.py`, PID 41556, started 19:36:38) was using a full core.
* **Conclusion: this is subprocess start-up cost on a loaded machine, not this iteration.** It has no correctness impact. It is worth re-timing on a quiet machine before Iteration 15, which adds integration scenarios.

**The regexes do have a latent catastrophic-backtracking case**, but nothing realistic triggers it (A1). In `_ARTICLE_WORK`, `\S+` and `[ ,]+` can both consume a comma, so a run of commas splits in many ways. After a matched verb, 100 characters of `, , , …` take 12.0 s and 200 characters of `a,a,…` take 12.7 s. Real text has spaces between words and holds no such runs, which is why the prompt scans in milliseconds. A future prompt edit or synthetic test case could hang the suite, though. The fix is one character class.

## 4. Code review findings (fix-round code)

| # | Severity | Where | Finding |
| :---: | :---: | :--- | :--- |
| A1 | 🟢 Minor | `test_supervisor.py` l.332 | Polynomial blow-up (about n⁵) on comma runs, as in §3. `[^\s,]+` in place of `\S+` makes it linear: 6,000 characters scan in 5 ms |
| A2 | 🟢 Minor | `test_supervisor.py` l.321 and l.331 | The comment says `_ARTICLE_WORK` "accepts any inflection", but `(?:s\|es\|d\|ed\|ing)?` misses the -ing form of every verb that ends in -e, and irregular forms. Missed: "When scoring the draft", "Consider improving the article", "Before judging the draft", "Rating the article", "Start by evaluating the draft" and "You rewrote the draft". This is QA-M1's class, and the comment overstates the coverage |
| A3 | 🟢 Minor | `test_supervisor.py` l.338 | `_NEGATED_BEFORE` treats any negation within three words as governing the match, even when it negates a different verb. "Never save before you review the draft." and "Don't save until you read the draft." are missed. "Do not save until you have reviewed the draft." is caught only because "have" makes a fourth word |
| A4 | 🟢 Minor | `test_supervisor.py` l.719–720 | `json.dumps` escapes the `\n` in `DRAFT_ARGS["article_body"]`, so `DRAFT_ARGS[field] in received` is always False for `article_body`, leaked or not. I checked this with a leak injected into a tool result: `headline`, `executive_summary` and `tdi_cta` are caught, `article_body` is not. The key check at l.728 still covers the §7.2 contract, so D-F stays proven; the docstring claims more than this one value check delivers. The weakness dates from round 1, and I missed it then |
| A5 | Nit | `test_supervisor.py` l.392 | `\breturns an error\b` in `_FAILURE` is dead: `\berrors?\b` already matches "error" in that phrase |

The remedies, validated against every existing hit and no-hit case, the 15 probes, the new probes and the real prompt, are in `FIXES.md` under *Architect — round 2*.

## 5. Record issue in `FIXES.md`

In fix round 1, the implementer replaced the body of *QA — round 1* / *🧪 Quality Assurance & Test Verification* with a one-line pointer: "All four items … were resolved in fix round 1 and removed from here". That edited another reviewer's section, which the workflow forbids, and the four original findings are now only in `QA_REVIEW.md`. QA will restore its own section, so I have not touched it. The implementer's own *Implementation — fix round 1* section should record resolutions without editing reviewer sections in future rounds.

## 6. Remediation directives

None blocks. If a fix round runs anyway, apply A1–A5 as given in `FIXES.md` (AGENTS.md Rule 7; §7.4 "must never contain"; code-reviewer Gate 1, "a test that would also pass against a stub is not coverage"). Otherwise record them in the walkthrough as accepted test-side limits. Nothing goes to `QUESTIONS.md`.

**Verdict: APPROVED.**
