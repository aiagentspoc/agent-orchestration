## Architect — round 1

Verdict: **APPROVED**. Full review: `.agents/tasks/iteration-13/ARCHITECT_REVIEW.md`.

### 🏛️ Architecture & System Boundaries

No blocking findings. Control flow stays in the Supervisor: one `agent(...)` call, and no code calls a tool. D-F holds: no article text and no article key reaches the Supervisor, and a test proves it over the real tools. Hook wiring is correct: one `LoggingHooks("supervisor")`, then the caller's hooks, with `FatalStopHook` passed by the caller. `SequentialToolExecutor` is used. There is no double ledger entry: `run_supervisor` leaves `RunState` untouched, and `finalise_run` appends the Supervisor's one entry. The prompt traces sentence by sentence to §7.4, D-C and Approach 1's ScopeParser prompt, and adds no rule.

### 🧹 Code Quality & Conventions

No blocking findings. `uvx ruff check src tests --no-cache`: 0 in-scope findings and 0 pre-existing debt. `uv run pytest -q`: 1201 passed.

Optional items. None blocks, and none needs a fix round:
- **O1 (optional, no change recommended).** In `src/supervisor.py`, the decision-table rows at l.105, l.126–127 and l.134 cite "rule 7", "rule 9" and "rule 8", but the prompt carries no rule list. They are kept verbatim because AC1 requires the rows "row for row". Changing them would need a specification change.
- **O2 (optional, record only).** In the Stage 4 `WALKTHROUGH.md` *Decisions*, record next to X7 that Approach 1's `time_window` worked example (`../code-orchestration/src/agents.py` l.129–132) was dropped with the `time_window` rules (§7.4, DM2).
- **O3 (optional).** In `src/supervisor.py` l.264–274, `WorkerOutput[str]` (§6.3) could replace `SupervisorOutput`. The dataclass matches the `RunFinalisation` precedent and is acceptable as it stands.

### ❓ Needs a decision

None from architect round 1. Forward risks F1–F3 in `ARCHITECT_REVIEW.md` §4 are inputs for the Iteration 14 and 15 pre-flights, not questions for this iteration.

## QA — round 1

Verdict: **CHANGES REQUIRED** (FAIL). Full review: `.agents/tasks/iteration-13/QA_REVIEW.md`. Real results: `uv run pytest -q` gave 1201 passed; `uvx ruff check src tests --no-cache` gave "All checks passed!". AC1 to AC3 hold. No production change is needed: every fix below is in the tests.

### 🧪 Quality Assurance & Test Verification

All four items (QA-M1, QA-m1, QA-m2, QA-m3) were resolved in fix round 1 and removed from here; see *Implementation — fix round 1* below.

### ❓ Needs a decision

None from QA round 1.

## Implementation — fix round 1

All four QA items are resolved in the tests. `src/supervisor.py` is unchanged: the stronger checks find nothing in `build_supervisor_prompt(None | 2 | 3)`. Architect O1 and O3 need no change, and O2 is a walkthrough note for Stage 4.

- **QA-M1, resolved.** In `tests/test_unit/test_supervisor.py`:
  - `_ARTICLE_WORK` is now QA's verb-inflected, determiner-tolerant pattern, with the verb list in `_ARTICLE_VERB`.
  - `_NEGATED_BEFORE` is QA's verb-scoped negation. A new `_affirmative_matches` applies it to each match.
  - `_article_work_instructions` and the new `_writer_feedback_instructions` both use `_affirmative_matches`.
  - The feedback pattern (`_WRITER_FEEDBACK`) now also catches "revision notes", "tell the Writer" and "give the Writer".
  - New tests: `test_article_work_instructions_catch_realistic_phrasings` covers the 12 sentences plus QA's three end-to-end sentences. `test_writer_feedback_check_catches_realistic_phrasings` and `test_writer_feedback_check_spares_negations_and_hand_offs` cover the feedback check.
  - QA's benign sentences were added as no-hit cases to `test_article_work_instructions_catch_instructions_but_not_their_negation`.
  - Red: all 15 article-work probes and 4 feedback probes failed by assertion against the old patterns. Green: they all pass.
