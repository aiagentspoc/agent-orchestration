# Instructions for AI Coding Assistants (`AGENTS.md`)
## Project: HSE Easy — Approach 2 (Research Analyst)

This is the **agent-orchestration** repository. It builds the same editorial product as Approach 1 — Italian and EU HSE regulatory updates turned into audited, TDI-branded draft articles — under a different control model: **an agent owns the flow.** A Supervisor Agent receives the user's prompt, plans the run, and calls the Scout, Writer and QA-Legal sub-agents as tools.

This file is harness-neutral. It states the rules every AI coding assistant follows in this repository, whichever harness runs it, and points to the documents that hold the detail. Where this file and those documents disagree, the documents win, and the disagreement is a stop condition (Rule 8).

---

### 1. Sources of truth

| Document | What it settles |
| :--- | :--- |
| [SPECIFICATIONS.md](.agents/docs/SPECIFICATIONS.md) | **The specification, and the single source of truth.** Benchmark constants and division of labour (§1), the multi-agent pattern (§3), the activity flow (§4), decisions D-A to D-J (§5), the data model (§6), the interfaces (§7) and the decision log (§8) |
| [IMPLEMENTATION_PLAN.md](.agents/docs/IMPLEMENTATION_PLAN.md) | The build sequence: the execution protocol and Definition of Done (§1), decisions P1 to P12 (§2), the iteration tracker (§3), the target layout and the allowed dependencies (§4), and each iteration's tests and acceptance criteria (§5) |
| [DESIGN.md](.agents/docs/DESIGN.md) | The concept and the component roles |
| [draft.md](.agents/templates/draft.md) | The draft template, held constant with Approach 1 |

**Approach 1 (reference project)** is `../code-orchestration/`, the folder next to this one. It is **read-only**: its `src/`, `tests/`, `uv.lock` and drafts are the baseline this project reuses and is benchmarked against. The substrate server, `../mcp-server/`, is read-only too.

#### 1.1 Layout and placement rule

```text
agent-orchestration/
├── AGENTS.md                  <-- You are here (harness-neutral rules)
├── CLAUDE.md                  <-- Claude Code entry point (thin pointer to this file)
├── .agents/                   <-- HARNESS-NEUTRAL: true about the project, whichever assistant runs
│   ├── docs/                  <-- DESIGN.md, SPECIFICATIONS.md, IMPLEMENTATION_PLAN.md
│   ├── skills/                <-- architect-review/ and code-reviewer/: the review criteria
│   ├── tasks/                 <-- QUESTIONS.md and one iteration-NN/ folder of artifacts per iteration
│   └── templates/             <-- draft.md, the draft template
├── .claude/                   <-- CLAUDE CODE ONLY: how this harness acts on the above
│   ├── agents/                <-- architect, implementation and qa subagent definitions
│   ├── skills/implement/      <-- the /implement workflow
│   └── settings.json          <-- read access to the two sibling folders; MCP servers enabled
├── .mcp.json                  <-- MCP server registration (hse-easy-mock, strands-agents)
├── src/  tests/               <-- the product and its tests
└── drafts/  logs/             <-- run artefacts, git-ignored apart from .gitkeep
```

The modules the plan builds, and where each one goes, are listed in `IMPLEMENTATION_PLAN.md` §4.

**Placement rule:** a file that states something true about the project belongs in `.agents/`: docs, review skills, tasks and templates. A file that exists only to tell one harness *how* to act on that truth belongs in that harness's directory; for Claude Code that is `.claude/`, which holds the subagents and `/implement`.

The workflow files:

| File | Role |
| :--- | :--- |
| [architect-review/SKILL.md](.agents/skills/architect-review/SKILL.md) | Architecture and conventions review criteria (harness-neutral) |
| [code-reviewer/SKILL.md](.agents/skills/code-reviewer/SKILL.md) | Quality gates: TDD, zero-token testing, contracts, guardrails, telemetry (harness-neutral) |
| [architect.md](.claude/agents/architect.md) | Claude Code subagent: pre-flight review and architecture audit |
| [implementation.md](.claude/agents/implementation.md) | Claude Code subagent: incremental TDD implementation and fix mode |
| [qa.md](.claude/agents/qa.md) | Claude Code subagent: verification of tests, acceptance criteria and contracts |
| [implement/SKILL.md](.claude/skills/implement/SKILL.md) | Claude Code `/implement` workflow: the four stages, the fix loop, the walkthrough and the commit |

