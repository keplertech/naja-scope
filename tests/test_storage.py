# SPDX-License-Identifier: Apache-2.0
"""Storage counts use state models and native memories, including snapshots."""
import json

import pytest
from najaeda import naja

from naja_scope import api
from naja_scope.session import SESSION

SV = """
module store(input clk, we, input [1:0] a, input [7:0] d,
             output [7:0] q, r, output reg [4:0] regq);
  logic [7:0] mem [0:3];
  localparam logic [7:0] rom [0:3] = '{8'h12,8'h34,8'h56,8'h78};
  always_ff @(posedge clk) begin
    if (we) mem[a] <= d;
    regq <= d[4:0];
  end
  assign q = mem[a];
  assign r = rom[a];
endmodule
module top(input clk, we, input [1:0] a, input [7:0] d,
           output [7:0] q0, q1, r0, r1, output [4:0] s0, s1);
  store u0(clk, we, a, d, q0, r0, s0);
  store u1(clk, we, a, d, q1, r1, s1);
endmodule
"""

LIB = """
library(storage_test) {
  cell(PAIR) {
    ff_bank(S, SN, 2) { clocked_on : "CK"; next_state : "D"; }
    pin(CK) { direction : input; clock : true; }
    bundle(D) {
      members(D0, D1); direction : input;
      pin(D0) {} pin(D1) {}
    }
    bundle(Q) {
      members(Q0, Q1); direction : output; function : "S";
      pin(Q0) {} pin(Q1) {}
    }
    pin(QN0) { direction : output; function : "!S"; }
  }
}
"""


@pytest.fixture(autouse=True)
def fresh_session():
    SESSION.reset()
    yield
    SESSION.reset()


def load_storage(tmp_path):
    source = tmp_path / 'storage.sv'
    source.write_text(SV)
    api.load_systemverilog([str(source)], top='top')


def test_memory_and_register_counts(tmp_path):
    load_storage(tmp_path)
    card = api.get_module_card('store')
    counts = card['counts']
    assert counts['register_bits'] == 5
    assert counts['register_bits_unknown_instances'] == 0
    assert counts['memory_instances'] == 2
    assert counts['memory_bits'] == 64
    assert counts['rom_instances'] == counts['ram_instances'] == 1
    rom = next(m for m in card['memories'] if m['kind'] == 'rom')
    ram = next(m for m in card['memories'] if m['kind'] == 'ram')
    assert (rom['width'], rom['depth'], rom['read_ports'], rom['write_ports']) == (8, 4, 1, 0)
    assert rom['initialized'] is True
    assert rom['init_preview'] == "32'h78563412"
    assert rom['init_truncated'] is False
    assert ram['initialized'] is False
    assert ram['write_ports'] == 1
    assert 'init_preview' not in ram
    assert card['memories_truncated'] is False
    # Direct-child counts differ from totals across both instances of store.
    assert api.get_module_card('top')['counts']['memory_bits'] == 0
    stats = api.get_stats(limit=1)
    assert stats['flat_register_bits'] == 10
    assert stats['flat_memory_bits'] == 128
    assert stats['flat_memory_instances'] == 4
    assert stats['flat_rom_instances'] == stats['flat_ram_instances'] == 2
    assert stats['flat_register_bits_unknown_instances'] == 0
    assert stats['has_more'] is True
    subtree = api.get_stats('top.u0')
    assert subtree['flat_register_bits'] == 5
    assert subtree['flat_memory_bits'] == 64
    snapshot = tmp_path / 'snapshot'
    snapshot.mkdir()
    api.save_snapshot(str(snapshot))
    SESSION.reset()
    api.load_snapshot(str(snapshot))
    assert api.get_module_card('store') == card
    assert api.get_stats(limit=1) == stats
    json.dumps(card)  # The public result contains no native objects.


def test_memory_details_are_bounded(tmp_path):
    load_storage(tmp_path)
    design = SESSION.require_top().design.getInstance('u0').getModel()
    rom = next(i for i in design.getInstances()
               if i.getModel().getParameter('WR_PORTS') is not None
               and i.getModel().getParameter('WR_PORTS').getValue() == '0')
    # An instance override must win over the primitive's default INIT.
    image = "32'b" + ('1_0_x_z_' * 8).rstrip('_')
    rom.getInstParameter('INIT').setValue(image)
    for index in range(13):
        naja.SNLInstance.create(design, rom.getModel(), f'extra_rom_{index}')
    card = api.get_module_card('store')
    assert len(card['memories']) == 12
    assert card['counts']['memory_instances'] == 15
    assert card['memories_truncated'] is True
    detail = next(m for m in card['memories'] if m['initialized'])
    assert detail['init_preview'] == image[:64]
    assert detail['init_truncated'] is True


