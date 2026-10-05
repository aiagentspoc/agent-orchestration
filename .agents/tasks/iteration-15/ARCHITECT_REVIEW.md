# Iteration 15 — Architect review, round 1

**Scope audited:** the uncommitted diff at `b797e13` + working tree. `git status --short` shows exactly two entries:

* `?? tests/test_integration/test_supervisor_e2e.py` (new, 1193 lines), the iteration's deliverable;
* ` M .agents/docs/IMPLEMENTATION_PLAN.md`, a one-row tracker change (`⏳ Pending` → `🔄 In progress`) made by the orchestrator.

`git status --short src` and `git diff --stat -- src` are empty: **no production code changed**, as the pre-flight required.

**Evidence run by the reviewer:**

| Check | Result |
| :--- | :--- |
| `uv run pytest -q` | **1433 passed** (1414 + 19), 96.6 s |
| `uv run pytest tests/test_integration/test_supervisor_e2e.py --durations=5` | 19 passed in 50.0 s; slowest scenario 3.05 s (AC1 bound: 60 s) |
| `uvx ruff check src tests --no-cache` | **All checks passed.** In-scope findings: 0. Pre-existing debt: 0 |
| Live model calls | None. Every model is a `ScriptedModel` (four per run, keyed by `(model_id, effort)`); x01's builder raises before any model exists |
| Orphaned substrate processes | None from the tests. The five `fastmcp.exe` processes on the machine are all children of `uv run --directory … fastmcp run server.py` **without** `--quiet` and started before this review; `HSEMockMCPClient` launches with `--quiet` (`src/mcp_client.py` l.83), so they are the harness's own MCP servers |

---

## 1. Overall verdict

**APPROVED.**

No blocker, no major finding. Four optional, minor suggestions (§3, §5) are recorded in `FIXES.md` and marked optional; none needs a decision.

---

## 2. Pillar audit

### Pillar 1 — An agent owns the flow: ✅

* **No test code drives the Supervisor.** Every scenario hands `src.app.run` a fixed list of Supervisor turns (`_run`, l.220–249); the Supervisor's tool choices are those turns alone. There is no loop over Writer and QA-Legal, no status-dependent branching on tool results, and no Graph, Swarm or Workflow. The module docstring (l.5–6) states the rule.
* **Scenario 10's fault injector does not choose a step.** `_SessionKillingSupervisor.stream` (l.819–827) only stops the substrate transport before replaying turn index 4, then delegates to `ScriptedModel.stream` unchanged. The turn it replays (`writer_tool(DOC_B)`) is the scripted one. Injecting an environmental fault is not sequencing.
* **Code only refuses.** s08 and s09 show refusals returned and the run continuing to the Supervisor's own final turn (`_assert_consumed(... supervisor=16)` / `supervisor=7`).

### Pillar 2 — Division of labour, D-F: ✅ (s15 is thorough)

`test_s15_no_message_the_supervisor_received_carries_article_text` (l.1058–1111) is the right shape and strength:

* **Unique sentinels** in all three article fields of three Writer drafts (A1, A2, B2) via `_sentinel_draft` (l.1041–1043). The positive control at l.1092 proves the text exists and reached the rendered draft, so the negative check is not vacuous.
* **Two forms of search per message:** (a) every string leaf of the raw message history (l.1100–1102), which includes the `toolResult` JSON as a raw string, the `toolUse` inputs and any text block; (b) each `toolResult` JSON parsed and walked for both sentinels and `FORBIDDEN_SUPERVISOR_KEYS` (l.1103–1105). `sent_text`'s blind spot for `toolResult` (pre-flight §7) is avoided.
* **Every round trip is covered:** `len(received) == turns_consumed` (l.1099), all 11 Supervisor turns.
* **Every result kind is proved present,** not assumed (l.1107–1111): 10 results in the final history, a writer failure summary (`str` error), a guardrail violation (`dict` error), and a revision (`attempt == 2`), alongside the ScoutReport, QA reports with `WARNING`, `PASS` and `ERROR` and a `DraftResult`.
* **The implementer's mutation** (`supervisor_view` keeping the draft) made s15 fail, so the test has teeth.
* **Paths s15 does not exercise are safe by construction.** The rule-2 rejection (`WriterSourceFetchError`, `src/tools.py` l.640–649) and every other failure reach the Supervisor only through `_one_line_error` (l.506–514), which emits exception type names and an HTTP status, never exception text. One failure kind is therefore representative of all of them.

