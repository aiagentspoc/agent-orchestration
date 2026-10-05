"""Docs-consistency contract for Approach 2 (IMPLEMENTATION_PLAN.md Iteration 1; DoD-5).

Every source of truth this project runs on is a Markdown file, so a document that drifts from the others is a
silent defect: a reviewer applying a stale rule flags correct code, and an implementer following a stale path
reads nothing. These tests pin what the documents must agree on, in the order of the plan's Red list:

* the eleven documents exist, and the two guides link to the other nine;
* every path a guide or workflow file cites exists, apart from those the workflow creates;
* ``.claude/settings.json`` grants the sibling folders and enables both MCP servers;
* nothing cites the scratchpad design plan that SPECIFICATIONS.md replaced;
* SPECIFICATIONS.md holds its models, guardrails, exit codes, decisions, tables and tool descriptions;
* the guardrail check order of §7.3 is the one the plan's Iteration 5 table states;
* the tool binding (P1), the attempt cap, the forbidden terms and the removed models are stated consistently.

Each scanning rule is a pure helper over text, with its own tests on synthetic strings, then applied to the files.
Text assertions only: no model, no substrate, no network and no I/O beyond reading the repository.
"""

import json
import os
import re
from pathlib import Path, PurePosixPath

import pytest

from src.schemas import MAX_ATTEMPTS_PER_DOC
from src.supervisor import build_supervisor_prompt

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS_DIR = REPO_ROOT / ".agents" / "docs"

AGENTS_MD = REPO_ROOT / "AGENTS.md"
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"
DESIGN_MD = DOCS_DIR / "DESIGN.md"
SPECIFICATIONS_MD = DOCS_DIR / "SPECIFICATIONS.md"
IMPLEMENTATION_PLAN_MD = DOCS_DIR / "IMPLEMENTATION_PLAN.md"

PROJECT_GUIDES: tuple[Path, ...] = (AGENTS_MD, CLAUDE_MD)
CORE_DOCS: tuple[Path, ...] = (DESIGN_MD, SPECIFICATIONS_MD, IMPLEMENTATION_PLAN_MD)
ARCHITECT_AGENT = REPO_ROOT / ".claude" / "agents" / "architect.md"
IMPLEMENTATION_AGENT = REPO_ROOT / ".claude" / "agents" / "implementation.md"
QA_AGENT = REPO_ROOT / ".claude" / "agents" / "qa.md"
IMPLEMENT_SKILL = REPO_ROOT / ".claude" / "skills" / "implement" / "SKILL.md"
ARCHITECT_REVIEW_SKILL = REPO_ROOT / ".agents" / "skills" / "architect-review" / "SKILL.md"
CODE_REVIEWER_SKILL = REPO_ROOT / ".agents" / "skills" / "code-reviewer" / "SKILL.md"
CLAUDE_SETTINGS = REPO_ROOT / ".claude" / "settings.json"
APPROACH_1_ROOT = REPO_ROOT.parent / "code-orchestration"
MCP_SERVER_ROOT = REPO_ROOT.parent / "mcp-server"

SUBAGENTS: tuple[Path, ...] = (ARCHITECT_AGENT, IMPLEMENTATION_AGENT, QA_AGENT)
REVIEW_SKILLS: tuple[Path, ...] = (ARCHITECT_REVIEW_SKILL, CODE_REVIEWER_SKILL)
WORKFLOW_FILES: tuple[Path, ...] = (*SUBAGENTS, IMPLEMENT_SKILL, *REVIEW_SKILLS)
#: The eleven documents the plan names: the two guides, the three core documents and the six workflow files.
ALL_DOCS: tuple[Path, ...] = PROJECT_GUIDES + CORE_DOCS + WORKFLOW_FILES
#: The documents that must not cite the scratchpad design plan. IMPLEMENTATION_PLAN.md is left out: it names the
#: ``**/scratchpad/*`` ignore rule (Iteration 0) and states this very check.
SCRATCHPAD_FREE_DOCS: tuple[Path, ...] = PROJECT_GUIDES + (DESIGN_MD, SPECIFICATIONS_MD) + WORKFLOW_FILES
#: The documents that restate the attempt cap: the guides, the three core documents, both review skills (normative
#: criteria, so a stale number there flags correct code) and the qa subagent. Records under ``.agents/tasks/``
#: are left out: they state what was true when they were written.
DOCS_STATING_THE_CAP: tuple[Path, ...] = (AGENTS_MD, *CORE_DOCS, *REVIEW_SKILLS, QA_AGENT)

#: SPECIFICATIONS.md §6: the 27 models, section by section (§6.1 to §6.10). ExitCode is an IntEnum.
SPEC_MODELS: tuple[str, ...] = (
    "RegulatoryUpdateSummary", "RegulatoryDocument", "CitationVerificationResult", "TDIServiceOffering",
    "AgentContext", "PipelineScope", "AttemptRecord",
    "ScoutCandidate", "ScoutReport", "ArticleDraft", "QAReport", "WorkerOutput",
    "RunContext", "DraftResult", "ToolResult",
    "DocumentRecord", "RunState",
    "ToolInvocation", "AgentTelemetry", "StageTelemetry", "ModelRate",
    "RemoteErrorDetail", "FailureRecord", "GuardrailViolation",
    "DraftMetadata",
    "PipelineConfig",
    "ExitCode",
)
#: SPECIFICATIONS.md §6.9: the settings classes, counted apart from the models.
SPEC_SETTINGS_CLASSES: tuple[str, ...] = ("ReasoningSettings", "CredentialManager", "ModelCredentials", "CostSettings")
#: The seven models that Approach 2 adds, marked ``# [New]`` in §6.
SPEC_NEW_MODELS: tuple[str, ...] = (
    "AgentContext", "AttemptRecord", "RunContext", "ToolResult", "DocumentRecord", "RunState", "GuardrailViolation",
)
#: SPECIFICATIONS.md §6.7, in order.
GUARDRAIL_NAMES: tuple[str, ...] = (
    "invalid_scope", "scout_already_run", "not_a_candidate", "attempt_limit", "initial_draft_exists", "not_audited",
    "revise_after_pass", "no_draft", "already_audited", "already_saved", "error_with_attempts_remaining",
    "draft_ceiling",
)
#: SPECIFICATIONS.md §6.10, in order.
EXIT_CODES: dict[str, int] = {
    "SUCCESS": 0, "NO_UPDATES": 1, "MCP_ERROR": 2, "PARSER_ERROR": 3, "PERSISTENCE_ERROR": 4, "CONFIG_ERROR": 5,
    "SUPERVISOR_ERROR": 6,
}
#: Terms the user has ruled out of Approach 2's documents. The one entry is a Strands feature the user has reserved
#: for a later proof of concept; see the project memory. It is held as a pattern, never as a literal, so this module
#: does not spell it: the pattern covers the camel-case, spaced, snake-case and kebab-case spellings, and does not
#: match the ``.agents/skills/`` folder, where ``agents`` is followed by ``/``.
FORBIDDEN_TERMS: tuple[re.Pattern[str], ...] = (re.compile(r"agent[ _-]?skills?", re.IGNORECASE),)
#: Folders the document scan never enters: version control, the environment and tool caches, and the git-ignored
#: run artefacts and scratchpads, none of which are documents of the repository.
_UNSCANNED_DIR_NAMES = frozenset(
    {".git", ".venv", ".pytest_cache", ".ruff_cache", "__pycache__", "node_modules", "scratchpad", "drafts", "logs"}
)

