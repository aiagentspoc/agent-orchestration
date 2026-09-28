# QA Review — Iteration 1: Project documents and working rules (round 1)

**Reviewer:** QA and Verification Agent · **Date:** 2026-09-28 · **Branch:** `approach-2/implementation` (uncommitted working tree)

## 1. Summary and verdict

**Verdict: PASSED**

Iteration 1 delivers what `IMPLEMENTATION_PLAN.md` promises:
* `AGENTS.md` and `CLAUDE.md`;
* `tests/test_unit/test_docs_consistency.py`, which covers every bullet of the Red list;
* the workflow edits that add `AGENTS.md` to both review skills and to the three subagents.

I ran every check myself, and every number in the implementer's report matches the real output. All three acceptance criteria hold. So do DoD-1, DoD-2, DoD-3 and DoD-5; DoD-4 is n/a, and DoD-6 is the orchestrator's Stage 4 step.

I probed the docs test by mutating the real documents in memory, from a script outside the repository. It caught 24 of 29 drifts, and the five misses are all weak spots in its heuristics, not missing rules. There are no blocker or major findings. I report three minor items of my own, which I have opened in `FIXES.md` as non-blocking. I also concur with the architect's A1 and C1.

### Commands run and real output

| Command | Real result |
| :--- | :--- |
| `uv run pytest -q` | `188 passed in 2.15s`. It matches the report: 16 from Iteration 0 plus 172 new |
| `uv run pytest tests/test_unit/test_docs_consistency.py -q` | `172 passed in 0.36s` |
| `uv run pytest -q -W error` | `188 passed`: no warnings are emitted |
| `uv run pytest --collect-only -q` | `188 tests collected` |
| `uvx ruff check src tests --no-cache` | `All checks passed!` |
| `uv run pytest -m live --collect-only -q` | `no tests collected (188 deselected)`. This was the only live command run |
| `git diff 2c8a7dc -- .agents/docs/DESIGN.md` (and `SPECIFICATIONS.md`, `.agents/templates/draft.md`) | 0 lines each. The last commit that touched DESIGN.md is `eb6418e` |
| Mermaid block of SPECIFICATIONS.md §4, extracted with `awk` to a session temp directory outside the repo; `npx -y @mermaid-js/mermaid-cli -i flow.mmd -o flow.png` | The block is 61 lines. mmdc exited 0 and wrote a 143 KB PNG. I viewed it: the full flowchart renders with all nodes and edges, from the CLI start to the exit code, including the fatal-stop branch. `git status --short --ignored` afterwards shows nothing new in the repo |
| Test count for `test_document_uses_no_forbidden_term` | 18 files before this review wrote its files. It matches the report's "18 files" |
| Process check (`Win32_Process`) | Every running `python.exe` and `uv.exe` is one of this session's MCP servers (`hse-easy-mock`, `strands-agents-mcp-server`). The test module has no subprocess, socket, network or write call, so it leaves no orphan |
| `hse-easy-mock`: `list_regulatory_updates(limit=1)`, `verify_legal_citation`, `get_tdi_service_offerings` | The live shapes match the `AGENTS.md` §4 table and SPECIFICATIONS.md §6.1. List tools wrap `list[...]` under `result`; `CitationVerificationResult` has all eight fields. No integration test asserts shapes in this iteration |

## 2. Gate matrix

