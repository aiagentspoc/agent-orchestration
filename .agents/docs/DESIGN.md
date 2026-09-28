# HSE Easy — Approach 2 Design Specification
## Research Analyst (Supervisor Agent-Orchestrated System)

**Approach 1 (reference project):** `../code-orchestration/`, the folder next to `agent-orchestration/`. On this machine that is `C:\Users\Saksham\Git\poc\AIAgents\code-orchestration`. It is **read-only**. Its `src/`, `tests/`, `uv.lock`, `drafts/` and `.agents/docs/` are the baseline this project reuses and is benchmarked against.

### 1. Executive Summary & Core Principle
* **Concept:** An autonomous research analyst that turns Italian and EU HSE regulatory developments into audited, TDI-branded draft articles. It plans its own run, decides which candidates to work on, and runs a revision loop driven by each compliance audit.
* **Core Architectural Principle:** **An agent owns the flow.** A central Supervisor Agent receives the raw prompt directly and coordinates sub-agents wrapped as tools. The execution path emerges at runtime.
* **Multi-agent pattern:** Strands **Agents as Tools**, implemented with its documented **custom agent tools** method: each sub-agent is a `@tool` that builds a fresh agent on every call, requests typed output, and returns a compact typed result to the Supervisor.

---

### 2. Division of Labour

**The Supervisor supervises agents, not drafts.** Each sub-agent does its own job, as defined by its own prompt; the Supervisor only decides what happens next. It never reads, reviews or edits article text.

| Who | Does | Never does |
| :--- | :--- | :--- |
| **Supervisor** | Turns the user's prompt into a scope; calls the Scout; decides which candidates to draft; reads each QA report and decides whether to request a revision or save; decides when the run is finished | Read or judge article text; write feedback for the Writer; write Markdown |
| **Scout** (`scout_tool`) | Finds and ranks qualifying regulatory updates | — |
| **Writer** (`writer_tool`) | Writes the article draft, and revises the latest draft against its QA report | Audit its own work; write the Markdown file |
| **QA-Legal** (`qa_tool`) | Audits the latest draft for legal accuracy and citation compliance | Change the draft; write the Markdown file |
| **Code** (tool wrappers) | Stores every draft and QA report; counts attempts; hands each sub-agent its input; enforces guardrails; renders the saved drafts into Markdown at run end; logs | Make editorial or routing decisions |

---

### 3. Models & Component Breakdown

| Component | Model | Role & Responsibilities |
| :--- | :--- | :--- |
| **Supervisor Agent** | `gpt-5.4` (effort `medium`) | Holds the user's context, plans the run, invokes the specialist tools, and decides from each QA report whether a document is revised or saved. |
| **`scout_tool`** | `gpt-5-mini` | Sub-agent tool for scanning, searching and ranking regulatory updates within the scope. |
| **`writer_tool`** | `gpt-5.4` (effort `high`) | Sub-agent tool for drafting technical content, regulatory breakdowns and business conversion hooks, and for revising a draft its audit rejected. |
| **`qa_tool`** | `gpt-5.4` (effort `medium`) | Sub-agent tool for auditing legal accuracy and citation compliance against the substrate. |
| **`save_draft`** | Python | Marks a document as saved once it has been audited. Code renders every saved draft into the Markdown template at the end of the run. |

The Supervisor has **no direct substrate access**: every MCP call is made by a sub-agent.

---

### 4. Substrate & Tool Interfaces (`hse-easy-mock`)
Connected via Strands `MCPClient` over `stdio`. As in Approach 1, every sub-agent is connected to all five tools. Each sub-agent's prompt limits it to the tools its job needs, shown in the "Used by" column:

| MCP tool | Purpose | Used by |
| :--- | :--- | :--- |
| `list_regulatory_updates` | Updates published in a date window, by source | Scout |
| `search_regulatory_docs` | Updates matching a topic or sector query | Scout |
| `get_document_by_id` | The full regulatory document, with obligations, penalties and text | Scout, Writer, QA-Legal |
| `verify_legal_citation` | Whether a legal citation exists and is in force | QA-Legal |
| `get_tdi_service_offerings` | TDI services and pre-approved calls to action | Writer |

---

### 5. Step-by-Step Data Flow & Dynamic Reasoning

```text
[User Prompt: "Generate draft for last 2 months articles from Gazzetta Ufficiale and INAIL"]
                                │
                                ▼
              [Supervisor Agent (gpt-5.4, effort medium)]
              builds the scope from the prompt
                                │
                                ▼
              [scout_tool] ──► ranked candidates
                                │
                                ▼
  ┌── For each candidate, one document at a time ──────────────────
  │
  │   [writer_tool] ──► article draft (kept in code, never shown to the Supervisor)
  │         │
  │         ▼
  │   [qa_tool] ──► QA report: PASS / WARNING / ERROR
  │         │
  │         ▼
  │   [Supervisor decides from the QA report alone]
  │   ├── PASS    ──► save
  │   ├── WARNING ──► revise if a statement is wrong or unsupported, otherwise save
  │   └── ERROR   ──► revise while attempts remain; saved with a compliance alert at the cap
  │         │
  │   (3 Writer attempts per document: an initial draft plus up to
  │    two revisions, counted in code ──► re-invoke Writer)
  │         │
  │         ▼
  │   [save_draft] ──► document marked saved
  │
  └────────────────────────────────────────────────────────────────
                                │
                                ▼ (Supervisor finishes)
     [Code renders every saved draft to drafts/draft_<id>.md]
                                │
                                ▼ (Run Terminates)
              [Human Review & Explicit TDI Approval]
                                │
                                ▼
     [publish.py --draft <id>] ──► Formats SEO, CTAs, & Publishes
```

* **Decision loop.** The Supervisor decides from the QA report alone, within hard rules enforced in code: a `PASS` is never revised, an `ERROR` is never saved while attempts remain, and no draft is saved without an audit.
* **Draft format.** Drafts are Markdown only, rendered from the same template as Approach 1 (`.agents/templates/draft.md`).
* **Guardrails.** A tool call that breaks a rule is refused in code, and the Supervisor is told why so it can decide again. Every refusal is logged and recorded on the run.

---

### 6. Logging

Every run writes a dated log file, `logs/run_YYYYMMDD.log`, at `INFO`, `WARNING` and `ERROR` levels. Because the execution path emerges at runtime, the log is the record of what the Supervisor actually did: every line carries the run ID and, where relevant, the document ID and attempt number. It covers model calls, MCP tool calls, sub-agent invocations, QA verdicts, revisions, saved drafts and the run outcome. The full event catalogue is in [`SPECIFICATIONS.md`](SPECIFICATIONS.md), decision D-I.
