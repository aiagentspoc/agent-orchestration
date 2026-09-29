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

## Q3 (Iteration 02): Should `.agents/templates/draft.md` be replaced with Approach 1's current template before Iteration 2 copies the template-engine tests?
**Background:** This repository's template matches Approach 1's initial template (`e0d634e`). Approach 1's current template (HEAD `3b123e4`, unchanged on disk) adds `* **Cost Basis:** {model_rates_used}` and an `#### Agent Tool Usage` section with `{stage_telemetry_markdown_table}`, and all 10 of its benchmark drafts carry them. Copied as they are, three tests in `test_template_engine.py` fail against this repository's template: `test_render_draft_substitutes_telemetry_placeholders`, `test_telemetry_table_is_a_top_level_block_not_a_list_continuation` and `test_telemetry_table_has_its_own_heading_and_cost_basis_stays_a_bullet`. `SPECIFICATIONS.md` §1, `AGENTS.md` Rules 4 and 5, and §6.8 (which keeps `stage_telemetry` and `model_rates_used`) all say the template is held constant with Approach 1.
**Recommendation:** A. A content-identical copy of Approach 1's current template makes "held constant" true. The three tests then pass unchanged, and Approach 2's drafts show the same tool-usage table and cost basis that Iteration 16's benchmark compares. `render_draft` already maps the two extra placeholders.
**Options:** A. Replace `.agents/templates/draft.md` with Approach 1's current template, content-identical, in Iteration 2, and record it · B. Keep the current template and drop or adapt the three tests; Approach 2's drafts then lack the Cost Basis line and the tool-usage table · C. Keep the current template for now, defer the three tests to Iteration 11 and decide there

**Answer (2026-09-29):** A, as recommended. Iteration 2 replaces `.agents/templates/draft.md` with a content-identical copy of Approach 1's current template (Cost Basis line and Agent Tool Usage table included). Recorded as P8 in `IMPLEMENTATION_PLAN.md` §2.

*Raised by the architect in the Iteration 2 pre-flight. Status: resolved.*

## Q4 (Iteration 02): May Iteration 2's prerequisite "the Approach 1 suite passes" count as met, when its only failures are 12 prompt-text tests in `test_agents.py` that Iteration 2 does not copy?
**Background:** Run read-only on its working tree, Approach 1 collects 324 tests, not the plan's 221, and 12 of them fail. All 12 are in `tests/test_unit/test_agents.py` and assert prompt phrases that the on-disk `src/agents.py` no longer contains. `agents.py` was edited on 2026-09-24 at 13:07, after those tests (2026-09-23) and before the benchmark drafts (13:16). All 106 tests in Iteration 2's copy set pass. Under P7 the on-disk prompts are the baseline, so Iteration 6 will copy prompts that Approach 1's own tests reject.
**Recommendation:** A. The prerequisite exists to prove the copied tests run in a matching environment, and the 106/106 result proves that. The prompts belong to Iteration 6, which keeps the on-disk prompts (P7) and does not copy the 12 stale assertions.
**Options:** A. Treat the prerequisite as met; in Iteration 6, copy the on-disk prompts and drop or adapt the 12 failing assertions, recording which ones · B. Treat it as met, but make Iteration 6 stop and ask again before copying any prompt · C. Block until you reconcile Approach 1's prompts and tests (outside this plan's scope)

**Answer (2026-09-29):** Yes (option A). The prerequisite counts as met for Iteration 2. Iteration 6 copies the on-disk prompts (P7) and drops or adapts the 12 stale prompt-text assertions of Approach 1's `test_agents.py`, recording which.

*Raised by the architect in the Iteration 2 pre-flight. Status: resolved.*

## Q5 (Iteration 07): When may the 9 missing type annotations in the verbatim copy of `src/mcp_client.py` be added, since Iteration 2's AC4 locks that file to Approach 1's text?
**Background:** Iteration 2's AC4 requires `src/mcp_client.py` to be identical to `../code-orchestration/src/mcp_client.py`, and it is. That copy has 9 ruff ANN findings: `__init__`, `start`, `stop`, `__enter__`, `__exit__` and its three arguments, and `_ensure_connected`. `AGENTS.md` Rule 7 and code-reviewer Gate 8 require complete annotations, and no later iteration is scheduled to edit this module, so the gap would last indefinitely. Both reviewers treat the gap as non-blocking.
**Recommendation:** A. Annotations change no behaviour and nothing a model sees. Adding them when Iteration 7 first wires the client into `tools.py` keeps Iteration 2's AC4 diff clean.
**Options:** A. Allow annotation-only edits to `src/mcp_client.py` in Iteration 7, recorded as the one permitted divergence from Approach 1 · B. Allow them now, as an Iteration 2 fix, with AC4 read as "differ only in import lines and type annotations" · C. Leave the file verbatim for the whole plan, as an accepted exception to Rule 7

