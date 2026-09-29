# Iteration 4 — Architect Review (Stage 3, round 1)

**Reviewer:** Lead Architect, 2026-09-29.
**Scope:** the uncommitted working tree on `approach-2/implementation` against `28faa79` (Iteration 03): `src/schemas.py`, `src/credentials.py`, `.env.example`, `tests/conftest.py`, `tests/test_unit/test_schemas.py`, `test_credentials.py`, `test_docs_consistency.py`, `test_telemetry.py`, `test_template_engine.py`, plus the orchestrator's one-row status edit in `IMPLEMENTATION_PLAN.md` §3. No files are untracked apart from this folder.
**Criteria:** `.agents/skills/architect-review/SKILL.md`, `.agents/skills/code-reviewer/SKILL.md`, `AGENTS.md`, `IMPLEMENTATION_PLAN.md` §1, §2, §4 and Iteration 4, and `SPECIFICATIONS.md` §6, §7.2, D-C, D-F, D-H and §8.2.

## 1. Overall verdict

**APPROVED WITH RESERVATIONS**

The contracts are faithful to `SPECIFICATIONS.md` §6. The D-F boundary holds at every depth, and every reused agent-facing JSON schema is byte-identical to Approach 1's. No code sequences anything, and the models carry no routing logic. There is one Major finding (A-M1). The Supervisor's effort setting does not honour the "unset or empty" rule that this iteration's own `.env.example` and docstring state for it: an empty value resolves to `""`, which the model factory would reject as `CONFIG_ERROR`. There are also two Minor findings (A-m1, A-m2). All three can be fixed within this iteration, and they are in `FIXES.md`.

**Verified independently:**
* `uv run pytest`: **410 passed**, 0 failed, 0 errors. The four touched unit files also pass under `-W error` (292 passed).
* `uvx ruff check src tests --no-cache`: **All checks passed**. That is 0 in-scope findings and 0 pre-existing.
* `uvx pyright` on `src/schemas.py` and `src/credentials.py`: 0 errors.
* AC2: `grep -rn "RevisionPayload\|PipelineRun\|PipelineExitCode\|time_window" src` finds nothing (exit 1).
* No control characters in any touched file.
* `git diff --summary` shows no mode changes.

## 2. Pillar audit

### Pillar 1 — An agent owns the flow: ✅
No code in the diff chooses a next step. The only behaviour on the models is:
* derivation, specified by §6.5: `DocumentRecord.attempts_used`, `attempts_remaining`, `latest_drafted` and `state`, and `AttemptRecord.doc_id`;
* the set-once invariant of D-C: `set_draft` and `set_qa_report` raise `ValueError` on a second call and never reroute;
* serialisation: the three views and `for_supervisor()`.

No guardrail or decision-table logic has leaked into `schemas.py`; that belongs to Iteration 5.

### Pillar 2 — Division of labour, D-F: ✅
* **Key sets, probed directly:**
  * `supervisor_view()` gives exactly `{doc_id, context, attempt, qa_report}`.
  * `qa_view()` gives exactly `{doc_id, context, attempt, draft}`.
  * `writer_view()` gives the whole record.
* **`for_supervisor()`** (`src/schemas.py:595-611`) builds `{"result", "run", "error"}` in that order. An `AttemptRecord` goes through `supervisor_view()`. A `ScoutReport` or `DraftResult` goes through `model_dump(mode="json")`, as §7.2 prescribes.
* **Test coverage.** `test_for_supervisor_never_carries_article_text_or_the_candidate` scans every key at any depth for all five forbidden keys of §7.2. That set is wider than the plan row, which omits `executive_summary`, and the test follows the specification. It also checks that no headline, summary, body or rationale text appears as a substring, across the success, failure-summary and violation shapes.
* **The plain `model_dump_json()` leaks** the draft and candidate. That is deliberate, and it is demonstrated by the same test and documented in the `ToolResult` docstring (`:584-586`). So the bypass risk now sits in Iteration 7's wrapper (see §4).
* **The `ScoutReport` path.** Its top-level key is `candidates`, which is not the forbidden `candidate`. The exact-key scan is therefore the right test, and the report is sent whole, as D-F allows.

