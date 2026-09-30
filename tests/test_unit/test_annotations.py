"""Every ``src`` function is fully annotated (AGENTS.md Rule 7; code-reviewer Gate 8; P9).

Checked from the source text with ``ast``, so the guarantee does not depend on an external linter run. P9 lets
``src/mcp_client.py`` gain its missing annotations in Iteration 7, as the one permitted divergence from Approach 1's
module; from then on every module in ``src`` is held to the same standard.
"""

import ast
from pathlib import Path

import pytest

SRC_DIR = Path(__file__).resolve().parents[2] / "src"

#: The first parameter of a method is annotated by the class it belongs to.
_IMPLICIT_FIRST_ARGS = frozenset({"self", "cls"})


def _missing_annotations(path: Path) -> list[str]:
    """Return ``"<line>: <function>(<what>)"`` for every missing parameter or return annotation in ``path``."""
    missing: list[str] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        arguments = node.args
        positional = [*arguments.posonlyargs, *arguments.args]
        if positional and positional[0].arg in _IMPLICIT_FIRST_ARGS:
            positional = positional[1:]
        parameters = [*positional, *arguments.kwonlyargs]
        parameters += [extra for extra in (arguments.vararg, arguments.kwarg) if extra is not None]
        missing += [f"{node.lineno}: {node.name}({p.arg})" for p in parameters if p.annotation is None]
        if node.returns is None:
            missing.append(f"{node.lineno}: {node.name}(return)")
    return missing


@pytest.mark.parametrize("path", sorted(SRC_DIR.glob("*.py")), ids=lambda path: path.name)
def test_every_src_function_is_fully_annotated(path: Path) -> None:
    """No parameter or return type is left unannotated in any ``src`` module."""
    assert _missing_annotations(path) == []
