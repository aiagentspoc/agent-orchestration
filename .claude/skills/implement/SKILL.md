---
name: implement
description: Execute iterations of .agents/docs/IMPLEMENTATION_PLAN.md for HSE Easy Approach 2 (Research Analyst) through the 4-stage TDD workflow (architect pre-flight → implementation → parallel architect/qa review with a bounded fix loop → walkthrough, tracker update and commit). Runs without human approval gates and stops only on the plan's stop conditions. Use when the user invokes /implement, /implement <n>, /implement all, or asks to implement an iteration of the plan.
---

# `/implement`: iteration workflow for Approach 2

You are the **orchestrating agent**. Your jobs:
* resolve the iteration;
* sequence the four stages;
* hold the fix-loop counter;
* write `WALKTHROUGH.md`;
* update the tracker in `IMPLEMENTATION_PLAN.md` §3;
* commit;
* stop and ask when the plan says to.

You delegate the architecture review, the implementation and the QA verification to subagents.

There is **no human approval gate.** Each iteration's section in `IMPLEMENTATION_PLAN.md` is its approved plan, and acceptance criteria that can be checked take the place of sign-off. You stop only for a stop condition in `IMPLEMENTATION_PLAN.md` §1.4.

---

## Zero fallback: read this first

The `architect`, `implementation` and `qa` roles **must** run as real subagents, spawned with the `Agent` tool using `subagent_type: architect | implementation | qa`.

**Never do a subagent's work yourself.** Auditing the architecture in your own context, writing production code or tests, or checking the suite in place of `qa` are all prohibited fallbacks, however much faster they would be. So is reading `.claude/agents/<role>.md` and "acting as" that role.

If a subagent cannot be spawned, that is stop condition 5: record the question (see *Stopping* below) and end the turn.

**What you do yourself:**
* resolve the iteration;
* dispatch the subagents;
* hold `round`;
* write `WALKTHROUGH.md`;
* update §3 of the plan;
* manage `QUESTIONS.md`;
* run `git`.

---

## Project files the subagents read

| File | Read by |
| :--- | :--- |
| `.agents/docs/IMPLEMENTATION_PLAN.md` | You, `architect`, `implementation`, `qa` |
| `.agents/docs/SPECIFICATIONS.md` | You (skim), `architect`, `implementation`, `qa` |
| `.agents/docs/DESIGN.md` | `architect`, `implementation`, `qa` |
| `.agents/templates/draft.md` | `architect`, `implementation`, `qa` |
| `.agents/skills/architect-review/SKILL.md` | `architect` |
| `.agents/skills/code-reviewer/SKILL.md` | `architect`, `implementation`, `qa` |
| `../code-orchestration/`, read-only | `architect`, `implementation`, `qa` |

Each subagent's definition lists its files as mandatory reading. **In every subagent prompt, name these paths again,** so that a subagent never has to search for them.

The two review skills live in `.agents/skills/`, and Claude Code does not discover them as skills, so subagents open them with the Read tool. Every subagent's `tools:` list includes Read.

`.claude/settings.json` makes this possible without permission prompts, which would stall an unattended run:
* `permissions.additionalDirectories` grants read access to `../code-orchestration/` and `../mcp-server/`;
* `enabledMcpjsonServers` enables the two MCP servers in `.mcp.json`.

If a subagent reports that it cannot read one of these files, stop (condition 5) rather than letting it work without the file.

---

## Pre-flight

1. Read `.agents/docs/IMPLEMENTATION_PLAN.md`: §1 to §3, and the target iteration's section. Skim `.agents/docs/SPECIFICATIONS.md` for the decisions and contracts that section cites, and `.agents/docs/DESIGN.md` for the concept. Each subagent reads its own sources in full; you need enough context to judge their reports.
2. Read `.agents/tasks/QUESTIONS.md` if it exists.
   * If a question for the target iteration has **no answer yet**, stop. Repeat the question to the user and end the turn.
   * If the user has now answered it, write the answer under the question as `**Answer (YYYY-MM-DD):** …`. Mark the question resolved, and pass the answer to the subagents as a binding decision.
   * If the answer settles a design point, add it to `IMPLEMENTATION_PLAN.md` §2 as the next P-decision (P7, P8 and so on). This is the only edit you make to the plan outside §3.
   * Tell the implementer to apply the answer in `SPECIFICATIONS.md` and to record it in its §8.3.