### Pillar 3 — Custom agent tools: not touched by this iteration
There are no wrappers yet. The one-input-per-agent contract is in place: the Scout takes `PipelineScope`, and the Writer and QA-Legal take `AttemptRecord` through its views.

### Pillar 4 — Guardrails and attempt state: ✅ (contracts only)
* **Guardrails.** `GuardrailName` holds the 12 values in §6.7 order, and the order is asserted with `get_args`. `GuardrailViolation` holds `guardrail`, `tool_name`, `doc_id: str | None` (required, as §6.7 writes it) and `message`.
* **The attempt cap.** `MAX_ATTEMPTS_PER_DOC: Final[int] = 3` is at `:462`. `RunContext.max_attempts_per_doc` defaults to it, and `DocumentRecord.attempts_remaining` subtracts from it (§6.5).
* **Latest draft.** `latest_drafted` skips a failed latest attempt, which is tested with an audited attempt followed by a failed one (D-C rule 8).
* **Identity (DM6).** It is preserved: pydantic's default `revalidate_instances="never"` keeps the caller's `ScoutCandidate` and `AttemptRecord` objects. I probed `AttemptRecord.candidate is c`, `DocumentRecord.candidate is c`, `DocumentRecord.attempts[0] is r`, and `ToolResult(result=r).result is r`, parametrised and not, and all hold.
* **Set-once is enforced through the setters only.** A direct `record.draft = x` is still accepted, since the model is mutable and has no `validate_assignment`. The plan's test for this (setters raise on a second call) is met, and nothing in `src/` assigns the slots directly today. This is a forward risk for Iterations 8 and 9, not a finding (§4).

### Pillar 5 — Benchmark parity: ✅
* **JSON schemas.** I ran my own parity probe, importing Approach 1's `schemas.py` read-only with bytecode writing disabled. Byte-identical `model_json_schema()` for:
  * the 4 substrate models;
  * `ScoutCandidate`, `ScoutReport`, `ArticleDraft` and `QAReport`;
  * `ToolInvocation`, `AgentTelemetry`, `ModelRate`, `RemoteErrorDetail` and `PipelineConfig`;
  * `WorkerOutput[ScoutReport | ArticleDraft | QAReport]`.
* **Class docstrings** of the agent-facing output models are unchanged. They become schema `description`s.
* **Only the five [Amended] models differ,** exactly as §6 marks them: `PipelineScope`, `StageTelemetry`, `FailureRecord`, `DraftResult`, and `DraftMetadata`, whose only change is the `approach_name` default.
* **Two literals stay inline.** The new `Source` and `QAStatus` aliases are not substituted into the reused `RegulatoryUpdateSummary.source` or `QAReport.status`. That keeps the reused source text verbatim, which is correct under the "[Reused] copied unchanged" marker.
* **`DraftMetadata.approach_name`** is `"Approach 2 (Research Analyst)"`, and its field list is pinned.
* **`ReasoningSettings.supervisor`** follows D-H: alias `HSE_MODEL_SUPERVISOR_REASONING_EFFORT`, `medium` when unset, no `populate_by_name`, and a bare `SUPERVISOR` is ignored. A-M1 concerns the *empty* value only.
* **`.env.example`.** Every uncommented variable line is identical to Approach 1's, checked with `diff`. The one added line is the commented `#HSE_MODEL_SUPERVISOR_REASONING_EFFORT=medium`. The only other changes are comment rewording, which removes the ScopeParser and names the Supervisor on the strong binding.
* **Template.** `draft.md` is untouched, and the template-engine tests pass with F4's data change only.

### Pillar 6 — Substrate isolation and lifecycle: not touched by this iteration
`RunState.fatal_error: BaseException | None` and `arbitrary_types_allowed` on `RunState` alone are in place for D-D. Identity is tested.

### Pillar 7 — Rendering, telemetry and logging: ✅ (contracts only)
* **`StageTelemetry`.** `stage` is narrowed to `supervisor`, `scout`, `writer` and `qa_legal`, and `doc_id` and `attempt` default to `None` (§6.6).
* **`FailureStage`** has the 9 values in order, and `FailureRecord.attempt` sits after `doc_id`.
* **F4.** The data is adapted in `test_template_engine.py:318, 339-340` and `test_telemetry.py:112, 136`, as §1.5 allows. `template_engine.py` and `telemetry.py` are unmodified.