#: Models that no longer exist: SPECIFICATIONS.md §6's "Removed" list, all 11 names, the six the plan's Red list
#: names first. A document may name one only in a sentence about its removal or its history, recognised by
#: ``_REMOVAL_WORDS``.
REMOVED_MODELS: tuple[str, ...] = (
    "RevisionPayload", "PipelineRun", "PipelineExitCode", "SupervisorReport", "RunBudget", "GuardrailRefusal",
    "ScoutResult", "WriterResult", "QAResult", "SaveResult", "DocumentOutcome",
)
_REMOVED_MODEL = re.compile(r"\b(?:" + "|".join(REMOVED_MODELS) + r")\b")
#: The words the removal and history passages use: "Removed", "replaces", "renamed from", "becomes", "delete the
#: tests of", "without", "no longer", "do not exist" and "finds nothing".
_REMOVAL_WORDS = re.compile(
    r"\b(?:removed|replaces|replaced|renamed|becomes|delete|without|no longer|do not exist|finds nothing)\b",
    re.IGNORECASE,
)
#: Sentences end at ``.``, ``!`` or ``?`` followed by whitespace. A line with no such break, such as a table cell
#: or a code comment, is one unit.
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+")

#: Phrases that describe a sub-agent as holding a subset of the substrate tools, contradicting P1. "Scoped tools"
#: is Approach 1's column name for that idea. Each phrase is anchored on tools, access or connection, so generic
#: prose such as "limited to the top N candidates" does not match. Deliberately absent: "limits it to", which
#: DESIGN.md §4 uses for the prompt's boundary, "subset of", which also describes token counts, and "given only
#: some", which the plan uses to state this check.
PARTIAL_BINDING_PHRASES: tuple[str, ...] = (
    "scoped tools",
    "only the tools",
    "bound only to",
    "attached only",
    "subset of the tools",
    "subset of the substrate tools",
    "only has access to",
    "has access only to",
    "connected only to",
    "only connected to",
    "limited to the tools",
    "restricted to the tools",
)
#: Patterns for the claims a fixed phrase cannot anchor, because words come between the verb and "tools": "is
#: limited to the list and search tools". The match must end on "tools" within one sentence, so "limited to the top
#: N candidates" does not match (QA-m4, Iteration 1).
PARTIAL_BINDING_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(?:is|are) (?:limited|restricted) to\b[^.\n]{0,60}?\btools\b", re.IGNORECASE),
)
#: SPECIFICATIONS.md D-C decision table, pinned word for word: (QA status, attempts remaining, condition, decision),
#: row by row. The Supervisor prompt copies these rows (Iteration 13), so, like §7.1, they are benchmark constants.
DECISION_TABLE_ROWS: tuple[tuple[str, str, str, str], ...] = (
    ("`PASS`", "any", "—", "**Save.** Revising is refused by rule 7"),
    ("`WARNING`", "0", "—", "**Save**"),
    (
        "`WARNING`",
        "≥ 1",
        "At least one issue says a statement in the article is **wrong or unsupported**: a citation, obligation, "
        "deadline, threshold, penalty or date",
        "**Revise**",
    ),
    (
        "`WARNING`",
        "≥ 1",
        "The issues are advisory only (suggestions, optional extra references, notes that require no change), or "
        "there are no issues",
        "**Save**",
    ),
    ("`ERROR`", "0", "—", "**Save,** with the compliance banner"),
    (
        "`ERROR`",
        "≥ 1",
        "Always",
        "**Revise.** There is no early save for `ERROR`: the Writer gets every remaining attempt, and `save_draft` "
        "refuses an `ERROR` while attempts remain (rule 9)",
    ),
    ("Writer call failed", "≥ 1", "No draft exists yet", "**Retry** `writer_tool(revise=False)`"),
    (
        "Writer call failed",
        "≥ 1",
        "An earlier draft exists",
        "Apply this table to the latest draft's QA report; the earlier draft is still the latest one (rule 8)",
    ),
    ("Writer call failed", "0", "No draft exists", "**Skip** the document; it is recorded as unfinished"),
    ("Writer call failed", "0", "An earlier draft exists", "**Save** the earlier draft"),
)
#: IMPLEMENTATION_PLAN.md §2 and SPECIFICATIONS.md §8.3: the bold statement that opens each decision's row.
IMPLEMENTATION_DECISIONS: dict[str, str] = {
    "P1": "Tool binding matches Approach 1",
    "P2": "A saved document is closed",
    "P3": "An unknown `doc_id` is `not_a_candidate`",
    "P4": "No live runs",
    "P5": "Commit per iteration",
    "P6": "Exit-code severity is the numeric maximum",
    "P7": "The Approach 1 baseline is the local working tree",
    "P8": "The draft template is Approach 1's current one",
    "P9": "`src/mcp_client.py` may gain type annotations only",
    "P10": "API-key redaction stays Approach 1's",
    "P11": "Per-draft latency counts only the Supervisor's own time",
    "P12": 'Run totals are logged once, on "Run completed"',
    "P13": "`PARSER_ERROR` needs a Supervisor that ended on its own",
}
#: SPECIFICATIONS.md D-I event catalogue: (level, event), in order.
LOG_EVENTS: tuple[tuple[str, str], ...] = (
    ("INFO", "Run started"),
    ("INFO", "MCP session opened"),
    ("INFO", "Scope built by the Supervisor"),
    ("INFO", "Supervisor turn completed"),
    ("INFO", "Model HTTP call"),
    ("INFO", "Tool call started / completed"),
    ("INFO", "Sub-agent invocation started / completed"),
    ("INFO", "Scout result"),
    ("INFO", "QA verdict `PASS`"),
    ("INFO", "Revision requested"),
    ("INFO", "Document marked saved"),
    ("INFO", "Draft rendered (run end)"),
    ("INFO", "Run completed"),
    ("WARNING", "QA verdict `WARNING` or `ERROR`"),
    ("WARNING", "Draft rendered with `[UNRESOLVED COMPLIANCE ALERT]`"),
    ("WARNING", "Guardrail violation"),
    ("WARNING", "Recoverable tool failure returned to the Supervisor"),
    ("WARNING", "Candidate left unsaved at run end"),
    ("ERROR", "Configuration failure"),
    ("ERROR", "MCP session failed to open, or died mid-run"),
    ("ERROR", "Supervisor invocation failed (provider or SDK error)"),
    ("ERROR", "Draft render or write failure"),
    ("ERROR", "Fatal abort triggered (D-D)"),
)
#: SPECIFICATIONS.md §7.1, word for word: the tool descriptions the Supervisor model sees, in order.
SUPERVISOR_TOOL_DESCRIPTIONS: dict[str, str] = {
    "scout_tool": (
        "Find and rank the regulatory updates within a scope. Call it once per run, with the scope you built from "
        "the user's prompt: `date_from` and `date_to` as ISO YYYY-MM-DD dates resolved against the current date, "
        "`sources` (any of EUR_LEX, GAZZETTA_UFFICIALE, INAIL; empty for all), `sector_constraints` (lowercase "
        "sectors; empty for all) and `max_drafts` (only when the user stated a limit, otherwise null). Returns the "
        "ranked candidates. An invalid scope is refused with a message; correct it and call again."
    ),
    "writer_tool": (
        "Ask the Writer to draft the article for one candidate (`revise=false`), or to revise the latest draft "
        "against its QA report (`revise=true`). Each call uses one of the document's attempts, whether or not it "
        "succeeds. Returns the attempt number and the run limits; the article itself is never returned to you."
    ),
    "qa_tool": (
        "Ask QA-Legal to audit the latest draft of one document. Each draft can be audited once. Returns the QA "
        "report: status (PASS, WARNING or ERROR), issues, review notes and verified citations."
    ),
    "save_draft": (
        "Mark one document's latest audited draft as saved. The draft file is written when the run ends. PASS and "
        "WARNING may be saved at any attempt; ERROR only when no attempts remain. Returns the draft ID and path."
    ),
}
#: SPECIFICATIONS.md §7.3: each Supervisor tool's guardrails in check order; the first that fails is returned. For
#: ``writer_tool``, ``initial_draft_exists`` applies when ``revise=False`` and the last two when ``revise=True``.
GUARDRAIL_CHECK_ORDER: dict[str, tuple[str, ...]] = {
    "scout_tool": ("scout_already_run", "invalid_scope"),
    "writer_tool": (
        "not_a_candidate", "already_saved", "attempt_limit", "initial_draft_exists", "not_audited", "revise_after_pass",
    ),
    "qa_tool": ("not_a_candidate", "already_saved", "no_draft", "already_audited"),
    "save_draft": ("not_a_candidate", "already_saved", "not_audited", "error_with_attempts_remaining", "draft_ceiling"),
}
#: IMPLEMENTATION_PLAN.md Iteration 5 names each tool by the check function that guards it.
_CHECK_FUNCTION_TOOLS: dict[str, str] = {
    "check_scout": "scout_tool", "check_writer": "writer_tool", "check_qa": "qa_tool", "check_save": "save_draft",
}

