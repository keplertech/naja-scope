# SPDX-License-Identifier: Apache-2.0
"""VHDL intent through the public API: naja's VHDL records, normalized to the
get_intent shape, and the same load/reload lifecycle as SystemVerilog."""
import asyncio
import os

import pytest

from naja_scope import api
from naja_scope.errors import ScopeError
from naja_scope.session import SESSION

PACKAGE = """
package fsm_pkg is
  type state_t is (IDLE, RUN, DONE);
  constant WIDTH : integer := 2 + 2;
end package;
"""

DESIGN = """
library ieee;
use ieee.std_logic_1164.all;
use work.fsm_pkg.all;
entity child is
  generic (N : integer := 3);
  port (clk : in std_logic;
        d : in std_logic_vector(N-1 downto 0);
        q : out std_logic_vector(N-1 downto 0));
end entity;
architecture rtl of child is
begin
  process(clk) begin
    if rising_edge(clk) then q <= d; end if;
  end process;
end architecture;

library ieee;
use ieee.std_logic_1164.all;
use work.fsm_pkg.all;
entity fsm_top is
  port (clk, rst, go : in std_logic;
        o : out std_logic_vector(WIDTH-1 downto 0));
end entity;
architecture rtl of fsm_top is
  signal state : state_t;
  type rec_t is record
    a : std_logic;
    b : std_logic_vector(1 downto 0);
  end record;
  signal r : rec_t;
  signal dv : std_logic_vector(WIDTH-1 downto 0);
begin
  u0 : entity work.child generic map (N => WIDTH)
    port map (clk => clk, d => dv, q => o);
  process(clk) begin
    if rising_edge(clk) then
      if rst = '1' then state <= IDLE;
      elsif state = IDLE and go = '1' then state <= RUN;
      elsif state = RUN then state <= DONE;
      else state <= IDLE; end if;
    end if;
  end process;
  r.a <= go;
  r.b <= "00";
  dv <= (others => '0');
end architecture;
"""


@pytest.fixture(autouse=True)
def fresh_session(monkeypatch):
    monkeypatch.delenv("NAJA_SCOPE_INTENT", raising=False)
    SESSION.reset()
    yield
    SESSION.reset()


@pytest.fixture
def sources(tmp_path):
    package = tmp_path / "pkg.vhd"
    package.write_text(PACKAGE)
    design = tmp_path / "design.vhd"
    design.write_text(DESIGN)
    return str(package), str(design)


@pytest.fixture
def loaded(sources):
    # The design precedes its package: units are resolved within the batch.
    with pytest.warns(RuntimeWarning, match="Beta"):
        result = api.load_vhdl([sources[1], sources[0]], top="fsm_top", intent=True)
    assert result["intent_loaded"] is True
    return sources


def test_enum_states_declared_in_package(loaded):
    rec = api.get_intent("fsm_top.state", want="fsm_states")
    assert rec["type"] == "fsm_pkg::state_t"
    assert rec["canonical_kind"] == "enum"
    assert rec["enum"]["width"] == 2
    assert rec["enum"]["members"] == [
        {"name": "IDLE", "ordinal": 0, "encoding": "00"},
        {"name": "RUN", "ordinal": 1, "encoding": "01"},
        {"name": "DONE", "ordinal": 2, "encoding": "10"},
    ]
    # The declaration lives in the package, away from the register's own line.
    assert rec["enum"]["decl"] == f"{loaded[0]}:3"
    assert rec["src"].startswith(f"{loaded[1]}:")


def test_record_fields_report_widths(loaded):
    rec = api.get_intent("fsm_top.r")
    assert rec["type"] == "rec_t"
    assert rec["canonical_kind"] == "record"
    assert rec["struct"]["width"] == 3
    assert rec["struct"]["fields"] == [
        {"name": "a", "type": "std_logic", "width": 1},
        {"name": "b", "type": "std_logic_vector", "width": 2},
    ]


def test_array_keeps_symbolic_constraint(loaded):
    rec = api.get_intent("fsm_top.dv", want="type")
    assert rec["type"] == "std_logic_vector"
    assert rec["canonical_kind"] == "array"
    assert rec["ranges"] == ["3 downto 0"]
    assert rec["constraint"] == "WIDTH-1 downto 0"


