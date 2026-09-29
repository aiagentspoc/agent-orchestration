# Iteration 4 — QA and Verification Review (Stage 3, round 1)

**Reviewer:** QA and Verification, 2026-09-29.
**Scope:** the uncommitted working tree on `approach-2/implementation` against `28faa79` (Iteration 03). Modified files: `src/schemas.py`, `src/credentials.py`, `.env.example`, `tests/conftest.py`, and `tests/test_unit/test_schemas.py`, `test_credentials.py`, `test_docs_consistency.py`, `test_template_engine.py` and `test_telemetry.py`. The orchestrator's own edit is the §3 status row of `IMPLEMENTATION_PLAN.md`. There are no untracked files apart from `.agents/tasks/iteration-04/`.
**Criteria:** `.agents/skills/code-reviewer/SKILL.md`; `AGENTS.md`; `IMPLEMENTATION_PLAN.md` §1.3, §1.4, §2 (P1 to P10) and Iteration 4; `SPECIFICATIONS.md` §6, §7.2, D-C, D-F and D-H; `DESIGN.md`; Approach 1 at `../code-orchestration/`, which was only read.

## 1. Summary and verdict

**CHANGES REQUIRED**

The contracts are correct and well tested:
* All 16 rows of the Red table are covered.
* All three acceptance criteria and DoD-1 to DoD-5 hold.
* 37 of the 41 valid mutation probes run on a scratch copy were killed. Of the 4 that survived, one is equivalent and three expose two small test gaps (QA-m1, QA-m2).

The verdict is **CHANGES REQUIRED** because one Major finding is open. I confirmed it independently: it is the architect's **A-M1**, already in `FIXES.md`. An empty `HSE_MODEL_SUPERVISOR_REASONING_EFFORT` resolves to `''`, not `medium`. That breaks the rule this iteration wrote into `.env.example` and the `ReasoningSettings` docstring, and nothing tests it.

QA adds two Minor test gaps. There are no Blockers.

**Measured by QA:**

| Check | Command | Result |
| :--- | :--- | :--- |
| Default suite | `uv run pytest -q` | **410 passed**, 0 failed, 0 errors (27.93 s), on the first run, before any review artefact existed. This matches the implementer's claim of 410. Later runs show **412 passed**, because `test_document_uses_no_forbidden_term` is parametrised over every Markdown file, and the architect's `ARCHITECT_REVIEW.md` and `FIXES.md` added two cases. This file adds one more. There is no discrepancy in the implementation's count |
| Warnings as errors | `uv run pytest -q -W error` | 410 passed; no unhandled warning |
| Lint | `uvx ruff check src tests --no-cache` | All checks passed |
| Live collection | `uv run pytest -m live --collect-only -q` | No tests collected (410 deselected). The live suite does not exist yet, and nothing was run live |
| Test deltas against HEAD | `--collect-only` on a `git archive HEAD` extract, compared with the working tree | 364 → 410. `test_schemas.py` went from 20 to 55, `test_credentials.py` from 13 to 23, and `test_docs_consistency.py` from 191 to 194. No other file changed count |
| Orphaned processes | PID sets of `python.exe` and `uv.exe` before and after a full run | No new PID survived the run |

## 2. Gate matrix