### Pillar 8 — Code quality: ✅ with two Minor items
* Imports are at the top and grouped, with zero E402. Every new function and method is fully annotated.
* The one `dict[str, Any]` return is `supervisor_view()`, the exception the skill sanctions. `for_supervisor()`'s `Any` usage is local.
* Every new `src` branch is exercised by a test: both setters on the first and second call, all three `for_supervisor` result branches and both error branches, and all four `state` outcomes.
* See A-m1 (stale section banners) and A-m2 (docstring layout).

## 3. Code review findings

| ID | Severity | Where | Finding |
| :--- | :---: | :--- | :--- |
| A-M1 | Major | `src/credentials.py:126`; the contract is stated at `src/credentials.py:100-104` and `.env.example:10-11` | `HSE_MODEL_SUPERVISOR_REASONING_EFFORT=` (empty) resolves to `supervisor == ""`, which I probed. `.env.example`, reworded in this iteration, says "Unset **or empty** means use the built-in role default (… Supervisor medium)". The Writer and QA-Legal get that behaviour from the consumer's `or` fallback (Approach 1 `orchestrator.py:993`). The Supervisor's default lives on the field instead, so nothing maps `""` back to `medium`. `build_model` (`src/model_factory.py:69`) would reject `""` as an unknown effort, and the run would fail as `CONFIG_ERROR` on a configuration the docs call valid. There is no test for the empty case |
| A-m1 | Minor | `src/schemas.py:222`, `:255` | Two section banners still cite Approach 1's section numbers, "SPECIFICATIONS §3.3" and "§3.4". In this repository §3.3 is "Terminology for the benchmark report", and there is no §3.4. The implementer updated the other banners in the same file. These are comments only. The Field descriptions at `:213` and `:276` and the `PipelineConfig` docstring at `:404` carry similar stale references, but they are part of reused JSON schemas and **must stay** verbatim |
| A-m2 | Minor | `tests/test_unit/test_docs_consistency.py:476-477` | The `_partial_binding_claims` docstring wraps its summary across two lines and closes the quotes on the text line. PEP 257 wants a one-line summary, a blank line, and the closing quotes on their own line |

**Pre-existing and not counted.** These are outside the configured ruff rules (`E`, `F`, `I`, `UP`, `B`) and not introduced here:
* `tests/test_unit/test_schemas.py` has E303 at `:406` and E302 at `:616`, from Approach 1's copy. `git show HEAD` shows both at `:358` and `:493`.
* W291 and W293 whitespace in `src/mcp_client.py`, `src/template_engine.py` and `tests/test_unit/test_template_engine.py`.

## 4. Anti-patterns and risks (forward directives, not findings)

1. **Iteration 7 must return `for_supervisor()` and never the `ToolResult` object.** When a tool returns a pydantic model, Strands serialises it with `model_dump_json()` (`.venv/Lib/site-packages/strands/tools/decorator.py:698-702`). For a `ToolResult[AttemptRecord]` that output carries the full `ArticleDraft` and `ScoutCandidate`, as the Iteration 4 test itself shows. The QA review should grep `src/tools.py` for any `return` of a `ToolResult` that is not `.for_supervisor()`.
2. **Iteration 8's one-line `error` must be written by code, never `str(exc)`.** A pydantic `ValidationError` raised on the Writer's structured output embeds `input_value=` fragments of the article, which would bypass D-F through `ToolResult.error`. Build the summary from the exception type and a fixed phrase. The full text belongs in `FailureRecord.message`.
3. **Iterations 8 and 9 must write the slots only through `set_draft` and `set_qa_report`,** and must never assign `.draft`, `.qa_report` or `.attempts = …` directly. The model does not stop direct assignment.
4. **View key order.** Computed fields serialise last, so every view ends with `doc_id`: `supervisor_view` is `context, attempt, qa_report, doc_id`. §7.2 lists the views as `{doc_id, context, attempt, …}`, while §6.2 lists QA-Legal's as `{context, doc_id, attempt, draft}`. The two sections disagree on order and agree on the set, so the set is the contract, and I raise no finding. Iteration 6 should confirm that the Writer and QA-Legal prompts refer to the keys by name, never by position.
5. **`RunState` cannot be dumped to JSON** once `fatal_error` is set, and it has no JSON schema. Iteration 5's acceptance tests, and any logging of the state, must use Python-mode `model_dump()` or targeted fields.
6. **Iteration 11.** `format_stage_telemetry` (`src/template_engine.py:122`, reused unchanged) will render `attempt=None` as the text `None` for Supervisor and Scout rows. Approach 1 rendered `1` there, because of its old default. This is a rendering question for Iteration 11's pre-flight, and it does not affect the contracts built here.
7. **`PipelineConfig.max_drafts`'s reused description** says "overrides PipelineScope.max_drafts", which is Approach 1's semantics. DM3 settles Approach 2's: the prompt limit reaches the Scout, and `--max-drafts` is enforced at save. The description stays for schema parity, and Iterations 10 and 14 must follow DM3, not the description.
8. **`tests/support/scripted.py:316`** still carries `time_window` in its scope arguments. It is harmless under `extra="ignore"`, and Iteration 7 restores those helpers.

