# Iteration 14 — Architect review (Stage 3, round 1)

**Scope audited:** the uncommitted diff on `approach-2/implementation` over HEAD `35b4e92`:
* new files: `src/app.py`, `src/cli.py`, `tests/test_integration/test_app.py`, `tests/test_unit/test_app.py`, `tests/test_unit/test_cli.py` and `tests/test_unit/test_isolation.py`;
* modified: `src/tools.py`, `tests/conftest.py`, `tests/support/scripted.py`, `tests/test_unit/test_supervisor.py`, `tests/test_unit/test_docs_consistency.py`, `tests/test_unit/test_module_structure.py`, `.agents/docs/SPECIFICATIONS.md`, `AGENTS.md` and both `.agents/skills/*/SKILL.md` files.

**Criteria:** `.agents/skills/architect-review/SKILL.md` (the eight pillars) and `.agents/skills/code-reviewer/SKILL.md` (gates and severities), against `IMPLEMENTATION_PLAN.md` Iteration 14 with P6, P12 and P13, and against `SPECIFICATIONS.md` §4, D-B, D-D/D-D.1, D-F, D-H, D-I, §6.9, §6.10, §7.5, §7.6 and §8.3.

**Verification run by the architect:**
* `uv run pytest -q`: **1408 passed**, 0 failed, in 44.8 s.
* `uvx ruff check src tests --no-cache`: **All checks passed**, so 0 in-scope findings and 0 pre-existing debt.
* `uvx pyright src/app.py src/cli.py`: one error, at `src/cli.py:99`, the known pydantic-settings stub gap on `CredentialManager()`. That line is Approach 1's verbatim. `src/app.py` is clean. Pyright is not part of the DoD.
* A probe against the local substrate, killing only its own descendant processes. A killed `hse-easy-mock` subprocess surfaces as `MCPConnectionError` at the next `list_all_tools()`, and `HSEMockMCPClient.stop()` then returns cleanly. See N1.

---

## 1. Overall verdict

**APPROVED WITH RESERVATIONS.** The architecture is right:
* the Supervisor is invoked exactly once;
* code only maps outcomes after it returns;
* there is one `with` session, and the run end sits outside it;
* `finalise_run` runs once, on every path where a `RunState` exists;
* P6 and P13 are implemented exactly as decided.

The reservations:
* **One required minor fix:** unreachable, untested fallback branches in `_log_run_completed`, which make the DoD-4 claim inaccurate.
* **One item for the user,** non-blocking: N1, a close-time SDK `RuntimeError` that would bypass rendering.

---

## 2. Pillar audit

### Pillar 1. An agent owns the flow: ✅
* `run_supervisor` is called exactly once (`src/app.py` l.257–259), inside `_supervise`. It sits in no loop and is not retried, and no code re-prompts the Supervisor.
* No code calls a tool, inspects `stop_reason` or the summary text, or branches on a QA status or a tool result.
* After the Supervisor returns, code only reads what the run left behind:
  * `state.fatal_error`, `state.scope`, `state.documents`;
  * the `raised` flag;
  * `RunFinalisation.persistence_failed`.

  It maps these through the pure `_exit_code` (l.367–405).
* A fatal stop is never rerouted. `FatalStopHook(state)` is registered on the Supervisor only (l.255), and `build_tools` gets no `hooks=` (l.242–247).

### Pillar 2. Division of labour, D-F: ✅
* Only `prompt` reaches the Supervisor, through `run_supervisor(agent, prompt, today=…)`. No context, candidate or draft goes into the user turn.
* `test_the_supervisor_logs_each_turn_once_and_receives_only_the_prompt` (`tests/test_integration/test_app.py` l.952–962) asserts a single first message, `Current date: 2026-09-22\n\n<prompt>`.
* The composition root's own `list_all_tools()` (l.187) only counts tools for "MCP session opened". Nothing is handed to the Supervisor, so Q10 = B (no direct substrate access) holds.

### Pillar 3. Custom agent tools: not touched by this iteration
`build_tools` is reused unchanged. The two renames in `src/tools.py` (`_failure_record` → `failure_record`, `_failed_call_telemetry` → `failed_call_telemetry`, both added to `__all__`) change no behaviour: the diff consists only of the call sites and the two `def` lines.