_FENCED_BLOCK = re.compile(r"^[ \t]*```.*?^[ \t]*```[^\n]*$", re.MULTILINE | re.DOTALL)
_MARKDOWN_LINK = re.compile(r"\[[^\]]*\]\(\s*([^)\s]+)(?:\s+\"[^\"]*\")?\s*\)")
_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_PYTHON_FENCE = re.compile(r"^```python\n(.*?)^```", re.MULTILINE | re.DOTALL)
_CLASS_LINE = re.compile(r"^class (\w+).*$", re.MULTILINE)
_TABLE_SEPARATOR_CELL = re.compile(r"^:?-{3,}:?$")
#: A Markdown table's cell border: a ``|`` that is not escaped as ``\|``.
_CELL_BORDER = re.compile(r"(?<!\\)\|")
#: The number words that a prose statement of the cap may use instead of digits.
_NUMBER_WORDS: dict[str, int] = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
#: A number in prose, digits or a number word, as a whole word, so that "none" is not read as "one".
_PROSE_NUMBER = r"\b(\d+|" + "|".join(_NUMBER_WORDS) + r")\b"
#: Every phrasing that states the attempt cap, each capturing the number. The prose phrasings match in any case,
#: with digits or number words. Deliberately absent: a bare "attempts N", which is an attempt number ("attempt 1
#: of 3", "attempts 2" in a scenario), and "up to N revisions", which counts revisions, not attempts.
_CAP_STATEMENTS: tuple[re.Pattern[str], ...] = (
    re.compile(r"MAX_ATTEMPTS_PER_DOC\s*==?\s*(\d+)"),
    re.compile(r"max_attempts_per_doc:\s*int\s*=\s*(\d+)"),
    re.compile(_PROSE_NUMBER + r" Writer attempts", re.IGNORECASE),
    re.compile(_PROSE_NUMBER + r" attempts per document", re.IGNORECASE),
    re.compile(_PROSE_NUMBER + r"-attempt (?:cap|budget)", re.IGNORECASE),
    re.compile(r"\battempt cap is (?:fixed at )?" + _PROSE_NUMBER, re.IGNORECASE),
    re.compile(r"\bcap(?:ped)? (?:of|at) " + _PROSE_NUMBER, re.IGNORECASE),
    re.compile(r"\b(?:up to|maximum of|max(?:imum)?) " + _PROSE_NUMBER + r" (?:Writer )?attempts", re.IGNORECASE),
)
#: The only scratchpad in the repository holds the superseded design plan, so any mention of one cites it.
_SCRATCHPAD = re.compile(r"scratchpad", re.IGNORECASE)
#: Two or more characters before the colon, so a Windows drive letter (``C:``) is not taken for a URL scheme.
_URL_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]+:")

#: File suffixes that make a slash-free token a file name. Without one, a dotted token is code, such as
#: ``ToolResult.error`` or ``Agent.cancel()``, or a model name such as ``gpt-5.4``.
_FILE_SUFFIXES = frozenset({".md", ".py", ".json", ".toml", ".lock", ".log", ".txt", ".yaml", ".yml", ".png"})
#: A token holding one of these is a placeholder, not a path: ``.claude/agents/<role>.md``,
#: ``draft_{YYYYMMDD}_{XXX}.md``, ``run_YYYYMMDD.log`` or ``*_TOOL_NAMES``.
_PLACEHOLDER_MARKERS = ("<", ">", "{", "}", "*", "YYYY")
#: Slash-containing tokens that name something other than a file: the git branch of P5.
_NON_PATH_TOKENS = frozenset({"approach-2/implementation"})

#: Paths the workflow itself creates while it runs, exempt from the existence check (Iteration 1, Red): the
#: per-iteration folders, written ``iteration-NN`` or as a two-digit example such as ``iteration-03``, and
#: ``QUESTIONS.md``. The bare artifact names are the same files, cited without their folder.
_WORKFLOW_CREATED_PATH = re.compile(r"^\.agents/tasks/(?:iteration-(?:NN|\d{2})(?:/|$)|QUESTIONS\.md$)")
_WORKFLOW_ARTIFACT_NAMES = frozenset(
    {"ARCHITECT_REVIEW.md", "QA_REVIEW.md", "FIXES.md", "WALKTHROUGH.md", "QUESTIONS.md"}
)


def _rel(path: Path) -> str:
    """Return ``path`` relative to the repository root, with forward slashes, for test IDs and messages."""
    return path.relative_to(REPO_ROOT).as_posix()


def _read(path: Path) -> str:
    """Read a document as UTF-8; universal newlines make CRLF checkouts read the same as LF ones."""
    return path.read_text(encoding="utf-8")


def _strip_fenced_blocks(text: str) -> str:
    """Remove fenced code blocks, which render as literal text rather than as links or citations."""
    return _FENCED_BLOCK.sub("", text)


def _markdown_link_targets(text: str) -> list[str]:
    """Return the file targets of the Markdown links outside fenced blocks, without ``#fragment`` suffixes.

    URLs (any ``scheme:``), pure anchors and empty targets are dropped: they are not files in the repository.
    """
    targets: list[str] = []
    for raw in _MARKDOWN_LINK.findall(_strip_fenced_blocks(text)):
        target = raw.split("#", 1)[0]
        if target and not _URL_SCHEME.match(target):
            targets.append(target)
    return targets


def _looks_like_path(token: str) -> bool:
    """Return True when an inline-code or link token names a file or folder.

    Excluded, by rule: anything with whitespace (commands and prose), slash commands such as ``/implement``,
    URLs, placeholders (``_PLACEHOLDER_MARKERS``) and the branch name. Kept: a token with a path separator, or
    one ending in a known file suffix.
    """
    if any(character.isspace() for character in token) or token.startswith("/") or _URL_SCHEME.match(token):
        return False
    if any(marker in token for marker in _PLACEHOLDER_MARKERS) or token in _NON_PATH_TOKENS:
        return False
    if "/" in token or "\\" in token:
        return True
    return PurePosixPath(token).suffix.lower() in _FILE_SUFFIXES


