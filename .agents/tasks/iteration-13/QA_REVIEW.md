# QA Review: Iteration 13, Supervisor agent (round 1)

## 1. Summary and verdict

**Verdict: CHANGES REQUIRED** (round 1 verdict line: **FAIL**).

The production code is correct. `src/supervisor.py` builds the Supervisor on `SequentialToolExecutor` with exactly the four tools, a null callback handler and one `LoggingHooks("supervisor")` ahead of the caller's hooks. Its prompt copies D-C's decision table and run-level priorities byte for byte, states the cap from `MAX_ATTEMPTS_PER_DOC`, and holds no date. `run_supervisor` sends the §7.4 user turn verbatim. The scripted flow, the fatal stop and the provider-error case all behave as specified. AC1 and AC3 survive every mutation I ran against them, with one gap: an invented extra priority is not caught.

One gap needs a fix round. It is the check behind §7.4's "must never contain any instruction to review, score or improve article text". The verb–object regex misses **12 of 12** realistic phrasings I tried. A forbidden sentence injected into the real prompt leaves the whole supervisor and docs suite green. The Writer-feedback check has the same weakness. I have validated a replacement pattern, given in §4: it catches every probe, spares the Role's negation, and finds nothing in the current prompt.

### Checks I ran myself

| Check | Result |
| :--- | :--- |
| `uv run pytest -q` | **1201 passed**, 0 failed, 0 errors, no warnings summary (32.6 s). Matches the implementer's claim |
| New tests | 90 = 82 (`test_supervisor.py`) + 6 (docs, AC1/AC3 × 2 ceilings) + 1 (import boundary) + 1 (annotations, `supervisor.py`). Matches 1111 → 1201 |
| `uvx ruff check src tests --no-cache` | All checks passed |
| `uv run pytest -m live --collect-only -q` | No tests collected (1201 deselected) |
| `-W error::DeprecationWarning` on `test_supervisor.py` | 82 passed |
| Stray processes | None from this iteration. Every `python.exe`/`uv.exe` present is a harness MCP server started on 29 or 30 September |
| Working tree | `src/tools.py` and `src/schemas.py` are unchanged. Only the five expected paths and this artifact folder differ |
| Substrate shape | `list_regulatory_updates(INAIL)` returns `RegulatoryUpdateSummary` fields (`doc_id`, `source`, `publication_date`, `summary`, …), consistent with `UPDATE_FIXTURE` |

Mutations were applied **in memory only**, through a throwaway pytest plugin loaded with `-p` from the session's temporary folder. No repository file was edited.

## 2. Gate matrix

| Gate | Topic | Status | Notes |
| :--- | :--- | :---: | :--- |
| 1 | Strict TDD | ❌ | The report gives a Red reason for every behaviour, and the positive checks are strong. The negative §7.4 checks (forbidden content) pass against realistic forbidden prompts, so they are not real coverage of that clause (QA-M1) |
| 2 | Zero-token testing | ✅ | Every model is `ScriptedModel` or `FailingModel`, and the substrate is `OfflineSubstrateSession`. The import-boundary test proves `src.supervisor` imports no `model_factory`, `mcp_client`, `strands.models.openai` or `strands.tools.mcp` |
| 3 | Pydantic v2 contracts | ✅ | No new model. `SupervisorOutput` is a frozen dataclass of `str` and `AgentTelemetry` and does not enter §6. No `dict[str, Any]` crosses a module boundary |
| 4 | Guardrails and attempt cap | n/a in this iteration | Untouched. The cap the prompt states is pinned to `MAX_ATTEMPTS_PER_DOC` (AC3) |
| 5 | Strands integration and telemetry | ✅ | `SequentialToolExecutor` is in place, and mutation M8 (the concurrent executor) fails a test. `extract_telemetry` is the only metrics reader. `tool_invocations` count each of the four tools once. The ledger holds only scout, writer and qa_legal; the Supervisor's entry belongs to `finalise_run` (Iteration 14) |
| 6 | No article text for the Supervisor | ✅ | No `FORBIDDEN_SUPERVISOR_KEYS` key appears in the four real tool results, and no `DRAFT_ARGS` headline, body or summary reaches any Supervisor message. Optional: also check `tdi_cta` (QA-m3) |
| 7 | Drafts and logging | ✅ | No drafts here. "Supervisor turn completed" is logged once per turn, and the tool lines carry `agent=supervisor` (hooks from Iteration 12) |
| 8 | Python and subprocess safety | ✅ | Annotations complete (test passes), imports at the top, `pathlib.Path` throughout, no orphaned subprocess, clean pytest output |