| Gate | Topic | Status | Notes |
| :--- | :--- | :---: | :--- |
| 1 | Strict TDD | ✅ | The report gives an expected, name- or value-level Red failure for all 18 behaviours. The AC1 structural tests passing on the first run is acceptable, since they pin invariants after Green. Every new `src/` function and branch is exercised: both setters on the first and second call; all three views; all three result branches and both error branches of `for_supervisor()`; all four `state` outcomes; `snapshot()`. The tests are meaningful, since 37 of 41 valid mutants were killed (§4). Two small gaps remain (QA-m1, QA-m2) |
| 2 | Zero-token testing | ✅ | No new test builds a model or an agent. The `model_builder` seam is untouched. `HSE_MODEL_SUPERVISOR_REASONING_EFFORT` was added to `_ISOLATED_ENV_VARS`, and a new parametrised test proves every alias of the three settings classes is isolated (mutant M35 killed). `addopts = "-m 'not live'"` is in place |
| 3 | Pydantic v2 contracts | ✅ | **Model count.** 27 §6 models (26 `BaseModel`s and the `ExitCode` `IntEnum`), 7 of them new, each asserted by `test_schemas_defines_exactly_the_27_models_of_the_specification`. **Config.** `extra="ignore"` is on every model, and `arbitrary_types_allowed` on `RunState` alone, both asserted. **Removed models.** None of them exists in `src`. **`dict[str, Any]`.** The only one crossing a boundary is `supervisor_view()`, the sanctioned exception. The hits in `mcp_client.py` and `model_factory.py` are reused and pre-existing. **Parity.** I ran my own probe: all 13 reused models and `WorkerOutput[QAReport]` have `model_json_schema()` and `model_config` identical to Approach 1's. Only the five [Amended] models differ, exactly as §6 marks them |
| 4 | Guardrails and attempt cap | ✅ (contracts only) | `MAX_ATTEMPTS_PER_DOC: Final[int] = 3`; `RunContext` defaults to it; `DocumentRecord.attempts_remaining` subtracts from it; the docs test reads the constant (mutant M33 killed). `GuardrailName` holds the 12 names in §6.7 order, asserted with `get_args`. The guardrail checks and wrappers are Iterations 5 to 10 |
| 5 | Strands integration and telemetry | ✅ (contracts only) | `StageTelemetry.stage` accepts `supervisor`, `scout`, `writer` and `qa_legal` and rejects `scope_parser`, and `doc_id` and `attempt` default to `None`. `FailureStage` has the 9 values in order, and `FailureRecord.attempt` exists. `extract_telemetry` is not touched this iteration |
| 6 | No article text for the Supervisor | ✅ | `test_for_supervisor_never_carries_article_text_or_the_candidate` scans every key at any depth for all five forbidden keys of §7.2. It also checks that no headline, summary, body or rationale text appears as a substring, across the success, failure-summary and violation shapes. Mutants that leaked `draft` (M01) or `candidate` (M02), or bypassed the view (M03), were killed |
| 7 | Drafts and logging | n/a in this iteration | AC3 only. `draft.md` is unchanged against HEAD and content-identical to Approach 1's; only CRLF line endings differ. `DraftMetadata` changed only its `approach_name` default, and its field list is pinned |
| 8 | Python and subprocess safety | ✅ | Annotations are complete and imports are at the top. `Path` is used for `DraftResult.path` and in the tests. No subprocess was left behind. No control characters in `src/` or `tests/`, scanned after the heredoc incident in the report |

## 3. Acceptance criteria and Definition of Done

| # | Criterion | Status | Evidence |
| :---: | :--- | :---: | :--- |
| AC1 | 27 models, 7 new, plus the four settings classes | ✅ | The model and new-model sets are asserted and the parity script agrees. The four settings classes: `ReasoningSettings`, `CredentialManager` and `ModelCredentials` in `src/credentials.py`, and `CostSettings` in `src/costs.py` |
| AC2 | `grep -n "RevisionPayload\|PipelineRun\|PipelineExitCode\|time_window" src` finds nothing | ✅ | `grep -rn` over `src` printed nothing (exit 1). A wider grep for all 11 removed names of §6 also finds nothing |
| AC3 | Template-engine tests pass; template unchanged; `DraftMetadata` changed only its default | ✅ | They pass, also under `-W error` (307 passed across the five touched unit files). `git diff HEAD -- .agents/templates/draft.md` is empty. The field list is pinned by `test_draft_metadata_fields_are_unchanged_apart_from_the_approach_default` |
| DoD-1 | Suite passes | ✅ | 410 passed, 0 failed, 0 errors |
| DoD-2 | Lint clean | ✅ | All checks passed |
| DoD-3 | No live model call | ✅ | No agent or model is built in any new test; the isolation list is complete |
| DoD-4 | Every new `src/` function tested | ✅ | See Gate 1. The two gaps in §5 are in how tightly the tests pin behaviour, not untested code |
| DoD-5 | Docs match code | ✅ | `test_docs_consistency.py` passes, including the new `test_specification_states_the_attempt_cap_the_code_enforces` |
| DoD-6 | `WALKTHROUGH.md` written | Pending | The orchestrator writes it at step 8 |