### Pillar 3 — Custom agent tools: not touched by this iteration

The scenarios exercise the wrappers end to end (fresh sub-agent per call is implied by `writer_turns` being consumed per call, and s01 sees `Tool call completed: tool=get_document_by_id agent=writer`), but no wrapper changed.

### Pillar 4 — Guardrails and attempt state: ✅ (exercised end to end)

* **s08** produces seven of the 12 guardrails through real tools (`already_audited`, `revise_after_pass`, `initial_draft_exists`, `not_a_candidate`, `already_saved` (P2, on `writer_tool`), `error_with_attempts_remaining`, `draft_ceiling`). For each one it asserts all three D-C obligations, each from its own source:
  * **returned:** `result is None` and `error.guardrail`, parsed from the Supervisor's own received `toolResult`s (l.761–764);
  * **logged:** at WARNING, on the refused document's `doc_id`, with `guardrail=` and `tool=` (l.766–769);
  * **stored:** the `RunState.violations` list compared exactly, in order (l.752).
* **s09 (DM16):** five identical `scout_already_run` violations are all logged and stored. The run still reaches its final turn, and "Run completed" reports `violations=5`.
* **s13b:** `invalid_scope` does not consume the Scout's one run (§7.3, D-C run-level guardrails).
* **The attempt counter is held in code:** s05 (a failed first call is attempt 1, with no `initial_draft_exists` on the retry), s06 (a rejected revision is attempt 2, and attempt 1's text is rendered), s07 (three failures, then skip), and s02 (`ERROR` saved only at the cap, with the banner).
* `attempt_limit`, `not_audited` and `no_draft` have no end-to-end scenario. The plan's scenario table does not ask for them, and each is produced twice at Gate 4 by earlier iterations. This is acceptable as recorded (implementer's decision 9).

### Pillar 5 — Benchmark parity: not touched by this iteration

No prompt, model, effort, tool binding, template or cost basis changed.

The Supervisor's effort is set to `low` **only in the test**, through the `reasoning_settings` seam, so the effort-keyed builder can tell it apart from QA-Legal's `(gpt-5.4, medium)`. `test_app.py` keeps pinning the default `medium`. This is a test seam, not parity drift.

### Pillar 6 — Substrate isolation and lifecycle, D-D: ✅

* **One real stdio session per run.** The default `client_factory=HSEMockMCPClient` is used, and s10 uses a capturing factory that asserts there is exactly one client (`[client] = self._clients`).
* **Scenario 10's mechanism is sound, and does not reach the Q12 path.** I traced Strands 1.55.1:
  * `MCPClient.stop()` (`.venv/…/strands/tools/mcp/mcp_client.py` l.633–716) raises `RuntimeError("Connection to the MCP server was closed")` only when `_close_exception` is set, which happens only when the background session task *failed*.
  * The test's `client.mcp_client.stop(None, None, None)` is a **clean** shutdown, so `_close_exception` stays `None`.
  * It resets `_background_thread` to `None`. The outer `with HSEMockMCPClient()`'s `__exit__` → `stop()` therefore skips both the signal and the join, and raises nothing.
  * The next sub-agent build's listing raises `MCPClientInitializationError`, which `HSEMockMCPClient._list_tools` (l.165–170) maps to `MCPConnectionError`. That is exactly the dead-transport surface in §8.4's Known limit.
  * `_connected` stays `True`, so the path is `MCPConnectionError`, not `MCPClientNotConnectedError`.

  The test would also catch a regression into the Q12 path. A close-time `RuntimeError` would escape `run` and fail the test, and any extra `mcp_session` failure would break the exact `_failures == [("mcp_session", DOC_B, 1)]` (l.852).
* **D-D.1 outcomes asserted:**
  * exit `MCP_ERROR`;
  * `fatal_error` is an `MCPConnectionError`;
  * Supervisor `turns_consumed == 5` against a 6-turn script;
  * exactly five `Model HTTP call: agent=supervisor` lines, the last before the abort;
  * `supervisor_summary == ""`;
  * the saved draft is still rendered;
  * B is logged as left unsaved, `not_drafted`.
