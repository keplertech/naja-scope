# SPDX-License-Identifier: Apache-2.0
"""Cone tracing on top of naja's native `LogicCone`.

`LogicCone(seed_occurrence, FanIn|FanOut)` builds, in C++, the rooted DAG
of combinational logic between the seed bit and the surrounding sequential /
port / black-box barriers, crossing hierarchy and following combinatorial arcs
only. naja-scope no longer hand-rolls the equipotential BFS; it seeds the cone,
then turns the DAG into a token-bounded summary:

* `getNodeCount()` / `getNodes()` kinds  -> size + counts_by_kind,
* `getLeaves()`                             -> the stop-at-flops frontier
  (flops, top ports, opaque black boxes), categorised and bounded,
* the flop frontier grouped by top-level submodule, naming the registers that
  lie OUTSIDE the cone root's own subtree -> the cross-hierarchy answer.

Token-bounding here is a correctness requirement: counts
are always exact, but every materialised list is capped with a truncation
marker — never a full node/edge dump.

The native cone is intrinsically stop-at-flops (a flop's D->Q is not a
combinatorial arc), so there is no `stop=none` mode and no traversal cap; size
bounding is the caller's job and lives here.
"""

from __future__ import annotations

from typing import Dict, List

from najaeda import naja

from . import snl
from .errors import ScopeError
from .resolve import Resolved
from .source_index import SrcRange

DEFAULT_MAX_FRONTIER = 50
HARD_MAX_FRONTIER = 200

_DIRECTIONS = {
    "fanin": naja.LogicCone.FanIn,
    "fanout": naja.LogicCone.FanOut,
}
# getLeaves() kinds that are barriers, by category.
_LEAF_KINDS = {"flop", "ports", "blackbox"}


def _bits_of(resolved: Resolved) -> List:
    if resolved.kind in ("term", "net"):
        return snl.obj_bits(resolved.obj)
    raise ScopeError(f"'{resolved.path}' is an instance; trace_cone expects a "
                     "term or net.")


def _subtree_key(path):
    return tuple(path[:2] if len(path) >= 3 else path[:1])


def _port_label(netcomp):
    return (snl.top_design().getName(), netcomp.getName(),
            netcomp.getBit() if type(netcomp).__name__ == "SNLBusTermBit" else None)


def _leaf_record(inst, ids) -> dict:
    entry = {"path": snl.path_from_ids(ids), "kind": "instance", "bit": None,
             "label": snl.friendly_label(inst),
             "model": inst.getModel().getName()}
    loc = snl.source_loc(inst)
    if loc:
        entry["src"] = SrcRange.from_loc(loc).to_ref()
    return entry


def _cross_hierarchy(root_path, flops):
    root_subtree = _subtree_key(root_path)
    groups = {}
    for rec in flops.values():
        key = _subtree_key(rec["path"])
        bucket = groups.setdefault(key, {"path": list(key), "count": 0, "examples": []})
        bucket["count"] += 1
        if len(bucket["examples"]) < 3:
            bucket["examples"].append(rec["path"])
    outside = [v for k, v in groups.items() if k != root_subtree]
    return {
        "root_subtree": list(root_subtree),
        "by_subtree": sorted(groups.values(), key=lambda v: -v["count"])[:20],
        "outside_root_subtree": {
            "count": sum(v["count"] for v in outside),
            "subtrees": sorted(v["path"] for v in outside),
            "examples": [p for v in outside for p in v["examples"]][:10],
        },
    }


def trace_cone(resolved: Resolved, session, direction: str,
               max_frontier: int = DEFAULT_MAX_FRONTIER) -> dict:
    if direction not in _DIRECTIONS:
        raise ScopeError("direction must be 'fanin' or 'fanout'.")
    max_frontier = max(1, min(max_frontier, HARD_MAX_FRONTIER))
    cone_dir = _DIRECTIONS[direction]

    bits = _bits_of(resolved)
    node_count = 0
    counts_by_kind: Dict[str, int] = {}
    counts_by_model: Dict[str, int] = {}
    # Frontier deduped across seed bits by identity (path / port label).
    flops: Dict[str, dict] = {}
    blackboxes: Dict[str, dict] = {}
    ports: Dict[str, dict] = {}

    for bit in bits:
        occ = snl.seed_occurrence(resolved.kind, resolved.owner, bit)
        if occ is None:
            continue
        cone = naja.LogicCone(occ, cone_dir)
        node_count += cone.getNodeCount()
        for (_id, _occ, kind, _nx, _pv) in cone.getNodes():
            counts_by_kind[kind] = counts_by_kind.get(kind, 0) + 1
        for (_id, leaf_occ, kind, _nx, _pv) in cone.getLeaves():
            if kind == "ports":
                nc = leaf_occ.getNetComponent()
                if nc is None:
                    continue
                label = _port_label(nc)
                ports.setdefault(label, {"port": list(label[:2]), "path": list(label[:2]), "bit": label[2], "kind": "term"})
                continue
            inst, ids = snl.occurrence_leaf(leaf_occ)
            if inst is None:
                continue
            rec = _leaf_record(inst, ids)
            if kind == "flop":
                if tuple(rec["path"]) not in flops:
                    flops[tuple(rec["path"])] = rec
                    counts_by_model[rec["model"]] = (
                        counts_by_model.get(rec["model"], 0) + 1)
            else:  # blackbox (opaque leaf cell) or any other un-crossed leaf
                blackboxes.setdefault(tuple(rec["path"]), rec)

    flop_list = sorted(flops.values(), key=lambda r: r["path"])
    bb_list = sorted(blackboxes.values(), key=lambda r: r["path"])
    port_list = sorted(ports.values(), key=lambda r: r["port"])
    frontier_truncated = (len(flop_list) > max_frontier
                          or len(bb_list) > max_frontier
                          or len(port_list) > max_frontier)

    out = {
        "root": resolved.path, "bit": resolved.bit, "kind": resolved.kind,
        "direction": direction,
        "stop": "flops",  # native cone always stops at flops/ports/black boxes
        "seed_bits": len(bits),
        "node_count": node_count,
        "node_count_summed_over_bits": len(bits) > 1,
        "counts_by_kind": dict(
            sorted(counts_by_kind.items(), key=lambda kv: -kv[1])),
        "frontier": {
            "flop_count": len(flop_list),
            "port_count": len(port_list),
            "blackbox_count": len(bb_list),
            "flops": flop_list[:max_frontier],
            "ports": port_list[:max_frontier],
            "blackboxes": bb_list[:max_frontier],
            "truncated": frontier_truncated,
        },
        "counts_by_model": dict(
            sorted(counts_by_model.items(), key=lambda kv: -kv[1])[:20]),
        "cross_hierarchy": _cross_hierarchy(resolved.path, flops),
        "truncated": frontier_truncated,
    }
    return out
