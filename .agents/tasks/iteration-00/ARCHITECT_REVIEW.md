# Iteration 00 — Packaging and scaffolding: Architect Review (round 1)

**Reviewer:** `architect` subagent, Stage 3 audit
**Date:** 2026-09-28
**Branch:** `approach-2/implementation` (uncommitted working tree over `eb6418e`)
**Criteria:** `.agents/skills/architect-review/SKILL.md` (eight pillars) and `.agents/skills/code-reviewer/SKILL.md` (severity taxonomy); `IMPLEMENTATION_PLAN.md` §1, §2, §4 and Iteration 0; `SPECIFICATIONS.md` §1, §5–§8.

---

## 1. Overall verdict

**APPROVED**

Iteration 0 delivers exactly the packaging and scaffolding the plan asks for, with no production logic beyond `src/__init__.py`. The environment is a faithful copy of Approach 1's: the same seven runtime and two dev dependencies, the same ruff and pytest settings, and a lock whose 102 non-root package pins are identical to `../code-orchestration/uv.lock`. No in-scope defect was found. One question that this iteration surfaced, but cannot settle, is filed under "Needs a decision" in `FIXES.md`. It does not block the Iteration 0 commit; it must be answered before Iteration 2 copies code from Approach 1.

### Evidence gathered on disk (not taken from the implementer's report)

| Check | Command | Result |
| :--- | :--- | :--- |
| DoD-1 | `uv run pytest` | 16 passed in 1.83 s, 0 failures, 0 errors, no warnings |
| DoD-2 | `uvx ruff check src tests --no-cache` | All checks passed (0 findings) |
| DoD-3 / P4 | `uv run pytest -m live --collect-only -q` | 0 collected, 16 deselected; no test touches a model |
| Lock consistency | `uv lock --check` | Resolved 103 packages, consistent with `pyproject.toml` |
| Environment matches lock | `uv sync --extra dev --locked --dry-run` | "Would make no changes" |
| Lock parity with Approach 1 | `tomllib` comparison of every `[[package]]` name → version, root package excluded | Same package set; **zero** version differences; `requires-python = ">=3.11"` on both |
| SDK pin | `importlib.metadata.version("strands-agents")` | `1.55.1` |
| Interpreter | `.venv/pyvenv.cfg` | `version_info = 3.11` |
| Acceptance 1 | `uv run pytest` | Passes, packaging and structure tests green |
| Acceptance 2 | `uv run python -c "import strands, pydantic, fastmcp, src"` | Exit 0 (`src.__version__ == "0.1.0"`) |
| Acceptance 3 | `git branch --show-current` | `approach-2/implementation` |
| Acceptance 4 | `git ls-files .env` | Empty |
| `pyproject.toml` vs Approach 1 | `diff --strip-trailing-cr` | Only `name`, `description`, and the added `markers` / `addopts` (lines 44–45) differ |
| `pyrightconfig.json`, `.env.example` vs Approach 1 | `diff` | Byte-identical |
| `.gitignore` behaviour | `git check-ignore -v` | `.env`, `logs/*.log`, `drafts/*.md` ignored; `.env.example`, `drafts/.gitkeep`, `logs/.gitkeep`, `uv.lock`, `.agents/tasks/**` and `tests/fixtures/*.md` (needed in Iteration 16) not ignored |
| Planning files tracked | `git ls-files` | `.agents/docs/`, `.agents/skills/`, `.agents/templates/`, `.claude/`, `.gitignore`, `.mcp.json`, `README.md` are all in `eb6418e`, so the Iteration 0 prerequisite on the working tree holds |

---

## 2. Pillar audit

| # | Pillar | Assessment |
| :---: | :--- | :--- |
| 1 | An agent owns the flow | Not touched by this iteration. No code sequences anything: `src/__init__.py` holds a docstring and `__version__` only. |
| 2 | Division of labour | Not touched by this iteration. |
| 3 | Custom agent tools | Not touched by this iteration. |
| 4 | Guardrails and attempt state | Not touched by this iteration. |
| 5 | Benchmark parity | **Holds for everything this iteration controls.** The SDK and every transitive pin equal Approach 1's lock (see §1). The dependency set equals `IMPLEMENTATION_PLAN.md` §4 exactly, and `tests/test_unit/test_packaging.py:79-88` asserts the exact name sets, so an added dependency (a §1.4 item 4 stop) fails loudly. The cost-rate example values in `.env.example` are byte-identical to Approach 1's and equal its `src/costs.py:34-41` built-in defaults, so the cost basis cannot drift through the example file. The substrate is bound the same way as in Approach 1 (`[tool.uv.sources]` editable `../mcp-server`). The baseline itself is, however, an uncommitted working tree in both sibling repositories; see §4 R1. |
| 6 | Substrate isolation and lifecycle | Not touched in business logic. The only import of the substrate package is `importlib.import_module("server")` in `tests/test_unit/test_packaging.py:118-125`, an installability check that mirrors Approach 1's `test_dependencies_importable`. That is test code, not business logic, so the "never imported into business logic" rule is not engaged. |
| 7 | Rendering, telemetry and logging | Not touched, beyond creating `drafts/` and `logs/` with `.gitkeep` and ignoring their run artefacts, which D-B / D-I and §7.5 will rely on. |
| 8 | Code quality and conventions | **Clean.** Imports at the top in stdlib / third-party groups (ruff `I` clean, zero E402). Every function in both test modules is fully annotated with PEP 585/604 types (`dict[str, Any]`, `str \| None`, `set[str]`). `pathlib.Path` for every path. Honest docstrings on every module and test. No dead code. `dict[str, Any]` appears only as the return type of the private TOML loader inside one test module, so it crosses no module boundary. |

