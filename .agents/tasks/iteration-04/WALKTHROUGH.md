# Iteration 4 — New and amended contracts: walkthrough

**Date:** 2026-09-29 · **Branch:** `approach-2/implementation` · **Plan section:** `IMPLEMENTATION_PLAN.md` §5, Iteration 4

## 1. Overview

Iteration 4 builds, test-first, every new and amended model in `SPECIFICATIONS.md` §6:
* `src/schemas.py` now holds exactly the **27 §6 models**: 26 BaseModels plus the `ExitCode` IntEnum. Seven of them are new: `AgentContext`, `AttemptRecord`, `RunContext`, `ToolResult`, `DocumentRecord`, `RunState` and `GuardrailViolation`.
* It also holds the constant `MAX_ATTEMPTS_PER_DOC = 3` and the aliases `GuardrailName`, `Source` and `QAStatus`.
* It builds the D-F boundary: the three `AttemptRecord` views, and `ToolResult.for_supervisor()`, which is the only way a result is serialised for the Supervisor.
* `ReasoningSettings` gains the Supervisor's effort, which defaults to `medium`.

It also closes the items carried forward to this iteration:
* **QA-m4**, deferred from Iteration 1 by the answer to Q2;
* the docs test now reading the cap constant;
* the `.env.example` wording;
* **F3**, the Supervisor variable in the test isolation;
* **F4**, the `scope_parser` test data.

## 2. Files changed

| File | Change |
| :--- | :--- |
| `src/schemas.py` | See the three groups below |
| `src/credentials.py` | Adds `ReasoningSettings.supervisor: str \| None = Field(default="medium", alias="HSE_MODEL_SUPERVISOR_REASONING_EFFORT")`. A `mode="before"` validator makes an empty value mean `medium`. `writer` and `qa_legal` are unchanged, and so are their tests. Docstrings updated |
| `.env.example` | Comments only. They now name the Scout and the Supervisor rather than the ScopeParser, and cite `SPECIFICATIONS.md` §1, §6.9 and D-H instead of Approach 1's ARCHITECTURE sections. `#HSE_MODEL_SUPERVISOR_REASONING_EFFORT=medium` is added. Every variable line and example value is unchanged |
| `tests/conftest.py` | `HSE_MODEL_SUPERVISOR_REASONING_EFFORT` added to `_ISOLATED_ENV_VARS` (F3) |
| `tests/test_unit/test_schemas.py` | 20 → 56 tests. Iteration 2's baseline tests of the amended models are rewritten, as the plan orders. New tests cover every model in the Red table, plus the AC1 inventory |
| `tests/test_unit/test_credentials.py` | 13 → 24 tests. The Supervisor setting; every settings alias is isolated in `conftest.py` and documented in `.env.example` |
| `tests/test_unit/test_docs_consistency.py` | The cap comes from `src.schemas.MAX_ATTEMPTS_PER_DOC`, not a local literal. `PARTIAL_BINDING_PATTERNS` adds QA-m4's tool-anchored pattern. One docstring is now PEP 257 |
| `tests/test_unit/test_template_engine.py`, `test_telemetry.py` | F4, data only: `stage="scope_parser"` becomes `"scout"` (3 tests). The expected telemetry row is now `\| scout \| 1 \| gpt-5-mini \| — \| 120 \| 0 \| 40 \|` |

**What changed in `src/schemas.py`:**
* **Unchanged:** the substrate models, `ScoutCandidate`, `ScoutReport`, `ArticleDraft`, `QAReport`, `ToolInvocation`, `AgentTelemetry`, `WorkerOutput`, `ModelRate`, `RemoteErrorDetail` and `PipelineConfig`. Both reviewers and the implementer confirmed that they produce JSON schemas byte-identical to Approach 1's.
* **Amended:**
  * `PipelineScope` gains a required `context`; `time_window` and `time_window_specified` are removed, and it has no validators.
  * `DraftResult` has the fields `doc_id, draft_id, path, qa_status`, in that order, without `writer_invocations`.
  * `StageTelemetry` takes the stages `supervisor | scout | writer | qa_legal`, with `doc_id` and `attempt` defaulting to `None`.
  * `FailureStage` has nine stages, in §6.7 order.
  * `FailureRecord` gains `attempt`.
  * `DraftMetadata.approach_name` defaults to `"Approach 2 (Research Analyst)"`.
  * `ExitCode`, with `SUPERVISOR_ERROR = 6`, replaces the old name.