**Red table rows** (Iteration 4): 16 of 16 are covered by meaningful tests.

| Row | Covered by (in `test_schemas.py` unless stated) | Probe |
| :--- | :--- | :--- |
| `AgentContext` | `test_agent_context_holds_today_only` | M27b killed |
| `PipelineScope` | `…_defaults_and_unconstrained`, `…_requires_context…`, `…_ignores_the_dropped_window_fields` | M30, M37 and M38 killed |
| `AttemptRecord` | `…_holds_its_candidate_by_identity…`, `…_doc_id_is_derived…`, `…_sets_its_draft_once`, `…_sets_its_qa_report_once` | M04, M05, M14, M31 and M32 killed |
| `AttemptRecord` views | `test_writer_view…`, `test_qa_view…`, `test_supervisor_view…` (×2) | M01, M02, M11, M12, M13 and M21 killed |
| `RunContext` | `test_run_context_…` (×2), `test_max_attempts_per_doc_is_three` | M15 and M42 killed |
| `DraftResult` | `test_draft_result_is_the_slim_save_result` | — |
| `ToolResult[T]` | `test_tool_result_…` (×2), `test_for_supervisor_…` (×3) | M03, M17, M18, M25, M26 and M40 killed |
| `DocumentRecord` | `test_document_record_…` (×4) | M09, M10 and M19 killed. M28 survived (QA-m1) |
| `RunState` | `test_run_state_…` (×3) | M07 and M08 killed. M24 and M41 survived (QA-m2) |
| `StageTelemetry` | `test_stage_telemetry_…` (×3) | M22 killed |
| `FailureStage`, `FailureRecord` | `test_failure_stages_…`, `test_failure_record_ties…` | — |
| `GuardrailName`, `GuardrailViolation` | `test_guardrail_…` (×2) | M16 and M29 killed |
| `DraftMetadata` | `test_draft_metadata_composition`, `…_fields_are_unchanged…` | — |
| `ExitCode` | `test_exit_codes`, `test_the_old_exit_code_name_no_longer_exists` | M23 killed |
| `ReasoningSettings` | `test_credentials.py`: 4 `supervisor` tests; the existing `writer` and `qa_legal` tests are unchanged | M20 and M34 killed. The empty-value case is untested (A-M1) |
| Docs link | `test_docs_consistency.py::test_specification_states_the_attempt_cap_the_code_enforces`, and the reworked cap tests | M33 killed |

The sources disagree on three points, and the code follows `SPECIFICATIONS.md` §7.2 in each:
* `qa_view` also excludes `qa_report`;
* `supervisor_view` includes `context`;
* the forbidden-key set has five keys, adding `executive_summary`.

This agrees with the architect's reading, and none of the three is a stop condition.

## 4. Mutation probes

**Method.**
* Scratch copy: `src/`, `tests/` and the docs, in the session scratchpad.
* Interpreter: the project `.venv`, with the copy's `src` confirmed first on `sys.path`.
* Each mutation was applied and the targeted test files were run with `-x`. The file was then restored, and `diff -r` against the repository confirmed the copy was pristine.
* Nothing in the repository was changed.
* M06 is not counted. Its first form, `revalidate_instances` on `AttemptRecord`, did not copy the candidate, so it was replaced by M31 and M32.

| Result | Mutants |
| :--- | :--- |
| **Killed (37)** | M01 to M05, M07 to M23, M25, M26, M27b, M29 to M38, M40 and M42. M27's first pattern matched twice and was re-run as M27b; M34's matched twice and was re-run with a unique anchor |
| **Survived (4)** | **M24.** `RunState.fatal_error: Any` instead of `BaseException \| None` (QA-m2). **M28.** `state` checks `saved` only after finding a drafted attempt (QA-m1). **M39.** `max(0, 3 - attempts_used)`, equivalent while the cap holds, so not a finding. **M41.** `RunState.documents: dict[str, Any]` (QA-m2) |