**Where the sources disagree, stated explicitly:**
* **`qa_view`.** The plan row names the included keys but does not exclude `qa_report`. §7.2 gives the exact set without it. The code follows §7.2, the stricter source.
* **`supervisor_view`.** The plan row omits `context`, while §7.2 includes it. The code follows §7.2.
* **Forbidden keys.** The plan row lists four, while §7.2 lists five, adding `executive_summary`. The test follows §7.2.
* **The Supervisor's effort default.** D-H says it follows "the same style as the Writer's and QA-Legal's overrides", which in Approach 1 is a `None` field plus an `or` fallback at the consumer. §6.9 and the plan put `medium` on the field itself. The code follows §6.9, and that asymmetry is the root of A-M1. Both readings can be satisfied, so this is not a stop condition.

## 5. Remediation directives

* **A-M1** (`SPECIFICATIONS.md` §6.9, D-H; `.env.example:10-11`).
  * **Red.** Add a test in `tests/test_unit/test_credentials.py`: with `monkeypatch.setenv("HSE_MODEL_SUPERVISOR_REASONING_EFFORT", "")`, `ReasoningSettings(_env_file=None).supervisor == "medium"`. Also cover an empty line in a `tmp_path` `.env`. The test fails today with `'' == 'medium'`.
  * **Green.** In `src/credentials.py`, add a `field_validator("supervisor", mode="before")` that returns `value or "medium"`, and import `field_validator` at the top. Keep `str | None` and the alias as they are.
  * **Refactor.** Update the class docstring at `:100-104` to say that an empty Supervisor value also resolves to `medium` on the field.
  * **Why this fix.** It keeps `.env.example`'s documented rule true without adding a second default in Iteration 13.
* **A-m1** (`IMPLEMENTATION_PLAN.md` §1.5, docstrings and comments). In `src/schemas.py`, change `:222` to `# Scout Triage Models (SPECIFICATIONS.md §6.3)` and `:255` to `# Worker Telemetry Envelope (SPECIFICATIONS.md §6.3, §6.6)`. Do not touch `:213`, `:276` or `:404`.
* **A-m2** (PEP 257). Change `tests/test_unit/test_docs_consistency.py:476-477` to a one-line summary, such as `"""Return the partial-binding phrases and pattern matches found in ``text``, in lower case."""`, with any detail after a blank line.

After the fixes: `uv run pytest` green, `uvx ruff check src tests` clean, and the AC2 grep still empty.

---

# Iteration 4 — Architect Review (Stage 3, round 2)

**Reviewer:** Lead Architect, 2026-09-29.
**Scope:** the implementer's fix round for A-M1, A-m1, A-m2, QA-m1 and QA-m2, and a regression check over the whole working tree. It is the same ten modified files, plus this folder.

## 1. Overall verdict

**APPROVED**

All three architect findings and both QA findings are resolved as directed. Nothing regressed, and I raise no new finding.