---

### 2. Product rules — constraints on the code you write

> [!NOTE]
> **"An agent owns the flow"** is the architectural principle of the product, not a directive about how you, the coding assistant, sequence your own work. It governs the Supervisor and the tools it calls. It is specified in `SPECIFICATIONS.md` §1 and §3.

#### Rule 1: The contracts are in `SPECIFICATIONS.md`
* Every model, tool signature, tool description, result shape, guardrail name and exit code is defined in `SPECIFICATIONS.md` §6 and §7, and every log event in its D-I catalogue. Implement them exactly.
* All models are Pydantic v2 with `model_config = ConfigDict(extra="ignore")`; `RunState` alone also allows arbitrary types, for its exception slot. No unstructured dictionary crosses a module boundary.
* Anything the Supervisor or a sub-agent sees — tool names, parameters, descriptions, prompts and result shapes — is a contract, never a free choice.

#### Rule 2: The Supervisor supervises agents, not drafts
* **The Supervisor decides the path.** It chooses the candidates, whether to revise or save, and when to finish, by calling its four tools. Code never sequences the sub-agents: no loop over Writer and QA-Legal, no status-driven revision in code, no Strands Graph, Swarm or Workflow.
* **Code only refuses.** A guardrail refuses a call and says why; it never chooses the next step. A fatal error stops the run; it never reroutes it (D-D).
* **The Supervisor never sees article text** (D-F). Full drafts stay in `RunState`; the Supervisor receives the `ToolResult` views defined in `SPECIFICATIONS.md` §7.2. It writes no feedback for the Writer and no Markdown, and it has no direct substrate access.
* The division of labour is `SPECIFICATIONS.md` §1.1.

#### Rule 3: The attempt cap and the guardrails are enforced in code
* **The attempt cap is `MAX_ATTEMPTS_PER_DOC = 3`:** 3 Writer attempts per document, an initial draft plus up to two revisions. Every `writer_tool` call counts, whether it succeeds or fails, because an attempt is appended before the Writer runs.
* **The guardrails** are the 12 `GuardrailName` values of `SPECIFICATIONS.md` §6.7, implemented as pure functions over `RunState` and checked in the order of §7.3. Their rules are D-C.
* **A violation never ends the run.** It is returned in `ToolResult.error`, logged at WARNING and stored on `RunState.violations`, and the Supervisor decides again.

#### Rule 4: The benchmark constants do not move
Orchestration is the only intentional variable between the two approaches. `SPECIFICATIONS.md` §1 lists what is held constant: the substrate, the models and efforts, the tool binding (all five substrate tools on every sub-agent, as in Approach 1; each prompt draws the boundary, P1), the prompts, the template, the cost basis and sequential execution. The Scout and QA-Legal prompts are byte-identical to Approach 1's; the Writer prompt changes only where it names its input.

#### Rule 5: Drafts are Markdown, rendered at run end
* `save_draft` only marks a document saved and allocates its draft ID. Code renders every saved draft once the Supervisor finishes, so each draft's cost includes its share of the Scout and the Supervisor (D-B).
* Drafts are self-contained Markdown files, `drafts/draft_YYYYMMDD_XXX.md`, rendered with the exact placeholders of `.agents/templates/draft.md`. There is no JSON store.
* A draft saved with `ERROR` at the cap carries the `[UNRESOLVED COMPLIANCE ALERT]` banner, as in Approach 1.

#### Rule 6: Telemetry and logging follow Approach 1
* `extract_telemetry` is the only reader of `AgentResult.metrics.get_summary()`. Every sub-agent call appends one `StageTelemetry` entry to the run ledger, on failure as well; the Supervisor gets one entry at run end.
* Cost uses Approach 1's three-rate cost model, unchanged. Each draft's cost is its own Writer and QA-Legal calls plus an equal share of the Scout and the Supervisor. Run totals are logged, not stored.
* Logging is Approach 1's, extracted into its own module: one dated file, `logs/run_YYYYMMDD.log`, full-fidelity errors and API-key redaction. Every line carries `run_id`, and `doc_id` and `attempt` where relevant. The event catalogue is D-I.

