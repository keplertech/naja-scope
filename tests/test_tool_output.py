# SPDX-License-Identifier: Apache-2.0
"""Payload budgets through the MCP client, including structured output."""

import asyncio
import json

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from naja_scope import api, server
from naja_scope.errors import ScopeError
from naja_scope.session import SESSION


@pytest.fixture
def midsize_session(tmp_path):
    # Many models and long paths expose both large stats and large endpoint
    # pages. Separate scalar registers keep bus drivers independently visible.
    source = tmp_path / 'midsize.sv'
    modules = [
        f'module lane_{i}(input clk, d, output logic q); '
        'always_ff @(posedge clk) q <= d; endmodule\n'
        for i in range(64)
    ]
    modules.append('module top(input clk, input [63:0] d, output [63:0] q);\n')
    modules.extend(
        f'lane_{i} pipeline_stage_with_a_long_elaborated_instance_name_'
        f'for_payload_budget_validation_{i} (.clk(clk), .d(d[{i}]), .q(q[{i}]));\n'
        for i in range(64)
    )
    modules.append('endmodule\n')
    source.write_text(''.join(modules))
    SESSION.reset()
    api.load_systemverilog([str(source)], top='top')
    yield
    SESSION.reset()


def test_stats_summary_and_complete_model_pagination(midsize_session):
    summary = api.get_stats()
    assert summary['flat_sequential'] == summary['flat_register_bits'] == 64
    assert summary['models'] == []
    assert summary['total_models'] >= 65
    cursor = summary['next_cursor']
    models = []
    while cursor is not None:
        page = api.get_stats(limit=7, cursor=cursor)
        assert 0 < page['count'] <= 7
        assert page['flat_register_bits'] == summary['flat_register_bits']
        models.extend(m['model'] for m in page['models'])
        cursor = page['next_cursor']
    assert len(models) == len(set(models)) == summary['total_models']
    assert api.get_stats(cursor='0')['count'] == 25
    assert api.get_stats(limit=2)['count'] == 2
    with pytest.raises(ScopeError, match='Invalid cursor'):
        api.get_stats(cursor='bad')
    subtree = api.get_stats('top.pipeline_stage_with_a_long_elaborated_instance_name_'
                            'for_payload_budget_validation_0')
    assert subtree['flat_register_bits'] == 1
    assert subtree['models'] == []


def test_default_pages_and_explicit_limits(midsize_session):
    first = api.find('*', kind='instance')
    assert first['count'] == 20
    second = api.find('*', kind='instance', cursor=first['next_cursor'])
    assert second['count'] == 20
    assert not ({m['path'] for m in first['matches']} &
                {m['path'] for m in second['matches']})
    assert api.find('*', kind='instance', limit=50)['count'] == 50
    for query, path, key in (
        (api.get_drivers, 'top.q', 'leaf_drivers'),
        (api.get_loads, 'top.clk', 'leaf_loads'),
    ):
        default = query(path)
        assert len(default[key]) == 20
        assert default['truncated'] is True
        full = query(path, limit=100)
        assert len(full[key]) == 64
        assert full['truncated'] is False
        assert {e['path'] for e in default[key]} <= {e['path'] for e in full[key]}


def test_mcp_text_is_compact_bounded_and_structured(midsize_session):
    async def check():
        async with create_connected_server_and_client_session(server.mcp) as client:
            tools = {t.name: t for t in (await client.list_tools()).tools}
            for name, arguments in (
                ('get_stats', {}),
                ('get_stats', {'limit': 5}),
                ('find', {'pattern': '*', 'kind': 'instance'}),
                ('get_drivers', {'path': 'top.q'}),
                ('get_loads', {'path': 'top.clk'}),
                ('get_hierarchy', {}),
                # ScopeError remains an ordinary structured tool response.
                ('find', {'pattern': '*', 'cursor': 'bad'}),
            ):
                result = await client.call_tool(name, arguments)
                assert not result.isError
                assert tools[name].outputSchema is not None
                assert len(result.content) == 1
                text = result.content[0].text
                assert len(text) < 16_000, (name, len(text))
                assert json.loads(text) == result.structuredContent
                assert text == json.dumps(result.structuredContent,
                                          ensure_ascii=False, separators=(',', ':'))
                if name == 'get_stats' and not arguments:
                    assert len(text) < 1_000
    asyncio.run(check())
