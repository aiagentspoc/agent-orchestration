# HSE Easy — Approach 2 Implementation Plan
## Research Analyst (Supervisor Agent-Orchestrated System)

**Built from:** [`DESIGN.md`](DESIGN.md) and [`SPECIFICATIONS.md`](SPECIFICATIONS.md), which consolidates the approved design (Draft v7, 2026-09-28).
**Baseline:** Approach 1, with 221 tests and `strands-agents 1.55.1`.
**Approach 1 (reference project):** `../code-orchestration/`, the folder next to `agent-orchestration/`. On this machine that is `C:\Users\Saksham\Git\poc\AIAgents\code-orchestration`. It is **read-only**. Its `src/`, `tests/`, `uv.lock`, `drafts/` and `.agents/docs/` are the baseline this project reuses and is benchmarked against.
**Method:** Strict TDD, in 17 iterations run in order. Each iteration has prerequisites and acceptance criteria that can be checked, so an agent can run every iteration without human input. It stops only for the reasons listed in §1.4.

All paths are relative to `agent-orchestration/` unless they start with `../`.

---

### 1. How to execute this plan

#### 1.1 Order and tracking

* Run the iterations **in numerical order**. An iteration starts only when every prerequisite it lists holds.
* On starting an iteration, set its row in §3 to `🔄 In progress`. When all its acceptance criteria hold, set it to `✅ Complete` and fill in the date and the test count.
* Record each iteration in `.agents/tasks/iteration-NN/WALKTHROUGH.md`. Cover:
  * files changed;
  * tests added;
  * the full-suite count;
  * decisions made (§1.5);
  * deviations from this plan, with their reason;
  * review findings and how each was resolved.

#### 1.2 The loop inside every iteration

The `/implement` skill (`.claude/skills/implement/SKILL.md`) runs this loop, and every iteration goes through it, Iterations 0 and 1 included:

| Step | Done by |
| :--- | :--- |
| 1 | The `architect` subagent |
| 2–6 | The `implementation` subagent |
| 7 | The `architect` and `qa` subagents, with `implementation` in fix mode |
| 8 | The orchestrating agent, which also writes `WALKTHROUGH.md` and updates §3 |

The subagents are defined in `.claude/agents/`, and the review criteria they load are in `.agents/skills/architect-review/` and `.agents/skills/code-reviewer/`.

1. **Pre-flight.** Check the prerequisites, and read the sections of `SPECIFICATIONS.md` that the iteration cites.
2. **Red.** Write the tests listed under *Red*, one behaviour at a time. Run them and confirm each **fails for the expected reason**, such as a missing name, a wrong value or a missing guardrail. A test that fails because of a typo or a broken fixture does not count as Red.
3. **Green.** Write the smallest production code that makes the tests pass.
4. **Refactor.** Add type annotations and docstrings, remove duplication, and use `ConfigDict(extra="ignore")` on every model. Keep the suite green throughout.
5. **Repeat** steps 2 to 4 for the next behaviour. Do not write all the tests up front.
6. **Verify.** Check the Definition of Done (§1.3) and the iteration's acceptance criteria.
7. **Review.** Spawn the `architect` and `qa` subagents in parallel, on the iteration's diff. Fix what they find, for at most two rounds. A finding you cannot fix within this plan's scope becomes a question (§1.4).
8. **Checkpoint.** Commit the iteration on the local branch `approach-2/implementation`. The orchestrating agent creates the branch before Iteration 0.
   * Commit message: `Iteration NN: <title>`, followed by the session's attribution lines.
   * Never push.

#### 1.3 Definition of Done (applies to every iteration)

| # | Check | Command | Expected |
| :---: | :--- | :--- | :--- |
| DoD-1 | Full default suite passes | `uv run pytest` | 0 failures, 0 errors |
| DoD-2 | Lint is clean | `uvx ruff check src tests` | No findings |
| DoD-3 | No live model call was made | Inspect the diff and the test run | No test reaches a real model endpoint. Every model is a `ScriptedModel` or `FailingModel` (D16) |
| DoD-4 | Every new `src/` function is exercised by a test | Review | No untested production code |
| DoD-5 | Docs match code | `uv run pytest tests/test_unit/test_docs_consistency.py` (from Iteration 1) | Passes |
| DoD-6 | Record written | `.agents/tasks/iteration-NN/WALKTHROUGH.md` | Exists, with §1.1's contents |

**No live runs.** Neither the implementation nor the default test suite ever calls a real model endpoint. The local `hse-easy-mock` substrate over stdio is not a live run and may be used freely. Live end-to-end tests are built in Iteration 16. They are excluded from the default run, and **only the user triggers them**.

#### 1.4 When to stop and ask

Stop, write the question to `.agents/tasks/QUESTIONS.md`, and end the turn with it, when any of these happens:

1. **The sources conflict or are silent** on something that would change any of these:
   * a contract in `SPECIFICATIONS.md`;
   * a guardrail;
   * a sub-agent or Supervisor prompt;
   * something the benchmark holds constant: substrate, models, template, cost basis, tool binding or sequential execution;
   * an exit code.
2. **An acceptance criterion cannot be met** after three Green attempts, or meeting it would change behaviour that an earlier iteration's acceptance tests lock. A plain bug fix is exempt.
3. **The Iteration 12 spike** finds that no candidate mechanism works.
4. **An action is outside the plan's scope:**
   * it needs credentials or a live model call;
   * it would modify `../code-orchestration/`, `../mcp-server/` or the git remote;
   * it would add a dependency that §4 does not list.
5. **A review subagent cannot be spawned.**

Write each question in this form. It is the format the user asked for.

```markdown
## Q<n> (Iteration NN): <one-line question ending in "?">
**Background:** <what was found, in two or three sentences>
**Recommendation:** <the option you would choose, and why>
**Options:** A. … · B. … · C. …
```

#### 1.5 Decisions you may make without asking

Record each in the iteration's `WALKTHROUGH.md` under *Decisions*. You may decide:

* names of private helpers, and how code is split into modules inside `src/` beyond §4;
* how test fixtures and helpers are organised;
* log message wording, as long as the fields in the D-I catalogue are present;
* docstrings and comments;
* the order of tests within a file.

Anything that is visible to the Supervisor or to a sub-agent is **never** a free decision: tool names, parameters, descriptions, prompts and result shapes.

---

### 2. Decisions added while writing this plan

These settle points that the design (Draft v7) left open. `SPECIFICATIONS.md` applies them throughout and records them in its Decision Log (§8.3).