def _is_workflow_created(token: str) -> bool:
    """Return True for a path the workflow creates as it runs, which need not exist yet."""
    return bool(_WORKFLOW_CREATED_PATH.match(token)) or token in _WORKFLOW_ARTIFACT_NAMES


def _candidate_locations(token: str, citing_file: Path, *, is_link: bool, repo_root: Path = REPO_ROOT) -> list[Path]:
    """Return the locations a cited path may denote, in the order they are tried; no file system access.

    * A bare file name resolves against the repository root, ``.agents/docs/``, the citing file's folder, or
      Approach 1's root (``../code-orchestration/``), as the plan allows.
    * A relative path in backticks is read from the repository root, the plan's convention; ``../`` reaches the
      sibling folders.
    * A relative link target is read from the citing file's folder, as a Markdown renderer reads it.
    """
    target = token.split("#", 1)[0]
    if Path(target).is_absolute():
        return [Path(target)]
    if "/" not in target and "\\" not in target:
        bases = [repo_root, repo_root / ".agents" / "docs", citing_file.parent, repo_root.parent / "code-orchestration"]
    elif is_link:
        bases = [citing_file.parent]
    else:
        bases = [repo_root]
    return [base / target for base in bases]


def _path_resolves(token: str, citing_file: Path, *, is_link: bool) -> bool:
    """Return True when any location a cited path may denote exists on disk."""
    return any(location.exists() for location in _candidate_locations(token, citing_file, is_link=is_link))


def _between(text: str, start: str, end: str, source: Path) -> str:
    """Return the text between the first ``start`` marker and the next ``end`` marker after it."""
    assert start in text, f"{_rel(source)} has no {start!r}"
    section = text.split(start, 1)[1]
    assert end in section, f"{_rel(source)} has no {end!r} after {start!r}"
    return section.split(end, 1)[0]


def _spec_section(start: str, end: str) -> str:
    """Return the text of SPECIFICATIONS.md between the first ``start`` marker and the next ``end`` after it."""
    return _between(_read(SPECIFICATIONS_MD), start, end, SPECIFICATIONS_MD)


def _python_classes(text: str) -> list[tuple[str, str]]:
    """Return ``(name, class line)`` for each top-level ``class`` inside the ``python`` fences of ``text``."""
    return [
        (match.group(1), match.group(0))
        for block in _PYTHON_FENCE.findall(text)
        for match in _CLASS_LINE.finditer(block)
    ]


def _literal_values(text: str, name: str) -> list[str]:
    """Return the string values of the multi-line ``name = Literal[...]`` in ``text``, in order.

    The block ends at the first line that is only ``]``, so a bracketed comment such as ``# [New]`` on the
    opening line does not end it early.
    """
    opening = f"{name} = Literal["
    assert opening in text, f"no {opening!r} found"
    block = text.split(opening, 1)[1].split("\n]", 1)[0]
    return re.findall(r'^\s+"(\w+)",', block, re.MULTILINE)


def _table_rows(text: str) -> list[list[str]]:
    """Return the body rows of the Markdown table in ``text`` as lists of stripped cells.

    The header row and the ``:---`` separator row are dropped. Cells are split on each unescaped ``|``; an escaped
    ``\\|``, a literal pipe in Markdown, stays inside its cell as written.
    """
    rows = [
        [cell.strip() for cell in _CELL_BORDER.split(line.strip().strip("|"))]
        for line in text.splitlines()
        if line.lstrip().startswith("|")
    ]
    return [cells for cells in rows[1:] if not all(_TABLE_SEPARATOR_CELL.match(cell) for cell in cells)]


def _guardrails_in_order(cell: str) -> tuple[str, ...]:
    """Return the guardrail names written in backticks in ``cell``, in order; other code spans are skipped."""
    return tuple(token for token in _INLINE_CODE.findall(cell) if token in GUARDRAIL_NAMES)


def _decisions_without_their_statement(section: str) -> list[str]:
    """Return the labels of ``IMPLEMENTATION_DECISIONS`` whose row in ``section`` does not open with its statement.

    The label may be bold (the plan's ``| **P1** |``) or plain (the specification's ``| P1 |``). The match stops
    before the ``.`` or ``,`` that closes the bold statement, which differs between the two documents for P5 and P6.
    """
    return [
        label
        for label, statement in IMPLEMENTATION_DECISIONS.items()
        if not re.search(r"^\|\s*\**" + label + r"\**\s*\|\s*\*\*" + re.escape(statement), section, re.MULTILINE)
    ]


def _repository_documents() -> list[Path]:
    """Return every Markdown file in the repository, sorted, outside the ``_UNSCANNED_DIR_NAMES`` folders."""
    documents: list[Path] = []
    for folder, subfolders, files in os.walk(REPO_ROOT):
        subfolders[:] = [name for name in subfolders if name not in _UNSCANNED_DIR_NAMES]
        documents.extend(Path(folder) / name for name in files if name.endswith(".md"))
    return sorted(documents)


def _forbidden_term_hits(text: str) -> list[str]:
    """Return every occurrence of a ``FORBIDDEN_TERMS`` pattern in ``text``, as written."""
    return [match.group(0) for pattern in FORBIDDEN_TERMS for match in pattern.finditer(text)]


def _current_mentions_of_removed_models(text: str) -> list[str]:
    """Return each sentence that names a removed model without saying it was removed, renamed or replaced."""
    return [
        sentence
        for line in text.splitlines()
        for sentence in _SENTENCE_BREAK.split(line)
        if _REMOVED_MODEL.search(sentence) and not _REMOVAL_WORDS.search(sentence)
    ]


def _cap_value(number: str) -> int:
    """Return the value of a captured cap: digits, or one of ``_NUMBER_WORDS`` in any case."""
    return int(number) if number.isdigit() else _NUMBER_WORDS[number.lower()]


def _stated_attempt_caps(text: str) -> list[int]:
    """Return every number ``text`` states as the attempt cap, in any of ``_CAP_STATEMENTS``' phrasings, in order.

    A number that two phrasings both read, such as the 2 of "up to 2 Writer attempts", is one statement: it is
    counted once, keyed by its position in ``text``.
    """
    stated = {
        match.start(1): _cap_value(match.group(1)) for pattern in _CAP_STATEMENTS for match in pattern.finditer(text)
    }
    return [stated[position] for position in sorted(stated)]


def _states_the_cap_canonically(text: str) -> bool:
    """Return True when ``text`` states the cap as ``MAX_ATTEMPTS_PER_DOC = 3`` or as "3 Writer attempts"."""
    return f"MAX_ATTEMPTS_PER_DOC = {MAX_ATTEMPTS_PER_DOC}" in text or f"{MAX_ATTEMPTS_PER_DOC} Writer attempts" in text


def _partial_binding_claims(text: str) -> list[str]:
    """Return the partial-binding phrases and pattern matches found in ``text``, in lower case."""
    lowered = text.lower()
    phrases = [phrase for phrase in PARTIAL_BINDING_PHRASES if phrase in lowered]
    return phrases + [match.group(0) for pattern in PARTIAL_BINDING_PATTERNS for match in pattern.finditer(lowered)]


def _scratchpad_mentions(text: str) -> list[str]:
    """Return every line that mentions a scratchpad."""
    return [line for line in text.splitlines() if _SCRATCHPAD.search(line)]