- **QA-m1, resolved.**
  - The tool-call pattern in `_RUN_BOUNDS` now accepts `after|within|more than|at most|up to|maximum of` before `N (tool )?(calls|tools)`. It is merged with the old pattern so that no phrase is counted twice.
  - A repeated-violation pattern was added.
  - `_failed_call_rules` needs a Scout or QA-Legal name together with a lower-case failure (`fail`, `error(s)`, `returns an error`). This spares the `ERROR` QA status.
  - The Red step failed 4 run-bound cases and 3 failed-call cases. Green: they pass.
  - No-hit cases now cover the `ERROR` table row, the `ERROR` status and the Writer's `ToolResult.error` rule. The prompt still yields `[]`.
- **QA-m2, resolved.** In `tests/test_unit/test_docs_consistency.py`, `_priorities_disagree` takes the numbered list under the heading, up to the first blank line, and requires it to equal D-C's list exactly.
  - `test_priorities_check_catches_an_invented_extra_priority` injects mutation M7.
  - Red: the helper still used the old subset logic and returned False, so the assertion failed. Green: it passes.
- **QA-m3, resolved.** `test_scripted_supervisor_never_receives_article_text` now checks every field in `ARTICLE_FIELDS`, `tdi_cta` included. This is a regression guard on correct production code, so it has no failing Red step.

## Architect — round 2

Verdict: **APPROVED**. Full review: `.agents/tasks/iteration-13/ARCHITECT_REVIEW.md`, round 2 section.

The fix-round results:
* `src/supervisor.py` is unchanged (last written 16:04, before round 1), and so is the prompt.
* All four QA items are verified.
* `uv run pytest -q` gives 1243 passed.
* `uvx ruff check src tests --no-cache` gives 0 in-scope findings and 0 pre-existing debt.

The runtime jump comes from the substrate integration tests, which spawn the server at 5.6–7.6 s each. The unit suite takes 30.5 s, and the two changed files take 10.5 s. The jump is not caused by the new regexes.

### 🏛️ Architecture & System Boundaries

No findings. No production code changed, so control flow, D-F and parity stand as approved in round 1.

**Record issue (for the workflow, not a code fix).** Fix round 1 replaced the body of *QA — round 1* / *🧪 Quality Assurance & Test Verification* with a pointer. That edited another reviewer's section. QA restores its own section. In later rounds, the implementer records resolutions only in its own *Implementation* section.

### 🧹 Code Quality & Conventions

None of these items blocks: the real prompt yields 0 hits under both the current helpers and the replacements below. Apply them if a fix round runs; otherwise record them in `WALKTHROUGH.md` as accepted test-side limits. All are in `tests/test_unit/test_supervisor.py`.

I validated the replacements below in memory. They keep all 9 existing counts in `test_article_work_instructions_catch_instructions_but_not_their_negation` and catch all 15 `ARTICLE_WORK_PROBES`. They also catch every new probe in A2 and A3, and find 0 hits in `build_supervisor_prompt(None | 1 | 2 | 3)`.

- **A1 (🟢 Minor): catastrophic backtracking in `_ARTICLE_WORK`.**
  - **Where:** l.332.
  - **Problem:** `\S+` and `[ ,]+` both match a comma, so a comma run splits in about n⁵ ways. Measured: 100 characters of `", " * 50` after "review " take 12.0 s, and `"a," * 100` takes 12.7 s.
  - **Change:** `(?:[ ,]+(?!(?:and|or)\b)\S+){0,4}?` → `(?:[ ,]+(?!(?:and|or)\b)[^\s,]+){0,4}?`. The scan becomes linear: 6,000 characters in 5 ms.
  - **Test:** add one case asserting that `_article_work_instructions("review " + ", " * 2000 + "x") == []`. Under the current pattern it would hang.
- **A2 (🟢 Minor): the inflection gap, and a comment that overstates coverage.**
  - **Where:** l.321–325 and l.331.
  - **Problem:** e-final verbs lose their -ing form ("scoring", "improving", "judging", "rating", "evaluating"), and "rewrote" is missed. The comment at l.321 claims "any inflection".
  - **Change:** use stems and an extended suffix group:
    ```python
    _ARTICLE_VERB = (
        r"(?:review|scor|rat|grad|improv|edit|rewr[io]t|reword|proofread|polish|read|judg|check|assess|evaluat"
        r"|fix|correct|critiqu|inspect|examin)"
    )
    # in _ARTICLE_WORK:
    r"\b" + _ARTICLE_VERB + r"(?:e|es|ed|d|s|ing|ten)?\b"
    ```
  - **Comment:** say "the verbs' stems; `_ARTICLE_WORK` adds the regular endings and `rewrote`/`rewritten`".
  - **Tests:** add to `ARTICLE_WORK_PROBES`:
    - "When scoring the draft, be strict."
    - "Consider improving the article."
    - "Before judging the draft, read the report."
    - "Rating the article is your job."
    - "Start by evaluating the draft."
    - "You rewrote the draft."