* **s11:** a provider error after one save still renders the save and exits `SUPERVISOR_ERROR` (6), with the full `RemoteErrorDetail` (status 429, request ID) and the traceback.

### Pillar 7 — Rendering, telemetry, logging: ✅

* **D-B token identity.** It is checked twice: with a zero unsaved term (s01) and with a real one (s08):

  Σ draft tokens + unsaved docs' ledger tokens == "Run completed" `total_tokens` == Σ ledger

* **§6.8 IDs.** s14 pre-creates today's `_001` and `_003` (a gap). The run's saves become `_004` and `_005`, the pre-existing files stay byte-identical, and the IDs carry the injected date, not the real one.
* **Correlation.** Every `src.*` line carries the run's `run_id` (`_assert_run_completed`, l.304). `doc_id` and `attempt` are checked where the plan names them (s03, s05, s06, s07, s08, s10).
* **AC2 (catalogue coverage) is sound:**
  * `_catalogue()` parses the D-I table **from SPECIFICATIONS.md** (between `**Event catalogue:**` and `#### D-J.`), so the test cannot drift from the spec.
  * It pins 23 events, and requires the pattern map's keys to equal the catalogue's.
  * The union of the 18 static `_SCENARIO_EVENTS` declarations must equal the catalogue.
  * Each declaration must belong to exactly one `test_<key>_` function.
  * `_assert_events` also checks that every matching line is at the **catalogue's level**.
  * The declarations are static, not a runtime registry, so the result does not depend on test order or `-k`.
  * I verified by reading that each of the 18 run tests calls `_assert_events(result, "<its own key>")` (l.495 … l.1170).
* **Recorded limits, and why they are acceptable:**
  * **The httpx half of "Model HTTP call"** (method, URL, status) is unreachable under P4, since scripted models make no HTTP request.
  * **"Configuration failure" and "Draft render or write failure"** are reachable by none of the plan's 15 scenarios. The two supplementary runs, x01 (exit 5) and x02 (exit 4), cover them. This is test organisation, which §1.5 permits.
  * **DEBUG request bodies** are not a catalogue row, so no exclusion is needed.

### Pillar 8 — Code quality and conventions: ✅

* **Imports:** at the top, grouped stdlib / third-party / local. Zero E402, and ruff is clean.
* **Annotations:** every function, fixture and test is fully annotated. `Any` appears only for JSON-like scripted payloads inside the test module, which is the harness's own convention (`tests/support/scripted.py`). Nothing crosses a `src/` boundary.
* **Paths:** `pathlib.Path` throughout, and every file read and write passes `encoding="utf-8"`.
* **Style:** `Final` constants, frozen dataclasses (`_LogLine`, `_Run`) and typed helpers. Sections are clearly delimited, and the docstrings are honest and cite the spec. Line length is within 120.
* **Dead code:** none. `_unconfigured_model_builder`'s parameters are unused, but they are required by the `ModelBuilder` protocol.
* **Conventions:** it follows `tests/test_integration/test_app.py` (module docstring citing the spec, a `_Run` dataclass, `-> None` tests).

---

## 3. Code review findings

| # | Severity | File:lines | Finding |
| :---: | :---: | :--- | :--- |
| 1 | 🟢 Minor (optional) | `tests/test_integration/test_supervisor_e2e.py` l.208–210 | `_Run.index` uses `tuple.index`, which compares `_LogLine` by **value**. `_LogLine` drops the timestamp (`match.groups()[1:]`, l.172), so two records with identical level, ids, logger and message would resolve to the first one, and an order assertion could pass or fail for the wrong reason. Every current use is on lines whose message is unique (durations, ids), so nothing is wrong today |
| 2 | 🟢 Minor (optional) | same file, l.300–301 | `f"violations={n}" in completed.message` and `f"failures={n}"` are substring checks: `violations=1` would also accept `violations=12`. `_field(completed, "violations") == str(n)` is exact |
| 3 | 🟢 Minor (optional) | same file, l.779, l.532 | `[_scout_call()] * (1 + repeats)` and `[_verdict(...)] * 3` repeat **one** turn object. `ScriptedModel.__init__` copies only the outer list (`list(turn)`), so the event dicts are shared across turns. It works today; building each turn fresh (`[_scout_call() for _ in range(...)]`) removes the latent aliasing |
| 4 | 🟢 Minor (optional) | same file, l.1191–1193 | The AC2 test proves that each `_SCENARIO_EVENTS` key has exactly one `test_<key>_` function, but not that that function calls `_assert_events` with **its own** key. Today all 18 do (verified by reading). A source check (`inspect.getsource(fn)` contains `_assert_events(result, "<key>")`) would make the guarantee mechanical |