## 3. Acceptance criteria and Red items

| # | Criterion | Status | Evidence |
| :--- | :--- | :---: | :--- |
| AC1 | Each D-C decision-table row is in the prompt, checked against a list taken from the specification | ✅ | `test_supervisor_prompt_copies_the_d_c_decision_table_row_for_row`. Each mutation fails it: two rows swapped (M1), one row dropped (M2), one cell reworded (M2b). The line-equality assertion also rules out a second table |
| AC2 | Tool descriptions match §7.1 word for word, and the prompt covers every §7.4 item | ✅ (with QA-M1) | `received_tool_specs[0]` equals `SUPERVISOR_TOOL_DESCRIPTIONS`. The 17 `PROMPT_ITEMS` × 2 ceilings and the ceiling test pass, and mutation M9 (ceiling ignored) and M10 (never-compare rule dropped) each fail them. The prompt holds no forbidden content, as my stronger pattern confirms. The test of that negative half is weak (QA-M1) |
| AC3 | D-C and the prompt agree on the cap and the priorities (docs test) | ✅ (with QA-m2) | Mutations caught: cap 4 (M5), a contradicting "cap of 5" (M6), priorities swapped (M3), priority 2 dropped (M4). Not caught: an invented third priority (M7) |
| Red | Builder: sequential executor, exactly four tools, `gpt-5.4`/`medium`, `callback_handler=None` | ✅ | Four builder tests and two binding tests. The model is injected; the composition root builds it in Iteration 14 |
| Red | Prompt: Role, Scope, Decision table plus never-compare, Priorities, Limits, Violations, Finishing | ✅ | `PROMPT_ITEMS`. The scope rules trace line by line to Approach 1's `SCOPE_PARSER_SYSTEM_PROMPT` (`../code-orchestration/src/agents.py` l.110–170), with the `time_window` rules and the dated example dropped |
| Red | Prompt holds no current date; the Supervisor is never told to review, score or improve article text | ✅ / ❌ | The no-date check is strong (no ISO literal, no `today()` in the module). The forbidden-phrase check is weak (QA-M1) |
| Red | `run_supervisor`: user turn `Current date: YYYY-MM-DD` + the raw prompt verbatim; returns the final text and `AgentTelemetry` counting the four tools | ✅ | `RAW_PROMPT` keeps its surrounding whitespace, and an exact `sent_text` equality checks it. `tool_invocations` equal `{4 tools: 1}` |
| Red | Scripted flow scout → writer → qa → save leaves one saved `DocumentRecord` | ✅ | `qa_status == "PASS"`, `attempts_used == 1`, 5 turns consumed, summary returned |
| Extra | Fatal stop (D-D.1) and provider error | ✅ | Cancelled: `ran == ["fatal_tool"]`, one model turn, summary `""`, `fatal_error` kept. Provider: `RuntimeError` propagates, one invocation |

**Definition of Done:**

| Row | Status |
| :--- | :--- |
| DoD-1 | ✅ |
| DoD-2 | ✅ |
| DoD-3 | ✅ |
| DoD-4 | ✅ Every function and branch in `src/supervisor.py` is exercised |
| DoD-5 | ✅ |
| DoD-6 | Pending: Stage 4 writes `WALKTHROUGH.md` |

**Totals:** 3 of 3 acceptance criteria and 5 of 5 applicable DoD rows hold. One test-quality finding blocks the PASS.

## 4. Findings by severity

### 🟡 Major

**QA-M1. The checks for article work and Writer feedback miss realistic phrasings.** The affected code is `tests/test_unit/test_supervisor.py`: `_ARTICLE_WORK` and `_NEGATION` (l.324–330), and the feedback regex at l.428. Three faults combine:

* the object must be literally `the article`, `the draft` or `article text`, so a plural, a possessive or a determiner such as "each" defeats it;
* the verb must be uninflected and drawn from a short list;
* any `no`, `not` or `never` anywhere in the clause cancels the match, including a "no" that is only a determiner ("no issues").