---

## 3. Code review findings

No blocker, no major and no minor defect. The notes below need no change in this iteration.

* `tests/test_unit/test_module_structure.py:22-25` iterates `EXPECTED_MODULES` in a loop rather than parametrising. Today the list has one entry. When later iterations grow it to fifteen modules, a loop stops at the first failure, although the `ModuleNotFoundError` still names that module. Parametrising it when the list grows is optional and is left to the implementer (§1.5 permits it).
* `tests/test_unit/test_packaging.py:33`: `_REQUIREMENT_NAME_END` does not normalise names (PEP 503) and does not split on `@` or `(`. Both gaps can only make the exact-set assertion **stricter** (a spurious failure), never let an extra dependency through, so they are acceptable for a guard test.
* `tests/test_unit/test_module_structure.py:33` creates and deletes a temporary file inside the real `drafts/` and `logs/` directories. On Windows, `NamedTemporaryFile(delete=True)` uses `O_TEMPORARY`, so nothing is left behind, and the test passed with no residue.
* Line endings. The new files are LF and `core.autocrlf=true`, which produces git's "LF will be replaced by CRLF" warnings. These are benign: git normalises to LF in the index either way. `.env.example` keeps Approach 1's CRLF, as a byte-identical copy must.

### Ruff

`uvx ruff check src tests --no-cache`: **All checks passed.**
* In-scope findings (blocking): **0**
* Pre-existing debt (deferred): **0**. Every Python file under `src/` and `tests/` is new in this iteration, so there is no pre-existing code to carry debt.

---

## 4. Anti-patterns and risks

No autonomy leak, no article-text path, no state coupling: there is no runtime code yet.

**Source discrepancies, stated explicitly:**

* **D1: `IMPLEMENTATION_PLAN.md` Iteration 0 Green versus Approach 1's `.gitignore`.** The plan says to "extend `.gitignore` with Approach 1's entries (`.venv`, `.env`, caches, `logs/*.log`, `drafts/*.md`)". Approach 1's `.gitignore` has no `logs/*.log` or `drafts/*.md` entry. The implementer copied Approach 1's file verbatim and added the two run-artefact entries in a labelled block. That satisfies the plan's intent, keeps `**/scratchpad/*`, and changes no contract. It is noted here so that the walkthrough records it; it needs no fix.
* **D2: `README.md` was modified,** although the Iteration 0 file list does not include it. The committed file was UTF-16 LE with a BOM. The `readme = "README.md"` metadata that the plan requires to be copied from Approach 1 has to be read as text by the build backend when `uv sync` builds the editable install, so re-encoding it to UTF-8 was necessary, with the content unchanged (`# agent-orchestration`). Accepted as a justified deviation; it must appear in the walkthrough's *Deviations*.

**Risks carried forward (not defects of this iteration):**

* **R1: the Approach 1 baseline and the substrate are uncommitted working trees.** Filed as a question under "Needs a decision" in `FIXES.md`.
  * `../code-orchestration/` HEAD is `3b123e4` (2026-09-23 17:14). Its working tree carries uncommitted edits to `src/agents.py` (+346/−161 lines across the file, including the Writer system prompt and `QA_LEGAL_TOOL_NAMES`, which gained `get_document_by_id`), to `src/orchestrator.py`, and to several tests.
  * The file times suggest that the working tree produced the benchmark run the plan cites: `src/agents.py` was modified at 2026-09-24 13:07 and `drafts/draft_20260924_00{1,2,3}.md` were written at 13:16. So the working tree, not HEAD, is the baseline.
  * `../mcp-server/` also has uncommitted changes to `server.py` and to every `fixtures/*.json` file.
  * Iterations 2 and 6 copy the reused modules and parse the prompts from whatever is on disk at that moment. If either sibling tree changes again, the prompt-parity and substrate constants move silently, with no commit to diff against. Nothing in Iteration 0 depends on this: `uv.lock` and `pyproject.toml` in Approach 1 are unmodified.
* **R2: `.env.example` still describes Approach 1.**
  * Lines 2, 6, 13, 18 and 21 cite the ScopeParser, which Approach 2 removes, and `ARCHITECTURE §3/§6.2`, a document that does not exist in this project.
  * It has no `#HSE_MODEL_SUPERVISOR_REASONING_EFFORT=medium` line.
  * The byte-identical copy is correct for Iteration 0: the plan says "copy", and parity of the cost-rate examples matters more than the comments.
  * **Directive for Iteration 4,** which adds `ReasoningSettings.supervisor` (D-H, DM17). That iteration should add the commented Supervisor line and reword the role comments ("Strong model: Writer, QA-Legal and Supervisor"; drop the ScopeParser). It must leave every variable name and every example value unchanged. This is a comment and documentation change, which §1.5 allows. It is not a question.