def test_non_enum_fsm_query_notes(loaded):
    rec = api.get_intent("fsm_top.clk", want="fsm_states")
    assert rec["type"] == "std_logic"
    assert rec["canonical_kind"] == "scalar"
    assert "enum" not in rec
    assert "not enum-typed" in rec["note"]


def test_generic_override_omits_package_constants(loaded):
    rec = api.get_intent("fsm_top.u0")
    assert rec["intent"] == "parameters"
    params = {p["name"]: p for p in rec["parameters"]}
    assert params["N"]["value"] == "4"
    assert params["N"]["expr"] == "3"
    assert params["N"]["overridden"] is True
    assert params["N"]["localparam"] is False
    assert "WIDTH" not in params
    assert rec["package_constants_omitted"] == 1


def test_package_members_any_case(loaded):
    constant = api.get_intent("fsm_pkg::width")
    assert constant["intent"] == "parameter"
    assert constant["value"] == "4"
    assert constant["expr"] == "2 + 2"
    typedef = api.get_intent("FSM_PKG::state_t")
    assert [m["name"] for m in typedef["enum"]["members"]] == ["IDLE", "RUN", "DONE"]
    assert "error" in api.get_intent("fsm_pkg::missing")


def test_inferred_flop_answers_with_a_note(loaded):
    top = SESSION.require_top()
    ff = next(i for i in top.design.getInstances()
              if i.getModel().getName().startswith("naja_dff"))
    assert "no source type" in api.get_intent(f"fsm_top.#{ff.getID()}", want="type")["note"]


def test_load_intent_reelaborates_file_by_file_session(sources):
    with pytest.warns(RuntimeWarning, match="Beta"):
        api.load_vhdl(sources[0])
        api.load_vhdl(sources[1], top="fsm_top")
    assert api.status()["intent_loaded"] is False
    assert "intent_loaded" in api.get_intent("fsm_top.state")
    with pytest.warns(RuntimeWarning, match="Beta"):
        assert api.load_intent() == {"intent_loaded": True}
    assert api.status()["top"]["model"] == "fsm_top"
    assert api.get_intent("fsm_top.state")["type"] == "fsm_pkg::state_t"
    # Already live: nothing is re-elaborated, so the design handle survives.
    top = SESSION.require_top().design
    api.load_intent()
    assert SESSION.require_top().design == top


def test_last_load_decides_whether_intent_stays_live(sources):
    with pytest.warns(RuntimeWarning, match="Beta"):
        api.load_vhdl(sources[0], intent=True)
        result = api.load_vhdl(sources[1], top="fsm_top")
    assert result["intent_loaded"] is False
    assert api.status()["intent_loaded"] is False


def test_env_opt_in(sources, monkeypatch):
    monkeypatch.setenv("NAJA_SCOPE_INTENT", "1")
    with pytest.warns(RuntimeWarning, match="Beta"):
        assert api.load_vhdl(list(sources), top="fsm_top")["intent_loaded"] is True


def test_snapshot_reload_with_intent(loaded, tmp_path):
    snapshot = str(tmp_path / "snapshot")
    api.save_snapshot(snapshot)
    SESSION.reset()
    assert api.load_snapshot(snapshot) and api.status()["intent_loaded"] is False
    assert api.status()["intent_loadable"] is True
    SESSION.reset()
    with pytest.warns(RuntimeWarning, match="Beta"):
        assert api.load_snapshot(snapshot, intent=True)["intent_loaded"] is True
    assert api.get_intent("fsm_top.state")["enum"]["width"] == 2


def test_flist_rejected(sources):
    with pytest.warns(RuntimeWarning, match="Beta"):
        api.load_vhdl(list(sources), top="fsm_top")
    with pytest.raises(ScopeError, match="not flist"):
        api.load_intent(flist="design.f")
    assert api.status()["top"]["model"] == "fsm_top"


def test_tool_schema_exposes_intent():
    from naja_scope import server
    tools = asyncio.run(server.mcp.list_tools())
    tool = next(t for t in tools if t.name == "load_vhdl")
    assert "intent" in tool.inputSchema["properties"]


