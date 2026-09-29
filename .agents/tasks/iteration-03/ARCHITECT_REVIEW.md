# Iteration 3: Architect Review (Stage 3, round 1)

**Iteration:** 3, Logging setup and correlation
**Reviewer:** architect
**Date:** 2026-09-29
**Scope audited:** `git status --short` and `git diff` against `5b6ae08`:
* `src/logging_setup.py` (new, 206 lines)
* `tests/test_unit/test_logging.py` (new, 623 lines)
* `tests/test_unit/test_module_structure.py` (+1 line)
* `tests/conftest.py` (1 comment line)

The §3 row edit in `.agents/docs/IMPLEMENTATION_PLAN.md` belongs to the orchestrator and is out of this audit.

---

## 1. Overall verdict: **APPROVED WITH RESERVATIONS**

The findings: 0 blockers, 0 majors, 3 minors (🟢), all test hygiene in `tests/test_unit/test_logging.py`. Nothing in `src/` needs a change.

The moved code is verbatim, and `configure_logging` has exactly the three amendments the brief allowed. The correlation mechanism is sound under Strands' thread handoffs. There is no import-time side effect, and the module imports nothing from `src`.

Checks run:

| Check | Result |
| :--- | :--- |
| `uv run pytest` | 360 passed, 0 failed, 0 errors, 39.65 s |
| `uv run pytest tests/test_unit/test_logging.py` | 39 passed, 0.59 s |
| `uv run pytest -m live --collect-only` | 0 collected (360 deselected) |
| `uvx ruff check src tests --no-cache` | All checks passed. In scope: **0**. Pre-existing debt: **0** |
| `uvx ruff format --check` on the two new files | Already formatted |

No live model call was made. The suite constructs no model, agent or HTTP client.

---

## 2. Pillar audit

| # | Pillar | Assessment |
| :---: | :--- | :--- |
| 1 | An agent owns the flow | Not touched by this iteration. `logging_setup.py` has no control flow over any sub-agent |
| 2 | Division of labour | Not touched by this iteration |
| 3 | Custom agent tools | Not touched by this iteration |
| 4 | Guardrails and attempt state | Not touched by this iteration. `attempt` is a correlation *label* only; the counter stays with Iteration 5 and later |
| 5 | Benchmark parity | ✅ See §2.1. `ROUTED_LOGGERS`, the redaction filter, the handler levels (file = resolved level, stderr = WARNING), `propagate = False` and the re-entrancy behaviour are identical to Approach 1 |
| 6 | Substrate isolation and lifecycle | Not touched by this iteration. The thread-copy claim about the MCP client was verified, see §2.2 |
| 7 | Rendering, telemetry, logging | ✅ Logging: `run_YYYYMMDD.log`, five routed loggers, stderr mirror, full-fidelity tracebacks, redaction, and `run_id` / `doc_id` / `attempt` on every record header (`-` when unset). The D-I *events* are not emitted yet; they belong to Iterations 7 to 14 |
| 8 | Code quality | ✅ Stdlib-only imports at the top, grouped, zero E402. Full PEP 484/585/604 annotations, `Final` on every constant, `pathlib.Path`, honest docstrings, no dead code. Three 🟢 test-hygiene items, see §3 |

### 2.1 Verbatim check against Approach 1

I checked this by comparing ASTs with the docstrings stripped, not by a text diff, so CRLF and formatting cannot hide a change. I compared against `../code-orchestration/src/orchestrator.py`: lines 135, 138 and 141 for the constants, and lines 1233 to 1325 for the filter and the two functions.

| Symbol | Result |
| :--- | :--- |
| `ROUTED_LOGGERS`, `_MANAGED_HANDLER_FLAG`, `_REDACTION_PLACEHOLDER` | Identical |
| `_ApiKeyRedactionFilter` | Identical, docstring included |
| `_resolve_log_level` | Body identical. The docstring was reworded, since the "§5.1 writes WARN" remark referred to Approach 1's spec. §1.5 allows this |
| `configure_logging` | Exactly three differing statements, listed below. The docstring was reworded, which §1.5 allows. The signature is unchanged: `(level: str, log_dir: Path, api_key: str \| None = None) -> None` |

