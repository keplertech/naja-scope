# SPDX-License-Identifier: Apache-2.0
"""Literal hierarchical paths: one exact name per list element, plus a bit field."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from . import snl
from .errors import ResolveError, ScopeError
from .source_index import SrcRange

_MAX_SUGGESTION_SCAN = 2000


def validate_path(path: List[str]) -> List[str]:
    if not isinstance(path, list) or any(not isinstance(n, str) or not n for n in path):
        raise ScopeError("path must be a JSON list of non-empty exact names; string paths are not accepted.")
    return path


@dataclass
class Resolved:
    kind: str                  # "instance" | "term" | "net"
    obj: object                # snl.InstNode | raw SNL term/net (bit if selected)
    path: List[str]            # canonical exact names including top
    owner: snl.InstNode        # InstNode owning the term/net (or the parent)
    bit: Optional[int] = None  # explicit bit select, if any


def _safe(fn):
    try:
        return fn()
    except Exception:
        return None


def describe(resolved: Resolved, session=None) -> dict:
    """Compact descriptor dict for one resolved object."""
    out = {"kind": resolved.kind, "path": resolved.path, "bit": resolved.bit}
    obj = resolved.obj
    if resolved.kind == "instance":
        out["model"] = obj.model_name
        out["is_leaf"] = obj.is_leaf()
        if obj.is_leaf():
            out["is_sequential"] = _safe(obj.is_sequential)
        else:
            out["children"] = obj.child_count()
    elif resolved.kind == "term":
        out["dir"] = snl.direction_str(obj.getDirection())
        out["width"] = snl.obj_width(obj)
        role = snl.role_str(_safe(lambda: obj.getRole()))
        if role:
            out["role"] = role
    elif resolved.kind == "net":
        out["width"] = snl.obj_width(obj)
    src = source_ref(resolved, session)
    if src:
        out["src"] = src
    origins = [r.to_ref() for r in source_origins(resolved)[:MAX_ORIGINS]]
    if origins:
        out["origins"] = origins
    return out


def source_range(resolved: Resolved) -> Optional[SrcRange]:
    """SrcRange for a resolved object, straight from its SNL source refs."""
    if resolved.kind == "instance":
        loc = resolved.obj.source_loc()
    else:
        loc = snl.source_loc(resolved.obj)
        if loc is None and resolved.owner is not None:
            loc = resolved.owner.source_loc()
    return SrcRange.from_loc(loc) if loc else None


def source_ref(resolved: Resolved, session=None) -> Optional[str]:
    """`file:start-end` for a resolved object, straight from its SNL source refs."""
    rng = source_range(resolved)
    return rng.to_ref() if rng else None


# Cap on upstream origins listed per object (a Yosys src attribute can merge
# many RTL locations into one cell).
MAX_ORIGINS = 8


def source_origins(resolved: Resolved) -> List[SrcRange]:
    """Upstream source origins (e.g. Yosys src -> RTL) beyond source_range."""
    if resolved.kind == "instance":
        locs = resolved.obj.source_origins()
    else:
        locs = snl.source_origins(resolved.obj)
    return [SrcRange.from_loc(loc) for loc in locs]


def _level_names(node: snl.InstNode, cap: int = _MAX_SUGGESTION_SCAN):
    """(child names, term names, net names) visible at one hierarchy level."""
    children, terms, nets = [], [], []
    for inst in node.design.getInstances():
        children.append(snl.inst_segment(inst))
        if len(children) >= cap:
            break
    for term in node.design.getTerms():
        terms.append(term.getName())
        if len(terms) >= cap:
            break
    for net in node.design.getNets():
        name = net.getName()
        if name:  # anonymous nets have no addressable name
            nets.append(name)
        if len(nets) >= cap:
            break
    return children, terms, nets


def _suggest(segment: str, node: snl.InstNode) -> List[str]:
    import difflib
    children, terms, nets = _level_names(node)
    pool = list(dict.fromkeys(name for name in children + terms + nets if name))
    close = difflib.get_close_matches(segment, pool, n=8, cutoff=0.5)
    lowered = segment.lower()
    for name in pool:
        if lowered in name.lower() and name not in close:
            close.append(name)
        if len(close) >= 8:
            break
    return close[:8]


def resolve_path(session, path: List[str], kind: Optional[str] = None,
                 bit: Optional[int] = None) -> List[Resolved]:
    """Walk exact names, without parsing, unescaping, globbing or rejoining."""
    validate_path(path)
    if bit is not None and type(bit) is not int:
        raise ScopeError("bit must be an integer or null.")
    if kind not in (None, "instance", "term", "net"):
        raise ScopeError("kind must be instance, term or net.")
    session.require_top()
    node = snl.top_node()
    start = int(bool(path) and path[0] == node.name)
    if start == len(path):
        if bit is not None or kind not in (None, "instance"):
            raise ScopeError("The top is an instance and cannot have a bit select.")
        return [Resolved("instance", node, node.path, node)]
    for index in range(start, len(path)):
        name = path[index]
        last = index == len(path) - 1
        matches = []
        child = snl.child_node(node, name)
        if child is not None and bit is None:
            matches.append(Resolved("instance", child, child.path, node))
        if last:
            for obj_kind, getter, picker in (
                    ("term", node.design.getTerm, snl.term_bit),
                    ("net", node.design.getNet, snl.net_bit)):
                obj = getter(name)
                if obj is not None:
                    if bit is not None:
                        # Scalar names, including brackets, never imply bus bits.
                        if type(obj).__name__ not in ("SNLBusTerm", "SNLBusNet"):
                            continue
                        obj = picker(obj, bit)
                    if obj is not None:
                        matches.append(Resolved(obj_kind, obj, node.path + [name], node, bit))
            matches = [m for m in matches if kind is None or m.kind == kind]
            if matches:
                return matches
        elif child is not None:
            node = child
            continue
        raise ResolveError(path, index, node.path, _suggest(name, node))