---

## 5. Remediation directives

* **Iteration 0:** none. The iteration may be committed as it stands (`IMPLEMENTATION_PLAN.md` §1.2 step 8, P5).
* **The walkthrough must record** (§1.1):
  * the ephemeral `uvx --python 3.11 … pytest` runner used for the Red steps of behaviours 1–2 (§1.5);
  * the exact-set dependency assertions and the added live-marker test;
  * deviation D2 (README re-encoding) and discrepancy D1 (the `.gitignore` entries that Approach 1 does not have).
* **Before Iteration 2 starts:** answer the "Needs a decision" question in `FIXES.md` (R1), copied to `.agents/tasks/QUESTIONS.md` under §1.4.
* **Iteration 4:** update the `.env.example` comments and add the Supervisor effort line, as R2 describes (`SPECIFICATIONS.md` D-H, §6.9).

---

# Round 2 — Re-review after fix round 1

**Reviewer:** `architect` subagent, Stage 3 re-review
**Date:** 2026-09-28
**Scope:** the implementer's fix for QA-m1, and a regression check of the whole iteration.

## R2.1 Overall verdict

**APPROVED.** Unchanged from round 1. The QA-m1 fix is correct and in scope, and nothing regressed.

## R2.2 Verification of the fix (QA-m1)

`tests/test_unit/test_packaging.py:109-118`, `test_installed_strands_agents_matches_approach_1_lock`:

* Line 115 asserts `_installed_version("strands-agents") == LOCKED_STRANDS_VERSION` unconditionally, before any skip. `_installed_version` (lines 59-64) returns `None` when the distribution is missing, so a missing or wrong SDK now fails this test instead of being skipped.
* Lines 116-117 skip only when `../code-orchestration/uv.lock` is absent, and line 118 is the only assertion that the skip covers, the cross-check against Approach 1's lock.
* The docstring (lines 110-114) now describes exactly this split, so it is accurate.
* This matches the Iteration 0 *Red* bullet ("the installed `strands-agents` version equals the one locked in `../code-orchestration/uv.lock`, which is 1.55.1"). Together with `test_lock_pins_the_strands_agents_version_approach_1_uses` (lines 104-106), the SDK pin is now checked three ways: this project's lock, the installed distribution, and Approach 1's lock.
* No Red step is needed. The change makes an existing test stricter and adds no production behaviour, so §1.2 step 2 is not engaged. The walkthrough should record this under the review findings (§1.1).

## R2.3 Regression check (on disk)

| Check | Command | Result |
| :--- | :--- | :--- |
| Files changed since round 1 | file mtimes against the round-1 review (20:14) | Only `tests/test_unit/test_packaging.py` (20:16), plus the review artefacts `FIXES.md` and `QUESTIONS.md`. `pyproject.toml`, `uv.lock`, `pyrightconfig.json`, `.env.example`, `.gitignore`, `README.md`, `src/__init__.py` and `test_module_structure.py` are all unchanged since before round 1. |
| `git status --short` | | Same set as round 1. The one tracked change to `IMPLEMENTATION_PLAN.md` is the §3 row for Iteration 0, `⏳ Pending` → `🔄 In progress`, which the orchestrator makes under §1.1. It is not an implementer change. |
| DoD-1 | `uv run pytest -q` | 16 passed, 0 failed, 0 skipped (`test_packaging.py` alone: 12 passed, no skips with `-rs`) |
| DoD-2 | `uvx ruff check src tests --no-cache` | All checks passed |
| DoD-3 / P4 | `uv run pytest -m live --collect-only -q` | 0 collected, 16 deselected |
| Lock | `uv lock --check` | Resolved 103 packages, consistent |
| Acceptance 2 | `uv run python -c "import strands, pydantic, fastmcp, src"` | Exit 0; `src.__version__ == "0.1.0"` |
| Acceptance 3 | `git branch --show-current` | `approach-2/implementation` |
| Acceptance 4 | `git ls-files .env` | Empty |

## R2.4 Pillar audit (delta only)

Pillars 1 to 4, 6 and 7: not touched by this iteration, as in round 1. Pillar 5 (parity): still holds, and it is now slightly stronger because the installed SDK version is asserted without a skip path. Pillar 8 (code quality): clean. The edited test keeps full annotations and the import order, adds no dead code, and has an accurate docstring.

## R2.5 Ruff

* In-scope findings (blocking): **0**
* Pre-existing debt (deferred): **0**

## R2.6 Remediation directives

None. The iteration may be checkpointed (§1.2 step 8). The round-1 walkthrough directives (§5 above) still apply, plus one more: record QA-m1 and its fix. Q1 in `.agents/tasks/QUESTIONS.md` binds Iteration 2 and is not re-raised here. The directive on the `.env.example` comments stays with Iteration 4 (R2 above).