The three statements that differ in `configure_logging`:
1. the formatter, `logging.Formatter(_LOG_FORMAT)`;
2. the file name, `run_{date.today():%Y%m%d}.log`;
3. the new line `handler.addFilter(CorrelationFilter())` inside the handler loop, before the key-conditional redaction filter.

The filter order has no effect on the output: redaction rewrites `record.msg` only, and correlation sets only the three extra attributes.

### 2.2 Context-variable safety under Strands' threads

The module docstring (`src/logging_setup.py:11-12`) claims that the MCP client and the SDK copy the caller's context into their worker threads. I checked this against the installed SDK, and it holds:

* `.venv/Lib/site-packages/strands/_async.py:43-44`: `run_async` does `contextvars.copy_context()` and then `executor.submit(context.run, …)`. So `Agent.__call__` keeps the caller's `log_context`.
* `.venv/Lib/site-packages/strands/tools/mcp/mcp_client.py:456-457`: `MCPClient.start()` runs its background thread under `ctx.run` over a copy made at `start()`.
* `mcp_client.py:940-945`: tool calls are handed over with `asyncio.run_coroutine_threadsafe`, which carries the caller's context per call.

`_CORRELATION` holds an immutable `NamedTuple` and is changed only by `set` and `reset(token)` inside `try/finally` (`src/logging_setup.py:90-101`). So a copied context cannot be mutated from another thread, and a nested exit restores the outer values exactly, even on an exception. Tests pin both: `test_leaving_a_log_context_by_an_exception_restores_the_outer_values` and `test_a_log_context_does_not_leak_into_an_unrelated_thread`.

**Carry-forward to Iteration 14.** The MCP background thread's context is a snapshot taken at `start()`. `run_id` therefore reaches the records `mcp.client.*` logs on its own thread only if `log_context(run_id=…)` is entered **before** `with HSEMockMCPClient(...)`. A `doc_id` or `attempt` set later reaches tool-call coroutines, which get a per-call copy, but not the session's own housekeeping records. The implementer noted this too. Iteration 14's pre-flight must carry it as a binding constraint.

### 2.3 Where the sources and the code disagree (each one named, none silent)

1. **Plan text: `log_context(**fields)`. Code: `log_context(*, run_id=None, doc_id=None, attempt=None)`.**
   * The explicit keyword-only form is strictly narrower than `**fields`, and fully typed. A misspelt field raises `TypeError`, which `test_log_context_rejects_an_unknown_field` pins.
   * Nothing here is visible to a model, so §1.5 allows the choice.
   * Accepted.
2. **The plan's Green lists "the name of the `src` logger, moved from Approach 1's `orchestrator.py`"; it was not moved.**
   * `PIPELINE_LOGGER_NAME = "src.orchestrator"` names a module that does not exist in Approach 2.
   * The implementer replaced it with a convention: every `src` module names its logger by the literal `"src.<module>"`. An AST scan of `src/*.py` enforces the convention (`test_logging.py:88-104`).
   * The `"src"` entry of `ROUTED_LOGGERS` is moved.
   * Accepted as recorded deviation 2. Minor item A-m2 below tightens the scan so it matches the convention as the implementer stated it.
3. **D-I says "every line carries `run_id`"; the code puts the fields on every record's header line.** The lines of a traceback, and of any multi-line message, follow verbatim without the prefix.
   * I read this as the reading that keeps D22's full fidelity. Records are written in order, one run per process, so a traceback follows its correlated header, and `test_a_traceback_is_written_in_full_under_its_correlated_header` pins that.
   * The line format is not a contract visible to a model or a benchmark constant (Approach 1 had no correlation), so this is a §1.5 decision, and it is recorded (decision 4).
   * No question is raised. The orchestrator should keep decision 4 in the walkthrough, in the words "per record header line".
