# CLAUDE.md

Claude Code entry point for **HSE Easy — Approach 2 (Research Analyst)**.

## Read this first

**[AGENTS.md](AGENTS.md) is the authoritative guide.** Read it before any work in this repository. It defines the product rules (1–6) constraining the code you write, and the working rules (7–10) constraining how you work: strict TDD, stop-and-ask in place of approval gates, review subagents with zero fallback, and no live model calls.

Supporting sources of truth, all harness-neutral, in [`.agents/docs/`](.agents/docs/):

| Document | What it settles |
| :--- | :--- |
| [SPECIFICATIONS.md](.agents/docs/SPECIFICATIONS.md) | The specification and single source of truth: decisions D-A to D-J, the data model, the interfaces, the decision log |
| [IMPLEMENTATION_PLAN.md](.agents/docs/IMPLEMENTATION_PLAN.md) | The build sequence: execution protocol, stop conditions, P1–P15, the iteration tracker and each iteration's tests |
| [DESIGN.md](.agents/docs/DESIGN.md) | The concept and the component roles |

## Project principle — "An agent owns the flow"

A Supervisor Agent plans each run and calls the Scout, Writer and QA-Legal sub-agents as tools; code stores results, enforces guardrails and renders drafts, but never decides which tool runs next. See `SPECIFICATIONS.md` §1 and §3.

This constrains **the code you write**. It is not a statement about how you sequence your own work.

## Repository layout

- **`.agents/`** — harness-neutral: docs, the review skills [architect-review](.agents/skills/architect-review/SKILL.md) and [code-reviewer](.agents/skills/code-reviewer/SKILL.md), templates and task artifacts.
- **`.claude/`** — Claude Code only: the subagents [architect](.claude/agents/architect.md), [implementation](.claude/agents/implementation.md) and [qa](.claude/agents/qa.md), and the [`/implement` workflow](.claude/skills/implement/SKILL.md). [settings.json](.claude/settings.json) grants read access to `../code-orchestration/` and `../mcp-server/` and enables the MCP servers.

When adding a file, ask which of the two it is. Project truth goes in `.agents/`; harness mechanics go in `.claude/`.

## Implementation workflow

Iterations of the plan are implemented with **`/implement`**, which runs four stages with no human approval gate: architect pre-flight → implementation by incremental TDD → parallel architect and qa review with at most two fix rounds → walkthrough, tracker update and a local commit. It stops only for a stop condition of `IMPLEMENTATION_PLAN.md` §1.4.

The architect, implementation and qa roles must run as real subagents (`subagent_type: architect | implementation | qa`). Acting them out inline is prohibited (AGENTS.md Rule 9); if one cannot be spawned, stop and record the question.

## Commands

```bash
uv sync --extra dev                       # install the locked environment
uv run pytest                             # default suite; live tests are deselected
uvx ruff check src tests                  # lint
uv run pytest -m live --collect-only      # the only live command allowed; only the user runs live tests
```

## MCP servers

Registered in [.mcp.json](.mcp.json): `hse-easy-mock` (the local regulatory substrate over stdio) and `strands-agents` (SDK documentation search). The substrate tools are listed in [AGENTS.md §4](AGENTS.md).

## Conventions

- Python with complete PEP 484/585/604 type annotations; imports at the top of the file.
- Pydantic v2 models with `model_config = ConfigDict(extra="ignore")`; no `dict[str, Any]` across module boundaries.
- `pathlib.Path` for all path handling — this is a Windows development environment.
- Tests before production code, always. No live model calls, ever (P4).