| # | Decision | Effect |
| :---: | :--- | :--- |
| **P1** | **Tool binding matches Approach 1.** Every sub-agent is built with all five substrate tools, as Approach 1's workers are (its D19). `SCOUT_TOOL_NAMES`, `WRITER_TOOL_NAMES` and `QA_LEGAL_TOOL_NAMES` remain declared intent; each sub-agent's prompt draws the boundary. | Benchmark parity. `DESIGN.md` §4 says so, and presents its "Used by" column as the tools each prompt directs a sub-agent to use (fixed 2026-09-28) |
| **P2** | **A saved document is closed.** Besides `save_draft`, `writer_tool` and `qa_tool` also refuse a saved document, with the existing `already_saved` guardrail. | The Supervisor is a model and can call a tool on the wrong document. Without this, `writer_tool(revise=True)` on a document saved with `WARNING` passes rule 7 and produces a draft that can never be saved. It also keeps the rendered draft the same one that was saved. The guardrail count stays at 12 |
| **P3** | **An unknown `doc_id` is `not_a_candidate`** on every per-document tool, not only `writer_tool`. | One clear message for "no such candidate" |
| **P4** | **No live runs** during implementation or in the default suite. Live end-to-end tests are marked `live`, deselected by default, and triggered only by the user. | Iteration 16 builds them but does not run them |
| **P5** | **Commit per iteration** on the local branch `approach-2/implementation`. Nothing is pushed. | §1.2 step 8 |
| **P6** | **Exit-code severity is the numeric maximum**, as in Approach 1's `_worst`. | `SUPERVISOR_ERROR` (6) is the most severe |
| **P7** | **The Approach 1 baseline is the local working tree.** `../code-orchestration/` and `../mcp-server/` are used as they are on disk, uncommitted edits included; neither is committed or changed (Q1, 2026-09-28). | Every copy from Approach 1, every parity check and the substrate read the on-disk files, not a git commit |
| **P8** | **The draft template is Approach 1's current one.** `.agents/templates/draft.md` is replaced by a content-identical copy of `../code-orchestration/.agents/templates/draft.md`, including its Cost Basis line and Agent Tool Usage table (Q3, 2026-09-29). | Iteration 2. The copied template-engine tests pass unchanged, and Approach 2 drafts carry the same telemetry sections as Approach 1's |
| **P9** | **`src/mcp_client.py` may gain type annotations only.** Iteration 7 adds the 9 missing annotations to the verbatim copy; this is the one permitted divergence from Approach 1's module (Q5, 2026-09-29). | Iteration 7. Behaviour and every result shape stay identical to Approach 1's `mcp_client.py`; only annotations differ |
| **P10** | **API-key redaction stays Approach 1's.** `_ApiKeyRedactionFilter` masks the key in the log message only; exception tracebacks and stack text are logged in full, even if they contain the key (Q7, 2026-09-29: a proof of concept, where sensitive data may be logged for audit). | Iteration 3. The filter is moved verbatim, and no later iteration widens it |
| **P11** | **Per-draft latency counts only the Supervisor's own time.** `DraftMetadata.latency_seconds` = the draft's own `writer`/`qa_legal` durations + its Scout share + an equal share of `max(supervisor.total_duration_seconds − Σ supervisor.tool_invocations.total_time_seconds, 0)`. The `stage_telemetry` entries stay exactly as `amortise_shared_telemetry` produces them (Q8, 2026-10-01). | Iteration 11. The Supervisor's duration already contains every sub-agent call, so the literal §6.8 sum would count it twice; per-draft times then mean what Approach 1's mean |
| **P12** | **Run totals are logged once, on "Run completed".** `finalise_run(state, *, supervisor_telemetry, rates)` keeps its signature, computes the run's tokens and cost and returns them with `persistence_failed`, and logs no totals line. The composition root measures wall-clock and logs all three on "Run completed" (Q9, 2026-10-01). | Iterations 11 and 14. D-I wins over the plan's Iteration 11 wording; DM18 holds, since nothing is stored on `RunState` |

---

### 3. Iterations at a glance

| # | Iteration | Design phase | Main deliverables | Status |
| :---: | :--- | :---: | :--- | :---: |
| 0 | Packaging and scaffolding | 1 | `pyproject.toml`, `uv.lock`, `src/`, `tests/`, git branch | ✅ Complete (2026-09-28, 16 tests) |
| 1 | Project documents and working rules | 0 | `AGENTS.md`, `CLAUDE.md`, and docs tests covering `SPECIFICATIONS.md`, `DESIGN.md` and the workflow files | ✅ Complete (2026-09-28, 199 tests) |
| 2 | Reused modules and triaged tests | 1 | Approach 1 modules and tests, per D-J | ✅ Complete (2026-09-29, 321 tests) |
| 3 | Logging setup and correlation | 1 | `src/logging_setup.py` | ✅ Complete (2026-09-29, 364 tests) |
| 4 | New and amended contracts | 2 | `src/schemas.py`, `src/credentials.py` | ✅ Complete (2026-09-29, 416 tests) |
| 5 | Guardrail checks | 3 | `src/guardrails.py` | ✅ Complete (2026-09-29, 634 tests) |
| 6 | Sub-agent runners and prompts | 3 | `src/agents.py` | ✅ Complete (2026-09-29, 742 tests) |
| 7 | Tool wrapper core and `scout_tool` | 3 | `src/tools.py` | ✅ Complete (2026-09-30, 850 tests) |
| 8 | `writer_tool` | 3 | `src/tools.py` | ✅ Complete (2026-09-30, 925 tests) |
| 9 | `qa_tool` | 3 | `src/tools.py` | ✅ Complete (2026-09-30, 999 tests) |
| 10 | `save_draft` and draft ID allocation | 3 | `src/tools.py`, `src/rendering.py` | ✅ Complete (2026-09-30, 1038 tests) |
| 11 | End-of-run reconciliation and rendering | 3 | `src/rendering.py`, `src/telemetry.py` | ✅ Complete (2026-10-01, 1068 tests) |
| 12 | SDK spike: fatal stop and logging hooks | 4 | `src/hooks.py`, SDK contract tests | ✅ Complete (2026-10-01, 1111 tests) |
| 13 | Supervisor agent | 4 | `src/supervisor.py` | ⏳ Pending |
| 14 | Composition root and CLI | 4 | `src/app.py`, `src/cli.py` | ⏳ Pending |
| 15 | Scripted end-to-end scenarios | 5 | `tests/test_integration/test_supervisor_e2e.py` | ⏳ Pending |
| 16 | Live end-to-end tests and benchmark report (built, not run) | 6 | `tests/test_live/`, `src/benchmark.py`, `README.md` | ⏳ Pending |

```text
0 ─► 1 ─► 2 ─► 3 ─► 4 ─► 5 ─► 6 ─► 7 ─► 8 ─► 9 ─► 10 ─► 11 ─► 12 ─► 13 ─► 14 ─► 15 ─► 16
                                                                                        │
                                              user-triggered: uv run pytest -m live ◄───┘
```

---

### 4. Target layout

```text
agent-orchestration/
├── AGENTS.md, CLAUDE.md, README.md
├── pyproject.toml, uv.lock, pyrightconfig.json, .env.example, .gitignore, .mcp.json
├── .agents/
│   ├── docs/        DESIGN.md, SPECIFICATIONS.md, IMPLEMENTATION_PLAN.md   (already present)
│   ├── tasks/       iteration-NN/WALKTHROUGH.md, QUESTIONS.md
│   ├── templates/   draft.md (Approach 1's current template, P8)
│   └── skills/      architect-review/SKILL.md, code-reviewer/SKILL.md   (review criteria; already present)
├── .claude/
│   ├── agents/      architect.md, implementation.md, qa.md             (already present)
│   ├── skills/implement/SKILL.md                                       (already present)
│   └── settings.json   read access to ../code-orchestration and ../mcp-server; MCP servers enabled (already present)
├── src/
│   ├── __init__.py
│   ├── schemas.py          §7 data model                                   [reused + amended + new]
│   ├── mcp_client.py       HSEMockMCPClient                                [reused]
│   ├── template_engine.py  render_draft, generate_draft_id                 [reused]
│   ├── costs.py  credentials.py  model_factory.py  diagnostics.py          [reused; credentials amended]
│   ├── telemetry.py        estimate_cost, amortise_shared_telemetry        [moved from Approach 1's orchestrator]
│   ├── logging_setup.py    configure_logging, key redaction, correlation   [extracted + new]
│   ├── agents.py           Scout / Writer / QA-Legal prompts and runners   [reused + adapted]
│   ├── guardrails.py       D-C checks, pure functions over RunState        [new]
│   ├── tools.py            build_tools(state, …) → the four Supervisor tools   [new]
│   ├── rendering.py        draft ID allocation, run-end reconciliation and render   [new]
│   ├── hooks.py            logging hooks, fatal-stop hook                  [new]
│   ├── supervisor.py       Supervisor prompt, builder, runner              [new]
│   ├── app.py              composition root: run(prompt, config, …) → RunState   [new]
│   ├── cli.py              argparse, main(argv) → int                      [new]
│   └── benchmark.py        Approach 1 vs Approach 2 report from drafts     [new]
├── tests/
│   ├── conftest.py, support/scripted.py
│   ├── test_unit/  test_integration/  test_live/
│   └── fixtures/
├── drafts/  logs/
```

**Dependencies:** the same as Approach 1's `pyproject.toml`: `strands-agents`, `pydantic`, `pydantic-settings`, `python-dotenv`, `openai`, `fastmcp` and `hse-easy-mock-mcp` (editable, from `../mcp-server`). The dev dependencies are `pytest` and `pytest-asyncio`. Adding anything else is a stop condition (§1.4).