The probes the orchestrator named are all killed:
* **Leaking `draft` into `supervisor_view`:** M01, killed by `test_supervisor_view_omits_the_draft_and_candidate_and_carries_the_report`.
* **Dropping set-once:** M04 and M05, killed by `test_attempt_record_sets_its_draft_once` and `test_attempt_record_sets_its_qa_report_once`.
* **Copying the candidate:** M31 (deep) and M32 (shallow), killed by `test_attempt_record_holds_its_candidate_by_identity_and_starts_empty`.
* **Counting `drafts_saved` from the context:** M07, killed by `test_run_state_snapshot_counts_saved_documents_into_a_new_context`.

## 5. Findings by severity

### 🔴 Blocker
None.

### 🟡 Major
* **A-M1 (the architect's; corroborated by QA): an empty Supervisor effort resolves to `''`.**
  * **Where.** `src/credentials.py:126`, against the rule stated at `src/credentials.py:100-104` and in `.env.example`.
  * **Probed output, verbatim.** With `HSE_MODEL_SUPERVISOR_REASONING_EFFORT="" HSE_MODEL_WRITER_REASONING_EFFORT=""`, `ReasoningSettings(_env_file=None)` printed `'' ''` for `supervisor` and `writer`.
  * **Why it matters.** The Writer's empty value falls back through the consumer's `or`. The Supervisor's default lives on the field, so `''` reaches `build_model`, which rejects it, and the run would fail as `CONFIG_ERROR`.
  * **Fix.** The fix instructions are in `FIXES.md` under the architect's section. QA adds a verification note under its own section and does not duplicate the item.

### 🟢 Minor
* **QA-m1: `DocumentRecord.state`'s `saved` precedence is not pinned.**
  * **What survived.** Mutant M28 moves the `saved` check after the `latest_drafted is None` check, and all 115 targeted tests still pass.
  * **What the spec says.** §6.5 reads `"saved" if saved else …`, so `saved` wins whatever the attempts hold.
  * **Why no test catches it.** Every existing `saved` case already has an audited draft.
* **QA-m2: `RunState`'s field types for `fatal_error` and `documents` are not pinned.**
  * **What survived.** Mutants M24 (`fatal_error: Any`) and M41 (`documents: dict[str, Any]`) pass every test.
  * **What the current code does.** It rejects `fatal_error="boom"` with `Input should be an instance of BaseException [type=is_instance_of, …]`, and validates a nested dict into a `DocumentRecord`. No test asserts either.
  * **Why it matters.** Iteration 12's stop mechanism and Iteration 5's guardrails rely on both.

**Forward notes (not findings).** I agree with the architect's §4 directives. In particular:
* Iteration 7 must return `ToolResult.for_supervisor()` and never the model itself, because the plain dump carries the draft and candidate, as the Iteration 4 test demonstrates.
* `tests/support/scripted.py:316` still carries `time_window`. It is harmless under `extra="ignore"`, and belongs to Iteration 7.

## 6. Remediation

The fix instructions are in `FIXES.md`:
* A-M1, under the architect's section;
* QA-m1 and QA-m2, under `## 🧪 QA & Verification`.

After the fixes:
* `uv run pytest` is green;
* `uvx ruff check src tests` is clean;
* the AC2 grep is still empty;
* M28, M24 and M41 are re-run on a scratch copy and are killed.

---

# Round 2 — QA re-review of the fix round

**Reviewer:** QA and Verification, 2026-09-29.
**Scope:** the fix-round changes against the implementer's fix-round report:
* `src/credentials.py`;
* `src/schemas.py`, two banners;
* `tests/test_unit/test_credentials.py` and `tests/test_unit/test_schemas.py`;
* `tests/test_unit/test_docs_consistency.py`, one docstring.

**Criteria:** those of round 1, re-read for this round: `AGENTS.md`, the code-reviewer skill, `IMPLEMENTATION_PLAN.md` §1.3 and Iteration 4, and `SPECIFICATIONS.md` §6, §7.2 and D-H.

## R2.1 Summary and verdict

**PASSED**

All five round-1 items are resolved and verified by QA:
* the architect's A-M1, A-m1 and A-m2;
* QA's QA-m1 and QA-m2.

The three round-1 survivors that were real gaps (M28, M24 and M41) are now killed. No new finding is opened. The acceptance criteria and DoD-1 to DoD-5 still hold, and DoD-6 is the orchestrator's step 8.

**Measured by QA:**

| Check | Command | Result |
| :--- | :--- | :--- |
| Default suite | `uv run pytest -q` | **415 passed**, 0 failed, 0 errors (30.64 s). This matches the implementer's 415 |
| Warnings as errors | `uv run pytest -q -W error` | 415 passed (27.69 s); no unhandled warning |
| Lint | `uvx ruff check src tests --no-cache` | All checks passed |
| Live collection | `uv run pytest -m live --collect-only -q` | No tests collected (415 deselected). Nothing was run live |
| AC2 | `grep -rn` of the four AC2 names over `src` | No output (exit 1) |
| Orphaned processes | PID sets of `python.exe` and `uv.exe` before and after the full run | No new PID survived |
| Control characters | A Python scan of every `.py` file in `src/` and `tests/` | None |

**How the count reconciles.**
* **410 → 415.** The fix round adds two new test functions:
  * `test_supervisor_reasoning_effort_resolves_to_medium_when_empty`;
  * `test_document_record_state_is_saved_whatever_its_attempts`.

  It also adds three `test_document_uses_no_forbidden_term` cases, one for each of the three Markdown records in `iteration-04/`.
* **Per file.**
  * `test_credentials.py` went from 23 to 24 tests.
  * `test_schemas.py` went from 55 to 56.
  * `test_docs_consistency.py` has 195: 192 cases of its own plus the three records.
* **Correction to round 1.**
  * My round-1 delta row gave `test_docs_consistency.py` as "191 to 194". That count was taken after the architect's two records existed.
  * The implementation's own delta was 191 to 192, the one new cap test. The other two were review-record cases.
  * The round-1 total of 410 is unaffected.

## R2.2 Round-1 items

| Item | Status | Evidence |
| :--- | :---: | :--- |
| **A-M1** (Major): an empty Supervisor effort resolved to `''` | ✅ Resolved | See the notes below the table |
| **A-m1** (Minor): banners | ✅ Resolved | `src/schemas.py:222` reads `# Scout Triage Models (SPECIFICATIONS.md §6.3)`, and `:255` reads `# Worker Telemetry Envelope (SPECIFICATIONS.md §6.3, §6.6)` |
| **A-m2** (Minor): docstring | ✅ Resolved | `_partial_binding_claims` (`tests/test_unit/test_docs_consistency.py:475`) has a one-line docstring |
| **QA-m1** (Minor): `saved` precedence unpinned | ✅ Resolved | `test_document_record_state_is_saved_whatever_its_attempts` asserts `saved` for two cases: a saved document with no attempts, and audited #1 + failed #2 + saved. M28 is now killed (R2.3) |
| **QA-m2** (Minor): `RunState` types unpinned | ✅ Resolved | M24 and M41 are now killed (R2.3). See the notes below the table |

**A-M1 in detail.**
* **The fix.** A `mode="before"` validator, `return value or "medium"`, on `supervisor` alone. The field keeps `str | None`, its `medium` default and its alias, as §6.9 states.
* **The test.** `test_supervisor_reasoning_effort_resolves_to_medium_when_empty` covers three inputs: an empty `.env` line, an empty environment variable and a real `high`. That meets my round-1 request that `high` still passes.
* **A direct probe of the real code.**
  * These give `'medium'`: unset, env `''`, `.env` `K=`, `.env` `K=""`, `.env` `K=` followed by spaces, and an explicit `None` through the alias.
  * `high` from either source gives `'high'`.
* **The Writer and QA-Legal are untouched.** With `HSE_MODEL_WRITER_REASONING_EFFORT=""` and `HSE_MODEL_QA_REASONING_EFFORT=""`, `writer` and `qa_legal` still read `''` and `''`, and still fall back through the consumer's `or`. Their field lines are identical to Approach 1's `src/credentials.py`.

**QA-m2 in detail.**
* **`fatal_error`.** `test_run_state_holds_the_fatal_exception_itself` now requires `fatal_error="boom"` to raise a `ValidationError` that names `fatal_error`.
* **`documents`.** `test_run_state_holds_the_fields_of_the_specification` validates a nested dict and asserts it comes back as a `DocumentRecord`.

**The implementer's recorded decision** is that an explicit `None` through the alias also resolves to `medium`.
* It is consistent with "unset or empty means the default" in `.env.example` and in the class docstring.
* §6.9 does not settle it otherwise.
* §1.5 allows it, and it is not a stop condition.

## R2.3 Mutation re-probes

**Method.**
* **Scratch copy.** The repository without `.venv`, `.git`, `drafts`, `logs` or caches, in the session scratchpad. It holds no `.env`.
* **Interpreter.** The project `.venv`, with the copy's `src` confirmed first on the import path.
* **Each mutant.**
  * It was applied with a single, unique text replacement.
  * `tests/test_unit/test_schemas.py` and `tests/test_unit/test_credentials.py` were run with `-x`.
  * The file was then restored.
* **Pristine check.** Afterwards, `diff --strip-trailing-cr` against the repository was clean. The only difference was CRLF endings, which my runner's Windows `write_text` introduced on the scratch copy.
* **The repository was not changed.** Its `git status` and diff stat are identical before and after.

| Mutant | Result | Failing assertion, verbatim |
| :--- | :---: | :--- |
| **M28:** `saved` checked after the `not_drafted` branch | **Killed** | `AssertionError: assert 'not_drafted' == 'saved'` |
| **M24:** `fatal_error: Any` | **Killed** | `Failed: DID NOT RAISE ValidationError` |
| M24b: `fatal_error: BaseException \| str \| None` | Killed | `Failed: DID NOT RAISE ValidationError` |
| **M41:** `documents: dict[str, Any]` | **Killed** | `AssertionError: assert False` |
| M41b: `documents: dict[str, DocumentRecord \| dict]` | Survived; equivalent for any valid input | Pydantic's smart union resolves a valid nested dict to `DocumentRecord`, so the behaviour is unchanged. Not a finding |
| A1: the validator returns `value` unchanged | Killed | `AssertionError: assert '' == 'medium'` |
| A2: the validator always returns `"medium"` | Killed | `AssertionError: assert 'medium' == 'high'` |
| A3: the validator also applies to `writer` | Killed | `AssertionError: assert 'medium' is None` |
| A4: only `None` maps to `medium` | Killed | `AssertionError: assert '' == 'medium'` |
| A5: the field default becomes `None` | Survived; equivalent | `BaseSettings.model_config["validate_default"]` is `True`, so the `None` default passes through the validator and still yields `medium` |
| A6: `mode="after"` | Survived; equivalent | `''` is a valid `str \| None`, and the after-validator maps it to `medium` all the same |

Over both rounds, every non-equivalent mutant is killed.

## R2.4 Gate matrix, acceptance criteria and Definition of Done

* **The round-1 matrix (§2) stands.** Gate 1 has lost its two noted gaps, since QA-m1 and QA-m2 are closed.
* **Gates.** 1, 2, 3, 6 and 8 are ✅. Gates 4 and 5 are ✅ for the contracts only. Gate 7 is n/a in this iteration.
* **Iteration 4's acceptance criteria.** 3 of 3 hold:
  * AC1, the model set;
  * AC2, the grep;
  * AC3, the template engine, the template and `DraftMetadata`.
* **The Definition of Done.** DoD-1 to DoD-5 hold. DoD-6 (`WALKTHROUGH.md`) is pending the orchestrator's step 8.
* **Red rows.** 16 of 16 are covered.
  * The `ReasoningSettings` row's empty case is now tested.
  * The `DocumentRecord` and `RunState` rows are now fully pinned.

## R2.5 Findings by severity

* 🔴 **Blocker:** none.
* 🟡 **Major:** none open. A-M1 is resolved.
* 🟢 **Minor:** none open. A-m1, A-m2, QA-m1 and QA-m2 are resolved.

**Observation, not a finding.**
* **The behaviour.** A whitespace-only value set in a real shell variable, such as `HSE_MODEL_SUPERVISOR_REASONING_EFFORT="  "`, passes through as `'  '`. The same value in `.env` is stripped by the dotenv parser and resolves to `medium`.
* **Why it is not a finding.** This matches the Writer's and QA-Legal's `or` semantics, which Approach 1 holds constant.
* **Where it is handled.** An unrecognised value is `build_model`'s concern. `.env.example` says it fails the run as `CONFIG_ERROR`, from the iteration that wires it.
