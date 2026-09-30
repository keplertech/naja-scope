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
        leaf = naja.SNLDesign.create(lib, "leaf")
        naja.SNLScalarTerm.create(leaf, naja.SNLTerm.Direction.Input, "A")
        named = naja.SNLInstance.create(top, leaf, "named")
        anonymous = naja.SNLInstance.create(top, leaf)
        another = naja.SNLInstance.create(top, leaf)
        u.setTopDB(db)
        u.setTopDesign(top)
        ids = named.getID(), anonymous.getID(), another.getID()
    yield ids
    schematic.close()
    SESSION.reset()


@pytest.fixture
def viewer(design):
    package = pytest.importorskip("naja_schematic")
    if not hasattr(package, "ViewerServer"):
        pytest.skip("requires naja-schematic>=0.1.6")
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
    path = f"top.#{anonymous}"
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
        assert api.get_schematic_selection()["selection"]["path"] == f"top.#{another}"
        api.annotate_schematic([{"path": path, "message": "check this", "severity": "warning"},
                               {"path": path + ".A", "kind": "term", "message": "input"}])
        diagnosis = receive(ws, "diagnosis_response")
        assert diagnosis["items"][0]["id_path"] == [anonymous]
        assert diagnosis["items"][1]["terminal"] == "A"
        api.annotate_schematic([])
        assert receive(ws, "diagnosis_response")["items"] == []
        api.reset_universe()
        receive(ws, "design_changed")
        assert api.get_schematic_selection()["selection"] is None


def test_snapshot_reload_and_shutdown(viewer, tmp_path):
    opened = api.open_schematic("top.named")
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
        assert api.open_schematic("top.named")["url"] == opened["url"]
        assert receive(ws, "focus_instance")["id_path"] == [viewer[0]]
    server = schematic._viewer
    schematic.close()
    assert not server.running


def test_validation_does_not_start_viewer(design):
    for items in ([{"path": "top.missing"}], [{"path": "top.named", "severity": "bad"}],
                  [{"path": "top.named", "message": "a" * 2001}], [{}] * 201):
        with pytest.raises(ScopeError):
            api.annotate_schematic(items)
    assert schematic._viewer is None


def test_mcp_tools_registered():
    import asyncio
    from naja_scope import server
    tools = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
    assert {"open_schematic", "annotate_schematic", "get_schematic_selection"} <= tools.keys()
    assert tools["get_schematic_selection"].annotations.readOnlyHint


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
        assert api.get_schematic_selection()["selection"]["path"] == "top.named"
