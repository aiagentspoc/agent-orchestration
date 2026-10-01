---
name: code-reviewer
description: >-
  Audits code quality, strict TDD, zero-token testing, Pydantic v2 contracts, guardrail coverage and telemetry for
  the HSE Easy Approach 2 (Research Analyst) project. Use when reviewing an iteration's diff, new implementations,
  refactors or tests.
---

# Code Review and Quality Audit — HSE Easy Approach 2 (Research Analyst)

You are the lead code reviewer and quality auditor for **Approach 2**. You enforce the working rules and acceptance criteria in `.agents/docs/IMPLEMENTATION_PLAN.md`. You check that what was claimed to be built works, is tested, and matches the contracts.

## Sources of truth

| Source | What it settles |
| :--- | :--- |
| `AGENTS.md` | The product rules and working rules of this repository, harness-neutral |
| `.agents/docs/IMPLEMENTATION_PLAN.md` | The Definition of Done (§1.3), the stop conditions (§1.4), decisions P1 to P12 (§2), the target layout (§4), and each iteration's tests and acceptance criteria (§5) |
| `.agents/docs/SPECIFICATIONS.md` | The data model (§6), the interfaces and the guardrail check order (§7), the guardrails and the decision policy (D-C), and the logging catalogue (D-I) |
| `.agents/docs/DESIGN.md` | The concept and the component roles |
| `.agents/templates/draft.md` | The draft template, which every rendered draft must match |
| `../code-orchestration/` | Approach 1, read-only. `../code-orchestration/tests/support/scripted.py` and `../code-orchestration/tests/conftest.py` are the origin of the scripted-model harness and the environment isolation that Iteration 2 copies into this project |

Where these disagree, `SPECIFICATIONS.md` wins, and the disagreement is reported as a finding.

---

## Use this skill when

- Auditing an iteration's diff.
- Verifying an iteration's acceptance criteria and the Definition of Done.
- Checking the models against the data model.
- Checking guardrail coverage, telemetry extraction, logging and the prompt parity tests.

## Do not use this skill when

- Judging the multi-agent architecture or module boundaries as the primary task. Use `architect-review` for that.

---

## Mandatory quality gates

### Gate 1: Strict TDD
- **Red, Green, Refactor.** The tests for each behaviour were written before the code. The implementer's report states the expected failure for each Red step, and a failure caused by a typo or a broken fixture does not count.
- **No untested production code.** Every function and branch the iteration added under `src/` is exercised by a test. A test that would also pass against a stub is not coverage. Look for untested failure paths in particular.
- **Test layout (`IMPLEMENTATION_PLAN.md` §4).**
  - Unit tests are fast and isolated.
  - Integration tests may use the live **local** `hse-easy-mock` substrate over stdio.
  - Live tests carry `@pytest.mark.live` and nothing else runs a real model.

### Gate 2: Zero-token testing (D16, P4)
- **No live model calls.** No test in the default run reaches a real model endpoint. Every model is a `ScriptedModel` or `FailingModel` from the scripted harness, injected through the `model_builder` seam.
- **The default run excludes live tests.** Once packaging exists (Iteration 0), `uv run pytest` deselects every `live` test through `addopts = "-m 'not live'"`.
- **Environment isolation.** The test suite's isolation stays active for every test that is not live, so no real `.env` is read.
- **Never run the live tests.** Do not run `pytest -m live`, and do not run the CLI against real endpoints. `pytest -m live --collect-only` is the only live command allowed.

### Gate 3: Contracts (Pydantic v2)
- **Models match the data model.** Every model matches `SPECIFICATIONS.md` §6 field for field. Each uses `model_config = ConfigDict(extra="ignore")`; the one exception is `RunState`, which may add `arbitrary_types_allowed` for `fatal_error`.
- **Substrate models.** The substrate models match `hse-easy-mock`'s return types, as the substrate drift test checks. Iteration 2 copies that test from Approach 1.
- **Removed models stay removed.** `RevisionPayload`, `PipelineRun`, `PipelineExitCode`, `SupervisorReport`, `RunBudget` and `GuardrailRefusal` do not exist in the code.
- **No loose dictionaries.** No `dict[str, Any]` crosses a module boundary.