| Gate | Topic | Status | Notes |
| :--- | :--- | :---: | :--- |
| 1 | Strict TDD | ✅ | Eleven behaviours, each with a stated Red. Behaviours 1, 2, 3, 8 and 11 failed on real document content first, and the report names the exact failures: the missing guides, 18 missing links, the one stale `tests/...` citation, and the two non-canonical caps in `qa.md` and `code-reviewer/SKILL.md`. For behaviours 4 to 7, 9 and 10, the Red was a missing helper name, because the documents already complied. The plan accepts a missing name as a Red. The gap, a rule never seen failing on real text, is closed by each helper's own self-test on synthetic strings, by the implementer's 13-case mutation probe and by mine (§4). No `src/` code was added. Deviation: the behaviour 11 tests, "AGENTS.md is listed", are extra to the Red list. The deviation is recorded, and it test-drives the Green workflow edits |
| 2 | Zero-token testing | ✅ | Text assertions only. The module does no model construction, no `.env` read and no network access. It only reads the repository, plus `exists()` checks on `../code-orchestration/` and `../mcp-server/`, which the plan's own path rule requires. No live tests exist; the only live command run was `--collect-only` |
| 3 | Pydantic v2 contracts | n/a in this iteration | No models. The docs test pins SPECIFICATIONS.md §6: 27 models, the four settings classes, the 7 `[New]` markers and the §6.9 membership |
| 4 | Guardrails and attempt cap | n/a in this iteration | No guardrail code. The docs test pins the 12 `GuardrailName` values in §6.7 order and the cap statements (see finding QA-m3 and the architect's C1) |
| 5 | Strands integration and telemetry | n/a in this iteration | |
| 6 | No article text for the Supervisor | n/a in this iteration | |
| 7 | Drafts and logging | n/a in this iteration | The D-I (level, event) pairs are pinned in order |
| 8 | Python and subprocess safety | ✅ | The module is fully annotated, with imports at the top, and ruff is clean. It uses `pathlib.Path` throughout; `os.walk` and `os.path.normcase` appear only because `Path.walk` needs Python 3.12 and the project runs 3.11. No subprocess, no orphans, no warnings |

## 3. Acceptance criteria and Definition of Done

| # | Criterion | Status | Evidence |
| :--- | :--- | :---: | :--- |
| AC1 | `uv run pytest tests/test_unit/test_docs_consistency.py` passes | ✅ | `172 passed in 0.36s` |
| AC2 | `DESIGN.md` is unchanged since the Iteration 0 commit | ✅ | `git diff 2c8a7dc -- .agents/docs/DESIGN.md` is empty |
| AC3 | The Mermaid block in §4 renders | ✅ | mmdc exited 0, and the PNG was viewed, outside the repository |
| DoD-1 | Full default suite passes | ✅ | 188 passed, 0 failed, 0 errors |
| DoD-2 | Lint is clean | ✅ | `All checks passed!` |
| DoD-3 | No live model call | ✅ | See Gate 2 |
| DoD-4 | Every new `src/` function tested | n/a | No `src/` change |
| DoD-5 | Docs match code | ✅ | Same as AC1 |
| DoD-6 | `WALKTHROUGH.md` written | pending | The orchestrator writes it in Stage 4 |

**Acceptance criteria: 3 of 3 passed. DoD: 4 of 4 applicable rows passed; DoD-4 n/a; DoD-6 pending, as it is the orchestrator's.**

### Red-list coverage (every bullet of the plan's Iteration 1 Red)

| Red bullet | Test(s) | Covered |
| :--- | :--- | :---: |
| The 11 files exist | `test_required_document_exists` (11 cases) | ✅ |
| Both guides link to the 3 core docs and the 6 workflow files | `test_project_guide_links_to_each_document_and_workflow_file` (18 cases) | ✅ |
| Every cited path exists, with the plan's exemptions and the four bases for bare names | `test_every_cited_path_exists` (8 files) and the helper self-tests | ✅ See the note below |
| `.claude/settings.json`: `additionalDirectories` and `enabledMcpjsonServers` | `test_claude_settings_grant_sibling_read_access_and_enable_both_mcp_servers` | ✅ |
| No scratchpad citation, in exactly the file set the plan names | `test_document_does_not_cite_the_scratchpad_design_plan` (10 files) | ✅ |
| SPECIFICATIONS.md holds its models, guardrails, exit codes, D-A to D-J, the D-C rows, the D-I events, the §7.1 descriptions and P1 to P6 | Eight `test_specification_*` tests | ✅ See QA-m1 and QA-m2: D-C conditions and P1 to P6 are pinned only in part |
| P1: DESIGN.md §4 states the binding, and no document states a partial set | `test_design_states_...` and `test_document_does_not_say_...` (11) | ✅ The phrase list is a denylist; see the architect's C2 |
| The attempt cap is consistent | `test_document_states_no_attempt_cap_but_the_canonical_one` (11) and `test_document_that_restates_the_cap_still_states_it` (7) | ✅ See the architect's C1 |
| No forbidden terms, in every `.md` of the repo | `test_document_uses_no_forbidden_term` (18) and the pattern self-test | ✅ |
| No removed model named as current | `test_document_names_no_removed_model_as_current` (11) | ✅ See QA-m3 |

**Green items:**
* `AGENTS.md` carries:
  * product rules 1 to 6, covering all five of the plan's product topics;
  * working rules 7 to 10, covering all four working topics;
  * the layout and placement rule.
* `CLAUDE.md` is a thin pointer that mirrors Approach 1's `CLAUDE.md` structure section for section.
* Both review skills list `AGENTS.md` in their Sources of truth.
* All three subagents list it as mandatory reading.
* The `qa.md` line-69 correction is accurate: it is the attempt, not the cap, that is appended before the Writer runs.

**Note on the path rule.** I dumped every cited token per file:
* Exemptions by the workflow-created rule are only `.agents/tasks/iteration-(NN|03)/…`, `.agents/tasks/QUESTIONS.md` and the bare artifact names.
* Tokens the classifier excludes are only slash commands, the branch name and placeholder paths (`draft_{YYYYMMDD}_{XXX}.md`, `logs/run_YYYYMMDD.log`, `.claude/agents/<role>.md`), plus one command string.
* No bare name currently resolves only through the Approach 1 fallback.

So no real stale path is being hidden.

## 4. Mutation probe of the docs test

Each mutation replaces text in one real document, in memory only, and then calls the relevant test function. Before any mutation, every probed test passed.

| Drift | Result |
| :--- | :--- |
| Model renamed · `[New]` marker dropped · guardrails reordered · `SUPERVISOR_ERROR = 7` · D-G heading broken · P6 row relabelled | caught |
| D-C decision cell changed (`ERROR`, ≥ 1, `Revise` → `Save`) · D-I level changed · §7.1 description edited ("once" → "twice") | caught |
| DESIGN.md §4 binding sentence removed · "Scoped Tools" added to DESIGN.md | caught |
| AGENTS.md cap stated as 4 · SPEC rule 4 stated as "4 attempts per document" · AGENTS.md cap statement deleted | caught |
| Removed model as current · scratchpad citation · nonexistent path, bare name or link target · CLAUDE.md link to `qa.md` removed · reserved feature named · `AGENTS.md` row removed from a review skill · removed from `qa.md` reading | caught |
| **P3 row text rewritten, label kept** | **not caught** (QA-m2) |
| **D-C `WARNING` condition cut to "a citation"** | **not caught** (QA-m1) |
| D-I key-fields cell edited | not caught; the plan asks for events, not fields, so this is by design |
| **SPEC cap as "four Writer attempts" · "The cap of 4"** | **not caught** (the architect's C1; see QA-m3's note) |
| **Removed model in a sentence that happens to contain "without"** | **not caught** (observation O1) |

## 5. Findings by severity

### 🔴 Blocker
None.

### 🟡 Major
None.

### 🟢 Minor

* **QA-m1: the D-C decision table is pinned only by fragments.**
  * **Problem.** `DECISION_TABLE_ROWS` holds a fragment of each condition cell and the start of each decision cell, so the rest of a row can drift unnoticed.
  * **Why it matters.** Iteration 13, acceptance criterion 1, checks the Supervisor prompt "against a list of the rows taken from `SPECIFICATIONS.md`". The decision table is therefore prompt content, a benchmark constant, just like the §7.1 descriptions, which are pinned word for word.
  * **Fix.** In `FIXES.md`.
* **QA-m2: P1 to P6 are pinned by label only.**
  * **Problem.** The test checks only that §8.3 has rows labelled `P1` to `P6`, in order. A row's decision text can change, and nothing ties §8.3 to `IMPLEMENTATION_PLAN.md` §2, which SPECIFICATIONS.md says it records.
  * **Fix.** In `FIXES.md`.
* **QA-m3: `REMOVED_MODELS` holds 6 of the 11 names that SPECIFICATIONS.md §6 lists as removed.**
  * **Problem.** The missing names are `ScoutResult`, `WriterResult`, `QAResult`, `SaveResult` and `DocumentOutcome`. The plan's Red list and `code-reviewer` Gate 3 name only the six, but the reviewer skill says SPECIFICATIONS.md wins and that the difference is reported.
  * **Verified.** Extending the list passes against all 11 documents today.
  * **Fix.** In `FIXES.md`.
* **Concur with the architect's A1:** `AGENTS.md` Rule 1 points log events to §6 and §7, but they are in D-I, §5. I found this independently.
* **Concur with the architect's C1:** the cap extractor. It also misses number words. "four Writer attempts" in SPECIFICATIONS.md was not caught, because that document still states `MAX_ATTEMPTS_PER_DOC = 3` elsewhere, so the check for a canonical form passes. Optional addition: a `(one|two|three|four|five|six) Writer attempts` pattern, with a word-to-int map.

### Observations (no fix required)

* **O1.** `_REMOVAL_WORDS` includes broad words (`without`, `becomes`, `delete`). Any sentence that contains one exempts a removed model anywhere in it. This is acceptable as a recorded §1.5 heuristic; tightening it would mean requiring the word near the model name.
* **O2.** The plan and the test module cite "the project memory" as the source of the forbidden-terms list. The Claude Code project memory folder for this repository is empty on disk. A later session therefore cannot check the list against its source, and today only the orchestrator's brief states the user's reservation. The orchestrator may wish to record the reservation somewhere durable. This is not an implementer action, and it is not a §1.4 stop condition.
* **O3.** `DOCS_STATING_THE_CAP` and the cap scan cover only the 11 named documents, not `.agents/tasks/**`. That is correct: records state what was true when they were written.

## 6. Remediation

The exact instructions for QA-m1 to QA-m3 are in `.agents/tasks/iteration-01/FIXES.md`, under `## 🧪 QA & Verification`. All three change only `tests/test_unit/test_docs_consistency.py`, and none requires a document edit. I verified the proposed P1 to P6 lead pins and the full D-C row values against the current SPECIFICATIONS.md and IMPLEMENTATION_PLAN.md; they pass as written.

---

# QA Review — Iteration 1, round 2 (fix-round re-review)

**Reviewer:** QA and Verification Agent · **Date:** 2026-09-28 · **Scope:** the implementer's fix round for A1, C1, C2, QA-m1, QA-m2 and QA-m3

## R2.1 Summary and verdict

**Verdict: PASSED**

All six round-1 items are resolved in substance, and every number in the implementer's report matches the real output. I re-probed each fix in memory, from a script in the session scratchpad that swaps the test module's `_read` for a mutating reader. Nothing in the repository was written, apart from this file and `FIXES.md`.
* Every drift that round 1 missed and that an item addressed is now caught.
* All 11 removed models are caught.
* Every D-C cell edit and every P-statement edit I tried is caught.

There is one new minor finding, QA-m4, which is non-blocking. The C2 phrase list still misses the architect's own round-1 probe sentence. The remaining misses are phrasings that no item asked for; I record them as observations.

### Commands run and real output

| Command | Real result |
| :--- | :--- |
| `uv run pytest -q` | `198 passed in 2.06s`. It matches the report |
| `uv run pytest tests/test_unit/test_docs_consistency.py -q` | `182 passed in 0.26s`. It matches the report |
| `uv run pytest -q -W error` | `198 passed`: no warnings are emitted |
| `uvx ruff check src tests --no-cache` | `All checks passed!` |
| `uv run pytest -m live --collect-only -q` | `no tests collected (198 deselected)`. This was the only live command run |
| `--collect-only` per test function | The delta is +10. `test_document_uses_no_forbidden_term` went from 18 to 21 cases: the three new `iteration-01` records. The other 7 are new cases: C1 +2, C2 +2, QA-m2 +2 (the pure helper test and the two-document parametrization), and QA-m3 +1. This matches the report's "7 new cases, 3 per-document" |
| `git diff 2c8a7dc -- .agents/docs/DESIGN.md` | 0 lines (AC2). `SPECIFICATIONS.md` and `draft.md` are also unchanged. The tracked diff is the same 7 workflow and plan files as in round 1 |
| `git status --short` after the probes | Unchanged. The probes wrote nothing to the repository |

## R2.2 Verification of each fix

| Item | Fix verified in the code | In-memory probe (the fixed test run against the mutated document) | Status |
| :--- | :--- | :--- | :---: |
| A1 | `AGENTS.md:64` now reads "…defined in `SPECIFICATIONS.md` §6 and §7, and every log event in its D-I catalogue." D-I is `#### D-I. Logging`, in §5 | n/a (a document fix) | ✅ |
| C1 | `_CAP_STATEMENTS` adds "cap of / capped at N" and "up to / maximum of / max N (Writer) attempts". The prose patterns accept digits or the whole number words one to ten. `_stated_attempt_caps` dedups by capture position. Order is kept: the synthetic line returns `[4, 5, 2, 6]` | Caught: "A cap of 4 attempts" in DESIGN, SPEC and AGENTS; "four Writer attempts" in SPEC; "capped at 4"; "up to 4 attempts"; "maximum of five Writer attempts"; "a four-attempt budget"; "Four attempts per document"; "The attempt cap is four". "Three Writer attempts" correctly passes | ✅ |
| C2 | `PARTIAL_BINDING_PHRASES` adds six phrases: "only has access to", "has access only to", "connected only to", "only connected to", "limited to the tools" and "restricted to the tools". "prompt limits it to the tools" still returns `[]` | Caught: all eight synthetic restriction sentences built on the listed phrases. **Missed: "The Scout is limited to the list and search tools."**, the architect's own round-1 probe sentence (QA-m4) | ✅ with QA-m4 |
| QA-m1 | `DECISION_TABLE_ROWS` holds all four cells of all ten rows, and the test asserts `rows == [list(row) for row in DECISION_TABLE_ROWS]` | Caught: the `WARNING` condition cut to "a citation" (the round-1 miss); "(rule 9)" changed to "(rule 8)"; the advisory condition edited; the Skip decision edited; the PASS decision tail edited; an extra row inserted | ✅ |
| QA-m2 | `IMPLEMENTATION_DECISIONS` pins each lead statement. The pure helper `_decisions_without_their_statement` has a synthetic Red test covering both label styles, and the test is parametrized over SPEC §8.3 and PLAN §2. The label-order test compares against `list(IMPLEMENTATION_DECISIONS)` | Caught: SPEC P3 rewritten with its label kept (the round-1 miss); SPEC P6 "maximum" changed to "minimum"; PLAN P2 drifted; PLAN P1 drifted; a PLAN row relabelled; SPEC P4 and P5 labels swapped | ✅ |
| QA-m3 | `REMOVED_MODELS` holds all 11 names of SPEC §6 line 543, the plan's six first | Caught: "Each worker returns a `<model>`." for each of the 11 names | ✅ |

**Red evidence.** The implementer's Reds cannot be replayed after the fact. They are, however, consistent with round 1: the drifts my round-1 probe listed as "not caught" are the same ones the new code now catches, as shown in the table above. The C1 expected value in the parametrized case is `[2, 4, 5, 6]`, the architect's figure. The implementer's remark means that before the dedup, the list read `[2, 2, 4, 5, 6]`. The dedup is correct: two patterns cannot capture different numbers at the same position.

**FIXES.md handling.** The implementer replaced the resolved items with one-line notes. This is consistent with `implementation.md` fix mode, step 4. The full round-1 text survives in `QA_REVIEW.md` §5 and `ARCHITECT_REVIEW.md`.

## R2.3 Gate matrix (round 2)

| Gate | Topic | Status | Notes |
| :--- | :--- | :---: | :--- |
| 1 | Strict TDD | ✅ | Each item has a Red that fails on assertion: synthetic cases for C1, C2, QA-m2 and QA-m3, and the tightened assertion for QA-m1. A1 is a document fix. No `src/` code |
| 2 | Zero-token testing | ✅ | Unchanged: text assertions only, and no live tests |
| 3 | Pydantic v2 contracts | n/a in this iteration | The removed-models scan now covers all 11 names |
| 4 | Guardrails and attempt cap | n/a in this iteration | The cap scan is widened (C1) |
| 5 | Strands integration and telemetry | n/a in this iteration | |
| 6 | No article text for the Supervisor | n/a in this iteration | |
| 7 | Drafts and logging | n/a in this iteration | `AGENTS.md` now cites D-I correctly (A1) |
| 8 | Python and subprocess safety | ✅ | The new helpers are annotated and ruff is clean. Still no subprocess or I/O beyond reads, and no warnings under `-W error` |

## R2.4 Acceptance criteria and Definition of Done (re-checked)

| # | Criterion | Status | Evidence |
| :--- | :--- | :---: | :--- |
| AC1 | The docs test passes | ✅ | `182 passed` |
| AC2 | `DESIGN.md` is unchanged since the Iteration 0 commit | ✅ | 0 diff lines |
| AC3 | The Mermaid block in §4 renders | ✅ | SPECIFICATIONS.md is unchanged since the round-1 render (0 diff lines against `2c8a7dc`), so the round-1 mmdc result stands |
| DoD-1 | Full default suite passes | ✅ | `198 passed`, 0 failed, 0 errors |
| DoD-2 | Lint is clean | ✅ | `All checks passed!` |
| DoD-3 | No live model call | ✅ | Only `--collect-only` was run |
| DoD-4 | Every new `src/` function tested | n/a | No `src/` change |
| DoD-5 | Docs match code | ✅ | Same as AC1 |
| DoD-6 | `WALKTHROUGH.md` written | pending | The orchestrator writes it in Stage 4 |

**Acceptance criteria: 3 of 3 passed. DoD: 5 of 5 applicable rows passed; DoD-4 n/a; DoD-6 pending, as it is the orchestrator's.**

## R2.5 Findings by severity

### 🔴 Blocker
None.

### 🟡 Major
None.

### 🟢 Minor

* **QA-m4: the C2 list still misses the architect's own round-1 probe sentence.**
  * **Problem.** The round-1 review showed that `_partial_binding_claims("The Scout is limited to the list and search tools. …")` returned `[]`. It still does, because "limited to the tools" is a literal phrase and the tool names sit between "to" and "tools".
  * **Candidate fix.** A tool-anchored regex that requires "is" or "are", then "limited to" or "restricted to", then the word "tools" within 60 characters on the same sentence:
    * catches that sentence;
    * does not match DESIGN.md's "prompt limits it to the tools" or "limited to the top 5 candidates";
    * has zero hits on the 11 documents today.
  * **Fix.** The exact pattern is in `FIXES.md`. This item is non-blocking. If the architect reopens C2 for the same sentence, one fix closes both items.

### Observations (no fix required)

* **O4, a false-positive risk in C1.** The "cap of / capped at N" pattern is not anchored to attempts, so "a cap of 5 drafts" is read as an attempt cap of 5. No document triggers it today; the only "cap of" in the 11 documents is followed by a backtick. It would fail loudly rather than hide a drift, so it is acceptable. It is noted so that a later failure is recognised.
* **O5, C1 residual phrasings.** "The attempt limit is 4", "The cap is four attempts", "4 attempts per doc" and "at most 4 attempts" still pass. Only the first appeared in the architect's round-1 probe; none was in the requested fix. The accepted limit of phrase scans holds, and Iteration 4's `MAX_ATTEMPTS_PER_DOC` is the code-level lock.
* **O6, the P1–P6 pins are lead pins by design.** Editing the text after a decision's bold lead statement is not caught, for example P1's "all five substrate tools" clause. This is what round 1 proposed. The P1 binding itself is also pinned by the DESIGN.md §4 test.
* **O1, from round 1, still holds.** A removed model in a sentence that contains "without" is still exempt.