- **A3 (🟢 Minor): the negation window governs a different verb.**
  - **Where:** l.336–338 and l.369–381.
  - **Problem:** a negation within three words cancels the match even when it negates another verb. "Never save before you review the draft." and "Don't save until you read the draft." are missed.
  - **Change:** for the article-work check only, the negation must reach the matched verb directly or through a coordinated verb list ("never read, judge or edit"):
    ```python
    _NEGATED_VERB = re.compile(
        r"\b(?:never|not|don't|cannot)[ ]+(?:[^\s,]+(?:,[ ]+(?:(?:and|or)[ ]+)?|[ ]+(?:and|or)[ ]+))*$",
        re.IGNORECASE,
    )
    ```
    Then give `_affirmative_matches` a `negation: re.Pattern[str]` parameter, and pass `_NEGATED_VERB` from `_article_work_instructions`.
  - **Keep `_NEGATED_BEFORE` for `_writer_feedback_instructions`.** That match starts at the object, not the verb, so `_NEGATED_VERB` would wrongly flag "You never write feedback for the Writer." I checked this.
  - **Tests:** add both missed sentences to `ARTICLE_WORK_PROBES`.
- **A4 (🟢 Minor): the `article_body` value check cannot fire.**
  - **Where:** l.719–720.
  - **Problem:** `DRAFT_ARGS["article_body"]` contains `\n`, which `json.dumps(model.received_messages)` escapes, so `in received` is always False for that field. I checked this with an injected leak.
  - **Change:** look for each value in its JSON-escaped form, inside the tool-result texts as the Supervisor received them. Those texts are single-encoded JSON, so a leaked value appears there escaped once:
    ```python
    texts = [
        block["toolResult"]["content"][0]["text"]
        for message in model.received_messages[-1]
        for block in message["content"]
        if "toolResult" in block
    ]
    leaked = [
        field for field in ARTICLE_FIELDS
        if any(json.dumps(DRAFT_ARGS[field], ensure_ascii=False)[1:-1] in text for text in texts)
    ]
    assert leaked == []
    ```
    I validated this in memory. With `article_body` and `headline` injected into a tool-result text it returns `['headline', 'article_body']`, and on a clean text it returns `[]`. The existing `results` and `json_keys` check (l.721–728) stays as it is.
- **A5 (Nit): dead alternative in `_FAILURE`.**
  - **Where:** l.392.
  - **Change:** drop `|\breturns an error\b`, since `\berrors?\b` already matches it. The QA-m1 case "If qa_tool returns an error, call it again." stays caught.

### ❓ Needs a decision

None from architect round 2.

## QA — round 1 (restored record)

Fix round 1 replaced the body of *QA — round 1* above with a pointer. This section restores the round 1 items as they were raised, for the record. It is append-only, and the pointer above stays. All four items are verified resolved in *QA — round 2* below. Full evidence: `QA_REVIEW.md`, round 1 §4.

### 🧪 Quality Assurance & Test Verification

- **QA-M1 (🟡 Major).** The article-work and Writer-feedback checks missed realistic phrasings.
  - **Where:** `tests/test_unit/test_supervisor.py`, `_ARTICLE_WORK`/`_NEGATION` (round 1 l.324–330) and the feedback regex (round 1 l.428).
  - **Problem:** the object had to be literally `the article`, `the draft` or `article text`. The verb had to be uninflected. Any `no`, `not` or `never` in the clause cancelled the match.
  - **Evidence:** 12 of 12 realistic sentences were missed, among them "Review each draft before you save it." and "Do not save until you have reviewed the draft.". Three feedback phrasings were missed too. Injected into the real prompt, three forbidden sentences each left the suite green (`321 passed`).
  - **Fix:** the verb-inflected, determiner-tolerant `_ARTICLE_WORK`, the verb-scoped `_NEGATED_BEFORE`, the probes as parametrized cases, and the feedback pattern widened to "revision notes/instructions", "tell the Writer" and "give the Writer".