* **New:**
  * **`AgentContext`** holds `today` only.
  * **`AttemptRecord`** holds `context`, `candidate`, `attempt`, `draft` and `qa_report`.
    * `doc_id` is a `@computed_field`.
    * `set_draft` and `set_qa_report` each fill their slot once; a second call raises `ValueError`.
    * `writer_view()` gives the whole record as JSON.
    * `qa_view()` gives exactly `{doc_id, context, attempt, draft}`.
    * `supervisor_view()` gives exactly `{doc_id, context, attempt, qa_report}` as a JSON-mode dict.
  * **`RunContext`** holds `today`, `max_attempts_per_doc = MAX_ATTEMPTS_PER_DOC`, `max_drafts` and `drafts_saved`.
  * **`GuardrailViolation`** holds `guardrail: GuardrailName`, `tool_name`, `doc_id` and `message`.
  * **`ToolResult(BaseModel, Generic[T])`** holds `result`, `run` and `error`, where `error` is a violation, a string or `None`.
    * `for_supervisor()` returns `{"result", "run", "error"}` as compact JSON.
    * An `AttemptRecord` result goes through `supervisor_view()`.
  * **`DocumentRecord`** holds `candidate`, `attempts` and `saved`. `attempts_used`, `attempts_remaining`, `latest_drafted` and `state` are plain properties.
  * **`RunState`** holds the §6.5 fields and sets `arbitrary_types_allowed`. `snapshot()` returns a new `RunContext` whose `drafts_saved` is counted from `documents`.

## 3. TDD record

One behaviour at a time, each Red observed before its Green:

| # | Behaviour | Red |
| :---: | :--- | :--- |
| 1 | `AgentContext` | `ImportError: cannot import name 'AgentContext'` |
| 2 | `PipelineScope` | `ValidationError … time_window Field required`; `no attribute 'context'` |
| 3 | `AttemptRecord`: candidate identity, `doc_id` in every dump, set-once slots | `ImportError: AttemptRecord` |
| 4 | The three views, with exact key sets | `AttributeError: … 'writer_view'` / `'qa_view'` / `'supervisor_view'` |
| 5 | `MAX_ATTEMPTS_PER_DOC`, `RunContext` | `ImportError: MAX_ATTEMPTS_PER_DOC` |
| 6 | `DraftResult` order, `writer_invocations` removed | `writer_invocations Field required`; `'draft_id' != 'doc_id'` |
| 7 | `GuardrailName` (12 names, in order) and `GuardrailViolation` | `ImportError: GuardrailName` |
| 8 | `ToolResult` over the three results and the three error kinds; `for_supervisor()`, with a recursive forbidden-key scan and an article-text substring scan | `ImportError: ToolResult` |
| 9 | `DocumentRecord`'s derived fields, including a failed latest attempt after an audited one | `ImportError: DocumentRecord` |
| 10 | `ExitCode`, `SUPERVISOR_ERROR = 6`, no leftover old name | `ImportError: ExitCode` |
| 11 | `RunState` and `snapshot()` | `ImportError: RunState` |
| 12 | `StageTelemetry`, `FailureStage` and `FailureRecord.attempt`, with the F4 data | `no attribute 'doc_id'` / `'attempt'`; `Input should be 'scope_parser', …`; tuple mismatch at index 2 |
| 13 | The `DraftMetadata` default | `'Approach 1 (…)' == 'Approach 2 (…)'` |
| 14 | `ReasoningSettings.supervisor` | `no attribute 'supervisor'` (4 tests) |
| 15 | F3: every settings alias is isolated | `Extra items in the left set: 'HSE_MODEL_SUPERVISOR_REASONING_EFFORT'` |
| 16 | `.env.example` documents every settings alias | The same missing-alias assertion |
| 17 | The docs test reads `MAX_ATTEMPTS_PER_DOC` | `NameError: MAX_ATTEMPTS_PER_DOC` |
| 18 | QA-m4 | `assert [] == ['is limited to the list and search tools']` |

The AC1 structural tests passed on their first run, because every name existed by then:
* exactly the 27 §6 models are defined and exported;
* every model has `extra="ignore"`;
* only `RunState` allows arbitrary types;
* no new model sets `populate_by_name`.

**Fix round 1:**
* **A-M1.** An empty `HSE_MODEL_SUPERVISOR_REASONING_EFFORT=` gave `""`, which `build_model` would reject.
  * **Red:** `assert '' == 'medium'`.
  * **Green:** the `mode="before"` validator. A real value such as `high` still passes through.
* **QA-m1.** A saved document now reads `saved` whatever its attempts hold. Red: the reordering mutation M28 survived before.
* **QA-m2.** `RunState.fatal_error` and `documents` are now type-pinned. Red: loosening either to `Any` survived before.
* **A-m1.** Two section banners now cite §6.3 and §6.6, not Approach 1's sections.
* **A-m2.** One docstring is now PEP 257.

## 4. Test results

A fresh run at the checkpoint, after this walkthrough was written:

| Command | Result |
| :--- | :--- |
| `uv run pytest -q` | **416 passed**, 0 failed |
| Tests added by this iteration | 47 collected cases: 36 in `test_schemas.py` (20 → 56), 11 in `test_credentials.py` (13 → 24), plus new docs-test cases. Also one reserved-feature case per new record under `iteration-04/` |
| `uvx ruff check src tests --no-cache` | `All checks passed!` |

## 5. Acceptance criteria