def _settings_directory(entry: str) -> str:
    """Normalise an ``additionalDirectories`` entry for comparison.

    A relative entry is read from the repository root; the result is resolved, and its case is folded on Windows,
    whose file system ignores case.
    """
    path = Path(entry)
    return os.path.normcase((path if path.is_absolute() else REPO_ROOT / path).resolve())


def _cited_path_tokens(text: str) -> list[tuple[str, bool]]:
    """Return ``(token, is_link)`` for every path cited outside fenced blocks, in inline code or as a link."""
    inline = [(token, False) for token in _INLINE_CODE.findall(_strip_fenced_blocks(text)) if _looks_like_path(token)]
    links = [(target, True) for target in _markdown_link_targets(text) if _looks_like_path(target)]
    return inline + links


@pytest.mark.parametrize("path", ALL_DOCS, ids=_rel)
def test_required_document_exists(path: Path) -> None:
    """Each of the eleven documents the plan names exists."""
    assert path.is_file(), f"{_rel(path)} not found"


def test_markdown_link_targets_strips_fragments_and_skips_urls_anchors_and_fences() -> None:
    """The link extractor keeps file targets only, and ignores links inside fenced code blocks."""
    text = (
        "See [the spec](.agents/docs/SPECIFICATIONS.md#6-data-model) and [a title](CLAUDE.md \"Claude\").\n"
        "Not files: [web](https://strandsagents.com/), [anchor](#top), [mail](mailto:someone@example.com).\n"
        "```text\n[fenced](not/a/link.md)\n```\n"
    )
    assert _markdown_link_targets(text) == [".agents/docs/SPECIFICATIONS.md", "CLAUDE.md"]


@pytest.mark.parametrize(
    ("guide", "target"),
    [(guide, target) for guide in PROJECT_GUIDES for target in CORE_DOCS + WORKFLOW_FILES],
    ids=_rel,
)
def test_project_guide_links_to_each_document_and_workflow_file(guide: Path, target: Path) -> None:
    """AGENTS.md and CLAUDE.md each link to the three core documents and to every workflow file."""
    linked = {(guide.parent / link).resolve() for link in _markdown_link_targets(_read(guide))}
    assert target.resolve() in linked, f"{_rel(guide)} has no Markdown link to {_rel(target)}"


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        (".agents/docs/DESIGN.md", True),
        ("SPECIFICATIONS.md", True),
        ("../code-orchestration/", True),
        ("src/", True),
        ("uv.lock", True),
        (".mcp.json", True),
        ("/implement", False),
        ("/implement <n>", False),
        ("approach-2/implementation", False),
        (".claude/agents/<role>.md", False),
        ("run_YYYYMMDD.log", False),
        ("draft_{YYYYMMDD}_{XXX}.md", False),
        ("ToolResult.error", False),
        ("Agent.cancel()", False),
        ("gpt-5.4", False),
        ("uv run pytest tests/", False),
        ("*_TOOL_NAMES", False),
    ],
)
def test_looks_like_path_classifies_citation_tokens(token: str, expected: bool) -> None:
    """Paths are recognised; slash commands, the branch name, placeholders, code and commands are not."""
    assert _looks_like_path(token) is expected


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        (".agents/tasks/iteration-NN/", True),
        (".agents/tasks/iteration-03/", True),
        (".agents/tasks/iteration-NN/FIXES.md", True),
        (".agents/tasks/QUESTIONS.md", True),
        ("WALKTHROUGH.md", True),
        (".agents/tasks/", False),
        (".agents/tasks/iteration-3/", False),
        ("SPECIFICATIONS.md", False),
    ],
)
def test_is_workflow_created_matches_only_the_workflow_artifacts(token: str, expected: bool) -> None:
    """Only the per-iteration folders, QUESTIONS.md and the artifact names the workflow writes are exempt."""
    assert _is_workflow_created(token) is expected


def test_candidate_locations_try_four_bases_for_bare_names_and_one_for_relative_paths() -> None:
    """A bare name is tried at root, docs, the citing folder and Approach 1; a relative path only as written."""
    root = Path("/repos/agent-orchestration")
    citing_file = root / ".claude" / "agents" / "qa.md"

    def locations(token: str, *, is_link: bool = False) -> list[Path]:
        return _candidate_locations(token, citing_file, is_link=is_link, repo_root=root)

    assert locations("README.md") == [
        root / "README.md",
        root / ".agents" / "docs" / "README.md",
        root / ".claude" / "agents" / "README.md",
        Path("/repos/code-orchestration/README.md"),
    ]
    assert locations("tests/conftest.py") == [root / "tests" / "conftest.py"]  # never retried against Approach 1
    assert locations("../code-orchestration/tests/") == [root / ".." / "code-orchestration" / "tests"]
    assert locations("src/agents.py", is_link=True) == [root / ".claude" / "agents" / "src" / "agents.py"]
    assert locations("qa.md#section", is_link=True)[2] == citing_file  # the fragment is dropped
    assert locations(str(REPO_ROOT / "AGENTS.md")) == [REPO_ROOT / "AGENTS.md"]  # an absolute path is itself


@pytest.mark.parametrize("path", PROJECT_GUIDES + WORKFLOW_FILES, ids=_rel)
def test_every_cited_path_exists(path: Path) -> None:
    """Every file path a guide or workflow file cites, in backticks or as a link, exists on disk.

    Fenced code blocks are not scanned: they hold commands and layout sketches, not citations. The paths the
    workflow itself creates (``_is_workflow_created``) are exempt.
    """
    missing = [
        token
        for token, is_link in _cited_path_tokens(_read(path))
        if not _is_workflow_created(token) and not _path_resolves(token, path, is_link=is_link)
    ]
    assert missing == [], f"{_rel(path)} cites paths that do not exist: {missing}"


def test_settings_directory_resolves_relative_entries_from_the_repository_root() -> None:
    """A relative ``additionalDirectories`` entry is read from the repository root; an absolute one as it is."""
    assert _settings_directory("../code-orchestration") == _settings_directory(str(APPROACH_1_ROOT))
    assert _settings_directory("../mcp-server/") == _settings_directory(str(MCP_SERVER_ROOT))
    assert _settings_directory("../code-orchestration") != _settings_directory("../mcp-server")


def test_claude_settings_grant_sibling_read_access_and_enable_both_mcp_servers() -> None:
    """settings.json grants read access to both sibling folders and enables both .mcp.json servers.

    Without them an unattended ``/implement`` run stalls on permission prompts (``.claude/skills/implement``).
    """
    assert CLAUDE_SETTINGS.is_file(), f"{_rel(CLAUDE_SETTINGS)} not found"
    settings = json.loads(_read(CLAUDE_SETTINGS))
    granted = {_settings_directory(entry) for entry in settings["permissions"]["additionalDirectories"]}
    assert granted == {_settings_directory(str(APPROACH_1_ROOT)), _settings_directory(str(MCP_SERVER_ROOT))}
    assert set(settings["enabledMcpjsonServers"]) == {"strands-agents", "hse-easy-mock"}


def test_scratchpad_mentions_finds_the_word_in_any_case_and_nothing_else() -> None:
    """The scratchpad check matches the folder name in any case, and not the plan's own file name."""
    text = "Read .agents/scratchpad/plan.md first.\nThe Scratchpad draft.\nSee IMPLEMENTATION_PLAN.md and plan.md.\n"
    assert _scratchpad_mentions(text) == ["Read .agents/scratchpad/plan.md first.", "The Scratchpad draft."]


