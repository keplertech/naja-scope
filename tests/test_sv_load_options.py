# SPDX-License-Identifier: Apache-2.0
"""load_systemverilog's `defines` and `allow_unknown_designs` passthrough.

Added alongside the core-v-mcu exploration: that design needs both --
`` `protect``/`` `endprotect`` wrapped IP needs empty defines to strip, and a
dozen undelivered technology hard macros need blackboxing -- and neither
kwarg was wired past loader.py before, even though the raw
NLDB.loadSystemVerilog binding already accepted them (mirroring load_verilog's
existing allow_unknown_designs).
"""
import pytest

from naja_scope import api
from naja_scope.errors import ScopeError
from naja_scope.session import SESSION


def test_allow_unknown_designs_blackboxes_unresolved_module(tmp_path):
    (tmp_path / "top.sv").write_text(
        "module top(input clk, output q);\n"
        "  unknown_ip u_ip(.clk_i(clk), .q_o(q));\n"
        "endmodule\n")
    SESSION.reset()
    with pytest.raises(ScopeError):
        api.load_systemverilog(files=[str(tmp_path / "top.sv")])
    SESSION.reset()
    res = api.load_systemverilog(files=[str(tmp_path / "top.sv")],
                                 allow_unknown_designs=True)
    assert res["top"]["name"] == "top"


def test_defines_select_ifdef_branch(tmp_path):
    (tmp_path / "top.sv").write_text(
        "module top(input clk, output q);\n"
        "`ifdef USE_WIDE\n"
        "  reg [7:0] r;\n"
        "`else\n"
        "  reg [3:0] r;\n"
        "`endif\n"
        "  always @(posedge clk) r <= r + 1;\n"
        "  assign q = r[0];\n"
        "endmodule\n")
    SESSION.reset()
    api.load_systemverilog(files=[str(tmp_path / "top.sv")],
                           defines=["USE_WIDE"])
    card = api.get_module_card("top")
    reg_models = card["counts"]["by_model"]
    assert any("8" in name or "w8" in name for name in reg_models), reg_models


_DP_RAM = """module dp_ram(input logic clk_a, clk_b, we_a, we_b,
              input logic [2:0] addr_a, addr_b,
              input logic [7:0] wd_a, wd_b,
              output logic [7:0] rd_a, rd_b);
  logic [7:0] mem [8];
  always @(posedge clk_a) begin
    if (we_a) mem[addr_a] = wd_a;
    rd_a <= mem[addr_a];
  end
  always @(posedge clk_b) begin
    if (we_b) mem[addr_b] = wd_b;
    rd_b <= mem[addr_b];
  end
endmodule
module top(input logic clk_a, clk_b, we_a, we_b,
           input logic [2:0] addr_a, addr_b,
           input logic [7:0] wd_a, wd_b,
           output logic [7:0] rd_a, rd_b);
  dp_ram ram(.*);
endmodule
"""


def test_blackbox_multi_writer_memories(tmp_path):
    """najaeda>=0.7.29 can blackbox a module whose memory has several
    writers (unsupported inference) instead of failing the whole load."""
    (tmp_path / "dp_ram.sv").write_text(_DP_RAM)
    source = str(tmp_path / "dp_ram.sv")
    SESSION.reset()
    with pytest.raises(ScopeError):
        api.load_systemverilog(files=[source])
    SESSION.reset()
    res = api.load_systemverilog(files=[source],
                                 blackbox_multi_writer_memories=True)
    assert res["top"]["name"] == "top"
    ram = api.resolve("top.ram")["matches"][0]
    assert ram["model"] == "dp_ram"
    assert ram["is_leaf"] is True
    assert SESSION.load_spec["blackbox_multi_writer_memories"] is True


def test_default_timescale_survives_snapshot_and_intent_reload(tmp_path):
    from naja_scope import server

    source = tmp_path / "timescale.sv"
    source.write_text(
        "module child(input a, output y); assign y = a; endmodule\n"
        "module top(input a, output y);\n"
        "  timeunit 1ns; timeprecision 1ps;\n"
        "  child u(.*);\n"
        "endmodule\n")
    SESSION.reset()
    try:
        with pytest.raises(ScopeError, match="time scale"):
            api.load_systemverilog([str(source)], top="top")
        SESSION.reset()
        result = server.load_systemverilog(
            files=[str(source)], top="top", default_timescale="1ns/1ps")
        assert result["top"]["model"] == "top"
        assert SESSION.load_spec["default_timescale"] == "1ns/1ps"
        snapshot = str(tmp_path / "snapshot")
        api.save_snapshot(snapshot)
        SESSION.reset()
        api.load_snapshot(snapshot)
        assert SESSION.load_spec["default_timescale"] == "1ns/1ps"
        assert api.load_intent()["intent_loaded"] is True
        assert api.get_hierarchy()["root"]["model"] == "top"
    finally:
        SESSION.reset()


def test_default_timescale_without_top_with_flist(tmp_path):
    source = tmp_path / "mixed.sv"
    source.write_text(
        "module child(input a, output y); assign y=a; endmodule\n"
        "module top(input a, output y); timeunit 1ns; timeprecision 1ps;\n"
        "child u(.*); endmodule\n")
    flist = tmp_path / "sources.f"
    flist.write_text(f'"{source}"\n')
    SESSION.reset()
    try:
        result = api.load_systemverilog(flist=str(flist), default_timescale="1ns/1ps")
        assert result["top"]["model"] == "top"
        assert api.resolve("top.u")["matches"][0]["model"] == "child"
    finally:
        SESSION.reset()


@pytest.mark.parametrize("timescale", ["", "1ns/1ps\n--top other", 123])
def test_default_timescale_rejects_invalid_filelist_tokens(timescale):
    with pytest.raises(ScopeError, match="default_timescale"):
        api.load_systemverilog(default_timescale=timescale)