4. **D-I lists `--log-level INFO | WARNING | ERROR` with `DEBUG` "still available", and §7.5 lists `{DEBUG,INFO,WARNING,ERROR}`.** These are consistent. `LOG_LEVELS` follows §7.5. `WARN` still resolves (Approach 1's body, verbatim), but `LOG_LEVELS` does not offer it, which matches §7.5.

---

## 3. Code review findings

`src/logging_setup.py` has no findings:
* the imports are stdlib only, at lines 22 to 29, sorted, with none from `src`;
* `__all__` is explicit;
* every constant is `Final`;
* the `ContextVar` default is bound to a `Final` immutable, which fixes B039 properly rather than suppressing it;
* `CorrelationFilter.filter` never drops a record;
* the docstrings are accurate, and the claim at 11-12 was verified in §2.2.

The minors are all in `tests/test_unit/test_logging.py`:

| ID | Severity | Where | Finding |
| :--- | :---: | :--- | :--- |
| A-m1 | 🟢 | `tests/test_unit/test_logging.py:612` | `subprocess.run([sys.executable, "-c", probe], …, check=True)` has no `timeout=`. If the import ever blocks, the whole suite hangs instead of failing. Gate 8 requires subprocess safety on Windows |
| A-m2 | 🟢 | `tests/test_unit/test_logging.py:95-104` | The AST guard rejects only `__name__` and nameless calls, and checks only `ast.Constant` arguments. Any other expression passes unchecked, for example `getLogger(f"{__name__}")`, `getLogger(__spec__.name)` or `getLogger(SOME_NAME)`. That is weaker than the convention the implementer recorded ("explicit literal `"src.<module>"`"), and weaker than the docstring's promise that a record can never fall through to `lastResort`. The one legitimate non-literal call is `logging.getLogger(name)` inside `configure_logging` (`src/logging_setup.py:198`) |
| A-m3 | 🟢 | `tests/test_unit/test_logging.py:83-85` | `test_src_child_loggers_are_routed_by_ancestry` compares a test-local constant (`SRC_CHILD_LOGGER = "src.tools"`) with `ROUTED_LOGGERS`. That is already pinned at line 80, so the test cannot fail for any change to `src/`. Approach 1's version asserted a real production logger name; there is none yet. This is dead test weight |

---

## 4. Anti-patterns and risks

* **Autonomy leaks, and article text reaching the Supervisor:** none. The module has no knowledge of agents or tools.
* **Parity drift:** none. The routed loggers, the levels, `propagate`, redaction and re-entrancy are identical, and only the file name and the line shape changed, both as D-I requires.
* **Inherited redaction gap (parity, not a new defect).** `_ApiKeyRedactionFilter` masks `record.getMessage()` only. The key would still be written if it appeared in exception text rendered from `exc_info` (the traceback), or in a record's `extra` fields. The filter was moved verbatim as the brief required, and correlation does not widen the gap. It should be reconsidered with Approach 1's owner if the key is ever seen in provider exception messages. This iteration raises no item for it.
* **`caplog` does not see correlation fields.** `caplog.handler` has no `CorrelationFilter`. Iterations 7 to 11 either read the log file under `configure_logging`, or call `caplog.handler.addFilter(CorrelationFilter())`, as the class docstring says (`src/logging_setup.py:107-109`). Their pre-flights should name this.
* **Precedence of `extra=`.** A field given through `extra=` wins over the context (`src/logging_setup.py:114-116`). That is sensible, but it means a tool wrapper that passes `extra={"attempt": ...}` inside a `log_context(attempt=...)` can print a different attempt from the one the context set. Iteration 7 should pick **one** way of correlating: the context manager, not `extra=`.
* **Midnight rollover.** The file is chosen once per `configure_logging` call, so a run that crosses midnight stays in the file it started with. This is Approach 1's behaviour, accepted.

---

## 5. Remediation directives

These are optional-but-requested minors, for implementation fix mode. Exact changes are in `FIXES.md`.

1. **A-m1.** Add `timeout=60` to the `subprocess.run` call at `tests/test_unit/test_logging.py:612`. Required by: code-reviewer Gate 8, and `IMPLEMENTATION_PLAN.md` §1.3 DoD-1, since a hang is neither a pass nor a fail.
2. **A-m2.** In `tests/test_unit/test_logging.py:95-104`, require every `getLogger` argument to be an `ast.Constant` under a routed root. The one exemption is `logging_setup.py`'s loop over `ROUTED_LOGGERS`. Required by: the implementer's decision 3 as recorded, and SPECIFICATIONS.md D-I ("routed to that file").
3. **A-m3.** Delete `test_src_child_loggers_are_routed_by_ancestry` (`tests/test_unit/test_logging.py:83-85`). Keep `SRC_CHILD_LOGGER`, which the other tests use. Required by: code-reviewer Gate 1, "a test that would also pass against a stub is not coverage".

The orchestrator should also do two things:
* keep decisions 1 to 8 and deviations 1 to 3 in `WALKTHROUGH.md`, including §2.3 items 2 and 3 above;
* carry into the Iteration 7 and Iteration 14 pre-flights the rule that `log_context(run_id=…)` is entered before the MCP session opens (§2.2), and the `caplog` note (§4).

---

# Iteration 3: Architect Review (Stage 3, round 2)

**Reviewer:** architect
**Date:** 2026-09-29
**Scope audited:** the fix round's changes to `tests/test_unit/test_logging.py` and to the `CorrelationFilter` docstring in `src/logging_setup.py`, and the P10 record. For P10 that covers `IMPLEMENTATION_PLAN.md` §2 and §6, `SPECIFICATIONS.md` lines 4 and 29 and §8.3, `tests/test_unit/test_docs_consistency.py:187,692,719`, and the range pointers in `AGENTS.md:15`, both skills, `CLAUDE.md:14` and `.claude/agents/{architect,implementation,qa}.md`.

## 1. Overall verdict: **APPROVED**

The findings: 0 blockers, 0 majors, 0 minors. All three of my round-1 items are resolved, and so are QA-M1, QA-m1 and the P10 record. No new item is opened.

| Check | Result |
| :--- | :--- |
| `uv run pytest -q` | 363 passed, 0 failed, 28.99 s |
| `uv run pytest -q tests/test_unit/test_logging.py` | 39 passed |
| `uv run pytest -m live --collect-only -q` | 0 collected (363 deselected) |
| `uvx ruff check src tests --no-cache` | All checks passed. In scope: **0** (blocking). Pre-existing debt: **0** (deferred) |
| `uvx ruff format --check` on the five touched test and source files | 4 already formatted. `test_docs_consistency.py` would be reformatted, see §3 |

**Test count reconciled.** The totals were 360 in round 1 and are 363 now. The difference is `test_document_uses_no_forbidden_term`, which is parametrized over every file in `.agents/tasks/`, and `iteration-03/` now holds three review files. `test_logging.py` stays at 39: A-m3 removed one test, and QA-M1 added one. My round-1 expectations of 38 and 359 were wrong, as the implementer reported.

## 2. Verification of the fix round

| Item | Verified how | Result |
| :--- | :--- | :--- |
| A-m1 | `tests/test_unit/test_logging.py:654-656`: `subprocess.run(..., check=True, timeout=60)` | ✅ Resolved |
| A-m2 | `test_logging.py:93-105`. I ran the test function in-process with `SRC_DIR` pointed at a scratch directory, one probe module per case. Each of these fails: `getLogger(f"{__name__}")`, `getLogger(N)`, `getLogger(__spec__.name)`, `getLogger(__name__)`, `getLogger("__main__")`, and the keyword form `getLogger(name="src.x")`. `getLogger("src.tools")` passes. The only `getLogger` call in `src/` is the exempted `logging_setup.py:200` | ✅ Resolved |
| A-m3 | `test_src_child_loggers_are_routed_by_ancestry` is gone. `SRC_CHILD_LOGGER` (`:42`) is still used by 8 tests and by the `_stamp` helper | ✅ Resolved |
| QA-m1 | `src/logging_setup.py:109-110`: the docstring now warns that fields are filled one by one, so a caller naming a different `doc_id` should pass its `attempt` too. That is accurate for `filter` at `:116-118` | ✅ Resolved |
| QA-M1 | I checked it independently, without touching `src/`. I monkeypatched `src.logging_setup._ApiKeyRedactionFilter` with a factory that returns the real filter for the file handler and a pass-through filter for the stderr handler, which is mutation M24. The new test, `test_the_stderr_mirror_redacts_a_record_the_file_handler_never_sees` (`:417-441`), **fails** under M24 at `:439`, and passes unmutated. QA's stderr assertions in `test_redaction_still_applies_to_records_that_carry_correlation_fields` (`:407-414`) **survive** M24 | ✅ Resolved. The implementer's correction of QA's evidence is right |

**Why the correction holds.** `Logger.callHandlers` checks `record.levelno >= handler.level` before it calls `handler.handle()`, so a handler's filters run only when the record passes that handler's level. The file handler comes first in `handlers` (`logging_setup.py:192`), and its redaction filter rewrites `record.msg` in place (`:140`). So any record the file handler accepts is already masked when the stderr handler formats it.

The new test covers the one path that can leak under M24. It uses `configure_logging("ERROR", ...)` with a child logger at WARNING. The file handler (ERROR) never sees the record, and the stderr handler (WARNING) formats it. The test restores the child's level in `finally`, and it asserts the record is absent from the file, so it cannot pass vacuously. It adds a test beyond what `FIXES.md` specified, which §1.5 allows, and the implementer recorded that choice.

**`_ApiKeyRedactionFilter` is still verbatim.** I compared its AST, docstrings included, with `../code-orchestration/src/orchestrator.py`: identical. So are `ROUTED_LOGGERS`, `_MANAGED_HANDLER_FLAG` and `_REDACTION_PLACEHOLDER`. `_resolve_log_level` is identical once docstrings are stripped. `configure_logging` still differs by exactly the three amendments of round 1 §2.1:
* `Formatter(_LOG_FORMAT)`;
* the `run_` file name;
* `handler.addFilter(CorrelationFilter())`.

**P10 is consistent.**
* The plan (§2, row `:120`) and the spec (§8.3, row `:1031`) open with the same pinned statement, "API-key redaction stays Approach 1's", as `IMPLEMENTATION_DECISIONS["P10"]` requires (`test_docs_consistency.py:187`). Both rows cite Q7, 2026-09-29, with the user's reason.
* The §8.3 heading reads P1–P10, and so do `SPECIFICATIONS.md:4` and `:29`. The closing sentence now reads "as P11, P12".
* The traceability table has `P10 | 3` (`IMPLEMENTATION_PLAN.md:823`).
* No "P1 to P9" or "P1–P9" survives outside `.agents/tasks/`. The two remaining "P1 to P6" strings in the plan are correct. `:264` is Iteration 1's historical Red list, and `:819` is a traceability row covering P1 to P6 only.
* `QUESTIONS.md` Q7 records answer B and P10.

P10 does not contradict D-I's "the only suppression is masking the literal API key" (`SPECIFICATIONS.md:464`). That sentence bounds what is suppressed; P10 bounds where the key is masked. The code is now what P10 describes.

## 3. Code review findings

None in scope. Two observations, neither opened as an item:
* **The guard's message for the keyword form.** `test_logging.py:98` rejects `getLogger(name="src.x")` with the message "getLogger() without a name is the root logger". The rejection is correct, since literal-only is the rule. Only the message is imprecise, and no `src` module uses the keyword form.
* **Formatting debt in `tests/test_unit/test_docs_consistency.py`.** `ruff format --check` would rewrap the constant tuples and dicts at lines 61, 92, 102, 117, 140 and 292, and requote one string at 560. I formatted the HEAD version (`5b6ae08`) of the file under the project's `pyproject.toml`, and it gives the same 15 changed lines. So the debt predates this iteration, and none of it falls on the three lines this iteration changed (187, 692, 719). `ruff format` is not a §1.3 DoD gate. Deferred.

## 4. Anti-patterns and risks

Nothing new. The round-1 carry-forwards stand for the orchestrator:
* Iteration 14 must enter `log_context(run_id=…)` before `with HSEMockMCPClient(...)` (§2.2 of round 1).
* Iterations 7 to 11 need the `caplog` note (round 1 §4).
* Iteration 7 should correlate through the context manager, not through `extra=` (round 1 §4, now also stated in the `CorrelationFilter` docstring).

Under P10, the traceback gap noted in round 1 §4 is now a recorded, accepted limitation, not an open risk. No later iteration may widen the filter.

## 5. Remediation directives

None. Iteration 3 is architecturally clear to commit. The orchestrator should record these in `WALKTHROUGH.md`:
* P10;
* the QA-M1 evidence correction (M24 is killed only by the stderr-only record);
* round 1's decisions 1 to 8 and deviations 1 to 3.
