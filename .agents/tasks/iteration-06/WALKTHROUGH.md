# Iteration 6 — Sub-agent runners and prompts: walkthrough

**Date:** 2026-09-29 · **Branch:** `approach-2/implementation` · **Plan section:** `IMPLEMENTATION_PLAN.md` §5, Iteration 6

## 1. Overview

Iteration 6 brings Approach 1's three sub-agents into `src/agents.py`: the Scout, the Writer and QA-Legal, each built by a factory and run by a runner that takes one input model.
* **The benchmark constants carry over unchanged.** The Scout and QA-Legal system prompts are byte-identical to Approach 1's. The Writer prompt differs only by three declared phrases that name its new input. The model IDs, the efforts and the tool-name tuples are Approach 1's.
* **The baseline** is Approach 1's working tree at `1734096`, under P7. That commit rewrote the Writer and QA-Legal prompts.
* **A parity test** parses Approach 1's file with `ast` and locks all of this.
* **Binding.** Every builder attaches all five substrate tools by default (P1), and accepts an optional `hooks` sequence for Iteration 12.

Answer Q4 said stale Approach 1 prompt assertions could be dropped. None were: at `1734096`, Approach 1's own `test_agents.py` passes 78 of 78, so nothing was stale.

## 2. Files changed

| File | Status | Responsibility |
| :--- | :--- | :--- |
| `src/agents.py` | New, 769 lines | See below |
| `tests/test_unit/test_agents.py` | New, 88 tests | Approach 1's agent tests, triaged (see §3), plus new tests for the runners' inputs, DM5 and DM7, the hooks, the harness markers and the public surface |
| `tests/test_unit/test_prompt_parity.py` | New, 16 tests | `ast`-parses `../code-orchestration/src/agents.py`, never importing it; skipped with a reason if it is absent |
| `tests/support/scripted.py` | Edited | `TEST_RATES` keyed by the three role model IDs again (F1). `VALID_SCOPE_ARGS` drops `time_window` and gains `"context": {"today": SCOPE_DATE_TO}`. `WRITER_PROMPT_SECTION` and `QA_LEGAL_PROMPT_SECTION` are now `"Write a publication-ready HSE article"` and `"Audit the article draft"`, two disjoint Approach 1 sentences |
| `tests/test_unit/test_costs.py` | Edited | Back to Approach 1's text, minus the ScopeParser model ID (F1) |
| `tests/test_unit/test_telemetry.py` | Edited | Uses the role model IDs again (F1); docstring updated |
| `tests/test_unit/test_module_structure.py` | Edited | Adds `"src.agents"` |
| `tests/test_unit/test_schemas.py` | Edited | A bug fix to the `_defined_models` helper (see §6) |

**What `src/agents.py` contains:**
* **Copied from Approach 1 (`1734096`), unchanged:**
  * the constants `SCOUT_MODEL_ID = "gpt-5-mini"`, `WRITER_MODEL_ID = QA_LEGAL_MODEL_ID = "gpt-5.4"`;
  * the efforts `None`, `"high"` and `"medium"`;
  * `SCOUT_TOOL_NAMES`, `WRITER_TOOL_NAMES` and `QA_LEGAL_TOOL_NAMES`, kept as declared intent under P1;
  * `SCOUT_SYSTEM_PROMPT` and `QA_LEGAL_SYSTEM_PROMPT`;
  * the functions `extract_telemetry`, `_resolve_tools` and `_run_worker`. The parity test compares their ASTs with the docstrings stripped; the docstrings were reworded.
* **`WRITER_SYSTEM_PROMPT`:** Approach 1's text, with three substitutions (the list is kept in the parity test):
  1. "Given one triaged `ScoutCandidate`, fetch" becomes "Given an `AttemptRecord` carrying one triaged `ScoutCandidate`, fetch".
  2. "If a revision payload is also supplied, revise" becomes "If the record also carries a `draft` and its `qa_report`, revise".
  3. "The revision payload contains your previous draft" becomes "The `AttemptRecord` contains your previous draft".