**Name clash to avoid:** `template_engine.save_draft` writes a file, while the Supervisor tool `save_draft` only marks a document saved. In `src/tools.py` and `src/rendering.py`, import the file writer as `from .template_engine import save_draft as write_draft_file`.

---

### 5. Iterations

Each iteration lists its **Goal**, its **Prerequisites**, **Red** (the tests to write first), **Green** (the code), **Refactor** where needed, its **Acceptance criteria**, and **Stop and ask if**, where there is a specific risk. The Definition of Done (§1.3) applies on top of every acceptance list.

---

#### Iteration 0 — Packaging and scaffolding

**Goal:** a reproducible `uv` project with an empty `src` package and a working test runner, locked to the SDK versions Approach 1 uses.

**Prerequisites**
* `uv --version` works, and `python --version` reports 3.11 or later.
* `../mcp-server/` and `../code-orchestration/uv.lock` exist.
* The git working tree of `agent-orchestration/` holds no changes other than the planning files: `.agents/docs/`, `.agents/skills/`, `.claude/`, `.gitignore` and `.mcp.json`. The Iteration 0 commit includes them.

**Red**
* `tests/test_unit/test_packaging.py`:
  * `pyproject.toml` exists; `project.name == "agent-orchestration"` and `version == "0.1.0"`;
  * the runtime and dev dependencies are those listed in §4;
  * `[tool.uv.sources]` points `hse-easy-mock-mcp` at `../mcp-server`;
  * the installed `strands-agents` version equals the one locked in `../code-orchestration/uv.lock`, which is 1.55.1.
* `tests/test_unit/test_module_structure.py`: `import src` works and `src.__version__ == "0.1.0"`; `drafts/` and `logs/` exist and are writable. Later iterations add each new module to this test's expected list, in their Red step.

**Green**
* The orchestrating agent has already created the git branch `approach-2/implementation` in `/implement`'s pre-flight; confirm it is checked out.
* Write `pyproject.toml` from Approach 1's, with the name and description changed.
  * Keep its `[tool.pytest.ini_options]`, and add `markers = ["live: calls real model endpoints; user-triggered only"]` and `addopts = "-m 'not live'"`.
  * Keep its `[tool.ruff]` settings.
* Copy `../code-orchestration/uv.lock` as the starting lock, then run `uv lock` and `uv sync --extra dev`.
* Copy `pyrightconfig.json`.
* Copy `.env.example`, but first confirm it holds placeholders only. If it holds anything that looks like a real secret, stop and ask.
* Extend `.gitignore` with Approach 1's entries (`.venv`, `.env`, caches, `logs/*.log`, `drafts/*.md`), keeping `**/scratchpad/*`.
* Create `src/__init__.py`, `tests/__init__.py`, `tests/test_unit/__init__.py`, `tests/test_integration/__init__.py`, `drafts/.gitkeep` and `logs/.gitkeep`.

**Acceptance criteria**
1. `uv run pytest` passes, with the packaging and structure tests green.
2. `uv run python -c "import strands, pydantic, fastmcp, src"` exits 0.
3. `git branch --show-current` prints `approach-2/implementation`.
4. `.env` is not tracked: `git ls-files .env` prints nothing.

---

#### Iteration 1 — Project documents and working rules

**Goal:** the working rules exist, and every source of truth is locked by tests. `SPECIFICATIONS.md` was written on 2026-09-28, before this plan runs. This iteration writes `AGENTS.md` and `CLAUDE.md` and guards every document. `DESIGN.md` needs no change.

**Prerequisites:** Iteration 0 is complete, and `.agents/docs/SPECIFICATIONS.md` exists.

**Red:** `tests/test_unit/test_docs_consistency.py`. It asserts text only and does no I/O beyond reading the repo.
* **These files exist:**
  * `AGENTS.md` and `CLAUDE.md`;
  * `.agents/docs/DESIGN.md`, `SPECIFICATIONS.md` and `IMPLEMENTATION_PLAN.md`;
  * the workflow files: `.claude/agents/architect.md`, `implementation.md` and `qa.md`, `.claude/skills/implement/SKILL.md`, and `.agents/skills/architect-review/SKILL.md` and `code-reviewer/SKILL.md`.
* `AGENTS.md` and `CLAUDE.md` link to the three documents in `.agents/docs/` and to each workflow file.
* **Every file path cited in a workflow file, `AGENTS.md` or `CLAUDE.md` exists on disk,** whether it is written in backticks or as a link. The exceptions are the paths the workflow itself creates: `.agents/tasks/iteration-NN/…` and `.agents/tasks/QUESTIONS.md`. A bare file name, such as `SPECIFICATIONS.md`, counts as existing when it resolves against the repository root, `.agents/docs/`, the citing file's folder, or `../code-orchestration/`.
* **`.claude/settings.json` exists.** It grants read access to `../code-orchestration/` and `../mcp-server/` through `permissions.additionalDirectories`, and it enables `strands-agents` and `hse-easy-mock` through `enabledMcpjsonServers`.
* **No workflow file, and none of `AGENTS.md`, `CLAUDE.md`, `DESIGN.md` or `SPECIFICATIONS.md`, cites the scratchpad design plan,** since `SPECIFICATIONS.md` has replaced it.
* **`SPECIFICATIONS.md` contains:**
  * every model in its §6: 27 models plus the four settings classes;
  * the 12 `GuardrailName` values;
  * the seven `ExitCode` members, with their values 0 to 6;
  * decisions D-A to D-J;
  * every row of the D-C decision table;
  * every event in the D-I catalogue;
  * the four tool descriptions in §7.1;
  * P1 to P6.
* **Tool binding (P1).** `DESIGN.md` §4 states that every sub-agent is connected to all five tools, and no document says a sub-agent is given only some of them.
* **The attempt cap is consistent.** Every document that states the cap states it as `MAX_ATTEMPTS_PER_DOC = 3` or as "3 Writer attempts", and none states another cap.
* **No forbidden terms.** No document in the repository uses a term from a forbidden-terms list kept in the test module. The list holds the out-of-scope features the user has ruled out of Approach 2's documents; see the project memory.
* **No removed model is named as current:** `RevisionPayload`, `PipelineRun`, `PipelineExitCode`, `SupervisorReport`, `RunBudget` or `GuardrailRefusal`. Mentions in a "Removed" or history passage are allowed, and are matched by the surrounding sentence.

**Green**
* **`AGENTS.md`**, harness-neutral and modelled on Approach 1's:
  * **Product rules:**
    * the contracts in `SPECIFICATIONS.md`;
    * the attempt cap and the guardrails are enforced in code;
    * the Supervisor supervises agents, not drafts;
    * drafts are Markdown, rendered at run end;
    * telemetry follows Approach 1's rules.
  * **Working rules:**
    * strict TDD;
    * this plan's stop-and-ask protocol replaces Approach 1's human approval gates;
    * review subagents, with zero fallback;
    * no live model calls.
  * **Layout and placement rule,** as in Approach 1: project truth goes in `.agents/` (docs, review skills, tasks, templates), and Claude Code mechanics in `.claude/` (subagents, `/implement`).
* **`CLAUDE.md`:** a thin pointer to `AGENTS.md`, as in Approach 1.
* **Workflow files.** Add `AGENTS.md` to the "Sources of truth" table of both review skills, and to the mandatory reading of the three subagents. Record the edits in the walkthrough.

**Acceptance criteria**
1. `uv run pytest tests/test_unit/test_docs_consistency.py` passes.
2. `DESIGN.md` is unchanged since the Iteration 0 commit, as shown by `git diff`.
3. The Mermaid block in `SPECIFICATIONS.md` §4 renders: `npx -y @mermaid-js/mermaid-cli -i <extracted block> -o <scratch>.png` exits 0. If `npx` is unavailable, record that in the walkthrough and continue; this check alone is not a stop condition.

---

#### Iteration 2 — Reused modules and triaged tests

**Goal:** Approach 1's reusable modules and their tests run here unchanged, apart from the removals D-J lists. Each copied test is the Red for its module.

