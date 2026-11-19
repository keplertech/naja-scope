# SPDX-License-Identifier: Apache-2.0
"""Exact names survive tool boundaries without separator or bit parsing."""
import asyncio

import pytest

from naja_scope import api
from naja_scope.errors import ResolveError, ScopeError
from naja_scope.resolve import resolve_path
from naja_scope.session import SESSION


@pytest.fixture
def exact_session():
    from pathlib import Path
    SESSION.reset()
    api.load_verilog([str(Path(__file__).parent / "fixtures" / "exact_paths.v")])
    yield
    SESSION.reset()


def roundtrip(record):
    args = {k: record[k] for k in ("path", "bit", "kind")}
    first = resolve_path(SESSION, **args)[0]
    result = api.resolve(**args)["matches"][0]
    assert {k: result[k] for k in args} == args
    again = resolve_path(SESSION, **{k: result[k] for k in args})[0]
    if first.kind == "instance":
        assert first.obj.snl_instance == again.obj.snl_instance
        assert list(first.obj.snlpath.getInstanceIDs()) == list(again.obj.snlpath.getInstanceIDs())
    else:
        assert first.obj == again.obj
        assert first.owner.names == again.owner.names


@pytest.mark.parametrize("names", [["a.b"], ["a", "b"], ["$yosys$name"], ["a/b[]$"], ["d_in[0]"]])
def test_verilog_exact_names(exact_session, names):
    rec = api.resolve(names)["matches"][0]
    assert rec["path"] == ["exact_paths"] + names
    assert rec["bit"] is None
    roundtrip(rec)


def test_ambiguous_splits_are_distinct(exact_session):
    dotted = resolve_path(SESSION, ["a.b"], kind="instance")[0]
    nested = resolve_path(SESSION, ["a", "b"], kind="instance")[0]
    assert dotted.obj.snl_instance != nested.obj.snl_instance
    assert dotted.path == ["exact_paths", "a.b"]
    assert nested.path == ["exact_paths", "a", "b"]


def test_bus_bit_and_bracket_scalar(exact_session):
    scalar = resolve_path(SESSION, ["d_in[0]"], kind="term")[0]
    bus = resolve_path(SESSION, ["d_in"], kind="term", bit=0)[0]
    assert type(scalar.obj).__name__ == "SNLScalarTerm"
    assert type(bus.obj).__name__ == "SNLBusTermBit"
    assert scalar.obj.getID() != bus.obj.getID()
    assert scalar.bit is None and bus.bit == 0
    for rec in (api.resolve(["d_in[0]"], kind="term")["matches"][0],
                api.resolve(["d_in"], kind="term", bit=0)["matches"][0]):
        roundtrip(rec)
    with pytest.raises(ResolveError):
        api.resolve(["d_in[0]"], bit=0)
    with pytest.raises(ResolveError):
        api.resolve(["d_in"], bit=9)


def test_element_errors_and_suggestions(exact_session):
    with pytest.raises(ResolveError) as exc:
        api.resolve(["a", "bx"])
    assert exc.value.index == 1
    assert "element 1 'bx' not found under ['exact_paths', 'a']" in str(exc.value)
    assert "b" in exc.value.suggestions
    assert "did you mean" in str(exc.value)


@pytest.mark.parametrize("query", [api.resolve, api.get_drivers, api.get_loads,
    api.get_source, api.get_hierarchy, api.get_stats, api.open_schematic])
def test_string_paths_rejected(exact_session, query):
    with pytest.raises(ScopeError, match="JSON list"):
        query("a.b")


def test_other_string_inputs_rejected(exact_session):
    with pytest.raises(ScopeError, match="JSON list"):
        api.trace_cone("a.b", "fanin")
    with pytest.raises(ScopeError, match="JSON list"):
        api.find("*")
    with pytest.raises(ScopeError, match="JSON list"):
        api.get_intent("exact_paths.d_in")
    with pytest.raises(ScopeError, match="JSON list"):
        api.annotate_schematic([{"path": "a.b"}])


def test_element_globs_and_recursive_descent(exact_session):
    assert [r["path"] for r in api.find(["a.b"], kind="instance")["matches"]] == [["exact_paths", "a.b"]]
    assert [r["path"] for r in api.find(["a", "b"], kind="instance")["matches"]] == [["exact_paths", "a", "b"]]
    assert len(api.find(["**", "b"], kind="instance")["matches"]) == 1
    assert len(api.find(["$yosys*"], kind="instance")["matches"]) == 1
    assert api.find(["exact_*", "a", "b"], kind="instance")["matches"][0]["path"] == ["exact_paths", "a", "b"]
    assert api.find(["a/b*"], kind="instance")["matches"][0]["path"][-1] == "a/b[]$"