@pytest.mark.parametrize("path", SCRATCHPAD_FREE_DOCS, ids=_rel)
def test_document_does_not_cite_the_scratchpad_design_plan(path: Path) -> None:
    """SPECIFICATIONS.md replaced the scratchpad design plan, so no guide, workflow file or design document cites it."""
    assert _scratchpad_mentions(_read(path)) == [], f"{_rel(path)} mentions the scratchpad"


def test_python_classes_reads_class_lines_inside_python_fences_only() -> None:
    """The class parser reads ``python`` fences only, and keeps each class line for its marker comment."""
    text = "```python\nclass A:  # [New]\n    x: int\nclass B(C):\n```\nclass D:\n```text\nclass E:\n```\n"
    assert _python_classes(text) == [("A", "class A:  # [New]"), ("B", "class B(C):")]


def test_literal_values_is_not_cut_short_by_a_bracketed_marker_comment() -> None:
    """``# [New]`` on the ``Literal[`` line must not end the value list at its ``]``."""
    text = 'Name = Literal[     # [New] see [D-C]\n    "first",        # rule 1\n    "second",\n]\n'
    assert _literal_values(text, "Name") == ["first", "second"]


def test_specification_data_model_declares_exactly_the_listed_models() -> None:
    """§6 declares the 27 models and the 4 settings classes, each once, and states those totals."""
    classes = [name for name, _ in _python_classes(_spec_section("### 6. Data model", "### 7. Interfaces"))]
    assert len(SPEC_MODELS) == 27 and len(SPEC_SETTINGS_CLASSES) == 4
    assert sorted(classes) == sorted(SPEC_MODELS + SPEC_SETTINGS_CLASSES)
    totals = (
        f"{len(SPEC_MODELS)} models, {len(SPEC_NEW_MODELS)} of them new, "
        f"plus the {len(SPEC_SETTINGS_CLASSES)} settings classes of §6.9"
    )
    assert totals in _read(SPECIFICATIONS_MD), f"SPECIFICATIONS.md §6 does not state the totals {totals!r}"


def test_specification_marks_exactly_the_seven_new_models() -> None:
    """The classes marked ``# [New]`` in §6 are the seven models Approach 2 adds."""
    classes = _python_classes(_spec_section("### 6. Data model", "### 7. Interfaces"))
    assert {name for name, line in classes if "# [New]" in line} == set(SPEC_NEW_MODELS)


def test_specification_settings_classes_live_in_section_6_9() -> None:
    """§6.9 holds the 4 settings classes, alongside ``PipelineConfig``."""
    classes = [name for name, _ in _python_classes(_spec_section("#### 6.9 Configuration", "#### 6.10"))]
    assert sorted(classes) == sorted((*SPEC_SETTINGS_CLASSES, "PipelineConfig"))


def test_specification_lists_the_twelve_guardrail_names_in_order() -> None:
    """§6.7 ``GuardrailName`` holds the 12 guardrails, in the order the specification gives them."""
    section = _spec_section("#### 6.7 Failures and guardrails", "#### 6.8")
    assert tuple(_literal_values(section, "GuardrailName")) == GUARDRAIL_NAMES


def test_specification_lists_the_seven_exit_codes_with_values_0_to_6() -> None:
    """§6.10 ``ExitCode`` holds the seven members, valued 0 to 6 in order."""
    section = _spec_section("#### 6.10 Run result", "### 7. Interfaces")
    members = re.findall(r"^\s+([A-Z_]+) = (\d+)", section, re.MULTILINE)
    assert [(name, int(value)) for name, value in members] == list(EXIT_CODES.items())


def test_specification_records_decisions_d_a_to_d_j() -> None:
    """§5 has one heading per architecture decision, D-A to D-J, in order."""
    headings = re.findall(r"^#### D-([A-Z])\.", _read(SPECIFICATIONS_MD), re.MULTILINE)
    assert headings == list("ABCDEFGHIJ")


def test_specification_records_every_implementation_decision_in_order() -> None:
    """§8.3 has one row per implementation decision in ``IMPLEMENTATION_DECISIONS``, P1 to P13, in order."""
    section = _spec_section("#### 8.3 Implementation decisions", "#### 8.4")
    assert re.findall(r"^\| (P\d+) \|", section, re.MULTILINE) == list(IMPLEMENTATION_DECISIONS)


def test_decisions_without_their_statement_reports_a_drifted_statement_under_either_label_style() -> None:
    """A row whose bold statement drifted is reported even though its label is kept; both label styles are read."""
    section = "\n".join(
        f"| **{label}** | **{statement},** more text. | Why |" for label, statement in IMPLEMENTATION_DECISIONS.items()
    )
    assert _decisions_without_their_statement(section) == []
    assert _decisions_without_their_statement(section.replace("| **P2** |", "| P2 |")) == []
    drifted = section.replace("**An unknown `doc_id` is `not_a_candidate`,**", "**An unknown `doc_id` is ignored.**")
    assert _decisions_without_their_statement(drifted) == ["P3"]


@pytest.mark.parametrize(
    ("source", "start", "end"),
    [
        (SPECIFICATIONS_MD, "#### 8.3 Implementation decisions", "#### 8.4"),
        (IMPLEMENTATION_PLAN_MD, "### 2. Decisions added", "### 3."),
    ],
    ids=["SPECIFICATIONS.md §8.3", "IMPLEMENTATION_PLAN.md §2"],
)
def test_implementation_decisions_open_with_the_same_statement_in_both_records(
    source: Path, start: str, end: str
) -> None:
    """Each of P1 to P13 opens its row with the statement pinned in ``IMPLEMENTATION_DECISIONS``, in both records."""
    missing = _decisions_without_their_statement(_between(_read(source), start, end, source))
    assert missing == [], f"{_rel(source)} does not open these decisions with their pinned statement: {missing}"


def test_table_rows_drops_the_header_and_separator_and_strips_cells() -> None:
    """The table parser returns body rows only, as stripped cells, and ignores text around the table."""
    text = "Intro.\n\n| A | B |\n| :--- | :---: |\n| `x` | 1 |\n|  y  | two words |\n\nAfter.\n"
    assert _table_rows(text) == [["`x`", "1"], ["y", "two words"]]


def test_specification_decision_table_has_every_d_c_row() -> None:
    """The D-C decision table, which the Supervisor prompt copies (Iteration 13), is pinned word for word."""
    rows = _table_rows(_spec_section("**Decision table:**", "A failed Writer call is shown"))
    assert rows == [list(row) for row in DECISION_TABLE_ROWS]


def test_specification_event_catalogue_has_every_d_i_event() -> None:
    """The D-I event catalogue lists every event at its level, in order; Iteration 15 asserts against it."""
    rows = _table_rows(_spec_section("**Event catalogue:**", "#### D-J."))
    assert [(cells[0].strip("*"), cells[1]) for cells in rows] == list(LOG_EVENTS)


def test_specification_states_the_four_supervisor_tool_descriptions_word_for_word() -> None:
    """§7.1's descriptions are what the Supervisor model sees, so they are benchmark constants, pinned here."""
    rows = _table_rows(_spec_section("#### 7.1 Supervisor tools", "#### 7.2"))
    assert [(cells[0].strip("`"), cells[1]) for cells in rows] == list(SUPERVISOR_TOOL_DESCRIPTIONS.items())


def test_table_rows_keeps_an_escaped_pipe_inside_its_cell() -> None:
    r"""A ``\|`` is a literal pipe in Markdown, as the plan's ``PipelineScope \| GuardrailViolation`` cell uses it."""
    text = "| A | B |\n| :--- | :--- |\n| `x` → `P \\| G` | `y` |\n"
    assert _table_rows(text) == [["`x` → `P \\| G`", "`y`"]]


