"""Module layout contract for Approach 2 (IMPLEMENTATION_PLAN.md §4).

Each iteration that adds a ``src`` module appends it to ``EXPECTED_MODULES`` in its Red step.
"""

import ast
import importlib
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
EXPECTED_MODULES = [
    "src",
    "src.credentials",
    "src.schemas",
    "src.costs",
    "src.diagnostics",
    "src.model_factory",
    "src.template_engine",
    "src.mcp_client",
    "src.telemetry",
    "src.logging_setup",
    "src.guardrails",
    "src.agents",
    "src.tools",
    "src.rendering",
    "src.hooks",
    "src.supervisor",
    "src.app",
    "src.cli",
    "src.benchmark",
]


def test_src_package_exposes_version() -> None:
    """The src package imports and declares version 0.1.0."""
    src = importlib.import_module("src")
    assert src.__version__ == "0.1.0"


def test_expected_modules_are_importable() -> None:
    """Every module the plan has delivered so far imports cleanly."""
    for module_name in EXPECTED_MODULES:
        importlib.import_module(module_name)


@pytest.mark.parametrize("directory_name", ["drafts", "logs"])
def test_artifact_directory_exists_and_is_writable(directory_name: str) -> None:
    """The drafts and logs directories exist at the repository root and accept new files."""
    directory = REPO_ROOT / directory_name
    assert directory.is_dir(), f"{directory_name}/ not found at {directory}"
    with tempfile.NamedTemporaryFile(dir=directory) as handle:
        assert Path(handle.name).is_file()


def _imported_modules(module_path: Path) -> set[str]:
    """Every module ``module_path`` imports, relative imports resolved against the ``src`` package."""
    imported: set[str] = set()
    for node in ast.walk(ast.parse(module_path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = ".".join(part for part in ("src" if node.level else None, node.module) if part)
            imported.add(base)
            imported.update(f"{base}.{alias.name}" for alias in node.names)
    return imported


def test_hooks_does_not_import_tools() -> None:
    """The dependency runs one way, ``src.tools`` -> ``src.hooks``; the Supervisor builder relies on it."""
    imported = _imported_modules(REPO_ROOT / "src" / "hooks.py")
    assert not any(name == "src.tools" or name.startswith("src.tools.") for name in imported), sorted(imported)


def test_supervisor_imports_no_substrate_client_and_no_concrete_model() -> None:
    """The Supervisor has no substrate access (Q10 = B), and its model is injected: it builds no provider model."""
    imported = _imported_modules(REPO_ROOT / "src" / "supervisor.py")
    forbidden = ("src.mcp_client", "src.model_factory", "strands.models.openai", "strands.tools.mcp")
    assert [name for name in imported if name.startswith(forbidden)] == [], sorted(imported)
