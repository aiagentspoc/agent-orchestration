# Architect Review — Iteration 1: Project documents and working rules (round 1)

**Reviewer:** `architect` subagent, Stage 3.
**Scope audited:** `git status --short` and `git diff` against `2c8a7dc` (Iteration 0), plus the three untracked files read directly: `AGENTS.md`, `CLAUDE.md`, `tests/test_unit/test_docs_consistency.py`. Criteria: `.agents/skills/architect-review/SKILL.md`, `.agents/skills/code-reviewer/SKILL.md`, `IMPLEMENTATION_PLAN.md` §1, §2, §4 and Iteration 1, `SPECIFICATIONS.md` §1, §3–§8, `DESIGN.md`, `.agents/templates/draft.md`, and Approach 1's `AGENTS.md`, `CLAUDE.md` and `tests/test_unit/test_docs_consistency.py` (read only).

**Commands run (no model, no network, no live test):**

| Command | Result |
| :--- | :--- |
| `uv run pytest -q` | 188 passed, 0 failed, 0 skipped |
| `uvx ruff check src tests --no-cache` | All checks passed (0 in scope, 0 pre-existing) |
| `uv run pytest -m live --collect-only -q` | 0 collected, 188 deselected |
| `git diff 2c8a7dc -- .agents/docs/DESIGN.md .agents/docs/SPECIFICATIONS.md .agents/templates/draft.md` | Empty |

The Mermaid render (acceptance 3) was not re-run by this review, because it writes a PNG outside the review's write scope; the implementer's report records exit 0.

---

## 1. Overall verdict

**APPROVED WITH RESERVATIONS.**

No blocker and no major finding. The product rules in `AGENTS.md` keep control flow in the Supervisor, keep article text away from it, and restate the benchmark constants only by reference or in the specification's own words. The workflow edits are minimal and correct, and two of them fix real pre-existing defects. The docs test is substantive: it pins exact inventories, tables and descriptions, and every scanning helper has synthetic tests. Three minor findings are opened in `FIXES.md`: one citation slip in `AGENTS.md`, and two phrase lists in the test that miss common rewordings, so a drifted cap or tool binding could pass unnoticed.

---

## 2. Pillar audit

No `src/` code is added in this iteration. Pillars 1–7 are therefore audited as **what `AGENTS.md` tells future implementers**, since it is now a source of truth for every subagent.