---

### 3. Working rules — constraints on how you work

#### Rule 7: Strict test-driven development
* **Red, Green, Refactor, one behaviour at a time.** Write the tests for one behaviour, run them and confirm they fail **for the expected reason**; write the smallest change that makes them pass; then clean up with the suite green. Never write all the tests first.
* **No untested production code.** Every function and branch in `src/` is exercised by a test.
* Unit tests live in `tests/test_unit/`; integration tests, which may use the local substrate, in `tests/test_integration/`.
* Complete PEP 484, 585 and 604 annotations, imports at the top of the file, and `pathlib.Path` for every path.

#### Rule 8: Stop and ask, instead of approval gates
* There is **no human approval gate.** Each iteration's section in `IMPLEMENTATION_PLAN.md` is its approved plan, and its acceptance criteria take the place of sign-off.
* **Stop only for a stop condition** of `IMPLEMENTATION_PLAN.md` §1.4: the sources conflict or are silent on a contract, guardrail, prompt, benchmark constant or exit code; an acceptance criterion cannot be met; the Iteration 12 spike finds no working mechanism; an action is out of scope; or a review subagent cannot be spawned. Write the question to `.agents/tasks/QUESTIONS.md` in the plan's format and end the turn.
* **Decide what §1.5 allows** — private helper names, test organisation, log wording, docstrings, test order — and record it. Do not guess past anything else.

#### Rule 9: Review subagents, with zero fallback
* The architect, implementation and qa roles run as genuinely separate subagents during their stages of the iteration workflow. Acting out a role in your own context is a prohibited fallback, however much faster.
* If a subagent cannot be spawned, that is stop condition 5: record the question and halt.
* Harness binding: under Claude Code the roles are defined in `.claude/agents/`, dispatched by the `/implement` workflow, and judged against the two review skills in `.agents/skills/`.

#### Rule 10: No live model calls (P4)
* Neither the implementation nor the default test suite ever calls a real model endpoint. Every model in a test is a scripted or failing model from the scripted harness, injected through the `model_builder` seam (Approach 1's D16).
* Live end-to-end tests carry `@pytest.mark.live` and are deselected by default. **Only the user runs them.** The one live command an assistant may run is `uv run pytest -m live --collect-only`.
* The local `hse-easy-mock` substrate over stdio is not a live run and may be used freely.
* Never modify `../code-orchestration/`, `../mcp-server/` or the git remote. Each iteration is committed on the local branch `approach-2/implementation` and never pushed (P5).

---

### 4. MCP servers

Both are registered in `.mcp.json` and enabled in `.claude/settings.json`.

#### `hse-easy-mock` — the local regulatory substrate, over stdio
Served by `../mcp-server/server.py`, launched with `uv run --directory <mcp-server> fastmcp run server.py`. Its five tools are the substrate every sub-agent is connected to:

| Tool | Returns |
| :--- | :--- |
| `list_regulatory_updates(source, date_from, date_to, limit)` | `list[RegulatoryUpdateSummary]` |
| `search_regulatory_docs(query, source, topic, sector)` | `list[RegulatoryUpdateSummary]` |
| `get_document_by_id(doc_id)` | `RegulatoryDocument` |
| `verify_legal_citation(citation, source)` | `CitationVerificationResult` |
| `get_tdi_service_offerings(topic, sector)` | `list[TDIServiceOffering]` |

The return models are the hard constraint of `SPECIFICATIONS.md` §6.1.

#### `strands-agents` — Strands SDK documentation search
`search_docs(query, k)` and `fetch_doc(uri, section)`. Confirm the SDK surface there before coding against it; the installed `strands-agents 1.55.1`, the version Approach 1 locks, has the final word.

---

### 5. Commands

```bash
uv sync --extra dev                       # install the locked environment
uv run pytest                             # the default suite; live tests are deselected
uvx ruff check src tests                  # lint
uv run pytest -m live --collect-only      # the only live command an assistant may run
```

The CLI, `python -m src.cli PROMPT`, is built in Iteration 14; its arguments are in `SPECIFICATIONS.md` §7.5.