Probe results, from `_article_work_instructions`. Each line should be caught; none is:

```text
MISS expected=True  got=False :: Review each draft before you save it.
MISS expected=True  got=False :: Read the latest draft and decide.
MISS expected=True  got=False :: Review the drafts before saving.
MISS expected=True  got=False :: Check the article for errors before saving.
MISS expected=True  got=False :: Assess the quality of the draft.
MISS expected=True  got=False :: Evaluate the article against the QA report.
MISS expected=True  got=False :: If QA-Legal reports no issues, review the draft yourself.
MISS expected=True  got=False :: Do not save until you have reviewed the draft.
MISS expected=True  got=False :: You never edit article text, but you should score the article.
MISS expected=True  got=False :: Improve the Writer's draft where QA-Legal objects.
MISS expected=True  got=False :: Rate the article from 1 to 10.
MISS expected=True  got=False :: Fix the article where needed.
```

Feedback check: "Tell the Writer what to fix in its revision.", "Give the Writer revision notes." and "When no issue is fixable, write feedback for the Writer anyway." are all missed.

**End to end.** I appended each of the following to the real prompt's Finishing section, in memory, and ran `tests/test_unit/test_supervisor.py` and `tests/test_unit/test_docs_consistency.py`:

```text
== Before saving, review each draft and improve its wording where QA-Legal objects.
321 passed in 1.56s
== Read the latest draft and check the article for errors before you call save_draft.
321 passed in 1.58s
== If QA-Legal reports no issues, still review the draft yourself and tell the Writer what to fix.
321 passed in 1.63s
```

The positive control was "Review the draft before you save it.", which gave `2 failed, 319 passed`. So the plugin worked, and the misses are real.

**Fix.** Replace `_ARTICLE_WORK` and `_NEGATION`, and add three things: the negation scope, the probes, and the feedback phrasings. I validated this pattern against 21 probes with 0 mismatches. It also finds 0 hits in `build_supervisor_prompt(None | 1 | 3)`, so the production prompt needs no change.

```python
_ARTICLE_VERB = (
    r"(?:review|score|rate|grade|improve|edit|rewrite|reword|proofread|polish|read|judge|check|assess|evaluate"
    r"|fix|correct|critique|inspect|examine)"
)
_ARTICLE_WORK = re.compile(
    r"\b" + _ARTICLE_VERB + r"(?:s|es|d|ed|ing)?\b"     # any inflection
    r"(?:[ ,]+(?!(?:and|or)\b)\S+){0,4}?"               # up to four words before the object
    r"[ ,]+(?:article|draft)s?\b",                      # any determiner or possessive, singular or plural
    re.IGNORECASE,
)
#: A negation that governs the verb: within three words before it. "no" is left out, since it is usually a
#: determiner ("no issues"), not a negation of the instruction.
_NEGATED_BEFORE = re.compile(r"\b(?:never|not|don't|cannot)\b(?:[ ,]+\S+){0,3}[ ,]*$", re.IGNORECASE)

def _article_work_instructions(text: str) -> list[str]:
    return [
        match.group(0)
        for clause in _clauses(text)
        for match in _ARTICLE_WORK.finditer(clause)
        if not _NEGATED_BEFORE.search(clause[: match.start()])
    ]
```

Then make these test changes:

* Add each of the 12 sentences above to `test_article_work_instructions_catch_instructions_but_not_their_negation` with `expected >= 1`. Use `bool(...)`, since the new helper returns matches, not clauses.
* Add these three to the same test with `expected == 0`, alongside the existing negative cases:
  * "Code hands the Writer the latest draft together with the QA report that audited it."
  * "Apply this table to the latest draft's QA report."
  * "Read each QA report; decide from the latest report alone."
* Widen the feedback pattern at l.428 to
  `r"\b(?:feedback|revision (?:notes|instructions?)|instructions? for the Writer|tell the Writer|give the Writer)\b"`
  and apply it with the same verb-scoped negation.
* Add synthetic-string tests for those three feedback phrasings.

### 🟢 Minor

**QA-m1. The run-bound and failed-call patterns miss common forms.** The code is in `tests/test_unit/test_supervisor.py`: `_RUN_BOUNDS` (l.334–339) and `failed_call` (l.456). Missed:

