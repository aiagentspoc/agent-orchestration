# QA Review — Iteration 0: Packaging and scaffolding (round 1)

**Reviewer:** QA and Verification Agent · **Date:** 2026-09-28 · **Branch:** `approach-2/implementation` (uncommitted working tree)

## 1. Summary and verdict

**Verdict: PASSED**

The packaging and scaffolding match `IMPLEMENTATION_PLAN.md` Iteration 0 and the Definition of Done. I ran every check myself, and each claim in the implementer's report holds: 16 passed, ruff clean, no live call, the lock matches Approach 1's pins, and `strands-agents` 1.55.1 is installed. There are no blocker or major findings, only two minor items, both non-blocking. One is a forward note for a later iteration.

### Commands run and real output

| Command | Real result |
| :--- | :--- |
| `uv run pytest -q` | `16 passed in 1.94s`, rc 0 |
| `uv run pytest -v -rA -W error` | `16 passed in 2.02s`. With warnings promoted to errors there are still no failures, so no warnings are emitted |
| `uvx ruff check src tests --no-cache` | `All checks passed!`, rc 0 |
| `uv run pytest -m live --collect-only -q` | `no tests collected (16 deselected)`, rc 5. No live tests exist yet, and the CLI `-m live` correctly overrides `addopts` |
| `uv run python -c "import strands, pydantic, fastmcp, src"` | rc 0. Versions: strands-agents 1.55.1, pydantic 2.13.5, fastmcp 4.0.3, src 0.1.0 |
| `git branch --show-current` | `approach-2/implementation` |
| `git ls-files .env` | empty (and no `.env` exists in this project) |
| `uv lock --check` | `Resolved 103 packages`, rc 0. The lock is fresh |
| `diff --strip-trailing-cr ../code-orchestration/uv.lock uv.lock` | 68 changed lines (34 added, 34 removed). The only difference is the root `[[package]]` block, renamed `code-orchestration`→`agent-orchestration` and moved to its sorted position. No pin changed. `strands-agents` is `1.55.1` |
| `diff --strip-trailing-cr ../code-orchestration/pyproject.toml pyproject.toml` | Only `name`, `description`, and the added `markers` and `addopts` differ |
| `diff pyrightconfig.json`, `diff .env.example` against Approach 1 | byte-identical (rc 0) |
| `.venv/pyvenv.cfg` | `version_info = 3.11` |
| `git check-ignore -v` | Ignored: `.env`, `.env.local`, `logs/x.log`, `drafts/x.md`, `.venv/x`, `.agents/scratchpad/plan.md`. Not ignored: `drafts/.gitkeep`, `logs/.gitkeep`, `src/`, `tests/`, `uv.lock`, `.agents/tasks/…`. `.env.example` is re-included by `!.env.example` |
| Import origins | `server` → `../mcp-server/server.py` (editable); `strands` → the project `.venv`; `src` → the project `src/__init__.py` |
| Process check (`Win32_Process`) | Every `python.exe` and `uv.exe` alive is one of this session's MCP servers (`hse-easy-mock`, `strands-agents-mcp-server`), created at 19:55 and 20:09, before the test run. The tests left no orphan |
| `hse-easy-mock` `list_regulatory_updates(limit=1)` | The substrate is reachable over stdio. No integration test asserts response shapes yet (Iteration 2 copies the drift test) |

## 2. Gate matrix

| Gate | Topic | Status | Notes |
| :--- | :--- | :---: | :--- |
| 1 | Strict TDD | ✅ | Four behaviours, each with a stated Red: a missing `pyproject.toml`, a missing `uv.lock` or `None` version plus `ModuleNotFoundError`, `No module named 'src'`, and missing directories. Each is a legitimate "not built yet" failure, not a typo or a broken fixture. The only production code, `src/__init__.py` (`__version__`), is asserted by value, so a stub would not pass. Using an ephemeral `uvx` runner for Red before any `pyproject.toml` existed is reasonable and recorded |
| 2 | Zero-token testing | ✅ | No test builds a model, reads `.env` or touches a network endpoint; `strands` is only imported. `addopts = "-m 'not live'"` and the `live` marker are declared, and a test asserts both. The `model_builder` seam and the `conftest.py` isolation are n/a until Iteration 2 |
| 3 | Pydantic v2 contracts | n/a in this iteration | No models yet |
| 4 | Guardrails and attempt cap | n/a in this iteration | |
| 5 | Strands integration and telemetry | n/a in this iteration | Only the SDK version pin applies, and it is verified: 1.55.1 is locked and installed |
| 6 | No article text for the Supervisor | n/a in this iteration | |
| 7 | Drafts and logging | n/a in this iteration | Only the scaffolding applies: `drafts/` and `logs/` exist and are writable, tested and kept by `.gitkeep`. `*.md` and `*.log` inside them are ignored |
| 8 | Python and subprocess safety | ✅ | The tests are fully annotated (PEP 585/604: `dict[str, Any]`, `str \| None`), use `pathlib.Path` throughout and have no E402. `NamedTemporaryFile(dir=…)` cleans up after itself. The output is clean with no warnings, even under `-W error`, and the run leaves no orphaned subprocess |

