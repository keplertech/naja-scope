# SPDX-License-Identifier: Apache-2.0
"""Exercise scope integration over the real upstream browser protocol."""
import builtins
import json
from urllib.parse import urlsplit
from urllib.request import urlopen

import pytest

from najaeda import naja
from naja_scope import api, schematic
from naja_scope.errors import ScopeError
from naja_scope.runtime import DESIGN_LOCK
from naja_scope.session import SESSION


@pytest.fixture
def design():
    SESSION.reset()
    with DESIGN_LOCK:
        u = naja.NLUniverse.create()
        db = naja.NLDB.create(u)
        lib = naja.NLLibrary.create(db, "work")
        top = naja.SNLDesign.create(lib, "top")
        port = naja.SNLBusTerm.create(top, naja.SNLTerm.Direction.Input, 3, 0, "data")
        single = naja.SNLBusTerm.create(top, naja.SNLTerm.Direction.Input, 7, 7, "single")
        prims = naja.NLLibrary.createPrimitives(db, "primitives")
        leaf = naja.SNLDesign.createPrimitive(prims, "leaf")
        naja.SNLScalarTerm.create(leaf, naja.SNLTerm.Direction.Input, "A")
        named = naja.SNLInstance.create(top, leaf, "named")
        anonymous = naja.SNLInstance.create(top, leaf)
        another = naja.SNLInstance.create(top, leaf)
        for term in (port.getBusTermBit(2), single.getBusTermBit(7)):
            net = naja.SNLScalarNet.create(top)
            term.setNet(net)
            if term == port.getBusTermBit(2):
                anonymous.getInstTerm(leaf.getTerm("A")).setNet(net)
        u.setTopDB(db)
        u.setTopDesign(top)
        ids = named.getID(), anonymous.getID(), another.getID()
    yield ids
    schematic.close()
    SESSION.reset()


@pytest.fixture
def viewer(design):
    package = pytest.importorskip("naja_schematic")
    if not hasattr(package, "export_png"):
        pytest.skip("requires naja-schematic>=0.3.0")
    pytest.importorskip("websockets")
    return design


def connect(url):
    from websockets.sync.client import connect as ws_connect
    parsed = urlsplit(url)
    return ws_connect(f"ws://{parsed.netloc}/ws?{parsed.query}",
                      origin=f"http://{parsed.netloc}")


def receive(ws, kind):
    for _ in range(20):
        message = json.loads(ws.recv(timeout=3))
        if message.get("response") == kind:
            return message
    pytest.fail(f"No {kind} response")


def test_optional_dependency_error(design, monkeypatch):
    original = builtins.__import__
    def missing(name, *args, **kwargs):
        if name == "naja_schematic":
            raise ImportError("not installed")
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", missing)
    with pytest.raises(ScopeError, match="schematic"):
        api.open_schematic()
    assert api.get_schematic_selection() == {"selection": None, "url": None}


def test_focus_selection_annotations_and_reset(viewer):
    _, anonymous, another = viewer
    path = ["top", f"#{anonymous}"]
    opened = api.open_schematic(path)
    assert opened["path"] == path
    with urlopen(opened["url"], timeout=3) as page:
        assert b"canvas" in page.read()
    with connect(opened["url"]) as ws:
        ws.send(json.dumps({"request": "load_root"}))
        assert receive(ws, "root_response")["root"]["name"] == "top"
        focus = receive(ws, "focus_instance")
        assert focus["id_path"] == [anonymous]
        ws.send(json.dumps({"request": "resolve_instance", "id_path": [anonymous]}))
        assert receive(ws, "instance_resolved")["found"]
        ws.send(json.dumps({"request": "instance_selected", "id_path": [another], "path": [""]}))
        # A following request forms a barrier after the selection notification.
        ws.send(json.dumps({"request": "load_root"}))
        receive(ws, "root_response")
        assert api.get_schematic_selection()["selection"]["path"] == ["top", f"#{another}"]
        api.annotate_schematic([{"path": path, "message": "check this", "severity": "warning"},
                               {"path": path + ["A"], "kind": "term", "message": "input"}])
        diagnosis = receive(ws, "diagnosis_response")
        assert diagnosis["items"][0]["id_path"] == [anonymous]
        assert diagnosis["items"][1]["terminal"] == "A"
        api.annotate_schematic([])
        assert receive(ws, "diagnosis_response")["items"] == []
        api.reset_universe()
        receive(ws, "design_changed")
        assert api.get_schematic_selection()["selection"] is None