def test_moved_sources_keep_the_snapshot_design(sources, tmp_path, monkeypatch):
    with pytest.warns(RuntimeWarning, match="Beta"):
        api.load_vhdl(list(sources), top="fsm_top")
    snapshot = str(tmp_path / "snapshot")
    api.save_snapshot(snapshot)
    SESSION.reset()
    os.remove(sources[1])
    monkeypatch.setenv("NAJA_SCOPE_INTENT", "1")
    result = api.load_snapshot(snapshot)
    assert result["intent_loaded"] is False
    assert "missing" in result["intent_note"]
    assert api.status()["top"]["model"] == "fsm_top"


def test_package_type_is_labelled_a_type(loaded):
    assert api.get_intent("fsm_pkg::state_t")["intent"] == "type"
    assert api.get_intent("fsm_pkg::WIDTH")["intent"] == "parameter"


NESTED = """
library ieee;
use ieee.std_logic_1164.all;
entity leaf is
  port (a : in std_logic; y : out std_logic);
end entity;
architecture rtl of leaf is
  signal hold : std_logic;
begin
  hold <= a;
  y <= hold;
end architecture;

library ieee;
use ieee.std_logic_1164.all;
entity gen_top is
  port (clk, a : in std_logic; y : out std_logic);
end entity;
architecture rtl of gen_top is
  type phase_t is (P_IDLE, P_BUSY);
  type ctl_t is record
    state : phase_t;
    done : std_logic;
  end record;
  signal ctl : ctl_t;
begin
  block_gen : if true generate
    inner_gen : for i in 0 to 0 generate
      u_leaf : entity work.leaf port map (a => a, y => y);
    end generate;
  end generate;
  process(clk) begin
    if rising_edge(clk) then
      ctl.done <= a;
      if ctl.state = P_IDLE then ctl.state <= P_BUSY; else ctl.state <= P_IDLE; end if;
    end if;
  end process;
end architecture;
"""


def test_paths_through_generate_labels_and_record_fsm(tmp_path):
    source = tmp_path / "nested.vhd"
    source.write_text(NESTED)
    with pytest.warns(RuntimeWarning, match="Beta"):
        api.load_vhdl(str(source), top="gen_top", intent=True)
    children = [c["name"] for c in api.get_hierarchy()["root"]["children"]]
    leaf = next(name for name in children if name.endswith("u_leaf"))
    assert "." in leaf
    assert api.resolve(f"gen_top.{leaf}")["matches"][0]["model"] == "leaf"
    assert api.get_intent(f"gen_top.{leaf}.hold", want="type")["type"] == "std_logic"
    assert api.resolve(f"gen_top.{leaf}.y")["matches"][0]["kind"] == "term"
    assert "text" in api.get_source(f"gen_top.{leaf}.hold", context_lines=0)
    rec = api.get_intent("gen_top.ctl", want="fsm_states")
    assert "note" not in rec
    state = next(f for f in rec["struct"]["fields"] if f["name"] == "state")
    assert [m["name"] for m in state["enum"]["members"]] == ["P_IDLE", "P_BUSY"]
    assert "enum" not in next(f for f in rec["struct"]["fields"] if f["name"] == "done")


def test_library_named_by_the_design(tmp_path):
    package = tmp_path / "p.vhd"
    package.write_text("package p is\n constant W : integer := 1;\nend package;\n")
    design = tmp_path / "t.vhd"
    design.write_text("""
library ieee, mylib;
use ieee.std_logic_1164.all;
use mylib.p.all;
entity t is
  port (a : in std_logic; y : out std_logic);
end entity;
architecture rtl of t is
begin
  y <= a;
end architecture;
""")
    files = [str(package), str(design)]
    with pytest.warns(RuntimeWarning, match="Beta"):
        with pytest.raises(ScopeError, match="missing VHDL library"):
            api.load_vhdl(files, top="t")
    SESSION.reset()
    with pytest.warns(RuntimeWarning, match="Beta"):
        assert api.load_vhdl(files, top="t", library="mylib")["top"]["model"] == "t"
    snapshot = str(tmp_path / "snapshot")
    api.save_snapshot(snapshot)
    SESSION.reset()
    # Intent re-elaboration needs the library back from the snapshot metadata.
    with pytest.warns(RuntimeWarning, match="Beta"):
        assert api.load_snapshot(snapshot, intent=True)["intent_loaded"] is True
    assert api.get_intent("mylib_not_used::W").get("error")
    assert api.get_intent("p::W")["value"] == "1"
