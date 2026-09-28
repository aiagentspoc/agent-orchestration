# Iteration 1 — Project documents and working rules: walkthrough

**Date:** 2026-09-28 · **Branch:** `approach-2/implementation` · **Plan section:** `IMPLEMENTATION_PLAN.md` §5, Iteration 1

## 1. Overview

Iteration 1 writes the repository's working rules and puts every source of truth under test.
* **`AGENTS.md`** is the harness-neutral guide: product rules 1–6, working rules 7–10, the layout and placement rule, the MCP servers and the commands.
* **`CLAUDE.md`** is a thin Claude Code pointer to it.
* **`tests/test_unit/test_docs_consistency.py`** makes the documents agree with each other and with `SPECIFICATIONS.md`. It pins the specification's models, guardrails, exit codes, decisions, decision table, event catalogue and Supervisor tool descriptions. It checks every cited path, the settings file, the tool binding (P1), the attempt cap, the reserved feature, and the removed models.

Four workflow files were edited so that the subagents and review skills read `AGENTS.md`. Two of them also carried wording that the new checks flagged. `DESIGN.md`, `SPECIFICATIONS.md` and the draft template are unchanged.

## 2. Files changed

| File | Status | Responsibility |
| :--- | :--- | :--- |
| `AGENTS.md` | New | Harness-neutral rules. **§1** covers the sources of truth, the layout tree, the placement rule (`.agents/` for project truth, `.claude/` for Claude Code mechanics), and a table linking the six workflow files. **§2** holds product rules 1–6: the contracts are in `SPECIFICATIONS.md`; the Supervisor supervises agents, not drafts, and code only refuses; the cap `MAX_ATTEMPTS_PER_DOC = 3` and the 12 guardrails are enforced in code; the benchmark constants, including P1, cited by reference to `SPECIFICATIONS.md` §1; Markdown drafts rendered at run end; telemetry and logging follow Approach 1. **§3** holds working rules 7–10: strict TDD; stop-and-ask per §1.4 instead of approval gates; review subagents with zero fallback; no live model calls (P4). **§4** covers the MCP servers and the five substrate tools, and **§5** the commands |
| `CLAUDE.md` | New | Thin pointer to `AGENTS.md`. It links the three core documents, the six workflow files, `settings.json` and `.mcp.json`, and summarises the principle, the layout, the `/implement` workflow, the commands and the conventions |
| `tests/test_unit/test_docs_consistency.py` | New | The docs-consistency contract (DoD-5 from now on). Every scanning rule is a pure helper over text, tested on synthetic strings, then applied to the real files |
| `.agents/skills/architect-review/SKILL.md` | Edited | An `AGENTS.md` row heads "Sources of truth" |
| `.agents/skills/code-reviewer/SKILL.md` | Edited | An `AGENTS.md` row in "Sources of truth". The harness files are now cited as `../code-orchestration/tests/support/scripted.py` and `../code-orchestration/tests/conftest.py`, which exist; the bare `tests/…` paths do not exist here until Iteration 2. Gate 4 now reads `MAX_ATTEMPTS_PER_DOC = 3`, not `== 3` |
| `.claude/agents/architect.md` | Edited | `AGENTS.md` is mandatory-reading item 8 |
| `.claude/agents/implementation.md` | Edited | `AGENTS.md` is mandatory-reading item 6 |
| `.claude/agents/qa.md` | Edited | `AGENTS.md` is item 6, and "What actually landed" moves to item 7. The guardrail bullet now reads "The attempt cap is `MAX_ATTEMPTS_PER_DOC = 3`, and each attempt is appended before the Writer runs". The old wording said the *cap* was appended |
| `.claude/skills/implement/SKILL.md` | Edited | An `AGENTS.md` row in "Project files the subagents read" |
| `.agents/tasks/QUESTIONS.md` | Edited | Q2 was raised and answered; the answer to Q1 was recorded (see §6) |
| `.agents/docs/IMPLEMENTATION_PLAN.md` | Edited | Only the §3 tracker row for Iteration 1 |

## 3. TDD record

Each behaviour went through Red, then Green. Where a rule needed a helper, the Red was a `NameError` on that helper, followed by real assertion failures once the helper existed.