No 🔴 or 🟡 findings.

---

## 4. Anti-patterns and risks

* **Autonomy leak: none.** No test-side sequencing, as Pillar 1 shows.
* **Article text towards the Supervisor: none observed,** and s15 now guards it at the model boundary, not only at the `ToolResult` boundary.
* **D-J compliance.** Assertions are on outcomes (exit code, files, Status and Revision Attempts lines, the `violations` and `failures` lists), guardrails and log events.
  * The exact per-role turn counts in `_assert_consumed` are not a call-sequence assertion on production code. They prove that each scripted role's script was consumed exactly, so a sub-agent script that ran dry, which `tools.py` would turn into a quiet recoverable failure, cannot pass unnoticed.
  * The ordered comparisons are of the stored `violations` list and of two log-event pairs. One of those pairs is required by the plan (s03, "Revision requested follows WARNING").
* **One brittle characterisation (accepted).** s10, l.868, asserts that "Fatal abort triggered" precedes the fatal tool's "Tool call completed". That depends on Strands dispatching `AfterToolCallEvent` callbacks in reverse registration order, and on the hook order in `src/app.py`. No spec line requires this order; the D-D requirement, no model call after the fatal tool, is asserted separately (l.857, l.870–871). It is kept because it documents real SDK behaviour, but if a hook-registration refactor breaks only this line, relax it rather than reorder production hooks.
* **Coupling to a reused module's attribute.** s10 reaches `HSEMockMCPClient.mcp_client`. P9 freezes that module's behaviour, and the attribute has been there since Approach 1, so this is acceptable for fault injection.

---

## 5. Remediation directives

**None required.** The four optional items in §3 are written to `FIXES.md` under `## Architect — round 1`, marked optional. Applying them is at the implementer's discretion (§1.5, test organisation).

The walkthrough must record these **decisions and deviations**, so §1.1's record is complete:

* **Scenario 11** uses a `ScriptedModel` exception turn carrying a genuine `openai.RateLimitError`, rather than the plan's "(`FailingModel`)". `FailingModel` fails on every invocation, so it cannot fail "after one save". This is a deviation in wording, not in intent.
* **The supplementary runs x01 and x02** were added for AC2.
* **Scenario 13b** runs to a save and exits 0, a value the plan leaves unspecified.
* **"Model HTTP call"** is asserted on its hook half only.
* **The per-scenario wall-clock figures** must be recorded (AC1). The implementer's figures are 1.89–2.95 s, and this review measured a maximum of 3.05 s.

---

**Verdict: APPROVED**

---

# Iteration 15 — Architect review, round 2

**Scope audited:** the fix round 1 changes in `tests/test_integration/test_supervisor_e2e.py`, which is still untracked and was read directly, plus everything those changes touch. `git status --short` is unchanged from round 1: the e2e file, the iteration-15 artifact folder, and the one-row tracker change in `IMPLEMENTATION_PLAN.md`. `git status --short src` and `git diff --stat -- src` are both empty, so production code is still unchanged.

**Evidence run by the reviewer:**

| Check | Result |
| :--- | :--- |
| `uv run pytest -q` | **1436 passed**, 80.9 s |
| The +3 since round 1 | Confirmed by `--collect-only`: these are `test_document_uses_no_forbidden_term` for the three iteration-15 review files (`ARCHITECT_REVIEW.md`, `FIXES.md` and `QA_REVIEW.md`). No test was lost and none was added to the e2e file |
| `uv run pytest tests/test_integration/test_supervisor_e2e.py -q` | 19 passed, 40.2 s |
| `uvx ruff check src tests --no-cache` | **All checks passed.** In-scope findings: 0. Pre-existing debt: 0 |
| Run artefacts after the suite | `drafts/` and `logs/` hold only `.gitkeep` |
| Live model calls | None (P4). The fixes add no model and no builder |