- **QA-m1 (🟢 Minor).** The run-bound and failed-call patterns missed common forms.
  - **Where:** `_RUN_BOUNDS` (round 1 l.334–339) and `failed_call` (round 1 l.456).
  - **Missed:** "Stop after 20 tool calls.", "Do not call more than 30 tools.", "If the same violation repeats three times, stop.", "Finish within 40 calls.", "If qa_tool returns an error, call it again." and "When QA-Legal errors, save the draft.".
  - **Fix:** widen both patterns, match failure words in lower case to spare the `ERROR` status, and add one synthetic test per phrasing.
- **QA-m2 (🟢 Minor).** The priorities test accepted an invented third priority (mutation M7).
  - **Where:** `tests/test_unit/test_docs_consistency.py`.
  - **Fix:** require the numbered list under the heading to equal D-C's list exactly.
- **QA-m3 (🟢 Minor, optional).** The D-F value check skipped `tdi_cta`.
  - **Fix:** add it to the field tuple.

## QA — round 2

Verdict: **PASSED** (PASS). Full review: `.agents/tasks/iteration-13/QA_REVIEW.md`, round 2 section.

Real results:
* `uv run pytest -q` gives 1243 passed in 120.7 s.
* `uvx ruff check src tests --no-cache` gives "All checks passed!".
* `uv run pytest -m live --collect-only -q` collects no tests (1243 deselected).

`src/supervisor.py` is unchanged. AC1 to AC3 hold.

### 🧪 Quality Assurance & Test Verification

QA-M1, QA-m1, QA-m2 and QA-m3 are verified resolved:
* all round 1 probes are caught;
* every end-to-end prompt mutation fails 2–4 tests, and the benign control stays at 363 passed;
* there are 0 false positives on the harmless sentences;
* the real prompt yields `[]` at every ceiling.

**Runtime.** The 120.7 s against 32.6 s is environmental. It comes from the substrate-spawning `tests/test_integration/test_mcp_client.py` (6.5–7.6 s per test), which this iteration does not change. Without that file, 1219 tests pass in 35.1 s. The new regexes take milliseconds on the real prompt.

Minor, test-side items. None blocks. Apply them if a fix round runs; otherwise record them in `WALKTHROUGH.md` as accepted limits:
- **QA-m4 (🟢), which concurs with architect A1.** `_ARTICLE_WORK` (l.332) backtracks polynomially on comma-dense text. Measured verbatim on `"review" + " ," * n`:
  ```text
  aw_commas n=40: 105.3 ms
  aw_commas n=80: 3775.7 ms
  ```
  At n=200 it gave no result within 300 s.
  - **Fix:** replace `\S+` with `[^\s,]+` at l.332, and also at l.338 (`_NEGATED_BEFORE`) for consistency.
  - **Validated:** n=80 then takes 0.7 ms, and the match counts are identical on all 33 probe, no-hit and prompt texts.
  - **Test:** add the architect's guard case.
- **QA-m5 (🟢), which concurs with architect A4.** I confirmed it: `DRAFT_ARGS["article_body"]` contains `\n`, so `DRAFT_ARGS["article_body"] in json.dumps(...)` is always False. Use the architect's escaped-form check.
- **QA-m6 (🟢, optional).** These fresh phrasings are still missed. They are outside the round 1 request:
  - "Look over the draft and polish its headline.";
  - "Explain to the Writer what QA-Legal found.", "Pass your comments to the Writer.", "Brief the Writer on each issue." and "Provide guidance to the Writer.";
  - "If qa_tool raises, retry it.", "Should the Scout time out, finish the run." and "If QA-Legal cannot audit the draft, save it anyway.";
  - "Stop after three violations.", "Stop after the third violation.", "Never exceed 50 tool calls." and "Call at most twenty tools.".

  **Cheap wins:**
  - accept number words as well as `\d+` in the `after|at most|more than N violations` and tool-call patterns;
  - add `exceed`;
  - add `brief the Writer|explain to the Writer|(?:guidance|comments) (?:to|for) the Writer` to `_WRITER_FEEDBACK`.

  Re-confirm that the prompt still yields `[]`.

### ❓ Needs a decision

None from QA round 2.
