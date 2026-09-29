# Iteration 3 — Fixes

<!-- Appended by the architect, Stage 3 round 1, 2026-09-29. Verdict APPROVED WITH RESERVATIONS (see ARCHITECT_REVIEW.md). -->

## 🏛️ Architecture & System Boundaries

No items. The moved code is verbatim, with only the three permitted amendments to `configure_logging`. Every handler carries a `CorrelationFilter`. The context-variable handling is safe under Strands' thread copies, which I verified in `strands/_async.py:43-44` and `strands/tools/mcp/mcp_client.py:456-457`. There are no `src` imports and no import-time side effects.

## 🧹 Code Quality & Conventions

* **A-m1: resolved** (fix round 1). The no-side-effects subprocess now has `timeout=60`.
* **A-m2: resolved** (fix round 1). The guard now requires a string literal under a routed logger, exempting only `logging_setup.py`'s `name` loop. Its docstring says the literal-only rule is deliberate.
* **A-m3: resolved** (fix round 1). `test_src_child_loggers_are_routed_by_ancestry` is deleted and `SRC_CHILD_LOGGER` is kept.

<!-- Appended by QA, Stage 3 round 1, 2026-09-29. Verdict CHANGES REQUIRED (see QA_REVIEW.md). -->

## 🧪 QA & Verification

* **QA-M1: resolved** (fix round 1), with a correction to the evidence. The stderr assertions were added as specified, but they do **not** catch M24. The redaction filter rewrites the record in place and the file handler runs first, so any record the file handler accepts is already masked on stderr. M24 leaks only a record that reaches stderr alone, one that passes a child logger's own lower level. The new test `test_the_stderr_mirror_redacts_a_record_the_file_handler_never_sees` kills M24, and the added assertions kill M24 combined with swapped handler order.
* **QA-m1: resolved** (fix round 1). The `CorrelationFilter` docstring now says a caller naming a different `doc_id` should pass its `attempt` too.

## ❓ Needs a decision

Moved by the orchestrator to `.agents/tasks/QUESTIONS.md` as **Q7 (Iteration 03)**, 2026-09-29. Answered B and recorded as P10.