| # | Behaviour | Red | Green |
| :---: | :--- | :--- | :--- |
| 1 | The eleven documents exist | 2 of 11 failed: `AGENTS.md not found`, `CLAUDE.md not found` | Minimal `AGENTS.md` and `CLAUDE.md` |
| 2 | Both guides link to the 3 core documents and the 6 workflow files | `NameError: _markdown_link_targets`, then 18 real link assertions | Full `AGENTS.md` and `CLAUDE.md` |
| 3 | Every path cited in a guide or workflow file exists | `NameError` on the four path helpers, then one real failure: `code-reviewer/SKILL.md` cited `tests/support/scripted.py` and `tests/conftest.py` | Reworded that line to the `../code-orchestration/…` paths |
| 4 | `.claude/settings.json` grants both sibling folders and enables both servers | `NameError: _settings_directory` | Helper only; the settings file was already correct. The entries are absolute, so paths are compared resolved |
| 5 | Nothing cites the scratchpad design plan | `NameError: _SCRATCHPAD` | Helper only; the files were clean |
| 6a | `SPECIFICATIONS.md` inventories: the 27 §6 models and 4 settings classes, the 7 `[New]` models, the 12 guardrails in order, the 7 exit codes 0–6, and P1–P6 | `NameError` on `_python_classes`, `_literal_values` and `_spec_section`. The D-A..D-J heading test needs no helper and passed at once | Helpers and pinned constants. `_literal_values` splits on the `Literal[` opener, so a `# [New]` comment cannot cut it short |
| 6b | The 10 D-C decision rows, the 23 D-I events (as level and event pairs) and the four §7.1 tool descriptions | `NameError: _table_rows` | Helper and pinned constants |
| 7 | P1: `DESIGN.md` §4 says every sub-agent is connected to all five tools, and no document names a partial tool set | `NameError` on `_between` and `_partial_binding_claims` | Helpers; the files were clean |
| 8 | The attempt cap | `NameError` on the cap helpers, then two real failures: `qa.md` ("The attempt cap is 3") and `code-reviewer/SKILL.md` (`== 3`) | Both reworded to the canonical form |
| 9 | The reserved feature is named in no `.md` in the repository, `.agents/tasks/**` included | `NameError: _repository_documents` at collection | A case-insensitive pattern that covers every spelling but does not match the `.agents/skills/` folders. It is held as a regex, and its self-test samples are built from fragments, so the term is never spelled in the repository |
| 10 | Removed models appear only in removal or history sentences | `NameError: _current_mentions_of_removed_models` | Sentence-level exemption by keyword (removed, replaces, renamed, becomes, …). One synthetic expectation was wrong, and the test value was corrected, not the logic |
| 11 | The review skills and subagents list `AGENTS.md` | 5 assertion failures, e.g. `architect-review/SKILL.md omits AGENTS.md` | The workflow-file edits |

**Refactor:**
* A `tmp_path` self-test was replaced by a pure `_candidate_locations` test, so the module does no I/O beyond reading the repository.
* The constants are grouped as paths, then contract pins, then scanning rules.
* One E501 was fixed.

**Fix round 1.** Each strengthening started with a failing synthetic case:
* **A1:** `AGENTS.md` Rule 1 now points log events to the D-I catalogue. It had pointed to §6 and §7.
* **C1:** new cap phrasings: "cap of / capped at N", "up to / maximum of N attempts", and the number words one to ten. The Red was `assert [2] == [2, 4, 5, 6]`. `_stated_attempt_caps` now counts a number read by two phrasings once, by its position in the text.
* **C2:** six more partial-binding phrases. The Red was `assert [] == ['only has access to']`.
* **QA-m1:** `DECISION_TABLE_ROWS` pins all four cells of every D-C row word for word. The Red was the tightened comparison failing on row 0.
* **QA-m2:** `IMPLEMENTATION_DECISIONS` pins the bold statement of P1–P6, and `_decisions_without_their_statement` checks it in both `SPECIFICATIONS.md` §8.3 and `IMPLEMENTATION_PLAN.md` §2. The Red was a drifted P3 that the label-only rule missed.
* **QA-m3:** `REMOVED_MODELS` grows to the 11 names that `SPECIFICATIONS.md` §6 lists as removed. The Red was that "`WriterResult`" was not caught.

## 4. Test results

A fresh run at the checkpoint, after this walkthrough was written:

| Command | Result |
| :--- | :--- |
| `uv run pytest -q` | **199 passed**, 0 failed |
| `uv run pytest tests/test_unit/test_docs_consistency.py` | **183 passed** |
| Tests added by this iteration | 183, all in `test_docs_consistency.py` |
| Full suite | 199: 16 from Iteration 0 and 183 new |
| `uvx ruff check src tests --no-cache` | `All checks passed!` |

The reserved-feature check runs once per `.md` file in the repository, so each new record under `.agents/tasks/` adds one test. This walkthrough is one of them, which is why the count is 199 and not the 198 the fix round reported.

## 5. Acceptance criteria

