"""Keep the MCP Registry metadata (server.json) in step with the package."""

import json
from pathlib import Path

import pytest

import naja_scope

tomllib = pytest.importorskip("tomllib")  # stdlib from Python 3.11

ROOT = Path(__file__).resolve().parent.parent


def test_server_json_version_matches_package():
    server = json.loads((ROOT / "server.json").read_text())
    assert server["version"] == naja_scope.__version__
    assert [p["version"] for p in server["packages"]] == [naja_scope.__version__]


def test_readmes_carry_registry_ownership_marker():
    # The registry verifies PyPI ownership by finding this marker in the
    # package description, which is README_PyPI.md.
    name = json.loads((ROOT / "server.json").read_text())["name"]
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    for readme in {"README.md", pyproject["project"]["readme"]}:
        assert f"<!-- mcp-name: {name} -->" in (ROOT / readme).read_text()


def test_package_name_is_a_console_script():
    # Registry clients launch a PyPI server as `uvx <identifier>`.
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    scripts = pyproject["project"]["scripts"]
    assert scripts["naja-scope"] == scripts["naja-scope-mcp"]