## 1. Overall verdict

**APPROVED.**

All four round 1 items are applied as directed, and so is QA-1. No regression was found where they touch the file, and there are no new findings.

## 2. Verification of the round 1 items

| # | Item | Where | Verified |
| :---: | :--- | :--- | :--- |
| 1 | `_Run.index` by position | l.145–177, l.211–214 | ✅ `_LogLine` gains `position: int`. Both `append` sites in `_read_log` fill it from `len(records)` before appending, so positions are 0-based and dense. `index` returns `line.position`. |
| 2 | Exact counters | l.304–305, l.797 | ✅ `_field(completed, "violations") == str(len(state.violations))`, and the same for `failures`. `_field`'s `(?:^\|\s)name=` anchor stops a longer key from matching. s09's own check is exact too. |
| 3 | Fresh turns | l.536, l.784 | ✅ s02 uses a list comprehension of `_verdict(...)`, and s09 unpacks a generator of `_scout_call()` into the list literal. Each turn's event dicts are now distinct objects. |
| 4 / QA-1 | Each scenario asserts its own key | l.18, l.1187–1202 | ✅ `import inspect` is at the top, in the stdlib group, so there is no E402. `[name] = [...]` still requires exactly one matching test. The `_assert_events(result, "<key>")` source check includes the closing quote and paren, so `s13` cannot be satisfied by `s13b`, and `test_s13_` cannot prefix-match `test_s13b_`. The docstring (l.1190–1192) now describes the stronger guarantee honestly. |

**Cross-checks on what the fixes touch:**

* **`_LogLine` equality now includes `position`.** No code compares two records by value: the only consumers are `events()`, `_field`, `_assert_events` (a level set), the `run_id` set at l.308 and the three `index` comparisons. Nothing depends on the old value equality.
* **The three `index` call sites,** l.584 (s03), l.875 and l.878 (s10), are unchanged and pass. Item 1 strengthens l.878 in particular. `result.index(supervisor_calls[-1])` now means the *last* Supervisor model call, whatever the text of the five "Model HTTP call" lines. Under the old value lookup, identical lines would have resolved to the first one, and the D-D "no model call after the fatal tool" ordering would have been checked against the wrong record.
* **The 18 `_assert_events(result, "<key>")` calls** (l.499 … l.1177) each name the key of their own `test_<key>_` function. The source check now enforces this mechanically.
* **s09's l.797 is now implied** by l.792 together with `_assert_run_completed`'s l.304. It stays as a readable statement of the scenario's own constant, so it is harmless and not a finding.
* **Residual limit, accepted.** The AC2 source check is textual, so a call that appears only in a comment or a docstring would satisfy it. It is not worth a finding: a non-executing call is unlikely, and the check closes the realistic regression, a deleted call, which the implementer showed failing with `AssertionError: x01`.

## 3. Pillar audit (delta)

* **Pillars 1, 2, 4, 6 and 7:** unchanged from round 1. The fixes alter no scenario script beyond rebuilding identical turns as fresh objects, and no outcome, guardrail or event assertion is weakened. Item 2 and item 4 tighten Pillar 7's checks (D-I counters and catalogue coverage). No test code sequences the Supervisor.
* **Pillars 3 and 5:** not touched by this iteration.
* **Pillar 8:** ✅. The imports are grouped and at the top. Annotations are complete (`position: int`), `pathlib.Path` is unchanged, there is no dead code, and ruff is clean.

## 4. Code review findings

None.

## 5. Anti-patterns and risks

None new. The round 1 note on s10's hook-order characterisation (l.875) still stands, unchanged.

## 6. Remediation directives

None. The walkthrough items listed in round 1 §5 still apply. It should also record that fix round 1 applied all four optional items, and that the suite went from 1433 to 1436 because of the docs cases for the three review files.

---

**Verdict: APPROVED**
