# Iteration 3 — Logging setup and correlation: walkthrough

**Date:** 2026-09-29 · **Branch:** `approach-2/implementation` · **Plan section:** `IMPLEMENTATION_PLAN.md` §5, Iteration 3

## 1. Overview

Iteration 3 moves Approach 1's logging out of its orchestrator into `src/logging_setup.py`, and adds the correlation that D-I requires.
* **One dated file per day,** `logs/run_YYYYMMDD.log`, as before.
* **Five routed loggers:** `strands`, `openai`, `httpx`, `mcp` and `src`, with `propagate = False`.
* **A WARNING-and-above mirror on stderr.**
* **API-key redaction.**
* **Correlation on every record:** `run_id`, `doc_id` and `attempt`, or `-` when a field is not set. `log_context(...)` sets them through a `contextvars` variable, and a `CorrelationFilter` on every handler stamps them.

The user's answer to Q7 became **P10**: redaction stays exactly as Approach 1 had it.

## 2. Files changed

| File | Status | Responsibility |
| :--- | :--- | :--- |
| `src/logging_setup.py` | New | Standard library only; imports nothing from `src`, and does nothing at import time |
| `tests/test_unit/test_logging.py` | New | 39 tests, run under `pytestmark = pytest.mark.usefixtures("restore_logging")` |
| `tests/test_unit/test_module_structure.py` | Edited | Adds `"src.logging_setup"` |
| `tests/conftest.py` | Edited | A stale comment now names `src.logging_setup` instead of `src.orchestrator`; no code changed |
| `.agents/docs/SPECIFICATIONS.md` | Edited | P10 row in §8.3; the range reads P1–P10; future decisions start at P11 |
| `tests/test_unit/test_docs_consistency.py` | Edited | P10 added to `IMPLEMENTATION_DECISIONS`; two docstrings updated |
| `AGENTS.md`, both review skills, `CLAUDE.md`, `.claude/agents/{architect,implementation,qa}.md` | Edited | "P1 to P10", one line each |
| `.agents/docs/IMPLEMENTATION_PLAN.md` | Edited by the orchestrator | P10 row in §2, a `P10 \| 3` traceability row, and the §3 tracker |
| `.agents/tasks/QUESTIONS.md` | Edited | Q7 raised and answered |

**What `src/logging_setup.py` contains:**
* **Moved from Approach 1's `orchestrator.py`, unchanged:** `ROUTED_LOGGERS`, `_MANAGED_HANDLER_FLAG`, `_REDACTION_PLACEHOLDER` and `_ApiKeyRedactionFilter`, docstring included. `_resolve_log_level` keeps its body; its docstring no longer claims that the specification writes `WARN`.
* **`configure_logging(level, log_dir, api_key=None) -> None`** keeps Approach 1's signature and handler set-up, with three amendments:
  * the file is named `run_YYYYMMDD.log`;
  * the format is `%(asctime)s %(levelname)-8s [run_id=… doc_id=… attempt=…] %(name)s: %(message)s`;
  * a `CorrelationFilter()` is added to each handler whether or not a key is given. The redaction filter is still added only when a key is given.
* **New:**
  * `LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")`, public so Iteration 14's CLI can use it;
  * `log_context(*, run_id=None, doc_id=None, attempt=None)`, a context manager;
  * `CorrelationFilter`, public so later tests can attach it to `caplog`'s handler;
  * the private `_CorrelationFields` NamedTuple and the `_CORRELATION` ContextVar, whose default is `_NO_CORRELATION`.

## 3. TDD record

| # | Behaviour | Red | Green |
| :---: | :--- | :--- | :--- |
| 1 | Approach 1's logging, moved and pointed at `src.logging_setup`. Also: one file per day, re-entrancy that keeps foreign handlers, an unknown level falling back to INFO, no redaction without a key, the stderr mirror | `ModuleNotFoundError: src.logging_setup`. Then, with the verbatim code still writing `pipeline_…`, 11 tests failed on the file name | The `run_` file name; `_resolve_log_level`'s docstring corrected |
| 2 | The four log levels, each set on all five loggers and on the file handler; stderr stays at WARNING even at DEBUG | `ImportError: LOG_LEVELS` | `LOG_LEVELS` |
| 3 | `log_context(run_id=…)` stamps records from the child loggers `strands.agent.agent`, `openai._base_client`, `httpx`, `mcp.client.stdio` and `src.tools`; `-` outside any context; every handler carries a `CorrelationFilter`, and no logger does | `ImportError: CorrelationFilter` | `CorrelationFilter` and `log_context` |
| 4 | Nesting adds fields and restores the outer values, even when the block raises; an explicit `extra=` overrides the context; nothing leaks into an unrelated thread | 4 failures: `AttributeError: … no attribute 'doc_id'`, and `TypeError: … unexpected keyword argument 'doc_id'` | The keyword-only signature and `ContextVar.set` / `reset(token)` in `try/finally`. The unknown-field test passed at once, because the signature already rejects unknown names; it pins that guarantee |
| 5 | Every header line in the file and on stderr has all three fields; a traceback follows verbatim under its header; redaction still works on correlated records | 5 failures on lines that read `[run_id=-]` | The correlated format |

