# Iteration 0 — Packaging and scaffolding: walkthrough

**Date:** 2026-09-28 · **Branch:** `approach-2/implementation` · **Plan section:** `IMPLEMENTATION_PLAN.md` §5, Iteration 0

## 1. Overview

Iteration 0 turns `agent-orchestration/` into a reproducible `uv` project. It is locked to the same SDK versions as Approach 1 (`strands-agents 1.55.1` on Python 3.11). It has an empty `src` package, a pytest runner that deselects `live` tests by default, and the `drafts/` and `logs/` directories. Twelve packaging tests and four structure tests lock these facts. No product code exists yet.

## 2. Files changed

| File | Status | Responsibility |
| :--- | :--- | :--- |
| `pyproject.toml` | New | Taken from Approach 1's. The name is changed to `agent-orchestration` and the description to "Supervisor Agent-Orchestrated HSE Editorial Research Analyst". The seven runtime dependencies and the dev extra (`pytest`, `pytest-asyncio`) keep Approach 1's version specifiers. `hse-easy-mock-mcp` is installed editable from `../mcp-server`, and hatchling builds `packages = ["src"]`. The ruff settings are unchanged. Pytest keeps `testpaths`, `pythonpath` and `asyncio_mode`, and adds a `live` marker and `addopts = "-m 'not live'"` (P4) |
| `uv.lock` | New | Copied from `../code-orchestration/uv.lock` and re-resolved with a plain `uv lock`. The only change is the root package block, renamed from `code-orchestration` to `agent-orchestration` and moved to its sorted position. No pin changed |
| `pyrightconfig.json` | New | Byte-identical copy of Approach 1's |
| `.env.example` | New | Byte-identical copy of Approach 1's, made after checking that it holds only placeholders: the API keys are empty, the endpoints are `<resource>` URLs, and the rates are labelled as example values |
| `.gitignore` | Rewritten | Approach 1's entries, then a *Run artefacts* group (`logs/*.log`, `drafts/*.md`), then the original `**/scratchpad/*`, ending with a newline |
| `README.md` | Re-encoded | Converted from UTF-16 LE with a BOM to UTF-8. The content, `# agent-orchestration`, is unchanged |
| `src/__init__.py` | New | Module docstring and `__version__ = "0.1.0"` only |
| `tests/__init__.py`, `tests/test_unit/__init__.py`, `tests/test_integration/__init__.py` | New | Package markers, each with a one-line docstring |
| `tests/test_unit/test_packaging.py` | New | The packaging contract: metadata, exact dependency name sets, the uv source, the live-marker configuration, the strands pin in both lock files and in the environment, and imports of the core dependencies |
| `tests/test_unit/test_module_structure.py` | New | `import src` and `__version__`; `EXPECTED_MODULES = ["src"]`, which later iterations extend; `drafts/` and `logs/` exist and are writable |
| `drafts/.gitkeep`, `logs/.gitkeep` | New | Keep the two run-artefact directories in git while their contents stay ignored |
| `.agents/tasks/QUESTIONS.md` | New | Holds Q1, which the Iteration 0 review raised for Iteration 2 (see §7) |
| `.agents/docs/IMPLEMENTATION_PLAN.md` | Modified | Only the §3 tracker row for Iteration 0 |

## 3. TDD record

**Behaviour 1: `pyproject.toml` metadata, dependencies, uv source and live marker.** Six tests in `test_packaging.py`.
* **Red:** there was no project yet, so `uv run` could not start. The tests ran under a temporary runner (`uvx --python 3.11 pytest`), and all six failed on `pyproject.toml not found`. This is the helper's assertion, not an import or fixture error.
* **Green:** `pyproject.toml` was written from Approach 1's, as described in §2.
* **Refactor:** the dependency tests compare exact name sets. Names are taken from each requirement string by splitting on `[\s<>=!~;\[]`, so `pydantic` no longer matches `pydantic-settings` as it did in Approach 1's substring check.

**Behaviour 2: the lock and the installed environment.** Six tests.
* **Red:** under the same temporary runner, these failed on `uv.lock not found`, on `assert None == '1.55.1'` (strands was not installed), and on `ModuleNotFoundError` for `strands`, `pydantic`, `fastmcp` and `server`.
* **Green:**
  * `README.md` was re-encoded (see §6);
  * Approach 1's lock was copied, then `uv lock` and `uv sync --extra dev` were run;
  * `.venv/pyvenv.cfg` reports `version_info = 3.11`.

  From this point on, every run used `uv run pytest`.

**Behaviour 3: `import src` and `__version__`.** Two tests.
* **Red:** `ModuleNotFoundError: No module named 'src'`, raised inside each test.
* **Green:** `src/__init__.py`.

**Behaviour 4: the `drafts/` and `logs/` directories.** One test, parametrized over both.
* **Red:** `drafts/ not found` and `logs/ not found`.
* **Green:** the two `.gitkeep` files. Writability is checked with `tempfile.NamedTemporaryFile(dir=…)`, which works on Windows.