## 3. Acceptance criteria and Definition of Done

| # | Criterion | Status | Evidence |
| :---: | :--- | :---: | :--- |
| AC-1 | `uv run pytest` passes, with the packaging and structure tests green | ✅ | `16 passed in 1.94s`. 12 are in `test_packaging.py` and 4 in `test_module_structure.py` |
| AC-2 | `uv run python -c "import strands, pydantic, fastmcp, src"` exits 0 | ✅ | rc 0 |
| AC-3 | `git branch --show-current` prints `approach-2/implementation` | ✅ | Printed exactly |
| AC-4 | `git ls-files .env` prints nothing | ✅ | Empty output; `.env` is also covered by `.gitignore:29` |
| Red-a | `pyproject.toml` exists; name `agent-orchestration`, version `0.1.0` | ✅ | `test_pyproject_toml_exists`, `test_project_name_and_version` |
| Red-b | Runtime and dev dependencies are those of §4 | ✅ | Exact-set comparison against the seven runtime names and `{pytest, pytest-asyncio}`. This is stronger than Approach 1's substring check |
| Red-c | `[tool.uv.sources]` points `hse-easy-mock-mcp` at `../mcp-server` | ✅ | `== {"path": "../mcp-server", "editable": True}` |
| Red-d | Installed `strands-agents` equals `../code-orchestration/uv.lock` (1.55.1) | ✅ | `test_installed_strands_agents_matches_approach_1_lock`, plus `test_lock_pins_…` for this project's lock. See m1 on the skip path |
| Red-e | `import src` works, `src.__version__ == "0.1.0"` | ✅ | `test_src_package_exposes_version` |
| Red-f | `drafts/` and `logs/` exist and are writable | ✅ | Parametrized `test_artifact_directory_exists_and_is_writable` |
| Green | pytest `markers` and `addopts` added; ruff settings kept | ✅ | Diff against Approach 1 shows exactly these additions |
| Green | Lock copied, then `uv lock` and `uv sync --extra dev` | ✅ | Lock diff is the root block only; `uv lock --check` rc 0; `.venv` is on 3.11 |
| Green | `pyrightconfig.json` copied; `.env.example` copied after a secrets check | ✅ | Both byte-identical. The API keys are empty, the endpoints are `<resource>` placeholders and the cost rates are labelled EXAMPLE VALUES, so there is no secret |
| Green | `.gitignore` extended with `.venv`, `.env`, caches, `logs/*.log`, `drafts/*.md`, keeping `**/scratchpad/*` | ✅ | Verified with `git check-ignore -v` |
| Green | The six `__init__.py` and `.gitkeep` files | ✅ | All present |
| DoD-1 | `uv run pytest`: 0 failures, 0 errors | ✅ | 16 passed |
| DoD-2 | `uvx ruff check src tests`: no findings | ✅ | `All checks passed!` |
| DoD-3 | No live model call | ✅ | Diff inspected: no model construction, no endpoint, no `.env` read |
| DoD-4 | Every new `src/` function is tested | ✅ | `src/__init__.py` holds only a docstring and `__version__`, and the value is asserted |
| DoD-5 | Docs consistency test | n/a | From Iteration 1 |
| DoD-6 | `WALKTHROUGH.md` written | ⏳ | The orchestrating agent writes it at step 8. It is not yet present, which is expected at review time |

**Acceptance criteria: 4/4 passed.** Of the Definition of Done, 4 of 4 applicable rows pass; DoD-5 is n/a and DoD-6 is pending with the orchestrator.

### Implementer's report, claim by claim