* "Stop after 20 tool calls."
* "Do not call more than 30 tools."
* "If the same violation repeats three times, stop."
* "Finish within 40 calls."
* "If qa_tool returns an error, call it again."
* "When QA-Legal errors, save the draft."

**Fix:**
* Add `r"\b(?:after|within|more than|at most|up to|no more than) \d+ (?:tool )?(?:calls|tools)\b"`.
* Add `r"\bviolations? (?:repeats?|occurs?) (?:\d+|one|two|three|four|five) times\b"`.
* Widen `failed_call` to `\bfail|\berrors?\b|returns an error`, scoped to clauses naming `scout_tool`, `qa_tool`, `Scout` or `QA-Legal`. Check that the current prompt still yields `[]`: the prompt's "error" only appears as the `ERROR` status and `ToolResult.error`, so match `\berrors?\b` case-sensitively in lower case.
* Add one synthetic test per phrasing.

**QA-m2. The priorities test accepts an invented extra priority (M7).** It is `test_supervisor_prompt_states_the_d_c_run_level_priorities_verbatim` in `tests/test_unit/test_docs_consistency.py`. Appending `3. **Start every candidate first.** Draft every candidate before auditing any.` left it green, which breaks "D-C and the prompt agree on the priorities".

**Fix:** after the existing assertion, take the numbered list under `**Run-level priorities,**` in the prompt and assert it equals D-C's:

```python
block = prompt.split("**Run-level priorities,** applied on top of the table:\n", 1)[1]
assert re.findall(r"^\d+\. (.+)$", block.split("\n\n", 1)[0], re.MULTILINE) == priorities
```

**QA-m3 (optional). The D-F text check skips `tdi_cta`.** It is `test_scripted_supervisor_never_receives_article_text`, l.589. The key check already covers the schema, but the value check names only three article fields. Optionally add `"tdi_cta"` to the field tuple, so the CTA text is shown not to reach the Supervisor either.

### Optional notes (no change required)

* **For Iteration 14.** After a fatal stop, `run_supervisor` returns `summary == ""`, which is tested. The composition root should decide whether `RunState.supervisor_summary` stores `""` or `None`; the architect's F-risks already cover the Iteration 14 handoff.
* The architect's O1 to O3 stand. I agree that the "rule 7/8/9" cites stay verbatim under AC1.

## 5. Needs a decision

None.

---

# QA Review: Iteration 13, Supervisor agent (round 2)

## 1. Summary and verdict

**Verdict: PASSED** (round 2 verdict line: **PASS**).

Fix round 1 resolves QA-M1, QA-m1, QA-m2 and QA-m3. Every realistic sentence and in-memory mutation from round 1 is now caught, the benign control stays green, and the real prompt yields nothing under any of the strengthened checks. `src/supervisor.py` is unchanged. AC1 to AC3 still hold.

The remaining items are minor and test-side. The backtracking in `_ARTICLE_WORK` (architect A1, which I reproduced) is latent: on the real prompt every check runs in milliseconds, and it is not why the suite got slower. None of them blocks.

### Checks I ran myself

| Check | Result |
| :--- | :--- |
| `uv run pytest -q --durations=15` | **1243 passed**, 0 failed, 0 errors, no warnings summary, in 120.7 s. The count matches the implementer's claim of 1201 + 42 |
| `uvx ruff check src tests --no-cache` | All checks passed! |
| `uv run pytest -m live --collect-only -q` | No tests collected (1243 deselected) |
| `src/supervisor.py` unchanged | Last written 16:04:27, before architect round 1 (16:13) and QA round 1 (19:14). sha256 `08cd9c41…e791`. `git diff HEAD -- src/` is empty, so `src/tools.py` and `src/schemas.py` are untouched |
| Changed files alone | `test_supervisor.py` and `test_docs_consistency.py`: 363 passed in 10.8 s. The slowest supervisor test takes 0.26 s |
| Stray processes | No `python.exe` or `uv.exe` was created today, after all my runs. The ones left are harness MCP servers from 29 and 30 September, as in round 1 |
| Scratch files | All were in the session scratchpad, which I deleted. The working tree shows only the six expected paths |

## 2. Runtime: 32.6 s → 120.7 s

**Cause: environmental, not the regexes.**

