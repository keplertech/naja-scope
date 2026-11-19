# SPDX-License-Identifier: Apache-2.0
"""Optional browser and headless rendering over the current raw naja universe."""
from __future__ import annotations

import atexit
import re
from pathlib import Path

from najaeda import naja

from . import snl
from .errors import ScopeError
from .resolve import resolve_path
from .runtime import DESIGN_LOCK, add_change_listener, serialized
from .session import SESSION

MAX_ANNOTATIONS = 200
_viewer = None


def _package():
    try:
        import naja_schematic
        # Import the required public entry points so older installations get
        # the same actionable error as a missing optional dependency.
        from naja_schematic import ViewerServer, export_svg, export_png
    except ImportError as exc:
        raise ScopeError('Schematic tools require naja-schematic>=0.3.0; '
                         'install "naja-scope[schematic]".') from exc
    return naja_schematic


def _options(options):
    if options is None:
        return None
    if not isinstance(options, dict):
        raise ScopeError("Schematic view_options must be an object.")
    _package()
    from naja_schematic.protocol import view_options
    try:
        view_options(options)
    except (ValueError, TypeError) as exc:
        raise ScopeError(str(exc)) from exc
    return options


def _resolve_one(path, kind, bit=None):
    matches = resolve_path(SESSION, path, kind=kind, bit=bit)
    if len(matches) != 1 or matches[0].kind != kind:
        raise ScopeError(f"Schematic target requires one {kind}.")
    return matches[0]


def _pin(path, bit=None):
    resolved = _resolve_one(path, "term", bit=bit)
    if resolved.bit is None and snl.obj_width(resolved.obj) != 1:
        raise ScopeError("Select one bus bit for a schematic net or trace.")
    # IDs preserve anonymous instances and names containing punctuation.
    # The terminal ID avoids a second name-based lookup upstream.
    bit = resolved.bit
    if bit is None and isinstance(resolved.obj, naja.SNLBusTerm):
        bit = resolved.obj.getMSB()
    return (list(resolved.owner.snlpath.getInstanceIDs()),
            resolved.obj.getID(), bit)


def _server():
    global _viewer
    if _viewer is None:
        ViewerServer = _package().ViewerServer
        # naja-schematic>=0.2 resolves relative source references (Show
        # Sources) against these roots; they are fixed at viewer creation.
        viewer = ViewerServer(lock=DESIGN_LOCK,
                              source_roots=tuple(SESSION.source_dirs))
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
def open_schematic(path=None, view_options=None):
    SESSION.require_top()
    options = _options(view_options)
    if path is None:
        node = SESSION.require_top()
    else:
        matches = resolve_path(SESSION, path, kind="instance")
        if len(matches) != 1:
            raise ScopeError("Schematic focus requires one instance.")
        node = matches[0].obj
    viewer = _server()
    if options is not None:
        viewer.view_options(options)
    viewer.show_instance(list(node.snlpath.getInstanceIDs()))
    return {"url": viewer.url, "path": node.path, "bit": None, "kind": "instance",
            "note": "Open this URL in a browser on the MCP server's machine."}


@serialized
def show_schematic_net(path, trace=False, add=True, color=None, bit=None):
    SESSION.require_top()
    pin = _pin(path, bit=bit)
    if type(trace) is not bool or type(add) is not bool:
        raise ScopeError("Schematic trace and add must be booleans.")
    if color is not None and (not isinstance(color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", color)):
        raise ScopeError("Schematic color must be #rrggbb.")
    try:
        viewer = _server()
        viewer.show_net(pin, trace=trace, add=add, color=color)
    except (ValueError, TypeError) as exc:
        raise ScopeError(str(exc)) from exc
    return {"url": viewer.url, "path": _resolve_one(path, "term", bit).path, "bit": bit, "kind": "term", "trace": trace}


@serialized
def export_schematic(file, instances=None, nets=None, traces=None,
                     view_options=None, scale=1.0):
    SESSION.require_top()
    if not isinstance(file, str) or not file:
        raise ScopeError("Provide a destination .svg or .png file.")
    destination = Path(file).expanduser().absolute()
    suffix = destination.suffix.lower()
    if suffix not in (".svg", ".png"):
        raise ScopeError("Schematic export file must end in .svg or .png.")
    groups = [group if group is not None else [] for group in (instances, nets, traces)]
    if any(not isinstance(group, list) for group in groups) or not 1 <= sum(map(len, groups)) <= 200:
        raise ScopeError("Provide lists containing 1 to 200 total instances, nets or traces.")
    insts = [_resolve_one(path, "instance").obj.snlpath for path in groups[0]]
    if any(not list(path.getInstanceIDs()) for path in insts):
        raise ScopeError("The top has no schematic box; export nets or traces on its ports.")
    def target(item):
        if not isinstance(item, dict) or set(item) - {"path", "bit"}:
            raise ScopeError("Net and trace targets must be objects with path and optional bit.")
        return _pin(item.get("path"), item.get("bit"))
    pins = [target(item) for item in groups[1]]
    cones = [target(item) for item in groups[2]]
    options = _options(view_options)
    package = _package()
    kwargs = dict(instances=insts, nets=pins, traces=cones, view_options=options,
                  source_roots=tuple(SESSION.source_dirs))
    try:
        if suffix == ".png":
            package.export_png(path=str(destination), scale=scale, **kwargs)
        else:
            package.export_svg(path=str(destination), **kwargs)
        size = destination.stat().st_size
    except (OSError, RuntimeError, ValueError, TypeError) as exc:
        raise ScopeError(f"Cannot export schematic: {exc}") from exc
    return {"file": str(destination), "format": suffix[1:],
            "bytes": size}


@serialized
def annotate_schematic(items):
    SESSION.require_top()
    if not isinstance(items, list) or len(items) > MAX_ANNOTATIONS:
        raise ScopeError(f"Provide at most {MAX_ANNOTATIONS} annotations.")
    annotations = []
    for item in items:
        if not isinstance(item, dict):
            raise ScopeError("Each annotation must be an object.")
        if set(item) - {"path", "bit", "kind", "severity", "message"}:
            raise ScopeError("Unknown annotation field; use path, bit, kind, severity and message.")
        kind = item.get("kind", "instance")
        if kind not in ("instance", "term"):
            raise ScopeError("Annotation kind must be instance or term (a pin/port).")
        path = item.get("path")
        matches = resolve_path(SESSION, path, kind=kind, bit=item.get("bit"))
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
            selection = {"kind": "instance", "path": node.path, "bit": None,
                         "model": node.model_name}
    return {"selection": selection, "url": _viewer.url if _viewer else None}
