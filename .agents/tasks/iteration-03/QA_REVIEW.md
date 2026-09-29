# QA Review — Iteration 3: Logging setup and correlation (round 1)

**Reviewer:** QA and Verification Agent · **Date:** 2026-09-29 · **Branch:** `approach-2/implementation` (uncommitted working tree)

## 1. Summary and verdict

**Verdict: CHANGES REQUIRED**

Iteration 3 delivers what `IMPLEMENTATION_PLAN.md` §5 promises. `src/logging_setup.py` moves Approach 1's logging verbatim, with the three planned amendments: the `run_` file name, the correlated line format, and a `CorrelationFilter` on every handler. `tests/test_unit/test_logging.py` carries over Approach 1's logging tests and adds the correlation tests. All three acceptance criteria hold, and so do DoD-1 to DoD-5. DoD-6 is the orchestrator's checkpoint step.

I ran every check myself. I ran a 25-mutation probe on a scratch copy outside the repository; §4 has the results.

One major finding keeps this from PASSED: **no test asserts that the stderr mirror is redacted.** If redaction were limited to the file handler, all 39 tests would still pass (mutation M24). The code redacts stderr correctly today. The gap is in the tests only. *Corrected in round 2 (§7.1): under M24 the key reaches stderr in clear only for a record the file handler rejects, and the "few assertion lines" I proposed do not catch M24.*

I also opened one "Needs a decision" item. The inherited `_ApiKeyRedactionFilter` masks only `getMessage()`, so a key inside exception text reaches the log in clear. I proved this with a probe. The implementer disclosed it and kept it for parity; closing it would change a component the plan says to move verbatim.

I concur with the architect's three minors, A-m1 to A-m3, and do not duplicate them. My probe independently confirms A-m2.

### Commands run and real output

