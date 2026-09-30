"""Draft ID allocation at save time (SPECIFICATIONS.md §6.8 "Draft IDs", D-B, D-C rules 9–11).

``save_draft`` allocates a document's draft ID when it marks the document saved, but the file is written only when
the run ends (AGENTS.md Rule 5). Approach 1's :func:`~src.template_engine.generate_draft_id` finds the next number
by scanning the drafts folder, which was enough when each draft was written as soon as it was numbered; here the
IDs allocated earlier in the run have no file yet, so they are counted from ``RunState.documents`` as well.
"""

import re
from typing import Final

from .schemas import RunState
from .template_engine import generate_draft_id

__all__ = ["allocate_draft_id"]

#: A draft ID exactly as ``f"draft_{stamp}_{n:03d}"`` builds it for ``n >= 1``: group 1 is the date, group 2 the
#: sequence number, three digits zero-padded or, past 999, four or more with no leading zero (``_0099`` is not one).
_DRAFT_ID_PATTERN: Final[re.Pattern[str]] = re.compile(r"^draft_(\d{8})_(\d{3}|[1-9]\d{3,})$")


def allocate_draft_id(state: RunState) -> str:
    """Allocate the next draft ID of the run's date, past every draft on disk and every ID this run allocated.

    The date is ``state.context.today``, the run's date, never the system clock. The disk contributes the number
    ``generate_draft_id`` would choose, and the run contributes one past the highest sequence among the documents
    already saved on that date, so IDs rise in save order. Nothing is written to disk: the drafts folder is scanned
    only if it exists, because ``generate_draft_id`` would otherwise create it.

    Args:
        state: The run state, read, never changed; call this before marking the document saved, so the document
            does not count an ID of its own.

    Returns:
        The draft ID, ``draft_{YYYYMMDD}_{XXX}``, the sequence zero-padded to three digits and wider past 999.
    """
    today = state.context.today
    stamp = today.strftime("%Y%m%d")
    drafts_dir = state.config.drafts_dir
    disk_next = _sequence(generate_draft_id(today, drafts_dir), stamp) if drafts_dir.is_dir() else 1
    run_highest = max(
        (
            _sequence(document.saved.draft_id, stamp)
            for document in state.documents.values()
            if document.saved is not None
        ),
        default=0,
    )
    return f"draft_{stamp}_{max(disk_next, run_highest + 1):03d}"


def _sequence(draft_id: str, stamp: str) -> int:
    """The sequence number of ``draft_id`` if it is a draft ID dated ``stamp``, else ``0``, which counts for nothing."""
    match = _DRAFT_ID_PATTERN.match(draft_id)
    if match is None or match.group(1) != stamp:
        return 0
    return int(match.group(2))