### Pillar 4. Guardrails and attempt state: not touched by this iteration
`--max-drafts` flows from `config.max_drafts` into three places: `RunContext.max_drafts` (l.291), `build_supervisor_agent(max_drafts=…)` (l.255), and the `draft_ceiling` check through `state.config`. The scope's own `max_drafts` is left to the prompt (DM3). `test_max_drafts_sets_the_run_context_the_prompt_and_the_save_ceiling` (l.927–949) pins all of this.

### Pillar 5. Benchmark parity: ✅
* **Model IDs** come from the role constants only (l.318–321): `SCOUT_MODEL_ID`, `WRITER_MODEL_ID`, `QA_LEGAL_MODEL_ID` and `SUPERVISOR_MODEL_ID`. Each is built once.
* **Efforts** use Approach 1's `or` fallback (`../code-orchestration/src/orchestrator.py` l.993–994). The Scout's effort is the constant and is never overridable (l.308). The resolved effort is used twice: to build each model, and to label its telemetry through `SubAgentEfforts` and `run_supervisor(reasoning_effort=…)`.
* **Tests** check the defaults (`gpt-5-mini`/None, `gpt-5.4`/high, `gpt-5.4`/medium, `gpt-5.4`/medium) and the `.env` overrides (l.872–911). They tell the Supervisor apart by its system prompt, not by build order.
* **Template:** `REPO_ROOT / ".agents" / "templates" / "draft.md"` (`src/cli.py` l.85), as in Approach 1 l.1370.
* **Rates:** only `load_model_rates()` (l.172). No `rates` seam was added.
* **P1:** `build_tools(client=…)` is unchanged, and the live-substrate test lists 5 tools.
* **`_resolve_redaction_key`** is Approach 1's verbatim (strong key only, P10).
* **`build_config`** matches Approach 1's, with one difference: a `log_dir` override is also resolved, which §7.5 ("Paths are made absolute") supports and the implementer recorded.
* **`main`'s stdout lines** keep Approach 1's wording and are ASCII.

### Pillar 6. Substrate isolation and lifecycle: ✅, with N1 noted
* Exactly one `client_factory()` call and one `with client:` (l.185–186). The body holds only session-dependent work: the root's listing, `RunState` creation, `build_tools` and the Supervisor.
* `finalise_run`, the summary and `_exit_code` run after the `with` has exited (l.212–221). `test_one_session_is_opened_per_run_and_closed_before_the_run_end` pins the order: enter, Supervisor completed, exit, Draft rendered, Run completed.
* `finalise_run` runs exactly once whenever a `RunState` exists: on SUCCESS, NO_UPDATES, PARSER_ERROR, PERSISTENCE_ERROR, a fatal MCP_ERROR, SUPERVISOR_ERROR and a close-time loss. It is skipped on the two early exits (CONFIG_ERROR, and a session that fails to open), where no state was bound into any tool. That matches §4's flow ("Init: open MCP session · create RunState") and §7.6 ("once a `RunState` exists").
* **Exception classes:**
  * configuration: `(ValidationError, ValueError)`, so a scripted `AssertionError` surfaces;
  * Supervisor: `Exception`, never `BaseException`;
  * session: `(MCPConnectionError, MCPClientNotConnectedError)`.
* `finalise_run`'s `ValueError` for an unpriced model escapes `run` after the session has closed. That matches the brief and Approach 1, and a test pins it.
* **Mapping (P6 + P13):** `_exit_code` matches brief D1 term for term:
  * a fatal stop or a lost session gives 2;
  * a Supervisor that raised gives 6;
  * `not raised and not fatal_stop and not scout_succeeded` gives 3;
  * a successful Scout with no documents gives 1;
  * a persistence failure gives 4;
  * `SUCCESS` is the floor, and the result is the `max`.

  The unit table covers every D1 row, including the close-time death edge that gives 3, and all 64 combinations, against an independent oracle. The integration rows cover every §7.6 row end to end through `run`, including 2b, 2c, 4b and 4c. Every non-6 row asserts that there is no `supervisor` failure.