**Verified independently:**
* `uv run pytest -q`: **415 passed**, 0 failed, 0 errors. That is round 1's 410, plus the two new test functions, plus three `test_document_uses_no_forbidden_term` cases for the three `.md` records in this folder. This matches the implementer's count.
* `uvx ruff check src tests --no-cache`: **All checks passed**. That is 0 in-scope findings and 0 pre-existing.
* `uvx pyright src/credentials.py src/schemas.py`: 0 errors.
* AC2: `grep -rn "RevisionPayload\|PipelineRun\|PipelineExitCode\|time_window" src` finds nothing (exit 1).
* JSON-schema parity: I re-ran the round-1 probe after the banner edits, loading Approach 1's `schemas.py` read-only with no bytecode written. `model_json_schema()` is identical for all 13 reused models and for `WorkerOutput[QAReport]`.

## 2. Resolution of round-1 findings

| ID | Status | Evidence |
| :--- | :---: | :--- |
| A-M1 | Resolved | `src/credentials.py:129-133` adds `@field_validator("supervisor", mode="before")`, which returns `value or "medium"`. `field_validator` is imported at the top (`:13`). The field keeps `str \| None`, `default="medium"` and its alias, as `SPECIFICATIONS.md:848` writes it. My probe gives these results. Unset → `medium`. `""` → `medium`. `high`, `low` and `medium` pass through unchanged. An explicit `None` through the alias → `medium`. A bare `SUPERVISOR=high` → still `medium`, since it is ignored. `writer` and `qa_legal` still give `''` for an empty value, which is unchanged and correct, because their fallback lives in the consumer. The class docstring (`:103-105`) now states the Supervisor's on-field rule. The test `test_supervisor_reasoning_effort_resolves_to_medium_when_empty` (`tests/test_unit/test_credentials.py:250-262`) covers an empty `.env` line, an empty environment variable, and QA's requested `high` case |
| A-m1 | Resolved | `src/schemas.py:222` reads `# Scout Triage Models (SPECIFICATIONS.md §6.3)`, and `:255` reads `# Worker Telemetry Envelope (SPECIFICATIONS.md §6.3, §6.6)`. The reused descriptions at `:213`, `:276` and `:404` still carry their Approach 1 text, which schema parity requires |
| A-m2 | Resolved | `tests/test_unit/test_docs_consistency.py:476` is a one-line PEP 257 summary |
| QA-m1 | Resolved | `tests/test_unit/test_schemas.py:1041-1048` covers a saved document with no attempts. That first assertion alone kills M28, the mutant that reads `not_drafted` before `saved`. The test also covers a saved document whose latest attempt failed |
| QA-m2 | Resolved | `tests/test_unit/test_schemas.py:1130-1132` shows that `fatal_error="boom"` raises a `ValidationError` naming `fatal_error`, which kills M24. `:1107-1113` shows that a nested dict validates into a `DocumentRecord`, which kills M41 |

**Two edge cases I considered and do not raise:**
* **An environment value of only whitespace**, such as `" "`, passes through as `" "`. The Writer's and QA-Legal's consumer `or` does the same thing, so the three roles behave alike. `.env.example` promises the default only for "unset or empty". In a `.env` file, dotenv strips an unquoted value, so `KEY= ` already reads as empty there.
* **The annotation `str | None`.** After the validator, `supervisor` can no longer hold `None`, so `str` would be the tighter type. §6.9 writes `str | None`, and the round-1 directive said to keep it. That is a contract choice, not a defect.

## 3. Pillar audit (delta)

The fix round changed no architectural surface. Pillars 1 to 7 stand as assessed in round 1:
* no code sequences anything;
* the D-F views are unchanged;
* the reused schemas still show parity.

Pillar 8 is now clean: A-m1 and A-m2 are closed, and ruff and pyright report nothing.

## 4. Forward directives

The eight round-1 forward directives in §4 above are unchanged. They still bind Iterations 5 to 14. The one directly relevant to this fix is this: Iteration 13's model factory call for the Supervisor can now read `ReasoningSettings().supervisor` directly, with no second `or "medium"` fallback. The field guarantees a non-empty value for every input except whitespace.

## 5. Remediation directives

None.
