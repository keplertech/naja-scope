# SPDX-License-Identifier: Apache-2.0
"""Source references on gate-level Verilog (najaeda>=0.7.29).

Netlist objects carry a language-neutral source declaration (their line in
the .v file), and with yosys_source_attributes=True the Yosys
`(* src = ... *)` attributes become source origins pointing back to the RTL.
"""
import os

import pytest

from naja_scope import api
from naja_scope.session import SESSION

HERE = os.path.dirname(__file__)
LIB = os.path.join(HERE, "..", "examples", "stdcells.lib")

NETLIST = """(* src = "rtl.sv:1.1-9.10" *)
module top(input a, input clk, output y);
  (* src = "rtl.sv:4.9-4.13|rtl.sv:6.3-6.20" *)
  wire n;
  (* src = "rtl.sv:5.3-7.6" *)
  INV u_inv (.I(a), .Z(n));
  DFF u_ff (.D(n), .CK(clk), .Q(y));
endmodule
"""

RTL = "".join(f"// rtl line {i}\n" for i in range(1, 11))


@pytest.fixture
def yosys_netlist(tmp_path):
    (tmp_path / "rtl.sv").write_text(RTL)
    path = tmp_path / "netlist.v"
    path.write_text(NETLIST)
    yield str(path)
    SESSION.reset()


def _load(path, **kwargs):
    SESSION.reset()
    api.load_liberty([LIB])
    api.load_verilog([path], **kwargs)


def test_netlist_declaration_source(yosys_netlist):
    _load(yosys_netlist)
    out = api.get_source("top.u_inv", context_lines=0)
    assert out["file"] == yosys_netlist
    assert out["start"] == 6
    assert "INV u_inv" in out["text"]
    assert "origins" not in out
    assert api.resolve("top.u_inv")["matches"][0]["src"].endswith("netlist.v:6")


def test_yosys_origins_cross_probe_to_rtl(yosys_netlist, tmp_path):
    _load(yosys_netlist, yosys_source_attributes=True)
    match = api.resolve("top.u_inv")["matches"][0]
    assert match["origins"] == ["rtl.sv:5-7"]
    out = api.get_source("top.u_inv", context_lines=0, origin=0)
    assert out["origin"] == 0
    assert out["file"] == str(tmp_path / "rtl.sv")
    assert out["text"] == "// rtl line 5\n// rtl line 6\n// rtl line 7\n"
    # Multi-location src attributes are split into separate origins.
    assert api.resolve("top.n")["matches"][0]["origins"] == [
        "rtl.sv:4", "rtl.sv:6"]
    # Cells without a src attribute have none; bad indexes are structured.
    assert "origins" not in api.resolve("top.u_ff")["matches"][0]
    assert "error" in api.get_source("top.u_ff", origin=0)


def test_yosys_origins_survive_snapshot(yosys_netlist, tmp_path):
    _load(yosys_netlist, yosys_source_attributes=True)
    snap = str(tmp_path / "snap")
    os.makedirs(snap)
    api.save_snapshot(snap)
    api.reset_universe()
    api.load_snapshot(snap)
    match = api.resolve("top.u_inv")["matches"][0]
    assert match["src"].endswith("netlist.v:6")
    assert match["origins"] == ["rtl.sv:5-7"]