| # | Criterion | Result | Evidence |
| :---: | :--- | :---: | :--- |
| 1 | `schemas.py` matches §6: 27 models, 7 new, plus the four settings classes | ✅ | The AC1 inventory test. The settings classes are `ReasoningSettings`, `CredentialManager` and `ModelCredentials` in `credentials.py`, and `CostSettings` in `costs.py` |
| 2 | `grep -n "RevisionPayload\|PipelineRun\|PipelineExitCode\|time_window" src` finds nothing | ✅ | It exits 1 with no output, docstrings and comments included |
| 3 | Template-engine tests still pass; the template is unchanged; `DraftMetadata` changed only its default | ✅ | 22 pass, with F4's data. `draft.md` is unchanged, and `DraftMetadata`'s field list is pinned by a test |

Definition of Done:
* **DoD-1** ✅, **DoD-2** ✅, **DoD-5** ✅ and **DoD-6** ✅ (this file).
* **DoD-3** ✅: pure pydantic and environment tests; settings are always built with `_env_file=None` or a `tmp_path` file.
* **DoD-4** ✅: every new method and branch is tested. QA ran 41 mutation probes; every non-equivalent survivor was closed in the fix round.

## 6. Decisions and deviations

**Decisions (§1.5), and readings of loosely specified points:**
* **The Supervisor's default lives on the field.** §6.9 says `default medium`; D-H says the override follows the Writer's style, where the fallback sits in the caller.
  * The field holds `"medium"`, because that is the only way the Iteration 4 test passes before `supervisor.py` exists. An empty value is also mapped to `medium`.
  * Iteration 13's `settings.supervisor or SUPERVISOR_REASONING_EFFORT` resolves to the same value either way.
* **Required-nullable fields.** The new models follow §6 literally, so `RunContext.max_drafts`, `RunContext.drafts_saved`, `ToolResult.result` and `GuardrailViolation.doc_id` are required but nullable. Reused models keep their code defaults.
* **Views follow §7.2.** It is stricter than the plan's rows: `qa_view` also drops `qa_report`, and all five forbidden keys are scanned. Key *sets* are the contract; `doc_id` serialises last, as computed fields do.
* **Generics.** `ToolResult(BaseModel, Generic[T])` is used, because the spec's PEP 695 syntax needs Python 3.12.
* **Style of `for_supervisor()` JSON.** `json.dumps(ensure_ascii=False, separators=(",", ":"))`: compact, as pydantic's own output is.
* **Derived fields.** `AttemptRecord.doc_id` is a `@computed_field`. `DocumentRecord`'s four derived fields are plain properties, so they are not stored or dumped.
* **Placement and ordering.** The new models sit at the end of the module, in dependency order, and `ExitCode` is implemented before `RunState`.
* **Setters.** Their error messages name the attempt and the `doc_id`.

**Deviations from the plan:** none.
* The implementer hit two incidents, both repaired: a Bash heredoc once mangled the QA-m4 regex, and `sed -i` stripped the CRLF working-copy endings from `schemas.py`. All files scan clean.

**Forward notes:**
* **Iteration 5:**
  * `draft_ceiling` reads `config.max_drafts`, while `snapshot()` carries `context.max_drafts`. Both must come from the same value.
  * AC2's no-mutation check must use Python-mode `model_dump()`. JSON mode raises once `fatal_error` is set.
* **Iteration 7:**
  * A tool must return `ToolResult.for_supervisor()`, never the model itself. Strands serialises a returned model with `model_dump_json()`, and that output carries the draft and the candidate.
  * Drop `time_window` from `VALID_SCOPE_ARGS` and `SCOPE_ARGS` in `tests/support/scripted.py`.
  * Build each `AttemptRecord` with `candidate=doc.candidate`, so the object keeps its identity.
  * Also carried: F5, F6 (P9, annotations in `mcp_client.py`), and F2.
* **Iterations 8 and 9:**
  * Fill the draft and report slots only through `set_draft` and `set_qa_report`; the model does not block a direct assignment.
  * The one-line `error` must be written by code, never `str(exc)`, because a pydantic `ValidationError` embeds article fragments.
* **Iterations 10 and 14:** follow DM3. The reused description on `PipelineConfig.max_drafts` ("overrides PipelineScope.max_drafts") is Approach 1's meaning.
* **Iteration 11:** the unchanged `format_stage_telemetry` prints `None` in the attempt column for the Supervisor and Scout rows, where Approach 1's drafts showed `1`. Iteration 11's pre-flight should decide on this; it also affects Iteration 16's parser.
* **Iteration 6:** F1 and A3, from Iteration 2.

## 7. Review

**Two rounds were used.**

| Round | Reviewer | Verdict | Findings | Resolution |
| :---: | :--- | :--- | :--- | :--- |
| 1 | Architect | APPROVED WITH RESERVATIONS | **A-M1 (major):** an empty Supervisor effort gave `""`. **A-m1:** stale section banners. **A-m2:** a docstring. Ruff: 0 in scope, 0 pre-existing | All fixed in fix round 1 |
| 1 | QA | CHANGES REQUIRED | Confirmed A-M1. **QA-m1:** saved precedence was untested. **QA-m2:** the `RunState` types were unpinned. 37 of 41 mutation probes killed | All fixed in fix round 1 |
| 2 | Architect | APPROVED | None. The reused schemas still match Approach 1 exactly | — |
| 2 | QA | PASSED | None. The round-1 survivors are killed; the remaining survivors are equivalent mutants | — |