### Pillar 7. Rendering, telemetry and logging: ✅
* `log_context(run_id=…)` wraps the whole run (l.136–146), and `clock()` is read once, inside it.
* The D-I events the composition root owns are all present, each with its catalogue fields:
  * **"Run started":** run ID, `%r` prompt, date, `max_drafts`, level, and the four model/effort pairs;
  * **"MCP session opened":** server directory, launch command, tool count;
  * **"Configuration failure":** `exc_info`, which carries the full pydantic report;
  * **"MCP session failed to open, or died mid-run":** server directory, launch command, `exc_info`;
  * **"Supervisor invocation started / completed / failed":** the failure carries the full `RemoteErrorDetail` JSON and `exc_info`;
  * **"Run completed":** exit code with its name, drafts saved, failures, violations, `RunFinalisation` totals, wall-clock, `%r` summary.
* P12 holds: the totals come from `finalise_run`'s return value, and nothing is stored on `RunState` (DM18).
* "Run completed" closes every path, early exits included, and is the last record of a run (test l.549).
* **F1:** after a provider error, the Supervisor's tokens are recovered from `event_loop_metrics` through the shared `failed_call_telemetry`. The value is `None` only when no agent was built.
* **F2:** after a fatal stop, `supervisor_summary` is exactly what was returned (`""`), and `None` when the Supervisor raised.

### Pillar 8. Code quality: ✅, with one required minor fix
* Imports are at the top, grouped standard library / third-party / local, with no E402.
* Every signature is annotated, and no `dict[str, Any]` crosses a module boundary. The helpers (`_Efforts`, `_Models`, `_SupervisorOutcome`) are frozen dataclasses.
* Both modules use the logger names `"src.app"` and `"src.cli"`, and neither has an import-time side effect.
* `pathlib.Path` is used throughout.
* The docstrings are accurate, with the exceptions noted in §3.
* Ruff is clean. See §3 for the findings.

---

## 3. Code review findings

| # | Severity | Where | Finding |
| :---: | :--- | :--- | :--- |
| m1 | 🟢 Minor (**required**) | `src/app.py` l.351–356 | `_log_run_completed` carries `"-" if code is None else …` fallbacks for `int(code)` and `code.name`. Both callers' paths set `state.exit_code` before this call: `_ended_early` and the end of `_run_once`. The branches are therefore unreachable, and no test exercises them (no test greps `exit_code=- `). That is dead code under Pillar 8, and it makes the report's DoD-4 claim ("every new `src` function and branch tested, except `_NOT_INVOKED`") inaccurate. The remedy is in `FIXES.md` |
| m2 | 🟢 Minor (optional) | `src/app.py` l.60–61 | `_SESSION_ERRORS` restates `src/tools.py` l.94 `_FATAL_ERRORS` exactly, and its comment says so. The renames already made two `src.tools` helpers public to avoid duplication; the same could be done here, or the duplication can stay as it is. It is not a defect |
| m3 | 🟢 Minor (optional) | `tests/test_integration/test_app.py` l.837 | The docstring says the clock's date reaches "the run context, the Supervisor's user turn and the draft ID". This test saves no draft and asserts only the first two; the SUCCESS test (l.179) covers the draft ID. Trim the docstring |
| m4 | 🟢 Minor (optional) | `tests/test_integration/test_app.py` l.1028 | `clients[0]._connected is False` reads a private attribute of the reused client. It is acceptable in a lifecycle test. Only note it if P9 ever lets the client change |

`_NOT_INVOKED` (l.103–105) is acceptable as written. Its start value is overwritten on every path that reaches `finalise_run`, because nothing between `RunState` creation and `_supervise`'s return can raise a session error. It exists for definite assignment, and its comment says so.

---

## 4. Anti-patterns and risks

