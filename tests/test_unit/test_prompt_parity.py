"""Parity of the sub-agents' benchmark constants with Approach 1 (IMPLEMENTATION_PLAN.md Iteration 6; P7).

Orchestration is the only intentional variable between the two approaches (SPECIFICATIONS.md §1), so the models,
efforts, declared tool intent and prompts of the Scout, Writer and QA-Legal must be Approach 1's. The baseline is
Approach 1's ``src/agents.py`` as it is on disk (P7). It is read as text and parsed with :mod:`ast`, never
imported: importing it would execute Approach 1's code and bind this suite to its dependencies.

The whole module is skipped, with a reason, when ``../code-orchestration/`` is not next to this repository.
"""

import ast
from pathlib import Path
from typing import Any, Final

import pytest

from src import agents as agents_module

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]

#: Approach 1's sub-agent module, the parity baseline (P7).
APPROACH_1_AGENTS: Final[Path] = REPO_ROOT.parent / "code-orchestration" / "src" / "agents.py"

pytestmark = pytest.mark.skipif(
    not APPROACH_1_AGENTS.is_file(),
    reason=f"Approach 1 is not on disk at {APPROACH_1_AGENTS}; the parity baseline is unavailable",
)


def _module_constants(path: Path) -> dict[str, Any]:
    """Map every module-level ``NAME = <literal>`` in ``path`` to its value, without executing the module.

    Reading with :meth:`Path.read_text` applies universal newlines, so a CRLF checkout of either project cannot
    make two identical prompts compare unequal.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    constants: dict[str, Any] = {}
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            targets, value = [node.target], node.value
        elif isinstance(node, ast.Assign):
            targets, value = [target for target in node.targets if isinstance(target, ast.Name)], node.value
        else:
            continue
        try:
            literal = ast.literal_eval(value)
        except ValueError:
            continue
        for target in targets:
            constants[target.id] = literal
    return constants


@pytest.fixture(scope="module")
def approach_1() -> dict[str, Any]:
    """Approach 1's module-level literals, parsed once for the module."""
    return _module_constants(APPROACH_1_AGENTS)


@pytest.mark.parametrize(
    "name",
    [
        "SCOUT_MODEL_ID",
        "WRITER_MODEL_ID",
        "QA_LEGAL_MODEL_ID",
        "SCOUT_REASONING_EFFORT",
        "WRITER_REASONING_EFFORT",
        "QA_LEGAL_REASONING_EFFORT",
        "SCOUT_TOOL_NAMES",
        "WRITER_TOOL_NAMES",
        "QA_LEGAL_TOOL_NAMES",
    ],
)
def test_model_bindings_efforts_and_tool_intent_match_approach_1(approach_1: dict[str, Any], name: str) -> None:
    """Each model ID, effort and declared tool tuple equals Approach 1's value of the same name."""
    assert name in approach_1, f"{name} is missing from Approach 1's agents.py"
    assert getattr(agents_module, name) == approach_1[name]


@pytest.mark.parametrize("name", ["SCOUT_SYSTEM_PROMPT", "QA_LEGAL_SYSTEM_PROMPT"])
def test_scout_and_qa_legal_prompts_are_byte_identical_to_approach_1(approach_1: dict[str, Any], name: str) -> None:
    """The Scout and QA-Legal system prompts are benchmark constants: not one character may differ."""
    ours = getattr(agents_module, name)

    assert isinstance(approach_1[name], str)
    assert ours == approach_1[name]
    assert ours.encode("utf-8") == approach_1[name].encode("utf-8")


#: The Writer's one permitted divergence (SPECIFICATIONS.md §1, D-A): its prompt names its input container in
#: exactly three places, and each is reworded from Approach 1's candidate plus "revision payload" to the one
#: ``AttemptRecord`` that carries the same ``ScoutCandidate`` and, on a revision, the draft and its QA report.
#: Applied in order to Approach 1's prompt, the list must give this project's prompt exactly. Nothing else moves:
#: the phrases about "the input candidate" stay, because the candidate is still the Writer's input, inside the
#: record.
WRITER_PROMPT_SUBSTITUTIONS: Final[tuple[tuple[str, str], ...]] = (
    (
        "Given one triaged `ScoutCandidate`, fetch",
        "Given an `AttemptRecord` carrying one triaged `ScoutCandidate`, fetch",
    ),
    (
        "If a revision payload is also supplied, revise",
        "If the record also carries a `draft` and its `qa_report`, revise",
    ),
    (
        "The revision payload contains your previous draft",
        "The `AttemptRecord` contains your previous draft",
    ),
)


def test_writer_prompt_is_approach_1s_with_only_the_declared_substitutions(approach_1: dict[str, Any]) -> None:
    """Approach 1's Writer prompt, with the substitution list applied, is exactly this project's Writer prompt.

    Each phrase replaced must occur exactly once in Approach 1's prompt, so a substitution cannot silently rewrite
    a second passage, and cannot pass by matching nothing.
    """
    expected = approach_1["WRITER_SYSTEM_PROMPT"]
    for old, new in WRITER_PROMPT_SUBSTITUTIONS:
        assert expected.count(old) == 1, f"{old!r} must occur exactly once in Approach 1's Writer prompt"
        expected = expected.replace(old, new)

    assert agents_module.WRITER_SYSTEM_PROMPT == expected


def test_writer_substitutions_only_rename_the_writers_input() -> None:
    """Every substitution is an input-naming phrase: it replaces the old containers with the ``AttemptRecord``.

    This keeps the list honest. An entry that touched the Writer's instructions rather than the name of its input
    would be a benchmark-constant change, which is a stop condition, not a substitution.
    """
    for old, new in WRITER_PROMPT_SUBSTITUTIONS:
        assert "revision payload" in old or "`ScoutCandidate`" in old, old
        assert "AttemptRecord" in new or "record" in new, new

    assert "revision payload" not in agents_module.WRITER_SYSTEM_PROMPT.lower()


def _functions(path: Path) -> dict[str, str]:
    """Map every module-level function in ``path`` to its AST dump, with its docstring removed.

    Docstrings are free to be reworded (IMPLEMENTATION_PLAN.md §1.5); the code, its signature and its annotations
    are what must not move.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    dumps: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        body = node.body
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            if isinstance(body[0].value.value, str):
                body = body[1:]
        node.body = body
        dumps[node.name] = ast.dump(node)
    return dumps


@pytest.mark.parametrize("name", ["extract_telemetry", "_resolve_tools", "_run_worker"])
def test_reused_functions_are_approach_1s_code(name: str) -> None:
    """``extract_telemetry``, ``_resolve_tools`` and ``_run_worker`` are Approach 1's code, unchanged (Iteration 6)."""
    ours = _functions(REPO_ROOT / "src" / "agents.py")
    theirs = _functions(APPROACH_1_AGENTS)

    assert name in theirs, f"{name} is missing from Approach 1's agents.py"
    assert name in ours, f"{name} is missing from src/agents.py"
    assert ours[name] == theirs[name]