3. **Git.**
   * For Iteration 0, create the branch `approach-2/implementation` from the current `main`, if it does not exist yet. The planning files (`.agents/docs/`, `.agents/skills/`, `.claude/`, `.gitignore`, `.mcp.json`) may still be uncommitted; the Iteration 0 commit includes them.
   * For later iterations, confirm that the branch is checked out and that the working tree is clean apart from files this workflow wrote.
   * If the tree has changes you did not make, stop (condition 4) rather than commit someone else's work.

## Resolving the iteration

| Invocation | Target |
| :--- | :--- |
| `/implement` | The first iteration in §3 that is `⏳ Pending`, `🔄 In progress` or `⛔ Blocked` with its question answered. No confirmation is needed |
| `/implement <n>` | Iteration n. Every earlier iteration must be `✅ Complete`; if one is not, tell the user and run the first incomplete one instead. If n is already complete, ask whether to run it again, which is the one confirmation this skill ever asks for |
| `/implement all` | Every remaining iteration, one after another, until all are complete or a stop condition is hit |

The artifact directory is `.agents/tasks/iteration-NN/`, with two digits (`iteration-00` to `iteration-16`). Set the iteration's row in §3 to `🔄 In progress`.

---

## Stage 1: architect pre-flight

Spawn **one** `architect` subagent with `run_in_background: false`. Its prompt must name:
* the iteration number and title;
* the path of its section in `IMPLEMENTATION_PLAN.md`;
* the earlier iterations it should verify and build on;
* any answer from `QUESTIONS.md` that binds this iteration;
* that this is the Stage 1 pre-flight review, that it writes **no files**, and that it must end with a `PREFLIGHT:` line.

When it returns:
* **`PREFLIGHT: CLEAR`** → Stage 2. Keep its report; it is the implementer's brief.
* **`PREFLIGHT: STOP`** → stop, using the question it gave (see *Stopping*).
* **No `PREFLIGHT:` line, or a report too thin to act on** → spawn the architect once more, naming the gaps. If the second report is still unclear, stop (condition 1).

## Stage 2: implementation

Spawn **one** `implementation` subagent with `run_in_background: false`. Its prompt must name:
* the iteration and the path of its section;
* the artifact directory;
* the architect's pre-flight report, pasted in full;
* any binding answers;
* the reminder to work **one behaviour at a time**, Red → Green → Refactor, never writing all the tests first;
* the reminder that no live model call is allowed (P4).

When it returns:
* **`STOP:`** → stop with its question.
* **A red suite, or unmet acceptance criteria, with no `STOP:`** → spawn it **once** more with the failing output and the unmet criteria. If it is still red, stop (condition 2).
* **Green, and it reports every acceptance criterion met** → Stage 3.

## Stage 3: parallel review and bounded fix loop

Initialise `round = 1`. You hold the counter; never delegate it, and never let a review reset it.

**Send both reviewers in a single message,** as two `Agent` calls in one block, both with `run_in_background: false`: one `architect`, one `qa`. Give each:
* the iteration;
* the artifact directory;
* its output file: `ARCHITECT_REVIEW.md` or `QA_REVIEW.md`;
* the implementer's report, pasted in full;
* the instruction to append its findings to the shared `FIXES.md`, under its own heading.

On a re-review, tell both reviewers the round number and what was raised before.

When both return:

| Outcome | Next step |
| :--- | :--- |
| Both pass, and `FIXES.md` has no open item | Stage 4 |
| A `## ❓ Needs a decision` item exists | Stop (condition 1 or 2), using that question |
| Findings raised, and `round <= 2` | Spawn **one** `implementation` subagent in fix mode, pointed at `FIXES.md`. When it returns, increment `round` and send both reviewers again |
| Findings still open after round 2 | Stop (condition 2). List the unresolved items in the question. Do not mark the iteration complete, and do not add a third round |