def test_liberty_bank_counts_states_not_outputs(tmp_path):
    lib = tmp_path / 'bank.lib'
    lib.write_text(LIB)
    source = tmp_path / 'top.v'
    source.write_text('''module top(input clk, a, b, output q0, q1);
      PAIR u_bank(.CK(clk), .D0(a), .D1(b), .Q0(q0), .Q1(q1));
    endmodule''')
    api.load_liberty([str(lib)])
    api.load_verilog([str(source)])
    card = api.get_module_card('top')
    assert card['counts']['sequential_instances'] == 1
    assert card['counts']['register_bits'] == 2
    assert card['counts']['register_bits_unknown_instances'] == 0
    assert card['counts']['memory_instances'] == 0
    assert api.get_stats()['flat_register_bits'] == 2


def test_vhdl_rom(tmp_path):
    source = tmp_path / 'rom.vhd'
    source.write_text('''library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
entity rom_top is
  port(a : in unsigned(1 downto 0); q : out std_logic_vector(7 downto 0));
end entity;
architecture rtl of rom_top is
  type words is array(0 to 3) of std_logic_vector(7 downto 0);
  constant table_data : words := (x"12", x"34", x"56", x"78");
begin
  q <= table_data(to_integer(a));
end architecture;
''')
    with pytest.warns(RuntimeWarning, match='Beta'):
        api.load_vhdl(str(source), top='rom_top')
    card = api.get_module_card('rom_top')
    assert card['counts']['rom_instances'] == 1
    assert card['counts']['memory_bits'] == 32
    assert card['counts']['register_bits'] == 0
    assert card['memories'][0]['init_preview'] == "32'h78563412"


def test_sequential_cell_without_state_model_is_unknown(tmp_path):
    load_storage(tmp_path)
    top = SESSION.require_top().design
    lib = naja.NLLibrary.createPrimitives(top.getLibrary().getDB())
    model = naja.SNLDesign.createPrimitive(lib, 'timing_only')
    clock = naja.SNLScalarTerm.create(model, naja.SNLTerm.Direction.Input, 'CK')
    data = naja.SNLScalarTerm.create(model, naja.SNLTerm.Direction.Input, 'D')
    model.addInputsToClockArcs([data], clock)
    naja.SNLInstance.create(top, model, 'unknown_reg')
    counts = api.get_module_card('top')['counts']
    assert counts['sequential_instances'] == 1
    assert counts['register_bits'] == 0
    assert counts['register_bits_unknown_instances'] == 1
    stats = api.get_stats()
    assert stats['flat_register_bits'] == 10
    assert stats['flat_register_bits_unknown_instances'] == 1


def test_parameter_dependent_register_states(tmp_path):
    load_storage(tmp_path)
    top = SESSION.require_top().design
    lib = naja.NLLibrary.createPrimitives(top.getLibrary().getDB())
    model = naja.SNLDesign.createPrimitive(lib, 'configurable_reg')
    for name in ('CK', 'D'):
        naja.SNLScalarTerm.create(model, naja.SNLTerm.Direction.Input, name)
    output = naja.SNLScalarTerm.create(model, naja.SNLTerm.Direction.Output, 'Q')
    param = naja.SNLParameter.createBinary(model, 'DOUBLE', 1, 0)
    model.setSequentialModelFromParameters(parameters=['DOUBLE'], models=[
        {'values': [0], 'clocked_on': 'CK',
         'states': [{'name': 'S', 'next_state': 'D'}], 'outputs': [(output, 'S')]},
        {'values': [1], 'clocked_on': 'CK',
         'states': [{'name': 'S', 'next_state': 'D'},
                    {'name': 'T', 'next_state': 'S'}], 'outputs': [(output, 'T')]},
    ])
    naja.SNLInstance.create(top, model, 'single')
    double = naja.SNLInstance.create(top, model, 'double')
    naja.SNLInstParameter.create(double, param, "1'b1")
    assert api.get_module_card('top')['counts']['register_bits'] == 3
    assert api.get_stats()['flat_register_bits'] == 13