**Prerequisites:** Iteration 1 is complete; the Approach 1 suite passes in `../code-orchestration/`, which you only read and never modify.

**Red:** copy each test file first, then run it to confirm an `ImportError` or `ModuleNotFoundError`:

| Test file | Action |
| :--- | :--- |
| `test_unit/test_costs.py`, `test_diagnostics.py`, `test_model_factory.py`, `test_template_engine.py` | Copy as is |
| `test_integration/test_mcp_client.py`, `test_substrate_compatibility.py` | Copy as is. The second is the §7.1 drift test |
| `test_unit/test_credentials.py` | Copy as is; Iteration 4 extends it |
| `test_unit/test_schemas.py` | Copy, then **delete** the tests of `RevisionPayload`, `PipelineRun` and `ScopeParser`-only behaviour. Keep the tests of models that Iteration 4 amends: they are the baseline that Iteration 4's Red changes |
| `test_unit/test_telemetry.py` (new file) | The `estimate_cost`, `amortise_shared_telemetry`, `aggregate_draft_totals`, `_share` and `_share_capped` tests from Approach 1's `test_orchestrator.py`, with their imports repointed to `src.telemetry` |
| `tests/conftest.py`, `tests/support/scripted.py` | Copy. Remove or defer any helper that imports `src.orchestrator`, such as `ModelBuilder`, `pipeline_config` or `scripted_model_builder`, and list the deferred helpers in the walkthrough. Iteration 7 restores them against the new modules |
| `test_orchestrator.py`, `test_e2e.py` | **Do not copy** (D-J) |

**Green**
* Copy `src/costs.py`, `credentials.py`, `model_factory.py`, `diagnostics.py`, `mcp_client.py` and `template_engine.py` unchanged.
* Copy `src/schemas.py` without `RevisionPayload` and `PipelineRun`. Every other Approach 1 model stays as it is for now.
* Create `src/telemetry.py` holding `estimate_cost`, `amortise_shared_telemetry`, `aggregate_draft_totals` and their private helpers, moved verbatim from Approach 1's `orchestrator.py`.
* Add every new module to `test_module_structure.py`.

**Acceptance criteria**
1. Every copied test passes. Record their number in the walkthrough, per file.
2. `uv run pytest tests/test_integration/test_substrate_compatibility.py` passes against the live local substrate.
3. `grep -rn "orchestrator" src tests` finds no import of `src.orchestrator`.
4. The copied modules differ from Approach 1's only in import lines, which you confirm with `diff` against `../code-orchestration/src/<module>.py`. The one exception is `schemas.py`, which differs by the two removed models.

**Stop and ask if:** a copied test fails for a reason other than a missing module or a removed model. That means the two projects' environments differ.

---

#### Iteration 3 — Logging setup and correlation

**Goal:** Approach 1's logging, extracted into its own module and extended with the correlation fields D-I requires.

**Prerequisites:** Iteration 2 is complete.

**Red:**
* `tests/test_unit/test_logging.py`: copy Approach 1's logging tests, repointed to `src.logging_setup`. Change the expected file name to `logs/run_YYYYMMDD.log`, since Approach 1 wrote `pipeline_…`.
* Add new tests, in the same file:
  * `log_context(run_id=…)`, a context manager, puts `run_id` on every record written inside it, including records from the `strands`, `httpx` and `mcp` loggers. So the filter sits on the handler, not on one logger.
  * A nested `log_context(doc_id=…, attempt=…)` adds those fields, and leaving it restores the outer values. Outside every context the fields read `-`.
  * The file format includes `run_id`, `doc_id` and `attempt` on every line.
  * `--log-level` accepts `DEBUG`, `INFO`, `WARNING` and `ERROR`.
  * The API-key redaction test from Approach 1 still passes on records that carry correlation fields.

**Green**
* Create `src/logging_setup.py`, containing:
  * `configure_logging(level, log_dir, api_key=None)`, `_ApiKeyRedactionFilter`, `_resolve_log_level` and the name of the `src` logger, moved from Approach 1's `orchestrator.py`;
  * a `contextvars`-backed `log_context(**fields)` and a `CorrelationFilter` attached to every handler.

**Acceptance criteria**
1. The logging tests pass, both the copied and the new ones.
2. A test run writes one file per day, named `run_YYYYMMDD.log`.
3. The five routed loggers (`strands`, `openai`, `httpx`, `mcp`, `src`) keep `propagate = False`, as the copied test asserts.

---

#### Iteration 4 — New and amended contracts

**Goal:** every new and amended model in `SPECIFICATIONS.md` §6, test-first.

**Prerequisites:** Iteration 3 is complete; `SPECIFICATIONS.md` exists.

**Red:** one behaviour at a time, in `tests/test_unit/test_schemas.py` and `test_credentials.py`.

| Model | Tests |
| :--- | :--- |
| `AgentContext` | Holds `today: date` only |
| `PipelineScope` | Has `context: AgentContext`; `time_window` and `time_window_specified` are gone, and are ignored when supplied, since `extra="ignore"`; `max_drafts` defaults to `None`; `sources` accepts only the three `Source` values |
| `AttemptRecord` | `doc_id` is a computed field equal to `candidate.update.doc_id` and appears in every dump. `set_draft()` and `set_qa_report()` set their slot once, and a second call raises `ValueError`. The record keeps the **same** `ScoutCandidate` object it was given (`is` identity), so no copy is made |
| `AttemptRecord` views | `writer_view()` gives the whole record as JSON. `qa_view()` gives JSON **without** `candidate`, but with `doc_id`, `context`, `attempt` and `draft`. `supervisor_view()` gives a dict **without** `draft` and `candidate`, but with `doc_id`, `attempt` and `qa_report` |
| `RunContext` | Holds `today`, `max_attempts_per_doc` (default `MAX_ATTEMPTS_PER_DOC`, which is 3), `max_drafts` and `drafts_saved` |
| `DraftResult` | Holds `doc_id`, `draft_id`, `path` and `qa_status`; `writer_invocations` is gone |
| `ToolResult[T]` | Generic over `ScoutReport`, `AttemptRecord` and `DraftResult`. `error` accepts a `GuardrailViolation`, a `str` or `None`. `for_supervisor()` returns a JSON string: for an `AttemptRecord` result it applies `supervisor_view()`, so no `draft`, `candidate`, `article_body` or `headline` key appears anywhere in the JSON |
| `DocumentRecord` | The derived fields `attempts_used`, `attempts_remaining`, `latest_drafted` and `state`. `latest_drafted` skips a failed latest attempt. `state` is `saved` if `saved` is set, `audited` if `latest_drafted` has a report, `drafted` if a draft exists, and `not_drafted` otherwise |
| `RunState` | Holds the fields of `SPECIFICATIONS.md` §6.5. `arbitrary_types_allowed` for `fatal_error`. `snapshot()` returns a new `RunContext` whose `drafts_saved` is counted from `documents` |
| `StageTelemetry` | `stage` takes `supervisor`, `scout`, `writer` or `qa_legal`, and rejects `scope_parser`; `doc_id` and `attempt` are optional and default to `None` |
| `FailureStage`, `FailureRecord` | The stage list of §7.7; `FailureRecord.attempt` is optional |
| `GuardrailName`, `GuardrailViolation` | Exactly 12 names; the violation holds `guardrail`, `tool_name`, `doc_id` and `message` |
| `DraftMetadata` | `approach_name` defaults to `"Approach 2 (Research Analyst)"`; the other fields are unchanged |
| `ExitCode` | Values 0 to 6, with `SUPERVISOR_ERROR = 6`; the name `PipelineExitCode` no longer exists |
| `ReasoningSettings` | `supervisor` is read from `HSE_MODEL_SUPERVISOR_REASONING_EFFORT` and resolves to `medium` when unset. The existing `writer` and `qa_legal` tests are unchanged |
| Docs link | `MAX_ATTEMPTS_PER_DOC` equals the cap stated in `SPECIFICATIONS.md`, so the docs test now reads the constant |

**Green:** amend `src/schemas.py` and `src/credentials.py`. `ModelRate`, `AgentTelemetry`, `ToolInvocation`, `WorkerOutput`, the substrate models and the agent outputs stay untouched.