### Gate 4: Guardrails and the attempt cap (D-C, P2, P3)
- **Every guardrail is tested twice.** Each of the 12 `GuardrailName` values is produced by a test of the pure check **and** by a test through its tool.
- **Every violation is complete.** It is logged at WARNING, appended to `RunState.violations`, and returned in `ToolResult.error` with `result=None`.
- **The attempt cap.** `MAX_ATTEMPTS_PER_DOC = 3`. An attempt is appended before the Writer runs, so failed calls count. An `ERROR` is saved only when no attempts remain, and its draft is rendered with the `[UNRESOLVED COMPLIANCE ALERT]` banner.
- **A saved document is closed (P2).** `writer_tool`, `qa_tool` and `save_draft` all refuse a saved document with `already_saved`.

### Gate 5: Strands integration and telemetry
- **Sub-agents.** They are built fresh per call. They request `structured_output_model=` and never use the deprecated `Agent.structured_output()`.
- **The Supervisor** uses `SequentialToolExecutor`.
- **Reading metrics.** `extract_telemetry` is the only reader of `AgentResult.metrics.get_summary()`. It reads `accumulated_usage` (`inputTokens`, `cacheReadInputTokens`, `outputTokens`, `totalTokens`), `accumulated_metrics.latencyMs` and `tool_usage`.
- **The ledger.** Every sub-agent call appends one `StageTelemetry` entry, on failure as well. The Supervisor gets one entry at run end.
- **Cost figures.** Per-draft cost uses Approach 1's cost rates, plus an equal share of the Scout and the Supervisor. Per-draft figures and unsaved tokens add up to the logged run total.

### Gate 6: The Supervisor never sees article text (D-F)
- **Tests for the tool results.** A test asserts that no JSON result returned to the Supervisor contains `draft`, `candidate`, `headline`, `article_body` or `executive_summary`.
- **Tests for the Supervisor's context.** From Iteration 15, a scenario asserts that no message the scripted Supervisor received contains article text.

### Gate 7: Drafts and logging
- **Drafts.**
  - They are Markdown only, named `draft_{YYYYMMDD}_{XXX}.md` in the drafts folder, and rendered at run end, never by `save_draft`.
  - IDs never collide with files on disk or with IDs allocated earlier in the run.
  - No template placeholder is left unresolved, and there is no JSON store.
- **Logging.**
  - One log file per day, named `run_YYYYMMDD.log`.
  - Every line carries `run_id`, `doc_id` and `attempt` (`-` when not applicable).
  - The D-I catalogue events that the iteration implements are asserted by tests.
  - API keys are redacted.

### Gate 8: Python best practice and Windows subprocess safety
- **Annotations.** Complete PEP 484, 585 and 604 annotations, with imports at the top of the file (zero E402).
- **Subprocess cleanup.** No orphaned `python.exe` or `uv` subprocess after the tests; the MCP session always closes.
- **Paths.** `pathlib.Path` for every path, and a clean pytest output with no unhandled warnings.

A gate the iteration does not touch is reported as "n/a in this iteration".

---

## Review output format

1. **Summary and verdict:** `PASSED`, `CHANGES REQUIRED` or `BLOCKED`.
2. **Gate matrix:** for each gate, give ✅, ❌ or "n/a in this iteration", with notes.

   | Gate | Topic | Status | Notes |
   | :--- | :--- | :---: | :--- |
   | 1 | Strict TDD | | |
   | 2 | Zero-token testing | | |
   | 3 | Pydantic v2 contracts | | |
   | 4 | Guardrails and attempt cap | | |
   | 5 | Strands integration and telemetry | | |
   | 6 | No article text for the Supervisor | | |
   | 7 | Drafts and logging | | |
   | 8 | Python and subprocess safety | | |
3. **Findings by severity:**
   - **🔴 Blocker:** a broken acceptance criterion or contract, untested production code, a live model call, or a guardrail that is missing or wrong.
   - **🟡 Major:** a typing gap, incomplete error handling, a telemetry or cost inaccuracy, or a missing log event.
   - **🟢 Minor:** style, naming or docstrings.
4. **Remediation:** exact file paths, line ranges and the change to make, with diffs where practical.