| Claim | Verified |
| :--- | :--- |
| 16 passed, 0 failed, 0 errors, no warnings | ✅ exactly 16 (also under `-W error`) |
| Ruff: All checks passed! | ✅ |
| Live collect: 16 deselected, 0 collected | ✅ |
| Lock diff: 34 added and 34 removed, root block only, no pin changed | ✅ 68 lines, root block only |
| `pyrightconfig.json` and `.env.example` byte-identical | ✅ |
| `pyvenv.cfg` `version_info = 3.11` | ✅ |
| README re-encoded from UTF-16 LE BOM CRLF to UTF-8 LF, same content | ✅ HEAD bytes `FF FE` + UTF-16 `# agent-orchestration\r\n`; now `# agent-orchestration\n` |
| `check-ignore` results | ✅ |

## 4. Findings by severity

### 🔴 Blocker
None.

### 🟡 Major
None.

### 🟢 Minor

**m1: the installed-version test has a silent skip path.**
* **Where:** `tests/test_unit/test_packaging.py:109-115`.
* **Problem:** When `../code-orchestration/uv.lock` is missing, the test skips, and nothing then checks the *installed* `strands-agents` version. `test_lock_pins_…` checks the lock file only.
* **Why it is minor:** The Approach 1 lock is an Iteration 0 prerequisite, and it exists today, so the test passed rather than skipped.
* **Fix:** Assert `_installed_version("strands-agents") == LOCKED_STRANDS_VERSION` unconditionally. Keep the comparison with Approach 1's lock only as the conditional part. This is in `FIXES.md`.

**m2 (forward note, no Iteration 0 action): `.env.example` still describes Approach 1.**
* **What it says:** Its comments name the ScopeParser and `ARCHITECTURE §3/§6.2`, and it lacks `HSE_MODEL_SUPERVISOR_REASONING_EFFORT` (SPECIFICATIONS §6.9, D-H).
* **Why it is not a defect now:** The Iteration 0 Green says "Copy `.env.example`", so the verbatim copy is correct.
* **The gap:** No iteration in the plan is assigned to update it.
* **Recommendation:** Update it in Iteration 4, which adds `ReasoningSettings.supervisor` (plan line 375), or at the latest in Iteration 16's README work. It is not a contract change, so no §1.4 question is needed. It is recorded here so that it is not lost.

### Observations (no action)
* **`.gitignore` source.** Plan line 226 attributes `logs/*.log` and `drafts/*.md` to "Approach 1's entries". Approach 1's `.gitignore` does not in fact contain them. The implementer added them under their own heading, which meets the plan's intent.
* **Line endings.** `git diff` prints `LF will be replaced by CRLF` warnings because `core.autocrlf=true`. They are cosmetic and do not affect tests or lint.
* **Name matching.** `_requirement_names` does not normalise names (PEP 503) and does not split on `@` or `(`. It fails closed: an unexpected spelling makes the exact-set test fail, and never lets a dependency through. No change is needed.

## 5. Remediation

See `.agents/tasks/iteration-00/FIXES.md`, section `## 🧪 QA & Verification`, for m1. m2 needs no action in this iteration. No "Needs a decision" items are opened.

---

# QA Review — Iteration 0, round 2 (re-review after fix round 1)

**Reviewer:** QA and Verification Agent · **Date:** 2026-09-28 · **Branch:** `approach-2/implementation` (uncommitted working tree)

## R2.1 Summary and verdict

**Verdict: PASSED**

QA-m1 is fixed, and I confirmed the fix works in both directions. The implementer's fix-round report is accurate on every point. Nothing else changed since round 1, and there are no new findings.

### Commands run and real output

| Command | Real result |
| :--- | :--- |
| `uv run pytest -q` | `16 passed in 1.91s`, rc 0. There are 0 failed, 0 errors and 0 skipped |
| `uv run pytest -q -W error -rA` | `16 passed in 1.75s`, rc 0. Every test shows PASSED and none is skipped. No warnings are emitted |
| `uvx ruff check src tests --no-cache` | `All checks passed!`, rc 0 |
| `uv run pytest -m live --collect-only -q` | `no tests collected (16 deselected)`, rc 5. This was the only live command run |
| `uv run python -c "import strands, pydantic, fastmcp, src"` | rc 0. `strands-agents` 1.55.1, `src.__version__` 0.1.0 |
| `git branch --show-current` | `approach-2/implementation` |
| `git ls-files .env` | empty |
| `uv lock --check` | `Resolved 103 packages`, rc 0 |
| Files modified after 20:10 (excluding `.venv`, `.git` and caches) | Only `tests/test_unit/test_packaging.py` and the review artifacts under `.agents/tasks/`. This confirms "No other changes" |
| `sha256sum` of `.env.example` and `pyrightconfig.json` against Approach 1 | Still identical |
| Process check (`Win32_Process`) | All `python.exe` and `uv.exe` processes are this session's MCP servers, started at 19:55 and 20:09, before the run. The tests left no orphan |

