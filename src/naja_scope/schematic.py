# SPDX-License-Identifier: Apache-2.0
"""Thin optional integration with naja-schematic's public ViewerServer API."""
from __future__ import annotations

import atexit

from . import snl
from .errors import ScopeError
from .resolve import resolve_path
from .runtime import DESIGN_LOCK, add_change_listener, serialized
from .session import SESSION

MAX_ANNOTATIONS = 200
_viewer = None


def _server():
    global _viewer
    if _viewer is None:
        try:
            from naja_schematic import ViewerServer
        except ImportError as exc:
            raise ScopeError('Schematic tools require naja-schematic>=0.1.6; '
                             'install "naja-scope[schematic]".') from exc
        viewer = ViewerServer(lock=DESIGN_LOCK)
        try:
            viewer.start()
        except (OSError, RuntimeError) as exc:
            viewer.stop()
            raise ScopeError(f"Cannot start schematic viewer: {exc}") from exc
        _viewer = viewer
    return _viewer


def _changed():
    if _viewer is not None:
        _viewer.design_changed()


def close():
    """Stop the optional server. Call outside the design lock at shutdown."""
    global _viewer
    with DESIGN_LOCK:
        viewer, _viewer = _viewer, None
    if viewer is not None:
        viewer.stop()


add_change_listener(_changed)
atexit.register(close)


@serialized
def open_schematic(path=None):
    SESSION.require_top()
    if path is None:
        node = SESSION.require_top()
    else:
        matches = resolve_path(SESSION, path, kind="instance")
        if len(matches) != 1:
            raise ScopeError("Schematic focus requires one instance.")
        node = matches[0].obj
    viewer = _server()
    viewer.show_instance(list(node.snlpath.getInstanceIDs()))
    return {"url": viewer.url, "path": node.path,
            "note": "Open this URL in a browser on the MCP server's machine."}


@serialized
def annotate_schematic(items):
    SESSION.require_top()
    if not isinstance(items, list) or len(items) > MAX_ANNOTATIONS:
        raise ScopeError(f"Provide at most {MAX_ANNOTATIONS} annotations.")
    annotations = []
    for item in items:
        if not isinstance(item, dict):
            raise ScopeError("Each annotation must be an object.")
        kind = item.get("kind", "instance")
        if kind not in ("instance", "term"):
            raise ScopeError("Annotation kind must be instance or term (a pin/port).")
        path = item.get("path")
        if not isinstance(path, str):
            raise ScopeError("Annotation path must be a naja-scope path string.")
        matches = resolve_path(SESSION, path, kind=kind)
        if len(matches) != 1 or matches[0].kind != kind:
            raise ScopeError("Each annotation must resolve to one object of the requested kind.")
        resolved = matches[0]
        if resolved.bit is not None:
            raise ScopeError("Viewer annotations apply to a whole pin/port; omit the bit select.")
        node = resolved.obj if kind == "instance" else resolved.owner
        severity = item.get("severity", "info")
        if severity not in ("info", "warning", "error"):
            raise ScopeError("Annotation severity must be info, warning or error.")
        message = item.get("message", "")
        if not isinstance(message, str) or len(message) > 2000:
            raise ScopeError("Annotation message must be text of at most 2000 characters.")
        out = {"kind": "instance" if kind == "instance" else "net",
               "id_path": list(node.snlpath.getInstanceIDs()),
               "severity": severity, "message": message, "source": "naja-scope"}
        if kind == "term":
            out["terminal"] = resolved.obj.getName()
        annotations.append(out)
    viewer = _server()
    viewer.annotate(annotations)
    return {"url": viewer.url, "count": len(annotations)}


@serialized
def get_schematic_selection():
    selection = None
    ids = _viewer.selected_id_path if _viewer is not None else None
    if ids is not None and SESSION.has_top():
        # Validate before constructing a raw SNLPath: UI messages can be stale
        # or malformed. Never use ViewerServer.selected (high-level wrapper).
        ids = list(ids)
        design = snl.top_design()
        for value in ids:
            if type(value) is not int or not 0 <= value < 2**32:
                break
            inst = design.getInstanceByID(value)
            if inst is None:
                break
            design = inst.getModel()
        else:
            node = snl.node_from_ids(ids)
            selection = {"kind": "instance", "path": node.path,
                         "model": node.model_name}
    return {"selection": selection, "url": _viewer.url if _viewer else None}
