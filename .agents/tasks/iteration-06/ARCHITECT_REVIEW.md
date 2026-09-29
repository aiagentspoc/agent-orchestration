# Iteration 6 — Architect Review (Stage 3, round 1)

**Scope audited:** `src/agents.py` (new), `tests/test_unit/test_agents.py` (new), `tests/test_unit/test_prompt_parity.py` (new), and the modified `tests/support/scripted.py`, `tests/test_unit/test_costs.py`, `tests/test_unit/test_telemetry.py`, `tests/test_unit/test_module_structure.py`, `tests/test_unit/test_schemas.py`. The orchestrator's own §3 row edit in `IMPLEMENTATION_PLAN.md` is out of scope.

**Baseline:** Approach 1's `../code-orchestration/src/agents.py`, read on disk (P7). I read it only. I did not import it, write to it or run tools inside it.

**Independent verification (my own runs, not the implementer's):**

| Check | Result |
| :--- | :--- |
| `uv run pytest` | 735 passed, 0 failed |
| `uv run pytest tests/test_unit/test_agents.py tests/test_unit/test_schemas.py` (the order that exposed the count bug) | 141 passed |
| `uv run pytest tests/test_unit/test_prompt_parity.py` | 16 passed |
| `uv run pytest -m live --collect-only` | nothing collected (735 deselected) |
| `uvx ruff check src tests --no-cache` | All checks passed |
| `grep` in `src/` for the removed `RevisionPayload` model, the phrase "revision payload" and `time_window` | nothing found: all three are removed |
| My own AST parity script (scratchpad; both files parsed, neither imported) | Scout prompt 2906 chars and QA-Legal prompt 7233 chars, **equal** to Approach 1's. The Writer diff is exactly 3 lines (the three declared substitutions). All 9 model IDs, efforts and `*_TOOL_NAMES` are equal. `extract_telemetry`, `_resolve_tools`, `_run_worker` and `run_scout` are **AST-identical** once docstrings are stripped |

---

## 1. Overall verdict

**APPROVED**

I found no blocker and no major finding. There is one 🟢 Minor docstring-accuracy item. It is in `FIXES.md` and does not block the iteration.

---

## 2. Pillar audit

### Pillar 1: An agent owns the flow, within guardrails in code ✅
* No code in `src/agents.py` sequences sub-agents. There is no `while` loop, and no runner calls another runner. The only `for` in executable code is `extract_telemetry`'s walk over `tool_usage` (`src/agents.py:446`), which is Approach 1's code, AST-identical.
* The runners never inspect QA status. No `.status` access appears in executable code. `run_writer` has one branch (`src/agents.py:713`), and it depends on whether a draft is present, not on the verdict. It chooses the wording of the turn and never whether to revise. That matches D-E: the Supervisor decides, and code hands over the latest drafted record.
* The two `ValueError` preconditions are refusals of incoherent input, not routing:
  * `run_writer` at `:701–705`: a draft without its QA report;
  * `run_qa_legal` at `:756–757`: no draft.

  Both are raised before any model call, which the tests assert with `turns_consumed == 0`. The guardrails of Iteration 5 make both inputs unreachable (`not_audited` and `no_draft`), so they are caller-bug assertions and not a thirteenth guardrail. Neither creates a `GuardrailViolation` or touches `RunState`. This is acceptable.
* `test_agents_module_contains_no_loop_state` (`tests/test_unit/test_agents.py:1319`) keeps Approach 1's structural guard.

### Pillar 2: Division of labour ✅
* The runners store nothing. They call neither `set_draft` nor `set_qa_report`, and tests assert the record is unchanged with `model_dump()` before and after (`test_agents.py:825`, `:903`, `:1215`).
* No sub-agent writes files.
* The Supervisor is not touched by this iteration, so there is no path for article text to reach it here.

### Pillar 3: Custom agent tools (D-A, D-G) ✅, for the part this iteration owns
* **Fresh agent per build.** Every builder goes through the private `_build_agent` (`src/agents.py:532–557`), which constructs a new `Agent(..., tools=_resolve_tools(...), callback_handler=None, hooks=list(hooks))`. There is no `preserve_context`, no `delegate`, no `as_tool()`, and no agent passed in `tools=`.
* **One typed input per runner.**
  * `run_scout(agent, scope: PipelineScope)`;
  * `run_writer(agent, record: AttemptRecord)`;
  * `run_qa_legal(agent, record: AttemptRecord)`.

  The `today` parameter is gone, and the date comes from `record.context.today` (D-G). The tests assert the parameter is absent (`test_agents.py:794`, `:1146`).
* **Structured output.** `structured_output_model=` is requested through the unchanged `_run_worker`.
* **The hooks seam.**
  * `hooks` is keyword-only, `Sequence[HookProvider] = ()`, and immutable by default.
  * A recording `HookProvider` is registered on each of the three builders and observes an invocation (`test_agents.py:383–407`).
  * Adding it does not change the tool binding.

  This is the seam Iteration 12 needs.

### Pillar 4: Guardrails and attempt state: not touched by this iteration
The runners read no counter. The plan's DM7/DM5 checks are covered under Pillar 5.

### Pillar 5: Benchmark parity ✅
* **Scout and QA-Legal system prompts.** Byte-identical. I confirmed this myself by AST literal comparison, and the implementer's test also compares `.encode("utf-8")`.
* **Writer system prompt.** It is Approach 1's with exactly the three declared substitutions, which are held in `WRITER_PROMPT_SUBSTITUTIONS` in the test (`test_prompt_parity.py:96–109`):
  1. the "Given one triaged `ScoutCandidate`" phrase gains the record that carries it;
  2. "If a revision payload is also supplied" becomes "If the record also carries a `draft` and its `qa_report`";
  3. "The revision payload contains" becomes "The `AttemptRecord` contains".

  Each phrase names the input. The test asserts that each old phrase occurs exactly once in Approach 1's prompt, so a substitution can neither match nothing nor rewrite a second passage.
* **Line wrapping.** Two substituted lines now run to 112 and 104 characters, against the prompt's roughly 84-column wrap. That is the correct choice: re-wrapping would move newlines outside the substituted phrases, which is a wording change the plan forbids (Iteration 6 "Stop and ask if").
* **Phrases left unchanged.** "the input candidate" (`:152`, `:162`) and `update.doc_id` (`:183`) remain, as they must. The candidate is still the Writer's input, inside the record, and the user turn names the full path `candidate.update.doc_id`. Changing them would not have been a pure input-renaming substitution.
* **Models and efforts.** Scout `gpt-5-mini`/`None`, Writer `gpt-5.4`/`high`, QA-Legal `gpt-5.4`/`medium`. These are checked twice: as literals in `test_agents.py:107`, and against Approach 1's AST in `test_prompt_parity.py:60–77`.
* **Tool binding (P1).**
  * All three builders default to `tool_names=None`, which means `list_all_tools()`, all five tools. Each builder's test asserts the full set of five `SUBSTRATE_TOOL_NAMES`.
  * The `*_TOOL_NAMES` tuples are Approach 1's, and the comment (`src/agents.py:77–79`) states that they are declared intent, not what is attached.
* **Reused code.** `extract_telemetry`, `_resolve_tools` and `_run_worker` are AST-identical to Approach 1's (`test_prompt_parity.py:159–167`, confirmed by my own script). Only their docstrings were reworded, which §1.5 allows. `run_scout` is AST-identical too, although the plan did not require it.
* **The `_as_json` change** (`src/agents.py:523–529`).
  * What changed: `model.model_dump()` became `model.model_dump(mode="json")`.
  * Why it is necessary: Approach 1's version raises `TypeError` on the new `context.today: date`.
  * Parity effect: `_as_json` now serves only the Scout. For every other `PipelineScope` field (`str`, `list[str]`, `Literal` strings, `int | None`), python-mode and JSON-mode dumps are identical, and `indent=2, ensure_ascii=False` is kept. The only change to the Scout turn is therefore the `context` object that DM5 requires. **Accepted.**
* **DM7 and DM5.** QA-Legal's turn is checked at attempts 2 and 3 (`test_agents.py:1168–1185`):
  * it carries `"attempt":N`;
  * it contains no `rationale`, `newsworthiness_score`, `candidate` or rationale text;
  * it contains no phrasing of the cap.

  The Writer's turn is checked for the cap as well (`:1188`). `AgentContext` holds `today` only (`src/schemas.py:123–132`).
* **Approach 1's revision instruction** is kept with only input renaming:
  * "QA audit" becomes "QA report";
  * "below" becomes "in the record below".

  The first-draft instruction still leads, as in Approach 1.

### Pillar 6: Substrate isolation and lifecycle: not touched by this iteration
`src/agents.py` imports only `HSEMockMCPClient` for typing and resolution. `mcp-server` is not imported. `test_factory_requires_live_client` still shows that a disconnected client fails before any agent exists.

### Pillar 7: Rendering, telemetry and logging ✅, for the part this iteration owns
* `extract_telemetry` is still the only reader of `metrics.get_summary()`.
* No logging was added. The D-I invocation events belong to the wrappers, from Iteration 7.
* **Cost basis.** Unchanged: `test_costs.py` now differs from Approach 1's only by removing `SCOPE_PARSER_MODEL_ID`, and `TEST_RATES` is keyed by the three role IDs exactly as Approach 1's is, minus the ScopeParser. The Iteration 2 rekey onto `FAST_MODEL_ID`/`STRONG_MODEL_ID` was a stopgap until `src.agents` existed, so reverting it restores Approach 1's shape. Every role's ID maps to the same rate as before, so no arithmetic changed.

### Pillar 8: Code quality and conventions ✅
* **Imports** are grouped stdlib, third-party, local (`src/agents.py:16–37`), with zero E402. Approach 1's unused `date` import was dropped along with `ScoutCandidate` and the removed model.
* **Annotations.** Every signature is fully annotated, `_build_agent` included.
* **Typed interfaces.** No `dict[str, Any]` crosses a module boundary.
* **`__all__`** has 19 names, and the test asserts the set.
* **ruff:** clean on the whole tree.
* **Dead code:** none.
* **Docstrings** are honest and reference Approach 2's documents. One test-helper docstring misstates a mechanism: see §3.
* **pyright** is not part of the DoD. The implementer reports a single error, at `_run_worker`, where `BaseModel | None` is passed as the payload. It is inherited: the code is AST-identical to Approach 1's, and the plan requires `_run_worker` unchanged. Deferred, and not a finding.

---

## 3. Code review findings

| # | Severity | File:lines | Finding |
| :---: | :---: | :--- | :--- |
| 1 | 🟢 Minor | `tests/test_unit/test_schemas.py:1173–1177` | **The docstring misstates why the helper needed fixing.** It says pydantic "registers each parametrised generic it builds at run time". I checked empirically with pydantic 2.13.5: `WorkerOutput[ScoutReport]` parametrised inside a function body is **not** registered. Only parametrisations evaluated at a module's global scope are written into the generic's module namespace. Here those come from `src/agents.py`'s return annotations (`-> WorkerOutput[ScoutReport]`, `-> WorkerOutput[_PayloadT]`, and so on), which run when `src.agents` is imported. The implementer's report blames the "unchanged `_run_worker`" call, and that is also imprecise. The fix itself is correct; only its stated cause is wrong |

**My assessment of the `_defined_models` fix itself: a legitimate bug fix, not a weakening of the Iteration 4 lock.**
* Before Iteration 6, `src.agents` did not exist, so the pollution could not occur. The test was latently order-dependent, which makes this a plain bug fix (§1.4 stop condition 2, "A plain bug fix is exempt").
* The added filter `name.isidentifier()` can only exclude pydantic's synthetic `Name[Arg]` entries. Any real `class X(BaseModel)`, and any alias `X = ...` in `schemas.py`, is bound to an identifier and is still counted.
* The lock itself, `set(defined) == SPEC_MODELS` with 27 names and `SPEC_NEW_MODELS` as a subset, is untouched and still strict.
* `src/schemas.py` is unchanged.

**Harness changes: all sound.**
* `VALID_SCOPE_ARGS` is used only by the harness self-tests' `PipelineScope` structured-output turns (`test_agents.py:134–269`). Adding `context` is what makes it a valid `PipelineScope`.
* The new `WRITER_PROMPT_SECTION` and `QA_LEGAL_PROMPT_SECTION` markers are sentences that only one runner writes. `test_agents.py:1228` proves they are disjoint across a first draft, a revision and an audit.
* The `TEST_RATES` rekey is covered under Pillar 7.

---

## 4. Anti-patterns and risks, for the next iterations

* **Iteration 7 (`scout_tool`):**
  * `VALID_SCOPE_ARGS` and its derivative `SCOPE_ARGS` (`tests/support/scripted.py:317`, `:505`) now carry `context`. They must **not** be reused as the scripted Supervisor's `scout_tool` arguments: the Supervisor never supplies `context`, because code fills it (D-A table, D-E step 1). When the deferred helpers are restored, derive the Supervisor's tool arguments from the five scope fields only.
  * The `SCOPE_ARGS` comment ("structured-output arguments") describes Approach 1's ScopeParser, which no longer exists. Reword it when that helper is touched.
* **Iterations 7 to 9 (wrappers):**
  * Call the builders with `tool_names` left at `None` (P1).
  * Pass `hooks` by keyword.
  * Build a fresh agent per call.
  * On a revision, pass `run_writer` the **latest drafted** `AttemptRecord`, not the new empty one: the Writer sees the attempt being revised, per §6.2 and D-E.
  * The runners' `ValueError`s are unreachable behind `not_audited` and `no_draft`. If one ever fires, `_invoke_sub_agent` will classify it as a recoverable failure, which is acceptable for a caller bug.
* **Iteration 16 (benchmark report caveat, not a finding):**
  * The Writer and QA-Legal user turns now carry the record as compact JSON (`model_dump_json()`, fixed in Iteration 4 by §7.2). Approach 1 used `indent=2` JSON.
  * The record also adds `context`, `attempt`, `doc_id` and a null `qa_report`.
  * Both effects on input tokens are small and pull in opposite directions, and the sources settle the choice (§7.2, and the plan's "sends `record.writer_view()`"). The benchmark report should still mention them as a known difference in the user turns.
* **DESIGN.md §4 "Used by" column:** it is stale against the current prompts: the Writer mandates `verify_legal_citation`, and QA-Legal may use `search_regulatory_docs`. I agree with this. The orchestrator owns it and will raise it with the user, so I do not raise it again.

---

## 5. Remediation directives

1. **Finding 1 (🟢 Minor, non-blocking):** reword the `_defined_models` docstring in `tests/test_unit/test_schemas.py:1173–1177` so it gives the correct mechanism. See `FIXES.md`. Record the corrected root cause in `WALKTHROUGH.md` under *Deviations* (IMPLEMENTATION_PLAN.md §1.1: the walkthrough must be accurate). Change no code.

**Ruff:**
* In-scope findings (blocking): **0**.
* Pre-existing debt (deferred): **0**.

---

# Iteration 6 — Architect Review (Stage 3, round 2)

**Scope re-audited:** the fix round's two changes:
* `tests/test_unit/test_agents.py:410–415`: the new `test_builder_without_a_client_builds_a_tool_free_agent`, for Q-1;
* `tests/test_unit/test_schemas.py:1172–1187`: the reworded `_defined_models` docstring, for A-1.

I also checked for regressions across the whole round-1 scope. `src/agents.py` was not touched: its mtime (20:17:57) is earlier than my round-1 review (20:29:33).

**Independent verification (my own runs):**

| Check | Result |
| :--- | :--- |
| `uv run pytest -q` | 741 passed, 0 failed. That is 735 at round 1, plus 3 from Q-1 and 3 from QA's round-1 additions, which is what the implementer reported |
| `uv run pytest tests/test_unit/test_prompt_parity.py` | 16 passed |
| `uv run pytest tests/test_unit/test_agents.py tests/test_unit/test_schemas.py`, then the reverse order with `-p no:randomly` | 144 passed both ways, so the `_defined_models` order-dependence stays fixed |
| `uv run pytest -k test_builder_without_a_client` | 3 passed: `scout`, `writer` and `qa_legal` |
| `uv run pytest -m live --collect-only` | nothing collected (741 deselected) |
| `uvx ruff check src tests --no-cache` | All checks passed |
| My AST parity script (scratchpad; it parses both `agents.py` files and imports neither) | No change from round 1. Scout 2906 chars and QA-Legal 7233 chars, both equal to Approach 1's. The Writer diff is still exactly the three declared substitutions. All 9 model, effort and `*_TOOL_NAMES` constants are equal. `extract_telemetry`, `_resolve_tools`, `_run_worker` and `run_scout` are still AST-identical |

## 1. Overall verdict

**APPROVED**

## 2. Round-1 items

* **A-1 (🟢 Minor): resolved.** The docstring at `tests/test_unit/test_schemas.py:1173–1179` now gives the right mechanism:
  * only parametrisations evaluated at module global scope are written into the generic's module namespace;
  * the example it names is `src.agents`' return annotation `WorkerOutput[ScoutReport]`;
  * it explains the `isidentifier()` filter.

  The function body and the lock (`set(defined) == SPEC_MODELS`, 27 names) are unchanged.
* **Q-1 (🔴 Blocker, DoD-4): resolved, and I accept the architecture of the fix.**
  * The test drives the `client is None` branch of `_resolve_tools` (`src/agents.py:486–487`) through the public builders rather than the private helper. That is the right level, and it keeps `_resolve_tools` AST-identical to Approach 1's, as the plan requires.
  * The assertion `agent.tool_names == []` is exact. The implementer's mutant, with the branch deleted, fails all three cases with `AttributeError` on `None.list_all_tools`, so this test would not pass against a stub.
  * The tool-free path is the builders' documented default (`client: HSEMockMCPClient | None = None`, at `src/agents.py:562`, `:585` and `:608`). Covering it does not change P1: the wrappers always pass a live client, so every sub-agent of a run still carries all five substrate tools. `test_builder_registers_the_hooks_it_is_given` and the per-builder binding tests still assert that.
* **Q-2 and Q-3 (🟢 Minor, `WALKTHROUGH.md`): I accept the orchestrator's handling.** Under `IMPLEMENTATION_PLAN.md` §1.1 and §1.2 step 8, `WALKTHROUGH.md` is the orchestrating agent's artifact at Stage 4. Both items are accuracy fixes to that record and need no code change, so the implementer was right to leave them. On the same basis I include my own round-1 directive: record the corrected `_defined_models` root cause under *Deviations*. Nothing blocks the commit on these, provided the walkthrough carries them.

## 3. Pillar audit (regression check)

The fix round touched no production code, so every round-1 pillar assessment stands unchanged:

| Pillar | Status |
| :--- | :--- |
| 1. An agent owns the flow | ✅ |
| 2. Division of labour | ✅ |
| 3. Custom agent tools | ✅ |
| 4. Guardrails and attempt state | not touched |
| 5. Benchmark parity | ✅, re-verified above |
| 6. Substrate isolation and lifecycle | not touched |
| 7. Telemetry and logging | ✅ |
| 8. Code quality | ✅ |

The new test adds no import, and uses only `_BUILDERS` and `ScriptedModel`, which already existed. Its annotations are complete, it contains no dead code, and it is placed with the other builder tests.

## 4. Code review findings

None new.

## 5. Remediation directives

None.

**Ruff:**
* In-scope findings (blocking): **0**.
* Pre-existing debt (deferred): **0**.