## R2.2 QA-m1 verification

`tests/test_unit/test_packaging.py:109-118` asserts `_installed_version("strands-agents") == LOCKED_STRANDS_VERSION` on line 115, before the skip on lines 116-117. The skip now guards only the cross-check against Approach 1's lock on line 118. The docstring on lines 110-114 describes this.

To check that the fix really does its job, I wrote a throwaway probe. It lived in the session scratchpad, outside the repository, and nothing was written to the project. It imports the test module and monkeypatches it.

| Probe | Expected | Result |
| :--- | :--- | :---: |
| `APPROACH_1_LOCK_PATH` pointed at a missing file, real install | The test skips *after* the installed-version assertion passes | ✅ `pytest.skip.Exception` raised |
| Sibling lock missing, `_installed_version` returns `"1.0.0"` | `AssertionError`. This is the silent path from round 1, now closed | ✅ fails |
| `_installed_version` returns `None` (not installed) | `AssertionError` | ✅ fails |

Before the fix, the second probe would have skipped. The fix therefore closes the gap m1 described. There was no Red step, which is acceptable: this tightens an existing test and adds no new behaviour or production code.

## R2.3 Gate matrix (round 2)

| Gate | Topic | Status | Notes |
| :--- | :--- | :---: | :--- |
| 1 | Strict TDD | ✅ | Unchanged from round 1. The m1 fix tightens a test and adds no production code |
| 2 | Zero-token testing | ✅ | No model is built and no endpoint is reached. `addopts = "-m 'not live'"` is still in effect: 16 are deselected under `-m live` |
| 3 | Pydantic v2 contracts | n/a in this iteration | |
| 4 | Guardrails and attempt cap | n/a in this iteration | |
| 5 | Strands integration and telemetry | n/a in this iteration | The SDK pin applies and holds: 1.55.1 is locked and installed, and this is now asserted unconditionally |
| 6 | No article text for the Supervisor | n/a in this iteration | |
| 7 | Drafts and logging | n/a in this iteration | Only the scaffolding applies, and it is unchanged: `drafts/` and `logs/` exist and are writable |
| 8 | Python and subprocess safety | ✅ | Clean under `-W error`, with no orphaned subprocess and `pathlib.Path` throughout |

## R2.4 Acceptance criteria and Definition of Done (round 2)

| # | Criterion | Status | Evidence |
| :---: | :--- | :---: | :--- |
| AC-1 | `uv run pytest` passes, with the packaging and structure tests green | ✅ | 16 passed, 0 skipped |
| AC-2 | `import strands, pydantic, fastmcp, src` exits 0 | ✅ | rc 0 |
| AC-3 | The branch is `approach-2/implementation` | ✅ | Printed exactly |
| AC-4 | `git ls-files .env` prints nothing | ✅ | Empty |
| DoD-1 | 0 failures, 0 errors | ✅ | 16 passed |
| DoD-2 | Ruff is clean | ✅ | `All checks passed!` |
| DoD-3 | No live model call | ✅ | Only `--collect-only` was run for `live` |
| DoD-4 | Every new `src/` function is tested | ✅ | `src/__init__.py` is unchanged; `__version__` is asserted |
| DoD-5 | Docs consistency | n/a | From Iteration 1 |
| DoD-6 | `WALKTHROUGH.md` | ⏳ | The orchestrator writes it at step 8 |

**Acceptance criteria: 4/4 passed.** Of the Definition of Done, 4 of 4 applicable rows pass; DoD-5 is n/a and DoD-6 is pending with the orchestrator.

## R2.5 Findings (round 2)

* 🔴 Blocker: none.
* 🟡 Major: none.
* 🟢 Minor: none new. **QA-m1 is resolved and verified.**
* **Forward note (carried, no Iteration 0 action):**
  * `.env.example` still needs Approach 2 wording and `HSE_MODEL_SUPERVISOR_REASONING_EFFORT` in Iteration 4.
  * It is untracked but not ignored (it is re-included by `!.env.example`), so the Iteration 0 commit will track it.
* **Q1** in `.agents/tasks/QUESTIONS.md` binds Iteration 2 and does not block Iteration 0.

No new `FIXES.md` items or "Needs a decision" items are opened.