* **Removed from Approach 1's module:** everything belonging to the ScopeParser (D-J): its constants, prompt, builder, runner and exports.
* **Builders:** `build_scout_agent`, `build_writer_agent` and `build_qa_legal_agent` share a private `_build_agent`. It calls `Agent(..., tools=_resolve_tools(client, tool_names), callback_handler=None, hooks=list(hooks))`. `tool_names` defaults to `None`, which means all five tools; `hooks` is keyword-only and defaults to `()`.
* **Runners:**
  * `run_scout(agent, scope)`;
  * `run_writer(agent, record)`;
  * `run_qa_legal(agent, record)`.

  Each keeps Approach 1's keyword-only `model_id` and `reasoning_effort` overrides and returns a `WorkerOutput`.
  * `today` is no longer a parameter: the date comes from `scope.context` or `record.context`.
  * No runner mutates its input, calls `set_draft` or `set_qa_report`, or inspects a QA status.
  * `run_writer` branches only on `record.draft is None`, which chooses between the first-draft turn and the revision turn.
* **Input guards:**
  * `run_qa_legal` raises `ValueError` when the record has no draft.
  * `run_writer` raises `ValueError` when the record has a draft but no QA report.
  * Both fire before any model call, and their messages carry only the `doc_id` and the attempt.
* **`__all__`** has 19 names: 3 model IDs, 3 efforts, 3 tool tuples, 3 prompts, `extract_telemetry`, 3 builders and 3 runners.

## 3. TDD record

| # | Behaviour | Red |
| :---: | :--- | :--- |
| 1 | The module, model IDs, efforts and tool tuples; F1 reverted in the tests | `ImportError: cannot import name 'agents' from 'src'` |
| 2 | Scout and QA-Legal prompts byte-identical, copied from Approach 1's source lines | `ImportError` |
| 3 | The Writer prompt: Approach 1's source plus the three substitutions | `ImportError` / `AttributeError` |
| 4 | `extract_telemetry`, and the harness scope fixture | `ImportError`; `VALID_SCOPE_ARGS` failed with `context Field required` |
| 5 | The three builders: all five tools; a recording `HookProvider` sees each invocation | `ImportError` |
| 6 | `run_scout`: Approach 1's turn; the JSON in the turn equals `scope.model_dump(mode="json")` | `ImportError` |
| 7 | `run_writer`, first draft: date from the record; `writer_view()` under `## AttemptRecord`; names `candidate.update.doc_id` | `ImportError` |
| 8 | `run_writer`, revision: the revision sentence appears when a draft exists; a draft without a report raises | The instruction was absent, and `DID NOT RAISE ValueError` |
| 9 | `run_qa_legal`: `qa_view()` in the turn; no draft raises. DM7 at attempts 2 and 3: `"attempt":N` present, with no candidate, rationale, score or cap. DM5: no cap in the Writer turn | `ImportError` |
| 10 | Harness markers disjoint, each matching only its own runner | `assert [] == [...]` (the old marker matched nothing) |
| 11 | The public surface | Set mismatch: the runners were missing from `__all__` |

**Tests that passed on their first run** are characterisation tests of copied code, not Red steps:
* the copied prompt-text tests after the first import;
* the loop-state guard;
* the three adapted revision tests;
* the F2 fresh-agent test;
* the fix-round Q-1 test.

**Triage of Approach 1's `test_agents.py` (Q-2's corrected split).** Of its 78 test functions:
* **16 dropped:** the ScopeParser tests (D-J).
* **34 kept verbatim.**
* **28 adapted:** 25 keep their names, and 3 are renamed:
  * `test_writer_accepts_revision_payload` becomes `test_writer_accepts_a_drafted_and_audited_record`;
  * the two `…_requires_the_current_date_as_a_keyword` tests become `…_takes_the_current_date_from_the_record`.
* **What the adaptations change:**
  * scopes carry `context`, not `time_window`;
  * the Writer and QA-Legal runners take an `AttemptRecord`;
  * the revision tests drop the old `"action"` key, and read `qa_report` where the removed payload model had `qa_audit`;
  * JSON assertions use the compact form.
* **F2.** The two telemetry tests owed from Iteration 2 were restored into `test_agents.py`: the fresh-agent test, adapted to a record, and the zero-latency test, verbatim.
* **22 new test functions**, including Q-1's.