* **Where the time went.** All 13 of the slowest durations are in `tests/test_integration/test_mcp_client.py`, at 6.5–7.6 s each. Each one spawns the substrate subprocess. That file is unchanged since commit 5b6ae08.
* **The suite without that file:** `--ignore=tests/test_integration/test_mcp_client.py` gives 1219 passed in 35.1 s, which is the round 1 figure for the whole suite.
* **The machine is slow today.** A bare `python -c "import src.supervisor, src.tools"` takes 5.6 s, and `--collect-only` takes 9.2 s.
* **The new regexes are fast on real input.** All four checks over the real prompt finish in milliseconds.

**Latent backtracking, confirming architect A1.** `_ARTICLE_WORK` (l.332) grows as about n⁵ on comma-dense text after an article verb, because `\S+` and `[ ,]+` both match a comma. Measured on `"review" + " ," * n`:

```text
aw_commas n=10: 0.2 ms
aw_commas n=20: 3.7 ms
aw_commas n=40: 105.3 ms
aw_commas n=80: 3775.7 ms
n=200: no result within 300 s
```

With `\S+` replaced by `[^\s,]+`, n=80 takes 0.7 ms. The fixed pattern gives the same match count as the current one on all 33 texts I checked: every probe, every no-hit case, and the prompt at `None`, `1` and `3`.

`_NEGATED_BEFORE` has the same ambiguity, but it stays fast in practice: 0.0 ms at n=80, because the `$` anchor prunes the search. The same replacement is safe there too.

**Severity:** 🟢 Minor. No current input triggers it. A future prompt line with a long run of commas after "review" or "read" would hang the suite rather than fail it.

## 3. Re-verification of the round 1 items

| Item | Status | Evidence |
| :--- | :---: | :--- |
| QA-M1, article work | ✅ | All 15 round 1 sentences are caught (0 mismatches), and so are 11 of 12 fresh probes ("Proofread every saved draft.", "Correct any typos in the drafts.", "Rewrite the draft's summary.", …). 0 of 12 harmless sentences are flagged, including the Role's negation, `review_notes`/`newsworthiness_score`, "Apply this table to the latest draft's QA report." and "Decide whether to revise or save the draft." |
| QA-M1, Writer feedback | ✅ | All 5 requested phrasings are caught. 0 of 4 harmless sentences are flagged |
| QA-m1, run bounds and failed calls | ✅ | All 6 round 1 phrasings are caught. 0 false positives on the `ERROR` row, the `ERROR` status, the Writer's `ToolResult.error` rule, "up to 2 revisions" and "3 Writer attempts" |
| QA-m2, invented priority | ✅ | Mutation M7 now fails the priorities test, `ceiling-2` and `no-ceiling` alike |
| QA-m3, `tdi_cta` | ✅ | `ARTICLE_FIELDS` includes `tdi_cta`, and the value check iterates over it. I confirm architect A4: `article_body`'s value holds `\n`, so the raw value is never found in `json.dumps(...)`, and that one field's value check cannot fire. The key check still covers it |

**Real prompt:** `_article_work_instructions`, `_writer_feedback_instructions`, `_failed_call_rules` and `_run_bounds` each return `[]` for `build_supervisor_prompt(None | 1 | 2 | 3)`.

**End-to-end, in memory.** A throwaway `-p` plugin patched `build_supervisor_prompt` in memory, then I ran `test_supervisor.py` and `test_docs_consistency.py`. No repository file was edited.

```text
== control (no mutation)                                                          363 passed
== Before saving, review each draft and improve its wording where QA-Legal objects.  2 failed, 361 passed
== Read the latest draft and check the article for errors before you call save_draft.  2 failed, 361 passed
== If QA-Legal reports no issues, still review the draft yourself and tell the Writer what to fix.  4 failed, 359 passed
== Give the Writer revision notes.                                                2 failed, 361 passed
== Stop after 20 tool calls.                                                      2 failed, 361 passed
== If the same violation repeats three times, stop.                               2 failed, 361 passed
== If qa_tool returns an error, call it again.                                    2 failed, 361 passed
== When the Scout fails, finish the run.                                          2 failed, 361 passed
== Code renders every saved draft at run end.  (benign control)                   363 passed
== M7 invented third priority                                                     2 failed, 361 passed
```