**Mutation check.** Moving `CorrelationFilter` from the handlers onto the loggers made 10 tests fail.

**Fix round 1:**
* **A-m2.** The logger-name guard now requires a string literal under a routed logger. The only exemption is the loop over `ROUTED_LOGGERS` in `logging_setup.py`.
  * **Red:** a temporary probe module using `getLogger(f"{__name__}")`, a variable and `__spec__.name` passed the old guard.
  * The probe was deleted afterwards.
* **A-m3.** The tautological `test_src_child_loggers_are_routed_by_ancestry` was deleted.
* **A-m1.** The subprocess in the no-side-effects test now has `timeout=60`.
* **QA-M1.** New test: `test_the_stderr_mirror_redacts_a_record_the_file_handler_never_sees`.
  * **Red:** mutation M24, in which only the file handler redacts, survived the existing tests. It also survived the stderr assertions QA first proposed.
  * **Why:** the filter rewrites `record.msg` in place and the file handler runs first, so a record the file handler accepts is already masked by the time stderr formats it. M24 can leak only a record that reaches stderr but not the file.
  * **The test builds exactly that case.** It configures at ERROR, sets `openai._base_client` to WARNING, logs a WARNING carrying the key, and asserts the key is absent from stderr and that the record is absent from the file.
  * **Result:** it fails under M24 and passes on the real code. QA's assertions were kept too; they catch M24 with the handler order swapped.
* **QA-m1.** The `CorrelationFilter` docstring now says that a record naming its own `doc_id` through `extra=` still inherits `attempt` from the context.
* **P10.**
  * **Red:** adding P10 to `IMPLEMENTATION_DECISIONS` failed the two §8.3 tests.
  * **Green:** the §8.3 row and the range updates.

## 4. Test results

A fresh run at the checkpoint, after this walkthrough was written:

| Command | Result |
| :--- | :--- |
| `uv run pytest -q` | **364 passed**, 0 failed |
| `uv run pytest tests/test_unit/test_logging.py` | 39 passed |
| Tests added by this iteration | 39 logging tests, plus the forbidden-term check on this iteration's four new records |
| `uvx ruff check src tests --no-cache` | `All checks passed!` |

`ruff format --check` would reformat some files that earlier iterations committed. Formatting is not a DoD gate, so this is left.

## 5. Acceptance criteria

| # | Criterion | Result | Evidence |
| :---: | :--- | :---: | :--- |
| 1 | The logging tests pass, copied and new | ✅ | 39 passed: 14 adapted from Approach 1, 25 new |
| 2 | One file per day, `run_YYYYMMDD.log` | ✅ | `test_configure_logging_writes_one_file_per_day` configures twice and finds exactly `run_{today}.log`, and no `pipeline_*` |
| 3 | The five routed loggers keep `propagate = False` | ✅ | `test_configure_logging_writes_to_the_dated_run_log` asserts it on all five. `test_routed_loggers_are_approach_1s_five` pins the tuple |

Definition of Done:
* **DoD-1** ✅, **DoD-2** ✅, **DoD-5** ✅ and **DoD-6** ✅ (this file).
* **DoD-3** ✅: no model or HTTP client is built, and every third-party record is emitted by hand through `logging.getLogger(name)`.
* **DoD-4** ✅: every branch of `logging_setup.py` has a test, including the stderr level, the missing key and the unknown level.

## 6. Decisions and deviations

