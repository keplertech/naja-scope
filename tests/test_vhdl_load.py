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
    assert result["intent_loaded"] is False
    assert api.status()["intent_loadable"] is True
    assert api.get_hierarchy()["root"]["model"] == "wire_top"
    ports = api.get_module_card("wire_top")["ports"]
    assert {p["name"] for p in ports} == {"a", "y"}
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
    # Coordinates refer to each original input file, not a concatenated batch.
    sources = {path: api.get_source(path, context_lines=0) for path in
               ("top", "top.a", "top.u", "top.u.a")}
    assert "entity top is" in sources["top"]["text"]
    assert sources["top.a"]["file"] == str(top)
    assert "a : in std_logic" in sources["top.a"]["text"]
    assert "u : entity work.child" in sources["top.u"]["text"]
    assert sources["top.u.a"]["file"] == str(child)
    assert "a : in std_logic" in sources["top.u.a"]["text"]
    snapshot = str(tmp_path / "snapshot")
    api.save_snapshot(snapshot)
    SESSION.reset()
    api.load_snapshot(snapshot)
    assert {p: api.get_source(p, context_lines=0) for p in sources} == sources


def test_snapshot_reload_brings_vhdl_intent_back(tmp_path, vhdl_file, monkeypatch):
    with pytest.warns(RuntimeWarning, match="Beta"):
        api.load_vhdl(vhdl_file)
    snapshot = str(tmp_path / "snapshot")
    api.save_snapshot(snapshot)
    SESSION.reset()
    monkeypatch.setenv("NAJA_SCOPE_INTENT", "1")
    with pytest.warns(RuntimeWarning, match="Beta"):
        result = api.load_snapshot(snapshot)
    assert result["intent_loaded"] is True
    assert api.status()["intent_loadable"] is True
    assert api.get_intent("wire_top.a", want="type")["type"] == "std_logic"


def test_signal_and_inferred_register_source_roundtrip(tmp_path):
    source = tmp_path / "seq.vhd"
    source.write_text("""library ieee;
use ieee.std_logic_1164.all;
entity seq_top is
  port(clk, d : in std_logic; q : out std_logic);
end entity;
architecture rtl of seq_top is
  signal state : std_logic;
begin
  process(clk) begin
    if rising_edge(clk) then state <= d; end if;
  end process;
  q <= state;
end architecture;
""")
    with pytest.warns(RuntimeWarning, match="Beta"):
        api.load_vhdl(str(source))
    declaration = api.get_source("seq_top.state", context_lines=0)
    assert declaration["start"] == declaration["end"] == 7
    assert declaration["text"].strip() == "signal state : std_logic;"
    driver = api.get_drivers("seq_top.q")["leaf_drivers"][0]
    process = api.get_source(driver["path"], context_lines=0)
    assert process["start"] == 9 and process["end"] == 11
    assert "rising_edge(clk)" in process["text"]
    snapshot = str(tmp_path / "snapshot")
    api.save_snapshot(snapshot)
    SESSION.reset()
    api.load_snapshot(snapshot)
    assert api.get_source("seq_top.state", context_lines=0) == declaration
    assert api.get_source(driver["path"], context_lines=0) == process


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
