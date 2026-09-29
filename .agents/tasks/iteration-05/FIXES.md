
<!-- Architect, Stage 3 round 1, 2026-09-29. Appended; other reviewers' sections are left as written. -->

## 🏛️ Architecture & System Boundaries

No findings. The §7.3 order, purity, data sources (`MAX_ATTEMPTS_PER_DOC` through `DocumentRecord`; `drafts_saved` from `documents`; `config.max_drafts`) and the "code only refuses" rule all hold. See `ARCHITECT_REVIEW.md` §2.

## 🧹 Code Quality & Conventions

*A-m1 resolved in fix round 1: the explicit `date_from`/`date_to` branch plus one typed `_SCOUT_PURITY_INPUTS` list; pyright 0 errors.*

<!-- QA, Stage 3 round 1, 2026-09-29. Appended; other reviewers' sections are left as written. -->

## 🧪 QA & Verification

Verdict **PASSED** (see `QA_REVIEW.md`). My runs: `uv run pytest -q` gives 629 passed, 0 failed, 0 errors; `uvx ruff check src tests --no-cache` gives `All checks passed!`; the live collect-only gives `no tests collected (629 deselected)`. No blocker or major finding. A-m1 above is confirmed; I reproduced its 4 pyright errors exactly, and I do not duplicate it here.

*Q-m1 resolved in fix round 1 with remedy A: `test_check_scout_fills_context_from_the_run_even_if_one_is_sent` added. It kills the reversed-merge mutant; the guardrail file has 210 passed.*

## ❓ Needs a decision

None from QA. The known conflict at `SPECIFICATIONS.md:348` ("or save A1" against rule 9) is already with the orchestrator. If the user keeps that row as written, the guardrail and `test_rule_8_walk_through_for_one_document` (`:716-720`) both change. If the doc is corrected, only the comment at `:716-719` needs rewording, so it no longer calls the row "illustrative".

<!-- Architect, Stage 3 round 2, 2026-09-29. Appended; other reviewers' sections are left as written. -->

## 🏛️ Architecture & System Boundaries

Round 2: no new findings.

## 🧹 Code Quality & Conventions

Round 2: A-m1 and Q-m1 are verified resolved. Pyright gives 0 errors on `src/guardrails.py` and `tests/test_unit/test_guardrails.py`; ruff reports all checks passed; `uv run pytest` gives 633 passed. There are no new findings.