* **Autonomy leaks:** none. Code sequences no sub-agent.
* **Parity drift:** none. The models, efforts, template, rates and tool binding are all unchanged, and no prompt or guardrail was touched; `src/supervisor.py` is unmodified.
* **Article text towards the Supervisor:** none. The prompt alone is passed in.
* **State coupling:** `RunState` is created once, after the session opens. Early exits return a result-only `RunState` and never call `finalise_run`.
* **N1. A close-time SDK `RuntimeError` bypasses rendering. Recorded under "Needs a decision"; non-blocking.**
  * **The SDK behaviour.** Strands 1.55.1 `MCPClient.stop()` (`strands/tools/mcp/mcp_client.py` l.713–716) raises `RuntimeError("Connection to the MCP server was closed")` when its background thread recorded an exception after initialisation (l.1531–1544).
  * **Why the root misses it.** `HSEMockMCPClient.stop()` maps nothing, and P9 forbids changing that. The error is not in `_SESSION_ERRORS`, so it would escape the `with` and skip `finalise_run`, losing the drafts already saved. It would also skip "Run completed" and leave `main` to exit 1, the NO_UPDATES number.
  * **What the tests model instead.** The close-time tests (`fail_exit_with=MCPConnectionError(...)`) cover the defensive `session_lost` branch with an error the real client never raises at close.
  * **Reachability.** My probe shows that a plain subprocess death does not reach this path: it surfaces as `MCPConnectionError` at the next listing, so D-D's fatal stop and rendering work. Reaching it needs an exception in the SDK's session task after the handshake.
  * **Parity.** Approach 1 has the same exposure for its exit code (`../code-orchestration/src/orchestrator.py` l.1188–1197), but it had already written its drafts inside the `with`. The rendering loss is new to Approach 2's run-end design.
  * **Why it is a question.** Mapping an SDK `RuntimeError` to an exit code is something the sources are silent on (§1.4, item 1).

---

## 5. Remediation directives

1. **m1 (required):** remove the unreachable `None` fallbacks in `_log_run_completed` (`IMPLEMENTATION_PLAN.md` §1.3 DoD-4; architect-review Pillar 8 "no dead code"). The exact change is in `FIXES.md`, under "Architect — round 1".
2. **m2–m4:** optional.
3. **N1:** the user's decision. It does not block committing Iteration 14 once m1 is fixed. If the answer is B, the change belongs in a follow-up, test-first, with `fail_exit_with=RuntimeError("Connection to the MCP server was closed")`.

### Record points for the orchestrator (not code findings)

* **Stale range text.** Four harness lines still read "P1 to P12", or "P1–P12" in `CLAUDE.md`, because the implementer declined to edit harness configuration on another agent's instruction:
  * `CLAUDE.md` l.14;
  * `.claude/agents/architect.md` l.19;
  * `.claude/agents/implementation.md` l.17;
  * `.claude/agents/qa.md` l.19.

  Brief D3's grep check (`P1 to P12`, `P1–P12` or `P1-P12` outside `.agents/tasks/`) therefore still finds exactly these four. No test reads them. Q6 and Iteration 11 are precedents for the same one-line edit; it is for the user to approve.
* **The plan's exit-code table is superseded.** Its row "The Supervisor finishes and `state.scope is None`" (`IMPLEMENTATION_PLAN.md` l.712) is superseded by P13 (§2, l.123) and was deliberately left unedited, per brief D3. Record it as a deviation in `WALKTHROUGH.md`.
* **The P13 edits to `SPECIFICATIONS.md` match brief D3 exactly:**
  * l.4 and l.29;
  * the §6.10 comment at l.866 (`PARSER_ERROR = 3` kept);
  * the §7.6 row at l.963 and the paragraph at l.956;
  * the §8.3 heading at l.1018 and the P13 row at l.1036, which opens with the pinned statement;
  * "P14 and so on" at l.1038.

  The docs test passes.
* **The renames in `src/tools.py` are behaviour-free:** two `def` lines, four call sites and two `__all__` entries.

---

# Iteration 14 — Architect review (Stage 3, round 2)

**Scope audited:** the fix-round-1 changes reported under "Implementation — fix round 1" in `FIXES.md`:
* `src/app.py` and `src/tools.py`;
* `tests/test_integration/test_app.py` and `tests/test_unit/test_app.py`;
* the four harness lines approved by Q13: `CLAUDE.md`, `.claude/agents/architect.md`, `.claude/agents/implementation.md` and `.claude/agents/qa.md`.