**Fix round 1:**
* **Q-1.** New test: `test_builder_without_a_client_builds_a_tool_free_agent`, over the three builders. It covers the `client is None` branch of `_resolve_tools`, the only statement in `src/agents.py` that no test ran.
  * **Red, on a scratch copy:** deleting that branch survived the suite before the test was added. After, it failed the 3 new cases.
  * QA re-traced coverage with a `sys.settrace` plugin: 146 of 146 executable lines are now run.
* **A-1.** The `_defined_models` docstring was corrected; see §6.

## 4. Test results

A fresh run at the checkpoint, after this walkthrough was written:

| Command | Result |
| :--- | :--- |
| `uv run pytest -q` | **742 passed**, 0 failed |
| Tests added by this iteration | 88 in `test_agents.py` and 16 in `test_prompt_parity.py`, plus the reserved-feature check on this iteration's four new records |
| `uvx ruff check src tests --no-cache` | `All checks passed!` |
| `uv run pytest -m live --collect-only` (reviewers) | 0 collected |

## 5. Acceptance criteria

| # | Criterion | Result | Evidence |
| :---: | :--- | :---: | :--- |
| 1 | The prompt parity tests pass | ✅ | 16/16. With `../code-orchestration/` absent, all 16 skip with a reason. QA showed that a one-character change, a trailing space or one CRLF in any prompt fails them |
| 2 | Scout and QA-Legal prompts diff empty against Approach 1 | ✅ | Empty, once line endings are normalised; checked independently by the implementer, the architect and QA. The Writer differs on exactly Approach 1's lines 234, 235 and 334 |
| 3 | Every runner test uses `ScriptedModel`, and `sent_text` shows the expected user turn | ✅ | There is no `build_model` in any test. `sent_text` reads only the messages, never the system prompt |

Definition of Done:
* **DoD-1** ✅, **DoD-2** ✅, **DoD-5** ✅ and **DoD-6** ✅ (this file).
* **DoD-3** ✅: `ScriptedModel` with `StubSubstrateClient` or `offline_client`, and no network.
* **DoD-4** ✅, after fix round 1 (Q-1).

## 6. Decisions and deviations

**Decisions (§1.5):**
* The builders share a private `_build_agent`.
* The substitution list lives in the parity test. That test also compares the nine constants as literals, and the three reused functions as ASTs.
* The harness fixture was fixed in place: `VALID_SCOPE_ARGS` gains `context`, rather than those tests being switched to a `ScoutReport` payload.
* The wording of the two `ValueError` messages is the implementer's own.
* **F2 is restored here, not in Iteration 7,** because both tests need only `src.agents`.

**Deviations from the plan:**
* **`_as_json` now dumps in JSON mode:** `json.dumps(model.model_dump(mode="json"), ensure_ascii=False, indent=2)`. Approach 1's version raises `TypeError` on the `date` in `PipelineScope.context`. The Scout turn's formatting is otherwise unchanged.
* **A bug fix to an earlier iteration's test (A-1).**
  * **The symptom:** `test_schemas.py`'s `_defined_models()` counted 29 classes instead of 27, but only when it ran after the agents tests.
  * **The cause:** pydantic registers parametrised generics written at module level, such as the return annotation `-> WorkerOutput[ScoutReport]` in `src.agents`, in the `src.schemas` namespace when `src.agents` is imported. The implementer's first account blamed the `_run_worker` call; the architect showed that is inexact.
  * **The fix:** the helper skips names that are not identifiers. The lock that the defined set equals the 27 specified models is unchanged, and a real extra model still fails it.