| # | Criterion | Result | Evidence |
| :---: | :--- | :---: | :--- |
| 1 | `uv run pytest tests/test_unit/test_docs_consistency.py` passes | ✅ | 183 passed |
| 2 | `DESIGN.md` is unchanged since the Iteration 0 commit | ✅ | `git diff 2c8a7dc -- .agents/docs/DESIGN.md` is empty, and the same diff for `SPECIFICATIONS.md` and `draft.md` is empty too |
| 3 | The Mermaid block in `SPECIFICATIONS.md` §4 renders | ✅ | The implementer rendered the 61-line block, and QA rendered it again independently. `npx -y @mermaid-js/mermaid-cli` exited 0 both times, and the full flowchart appears in the PNG. Both runs worked outside the repository; the specification is unchanged since then |

Definition of Done:
* **DoD-1** ✅, **DoD-2** ✅, **DoD-5** ✅ and **DoD-6** ✅ (this file).
* **DoD-3** ✅: the tests are text-only.
* **DoD-4** does not apply: there is no new `src/` code.

## 6. Decisions and deviations

**Decisions (§1.5), as the test module records them:**
* **What counts as a path.** A token with no whitespace that contains `/` or `\`, or ends in a known file suffix. Slash commands, URLs, placeholders (`<`, `>`, `{`, `}`, `*`, `YYYY`) and the branch name `approach-2/implementation` are not paths. Fenced code blocks are not scanned.
* **How paths resolve.** Bare names resolve against the repository root, `.agents/docs/`, the citing file's folder and `../code-orchestration/`. Relative paths in backticks resolve from the repository root, and links from the citing file's folder.
* **"Paths the workflow creates"** means `.agents/tasks/iteration-(NN|dd)/…`, `.agents/tasks/QUESTIONS.md`, and the bare artefact names `ARCHITECT_REVIEW.md`, `QA_REVIEW.md`, `FIXES.md`, `WALKTHROUGH.md` and `QUESTIONS.md`.
* **Missing sibling checkout.** If `../code-orchestration/` is absent, the path check fails rather than skips.
* **The attempt cap.** `_ATTEMPT_CAP = 3` is a local literal, and Iteration 4 replaces it with `src.schemas.MAX_ATTEMPTS_PER_DOC`. Only `MAX_ATTEMPTS_PER_DOC = 3` and "3 Writer attempts" count as canonical. `DOCS_STATING_THE_CAP` makes sure the guides, the core documents, the review skills and `qa.md` keep stating the cap.
* **Scratchpad scope.** `IMPLEMENTATION_PLAN.md` is exempt from the scratchpad check, because it cites the `.gitignore` rule and the check itself.
* **Where `AGENTS.md` was added.** It is appended to the subagents' reading lists rather than inserted first.

**Deviations from the plan:**
* **An added behaviour.** Behaviour 11, the tests that the review skills and subagents list `AGENTS.md`, is not in the plan's Red list. It was added so that the plan's Green edits to the workflow files are driven by a test.
* **Two workflow files were reworded beyond adding `AGENTS.md`,** because the plan's own checks flagged them:
  * `code-reviewer/SKILL.md`: the harness paths and the `==` in the cap;
  * `qa.md`: the cap sentence.

**Answers recorded this iteration (`QUESTIONS.md`):**
* **Q1 (binds Iteration 2).** The current local working trees of `../code-orchestration/` and `../mcp-server/` are correct, including their uncommitted edits, and neither is committed or changed.
  * This becomes **P7**, which Iteration 2's pre-flight adds to `IMPLEMENTATION_PLAN.md` §2.
  * It is not added now: the docs test pins exactly P1–P6 in both records, so the Iteration 2 implementer must add P7 to `SPECIFICATIONS.md` §8.3 and to `IMPLEMENTATION_DECISIONS` in the same change.
* **Q2.** Option A: Iteration 1 is completed with **QA-m4** deferred to Iteration 4.

## 7. Review

**Two rounds were used.**

| Round | Reviewer | Verdict | Findings | Resolution |
| :---: | :--- | :--- | :--- | :--- |
| 1 | Architect | APPROVED WITH RESERVATIONS | **A1:** `AGENTS.md` pointed log events to §6 and §7. **C1:** some cap phrasings were missed. **C2:** some partial-binding phrasings were missed. All minor. Ruff: 0 in scope, 0 pre-existing | All three fixed in fix round 1 |
| 1 | QA | PASSED | **QA-m1:** pin the D-C rows word for word. **QA-m2:** pin the P1–P6 statements. **QA-m3:** list all 11 removed models. All minor. 29 in-memory mutations, 24 caught | All three fixed in fix round 1 |
| 2 | Architect | APPROVED | None. Informational: the "cap of N" pattern is not tied to "attempts", which fails safe | — |
| 2 | QA | PASSED | **QA-m4 (minor):** the partial-binding check still misses "The Scout is limited to the list and search tools." | Still open after round 2, which is stop condition 2, so it was raised as **Q2**. The user chose A: deferred to Iteration 4, with the fix and its Red case recorded in `FIXES.md` |
