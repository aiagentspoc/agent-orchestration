# Open questions

Questions raised by the `/implement` workflow under `IMPLEMENTATION_PLAN.md` §1.4. Each is answered by the user; the next `/implement` records the answer here.

## Q1 (Iteration 02): Should the Approach 1 and `mcp-server` working trees be pinned by a commit before Iteration 2 copies Approach 1's modules and prompts from them?

**Background:** `../code-orchestration/` is at HEAD `3b123e4`, but its working tree carries uncommitted edits to `src/agents.py`, including the Writer system prompt and `QA_LEGAL_TOOL_NAMES`, and to `src/orchestrator.py` and several tests. The file times show that the benchmark run the plan cites (2026-09-24: 3 drafts, 223,970 tokens, $0.7803) was made from that working tree: `agents.py` was modified at 13:07, and the drafts were written at 13:16. `../mcp-server/` likewise has uncommitted changes to `server.py` and to every fixture file. Iterations 2 and 6 copy the reused modules and check prompt parity against whatever is on disk at the time. If either sibling tree changes again, the benchmark constants (prompts, tool names, substrate) move silently, and there is no commit to diff against. Modifying either repository is outside the plan's scope (`IMPLEMENTATION_PLAN.md` §1.4 item 4).

**Recommendation:** A. The user commits both working trees as they stand now. The Iteration 2 walkthrough then records the two SHAs as the benchmark baseline, and every later "copy from Approach 1" and parity check refers to those SHAs. That keeps the baseline equal to the tree that produced the 2026-09-24 run, and makes any drift visible through `git diff`.

**Options:** A. The user commits both working trees. The agent records the SHAs in the Iteration 2 walkthrough and treats them as the baseline. · B. Nothing is committed. Iteration 2's walkthrough records SHA-256 hashes of every Approach 1 file it copies or parses, and of `../mcp-server/server.py` and `fixtures/*.json`. Later iterations re-check the hashes and stop if they differ. · C. Treat HEAD `3b123e4` as the baseline, reading files with `git show 3b123e4:<path>`. This departs from the tree that produced the 2026-09-24 benchmark run, so the baseline numbers would no longer correspond to the prompts being copied.

**Answer (2026-09-28):** The current local state of Approach 1 (`../code-orchestration/`) and `../mcp-server/` is correct. Do not commit or change anything in either directory. The on-disk working trees, including their uncommitted edits, are the baseline for every copy from Approach 1, every parity check and the substrate. Recorded as P7 in `IMPLEMENTATION_PLAN.md` §2.

*Raised by the architect in the Iteration 0 review (round 1). Status: resolved.*

## Q2 (Iteration 01): May Iteration 1 be completed with the minor finding QA-m4 deferred, since it is still open after the two review rounds the workflow allows?
**Background:** Iteration 1 is green (198 tests, ruff clean, all three acceptance criteria met). Both round-2 reviewers pass it: the architect APPROVED with no findings, and QA PASSED. But QA raised one new minor, non-blocking item, QA-m4. The P1 tool-binding phrase list in `tests/test_unit/test_docs_consistency.py` still misses a sentence such as "The Scout is limited to the list and search tools." `/implement` treats any finding still open after round 2 as stop condition 2, and forbids a third round.
**Recommendation:** A. QA-m4 only strengthens a heuristic docs check; no document today uses the wording it would catch, and QA has written the exact fix and its Red case in `.agents/tasks/iteration-01/FIXES.md`. Deferring it to Iteration 4, which edits the docs test anyway to read `MAX_ATTEMPTS_PER_DOC`, costs nothing and unblocks the run.
**Options:** A. Complete Iteration 1 now; carry QA-m4 into Iteration 4's brief and apply it there · B. Allow one extra fix round for QA-m4 only, then complete Iteration 1 · C. Drop QA-m4 and complete Iteration 1

**Answer (2026-09-28):** A, as recommended. Iteration 1 is completed now; QA-m4 is carried into Iteration 4's brief and applied there.

*Raised by the orchestrator at the end of the Iteration 1 review (round 2). Status: resolved.*
