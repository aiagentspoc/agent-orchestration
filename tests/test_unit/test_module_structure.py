"""Module layout contract for Approach 2 (IMPLEMENTATION_PLAN.md §4).

Each iteration that adds a ``src`` module appends it to ``EXPECTED_MODULES`` in its Red step.
"""

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