def test_guardrails_in_order_keeps_guardrail_names_and_drops_other_code_spans() -> None:
    """Only the 12 names count: ``revise=False``, conditions and dates in the same cell are not guardrails."""
    cell = "`attempt_limit` → if `revise=False`: `initial_draft_exists` (`drafts_saved >= config.max_drafts`) `2026`"
    assert _guardrails_in_order(cell) == ("attempt_limit", "initial_draft_exists")


def test_specification_states_the_guardrail_check_order() -> None:
    """§7.3's check order is the one the guardrails implement (``tests/test_unit/test_guardrails.py`` precedence)."""
    rows = _table_rows(_spec_section("#### 7.3 Guardrail check order", "`invalid_scope` covers these cases"))
    assert {cells[0].strip("`"): _guardrails_in_order(cells[1]) for cells in rows} == GUARDRAIL_CHECK_ORDER


def test_plan_iteration_5_table_states_the_same_check_order_as_the_specification() -> None:
    """Iteration 5 AC3: the plan's check-order column matches §7.3, tool by tool."""
    plan = _read(IMPLEMENTATION_PLAN_MD)
    section = _between(plan, "#### Iteration 5", "Also add the rule 8 walk-through", IMPLEMENTATION_PLAN_MD)
    order: dict[str, tuple[str, ...]] = {}
    for cells in _table_rows(section):
        function = re.match(r"`(check_\w+)\(", cells[0])
        assert function is not None, f"no check function in {cells[0]!r}"
        order[_CHECK_FUNCTION_TOOLS[function.group(1)]] = _guardrails_in_order(cells[1])
    assert order == GUARDRAIL_CHECK_ORDER


def test_partial_binding_claims_flags_restricted_tool_sets_but_not_prompt_boundaries() -> None:
    """A claim that a sub-agent holds only some tools is flagged; the prompt drawing the boundary is not."""
    assert _partial_binding_claims("QA-Legal's Scoped Tools: verify_legal_citation.") == ["scoped tools"]
    assert _partial_binding_claims("The Scout is bound only to the list and search tools.") == ["bound only to"]
    assert _partial_binding_claims("The Writer only has access to two tools.") == ["only has access to"]
    assert _partial_binding_claims("QA-Legal is connected only to verify_legal_citation.") == ["connected only to"]
    assert _partial_binding_claims("The Scout is limited to the list and search tools.") == [
        "is limited to the list and search tools"
    ]
    assert _partial_binding_claims("The Scout is limited to the top 5 candidates.") == []
    assert _partial_binding_claims("Each sub-agent's prompt limits it to the tools its job needs.") == []
    assert _partial_binding_claims("cache_read_input_tokens: int  # subset of input_tokens") == []


def test_design_states_that_every_sub_agent_is_connected_to_all_five_tools() -> None:
    """DESIGN.md §4 states P1's binding: all five substrate tools on every sub-agent, as in Approach 1."""
    section = _between(_read(DESIGN_MD), "### 4.", "### 5.", DESIGN_MD)
    assert "every sub-agent is connected to all five tools" in section


@pytest.mark.parametrize("path", ALL_DOCS, ids=_rel)
def test_document_does_not_say_a_sub_agent_is_given_only_some_tools(path: Path) -> None:
    """No document contradicts P1 by describing a sub-agent's tool set as a subset of the substrate's."""
    assert _partial_binding_claims(_read(path)) == [], f"{_rel(path)} contradicts P1"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("An initial draft plus revisions: up to 4 Writer attempts.", [4]),
        ("Scenario 2: attempts 3. Attempts 2; attempt 1 of 3; 3 of 3 attempts used.", []),
        ("`MAX_ATTEMPTS_PER_DOC == 3`, the 3-attempt budget, and the attempt cap is fixed at 5.", [3, 3, 5]),
        ("max_attempts_per_doc: int = 2  # and 6 attempts per document", [2, 6]),
        ("A cap of 4, capped at 5, up to 2 Writer attempts, a maximum of 6 attempts.", [2, 4, 5, 6]),
        ("Four Writer attempts, a cap of three, the two-attempt budget, up to five attempts.", [2, 3, 4, 5]),
        ("An initial draft plus up to two revisions; attempt one of three.", []),
    ],
)
def test_stated_attempt_caps_reads_each_phrasing_of_the_cap_and_nothing_else(text: str, expected: list[int]) -> None:
    """The cap extractor reads every phrasing a document uses for the cap, and ignores attempt numbers."""
    assert sorted(_stated_attempt_caps(text)) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("The cap is `MAX_ATTEMPTS_PER_DOC = 3`.", True),
        ("Limits: 3 Writer attempts per document.", True),
        ("`MAX_ATTEMPTS_PER_DOC == 3`.", False),
        ("The attempt cap is 3.", False),
        ("Limits: 4 Writer attempts per document.", False),
    ],
)
def test_states_the_cap_canonically_accepts_only_the_two_canonical_forms(text: str, expected: bool) -> None:
    """Only ``MAX_ATTEMPTS_PER_DOC = 3`` and "3 Writer attempts" count as stating the cap canonically."""
    assert _states_the_cap_canonically(text) is expected


@pytest.mark.parametrize("path", ALL_DOCS, ids=_rel)
def test_document_states_no_attempt_cap_but_the_canonical_one(path: Path) -> None:
    """A document that states the cap states 3, and states it at least once in a canonical form."""
    text = _read(path)
    caps = _stated_attempt_caps(text)
    assert all(cap == MAX_ATTEMPTS_PER_DOC for cap in caps), f"{_rel(path)} states the attempt cap as {caps}"
    if caps:
        assert _states_the_cap_canonically(text), (
            f"{_rel(path)} states the cap, but not as `MAX_ATTEMPTS_PER_DOC = {MAX_ATTEMPTS_PER_DOC}` "
            f"or as '{MAX_ATTEMPTS_PER_DOC} Writer attempts'"
        )


def test_specification_states_the_attempt_cap_the_code_enforces() -> None:
    """SPECIFICATIONS.md §6.9 declares the constant with the value ``src.schemas`` gives it."""
    assert f"MAX_ATTEMPTS_PER_DOC = {MAX_ATTEMPTS_PER_DOC}" in _read(SPECIFICATIONS_MD)


@pytest.mark.parametrize("path", DOCS_STATING_THE_CAP, ids=_rel)
def test_document_that_restates_the_cap_still_states_it(path: Path) -> None:
    """The documents that restate the cap keep stating it, so a deleted statement cannot pass unnoticed."""
    assert _states_the_cap_canonically(_read(path)), f"{_rel(path)} no longer states the attempt cap"


def test_forbidden_term_hits_catches_every_spelling_and_spares_the_skills_folders() -> None:
    """The forbidden-terms check matches the reserved feature in any spelling, and no project path or phrase.

    The samples are built from fragments so that this module never spells the term either.
    """
    for spelling in ("Agent" + "Skills", "agent" + "_skills", "Agent " + "Skill", "agent" + "-skills"):
        assert _forbidden_term_hits(f"Use the {spelling} plugin.") == [spelling], spelling
    for innocent in (
        ".agents/skills/code-reviewer/SKILL.md",
        "The two review skills are project files, not registered Claude Code skills.",
        ".claude/skills/implement/SKILL.md",
    ):
        assert _forbidden_term_hits(innocent) == [], innocent


