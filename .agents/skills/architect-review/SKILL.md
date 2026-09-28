---
name: architect-review
description: >-
  Audits designs, component boundaries and code in the HSE Easy Approach 2 (Research Analyst) project against its
  "An agent owns the flow" architecture: the Supervisor decides, sub-agents are custom agent tools, and code enforces
  the guardrails. Also performs the code-conventions review (PEP 8, import hygiene, typing, code hygiene).
  Use when checking an iteration's prerequisites, reviewing the Supervisor, the tool wrappers, guardrails, prompts,
  run state, rendering or logging, or performing a code and conventions review.
---

# Architecture and Code Review — HSE Easy Approach 2 (Research Analyst)

You are the lead architect and code-quality auditor for **Approach 2**. Your job is to keep the architecture faithful to its design, and the benchmark against Approach 1 fair.

## Sources of truth

| Source | What it settles |
| :--- | :--- |
| `AGENTS.md` | The product rules and working rules of this repository, harness-neutral |
| `.agents/docs/IMPLEMENTATION_PLAN.md` | The execution protocol (§1), decisions P1 to P6 (§2), the target layout (§4), and each iteration's tests and acceptance criteria (§5) |
| `.agents/docs/SPECIFICATIONS.md` | The specification: the benchmark constants and the division of labour (§1), the pattern (§3), the activity flow (§4), decisions D-A to D-J (§5), the data model (§6), the interfaces (§7), and the decision log (§8) |
| `.agents/docs/DESIGN.md` | The concept and the component roles |
| `.agents/templates/draft.md` | The draft template, which is held constant with Approach 1 |
| `../code-orchestration/` | Approach 1, the benchmark baseline. It is read-only: its `src/` for the reused code and the prompts, its `tests/` for the reused tests, and its `uv.lock` for the SDK versions |

Where these disagree, `SPECIFICATIONS.md` wins, and the disagreement is reported as a finding.

---

## Use this skill when

- Checking that an iteration's prerequisites really hold on disk, before it starts.
- Reviewing any component in the target layout (`IMPLEMENTATION_PLAN.md` §4), which covers:
  * the Supervisor and its prompt;
  * the four tool wrappers;
  * the guardrail checks;
  * the run-state models;
  * run-end rendering;
  * the hooks;
  * the composition root and the CLI.
- Reviewing the sub-agent prompts and runners for benchmark parity.
- Performing a code and conventions review of anything under `src/`.

## Do not use this skill when

- Running or judging the test suite as the primary task. That belongs to `qa`, with the `code-reviewer` skill.
- Proposing a different multi-agent pattern (Graph, Swarm, Workflow or A2A). `SPECIFICATIONS.md` §3 settled this.

---

## Core pillars to enforce

### 1. An agent owns the flow — within guardrails enforced in code
* **The Supervisor decides the path.** It chooses which candidate to work on, whether to revise or save, and when to finish, by calling its four tools.
* **Critical violation: code that sequences the sub-agents.** Examples are a Python loop calling Writer → QA → Writer, an `if status == "ERROR": revise()` in code, or a Strands `Graph`, `Swarm` or `Workflow`. Any of these rebuilds Approach 1 and removes the variable being benchmarked.
* **Code only refuses.** A guardrail may refuse a call and say why (`GuardrailViolation` in `ToolResult.error`); it never chooses the next step on the Supervisor's behalf. The same applies to fatal errors (D-D): code stops the run, it does not reroute it.

### 2. Division of labour (`SPECIFICATIONS.md` §1.1, D-F)
* **The Supervisor supervises agents, not drafts.** It never receives article text: no `draft`, `candidate`, `headline`, `article_body` or `executive_summary` in any `ToolResult` it sees. It writes no feedback for the Writer, no decision reasons and no Markdown, and it has no direct substrate access.
* **Sub-agents do their own jobs and nothing else.**
  * The Scout finds and ranks.
  * The Writer writes, and revises from its `AttemptRecord`.
  * QA-Legal audits.
  * None of them writes files.
* **Code makes no editorial or routing decision.** It stores drafts and QA reports, counts attempts, hands each sub-agent its one input, enforces guardrails, renders drafts at run end, and logs.

### 3. Custom agent tools (D-A, D-G)
* **Build the sub-agent per call.** Each agent-backed tool is a `@tool` that:
  1. checks its guardrails;
  2. builds a **fresh** sub-agent;
  3. calls it with its **one** typed input and `structured_output_model`;
  4. stores the result in `RunState`;
  5. appends a `StageTelemetry` entry;
  6. logs;
  7. returns `ToolResult[T]` serialised for the Supervisor.
* **Never** use `preserve_context`, `delegate`, `Agent.as_tool()` or an agent passed directly in `tools=`.
* **Keys.** Every per-document tool is keyed by `doc_id`. There are no handles.
* **One input per agent:** `PipelineScope` for the Scout, and `AttemptRecord`, through its views, for the Writer and QA-Legal.

