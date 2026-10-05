# agent-orchestration

HSE Easy, **Approach 2: the Research Analyst**. It turns Italian and EU health, safety and environment (HSE) regulatory updates into audited, TDI-branded draft articles, the same product as Approach 1 (`../code-orchestration/`, the Content Factory), under a different control model: **an agent owns the flow.** A Supervisor agent receives the prompt, builds the search scope, and calls the Scout, Writer and QA-Legal sub-agents as tools; code stores the results, enforces the guardrails and renders the saved drafts at the end of the run.

See [AGENTS.md](AGENTS.md) for the repository rules and [`.agents/docs/`](.agents/docs/) for the design, the specification and the implementation plan.

## Setup

Run every command from this folder, `agent-orchestration/`.

```bash
uv sync --extra dev
cp .env.example .env
```

Fill in `.env`. It lives in `agent-orchestration/`, is git-ignored, and is read from the working directory, which is why every command runs from here. The default test suite never reads it; the live tests read this file wherever pytest is started.

* **Model credentials (required).** `HSE_MODEL_FAST_*` drives the Scout; `HSE_MODEL_STRONG_*` drives the Writer, QA-Legal and the Supervisor. Each needs an `ENDPOINT` (an OpenAI v1-compatible base URL), an `API_KEY` and a `DEPLOYMENT`. Without them the run exits **5** (`CONFIG_ERROR`).
* **Reasoning effort (optional).** `HSE_MODEL_WRITER_REASONING_EFFORT`, `HSE_MODEL_QA_REASONING_EFFORT` and `HSE_MODEL_SUPERVISOR_REASONING_EFFORT` override the role defaults: Writer `high`, QA-Legal `medium`, Supervisor `medium`.
* **Cost rates (optional).** The six `HSE_COST_*` variables set USD per 1M tokens, for input, cached input and output. Each draft records the rates it was priced with.

**For a fair comparison with Approach 1, copy its `HSE_COST_*` values.** Approach 1's drafts were priced at gpt-5.4 $2.50 / $0.250 / $15.00 per 1M tokens (input / cached / output), while this project's built-in defaults are $1.25 / $0.125 / $10.00. Approach 1's variable names are a subset of this project's, so its `.env` values carry over as they are; this project adds the optional `HSE_MODEL_SUPERVISOR_REASONING_EFFORT`.

The `hse-easy-mock` substrate is started as a stdio subprocess by the run itself, from `../mcp-server/`; it needs `uv` on `PATH`.

## Running the Research Analyst

```bash
uv run python -m src.cli PROMPT [--max-drafts N] [--log-level {DEBUG,INFO,WARNING,ERROR}] [--drafts-dir DIR]
```

| Argument | Default | Meaning |
| :--- | :--- | :--- |
| `PROMPT` | required | The natural-language task, passed to the Supervisor verbatim |
| `--max-drafts` | none | The draft ceiling, enforced when a draft is saved and stated in the Supervisor's prompt |
| `--log-level` | `INFO` | Logging verbosity; `DEBUG` adds the provider request bodies |
| `--drafts-dir` | `drafts/` | Where the drafts are written at the end of the run |

Each document gets at most 3 Writer attempts: an initial draft plus up to two revisions. Drafts are written to `drafts/draft_YYYYMMDD_XXX.md`; a draft saved with `ERROR` carries the `[UNRESOLVED COMPLIANCE ALERT]` banner. The run's log is `logs/run_YYYYMMDD.log`, one file per day; every line carries the run ID, and the "Run completed" line states the exit code, the drafts saved, the run's tokens, cost and wall-clock.

| Exit code | Name | Meaning |
| :---: | :--- | :--- |
| 0 | `SUCCESS` | The run completed, whatever the number of drafts saved |
| 1 | `NO_UPDATES` | The Scout returned no candidates |
| 2 | `MCP_ERROR` | The substrate session failed to open or died mid-run |
| 3 | `PARSER_ERROR` | The Supervisor ended with no successful Scout call |
| 4 | `PERSISTENCE_ERROR` | A draft could not be rendered or written |
| 5 | `CONFIG_ERROR` | Settings could not be resolved; the run never started |
| 6 | `SUPERVISOR_ERROR` | The Supervisor failed on a provider or SDK error |

When several hold, the highest code is returned. The full rules are in `SPECIFICATIONS.md` §6.10 and §7.6.

## Tests

```bash
uv run pytest                    # the default suite: offline, zero tokens; live tests are deselected
uvx ruff check src tests         # lint
```

The default suite never calls a model: every model is scripted, and no test reads `.env`. The live tests are marked `live` and are deselected.

## Running the live benchmark

These commands call the real models and spend real tokens. Run them yourself; Approach 1's run of the benchmark prompt took about 8.5 minutes and cost $0.78.

**1. The live end-to-end tests.** They skip with a reason when `.env` is absent. Their drafts and logs go to pytest's temporary folders, not to `drafts/` and `logs/`.

```bash
uv run pytest -m live
```

* **Prompt A**, `Analyze INAIL updates on heat stress published since 2024`, Approach 1's benchmark prompt, must exit 0 with sound drafts.
* **Prompt B**, `Analyze recent INAIL updates on heat stress`, checks the Supervisor's default window: the past 3 months to the run date, INAIL only. **Exit 0 and exit 1 are both valid.** The corpus holds INAIL updates dated 2026-07-15 and 2026-08-20, and the Scout's input carries no topic, so whether the window holds a qualifying update depends on the run date. With exit 1 no draft is written; with exit 0 the drafts are checked as Prompt A's are.
* The **role-bleed audit** checks that no sub-agent called a substrate tool its own prompt declares a non-goal.

**2. A benchmark run of the Research Analyst**, which writes to `drafts/` and `logs/`:

```bash
uv run python -m src.cli "Analyze INAIL updates on heat stress published since 2024"
```

**3. The benchmark report**, comparing the Content Factory with the Research Analyst:

```bash
uv run python -m src.benchmark --a1 ../code-orchestration/drafts --a2 drafts --out .agents/docs/BENCHMARK.md
```

The full form is `python -m src.benchmark --a1 DIR --a2 DIR --out FILE [--a1-logs DIR] [--a2-logs DIR]`. Each approach's logs are read from `<drafts>/../logs` unless `--a1-logs` or `--a2-logs` names another folder; a missing logs folder means no runs. The report states Approach 1's metrics only: cost, time and tokens per draft, QA status, attempts, and run wall-clock. Each draft must state the approach its folder was given for, or the command stops with exit 2.

The two run wall-clocks are measured differently, and the report's footnote says so. The Research Analyst's is the `wall_clock` its "Run completed" line records. The Content Factory logs no wall-clock, so its run wall-clock is read from the timestamps of its "Pipeline run starting" and "Pipeline run finished" lines, which Approach 1's logs carry from 2026-09-23 on. Its earlier logs carry neither line and contribute no run; a run whose log lacks the "starting" line shows "not recorded".