Everything those changes touch was re-checked against the eight pillars.

**User answers applied:** Q12 = A (the close-time plain `RuntimeError` is a known limit; not re-raised here) and Q13 = A (standing approval for the range text).

**Verification run by the architect:**
* `uv run pytest -q`: **1413 passed**, 0 failed, in 47.2 s. That is 1410 plus the 3 new cases.
* `uvx ruff check src tests --no-cache` and `uvx ruff check src tests`: **All checks passed**, so 0 in-scope findings and 0 pre-existing debt.
* `uvx pyright src/app.py src/tools.py`: 0 errors and 0 warnings.
* An AST scan of `tests/` for `ReasoningSettings`, `CostSettings`, `CredentialManager` or `load_model_rates` calls at module level, in decorators, in default arguments or in class bodies: **none found**. QA-M1's class of defect is gone suite-wide, not only in the one parametrize.
* No live model call was made, and no `.env` was created.

## 1. Overall verdict

**APPROVED.** Every round 1 item is resolved as directed, and the fixes change no behaviour beyond what they claim. One new item, m5, is a docstring overclaim. It is optional and non-blocking.

## 2. Verification of the round 1 items

| Item | Status | Evidence |
| :--- | :---: | :--- |
| m1 (required) | ✅ | `_run_once` returns `tuple[RunState, ExitCode, RunFinalisation \| None]` (`src/app.py` l.158). The early exits return `CONFIG_ERROR` (l.175–176) and `MCP_ERROR` (l.204–205), and the run end returns the `_exit_code(...)` result after storing it on `state.exit_code` (l.215–224). `_log_run_completed(state, code, finalisation, wall_clock_seconds)` (l.348–367) logs `int(code)` and `code.name` with no fallback. The two `0 if finalisation is None` branches that remain are reachable, and `test_an_early_exit_still_logs_run_completed_with_nothing_spent` (l.618–633) pins them |
| m2 | ✅ | See §3 below |
| m3 | ✅ | `tests/test_integration/test_app.py` l.865 now claims only the run context and the user turn, which are exactly what l.881–883 assert |
| m4 | ✅ | l.1060–1061 assert `pytest.raises(MCPClientNotConnectedError)` on `clients[0].list_all_tools()`. This is sound: `HSEMockMCPClient._ensure_connected` (`src/mcp_client.py` l.120–122) raises before any I/O, so the probe opens no session and spawns no process. It uses only the public surface, so the frozen client (P9) stays untouched |
| QA-M1 | ✅ | The parametrize (l.900–917) now carries `dict[str, str]` overrides, and `ReasoningSettings(**overrides)` is built in the test body (l.933), where `_isolate_environment` is active. The docstring states why. The other `ReasoningSettings(...)` calls (l.143, 274, 1032) are all inside function bodies |
| QA-m1 | ✅ | There are three mutation-killing cases. **(a)** l.281–288: a builder `RuntimeError` escapes `run`, which pins the configuration `except` to `(ValidationError, ValueError)`. **(b)** l.445–457: a `KeyboardInterrupt` escapes and the session's events are `["enter", "exit"]`, which pins `_supervise`'s `except Exception` and the `with` closing. **(c)** l.323–343: the factory test is parametrized over both `SESSION_ERRORS` members. The implementer re-ran the narrowing mutation against the shared tuple, after m2 |
| QA-m5, QA-m6 | ✅ | The `## Implementation` entry now reads "partly applied". `_conditions_holding` (`tests/test_unit/test_app.py` l.78–83) states that it pins only P6's maximum and that the two explicit tables are the independent check |
| Q13 | ✅ | See §4 below |

## 3. The `SESSION_ERRORS` rename is behaviour-free