In round 1, the first three sentences left the suite fully green (321 passed).

**The Red claims.** I cannot replay the implementer's Red steps after the fact. These mutations show the strengthened tests fail on the forbidden content and pass without it, so they are real coverage and not stub-passing checks.

## 4. Gate matrix

| Gate | Topic | Status | Notes |
| :--- | :--- | :---: | :--- |
| 1 | Strict TDD | ✅ | The negative §7.4 checks now fail on realistic forbidden prompts (§3). Production code is unchanged, and every branch was already covered in round 1 |
| 2 | Zero-token testing | ✅ | As in round 1. No model is added; the live collection is empty |
| 3 | Pydantic v2 contracts | ✅ | No change |
| 4 | Guardrails and attempt cap | n/a in this iteration | The cap in the prompt is still pinned to `MAX_ATTEMPTS_PER_DOC` (AC3 test green) |
| 5 | Strands integration and telemetry | ✅ | No change |
| 6 | No article text for the Supervisor | ✅ | The key check covers every forbidden key. The value check covers `headline`, `executive_summary` and `tdi_cta`; `article_body`'s value check is vacuous (A4, minor) |
| 7 | Drafts and logging | ✅ | No change |
| 8 | Python and subprocess safety | ✅ | Ruff is clean, there is no stray process, and the pytest output is clean. The backtracking is a latent hazard in test code only (§2) |

## 5. Acceptance criteria and Definition of Done

| # | Criterion | Status | Evidence |
| :--- | :--- | :---: | :--- |
| AC1 | Each D-C row is in the prompt, checked against a list from the specification | ✅ | `test_supervisor_prompt_copies_the_d_c_decision_table_row_for_row` passes at both ceilings |
| AC2 | Tool descriptions match §7.1 word for word, and the prompt covers every §7.4 item | ✅ | The description equality, `PROMPT_ITEMS` and the ceiling tests pass. The forbidden-content half is now really tested (§3) |
| AC3 | D-C and the prompt agree on the cap and the priorities | ✅ | The cap test passes, and the priorities test now requires an exact list match, which M7 confirms |

**Definition of Done:** DoD-1 to DoD-5 ✅. DoD-6 (`WALKTHROUGH.md`) is pending for Stage 4.

**Totals:** 3 of 3 acceptance criteria and 5 of 5 applicable DoD rows hold.

## 6. Findings by severity

### 🔴 Blocker

None.

### 🟡 Major

None.

### 🟢 Minor (none blocks; apply in a fix round if one runs, or record in `WALKTHROUGH.md` as accepted test-side limits)

* **QA-m4, which concurs with architect A1: backtracking in `_ARTICLE_WORK`.** The evidence is in §2. The fix is the architect's: `\S+` → `[^\s,]+` at l.332, plus a guard case. I would apply it to `_NEGATED_BEFORE` (l.338) as well, for consistency.
* **QA-m5, which concurs with architect A4: `article_body`'s value check cannot fire.** I confirmed it independently. Use the architect's escaped-form check.
* **QA-m6 (optional): the deny-list tail.** These fresh phrasings are still missed. They are beyond what round 1 asked for, so they are recorded here, not required:
  * article work: "Look over the draft and polish its headline." The phrasal verb "look over" is not in the list. The architect's A2 and A3 cover further inflection and negation gaps;
  * feedback: "Explain to the Writer what QA-Legal found.", "Pass your comments to the Writer.", "Brief the Writer on each issue." and "Provide guidance to the Writer.";
  * failed call: "If qa_tool raises, retry it.", "Should the Scout time out, finish the run." and "If QA-Legal cannot audit the draft, save it anyway.";
  * run bounds: "Stop after three violations.", "Stop after the third violation.", "Never exceed 50 tool calls." and "Call at most twenty tools." The violation-count pattern takes digits only, while the repeat pattern also takes number words.

  A deny-list cannot be complete. The cheap wins are number words in the `after|at most|more than N violations` and tool-call patterns, plus `exceed`, and `brief|explain to|guidance|comments` in `_WRITER_FEEDBACK`.

### Record

The implementer replaced my round 1 items in `FIXES.md` with a pointer. I restored them there, append-only, under *QA — round 1 (restored record)*.

## 7. Needs a decision

None.