* **User-turn rewordings (Q-3).** Each renames the new input only; the sentences are otherwise Approach 1's.
  * **Scout:** the text is unchanged. The `## PipelineScope` JSON now carries `context: {today}` and no longer has the two time-window fields.
  * **Writer, both turns:**
    * "regulatory update below" becomes "regulatory update in the AttemptRecord below";
    * "on its update.doc_id" becomes "on its candidate.update.doc_id";
    * the `## ScoutCandidate` section with indented JSON becomes `## AttemptRecord`, carrying `writer_view()` as compact JSON;
    * the `Current date:` line is unchanged, and is now read from `record.context.today`.
  * **Writer, revision:**
    * the second section, which carried the removed payload model, is gone;
    * the revision sentence now comes before the single `## AttemptRecord` section;
    * "Rewrite the previous draft below so that every issue in its QA audit is resolved." becomes "Rewrite the previous draft in the record below so that every issue in its QA report is resolved.";
    * "Preserve everything the audit did not object to." is unchanged.
  * **QA-Legal:**
    * "Audit the article draft below" becomes "Audit the article draft in the AttemptRecord below";
    * the `## ArticleDraft` section becomes `## AttemptRecord`, carrying `qa_view()` (`doc_id`, `context`, `attempt`, `draft`) as compact JSON;
    * `get_document_by_id(...)` interpolates the same `source_doc_id`, now read from `record.draft`.
* **The revision test asserts Approach 1's own sentences,** as reworded above, not the plan's paraphrase ("resolve every issue …"). That phrase appears only in the Writer's system prompt.
* **Writer and QA-Legal JSON is compact,** where Approach 1 used `indent=2`, because §7.2 makes `writer_view()` and `qa_view()` the content, and Iteration 4 locked them. On a revision, the Writer sees the attempt number of the record being revised (§6.2, D-E).
* **pyright, which is not a DoD gate:**
  * `src/agents.py` has 1 error, inherited: Approach 1's file gives the identical error on the same line.
  * `test_agents.py` has errors from passing `StubSubstrateClient` where `HSEMockMCPClient` is expected, which is Approach 1's pattern.

**For the user: a documentation drift in `DESIGN.md` §4.** Its "Used by" column no longer matches the prompts at `1734096`:
* the Writer prompt requires `verify_legal_citation`, but the column lists it for QA-Legal only;
* the QA-Legal prompt uses `search_regulatory_docs`, but the column lists it for the Scout only.

No code or binding is affected: all five tools are attached (P1), and the prompts are verbatim. It is offered as a doc correction.

**Process note.** During round 1, QA ran one read-only pyright check with its working directory inside `../code-orchestration/`, against its brief. It wrote nothing: that folder's `git status` shows only its long-standing untracked drafts and logs.

**Forward notes:**
* **Iteration 7:**
  * Wrappers never pass `tool_names`, and they pass `hooks` by keyword.
  * Restore `scripted_model_builder`, keyed so the Supervisor, the Writer and QA-Legal (all `gpt-5.4`) can be scripted independently (F5).
  * Do not reuse `VALID_SCOPE_ARGS` or `SCOPE_ARGS` as the scripted Supervisor's `scout_tool` arguments: they now carry `context`, which the Supervisor never supplies.
  * Reading telemetry from `agent.event_loop_metrics` after a failed call needs a path through the unchanged `extract_telemetry`.
  * Apply P9 (F6).
* **Iterations 8 and 9:** on a revision, pass the latest drafted record.
* **Iteration 13:** add the Supervisor's model ID to `test_costs.py`'s worker IDs.
* **Iteration 16:** the benchmark report should note the compact JSON in the Writer and QA-Legal turns.

## 7. Review

**Two rounds were used.**

| Round | Reviewer | Verdict | Findings | Resolution |
| :---: | :--- | :--- | :--- | :--- |
| 1 | Architect | APPROVED | **A-1 (minor):** the `_defined_models` docstring gave the wrong cause. Parity, P1, statelessness, DM5 and DM7 all hold. Ruff: 0 in scope, 0 pre-existing | Fixed in fix round 1 |
| 1 | QA | CHANGES REQUIRED | **Q-1 (blocker, DoD-4):** the `client is None` branch was untested. **Q-2:** the triage split was misreported. **Q-3:** the user-turn rewordings were unrecorded | Q-1 was fixed with a new test. Q-2 and Q-3 are recorded in §3 and §6 of this walkthrough |
| 2 | Architect | APPROVED | None. Parity re-checked with its own AST script | — |
| 2 | QA | PASSED | None. Coverage is 146/146 lines, and the mutant is killed | — |