| # | Pillar | Assessment |
| :---: | :--- | :--- |
| 1 | An agent owns the flow | ✅ `AGENTS.md:69` states the Supervisor decides the path by calling its four tools, and forbids a Writer/QA-Legal loop, status-driven revision in code, and Graph, Swarm or Workflow. `AGENTS.md:70` restates "code only refuses" and that a fatal error stops, never reroutes (D-D). The NOTE at `AGENTS.md:60-61` correctly separates the product principle from how the assistant sequences its own work, as Approach 1's `CLAUDE.md` does. Nothing moves control flow out of the Supervisor. |
| 2 | Division of labour | ✅ `AGENTS.md:71` states D-F: full drafts stay in `RunState`, the Supervisor gets only the §7.2 views, writes no feedback and no Markdown, and has no substrate access. It points to §1.1 for the table rather than paraphrasing it. |
| 3 | Custom agent tools | Not touched by this iteration (no rule restates D-A/D-G beyond Rule 1's pointer to §6 and §7). |
| 4 | Guardrails and attempt state | ✅ `AGENTS.md:75-77`: `MAX_ATTEMPTS_PER_DOC = 3`, 3 Writer attempts, appended before the Writer runs, the 12 `GuardrailName` values of §6.7 in the §7.3 order, a violation never ends the run. This matches D-C rules 3–4 (`SPECIFICATIONS.md:317-318`) word for word in substance. |
| 5 | Benchmark parity | ✅ `AGENTS.md:80` lists exactly the seven held-constant rows of `SPECIFICATIONS.md:42-50` (substrate, models and efforts, tool binding, prompts, template, cost basis, sequential execution). Models and efforts are cited by reference, not restated. The tool binding matches P1 and `SPECIFICATIONS.md:46`. The prompt rule matches `SPECIFICATIONS.md:47`. The MCP tool table at `AGENTS.md:127-133` matches the substrate signatures and §6.1's return types. |
| 6 | Substrate isolation and lifecycle | Not touched by this iteration. |
| 7 | Rendering, telemetry and logging | ✅ `AGENTS.md:83-90` matches D-B and D-I: `save_draft` marks and allocates only, rendering at run end, the compliance banner, one ledger entry per call on failure too, the Supervisor's one entry at run end, the equal share of the Scout and Supervisor, totals logged not stored, `logs/run_YYYYMMDD.log`, correlation fields and key redaction. One citation slip: see finding A1. |
| 8 | Code quality | ✅ with minor findings. See §3. |

**Checklist items:**
1. Control flow — no code; the rules forbid code sequencing. ✅
2. Division of labour — no path for article text is described or implied. ✅
3. Tool wrappers — n/a.
4. Guardrails — stated by reference to §6.7, §7.3 and D-C. ✅
5. Parity — no constant drifts; `DESIGN.md`, `SPECIFICATIONS.md` and `draft.md` unchanged since `2c8a7dc`. ✅
6. Lifecycle — n/a.
7. Observability — see A1.
8. Code quality — see §3.

### Workflow-file edits

All seven modified files were checked line by line (`git diff --stat`: 11 insertions, 5 deletions).

| File | Change | Assessment |
| :--- | :--- | :--- |
| `.agents/skills/architect-review/SKILL.md:19` | `AGENTS.md` row added to Sources of truth | ✅ As the plan's Green step asks. |
| `.agents/skills/code-reviewer/SKILL.md:17` | `AGENTS.md` row added | ✅ |
| `.agents/skills/code-reviewer/SKILL.md:22` | `tests/support/scripted.py` and `tests/conftest.py` now written as `../code-orchestration/…` paths | ✅ The old wording cited paths that do not exist in this repository until Iteration 2. The meaning is unchanged. |
| `.agents/skills/code-reviewer/SKILL.md:66` | `MAX_ATTEMPTS_PER_DOC == 3` → `= 3` | ✅ Now the canonical form of the plan's cap check. The meaning is unchanged. |
| `.claude/agents/architect.md:31` | Mandatory reading item 8, `AGENTS.md` | ✅ |
| `.claude/agents/implementation.md:30` | Mandatory reading item 6, `AGENTS.md` | ✅ |
| `.claude/agents/qa.md:29-30` | Item 6 `AGENTS.md`, "What actually landed" renumbered 7 | ✅ |
| `.claude/agents/qa.md:70` | "The attempt cap is 3 and is appended before the Writer runs" → "The attempt cap is `MAX_ATTEMPTS_PER_DOC = 3`, and each attempt is appended before the Writer runs." | ✅ Also corrects a real semantic defect: the old text said the *cap* is appended. |
| `.claude/skills/implement/SKILL.md:46` | `AGENTS.md` row in "Project files the subagents read" | ✅ Consistent with the three subagent edits. |
| `.agents/docs/IMPLEMENTATION_PLAN.md:125` | §3 row set to `🔄 In progress` | Orchestrator's change, per §1.1. Not the implementer's. |

No edit changes a criterion, a gate or a constant. Appending `AGENTS.md` at the end of each reading list, rather than first, is a §1.5 ordering decision and is recorded.

### `AGENTS.md` and `CLAUDE.md` against the plan's Green list

* Product rules: contracts in `SPECIFICATIONS.md` (Rule 1), the Supervisor supervises agents (Rule 2), cap and guardrails in code (Rule 3), benchmark constants (Rule 4), Markdown drafts at run end (Rule 5), telemetry and logging (Rule 6). All five required rules are present; Rule 4 is an addition that supports the benchmark. ✅
* Working rules: strict TDD (Rule 7), stop-and-ask replacing approval gates (Rule 8, faithful to §1.4's five conditions), review subagents with zero fallback (Rule 9), no live model calls (Rule 10). ✅
* Layout and placement rule, modelled on Approach 1's (`AGENTS.md:21-54`). ✅
* `CLAUDE.md` is a thin pointer to `AGENTS.md`, structured as Approach 1's `CLAUDE.md`, with the Approach 1-specific approval gate and three-round loop correctly replaced by "no human approval gate" and "at most two fix rounds" (§1.2 step 7). ✅
* Harness neutrality: `AGENTS.md` confines the Claude Code binding to Rule 9's last bullet and §1.1's `.claude/` row. ✅

### The docs test: meaningful, not vacuous

Every Red item of the plan is covered:

| Plan Red item | Test(s) | Strength |
| :--- | :--- | :--- |
| Eleven files exist | `test_required_document_exists` | Exact |
| Guides link to 3 docs and 6 workflow files | `test_project_guide_links_to_each_document_and_workflow_file` (18 cases) | Exact, resolved paths |
| Every cited path exists | `test_every_cited_path_exists` + 3 helper tests | Strong; fails rather than skips when a sibling is missing |
| `settings.json` | `test_claude_settings_grant_sibling_read_access_and_enable_both_mcp_servers` | Exact set equality, case-folded on Windows |
| No scratch design plan cited | `test_document_does_not_cite_the_scratchpad_design_plan` | Exact word match |
| §6 models, `GuardrailName`, `ExitCode`, D-A..D-J, D-C rows, D-I events, §7.1 descriptions, P1..P6 | Nine `test_specification_*` tests | Exact inventories; §7.1 and D-I pinned word for word and in order; sorted equality proves each model is declared once; the stated totals are pinned too |
| P1 | `test_design_states_that_every_sub_agent_is_connected_to_all_five_tools` + phrase scan | Positive check exact; negative check is a phrase list (finding C2) |
| Attempt cap | extractor, canonical-form check, plus `DOCS_STATING_THE_CAP` guard against deletion | Good design; the extractor's phrase list is narrow (finding C1) |
| Forbidden terms | `test_document_uses_no_forbidden_term` over all 18 repository Markdown files, `.agents/tasks/**` included | Pattern held as a regex, never a literal; samples built from fragments. The reserved feature is never spelled in the module |
| Removed models | sentence-scoped exemption | Matches the plan's "matched by the surrounding sentence". Each exemption word is used by a real passage (for example "without" at `IMPLEMENTATION_PLAN.md:310`, "becomes" at `SPECIFICATIONS.md:510`), so the list cannot be narrowed without false positives. Accepted as an inherent limit |

In-memory probes, run by this review without writing any file:
* `_stated_attempt_caps("A cap of 4 attempts per doc. Up to 4 attempts. The attempt limit is 4.")` returns `[]`, so a drifted cap in those phrasings passes (C1).
* `_partial_binding_claims("The Scout is limited to the list and search tools. … The Writer only has access to two tools.")` returns `[]` (C2).
* The proposed extra patterns in `FIXES.md` produce **zero** hits on all 18 repository documents, so they add detection without false positives today.

The additional "`AGENTS.md` is listed" tests (implementer's behaviour 11) are a sound deviation: they make the Green workflow edits test-driven and are recorded.

---

## 3. Code review findings

`tests/test_unit/test_docs_consistency.py` (783 lines):

* **Imports:** standard library (`json`, `os`, `re`, `pathlib`) then third-party (`pytest`); no local import; zero E402. ✅
* **Annotations:** every function and test is fully annotated with PEP 585/604 forms (`tuple[Path, ...]`, `list[tuple[str, bool]]`, `re.Pattern[str]`). ✅
* **Paths:** `pathlib.Path` throughout. `os.walk` and `os.path.normcase` are justified: `requires-python = ">=3.11"` rules out `Path.walk` (3.12), and case folding is a string operation for comparison only. ✅
* **Naming and structure:** constants grouped paths → contract pins → scanning rules; private helpers prefixed `_`; each helper has a docstring that states its rule and its exclusions. ✅
* **Dead code:** none found. `repo_root` on `_candidate_locations` exists only for the pure test and is used by it. ✅
* **Zero I/O beyond reading:** confirmed; no temporary files, no subprocess, no network. The existence checks on `../code-orchestration/` and `../mcp-server/` are reads the plan requires. ✅
* **Finding C1** (🟢 Minor), lines 202–209: `_CAP_STATEMENTS` misses "cap of N", "capped at N" and "up to / maximum of N attempts". See `FIXES.md`.
* **Finding C2** (🟢 Minor), lines 122–129: `PARTIAL_BINDING_PHRASES` misses "only has access to", "connected only to", "limited to the tools" and similar. See `FIXES.md`.

`AGENTS.md`:
* **Finding A1** (🟢 Minor), line 64: log events are said to be defined in `SPECIFICATIONS.md` §6 and §7; the catalogue is D-I, in §5. See `FIXES.md`.

`CLAUDE.md`: no finding.

**Ruff:** 0 in-scope findings, 0 pre-existing findings.

---

## 4. Anti-patterns and risks

* **Autonomy leak:** none. No rule, in `AGENTS.md` or in the edited workflow files, lets code choose the next tool.
* **Parity drift:** none. No constant is restated with a different value; models and efforts are cited by reference only.
* **Article text towards the Supervisor:** none.
* **Future risk, heuristic scans.** The P1, cap and removed-model checks are phrase-based. They lock today's wording and catch the drifts they were designed for, but a paraphrase can slip through. C1 and C2 narrow that gap; the rest is an accepted limit of text tests, and later iterations add code-level checks (Iteration 4's `MAX_ATTEMPTS_PER_DOC`, Iteration 6's tool-binding tests).
* **Future risk, the forbidden-term pattern** matches the plain English phrase of "agent" directly followed by "skill". A future document that uses that phrase innocently fails the suite. This is by design and the right default; noted so later reviewers expect it.
* **Informational, not a finding for this iteration:** the contents table of `SPECIFICATIONS.md` (line 28) lists "logs" under §7, but §7 has no logging subsection; the catalogue is D-I in §5. This is the likely source of A1. Changing `SPECIFICATIONS.md` is not needed to fix A1, and no contract depends on it.

---

## 5. Remediation directives

| ID | Severity | File and lines | Change | Required by |
| :--- | :---: | :--- | :--- | :--- |
| A1 | 🟢 Minor | `AGENTS.md:64` | Cite D-I for log events, not §6 and §7 | `SPECIFICATIONS.md` D-I; `IMPLEMENTATION_PLAN.md` Iteration 1 (docs match their sources) |
| C1 | 🟢 Minor | `tests/test_unit/test_docs_consistency.py:202-209`, `666-677` | Add two cap phrasings to `_CAP_STATEMENTS`, with synthetic cases | `IMPLEMENTATION_PLAN.md` Iteration 1 Red: "none states another cap" |
| C2 | 🟢 Minor | `tests/test_unit/test_docs_consistency.py:122-129`, `646-651` | Add tool-anchored restriction phrases to `PARTIAL_BINDING_PHRASES`, with synthetic cases | `IMPLEMENTATION_PLAN.md` Iteration 1 Red, P1: "no document says a sub-agent is given only some of them" |

Exact changes are in `.agents/tasks/iteration-01/FIXES.md`. No "Needs a decision" item is opened.

---

# Architect Review — Iteration 1, round 2 (re-review after fix round 1)

**Reviewer:** `architect` subagent, Stage 3 round 2.
**Scope audited:** `git status --short`, `git diff --stat` (tracked files), and direct reads of the untracked `AGENTS.md` and `tests/test_unit/test_docs_consistency.py` (now 886 lines), and of `FIXES.md`. The fix round touched only `AGENTS.md`, the docs test and `FIXES.md`.

**Commands run (no model, no network, no live test):**

| Command | Result |
| :--- | :--- |
| `uv run pytest -q` | 198 passed, 0 failed, 0 skipped (188 in round 1: 7 new cases, plus 3 forbidden-term cases for this folder's three record files) |
| `uvx ruff check src tests --no-cache` | All checks passed: **0 in-scope, 0 pre-existing** |
| `uv run pytest -m live --collect-only -q` | 0 collected, 198 deselected |
| `git diff --stat 2c8a7dc -- .agents/docs/DESIGN.md .agents/docs/SPECIFICATIONS.md .agents/templates/draft.md` | Empty |
| `git diff --stat` | Unchanged from round 1: the same seven workflow and plan files, 11 insertions and 5 deletions |

## 1. Overall verdict

**APPROVED.**

All three round-1 architect findings and all three QA findings are resolved in substance, each with a synthetic test that fails on the drift it targets. Nothing regressed: the benchmark-constant documents are byte-unchanged since Iteration 0, the tracked workflow edits are the ones approved in round 1, and ruff is clean. No new finding is opened.

## 2. Verification of the round-1 items

| ID | Where | Verified by | Result |
| :--- | :--- | :--- | :--- |
| A1 | `AGENTS.md:64` | Read. It now says "... guardrail name and exit code is defined in `SPECIFICATIONS.md` §6 and §7, and every log event in its D-I catalogue". This is consistent with Rule 6 (`AGENTS.md:90`, "The event catalogue is D-I") | ✅ |
| C1 | `test_docs_consistency.py:241-259`, `443-457`, `766-780` | `_CAP_STATEMENTS` gains `cap(?:ped)? (?:of\|at) N` and `(?:up to\|maximum of\|max(?:imum)?) N (?:Writer )?attempts`. Prose patterns take digits or whole-word number words one to ten, so "none" is not read as "one". `_stated_attempt_caps` keys each number by its text position, so a number that two phrasings read counts once. Synthetic cases at lines 773-775 cover digits, number words and a guard case. My probes on the real documents in memory: "capped at four attempts" appended to DESIGN.md gives `[3, 4]`, "a maximum of 5 Writer attempts" appended to SPECIFICATIONS.md gives `[…, 5]`, "Up To Six attempts" gives `[6]`. Every cap hit in the eleven documents is 3 | ✅ |
| C2 | `test_docs_consistency.py:125-138`, `744-751` | Six phrases are added (`only has access to`, `has access only to`, `connected only to`, `only connected to`, `limited to the tools`, `restricted to the tools`). The prompt-boundary sentence and the token-subset comment still give `[]`. Probes on "has access only to" (appended to DESIGN.md) and "restricted to the tools" are caught. No repository document triggers any phrase | ✅ |
| QA-m1 | `test_docs_consistency.py:139-175`, `726-729` | `DECISION_TABLE_ROWS` holds all ten D-C rows as full four-cell values, compared with list equality. A one-word mutation of the real table ("advisory only" to "advisory mostly") is detected | ✅ |
| QA-m2 | `test_docs_consistency.py:176-184`, `406-416`, `687-717` | `IMPLEMENTATION_DECISIONS` pins each bold statement. The pure helper `_decisions_without_their_statement` reads bold and plain labels, and is applied to SPECIFICATIONS.md §8.3 and IMPLEMENTATION_PLAN.md §2. Probes on the real sections: a drifted P2 in the spec gives `['P2']`, and a drifted P6 in the plan gives `['P6']` | ✅ |
| QA-m3 | `test_docs_consistency.py:100-107`, `858` | `REMOVED_MODELS` holds the 11 names. They match `SPECIFICATIONS.md:543` exactly (same set). Probes on `SaveResult` and `DocumentOutcome` in current-tense sentences are reported | ✅ |

The implementer's note on C1's expected value is consistent with this review's round-1 intent. `[2, 4, 5, 6]` was the intended result, one reading per stated number. The dedup by position is what makes it hold, and it is documented in the helper's docstring.

## 3. Pillar audit (delta)

| # | Pillar | Round 2 |
| :---: | :--- | :--- |
| 1 | An agent owns the flow | ✅ Unchanged. No rule or test moves control flow out of the Supervisor |
| 2 | Division of labour | ✅ Unchanged |
| 3 | Custom agent tools | Not touched by this iteration |
| 4 | Guardrails and attempt state | ✅ The cap is now guarded against more rewordings in all eleven documents, and the D-C table is pinned word for word |
| 5 | Benchmark parity | ✅ DESIGN.md, SPECIFICATIONS.md and the template are unchanged. The P1 negative check is broader. P1–P6 statements are pinned in both records |
| 6 | Substrate isolation and lifecycle | Not touched by this iteration |
| 7 | Rendering, telemetry and logging | ✅ A1 is fixed |
| 8 | Code quality | ✅ See §4 |

## 4. Code review of the fix-round changes

* **Imports:** unchanged, grouped standard library then `pytest`, with zero E402. ✅
* **Annotations:** the new constants and helpers are fully annotated (`dict[str, int]`, `dict[str, str]`, `-> int`, `-> list[str]`). ✅
* **Naming and docstrings:** `_cap_value`, `_PROSE_NUMBER`, `_NUMBER_WORDS` and `_decisions_without_their_statement` are private, named for what they do, and documented with their rule and exclusions. The comment at lines 120-124 now records why `limits it to`, `subset of` and `given only some` are left out. ✅
* **Dead code:** none. The superseded label-only P1–P6 check was replaced, not left alongside. ✅
* **Ruff:** 0 in-scope findings (blocking), 0 pre-existing (deferred).

## 5. Anti-patterns and risks

* **Autonomy leak, parity drift, article text towards the Supervisor:** none.
* **Informational, not a finding:** `\bcap(?:ped)? (?:of|at) N` (line 257) is not anchored on "attempts". A future sentence such as "a cap of two revisions" would therefore read as a cap of 2 and fail the suite. The failure is loud rather than silent, it sits on the safe side, and no document triggers it today. If that phrasing is ever wanted, the fix is to add a negative lookahead for "revisions", in the way lines 247-249 already exclude "up to N revisions".
* **Accepted limit, unchanged:** the P1, cap and removed-model scans remain phrase-based. Code-level checks arrive in Iterations 4 and 6.

## 6. Remediation directives

None. No `FIXES.md` item and no "Needs a decision" item is opened in round 2.
