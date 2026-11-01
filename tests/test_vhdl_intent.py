# SPDX-License-Identifier: Apache-2.0
"""VHDL intent through the public API: naja's VHDL records, normalized to the
get_intent shape, and the same load/reload lifecycle as SystemVerilog."""
import asyncio

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


def test_generic_override_and_visible_constant(loaded):
    rec = api.get_intent("fsm_top.u0")
    assert rec["intent"] == "parameters"
    params = {p["name"]: p for p in rec["parameters"]}
    assert params["N"]["value"] == "4"
    assert params["N"]["expr"] == "3"
    assert params["N"]["overridden"] is True
    assert params["N"]["localparam"] is False
    assert params["WIDTH"]["owner"] == "fsm_pkg"
    assert params["WIDTH"]["localparam"] is True


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