**Acceptance criteria**
1. The `schemas.py` models match `SPECIFICATIONS.md`: 27 models in total, 7 of them new, plus the four settings classes.
2. `grep -n "RevisionPayload\|PipelineRun\|PipelineExitCode\|time_window" src` finds nothing.
3. The template engine tests still pass. The template is unchanged, and `DraftMetadata` changed only its default.

---

#### Iteration 5 — Guardrail checks

**Goal:** every D-C rule and every one of the 12 guardrails, as pure functions over `RunState`, with no agents and no I/O.

**Prerequisites:** Iteration 4 is complete.

**Red:** `tests/test_unit/test_guardrails.py`, table-driven, with one case per row below plus the "allowed" cases. Each violation's `message` must name the rule and any limit, such as "3 of 3 attempts used".

| Function | Check order: the first failing check wins | Allowed cases to test |
| :--- | :--- | :--- |
| `check_scout(state, raw_scope)` → `PipelineScope \| GuardrailViolation` | `scout_already_run` (only a *successful* earlier call counts) → `invalid_scope` (a date that is not ISO `YYYY-MM-DD`, including the basic form `20260622`; `date_from` later than `date_to`; an unknown source) | A valid scope is returned with `context` filled in; after an `invalid_scope`, a corrected scope is allowed |
| `check_writer(state, doc_id, revise)` | `not_a_candidate` → `already_saved` (P2) → `attempt_limit` → if `revise=False`: `initial_draft_exists` · if `revise=True`: `not_audited` (no draft, or the latest draft has no report) → `revise_after_pass` | A first draft; a retry after a failed first call; a revision of `ERROR` or `WARNING`; a revision after a failed revision, from the earlier audited draft |
| `check_qa(state, doc_id)` | `not_a_candidate` (P3) → `already_saved` (P2) → `no_draft` → `already_audited` | An audit of the latest draft; an audit after a successful revision |
| `check_save(state, doc_id)` | `not_a_candidate` (P3) → `already_saved` → `not_audited` → `error_with_attempts_remaining` → `draft_ceiling` (`drafts_saved >= config.max_drafts`) | `PASS` or `WARNING` at any attempt; `ERROR` with no attempts remaining; an earlier audited draft when the latest call failed; no ceiling when `max_drafts is None` |

Also add the rule 8 walk-through from `SPECIFICATIONS.md` D-C ("How rule 8 plays out") as a single sequential test.

**Green:** create `src/guardrails.py`. Carry `invalid_scope`'s date logic over from Approach 1's `_validate_scope_bounds`. Validation errors raised while building a `PipelineScope` map to `invalid_scope`, with the pydantic message.

**Acceptance criteria**
1. Each of the 12 `GuardrailName` values is produced by at least one test. A test asserts that the set produced equals `get_args(GuardrailName)`.
2. None of the functions mutates `RunState`, which a test asserts by comparing `model_dump()` before and after.
3. The check order in `SPECIFICATIONS.md` §7.3 matches the table above.

---

#### Iteration 6 — Sub-agent runners and prompts

**Goal:** the Scout, Writer and QA-Legal runners each take one input model, with prompts that stay at parity with Approach 1.

**Prerequisites:** Iteration 5 is complete; `../code-orchestration/src/agents.py` is readable.

**Red:**
* `tests/test_unit/test_agents.py`: copy the Scout, QA-Legal and `extract_telemetry` tests from Approach 1, and drop the ScopeParser tests (D-J).
* Adapt the Writer and QA-Legal tests to the new inputs.
* New tests:
  * **Prompt parity** (`test_prompt_parity.py`). Parse Approach 1's `agents.py` with `ast`, never by importing it, and assert:
    * `SCOUT_SYSTEM_PROMPT` and `QA_LEGAL_SYSTEM_PROMPT` are **byte-identical**;
    * applying a declared substitution list to Approach 1's `WRITER_SYSTEM_PROMPT` gives this project's prompt exactly. The substitution list is kept in the test, and every entry is a phrase naming the Writer's input ("revision payload" → "`AttemptRecord` …").
    * The test is skipped, with a reason, when `../code-orchestration/` is absent.
  * **Model IDs and efforts** are unchanged. The Scout uses `gpt-5-mini` with no effort; the Writer uses `gpt-5.4` with effort `high`; QA-Legal uses `gpt-5.4` with effort `medium`.
  * `run_scout(agent, scope)` sends the `PipelineScope`, including `context.today`, as JSON in the user turn.
  * `run_writer(agent, record)`:
    * sends `record.writer_view()`, with the current date taken from `record.context.today`;
    * when `record.draft is None`, the user turn asks for a first draft and names `candidate.update.doc_id` for `get_document_by_id`;
    * when the record carries a draft and a QA report, the user turn gives Approach 1's revision instruction ("resolve every issue … preserve everything the audit did not object to").
  * `run_qa_legal(agent, record)` sends `record.qa_view()`. The user turn contains no `rationale` or `newsworthiness_score`, and contains neither "3 attempts" nor "max_attempts" (DM7).
  * **Tool binding (P1).** `build_scout_agent`, `build_writer_agent` and `build_qa_legal_agent` attach **all five** substrate tools by default, as in Approach 1. Each also takes an optional `hooks` sequence, which Iteration 12 fills.

**Green:** copy `src/agents.py`. Remove the ScopeParser, reword the Writer prompt through the substitution list only, and adapt the three runners. `extract_telemetry`, `_run_worker` and `_resolve_tools` stay unchanged.

**Acceptance criteria**
1. The prompt parity tests pass.
2. `diff` of `SCOUT_SYSTEM_PROMPT` and `QA_LEGAL_SYSTEM_PROMPT` against Approach 1 is empty.
3. Every runner test uses `ScriptedModel`, and `sent_text` shows the expected user turn.

**Stop and ask if:** any wording change outside an input-naming phrase seems necessary. The Scout and QA-Legal prompts, and the Writer's instructions, are benchmark constants.

---

#### Iteration 7 — Tool wrapper core and `scout_tool`

**Goal:** the shared custom agent tool pipeline (D-A), and the first tool built on it.

**Prerequisites:** Iteration 6 is complete.

**Red:** `tests/test_unit/test_tools_scout.py`, using `ScriptedModel` sub-agents and the offline or stub substrate from `tests/support/scripted.py`:
* `build_tools(state, client=…, models=…, efforts=…, hooks=())` returns four tools named exactly `scout_tool`, `writer_tool`, `qa_tool` and `save_draft`. Their input schemas match `SPECIFICATIONS.md`:
  * `scout_tool(date_from, date_to, sources, sector_constraints, max_drafts)`;
  * `writer_tool(doc_id, revise)`;
  * `qa_tool(doc_id)`;
  * `save_draft(doc_id)`.
* Declare `sources` as `list[str]` in the tool signature, so that an unknown source reaches `check_scout` and becomes `invalid_scope` rather than a schema error the wrapper never sees. Record this in the walkthrough.
* A successful call:
  * stores `state.scope`;
  * creates one `DocumentRecord` per candidate, keyed by `doc_id`, in Scout rank order;
  * appends one `StageTelemetry(stage="scout")` to the ledger;
  * returns `ToolResult[ScoutReport].for_supervisor()` holding the full report and a `RunContext` snapshot;
  * logs "Scope built by the Supervisor" and "Scout result" (D-I), and the "Sub-agent invocation started / completed" pair.
* A second call returns `scout_already_run`. An invalid scope returns `invalid_scope` and does not count as a run.
* Every violation is:
  * logged at WARNING;
  * appended to `state.violations`;
  * returned in `ToolResult.error`, with `result=None`.
* A sub-agent that raises an ordinary exception produces:
  * a `FailureRecord(stage="scout")` holding full `RemoteErrorDetail` and traceback;
  * a one-line `error` string, with no traceback, in the returned result;
  * a WARNING "Recoverable tool failure" log.
  * The Scout has not succeeded, so a retry is allowed.
