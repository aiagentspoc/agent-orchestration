# Open questions

Questions raised by the `/implement` workflow under `IMPLEMENTATION_PLAN.md` §1.4. Each is answered by the user; the next `/implement` records the answer here.

## Q1 (Iteration 02): Should the Approach 1 and `mcp-server` working trees be pinned by a commit before Iteration 2 copies Approach 1's modules and prompts from them?

**Background:** `../code-orchestration/` is at HEAD `3b123e4`, but its working tree carries uncommitted edits to `src/agents.py`, including the Writer system prompt and `QA_LEGAL_TOOL_NAMES`, and to `src/orchestrator.py` and several tests. The file times show that the benchmark run the plan cites (2026-09-24: 3 drafts, 223,970 tokens, $0.7803) was made from that working tree: `agents.py` was modified at 13:07, and the drafts were written at 13:16. `../mcp-server/` likewise has uncommitted changes to `server.py` and to every fixture file. Iterations 2 and 6 copy the reused modules and check prompt parity against whatever is on disk at the time. If either sibling tree changes again, the benchmark constants (prompts, tool names, substrate) move silently, and there is no commit to diff against. Modifying either repository is outside the plan's scope (`IMPLEMENTATION_PLAN.md` §1.4 item 4).

**Recommendation:** A. The user commits both working trees as they stand now. The Iteration 2 walkthrough then records the two SHAs as the benchmark baseline, and every later "copy from Approach 1" and parity check refers to those SHAs. That keeps the baseline equal to the tree that produced the 2026-09-24 run, and makes any drift visible through `git diff`.

**Options:** A. The user commits both working trees. The agent records the SHAs in the Iteration 2 walkthrough and treats them as the baseline. · B. Nothing is committed. Iteration 2's walkthrough records SHA-256 hashes of every Approach 1 file it copies or parses, and of `../mcp-server/server.py` and `fixtures/*.json`. Later iterations re-check the hashes and stop if they differ. · C. Treat HEAD `3b123e4` as the baseline, reading files with `git show 3b123e4:<path>`. This departs from the tree that produced the 2026-09-24 benchmark run, so the baseline numbers would no longer correspond to the prompts being copied.

*Raised by the architect in the Iteration 0 review (round 1). Status: open.*