def test_all_connectivity_paths_roundtrip(exact_session):
    records = api.find(["**"], limit=200)["matches"]
    for direction in ("fanin", "fanout"):
        cone = api.trace_cone(["y"], direction)
        records += sum((cone["frontier"][k] for k in ("flops", "ports", "blackboxes")), [])
    for query in (api.get_drivers, api.get_loads):
        for names in (["y"], ["d_in"], ["d_in[0]"]):
            out = query(names, limit=200)
            records += sum((out[k] for k in out if k.startswith(("leaf_", "top_"))), [])
    assert any(r.get("bit") == 0 for r in records)
    for rec in records:
        if "path" in rec:
            roundtrip(rec)


def test_uart_frontier_roundtrip(uart_session):
    for direction in ("fanin", "fanout"):
        cone = api.trace_cone(["u_tx", "state_n"], direction)
        for group in ("flops", "ports", "blackboxes"):
            for rec in cone["frontier"][group]:
                roundtrip(rec)


def test_mcp_path_schemas_and_validation(exact_session):
    from naja_scope import server
    async def check():
        tools = {t.name: t for t in await server.mcp.list_tools()}
        for name, arg in (("resolve", "path"), ("find", "pattern"), ("get_intent", "ref"),
                          ("get_drivers", "path"), ("get_loads", "path"),
                          ("trace_cone", "path"), ("get_source", "path"),
                          ("get_hierarchy", "path"), ("get_stats", "path"),
                          ("open_schematic", "path"), ("show_schematic_net", "path")):
            schema = tools[name].inputSchema["properties"][arg]
            schema = next((s for s in schema.get("anyOf", []) if s.get("type") == "array"), schema)
            assert schema["type"] == "array"
            assert schema["items"]["type"] == "string"
        content, structured = await server.mcp.call_tool("resolve", {"path": ["d_in"], "bit": 0, "kind": "term"})
        assert structured.get("result", structured)["matches"][0]["bit"] == 0
        with pytest.raises(Exception, match="list"):
            await server.mcp.call_tool("resolve", {"path": "a.b"})
    asyncio.run(check())


def test_raw_names_with_spaces_and_glob_punctuation(exact_session):
    from najaeda import naja
    from naja_scope import snl
    top = snl.top_design()
    model = top.getInstance("a.b").getModel()
    names = [" name with spaces ", "x*y?[]", r"\literal", "#not-an-id"]
    for name in names:
        inst = naja.SNLInstance.create(top, model, name)
        resolved = resolve_path(SESSION, [name], kind="instance")[0]
        assert resolved.obj.snl_instance.getID() == inst.getID()
        assert resolved.path[-1] == name
        roundtrip(api.resolve([name], kind="instance")["matches"][0])


@pytest.mark.parametrize("path", ["", ("a", "b"), [""], [1], ["a", None], {"display": "a.b"}])
def test_invalid_path_types(exact_session, path):
    with pytest.raises(ScopeError, match="JSON list"):
        api.resolve(path)


def test_hierarchy_source_and_top_roundtrip(exact_session):
    assert api.resolve([])["matches"][0]["path"] == ["exact_paths"]
    hierarchy = api.get_hierarchy(depth=3, limit=100)["root"]
    def walk(node):
        roundtrip(node)
        for child in node.get("children", []):
            walk(child)
    walk(hierarchy)
    roundtrip(api.get_source(["d_in"], bit=2))


def test_nested_mcp_schemas():
    from naja_scope import server
    async def check():
        tools = {t.name: t for t in await server.mcp.list_tools()}
        export = tools["export_schematic"].inputSchema
        instances = next(s for s in export["properties"]["instances"]["anyOf"] if s.get("type") == "array")
        assert instances["items"] == {"type": "array", "items": {"type": "string"}}
        for arg in ("nets", "traces"):
            array = next(s for s in export["properties"][arg]["anyOf"] if s.get("type") == "array")
            target = export["$defs"][array["items"]["$ref"].rsplit("/", 1)[1]]
            assert target["properties"]["path"]["items"]["type"] == "string"
            assert "bit" in target["properties"]
            assert target["additionalProperties"] is False
        schema = tools["annotate_schematic"].inputSchema
        target = schema["$defs"][schema["properties"]["items"]["items"]["$ref"].rsplit("/", 1)[1]]
        assert target["properties"]["path"]["items"]["type"] == "string"
    asyncio.run(check())


def test_anonymous_addresses_do_not_shadow_literal_names(exact_session):
    from najaeda import naja
    from naja_scope import snl
    top = snl.top_design()
    model = top.getInstance("a.b").getModel()
    anonymous = naja.SNLInstance.create(top, model)
    literal = naja.SNLInstance.create(top, model, f"#{anonymous.getID()}")
    anon_path = [snl.inst_segment(anonymous)]
    literal_path = [literal.getName()]
    assert anon_path != literal_path
    assert resolve_path(SESSION, anon_path)[0].obj.snl_instance.getID() == anonymous.getID()
    assert resolve_path(SESSION, literal_path)[0].obj.snl_instance.getID() == literal.getID()
    roundtrip(api.resolve(anon_path)["matches"][0])
    roundtrip(api.resolve(literal_path)["matches"][0])