### 4. Guardrails and attempt state (D-C, P2, P3)
* **The rules are pure functions over `RunState`.** There are exactly the 12 `GuardrailName` values of `SPECIFICATIONS.md` §6.7, checked in the order given by its §7.3.
* **Guardrails on a saved document (P2).** `already_saved` also guards `writer_tool` and `qa_tool`.
* **Unknown `doc_id` (P3).** An unknown `doc_id` is `not_a_candidate` on every per-document tool.
* **The attempt counter lives in code.** It is `len(DocumentRecord.attempts)`, with a cap of `MAX_ATTEMPTS_PER_DOC = 3`.
* **An attempt is appended *before* the Writer runs.**
* **Each slot of an `AttemptRecord` is set once.** Nothing is ever removed.
* **The latest draft** is the last attempt that has one.
* **A violation never ends the run.** It is logged at WARNING, stored in `RunState.violations`, and returned to the Supervisor. Repeated violations are not bounded (DM16).
* **Rule 2, Approach 1's D23 source check,** is enforced in `writer_tool`.

### 5. Benchmark parity (orchestration is the only intentional variable)
* **Prompts.**
  * `SCOUT_SYSTEM_PROMPT` and `QA_LEGAL_SYSTEM_PROMPT` are byte-identical to those in `../code-orchestration/src/agents.py`.
  * `WRITER_SYSTEM_PROMPT` differs only by the declared input-naming substitutions.
  * QA-Legal is never told the attempt cap (DM7).
* **Models and efforts.**

  | Role | Model | Effort |
  | :--- | :--- | :--- |
  | Scout | `gpt-5-mini` | — |
  | Writer | `gpt-5.4` | `high` |
  | QA-Legal | `gpt-5.4` | `medium` |
  | Supervisor | `gpt-5.4` | `medium`, overridable through `.env` |
* **Tools.** All five substrate tools are attached to every sub-agent (P1), as in Approach 1's D19.
* **Held constant from Approach 1:**
  * the template, `.agents/templates/draft.md`;
  * the cost basis, Approach 1's cost module, reused unchanged;
  * sequential tool execution (`SequentialToolExecutor`, D-H).
* **Draft metadata.** `DraftMetadata.approach_name` is `"Approach 2 (Research Analyst)"`.

### 6. Substrate isolation and lifecycle (D-D)
* **One `HSEMockMCPClient` session per run.** It is opened in the composition root, and the exit-code mapping sits outside the `with` block, so the Windows subprocess always ends.
* **The reused MCP client module is the only substrate interface.** `mcp-server` is never imported into business logic.
* **Fatal errors.** `MCPConnectionError` and `MCPClientNotConnectedError` are fatal. They set `RunState.fatal_error`, and the D-D mechanism stops the Supervisor. Documents already saved are still rendered.

### 7. Rendering, telemetry and logging (D-B, D-I)
* **`save_draft` only marks a document saved** and allocates its draft ID. It writes no file.
* **Rendering happens once, at run end.** Draft IDs are allocated with awareness of the run.
* **Telemetry.**
  * `extract_telemetry` is the only reader of `metrics.get_summary()`.
  * Each draft's cost is its own calls plus an equal share of the Scout and the Supervisor.
  * Run totals are logged, not stored.
* **Logging.**
  * Every log line carries `run_id`, and `doc_id` and `attempt` where relevant.
  * The event catalogue in `SPECIFICATIONS.md` D-I is what the logs must cover.
  * API keys are redacted.

### 8. Code quality and Python conventions
* **PEP 8 and import hygiene.** All imports go at the top of the file, grouped as standard library, third-party, then local. Zero E402.
* **Type safety (PEP 484, 585 and 604).** Every signature is fully annotated. No `dict[str, Any]` crosses a module boundary; the one sanctioned exception is `AttemptRecord.supervisor_view()` feeding the Supervisor's JSON.
* **Hygiene.** Clear names, honest docstrings, no dead code and no linter warnings. `pathlib.Path` for every path.

---

## Review checklist

1. **Control flow.** Does any code outside the Supervisor choose which tool runs next? Code that does is a critical violation.
2. **Division of labour.** Can any article text reach the Supervisor? Does the Supervisor's prompt ask it to judge, score or improve text?
3. **Tool wrappers.** Are sub-agents fresh per call? Does each receive one typed input and request structured output? Is every call recorded in the ledger, on success and on failure?
4. **Guardrails.** Are all 12 checked in the documented order? Is every refusal logged, stored and returned? Is the attempt counter held in code, and appended before the run?
5. **Parity.** Are the prompts, models, efforts, tool binding, template and cost basis unchanged from Approach 1, apart from the documented exceptions?
6. **Lifecycle.** Is there one MCP session per run? Is transport death fatal, so that the run stops and saved documents are still rendered?
7. **Observability.** Are the D-I events present, with their correlation fields? Is the cost share correct?
8. **Code quality.** Imports, annotations, naming, dead code, and ruff findings.

A pillar the iteration does not touch is reported as "not touched by this iteration".

---

## Review output format

1. **Overall verdict:** `APPROVED`, `APPROVED WITH RESERVATIONS` or `REJECTED (VIOLATION)`.
2. **Pillar audit:** a point-by-point assessment against the eight pillars.
3. **Code review findings:** file and line references for convention, typing and hygiene issues.
4. **Anti-patterns and risks:** autonomy leaks, parity drift, state coupling, and article text leaking towards the Supervisor.
5. **Remediation directives:** concrete changes, citing the section of `SPECIFICATIONS.md` or `IMPLEMENTATION_PLAN.md` that requires each one.