**Fix round 1 (QA-m1).** `test_installed_strands_agents_matches_approach_1_lock` now asserts that the installed version is `1.55.1` before it can skip. Only the comparison with Approach 1's lock is skipped when that lock is absent. This makes an existing test stricter, so it has no Red step.

## 4. Test results

A fresh run at the checkpoint:

| Command | Result |
| :--- | :--- |
| `uv run pytest -q` | **16 passed**, 0 failed, 0 skipped, in 1.83 s |
| Tests added by this iteration | 16: 12 in `test_packaging.py` and 4 in `test_module_structure.py` |
| Full suite | 16 |
| `uvx ruff check src tests --no-cache` | `All checks passed!` |
| `uv run pytest -m live --collect-only -q` (reviewers) | 0 collected, 16 deselected |

## 5. Acceptance criteria

| # | Criterion | Result | Evidence |
| :---: | :--- | :---: | :--- |
| 1 | `uv run pytest` passes, with the packaging and structure tests green | ✅ | 16 passed |
| 2 | `uv run python -c "import strands, pydantic, fastmcp, src"` exits 0 | ✅ | Prints `ok`, exit 0 |
| 3 | `git branch --show-current` prints `approach-2/implementation` | ✅ | Checked by both reviewers and at the checkpoint |
| 4 | `.env` is not tracked | ✅ | `git ls-files .env` prints nothing; `.gitignore` ignores `.env` and `.env.*`, and keeps `.env.example` |

Definition of Done:
* **DoD-1** ✅, **DoD-2** ✅ and **DoD-6** ✅ (this file).
* **DoD-3** ✅: there is no model code, and the default run deselects `live`.
* **DoD-4** ✅: `src/__init__.py` is imported by the tests.
* **DoD-5** starts at Iteration 1.

## 6. Decisions and deviations

**Decisions (§1.5):**
* The Red steps of behaviours 1 and 2 ran under a temporary `uvx --python 3.11 pytest` runner. `uv run` needs `pyproject.toml`, and running it before the lock was copied would have resolved a fresh lock instead of starting from Approach 1's.
* The dependency tests compare exact name sets. A test for the `live` marker and `addopts` was added, so that P4's default deselection is locked from Iteration 0 on.
* `test_core_dependencies_are_importable` is an addition that the plan's Red list does not name. It mirrors Approach 1's importability check and backs acceptance criterion 2.
* New files use LF line endings; the repository has `core.autocrlf=true`.

**Deviations from the plan:**
* **`.gitignore`.** The plan lists `logs/*.log` and `drafts/*.md` among "Approach 1's entries", but Approach 1's `.gitignore` has neither. They were added as a new *Run artefacts* group. `git check-ignore` confirms:
  * ignored: `.env`, `logs/*.log`, `drafts/*.md`, `.venv/` and `.agents/scratchpad/*`;
  * kept: `.env.example` and both `.gitkeep` files.
* **`README.md` was re-encoded,** though the plan does not list it for Iteration 0. The committed file was UTF-16 LE with a BOM, and hatchling reads the `readme` file as UTF-8 while it builds the editable project, so `uv sync` would have failed. The content and the `readme` key are unchanged. §4 still makes the README itself an Iteration 16 deliverable.

**Forward notes, handed to later iterations:**
* **Iteration 4.** `.env.example` is a verbatim copy. It still mentions Approach 1's ScopeParser and `ARCHITECTURE §3/§6.2`, and it has no `HSE_MODEL_SUPERVISOR_REASONING_EFFORT` line. Iteration 4 adds `ReasoningSettings.supervisor`, so it should add that line and reword those comments.
* **Iteration 16.** `../mcp-server/fixtures/regulatory_docs.json` holds 20 documents, published from 1989-06-29 to **2026-08-20** (`inail-2026-ot23`). That contradicts Prompt B's premise that "the corpus ends on 2024-07-24". The premise must be checked again before Iteration 16.

## 7. Review

**Two rounds were used.**

| Round | Reviewer | Verdict | Findings | Resolution |
| :---: | :--- | :--- | :--- | :--- |
| 1 | Architect | APPROVED | None to fix. Ruff: 0 in scope, 0 pre-existing. One *Needs a decision* question | The question binds Iteration 2, so it was moved to `QUESTIONS.md` as **Q1 (Iteration 02)** |
| 1 | QA | PASSED | QA-m1 (minor): the installed strands version went unchecked when Approach 1's lock was missing. Forward note on `.env.example` | QA-m1 was fixed in fix round 1. The `.env.example` note is carried to Iteration 4 |
| 2 | Architect | APPROVED | None | — |
| 2 | QA | PASSED | None. QA confirmed the fix with probes: the test fails with a faked wrong version or a missing package | — |

**Q1 (Iteration 02).** Approach 1 (`../code-orchestration/`, HEAD `3b123e4`) has uncommitted edits to `src/agents.py`, including the Writer prompt, and to `src/orchestrator.py` and several tests. `../mcp-server/` has uncommitted edits to `server.py` and to every fixture. The 2026-09-24 benchmark run was made from those working trees. The question asks how to pin the baseline before Iteration 2 copies from them. It must be answered before Iteration 2 starts.