* A sub-agent build or call that raises `MCPConnectionError` or `MCPClientNotConnectedError`:
  * sets `state.fatal_error`;
  * records `FailureRecord(stage="mcp_session")`;
  * logs at ERROR;
  * returns an error result. Iteration 12 adds the stop.
* A failed call still records its telemetry. When the agent was built but raised, the telemetry comes from `agent.event_loop_metrics`, so spent tokens are not lost.
* Every log line written during the call carries `run_id`.

**Green:**
* `src/tools.py`: `build_tools` and a private `_invoke_sub_agent(...)` helper that does the D-A steps in order (fresh agent → run → ledger → log → classify errors). The guardrail checks are called before the helper runs.
* Restore the deferred helpers in `tests/support/scripted.py` against the new modules; `ModelBuilder` moves to `src/model_factory.py`.

**Acceptance criteria**
1. The tests pass, and every branch of `_invoke_sub_agent` is covered by a test.
2. No `ToolResult` JSON returned in these tests exceeds the `ScoutReport` it carries plus the `RunContext`. A test checks this by key set.

---

#### Iteration 8 — `writer_tool`

**Goal:** writing and revising, with the attempt counter held in code (D-C rules 1 to 7, D-E).

**Prerequisites:** Iteration 7 is complete.

**Red:** `tests/test_unit/test_tools_writer.py`.
* **Rule 3.** The new `AttemptRecord` is appended **before** the Writer runs. A test's scripted Writer reads `state` and sees the record already present.
* **First draft** (`revise=False`). The Writer receives the new record `{context, candidate, attempt: 1}`, and its `candidate` is the same object as the `DocumentRecord`'s. On success, `draft` is set on that record.
* **Revision** (`revise=True`):
  * the Writer receives the **latest drafted** record, with its draft and QA report;
  * the output is stored on the new record, attempt n + 1;
  * INFO "Revision requested" is logged with `doc_id`, the new attempt and the QA status it follows.
* **Rule 2** (Approach 1 D23, moved here from its orchestrator). If the telemetry shows no `get_document_by_id` call, or `source_doc_id` differs from the record's `doc_id`, then:
  * the attempt keeps no draft;
  * a `FailureRecord(stage="fetch_document", attempt=n)` is stored;
  * `error` is a one-line summary, and `result` is the record without a draft.
* **Failed call.** `FailureRecord(stage="writer", attempt=n)` is stored; the attempt still counts; `result` is the draft-less record; `error` is set.
* **The result to the Supervisor** holds `doc_id`, `attempt` and an empty `qa_report`, together with `run.max_attempts_per_doc`. It holds no `draft`, `candidate` or article text.
* `StageTelemetry(stage="writer", doc_id, attempt)` is appended on success and on failure.
* All the `check_writer` violations are reachable through the tool, one test each, including `already_saved` (P2).
* Log lines inside the call carry `doc_id` and `attempt`.

**Green:** add `writer_tool` to `src/tools.py`, with the dereference check ported from Approach 1's `_verify_writer_dereferenced_source`.

**Acceptance criteria**
1. The rule 8 walk-through table's states are reproduced through the real tools: `writer_tool` followed by a stubbed QA report stored with `set_qa_report`. A failed revision leaves the earlier draft as the latest.
2. `writer_tool` never returns article text, as a test asserts over every result in the file.

---

#### Iteration 9 — `qa_tool`

**Goal:** auditing the latest draft once (D-C rule 8), with the attempt cap kept out of QA-Legal's view.

**Prerequisites:** Iteration 8 is complete.

**Red:** `tests/test_unit/test_tools_qa.py`.
* QA-Legal receives `latest_drafted.qa_view()`: no candidate, and no cap.
* The `QAReport` is stored with `set_qa_report` on the **latest drafted** record.
* The result holds the record with its `qa_report` and without draft or candidate, plus `RunContext`.
* The verdict is logged at the D-I levels: `PASS` at INFO; `WARNING` or `ERROR` at WARNING, with the issues.
* `StageTelemetry(stage="qa_legal", doc_id, attempt)` is appended.
* The violations `not_a_candidate`, `already_saved`, `no_draft` and `already_audited` each have a test.
* A failed call stores `FailureRecord(stage="qa_legal", attempt)`, leaves `qa_report` empty so that a retry is allowed, and returns an error string.

**Green:** add `qa_tool` to `src/tools.py`.

**Acceptance criteria**
1. After a successful revision, `qa_tool` is allowed again; after a failed revision, it returns `already_audited`.
2. No QA-Legal user turn in the tests contains the attempt cap.

---

#### Iteration 10 — `save_draft` and draft ID allocation

**Goal:** marking a document saved. Nothing is written to disk until run end (D-B, §7.8).

**Prerequisites:** Iteration 9 is complete.

**Red:**
* `tests/test_unit/test_rendering.py::allocate_draft_id`. With an empty folder, two saves in one run give `draft_YYYYMMDD_001` and `_002`. With `_004.md` already on disk, they give `_005` and `_006`. The allocator counts the IDs allocated earlier in the run, not only the files on disk. The date comes from `state.context.today`.
* `tests/test_unit/test_tools_save.py`:
  * success sets `DocumentRecord.saved = DraftResult(doc_id, draft_id, path, qa_status)`, with `path` equal to `config.drafts_dir / f"{draft_id}.md"`;
  * **no file is created**;
  * `RunContext.drafts_saved` rises by 1 in the returned snapshot;
  * INFO "Document marked saved" is logged with `doc_id`, the draft ID, the QA status and the attempts.
* Every `check_save` violation has a test, including `draft_ceiling` with `--max-drafts 1` and `error_with_attempts_remaining`.
* An `ERROR` at the cap is saved.

**Green:** add `allocate_draft_id` to `src/rendering.py`, reusing `generate_draft_id`'s disk scan, and add `save_draft` to `src/tools.py`.

**Acceptance criteria**
1. `drafts_dir` holds no new file after any `save_draft` test.
2. The four tools are complete, and `test_module_structure.py` lists `src.tools`, `src.guardrails` and `src.rendering`.

---

#### Iteration 11 — End-of-run reconciliation and rendering

**Goal:** everything code does after the Supervisor finishes (D-B, D-C "Unfinished candidates", §7.8).

**Prerequisites:** Iteration 10 is complete.

**Red:** `tests/test_unit/test_rendering.py`, testing `finalise_run(state, *, supervisor_telemetry, rates)`:
* **Supervisor entry.** One `StageTelemetry(stage="supervisor")` is appended when telemetry is given. When it is `None` because the Supervisor raised and no metrics could be read, a WARNING is logged and no entry is added.
* **Unfinished candidates.** Each candidate left unsaved is logged at WARNING with its last state (`not drafted`, `drafted` or `audited`).
* **`DraftMetadata` per saved document**, in save order:
  * the source fields come from `candidate.update`, mapped as Approach 1's `_build_draft_metadata` maps them;
  * `qa_report` is the saved draft's report;
  * `attempts = attempts_used`;
  * `stage_telemetry` holds the document's own `writer` and `qa_legal` entries **plus** an equal share of the `scout` and `supervisor` entries, using `amortise_shared_telemetry`;
  * `estimated_cost` and `total_tokens` come from those entries;
  * `unresolved_errors = qa_report.issues` when the status is `ERROR`.
* **Totals add up.** The sum of the per-draft tokens equals the sum of the saved documents' own entries plus all of the shared entries. Tokens spent on unsaved documents appear only in the logged run total.
* **Rendering.** Each saved draft is rendered with `render_draft` into `.agents/templates/draft.md` and written to its allocated `path`. An `ERROR` draft carries `[UNRESOLVED COMPLIANCE ALERT]` and a WARNING log. INFO "Draft rendered" is logged with the draft ID, path, `doc_id`, tokens and cost.
* **Render failures.** A render or write failure records `FailureRecord(stage="render" | "persist")`, logs at ERROR, and **continues** with the other drafts. `finalise_run` reports that persistence failed.
* **Run totals.** Tokens, cost and wall-clock are logged once at INFO and not stored on `RunState` (DM18).
* **The drafted text is right.** The rendered draft is the `latest_drafted` of the saved document, which by P2 is the draft that was saved.

