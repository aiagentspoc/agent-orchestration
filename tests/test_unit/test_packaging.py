"""Packaging contract for Approach 2 (IMPLEMENTATION_PLAN.md Iteration 0, §4).

The dependency sets are asserted exactly: adding a dependency that §4 does not list is a stop
condition (§1.4 item 4), so a new name must fail this test rather than slip through.
"""

import importlib
import importlib.metadata
import re
import tomllib
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"
LOCK_PATH = REPO_ROOT / "uv.lock"
APPROACH_1_LOCK_PATH = REPO_ROOT.parent / "code-orchestration" / "uv.lock"
LOCKED_STRANDS_VERSION = "1.55.1"

EXPECTED_RUNTIME_DEPENDENCIES = {
    "strands-agents",
    "pydantic",
    "pydantic-settings",
    "python-dotenv",
    "openai",
    "fastmcp",
    "hse-easy-mock-mcp",
}
EXPECTED_DEV_DEPENDENCIES = {"pytest", "pytest-asyncio"}

_REQUIREMENT_NAME_END = re.compile(r"[\s<>=!~;\[]")


def _load_pyproject() -> dict[str, Any]:
    """Parse pyproject.toml, failing with a clear message when it is missing."""
    assert PYPROJECT_PATH.is_file(), f"pyproject.toml not found at {PYPROJECT_PATH}"
    with PYPROJECT_PATH.open("rb") as handle:
        return tomllib.load(handle)


def _requirement_names(requirements: list[str]) -> set[str]:
    """Return the distribution names of PEP 508 requirement strings, without specifiers or extras."""
    return {_REQUIREMENT_NAME_END.split(requirement, maxsplit=1)[0] for requirement in requirements}


def _locked_version(lock_path: Path, package_name: str) -> str | None:
    """Return the version of ``package_name`` pinned in a uv lock file, or None when it is not pinned."""
    assert lock_path.is_file(), f"uv.lock not found at {lock_path}"
    with lock_path.open("rb") as handle:
        packages: list[dict[str, Any]] = tomllib.load(handle).get("package", [])
    for package in packages:
        if package["name"] == package_name:
            return package["version"]
    return None


def _installed_version(distribution_name: str) -> str | None:
    """Return the installed version of a distribution, or None when it is not installed."""
    try:
        return importlib.metadata.version(distribution_name)
    except importlib.metadata.PackageNotFoundError:
        return None


def test_pyproject_toml_exists() -> None:
    """pyproject.toml exists at the repository root."""
    assert PYPROJECT_PATH.is_file(), f"pyproject.toml not found at {PYPROJECT_PATH}"


def test_project_name_and_version() -> None:
    """The project is named agent-orchestration and versioned 0.1.0."""
    project = _load_pyproject()["project"]
    assert project["name"] == "agent-orchestration"
    assert project["version"] == "0.1.0"


def test_runtime_dependencies_are_exactly_those_of_section_4() -> None:
    """The runtime dependencies are exactly Approach 1's seven, no more and no fewer."""
    dependencies = _load_pyproject()["project"]["dependencies"]
    assert _requirement_names(dependencies) == EXPECTED_RUNTIME_DEPENDENCIES


def test_dev_dependencies_are_exactly_pytest_and_pytest_asyncio() -> None:
    """The dev extra holds exactly pytest and pytest-asyncio."""
    dev_dependencies = _load_pyproject()["project"]["optional-dependencies"]["dev"]
    assert _requirement_names(dev_dependencies) == EXPECTED_DEV_DEPENDENCIES


def test_uv_source_points_hse_easy_mock_mcp_at_the_sibling_mcp_server() -> None:
    """hse-easy-mock-mcp is installed editable from ../mcp-server."""
    sources = _load_pyproject()["tool"]["uv"]["sources"]
    assert sources["hse-easy-mock-mcp"] == {"path": "../mcp-server", "editable": True}


def test_default_pytest_run_deselects_live_tests() -> None:
    """The live marker is declared and the default run deselects it (P4)."""
    pytest_options = _load_pyproject()["tool"]["pytest"]["ini_options"]
    assert any(marker.startswith("live:") for marker in pytest_options["markers"])
    assert "-m 'not live'" in pytest_options["addopts"]


def test_lock_pins_the_strands_agents_version_approach_1_uses() -> None:
    """This project's uv.lock pins strands-agents 1.55.1, the benchmark SDK version."""
    assert _locked_version(LOCK_PATH, "strands-agents") == LOCKED_STRANDS_VERSION


def test_installed_strands_agents_matches_approach_1_lock() -> None:
    """The installed strands-agents is 1.55.1, the version locked in ../code-orchestration/uv.lock.

    The installed version is asserted unconditionally; only the cross-check against Approach 1's
    lock is skipped when that sibling checkout is absent.
    """
    assert _installed_version("strands-agents") == LOCKED_STRANDS_VERSION
    if not APPROACH_1_LOCK_PATH.is_file():
        pytest.skip(f"Approach 1 lock not found at {APPROACH_1_LOCK_PATH}")
    assert _locked_version(APPROACH_1_LOCK_PATH, "strands-agents") == LOCKED_STRANDS_VERSION


@pytest.mark.parametrize(
    ("module_name", "attribute"),
    [("strands", "Agent"), ("pydantic", "BaseModel"), ("fastmcp", "FastMCP"), ("server", "mcp")],
)
def test_core_dependencies_are_importable(module_name: str, attribute: str) -> None:
    """The SDK, pydantic, fastmcp and the hse-easy-mock server module import in this environment."""
    module = importlib.import_module(module_name)
    assert hasattr(module, attribute)
