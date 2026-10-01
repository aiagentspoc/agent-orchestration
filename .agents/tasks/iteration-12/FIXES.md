
## Architect — round 1

Verdict: **APPROVED**. No blocking items. Every item below is **optional** and does not block the iteration. Ruff found 0 in-scope findings and 0 pre-existing findings.

### 🏛️ Architecture & System Boundaries

- **(Optional) `.agents/docs/SPECIFICATIONS.md:403` (D-D).** The sentence "Transport death surfaces when a fresh sub-agent's tools are resolved, or during its call" overstates the behaviour. §8.4's verified known limit shows that a death during a sub-agent's MCP call is returned to that sub-agent as an error tool result. It becomes fatal only at the next sub-agent build. To fix it, append "(during a call it surfaces at the next build; §8.4, Known limit)" to the sentence. This changes wording only, and no contract.
- **(Optional) `tests/test_unit/test_module_structure.py`.** Add a test asserting that `src.hooks` does not import `src.tools`, for example by parsing `src/hooks.py` with `ast` and checking that no `ImportFrom` names `tools`. The test pins the one-way `tools → hooks` dependency that Iteration 13's `src/supervisor.py` will rely on.

### 🧹 Code Quality & Conventions

- **(Optional) `src/hooks.py:34`.** `AgentRole` repeats the inline literal of `StageTelemetry.stage` (`src/schemas.py:327`). The fix is one shared alias in `src/schemas.py`, used by both. Make the change only if no existing schema or docs test pins the inline form; otherwise leave it as it is.

### ❓ Needs a decision

None.

## QA — round 1

Verdict: **PASSED**. No blocker or major item. One minor item and two optional notes follow. Tests: 1105 passed, 0 failed, 0 errors, no warnings. Ruff: "All checks passed!".

### 🧪 Quality Assurance & Test Verification

- **(Minor) The `tool=` field of "Fatal abort triggered (D-D)" is not pinned by any test.** D-I requires this field to name "the tool that recorded it". In a scratch copy I replaced `event.tool_use["name"]` in `src/hooks.py:157` (`FatalStopHook._after_tool_call`) with the literal `"writer_tool"`. All 288 tests in the hooks, SDK contract and `test_tools_*` files still passed:

  ```text
  M23 fatal hook tool name wrong: SURVIVED | 288 passed in 5.33s | []
  ```

  The cause is that every test asserting this line uses `writer_tool` as the tool that completes first.

  **Fix (test only).** Make one test assert a different tool name. Either of these works:
  - In `tests/test_unit/test_hooks.py::test_the_fatal_abort_is_logged_once_at_error_with_its_cause_the_tool_and_the_exit_code`, parametrize the first event's tool name over `["writer_tool", "scout_tool"]` and expect `tool=<that name>`.
  - In `tests/test_unit/test_sdk_contract.py::test_the_production_fatal_stop_hook_passes_every_spike_assertion`, capture `src.hooks` at ERROR and assert `tool=fatal_tool`.

  No production change is needed.

- **(Optional, docs) A same-turn tool that the fatal stop skips produces no tool-call log line.** `SequentialToolExecutor` answers the skipped tool with "Tool execution cancelled" before `_stream_with_trace` (`strands/tools/executors/sequential.py:51-58`), so neither `BeforeToolCallEvent` nor `AfterToolCallEvent` fires for it. As a result, "Tool call started / completed" is not logged for that tool. This is acceptable, but one sentence under "Logging hooks (D-I)" in §8.4 would save the reader of a run log from wondering why the line is missing.

- **(Optional, forward note for Iteration 13) The same-turn stop depends on `SequentialToolExecutor`.** In a scratch copy I removed `tool_executor=SequentialToolExecutor()` from the spike harness. Three same-turn tests then failed: `test_candidate_1_…[same-turn]`, `test_the_production_fatal_stop_hook_…[same-turn]` and `test_candidate_1_answers_a_same_turn_tool_use_…`. Iteration 13's `build_supervisor_agent` must therefore use `SequentialToolExecutor`, as D-H and the implementer's forward notes already say. Its test should be written to fail without it.

### ❓ Needs a decision

None.

## Implementation — fix round 1