* **The tuple is unchanged.** `SESSION_ERRORS: Final[tuple[type[MCPClientError], ...]] = (MCPConnectionError, MCPClientNotConnectedError)` (`src/tools.py` l.96) has the same members, order and type as the former private tuple. Only its name changed, and its comment gained one clause naming the composition root's use.
* **It has one use in the module, and that use is unchanged.** It is the `isinstance` test in `_fatal_cause` (l.431). No other reference to the old name remains in `src/` or `tests/`.
* **It is exported deliberately.** It is listed in `__all__` (l.78), in sorted position.
* **The composition root's side.** `src/app.py` imports it (l.43) and catches it at l.196. The duplicate tuple and the now-unused `mcp_client` error imports are gone.
* **The whole `src/tools.py` diff over HEAD** consists of three renames:
  * this tuple;
  * `failure_record` and `failed_call_telemetry`, from round 1;
  * their call sites and three `__all__` entries.

  No logic line changed, so Pillars 3 and 4 remain untouched by this iteration.

## 4. The four harness diffs are range text only

`git diff --stat` shows 4 insertions and 4 deletions across the four files, one line each:
* "P1 to P12" became "P1 to P13" in `.claude/agents/architect.md` l.19, `.claude/agents/implementation.md` l.17 and `.claude/agents/qa.md` l.19;
* "P1–P12" became "P1–P13" in `CLAUDE.md` l.14.

Nothing else changed. Each file keeps CRLF on every line, so there is no line-ending churn. A grep for `P1 to P12`, `P1–P12` and `P1-P12` across every `.md` outside `.agents/tasks/` finds nothing, so brief D3's grep check now holds.

## 5. Pillar re-check after the fixes

| Pillar | Status | Note |
| :--- | :---: | :--- |
| 1. An agent owns the flow | ✅ | Unchanged: there is one `run_supervisor` call (l.259), and code only maps the outcome afterwards. The refactor of `_run_once`'s return value adds no branching on tool results |
| 2. Division of labour | ✅ | Unchanged: only the prompt reaches the Supervisor |
| 3. Custom agent tools | not touched | Renames only (§3 above) |
| 4. Guardrails and attempt state | not touched | |
| 5. Benchmark parity | ✅ | Models, efforts, template, rates and tool binding are all unchanged. QA-M1 makes the efforts test hermetic, so it now really pins the role constants |
| 6. Substrate isolation and lifecycle | ✅ | There is one `with` and the mapping sits outside it, as before. The new interrupt test proves that the session closes even on a `BaseException`. Q12 = A records the close-time `RuntimeError` as a known limit |
| 7. Rendering, telemetry and logging | ✅ | "Run completed" still closes every path, with the exit code passed in explicitly |
| 8. Code quality | ✅ | Ruff and pyright are clean, and the dead code is gone. m5 is optional |

## 6. Code review findings (round 2)

| # | Severity | Where | Finding |
| :---: | :--- | :--- | :--- |
| m5 | 🟢 Minor (optional) | `src/app.py` l.119–120 | `run`'s docstring says "the one exception let through is the `ValueError` of a ledger entry with no cost rate". Since fix round 1, `test_a_model_builder_defect_is_not_a_configuration_failure` pins a second one: a builder `RuntimeError`. `test_an_interrupt_during_the_supervisor_leaves_run_and_still_closes_the_session` pins a third, a `KeyboardInterrupt`. The Q12 known limit is a fourth. The behaviour is right, and only the sentence overclaims. The remedy is in `FIXES.md` |

## 7. Anti-patterns and risks

None new. There is no autonomy leak, no parity drift and no article-text path, and there is no new state coupling. Q12's latent close-time `RuntimeError` remains, as the user accepted, and belongs in `WALKTHROUGH.md` as a known limit.

## 8. Remediation directives

* **m5 (optional):** reword `run`'s docstring as `FIXES.md` "Architect — round 2" gives. Apply it only if a fix round 2 happens for another reason; it does not hold the commit.
* **For the walkthrough:**
  * the suite count at commit time: 1413, plus one for each new `.md` added to this folder, such as `WALKTHROUGH.md`;
  * Q12 = A as a known limit;
  * the superseded plan row at `IMPLEMENTATION_PLAN.md` l.712, a deviation under P13.

**Verdict: APPROVED.**