**Answer (2026-09-29):** A, as recommended. Annotation-only edits to `src/mcp_client.py` are allowed in Iteration 7, recorded as the one permitted divergence from Approach 1. Recorded as P9 in `IMPLEMENTATION_PLAN.md` §2.

*Raised by QA in the Iteration 2 review (round 1); the architect concurs with A. Status: resolved.*

## Q6 (Iteration 02): May the stale "P1 to P6" and "template unchanged" wording be updated in `CLAUDE.md`, the three `.claude/agents/*.md` files and `IMPLEMENTATION_PLAN.md`, in the Iteration 2 commit?
**Background:** Iteration 2 updated `AGENTS.md`, both review skills and `SPECIFICATIONS.md` to "P1 to P8", and replaced the template under P8. Several files still carry the old wording:
* `CLAUDE.md:14`, `.claude/agents/architect.md:18`, `.claude/agents/implementation.md:16` and `.claude/agents/qa.md:18` still say P1 to P6. So the subagents' mandatory-reading lists omit P7 (the baseline) and P8 (the template);
* in the plan, the traceability row (`IMPLEMENTATION_PLAN.md:817`) still says P1 to P6;
* the §4 layout (`IMPLEMENTATION_PLAN.md:161`) still calls `draft.md` "already present; unchanged".

No test reads these lines, so the suite stays green. The implementer declined to edit `CLAUDE.md` and `.claude/` as harness configuration, and my own plan edits are limited to §3 and new P-decisions, so this needs your consent.
**Recommendation:** A. The changes are wording only, and they keep every subagent reading P7 and P8, which bind every later iteration.
**Options:** A. Approve all of it. A fix pass updates the four harness files to "P1 to P8"; the plan's traceability row gains `P7 | 2, 6, 16` and `P8 | 2`, and line 161 reads "draft.md (Approach 1's current template, P8)". All of it goes in the Iteration 2 commit · B. Update only the two plan lines, and leave the harness files as they are · C. Leave everything as is; the subagents read the plan's §2 in full anyway

**Answer (2026-09-29):** A, as recommended. The user approves updating the four harness files to "P1 to P9" (P9 was added the same day), the plan's traceability row, and line 161, in the Iteration 2 commit.

*Raised by QA (its Q6) and the architect (A1, A2) in the Iteration 2 review (round 1). Status: resolved.*

## Q7 (Iteration 03): Should `_ApiKeyRedactionFilter` also mask the API key in exception tracebacks and stack text, although the plan moves it verbatim from Approach 1?
**Background:** The filter rewrites only `record.getMessage()` (`src/logging_setup.py:134-140`, identical to Approach 1's `orchestrator.py:1246-1253`). Tracebacks are formatted afterwards, from `exc_info`, and are never checked. My probe used `configure_logging("INFO", d, api_key=KEY)`, then logged `RuntimeError(f"AuthenticationError: bad key {KEY}")` with `.exception(...)`. It printed `KEY IN FILE: True`, on the line `RuntimeError: AuthenticationError: bad key sk-live-0123456789abcdefSECRET`, and the same text goes to stderr. D-I and D22 say "the only suppression is masking the literal API key" and require full tracebacks for "Supervisor invocation failed", while Iteration 3's Green moves the filter from Approach 1 and the implementer kept the gap for parity. Logging is not among the benchmark constants of `SPECIFICATIONS.md` §1, but amending a verbatim-moved component is a plan deviation the sources do not settle.
**Recommendation:** A. Close the gap in Iteration 3, test-first. In the filter, when `record.exc_info` is set and `record.exc_text` is not yet cached, set `record.exc_text` to `logging.Formatter().formatException(record.exc_info)` with the key replaced. Apply the same replacement to `record.exc_text` and `record.stack_info` when they are present. The formatter reuses the cached `exc_text`, so the traceback stays verbatim apart from the key, and the fix meets D22's "full fidelity except the key" literally. The Red is a test like my probe, asserting the key is absent and the rest of the traceback, including `status=` and `request_id=` markers, is present in both the file and stderr. Doing it now, before Iteration 14 first passes a real key to `configure_logging`, is cheaper than retrofitting.
**Options:** A. Amend the filter now to cover `exc_text` and `stack_info`, and record the change as a deviation from Approach 1 in the walkthrough · B. Keep Approach 1's filter verbatim for parity, record the gap as a known limitation, and revisit in Iteration 14 when the CLI passes a key · C. Redact at the formatter instead: a `Formatter` subclass that replaces the key in the fully formatted output, covering message, traceback and stack alike, with the filter kept only for parity

**Answer (2026-09-29):** B. Keep Approach 1's filter verbatim. Reason given by the user: this is a proof of concept, not a production app, and sensitive data may be logged for audit. Recorded as P10 in `IMPLEMENTATION_PLAN.md` §2; no later iteration widens the redaction.

*Raised by QA in the Iteration 3 review (round 1). Status: resolved.*