- **QA F1 (minor): resolved, test only.** `tests/test_unit/test_hooks.py::test_the_fatal_abort_is_logged_once_at_error_with_its_cause_the_tool_and_the_exit_code` is now parametrized over `(recording_tool, later_tool)` = `("writer_tool", "qa_tool")` and `("scout_tool", "writer_tool")`, and expects `tool=<recording_tool>`. Mutation proof: with `event.tool_use["name"]` at `src/hooks.py:157` temporarily replaced by `"writer_tool"`, the `[scout_tool-writer_tool]` case failed (1 failed, 1 passed). The mutation was reverted and the line is back to `event.tool_use["name"]`. No production change.
- **Architect 1 (optional): resolved, wording only.** D-D in `SPECIFICATIONS.md` (~:403) now reads: "Transport death surfaces when a fresh sub-agent's tools are resolved (during a call it surfaces at the next build; §8.4, Known limit)." No contract changed.
- **Architect 2 (optional): resolved.** Added `tests/test_unit/test_module_structure.py::test_hooks_does_not_import_tools`, which parses `src/hooks.py` with `ast` and resolves relative imports against `src`. Red check: each of four temporary mutants made it fail, and each was reverted: `from . import tools`, `from .tools import build_tools`, `from src.tools import build_tools` and `import src.tools`.
- **Architect 3 (optional): left as is.** `SPECIFICATIONS.md` §6 (~:755) gives the data model with `stage: Literal["supervisor", "scout", "writer", "qa_legal"]` written inline. Moving that field to a shared alias in `src/schemas.py` would make the code drift from the spec's listing, or would mean editing the §6 data model. The second is a data-model change, not a code-quality fix, so it is outside a fix round. `AgentRole`'s comment already names `StageTelemetry.stage` as its twin.
- **QA O1 (optional): resolved, wording only.** §8.4, "Logging hooks (D-I)", has a new bullet, **Skipped tools.** It says that a same-turn tool the fatal stop skips gets no "Tool call started" or "Tool call completed" line, because `SequentialToolExecutor` answers it with "Tool execution cancelled" before any tool hook fires.
- **QA O2: skipped as instructed.** It is a forward note for Iteration 13.

Close-out: `uv run pytest -q` gave 1110 passed, 0 failed. `uvx ruff check src tests` gave "All checks passed!".

## Architect — round 2

Verdict: **APPROVED**. I checked every round 1 item on disk. Nothing new is opened. Ruff found 0 in-scope findings and 0 pre-existing debt.

### 🏛️ Architecture & System Boundaries

- **Architect 1: verified closed.** D-D at `.agents/docs/SPECIFICATIONS.md:403` now agrees with §8.4's Known limit. No other document under `.agents/docs/` still says "or during its call".
- **Architect 2: verified closed.** `tests/test_unit/test_module_structure.py:55-70` walks the whole tree, including imports inside functions. It resolves `from . import tools` to `src.tools`, and the test passes on the current `src/hooks.py`.
- **QA O1: verified accurate.** The §8.4 "Skipped tools" bullet (`SPECIFICATIONS.md:1060`) matches the SDK. In `strands/tools/executors/sequential.py:50-59`, the cancelled branch `continue`s before `_stream_with_trace`, which is where the tool hooks fire.

### 🧹 Code Quality & Conventions

- **QA F1: verified closed.** The fatal-abort test (`tests/test_unit/test_hooks.py:388-405`) is now parametrized, and its `scout_tool` case pins `tool=` to the recording tool. `src/hooks.py:157` is unchanged.
- **Architect 3: declined, and I accept that.** The item was optional. The `AgentRole` comment at `src/hooks.py:33` names its twin. A shared alias would need a §6 listing edit, which is not fix-round scope.

### ❓ Needs a decision

None.

## QA — round 2

Verdict: **PASSED**. No new item. Tests: 1110 passed, 0 failed, 0 errors, no warnings. Ruff: "All checks passed!".

### 🧪 Quality Assurance & Test Verification

- **QA F1: verified closed.** On a scratch copy, I replaced only `src/hooks.py:157` with `"writer_tool"` (M23). The round 1 file set now gives `1 failed, 288 passed`, and the failing test is `test_the_fatal_abort_is_logged_once_at_error_with_its_cause_the_tool_and_the_exit_code[scout_tool-writer_tool]`. In round 1 the mutant survived with `288 passed`.
- **Architect 2: independently verified.** `test_hooks_does_not_import_tools` fails against each of five appended imports: the implementer's four, plus `from src import tools`.
- **Architect 1 and QA O1:** the wording is verified against §8.4 and the SDK.
- **Hygiene:** the scratch copy was deleted, and no process from today's runs is left.

### ❓ Needs a decision

None.