Between rounds, tell the user in one line what happened: which reviewer raised what, and that a fix pass is starting.

## Stage 4: walkthrough, tracker and commit

### 4a. Write `WALKTHROUGH.md` yourself

Write `.agents/tasks/iteration-NN/WALKTHROUGH.md` **from the diff and the plan only**. Do not build it from the subagents' reports or from your memory of the run: those are claims about the work, and the walkthrough documents the work itself.

1. Run `git diff` and `git status --short`, and read every new file directly.
2. Read the iteration's section of the plan. The plan gives the structure and the *why*, and the diff gives the *what*. Where they disagree, the diff is the truth: record the deviation.
3. Write these sections:

   | Section | Contents |
   | :--- | :--- |
   | `## 1. Overview` | What the iteration delivered |
   | `## 2. Files changed` | Each file, and what it is responsible for |
   | `## 3. TDD record` | Behaviour by behaviour: what the Red test asserted and why it failed, what Green added, what Refactor cleaned up |
   | `## 4. Test results` | Real counts from a fresh `uv run pytest -q`, which you run yourself: the tests added by this iteration, and the full suite. Add the ruff result |
   | `## 5. Acceptance criteria` | Each criterion, marked ✅ with its evidence |
   | `## 6. Decisions and deviations` | The §1.5 decisions made, and any deviation from the plan with its reason |
   | `## 7. Review` | Review rounds used, and each finding with how it was resolved |

   Explain the code; never paste raw patch hunks. Leave out any claim you cannot back up from the diff.

### 4b. Update the tracker

In `IMPLEMENTATION_PLAN.md` §3, set the row to `✅ Complete (YYYY-MM-DD, <n> tests)`. Change nothing else in the plan, apart from P-decisions added under pre-flight step 2.

### 4c. Commit (P5)

Stage everything the iteration changed. Leave out `.env` and anything `.gitignore` excludes. Commit on `approach-2/implementation`:
* Message: `Iteration NN: <title>`, followed by a blank line, a one-line summary, and the session's attribution lines.
* **Never push.** Never use `--no-verify`.

### 4d. Report, then continue or finish

Tell the user, in a few lines:
* what was built;
* the real test numbers;
* the review rounds used;
* the commit hash;
* the next iteration.

For `/implement all`, go straight on to the next iteration's pre-flight. After Iteration 16, report that the live end-to-end tests are built and are **waiting for the user to run them** with `uv run pytest -m live`.

---

## Stopping

When any stage hits a condition in `IMPLEMENTATION_PLAN.md` §1.4:

1. **Record the question.** Append it to `.agents/tasks/QUESTIONS.md` in the plan's format:

   ```markdown
   ## Q<n> (Iteration NN): <one-line question ending in "?">
   **Background:** <what was found, in two or three sentences>
   **Recommendation:** <the option you would choose, and why>
   **Options:** A. … · B. … · C. …
   ```

2. **Mark the iteration blocked.** Set its row in §3 to `⛔ Blocked (Q<n>)`.
3. **Commit nothing** for an unfinished iteration. Leave the work in the tree, so it continues from there.
4. **End the turn** by showing the user the question. When the user answers, the next `/implement` picks it up in pre-flight step 2.

---

## Notes

- **Artifacts per iteration:**
  * `ARCHITECT_REVIEW.md` and `QA_REVIEW.md`, from Stage 3;
  * `FIXES.md`, while the fix loop is open, and kept afterwards as the record;
  * `WALKTHROUGH.md`, from Stage 4.

  `QUESTIONS.md` is shared across iterations.
- **Write scopes:**
  * Only `implementation` touches the code, the tests and the iteration's listed deliverables.
  * The reviewers write only inside `.agents/tasks/iteration-NN/`, and the architect writes nothing in Stage 1.
  * You write `WALKTHROUGH.md`, the §3 tracker, `QUESTIONS.md` and commits.
- **No live runs (P4).** No stage runs `pytest -m live` or the CLI against real endpoints. Only the user starts live runs.
- **Out of bounds:** `../code-orchestration/` and `../mcp-server/` are read-only, and the git remote is never touched.