def test_snapshot_reload_and_shutdown(viewer, tmp_path):
    opened = api.open_schematic(['top', 'named'])
    snapshot = str(tmp_path / "snapshot")
    api.save_snapshot(snapshot)
    with connect(opened["url"]) as ws:
        ws.send(json.dumps({"request": "load_root"}))
        receive(ws, "root_response")
        api.reset_universe()
        receive(ws, "design_changed")
        api.load_snapshot(snapshot)
        receive(ws, "design_changed")
        ws.send(json.dumps({"request": "load_root"}))
        assert receive(ws, "root_response")["root"]["name"] == "top"
        assert api.open_schematic(['top', 'named'])["url"] == opened["url"]
        assert receive(ws, "focus_instance")["id_path"] == [viewer[0]]
    server = schematic._viewer
    schematic.close()
    assert not server.running


def test_validation_does_not_start_viewer(design):
    for items in ([{"path": ['top', 'missing']}], [{"path": ['top', 'named'], "severity": "bad"}],
                  [{"path": ['top', 'named'], "message": "a" * 2001}], [{}] * 201):
        with pytest.raises(ScopeError):
            api.annotate_schematic(items)
    assert schematic._viewer is None


def test_mcp_tools_registered():
    import asyncio
    from naja_scope import server
    tools = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
    assert {"open_schematic", "annotate_schematic", "get_schematic_selection",
            "show_schematic_net", "export_schematic"} <= tools.keys()
    assert tools["get_schematic_selection"].annotations.readOnlyHint
    assert not tools["export_schematic"].annotations.readOnlyHint
    assert tools["export_schematic"].annotations.destructiveHint


def test_viewer_waits_for_design_lock(viewer):
    from concurrent.futures import ThreadPoolExecutor, TimeoutError
    opened = api.open_schematic()
    with connect(opened["url"]) as ws, ThreadPoolExecutor(max_workers=1) as executor:
        with DESIGN_LOCK:
            ws.send(json.dumps({"request": "load_root"}))
            pending = executor.submit(receive, ws, "root_response")
            with pytest.raises(TimeoutError):
                pending.result(timeout=0.1)
        assert pending.result(timeout=3)["root"]["name"] == "top"


def test_failed_load_clears_old_selection(viewer, tmp_path):
    opened = api.open_schematic()
    with connect(opened["url"]) as ws:
        ws.send(json.dumps({"request": "instance_selected", "id_path": [viewer[0]], "path": ["named"]}))
        ws.send(json.dumps({"request": "load_root"}))
        receive(ws, "root_response")
        assert api.get_schematic_selection()["selection"] is not None
        with pytest.raises(ScopeError):
            api.load_snapshot(str(tmp_path / "does-not-exist"))
        receive(ws, "design_changed")
        assert api.get_schematic_selection()["selection"] is None


def test_old_generation_cannot_restore_selection_after_reload(viewer, tmp_path):
    opened = api.open_schematic()
    snapshot = str(tmp_path / "snapshot")
    api.save_snapshot(snapshot)
    with connect(opened["url"]) as ws:
        ws.send(json.dumps({"request": "load_root"}))
        old_generation = receive(ws, "root_response")["generation"]
        api.reset_universe()
        receive(ws, "design_changed")
        api.load_snapshot(snapshot)  # same IDs, but a different generation
        generation = receive(ws, "design_changed")["generation"]
        stale = {"request": "instance_selected", "id_path": [viewer[0]],
                 "path": ["named"], "generation": old_generation}
        ws.send(json.dumps(stale))
        ws.send(json.dumps({"request": "load_root", "generation": generation}))
        receive(ws, "root_response")
        assert api.get_schematic_selection()["selection"] is None
        ws.send(json.dumps({**stale, "generation": generation}))
        ws.send(json.dumps({"request": "load_root", "generation": generation}))
        receive(ws, "root_response")
        assert api.get_schematic_selection()["selection"]["path"] == ['top', 'named']