**Decisions (§1.5):**
* **`log_context` signature.** It is keyword-only: `log_context(*, run_id, doc_id, attempt)`. Calls look like the plan's `log_context(**fields)`, but an unknown name raises `TypeError`.
  * `None` means "inherit from the enclosing context".
  * The state is one `ContextVar` holding an immutable NamedTuple, which is safe when Strands copies the context into its threads (`strands/_async.py`, and the MCP client's background thread).
* **`extra=` wins.** `CorrelationFilter` sets only the fields a record does not already carry.
* **Logger naming.** Every `src` module takes its logger by an explicit literal name, `"src.<module>"`, never `__name__`. An AST scan of `src/*.py` enforces this. `logging_setup.py` emits no records, so it has no `_LOGGER`.
* **"Every line carries `run_id`."** This is read as every record's header line. Tracebacks and multi-line bodies follow verbatim, never folded, and a test pins this.
* **Tests.**
  * `restore_logging` applies to the whole file.
  * `REPO_ROOT` is defined in the test module.
  * The no-side-effects test uses a fresh subprocess plus an AST check, instead of `importlib.reload`.
* **Ruff B039.** The `ContextVar` default is bound to the named constant `_NO_CORRELATION`.

**Deviations from the plan:**
* **Tests from `test_orchestrator.py`.** AC3 says "as the copied test asserts", but Approach 1's `test_logging.py` has no `propagate` assertion. So the 7 pure `configure_logging` tests in Approach 1's `tests/test_integration/test_orchestrator.py` were also adapted, without that file's strands, openai and httpx imports:
  * `WARN` mapping;
  * the dated file;
  * provider routing;
  * DEBUG detail;
  * redaction of only the key;
  * clean stdout;
  * no import side effects.

  D-J excludes that file because it asserts a fixed sequence, which these tests don't. The dated-file test now asserts `propagate` on all five loggers, not only `strands`.
* **Not moved.** The plan lists "the name of the `src` logger" to move, but `PIPELINE_LOGGER_NAME` (`"src.orchestrator"`), `_LOGGER` and Approach 1's `REPO_ROOT` were not moved. They name a module that doesn't exist here; the naming rule above replaces them.
* **Dropped.** `test_log_file_naming_constant_is_a_path_helper` guarded the orchestrator's `REPO_ROOT` and file, neither of which exists here.

**The answer recorded: Q7, option B, which became P10.** `_ApiKeyRedactionFilter` masks the key in the formatted message only. The user chose to keep it that way: this is a proof of concept, and sensitive data may be logged for audit.
* **The known limitation:** an exception traceback or stack text is written in full, even when it contains the key.
* No later iteration widens the redaction.

**Forward notes:**
* **Iterations 7 to 11:**
  * `caplog` does not see the correlation fields. Assert on the log file, or call `caplog.handler.addFilter(CorrelationFilter())`.
  * Correlate through `log_context`, not `extra=`.
  * Set `doc_id` and `attempt` together, so a stale outer `attempt` is never inherited.
* **Iteration 14:**
  * Enter `log_context(run_id=…)` **before** `with HSEMockMCPClient()`. The MCP background thread copies the context once, when the session starts.
  * Use `LOG_LEVELS` as the CLI's `choices=`.
* **Informational:**
  * The `WARN` alias is redundant on Python 3.11, and is kept for parity.
  * `getLogger(name="src.x")` is correctly rejected by the guard, but its message wrongly says the call has no name.
* **Still carried from Iteration 2:** F1 to F6, which apply to Iterations 4, 6 and 7.

## 7. Review

**Two rounds were used.**

| Round | Reviewer | Verdict | Findings | Resolution |
| :---: | :--- | :--- | :--- | :--- |
| 1 | Architect | APPROVED WITH RESERVATIONS | **A-m1:** the subprocess had no timeout. **A-m2:** the logger-name guard was too loose. **A-m3:** one test could not fail. All minor. Ruff: 0 in scope, 0 pre-existing | Fixed in fix round 1 |
| 1 | QA | CHANGES REQUIRED | **QA-M1 (major):** stderr redaction was untested. **QA-m1:** a docstring gap. **Q7:** the key can appear in tracebacks | QA-M1 was fixed with a new test, and its evidence corrected (see §3). QA-m1 was fixed. Q7 went to the user, who chose B, recorded as P10 |
| 2 | Architect | APPROVED | None. `_ApiKeyRedactionFilter` is still verbatim, and P10 is consistent across the plan, the specification and the test | — |
| 2 | QA | PASSED | None. QA confirmed M24 independently: only the new test catches it. QA also corrected its round-1 account of M24 | — |