def test_repository_documents_cover_the_docs_and_records_but_skip_tooling_and_ignored_folders() -> None:
    """The scan reads every tracked kind of document, task records included, and no ignored or tool folder."""
    documents = set(_repository_documents())
    assert set(ALL_DOCS) <= documents
    assert any(_rel(path).startswith(".agents/tasks/") for path in documents)
    assert not any(set(path.relative_to(REPO_ROOT).parts) & _UNSCANNED_DIR_NAMES for path in documents)


@pytest.mark.parametrize("path", _repository_documents(), ids=_rel)
def test_document_uses_no_forbidden_term(path: Path) -> None:
    """No document in the repository names a feature the user has ruled out of Approach 2 (FORBIDDEN_TERMS)."""
    assert _forbidden_term_hits(_read(path)) == [], f"{_rel(path)} uses a forbidden term"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Use `RunBudget` for the run limits.", ["Use `RunBudget` for the run limits."]),
        ("`RunBudget` was removed.", []),
        (
            "| Copy | `RevisionPayload` is removed. The run returns `PipelineRun`. |",
            ["The run returns `PipelineRun`."],
        ),
        ("class ExitCode(IntEnum):   # [Amended] renamed from PipelineExitCode; 0–5 unchanged", []),
        ("`RunState` replaces Approach 1's `PipelineRun`.", []),
        ("A `PipelineRunner` is not a removed model; neither is `SupervisorReports`.", []),
        ("Each worker returns a `WriterResult`.", ["Each worker returns a `WriterResult`."]),
    ],
)
def test_current_mentions_of_removed_models_exempts_removal_and_history_sentences(
    text: str, expected: list[str]
) -> None:
    """A removed model named in a sentence about its removal passes; named anywhere else, it is reported."""
    assert _current_mentions_of_removed_models(text) == expected


@pytest.mark.parametrize("path", ALL_DOCS, ids=_rel)
def test_document_names_no_removed_model_as_current(path: Path) -> None:
    """No document presents a removed model as part of Approach 2 (SPECIFICATIONS.md §6)."""
    mentions = _current_mentions_of_removed_models(_read(path))
    assert mentions == [], f"{_rel(path)} names a removed model outside a removal passage: {mentions}"


@pytest.mark.parametrize("path", REVIEW_SKILLS, ids=_rel)
def test_review_skill_lists_agents_md_among_its_sources_of_truth(path: Path) -> None:
    """Both review skills name AGENTS.md in their "Sources of truth" table, so reviews apply its rules."""
    section = _between(_read(path), "## Sources of truth", "\n---", path)
    assert any(cells[0] == "`AGENTS.md`" for cells in _table_rows(section)), f"{_rel(path)} omits AGENTS.md"


@pytest.mark.parametrize("path", SUBAGENTS, ids=_rel)
def test_subagent_lists_agents_md_as_mandatory_reading(path: Path) -> None:
    """Each subagent reads AGENTS.md as part of its mandatory first step."""
    section = _between(_read(path), "## Mandatory first step", "\n## ", path)
    assert "`AGENTS.md`" in section, f"{_rel(path)} does not list AGENTS.md as mandatory reading"


def test_specification_records_the_fatal_stop_the_iteration_12_spike_chose() -> None:
    """D-D.1: D-D names candidate 1 as the stop, and §8.4 records it with its evidence instead of "Pending"."""
    decision = _spec_section("#### D-D.", "#### D-E.")
    spike = _read(SPECIFICATIONS_MD).split("#### 8.4 Spike results", 1)[1]

    assert "The result is recorded here as D-D.1." not in decision
    assert "**D-D.1 (Iteration 12): candidate 1.**" in decision
    assert "FatalStopHook" in decision and "Agent.cancel()" in decision
    assert "*Pending.*" not in spike
    for evidence in ("tests/test_unit/test_sdk_contract.py", "tests/test_unit/test_hooks.py", "SequentialToolExecutor"):
        assert evidence in spike, evidence


@pytest.mark.parametrize("max_drafts", [None, 2], ids=["no-ceiling", "ceiling-2"])
def test_supervisor_prompt_copies_the_d_c_decision_table_row_for_row(max_drafts: int | None) -> None:
    """Iteration 13, AC1: the prompt holds one Markdown table, D-C's decision table, every line byte for byte."""
    spec_section = _spec_section("**Decision table:**", "A failed Writer call is shown")
    spec_rows = _table_rows(spec_section)
    assert spec_rows == [list(row) for row in DECISION_TABLE_ROWS]
    prompt = build_supervisor_prompt(max_drafts)
    assert _table_rows(prompt) == spec_rows
    spec_lines = [line for line in spec_section.splitlines() if line.startswith("|")]
    assert [line for line in prompt.splitlines() if line.startswith("|")] == spec_lines


#: The heading both D-C and the prompt put above the run-level priorities.
_PRIORITIES_HEADING: str = "**Run-level priorities,** applied on top of the table:"


def _d_c_priorities() -> list[str]:
    """D-C's run-level priorities, as its numbered list words them."""
    section = _spec_section(_PRIORITIES_HEADING, "##### Run-level guardrails")
    return re.findall(r"^\d+\. (.+)$", section, re.MULTILINE)


def _priorities_disagree(prompt: str, priorities: list[str]) -> bool:
    """Whether ``prompt`` states other run-level priorities than ``priorities``: one missing, reworded or added.

    The prompt's priorities are the numbered list right under the heading, up to the first blank line.
    """
    if _PRIORITIES_HEADING + "\n" not in prompt:
        return True
    block = prompt.split(_PRIORITIES_HEADING + "\n", 1)[1].split("\n\n", 1)[0]
    return re.findall(r"^\d+\. (.+)$", block, re.MULTILINE) != priorities


@pytest.mark.parametrize("max_drafts", [None, 2], ids=["no-ceiling", "ceiling-2"])
def test_supervisor_prompt_states_the_d_c_run_level_priorities_verbatim(max_drafts: int | None) -> None:
    """Iteration 13, AC3: the prompt's priorities are D-C's two, as D-C words them, and no others."""
    priorities = _d_c_priorities()
    assert len(priorities) == 2
    assert not _priorities_disagree(build_supervisor_prompt(max_drafts), priorities)


def test_priorities_check_catches_an_invented_extra_priority() -> None:
    """A third priority under the heading breaks "D-C and the prompt agree on the priorities" (QA-m2, M7)."""
    priorities = _d_c_priorities()
    prompt = build_supervisor_prompt(None)
    last = f"{len(priorities)}. {priorities[-1]}\n"
    assert last in prompt
    extra = "3. **Start every candidate first.** Draft every candidate before auditing any.\n"
    invented = prompt.replace(last, last + extra)
    assert _priorities_disagree(invented, priorities)


@pytest.mark.parametrize("max_drafts", [None, 2], ids=["no-ceiling", "ceiling-2"])
def test_supervisor_prompt_states_the_attempt_cap_d_c_states(max_drafts: int | None) -> None:
    """Iteration 13, AC3: the prompt states the cap, canonically, as the one D-C rule 4 and ``src.schemas`` hold."""
    rule_4 = _spec_section("4. **The limit is", "5. **")
    assert _stated_attempt_caps("The limit is" + rule_4) == [MAX_ATTEMPTS_PER_DOC]
    prompt = build_supervisor_prompt(max_drafts)
    caps = _stated_attempt_caps(prompt)
    assert caps and all(cap == MAX_ATTEMPTS_PER_DOC for cap in caps), caps
    assert _states_the_cap_canonically(prompt)