| Command | Real result |
| :--- | :--- |
| `uv run pytest -q` (at the start of review) | `360 passed in 27.65s`. This matches the report: the 321 of Iteration 2 plus 39 |
| `uv run pytest -q` (later in review) | `362 passed in 27.21s`. The two extra tests are `test_document_uses_no_forbidden_term` cases for the architect's `ARCHITECT_REVIEW.md` and `FIXES.md`, which landed during my review. This `QA_REVIEW.md` adds one more. The implementer's count was right when it was reported; see QA-i1 |
| `uvx ruff check src tests --no-cache` | `All checks passed!` |
| `uvx ruff format --check src/logging_setup.py tests/test_unit/test_logging.py --no-cache` | `2 files already formatted` |
| `uv run pytest tests/test_unit/test_logging.py -q -W error` | `39 passed in 0.45s`. No warning escalated to an error |
| `uv run pytest -q -rw`, grepped for `warn` | No warning lines |
| `uv run pytest tests/test_unit/test_docs_consistency.py -q` | `187 passed` at the start of review (189 after the architect's files) |
| `uv run pytest -m live --collect-only -q` | `no tests collected (360 deselected)`. This was the only live command I ran |
| Side-by-side read of `../code-orchestration/src/orchestrator.py` lines 135-141 and 1233-1325 against `src/logging_setup.py` | `ROUTED_LOGGERS`, `_MANAGED_HANDLER_FLAG`, `_REDACTION_PLACEHOLDER`, the `_ApiKeyRedactionFilter` body and the `_resolve_log_level` body are identical. `configure_logging` differs in exactly three places: the formatter string (line 181), the `run_` file name (line 183) and `handler.addFilter(CorrelationFilter())` (line 193) |
| Process list (`Get-CimInstance Win32_Process`, `python.exe` and `uv.exe`) after the runs | Every process predates this iteration. They are the harness's `hse-easy-mock` and `strands-agents` MCP servers, started 2026-09-28 19:55 and 20:09 and 2026-09-29 00:25. The suite orphaned nothing |
| `ls logs drafts` after the runs | `.gitkeep` only. Every test writes to `tmp_path` |

I wrote nothing inside `../code-orchestration/` or the repository, apart from this folder. The mutation probes ran on a copy under the session scratchpad and imported the copy's `src`, which I checked through `src.logging_setup.__file__`.

## 2. Gate matrix

| Gate | Topic | Status | Notes |
| :--- | :--- | :---: | :--- |
| 1 | Strict TDD | ✅ | **Red steps.** The report gives a Red for each of the five behaviours, each for the expected reason: `ModuleNotFoundError`, then `ImportError` on `LOG_LEVELS` and `CorrelationFilter`, then `AttributeError`/`TypeError` on `doc_id`, then format assertions. Green step 1 fails on the file name, as the plan intends. `test_log_context_rejects_an_unknown_field` passed without a Red, which the report discloses: it pins a signature guarantee. **Coverage.** Every function and branch in `src/logging_setup.py` runs under test. 22 of 23 behavioural mutations are killed (§4). M22 survives because it is equivalent: Python 3.11's `logging.getLevelName("WARN")` already returns `30` (QA-i2). The architect's A-m3, a test that cannot fail, is the only weak test I agree with |
| 2 | Zero-token testing | ✅ | `test_logging.py` imports only the stdlib, `pytest` and `src.logging_setup`, and builds no model, agent or HTTP client; every third-party record is emitted by hand. `src/logging_setup.py` imports nothing from `src` or any third party. The autouse `_isolate_environment` fixture is unchanged. `addopts = "-m 'not live'"` holds, and there are 0 `live` tests. `model_builder` is n/a until Iteration 7 |
| 3 | Pydantic v2 contracts | n/a in this iteration | No model was added or changed. `_CorrelationFields` is a private `NamedTuple` that never crosses a module boundary |
| 4 | Guardrails and attempt cap | n/a in this iteration | |
| 5 | Strands integration and telemetry | n/a in this iteration | I did check the context-variable choice against installed `strands-agents` 1.55.1. `strands/tools/mcp/mcp_client.py:456-457` starts the MCP background thread under `contextvars.copy_context()`. `strands/_async.py:43` copies the context into its executor. So the module docstring's claim holds, provided `log_context(run_id=…)` is entered before the MCP client starts, as the report plans for Iteration 14 |
| 6 | No article text for the Supervisor | n/a in this iteration | |
| 7 | Drafts and logging | ❌ (a test gap only) | **Holds:** one file per day, `run_YYYYMMDD.log` (AC2; M08 killed). `[run_id=… doc_id=… attempt=…]` is on every record's header line in the file and on stderr, reading `-` outside a context (M01, M02, M07, M10 killed). `propagate = False` on all five loggers (M09 killed). The file is redacted on correlated records, with and without a key (M12 killed). **Fails:** redaction of the stderr mirror is unasserted (QA-M1, M24 survives), and exception text is not redacted at all (QA-D1). No D-I catalogue event is implemented yet, so none is asserted; the first are in Iterations 7 to 11 |
| 8 | Python and subprocess safety | ✅ | Full PEP 484/585/604 annotations, `Final` constants, imports at the top, `pathlib.Path` throughout. **Resources.** `restore_logging` closes and removes every handler a test adds and restores `level` and `propagate`. My per-test leak probe (§4) found 0 leaked handlers, 0 changed `propagate` flags and 0 correlation contexts left set, across all 39 tests. The same probe reports 29 leaks when the fixture is removed, so it can detect them. **Processes.** The one subprocess, in the no-side-effects test, finishes and orphans nothing; the architect's A-m1 adds its missing `timeout=` |

## 3. Acceptance criteria, Red list and Definition of Done

**Acceptance criteria: 3 of 3 pass.**

| # | Criterion | Status | Evidence |
| :---: | :--- | :---: | :--- |
| AC1 | The logging tests pass, both the copied and the new ones | ✅ | `tests/test_unit/test_logging.py`: 39 passed. Carried over from Approach 1: 7 of 8 tests from its `test_unit/test_logging.py`, repointed, and 7 pure `configure_logging` tests from its `test_integration/test_orchestrator.py`. That makes 14, as the report says; the other 25 are new. The one test dropped, `test_log_file_naming_constant_is_a_path_helper`, is a recorded deviation. It tested Approach 1's `REPO_ROOT`, which does not move |
| AC2 | A test run writes one file per day, `run_YYYYMMDD.log` | ✅ | `test_configure_logging_writes_one_file_per_day` configures twice and asserts `sorted(log_dir.glob("*.log")) == [log_dir / f"run_{date.today():%Y%m%d}.log"]`. Mutation M08 (`pipeline_`) fails 10+ tests |
| AC3 | The five routed loggers keep `propagate = False` | ✅ | `test_configure_logging_writes_to_the_dated_run_log` asserts it on all five, not just on `strands` as Approach 1 did. Mutation M09 (`propagate = True`) fails it |

**Red list: all 6 bullets covered by a test that fails when the behaviour breaks.**

| Red bullet (`IMPLEMENTATION_PLAN.md` §5, Iteration 3) | Status | Tests, and the mutations that prove them |
| :--- | :---: | :--- |
| Copy Approach 1's logging tests, repointed; expect `run_YYYYMMDD.log` | ✅ | See AC1. M08 is killed |
| `log_context(run_id=…)` puts `run_id` on every record, including from `strands`, `httpx` and `mcp`; filter on the handler | ✅ | `test_log_context_puts_run_id_on_records_from_every_routed_logger` uses child loggers (`strands.agent.agent`, `openai._base_client`, `mcp.client.stdio`). `test_every_handler_carries_a_correlation_filter` is parametrized with and without a key. M01 (no filter), M02 (filter on the loggers) and M23 (filter only with a key) are each killed |
| Nested `log_context(doc_id=…, attempt=…)` adds fields, and leaving restores the outer values; `-` outside every context | ✅ | Tests for nesting, exit by exception, `extra=` precedence and thread isolation. M03 (no reset), M04 (reset only on normal exit), M05 (no inheritance), M06 (`extra=` overwritten), M07 (`None` instead of `-`), M13 (module global instead of `ContextVar`) and M20 (`attempt` as `str`) are each killed |
| The file format includes `run_id`, `doc_id` and `attempt` on every line | ✅ | `test_every_line_in_the_file_and_on_stderr_carries_the_three_fields` checks every header line in both outputs with a strict regex. The traceback test pins the reading "every record's header line", decision 4; see QA-i3. M10 is killed |
| `--log-level` accepts `DEBUG`, `INFO`, `WARNING` and `ERROR` | ✅ | `LOG_LEVELS` is pinned. Each level resolves and is applied to all five loggers and to the file handler. stderr stays at WARNING. M16, M17, M18 and M11 are killed |
| Approach 1's redaction test still passes on records carrying correlation fields | ✅ for the file · ❌ for stderr | `test_redaction_still_applies_to_records_that_carry_correlation_fields` is parametrized with and without a key and checks a record without the key too. It reads the file only. M12 is killed, **M24 survives**: QA-M1 |

**Definition of Done**

| # | Check | Status | Evidence |
| :---: | :--- | :---: | :--- |
| DoD-1 | Full default suite passes | ✅ | 360 passed at review start, 362 after the architect's files; 0 failed, 0 errors |
| DoD-2 | Lint is clean | ✅ | `All checks passed!` |
| DoD-3 | No live model call | ✅ | See Gate 2 |
| DoD-4 | Every new `src/` function is exercised by a test | ✅ | `log_context`, `CorrelationFilter.filter`, `configure_logging` and `_resolve_log_level` (including the unknown-level branch) all run under assertion. The one surviving behavioural mutant is equivalent (QA-i2) |
| DoD-5 | Docs match code | ✅ | `test_docs_consistency.py`: 187 passed (189 once the architect's files landed) |
| DoD-6 | `WALKTHROUGH.md` written | Pending | The orchestrator's step 8. It must carry QA-i1 and QA-i3 |

## 4. Mutation probe

I applied each mutation to a scratch copy of `src/logging_setup.py`, ran `tests/test_unit/test_logging.py`, and restored the file. The copy was verified byte-identical to the repository's afterwards.

| # | Mutation | Result |
| :---: | :--- | :--- |
| M01 | No `CorrelationFilter` on the handlers | killed (many tests) |
| M02 | Filter on the loggers instead of the handlers | killed |
| M03 | `log_context` never resets | killed (4) |
| M04 | Reset only on normal exit, no `finally` | killed (2) |
| M05 | Inner context does not inherit the outer fields | killed (2) |
| M06 | Filter overwrites fields passed with `extra=` | killed (1) |
| M07 | Unset fields read `None` instead of `-` | killed |
| M08 | File named `pipeline_…` | killed |
| M09 | `propagate = True` | killed (1) |
| M10 | Format without `doc_id` and `attempt` | killed (4) |
| M11 | stderr handler at the configured level | killed (2) |
| M12 | Redaction on the stderr handler only | killed (3) |
| M13 | Module global instead of `ContextVar` | killed (1: the thread test) |
| M14 | Replaced handlers not closed | killed (1) |
| M15 | Foreign handlers removed too | killed (1) |
| M16 | `LOG_LEVELS` without `DEBUG` | killed |
| M17 | Unknown level resolves to `WARNING` | killed (1) |
| M18 | File handler level ignores the setting | killed |
| M19 | `mcp` dropped from `ROUTED_LOGGERS` | killed (5) |
| M20 | `attempt` stamped as a `str` | killed (2) |
| M21 | Filter drops records below WARNING | killed (many) |
| M22 | `WARN` alias removed from `_resolve_log_level` | **survived: equivalent** (QA-i2) |
| M23 | `CorrelationFilter` only when a key is given | killed |
| M24 | Redaction filter on the file handler only | **survived** (QA-M1). *Round 2 correction: stderr is unredacted only for a record the file handler rejects by level; see §7.1* |
| AST | A scratch `src/zz_probe.py` with `getLogger(__name__)`, `getLogger()`, `getLogger("hse.tools")`, `from logging import getLogger; getLogger(__name__)`, `getLogger(name=__name__)` | all 5 caught. `getLogger(f"{__name__}")` slips through, which confirms the architect's A-m2 |

**Leak probe.** An autouse fixture in the scratch `conftest.py` compared each routed logger's handlers, `propagate` and `level`, and the correlation context variable, before and after every test. With `restore_logging` in place it reported **0 leaks in 39 tests**. With the module's `pytestmark` removed it reported 29, so it does detect leaks.

**Traceback probe.** I configured logging with `api_key="sk-live-0123456789abcdefSECRET"`, raised `RuntimeError(f"AuthenticationError: bad key {KEY}")` inside `log_context`, and logged it with `.exception(...)`. Output: `KEY IN FILE: True`, on the line `RuntimeError: AuthenticationError: bad key sk-live-0123456789abcdefSECRET`. See QA-D1.

## 5. Findings by severity

**🔴 Blocker:** none.

**🟡 Major: 1.**
* **QA-M1: the stderr mirror's redaction is unasserted.** D-I mirrors WARNING and worse to stderr, which is where provider ERRORs, the records most likely to carry a key, land on the terminal. `configure_logging` does add the redaction filter to both handlers (`src/logging_setup.py:191-195`). But no test reads stderr with a key configured, so M24 passes all 39 tests. The fix is test-only; see `FIXES.md`. *Round 2 correction: the stderr assertions I proposed there are necessary but not sufficient; §7.1 explains why and records the test that does kill M24.*

**🟢 Minor: 1.**
* **QA-m1: `extra=` can pair one document with another's attempt.** `test_an_explicit_extra_field_overrides_the_context` asserts `("run-7f3a", "eu-2024-1234", 1)`. There, `doc_id` comes from `extra=` and `attempt=1` from the `inail-…` context, so the line shows an attempt number that belongs to a different document. The behaviour is a legitimate §1.5 choice (decision 2). It should be documented, so that Iterations 7 to 11 pass `doc_id` and `attempt` together. A docstring line is enough; see `FIXES.md`.

**Needs a decision: 1.**
* **QA-D1: exception and stack text are not redacted.** Inherited verbatim from Approach 1 and disclosed in the report. The plan moves `_ApiKeyRedactionFilter` verbatim, while D-I says "the only suppression is masking the literal API key" and Gate 7 says "API keys are redacted". The sources do not settle whether to amend the filter now; see `FIXES.md` under "Needs a decision".

**Informational (no action beyond the walkthrough):**
* **QA-i1: the counts move under the review artifacts.** 360 was right when the report was written. With the architect's two files it is 362, and this file makes it 363. If A-m3 is applied, subtract 1. Any QA-M1 fix that edits an existing test adds nothing. Take the walkthrough's full-suite count from a final `uv run pytest -q` after the fix round.
* **QA-i2: the `WARN` alias branch is equivalent code.** `logging.getLevelName("WARN")` returns `30` on Python 3.11.16, so `"WARNING" if level.upper() == "WARN" else …` changes nothing. It is Approach 1's body, kept verbatim for parity; leave it.
* **QA-i3: the walkthrough must record two points.**
  * Deviation 2. The plan's Green says to move "the name of the `src` logger", but `PIPELINE_LOGGER_NAME` was not moved. The literal-name rule and the AST guard replace it; its value, `"src.orchestrator"`, names a module Approach 2 does not have.
  * Decision 4. "Every line" is read as every record's header line, with traceback lines verbatim beneath it, per D22's full fidelity. A `grep run_id=…` therefore finds the header of a multi-line record, not its continuation lines. That reading is defensible and pinned by `test_a_traceback_is_written_in_full_under_its_correlated_header`.

## 6. Remediation

Exact instructions are in `.agents/tasks/iteration-03/FIXES.md`, under `## 🧪 QA & Verification` (QA-M1, QA-m1) and `## ❓ Needs a decision` (QA-D1). Nothing in `src/` needs to change for QA-M1 or QA-m1, apart from the one docstring line QA-m1 suggests.

---

# Round 2: fix-round re-review

**Reviewer:** QA and Verification Agent · **Date:** 2026-09-29 · **Scope:** QA-M1, QA-m1, Q7 → P10, and the architect's A-m1 to A-m3

## 7. Summary and verdict

**Verdict: PASSED**

All five round-1 items are resolved, and P10 is recorded and pinned. I re-ran every check myself. The implementer's correction of my M24 account is right; §7.1 gives my independent reproduction. No new findings. Nothing new goes into `FIXES.md`.

### Commands run and real output

| Command | Real result |
| :--- | :--- |
| `uv run pytest -q` | `363 passed in 27.64s`. This matches the report. Arithmetic: 363 at the end of round 1 (QA-i1), minus 1 for A-m3, plus 1 for the new stderr test. The 39 logging tests are 39 − 1 + 1 |
| `uvx ruff check src tests --no-cache` | `All checks passed!` |
| `uv run pytest tests/test_unit/test_logging.py -q -W error` | `39 passed in 0.51s` |
| `uv run pytest -q -rw`, grepped for `warn` | No warning lines |
| `uv run pytest tests/test_unit/test_docs_consistency.py -q` | `190 passed` |
| `uv run pytest -m live --collect-only -q` | `no tests collected (363 deselected)`. This was the only live command I ran |
| `uvx ruff format --check src tests --no-cache` | `9 files would be reformatted`. `test_docs_consistency.py` fails the check at `HEAD` too, so this predates Iteration 3. It is not a DoD gate (QA-i5) |
| `sed`-extracted `_ApiKeyRedactionFilter` and `_resolve_log_level` bodies, `diff`ed against `../code-orchestration/src/orchestrator.py` | Both identical. P10's "moved verbatim" holds |
| Process list (`python.exe`, `uv.exe`) | Every process predates the iteration (2026-09-28 19:55 and 20:09, 2026-09-29 00:25). None was orphaned |
| `git status --short`, `ls logs drafts`, `sha256sum src/logging_setup.py` | No change outside this folder. `logs/` and `drafts/` hold `.gitkeep` only. `src/logging_setup.py` is byte-identical before and after my probes |

All probes ran on copies under the session scratchpad and imported the copy's `src` (checked through `src.logging_setup.__file__`).

### 7.1 Correction of my round-1 M24 account

I agree with the implementer's analysis. My round-1 claim went too far. I wrote that under M24 "the key would reach stderr in clear" and that "a few assertion lines" reading stderr would fix the gap. Neither is right in general.

* **The mechanism.** `_ApiKeyRedactionFilter.filter` rewrites `record.msg` and clears `record.args` in place. `Logger.callHandlers` gives the same record object to the handlers in order, file handler first. So once the file handler's filter has run, stderr formats a record that is already masked.
* **When M24 leaks.** Under M24, a key reaches stderr in clear only for a record that stderr accepts and the file handler rejects by level. That happens when the configured level is above WARNING and a child logger has its own lower level. For example: `--log-level ERROR`, with a WARNING from `openai._base_client` set to WARNING.
* **Why round 1's M24 result stands.** M24 did survive all 39 tests. The finding, stderr redaction untested, was real. Only the explanation and the proposed fix were wrong.

**My reproduction.** I applied each mutation below to a scratch copy and ran `tests/test_unit/test_logging.py`:

| Mutation | Result | Killed by |
| :--- | :--- | :--- |
| none (baseline) | `39 passed` | |
| **M24**: redaction on the file handler only | `1 failed, 38 passed` | `test_the_stderr_mirror_redacts_a_record_the_file_handler_never_sees` only. So the stderr assertions I proposed, now in `test_redaction_still_applies_to_records_that_carry_correlation_fields`, pass under M24, as the implementer said |
| **M24b**: M24, with the handler order swapped to stderr first | `2 failed, 37 passed` | the new test, and `test_redaction_still_applies_…[sk-live-…]`. The added stderr assertions earn their place: they guard a change of handler order |
| **SWAP**: handler order swapped, redaction on both | `39 passed` | Correct. This is not a defect, and nothing should fail |
| **M12**: redaction on stderr only | `3 failed, 36 passed` | as in round 1 |

The new test cannot pass vacuously. It asserts `"Retrying request" not in _read_log(log_dir)`, which proves that the record bypassed the file handler, the precondition for the leak. It restores the child logger's level in a `finally`. It also asserts that the rest of the line is kept in full: `api-key=[REDACTED] status=429 request_id=req_abc123`, per D22's full fidelity. Adding a test beyond `FIXES.md`'s instructions is a sound §1.5 choice, and the report discloses it.

### 7.2 Round-1 items

| Item | Status | Evidence |
| :--- | :---: | :--- |
| **QA-M1**: stderr redaction untested (major) | ✅ resolved | See §7.1. M24 and M24b are both killed now |
| **QA-m1**: `CorrelationFilter` docstring | ✅ resolved | `src/logging_setup.py:109-110`: "a caller naming a different `doc_id` should pass its `attempt` too, or the line pairs that document with the enclosing context's attempt". `_ApiKeyRedactionFilter` is untouched |
| **Q7 → P10**: traceback redaction | ✅ recorded | `QUESTIONS.md` Q7 is answered B and marked resolved. The P10 row is in `IMPLEMENTATION_PLAN.md` §2 (line 120) and its iteration map (P10 → 3), and in `SPECIFICATIONS.md` §8.3 (line 1031), citing Q7. The status line, the contents row and the §8.3 heading say P1 to P10, and the closing sentence says "P11, P12". A sweep for the old P1-to-P9 range, in all three spellings, outside `.agents/tasks/` finds nothing |
| **P10 pin** | ✅ | `IMPLEMENTATION_DECISIONS["P10"]` pins the statement. Drift probes on a scratch copy: rewording the §8.3 statement fails `test_implementation_decisions_open_with_the_same_statement_in_both_records[SPECIFICATIONS.md §8.3]`. Deleting the §8.3 row also fails `test_specification_records_every_implementation_decision_in_order`. Rewording the plan's §2 statement fails the `[IMPLEMENTATION_PLAN.md §2]` case. Each probe added exactly the expected failures over the scratch baseline, whose 9 failures come from the sibling `../` paths the copy cannot resolve |
| **A-m1**: subprocess timeout | ✅ resolved | `test_logging.py:655`: `check=True, timeout=60` |
| **A-m2**: logger-name guard, literal only | ✅ resolved | I put a scratch `src/zz_probe.py` in the copy and ran the guard against it. It **fails**, as it should, on each of: `getLogger(f"{__name__}")`, `getLogger(NAME)` bound to `"src.x"`, `getLogger(__spec__.name)`, `getLogger("__main__")`, `getLogger()`, `getLogger(__name__)`, `getLogger("hse.tools")`, and a module-level `name` variable outside `logging_setup.py`. It **passes** `getLogger("src.tools")`. The exemption is scoped to the file and the argument text, and the docstring names it |
| **A-m3**: tautological test | ✅ resolved | `test_src_child_loggers_are_routed_by_ancestry` is gone. `SRC_CHILD_LOGGER` stays, used by 8 tests |

### 7.3 Gate matrix (round 2)

| Gate | Topic | Status | Notes |
| :--- | :--- | :---: | :--- |
| 1 | Strict TDD | ✅ | The report gives a Red for each fix: M24 survives, then survives with the added assertions, then fails against the new test; the A-m2 probe passes the old guard; the P10 docs tests fail at 2. I reproduced the M24 Reds and the guard's behaviour myself |
| 2 | Zero-token testing | ✅ | Unchanged from round 1. There are no new imports and 0 `live` tests |
| 3 | Pydantic v2 contracts | n/a in this iteration | |
| 4 | Guardrails and attempt cap | n/a in this iteration | |
| 5 | Strands integration and telemetry | n/a in this iteration | |
| 6 | No article text for the Supervisor | n/a in this iteration | |
| 7 | Drafts and logging | ✅ | Stderr redaction is now asserted, both for records the file handler also takes and for records that reach stderr alone. Exception-text redaction is out of scope by decision P10 |
| 8 | Python and subprocess safety | ✅ | The subprocess has a timeout (A-m1). No leaked processes, clean `-W error` run |

### 7.4 Acceptance criteria and Definition of Done (round 2)

**Acceptance criteria: 3 of 3 pass.** AC1: the logging tests pass, 39 of 39. AC2: `test_configure_logging_writes_one_file_per_day` is unchanged and passes. AC3: `propagate = False` is asserted on all five loggers and passes. The Red list's sixth bullet, "Approach 1's redaction test still passes on records carrying correlation fields", is now ✅ for both the file and stderr.

| # | Check | Status | Evidence |
| :---: | :--- | :---: | :--- |
| DoD-1 | Full default suite passes | ✅ | `363 passed` |
| DoD-2 | Lint is clean | ✅ | `All checks passed!` |
| DoD-3 | No live model call | ✅ | Gate 2 |
| DoD-4 | Every new `src/` function is exercised by a test | ✅ | No new `src/` code in this round; only a docstring |
| DoD-5 | Docs match code | ✅ | `test_docs_consistency.py`: 190 passed, P10 pinned in both records |
| DoD-6 | `WALKTHROUGH.md` written | Pending | The orchestrator's step. Besides QA-i1 and QA-i3, it should record the §7.1 mechanism, P10 as a known limitation (tracebacks and stack text are unredacted by decision), and that the full-suite count is 363 |

### 7.5 Findings (round 2)

**🔴 Blocker:** none. **🟡 Major:** none. **🟢 Minor:** none.

**Informational (no action):**
* **QA-i4: the guard's message for a keyword argument is misleading.** `getLogger(name="src.x")` is rejected, which is safe, with the message "getLogger() without a name is the root logger". No `src` module uses the keyword form, and rejecting it matches the literal-only rule, so it needs no change.
* **QA-i5: `ruff format --check` is not clean, and was not clean before this iteration.** 9 files would be reformatted, including `test_docs_consistency.py`, which fails the check at `HEAD` as well. The DoD gate is `ruff check`, which is clean. A formatting pass would be a separate housekeeping change, outside Iteration 3's scope.
