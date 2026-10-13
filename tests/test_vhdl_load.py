# SPDX-License-Identifier: Apache-2.0
"""Exercise the raw VHDL beta frontend through the public API and MCP tool."""
import asyncio

import pytest

from naja_scope import api
from naja_scope.errors import ScopeError
from naja_scope.session import SESSION


@pytest.fixture(autouse=True)
def fresh_session():
    SESSION.reset()
    yield
    SESSION.reset()


@pytest.fixture
def vhdl_file(tmp_path):
    source = tmp_path / "wire.vhd"
    source.write_text("""
library ieee;
use ieee.std_logic_1164.all;
entity wire_top is
  port (a : in std_logic; y : out std_logic);
end entity;
architecture rtl of wire_top is
begin
  y <= a;
end architecture;
""")
    return str(source)


def test_load_and_query(vhdl_file):
    with pytest.warns(RuntimeWarning, match="Beta"):
        result = api.load_vhdl(vhdl_file, top="wire_top")
    assert result["beta"] is True
    assert result["top"]["model"] == "wire_top"
    assert result["top"]["terms"] == 2
    assert api.status()["intent_loadable"] is False
    assert api.get_hierarchy()["root"]["model"] == "wire_top"
    ports = api.get_module_card("wire_top")["ports"]
    assert {p["name"] for p in ports} == {"a", "y"}
    with pytest.raises(ScopeError, match="SystemVerilog-only"):
        api.load_intent()
    assert api.status()["top"]["model"] == "wire_top"


def test_package_then_top(tmp_path, vhdl_file):
    package = tmp_path / "types.vhd"
    package.write_text("package types is\n constant WIDTH : integer := 1;\nend package;\n")
    with pytest.warns(RuntimeWarning, match="Beta"):
        result = api.load_vhdl(str(package))
    assert result["top"] is None
    assert api.status()["loaded"] is False
    with pytest.warns(RuntimeWarning, match="Beta"):
        api.load_vhdl(vhdl_file)
    assert api.status()["loaded_files"] == [str(package), vhdl_file]


def test_batch_files_any_order(tmp_path):
    child = tmp_path / "child.vhd"
    child.write_text("""
library ieee;
use ieee.std_logic_1164.all;
entity child is
  port (a : in std_logic; y : out std_logic);
end entity;
architecture rtl of child is
begin
  y <= a;
end architecture;
""")
    top = tmp_path / "top.vhd"
    top.write_text("""
library ieee;
use ieee.std_logic_1164.all;
entity top is
  port (a : in std_logic; y : out std_logic);
end entity;
architecture rtl of top is
begin
  u : entity work.child port map (a => a, y => y);
end architecture;
""")
    # The top's user precedes the child's definition: units are resolved.
    with pytest.warns(RuntimeWarning, match="Beta"):
        result = api.load_vhdl([str(top), str(child)])
    assert result["top"]["model"] == "top"
    assert api.resolve("top.u")["matches"][0]["model"] == "child"
    assert api.status()["loaded_files"] == [str(top), str(child)]


def test_snapshot_preserves_vhdl_intent_guard(tmp_path, vhdl_file, monkeypatch):
    with pytest.warns(RuntimeWarning, match="Beta"):
        api.load_vhdl(vhdl_file)
    snapshot = str(tmp_path / "snapshot")
    api.save_snapshot(snapshot)
    SESSION.reset()
    monkeypatch.setenv("NAJA_SCOPE_INTENT", "1")
    result = api.load_snapshot(snapshot)
    assert result["intent_loaded"] is False
    assert "SystemVerilog-only" in result["intent_note"]
    assert api.status()["intent_loadable"] is False
    assert api.status()["top"]["model"] == "wire_top"


def test_errors_and_tool_schema(tmp_path):
    from naja_scope import server
    result = server.load_vhdl(str(tmp_path / "missing.vhd"))
    assert "VHDL source file not found" in result["error"]
    bad = tmp_path / "bad.vhd"
    bad.write_text("this is not vhdl;")
    with pytest.warns(RuntimeWarning, match="Beta"):
        result = server.load_vhdl(str(bad))
    assert "VHDL beta loading failed" in result["error"]
    tools = asyncio.run(server.mcp.list_tools())
    tool = next(t for t in tools if t.name == "load_vhdl")
    assert "beta" in tool.description
    assert tool.inputSchema["required"] == ["file"]