**Green:** add `finalise_run` and its helpers to `src/rendering.py`, and any cost-share adapter to `src/telemetry.py`.

**Acceptance criteria**
1. A rendered test draft contains no unresolved template token.
2. `approach_name` renders as `Approach 2 (Research Analyst)`.
3. The per-draft cost equals `estimate_cost` over that draft's `stage_telemetry`, to within 1e-9.

---

#### Iteration 12 — SDK spike: fatal stop and logging hooks

**Goal:** settle the two open SDK questions (D-D, D-I) with characterisation tests against the installed `strands-agents 1.55.1`, then build `src/hooks.py`.

**Prerequisites:** Iteration 11 is complete.

**Spike, part (a): fatal stop.** Write `tests/test_unit/test_sdk_contract.py`. A `ScriptedModel` "supervisor" calls a tool that records a fatal error; its script would then call a second tool and send one more turn. Try these mechanisms **in this order** and keep the first that passes every assertion:

1. An `AfterToolCallEvent` hook calls `event.agent.cancel()` when `state.fatal_error` is set. In 1.55.1, `Agent.cancel()` stops "after tool execution, before the next model call", with `stop_reason="cancelled"`.
2. The tool is declared with `@tool(context=True)` and sets `request_state["stop_event_loop"] = True`; the event loop checks this flag after tool execution.
3. A `BeforeToolCallEvent` hook cancels every later tool call, combined with option 2.

The assertions:
* the second tool never runs;
* the model is not called again after the fatal tool;
* control returns to the caller without an unhandled exception, or with one exception type that the composition root can map to `MCP_ERROR`;
* `state.fatal_error` is still set.

Record the chosen mechanism and the evidence in `SPECIFICATIONS.md` D-D, and in its §8.4 as D-D.1.

**Spike, part (b): logging hooks.** The characterisation tests assert:
* `AfterModelCallEvent` fires once per model call, and its stop reason and token usage can be read. If usage is not on the event, read it from `agent.event_loop_metrics`, and record which one is used.
* `BeforeToolCallEvent` and `AfterToolCallEvent` fire for the Supervisor's tools **and** for the MCP tools called inside a sub-agent, when the hooks are passed to that sub-agent.
* `SequentialToolExecutor` exists at the import path you use. With it, two tool uses in one model turn run one after another; with the default executor, they run concurrently.

**Red, then Green: `src/hooks.py`**
* `LoggingHooks(role)` writes:
  * "Model HTTP call" (agent, stop reason, tokens);
  * "Tool call started / completed" (tool name, calling agent, `doc_id` from the log context, duration, outcome);
  * for the Supervisor only, "Supervisor turn completed" (turn number, stop reason, tools requested, tokens, text).
* `FatalStopHook(state)`, using the mechanism chosen in part (a).
* `build_tools` passes `LoggingHooks(<role>)` to every sub-agent it builds.

**Acceptance criteria**
1. The SDK contract tests pass. They are kept permanently, so an SDK upgrade that breaks one of these behaviours fails loudly.
2. `writer_tool` with a stub transport that dies stops a scripted Supervisor within one tool call.

**Stop and ask if:** none of the three mechanisms passes (§1.4 item 3).

---

#### Iteration 13 — Supervisor agent

**Goal:** the agent that owns the flow. Its prompt carries the scope rules, the decision policy and the limits; code still enforces the hard rules.

**Prerequisites:** Iteration 12 is complete.

**Red:** `tests/test_unit/test_supervisor.py`.
* `build_supervisor_agent(model, tools, *, max_drafts, hooks)`:
  * uses `SequentialToolExecutor`;
  * has exactly the four tools;
  * is built on the strong `gpt-5.4` binding, with the effort from `ReasoningSettings.supervisor` (default `medium`);
  * `callback_handler=None`.
* **The system prompt** contains:
  * **Role:** the division of labour. The Supervisor supervises agents, not drafts. It never reads, judges or edits article text, never writes feedback for the Writer, and never writes Markdown.
  * **Scope rules:** how to build `date_from`, `date_to`, `sources`, `sector_constraints` and `max_drafts` from the prompt. These are adapted from Approach 1's ScopeParser prompt:
    * resolve dates against the current date given in the user turn;
    * default to the past 3 months when no window is named;
    * `date_to` is the current date unless the user named an end date;
    * an empty `sources` list means all sources;
    * `max_drafts` only for a stated count or a singular definite request.
    * The `time_window` rules are dropped.
  * **The decision table,** row for row as in D-C, and the rule never to compare QA reports across attempts.
  * **Run-level priorities:** finish documents before starting new ones; respect the draft ceiling.
  * **Limits:** 3 Writer attempts per document, read from `RunContext`, and the `--max-drafts` value, or the words "no ceiling" when it is `None`.
  * **Violations:** a violation is not the end of the run; read its message and decide again.
  * **Finishing:** end with a plain-text summary of the documents saved, skipped and left unfinished.
* **The system prompt does not contain** the current date, which goes in the user turn. The Supervisor is also never told to review, score or improve article text, which a list of forbidden phrases checks.
* **`run_supervisor(agent, prompt, *, today)`:**
  * the user turn is `Current date: YYYY-MM-DD` followed by the raw prompt, verbatim;
  * it returns the final text as `supervisor_summary`, plus `AgentTelemetry` whose `tool_invocations` count the four tools.
* **Scripted Supervisor flow.** A scripted Supervisor that calls `scout_tool` → `writer_tool` → `qa_tool` → `save_draft` over scripted sub-agents leaves one saved `DocumentRecord` in `RunState`.

**Green:** create `src/supervisor.py`, holding `SUPERVISOR_MODEL_ID`, `SUPERVISOR_REASONING_EFFORT`, the prompt builder, `build_supervisor_agent` and `run_supervisor`.

**Acceptance criteria**
1. Each row of the D-C decision table appears in the prompt, which a test checks against a list of the rows taken from `SPECIFICATIONS.md`.
2. The Supervisor's tool descriptions match `SPECIFICATIONS.md` §7.1 word for word, and the prompt covers every item in §7.4.
3. `SPECIFICATIONS.md` D-C and the prompt agree on the attempt cap and the priorities, as the docs test checks.

**Stop and ask if:** a decision-table row cannot be written as a prompt instruction without adding a new rule.

---

#### Iteration 14 — Composition root and CLI

**Goal:** one run, from CLI prompt to exit code (the `SPECIFICATIONS.md` §4 activity flow).

**Prerequisites:** Iteration 13 is complete.

**Red:**
* `tests/test_integration/test_app.py`, with scripted models and the live local substrate. `run(prompt, config, *, client_factory, model_builder, clock, reasoning_settings)` returns `RunState` with `exit_code` and `supervisor_summary` set.
* **Session.** Exactly one `with HSEMockMCPClient()` per run. The exit-code mapping sits **outside** the `with`, as in Approach 1, so the subprocess always ends first.
* **Models.** Four models are built once per run: the Scout on the fast binding; the Writer (`high`), QA-Legal (`medium`) and Supervisor (`medium`) on the strong binding. Agents are rebuilt per call.
* **Logging.** A `run_id` is generated per run, and `log_context(run_id=…)` wraps the whole run. INFO "Run started" and "Run completed" are logged with the fields in the D-I catalogue, and "MCP session opened" with the number of tools.
* **Exit codes,** combined by numeric maximum (P6):

  | Condition | Code |
  | :--- | :--- |
  | Settings cannot be resolved (credentials or rates); the run never starts | `CONFIG_ERROR` (5) |
  | The session fails to open, or `state.fatal_error` is set | `MCP_ERROR` (2) |
  | The Supervisor raises a provider or SDK error | `SUPERVISOR_ERROR` (6) |
  | The Supervisor finishes and `state.scope is None` | `PARSER_ERROR` (3) |
  | The Scout succeeded with zero candidates | `NO_UPDATES` (1) |
  | `finalise_run` reports a render or write failure | `PERSISTENCE_ERROR` (4) |
  | Otherwise, whatever the number of drafts saved | `SUCCESS` (0) |

