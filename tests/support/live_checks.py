"""The checks the live end-to-end tests apply to a real run (Iteration 16, P14).

Kept apart from ``tests/test_live/`` so they can be proven offline by ``tests/test_unit/test_live_checks.py``: a live
test is deselected by default, and a defect in its checks would otherwise surface only as a false failure of a run
that cost real tokens. Each check returns what is wrong, as text, so a live failure reports every fault at once.
"""

import calendar
import re
from datetime import date
from pathlib import Path
from typing import Final

from src.schemas import MAX_ATTEMPTS_PER_DOC, RunState
from src.template_engine import _template_tokens
from tests.support.scripted import REAL_TEMPLATE_PATH

#: The ``Approach`` bullet every Approach 2 draft carries (SPECIFICATIONS.md §3.3, §6.8).
APPROACH_BULLET: Final[str] = "* **Approach:** Approach 2 (Research Analyst)"
#: The banner a draft saved with ``ERROR`` carries (AGENTS.md Rule 5).
COMPLIANCE_BANNER: Final[str] = "[UNRESOLVED COMPLIANCE ALERT]"

_RENDERED_ATTEMPTS: Final[re.Pattern[str]] = re.compile(r"^\* \*\*Revision Attempts:\*\* (\d+)\s*$", re.MULTILINE)
_ERROR_STATUS: Final[re.Pattern[str]] = re.compile(r"^\* \*\*Status:\*\* ERROR\s*$", re.MULTILINE)


def months_before(day: date, months: int) -> date:
    """The same day ``months`` whole months before ``day``, clamped to the last day of a shorter month.

    Args:
        day: The date to step back from.
        months: How many whole months to step back.

    Returns:
        The earlier date: 2026-10-05 gives 2026-07-05 for 3 months, and 2026-05-31 gives 2026-02-28.
    """
    year, month_index = divmod(day.year * 12 + day.month - 1 - months, 12)
    month = month_index + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def saved_draft_problems(state: RunState, drafts_dir: Path) -> list[str]:
    """Check what a run saved against Prompt A's draft checks; return each fault found, or ``[]``.

    The checks: at least one draft was saved; the draft files on disk are exactly the saved drafts; and each draft
    leaves no template token, used at most ``MAX_ATTEMPTS_PER_DOC`` attempts and renders that count, is marked
    Approach 2, and carries the compliance banner when its status is ``ERROR``.

    Args:
        state: The run's state, as ``src.app.run`` returned it.
        drafts_dir: The folder the run wrote its drafts to.

    Returns:
        One line per fault, in the order checked.
    """
    saved = [document for document in state.documents.values() if document.saved is not None]
    if not saved:
        return ["no draft was saved"]
    problems: list[str] = []
    on_disk = sorted(path.name for path in drafts_dir.glob("draft_*.md"))
    expected = sorted(f"{document.saved.draft_id}.md" for document in saved if document.saved is not None)
    if on_disk != expected:
        problems.append(f"draft files on disk {on_disk} differ from the saved drafts {expected}")
    tokens = _template_tokens(REAL_TEMPLATE_PATH.read_text(encoding="utf-8"))
    for document in saved:
        assert document.saved is not None  # narrowed above; restated for the type checker
        name = f"{document.saved.draft_id}.md"
        if not document.saved.path.is_file():
            problems.append(f"{name} was saved but not written")
            continue
        text = document.saved.path.read_text(encoding="utf-8")
        left = sorted(token for token in tokens if token in text)
        if left:
            problems.append(f"{name} leaves template tokens {left}")
        used = document.attempts_used
        if used > MAX_ATTEMPTS_PER_DOC:
            problems.append(f"{name} used {used} attempts, over the cap of {MAX_ATTEMPTS_PER_DOC}")
        rendered = _RENDERED_ATTEMPTS.search(text)
        if rendered is None or int(rendered.group(1)) != used:
            shown = "no" if rendered is None else rendered.group(1)
            problems.append(f"{name} renders {shown} attempt(s), but {used} were used")
        if APPROACH_BULLET not in text:
            problems.append(f"{name} is not marked Approach 2 (Research Analyst)")
        if _ERROR_STATUS.search(text) and COMPLIANCE_BANNER not in text:
            problems.append(f"{name} is ERROR without {COMPLIANCE_BANNER}")
    return problems
