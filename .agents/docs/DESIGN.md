# HSE Easy — Approach 2 Design Specification
## Research Analyst (Supervisor Agent-Orchestrated System)

### 1. Executive Summary & Core Principle
* **Concept:** An autonomous research analyst that investigates regulatory developments with contextual depth. It dynamically plans its investigation, queries cross-references as needed, and conducts reflective revision loops.
* **Core Architectural Principle:** **An agent owns the flow.** A central Supervisor Agent receives the raw prompt directly and coordinates sub-agents wrapped as tools (`agents-as-tools` pattern). The execution graph emerges dynamically at runtime.

---

### 2. Models & Component Breakdown

| Component | Model | Role & Responsibilities |
| :--- | :--- | :--- |
| **Supervisor Agent** | `gpt-5.4` | Holds user context, plans investigative steps, invokes specialist tools, performs independent editorial review, and evaluates drafts. |
| **`scout_tool`** | `gpt-5-mini` | Sub-agent tool for scanning, searching, and filtering MCP regulatory notices. |
| **`writer_tool`** | `gpt-5.4` | Sub-agent tool for drafting technical content, regulatory breakdowns, and business conversion hooks. |
| **`qa_tool`** | `gpt-5.4` | Sub-agent tool for auditing legal accuracy and citation compliance against certified references. |
| **`citation_lookup_tool`** | Python MCP Tool | Direct MCP tool allowing the Supervisor to query TDI legal citations independently when investigating edge cases. |

---

### 3. Substrate & Tool Interfaces (`1_local_mcp_server`)
Connected via Strands `MCPClient` over `stdio`:
* `fetch_regulatory_updates(sources, time_window)`
* `lookup_tdi_citations(query)`

---

### 4. Step-by-Step Data Flow & Dynamic Reasoning

```text
[User Prompt: "Generate draft for last 2 months articles from Gazzetta Ufficiale and INAIL"]
                                │
                                ▼
                   [Supervisor Agent (gpt-5.4)]
                                │
     ┌──────────────────────────┼──────────────────────────┐
     ▼                          ▼                          ▼
[scout_tool]              [writer_tool]                [qa_tool]
(Finds updates)       (Drafts technical piece)     (Audits citations)
     │                          │                          │
     └──────────────────────────┼──────────────────────────┘
                                │
                                ▼
       [Supervisor Reflection & Autonomous Decision Loop]
       ├── Trigger A: Did QA flag status == "ERROR"?
       └── Trigger B: Did Supervisor identify technical/editorial gaps?
                                │
                  (Revision count < 2? ──► Re-invoke Writer)
                                │
                                ▼
         [Save Candidate Draft to drafts/draft_<id>.json]
                                │
                                ▼ (Run Terminates)
              [Human Review & Explicit TDI Approval]
                                │
                                ▼
     [publish.py --draft <id>] ──► Formats SEO, CTAs, & Publishes