* **`finalise_run` always runs** once a `RunState` exists, including after `SUPERVISOR_ERROR` and `MCP_ERROR`, so documents already saved are rendered.
* `tests/test_unit/test_cli.py`:
  * `build_arg_parser()` matches the CLI specification in `SPECIFICATIONS.md`;
  * `main(argv, runner=…, log_dir=…, api_key=…)` configures logging, calls the runner and returns the exit code as an `int`;
  * `python -m src.cli --help` exits 0.

**Green:** create `src/app.py` and `src/cli.py`. Port `build_config` and `_resolve_redaction_key` from Approach 1's `orchestrator.py`.

**Acceptance criteria**
1. Every row of the exit-code table has a test.
2. `uv run python -m src.cli --help` prints the four arguments.
3. The CLI tests make no live model call: they inject `runner` or a scripted `model_builder`.

---

#### Iteration 15 — Scripted end-to-end scenarios

**Goal:** the whole system, with a scripted Supervisor and scripted sub-agents over the live local substrate, and zero tokens. Because the path is decided at runtime, the tests assert **guardrails, persisted outcomes and log events**, never exact call sequences (`SPECIFICATIONS.md` D-J).

**Prerequisites:** Iteration 14 is complete.

**Red, then Green:** `tests/test_integration/test_supervisor_e2e.py`. One test per scenario. Each asserts: the files in `drafts/`, their QA status and attempts, `RunState.violations`, `RunState.failures`, the exit code, and the D-I events expected for that scenario, read from the log file.

| # | Scenario | Key assertions |
| :---: | :--- | :--- |
| 1 | Happy path: two candidates, both `PASS` at attempt 1 | Two drafts; exit 0; per-draft tokens plus unsaved tokens add up to the run total |
| 2 | Revision cap: `ERROR` three times | One draft with the banner; attempts 3; WARNING "Draft rendered with [UNRESOLVED COMPLIANCE ALERT]" |
| 3 | `WARNING` with a substantive issue → revise → `PASS` | Attempts 2; "Revision requested" follows `WARNING` |
| 4 | `WARNING` with advisory issues only → save | Attempts 1; status `WARNING` |
| 5 | Writer fails, no draft → retry → `PASS` | `FailureRecord(stage="writer", attempt=1)`; attempts 2 |
| 6 | A revision fails → the earlier draft is saved | The rendered text is the earlier draft's; attempts 2 |
| 7 | Writer fails three times | No draft; WARNING "Candidate left unsaved" |
| 8 | Guardrail violations: revise a `PASS`; save an `ERROR` with attempts left; re-audit; restart a drafted document; a non-candidate; writer after save (P2); `--max-drafts 1` exceeded | Each violation is returned, logged at WARNING and stored; the run continues to exit 0 |
| 9 | The same violation five times in a row | All five are logged and stored; none is bounded (DM16) |
| 10 | MCP transport dies after one save | The saved draft is rendered; exit 2; no model call after the fatal tool |
| 11 | The Supervisor provider fails (`FailingModel`) after one save | The saved draft is rendered; exit 6; ERROR "Supervisor invocation failed" with `RemoteErrorDetail` |
| 12 | Scout finds nothing | Exit 1; no draft |
| 13 | The Supervisor never calls `scout_tool`; separately, an invalid scope is corrected and retried | Exit 3; in the second case, the retry succeeds |
| 14 | Draft files already exist for today | New IDs continue the sequence, with no overwrite |
| 15 | **D-F:** article text never reaches the Supervisor | No message the scripted Supervisor model received contains any `headline`, `article_body` or `executive_summary` from the scripted Writer |

Scenarios 3 to 7 check that **code** handles each decision-table path correctly. In these tests the Supervisor's choices are scripted, so whether a real model chooses well is measured only by the live tests (Iteration 16).

**Acceptance criteria**
1. All 15 scenarios pass in the default run. Each runs in under 60 s, which you record in the walkthrough.
2. Every event in the D-I catalogue is asserted by at least one scenario, except `DEBUG` request bodies. A test compares the catalogue's event names with the set asserted.

---

#### Iteration 16 — Live end-to-end tests and benchmark report (built, not run)

**Goal:** everything the user needs to run the live benchmark. **The executing agent does not run any live test or live CLI command in this iteration.**

**Prerequisites:** Iteration 15 is complete.

**Red, then Green**
* **`tests/test_live/test_live_e2e.py`**, every test marked `@pytest.mark.live`:
  * **Opt-out of isolation.** The tests opt out of `conftest.py`'s environment isolation through the marker.
  * **Skip rule.** They skip, with a reason, when `agent-orchestration/.env` is absent.
  * **Prompt A:** `Analyze INAIL updates on heat stress published since 2024`. This is Approach 1's benchmark prompt, which gave 3 drafts, 223,970 tokens and $0.7803 on 2026-09-24. Assert:
    * exit 0 and at least one draft;
    * no unresolved token in any draft;
    * attempts ≤ 3 per draft;
    * every `ERROR` draft carries the banner;
    * every draft's `approach_name` is `Approach 2 (Research Analyst)`;
    * no guardrail violation ended the run.
  * **Prompt B:** `Analyze recent INAIL updates on heat stress`. The corpus ends on 2024-07-24, so the default 3-month window finds nothing; assert exit 1 (`NO_UPDATES`).
  * **Role-bleed audit (P1):** no sub-agent's `tool_invocations` contains a substrate tool that its own prompt declares a non-goal, as in Approach 1's Phase 7 audit.
* **`src/benchmark.py`** with `python -m src.benchmark --a1 ../code-orchestration/drafts --a2 drafts --out .agents/docs/BENCHMARK.md`:
  * it parses each draft's telemetry section and each run's "Run completed" log line;
  * it reports only Approach 1's metrics (Q8 = D): cost, time and tokens per draft, QA status, attempts, and run wall-clock;
  * it labels the columns *Content Factory* and *Research Analyst* (Q9 = C).
  * Unit-test it offline in `tests/test_unit/test_benchmark.py` against fixture drafts in `tests/fixtures/`. Use copies of two Approach 1 drafts and one hand-made Approach 2 draft.
* **`README.md`**: setup, `.env` from `.env.example`, the CLI, and a **"Running the live benchmark"** section giving the user's commands:
  * `uv run pytest -m live`;
  * `uv run python -m src.cli "<prompt>"`;
  * `uv run python -m src.benchmark …`.

**Acceptance criteria**
1. `uv run pytest` (the default run) deselects every live test: the summary shows them as deselected and none executed.
2. `uv run pytest -m live --collect-only -q` lists the live tests. This command only collects tests, so no model is called. It is the only `-m live` command the agent may run.
3. The benchmark unit tests pass offline.
4. §3 of this plan shows every iteration `✅ Complete`, and the walkthrough says the live run is **pending the user's trigger**.

---

### 6. Traceability

| `SPECIFICATIONS.md` source | Implemented in iterations |
| :--- | :--- |
| §1.1 Division of labour | 13 (prompt), 15 (scenario 15) |
| §4 Activity flow | 14, 15 |
| D-A Custom agent tools | 7, 8, 9, 10 |
| D-B Ledger, cost sharing, render at run end | 7, 11, 15 (scenario 1) |
| D-C Guardrails, decision policy | 5, 8, 9, 10, 13, 15 |
| D-D Fatal errors | 7, 12, 14, 15 (scenarios 10 and 11) |
| D-E Revision handoff | 8 |
| D-F No article text for the Supervisor | 4 (views), 8, 15 (scenario 15) |
| D-G Stateless sub-agents | 6, 7 |
| D-H Sequential execution, effort `medium` | 4, 12, 13 |
| D-I Logging | 3, 7 to 12, 14, 15 |
| D-J Reuse and test triage | 2, 6 |
| §6 Data model | 4 |
| §7 Interfaces | 5 (check order), 7 to 10 (tools), 13 (prompt), 14 (CLI, exit codes) |
| §8 Decision log | 1 (docs tests); new P-decisions as they arise |
| P1 to P6 | 1, 5, 6, 8, 9, 14, 16 |
| P7 | 2, 6, 16 |
| P8 | 2 |
| P9 | 7 |
| P10 | 3 |
