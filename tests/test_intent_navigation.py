# SPDX-License-Identifier: Apache-2.0
"""Agent recovery paths from issue #37, exercised against the raw engine."""
from pathlib import Path

import pytest

from naja_scope import api, snl

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def warm_uart():
    api.SESSION.reset()
    api.SESSION.load_systemverilog([str(ROOT / 'examples/uart.sv')], keep_ast_link=True)
    yield
    api.SESSION.reset()


@pytest.mark.parametrize('pattern', ['.*state.*', '^state$', '.+state', r'state\d'])
def test_regex_hint_avoids_hierarchy_scan(warm_uart, monkeypatch, pattern):
    def unexpected_walk(*args):
        pytest.fail('regex diagnostic must not walk the hierarchy')
    monkeypatch.setattr(snl, 'child_nodes', unexpected_walk)
    out = api.find(pattern)
    assert out['count'] == 0 and not out['has_more']
    assert 'regex' in out['hint'] and 'glob' in out['hint']
    if pattern == '.*state.*':
        assert "'*state*'" in out['hint']


def test_globs_and_hierarchical_paths_still_work(warm_uart):
    assert api.find('*state*')['count'] > 0
    assert api.find('uart_top.u_tx.state')['count'] > 0
    assert api.find('stat[^e]')['count'] > 0


@pytest.mark.parametrize('want', ['auto', 'parameters'])
def test_instance_parameter_path(warm_uart, want):
    rec = api.get_intent('uart_top.u_tx.DIV_W', want=want)
    assert rec['intent'] == 'parameter'
    assert rec['name'] == 'DIV_W' and rec['value'] == '4'
    assert rec['expr'] == '4' and rec['localparam'] is False
    assert rec['src'].endswith('uart.sv:29')
    assert api.get_intent('u_tx.DIV_W', want=want)['value'] == '4'
    assert 'error' in api.get_intent('uart_top.u_tx.NO_SUCH_PARAM', want=want)


def test_parameter_search_hint_points_to_working_call(warm_uart):
    out = api.find('DIV_W')
    assert out['count'] == 0
    assert "get_intent('uart_tx', want='parameters')" in out['hint']
    rec = api.get_intent('uart_tx', want='parameters')
    assert any(p['name'] == 'DIV_W' for p in rec['parameters'])
    assert 'hint' not in api.find('NOT_A_DECLARATION')


def test_parameter_search_without_intent(uart_session):
    out = api.find('DIV_W')
    assert out['count'] == 0 and 'hint' not in out


@pytest.fixture
def package_session():
    api.SESSION.reset()
    api.SESSION.load_systemverilog(
        [str(ROOT / 'tests/fixtures/intent_mini.sv')], keep_ast_link=True)
    yield
    api.SESSION.reset()


@pytest.mark.parametrize('want', ['auto', 'parameters'])
def test_package_and_member_navigation(package_session, want):
    rec = api.get_intent('mini_pkg::PLEN', want=want)
    assert rec['intent'] == 'parameter' and rec['value'] == '34'
    assert rec['expr'] == '(32 == 32) ? 34 : 56'
    package = api.get_intent('mini_pkg', want=want)
    assert package['intent'] == 'parameters'
    assert [p['name'] for p in package['parameters']] == ['PLEN']
    assert package['parameters'][0]['value'] == '34'
    assert 'error' in api.get_intent('no_such_package', want=want)
    assert 'error' in api.get_intent('mini_pkg::ABSENT', want=want)


def test_package_parameter_hint(package_session):
    out = api.find('PLEN')
    assert out['count'] == 0
    assert "get_intent('mini_pkg::PLEN')" in out['hint']


def test_package_source_candidates_verified_by_engine(tmp_path):
    # Includes, comma declarations, and inactive preprocessor branches must
    # not turn source tokens into guessed parameter values.
    (tmp_path / 'pkg.svh').write_text('''
package nav_pkg;
  localparam int A = 3, B = A + 2;
`ifdef NOT_DEFINED
  localparam int GHOST = 99;
`endif
endpackage
''')
    source = tmp_path / 'top.sv'
    source.write_text('`include "pkg.svh"\nmodule nav_top(output logic [nav_pkg::B-1:0] q); assign q = 0; endmodule\n')
    flist = tmp_path / 'rtl.f'
    # File lists use shell-style escaping, including on Windows. Forward
    # slashes preserve drive paths; quotes also support directories with spaces.
    flist.write_text(f'+incdir+"{tmp_path.as_posix()}"\n"{source.as_posix()}"\n')
    api.SESSION.reset()
    try:
        api.SESSION.load_systemverilog([], flist=str(flist), keep_ast_link=True)
        rec = api.get_intent('nav_pkg')
        assert {p['name']: p['value'] for p in rec['parameters']} == {'A': '3', 'B': '5'}
        assert 'hint' not in api.find('GHOST')
    finally:
        api.SESSION.reset()


def test_package_catalogue_does_not_survive_session_reset(package_session):
    assert api.get_intent('mini_pkg')['count'] == 1
    api.SESSION.reset()
    api.SESSION.load_systemverilog([str(ROOT / 'examples/uart.sv')], keep_ast_link=True)
    assert 'error' in api.get_intent('mini_pkg')
    assert 'hint' not in api.find('PLEN')