def test_net_trace_and_view_options_protocol(viewer):
    options = {"instance_label": "both", "max_sinks": 16, "group_by": "role"}
    opened = api.open_schematic(view_options=options)
    with connect(opened["url"]) as ws:
        ws.send(json.dumps({"request": "load_root"}))
        receive(ws, "root_response")
        assert receive(ws, "view_options").items() >= options.items()
        path = ["top", f"#{viewer[1]}", "A"]
        result = api.show_schematic_net(path, color="#ff8800", add=False)
        assert result["url"] == opened["url"]
        message = receive(ws, "show_net")
        assert message["id_path"] == [viewer[1]]
        assert message["color"] == "#ff8800"
        assert message["add"] is False
        api.show_schematic_net(['top', 'data'], trace=True, bit=2)
        message = receive(ws, "show_net")
        assert message["id_path"] == []
        assert message["bit"] == 2
        assert message["trace"] is True
        api.show_schematic_net(['top', 'single'])
        assert receive(ws, "show_net")["bit"] == 7
    # Traces and drawing options are replayed to a newly connected viewer.
    with connect(opened["url"]) as ws:
        ws.send(json.dumps({"request": "load_root"}))
        receive(ws, "root_response")
        assert receive(ws, "view_options")["group_by"] == "role"
        assert receive(ws, "show_net")["id_path"] == [viewer[1]]
        assert receive(ws, "show_net")["trace"] is True
        api.reset_universe()
        receive(ws, "design_changed")


def test_headless_exports(viewer, tmp_path):
    import struct
    import xml.etree.ElementTree as ET

    svg = tmp_path / "cone.svg"
    result = api.export_schematic(str(svg), instances=[["top", f"#{viewer[1]}"]],
                                  nets=[{"path": ["top", "data"], "bit": 2}], traces=[{"path": ["top", f"#{viewer[1]}", "A"]}],
                                  view_options={"title": "Input cone", "legend": True,
                                                "instance_label": "both", "hide_ui_glyphs": True})
    assert result == {"file": str(svg), "format": "svg", "bytes": svg.stat().st_size}
    root = ET.parse(svg).getroot()
    assert root.tag.endswith("svg")
    assert "Input cone" in "".join(root.itertext())
    assert any(e.get("data-id-path") == str(viewer[1]) for e in root.iter())
    assert any(e.get("class") == "net" for e in root.iter())
    png = tmp_path / "cone.png"
    api.export_schematic(str(png), nets=[{"path": ["top", "data"], "bit": 2}], scale=2)
    data = png.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert all(n > 0 for n in struct.unpack(">II", data[16:24]))
    assert schematic._viewer is None  # no browser or socket needed


def test_new_tool_validation(viewer, tmp_path):
    for kwargs in ({"path": ['top', 'data']}, {"path": ["top", "data"], "bit": 2, "color": "bad"},
                   {"path": ["top", "data"], "bit": 2, "trace": "yes"}):
        with pytest.raises(ScopeError):
            api.show_schematic_net(**kwargs)
    for options in ({"max_sinks": -1}, {"unknown": True}, []):
        with pytest.raises(ScopeError):
            api.open_schematic(view_options=options)
    svg = tmp_path / "bad.svg"
    for kwargs in ({}, {"instances": ["top"]}, {"nets": [['top', 'data']]},
                   {"instances": [['top', 'named']] * 201}, {"instances": ['top', 'named']},
                   {"nets": [{"path": ["top", "data"], "bit": 2}], "view_options": {"group_by": "invalid"}}):
        with pytest.raises(ScopeError):
            api.export_schematic(str(svg), **kwargs)
    with pytest.raises(ScopeError, match="scale"):
        api.export_schematic(str(tmp_path / "bad.png"), nets=[{"path": ["top", "data"], "bit": 2}], scale=0)
    with pytest.raises(ScopeError, match="Cannot export"):
        api.export_schematic(str(tmp_path / "missing" / "bad.svg"), nets=[{"path": ["top", "data"], "bit": 2}])
    assert not svg.exists()
    assert schematic._viewer is None


def test_export_elaborated_hierarchical_cone(uart_session, tmp_path):
    import xml.etree.ElementTree as ET
    package = pytest.importorskip("naja_schematic")
    if not hasattr(package, "export_png"):
        pytest.skip("requires naja-schematic>=0.3.0")
    file = tmp_path / "busy.svg"
    api.export_schematic(str(file), traces=[{"path": ["uart_top", "u_tx", "tx_busy"]}],
                         view_options={"instance_label": "both"})
    root = ET.parse(file).getroot()
    boxes = [e for e in root.iter() if e.get("class") == "instance"]
    assert len(boxes) > 1  # cone expands logic and reaches its state registers
    assert all(e.get("data-path").startswith("u_tx/") for e in boxes)
    assert any("DFF" in e.get("data-model", "").upper() for e in boxes)
