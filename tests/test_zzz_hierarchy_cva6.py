# SPDX-License-Identifier: Apache-2.0
"""Top-level fan-out affordance regression on CVA6 (eval finding #4).

The lowered `cva6` top has thousands of direct children that are almost all
`assign` glue, drowning the 10 real submodules.
get_hierarchy must enumerate only the NON-ASSIGN children (real submodules +
leaf primitives) and report the assign glue as a count — so an agent can reach
all 10 submodules in one bounded call instead of paging through glue.

Built on snl.non_assign_child_nodes, which prefers naja's native
getNonAssignInstances() accessor with a getInstances()/isAssign() fallback.

Same gating/ordering rationale as test_zzz_cone_cva6 (resets the universe to
load CVA6, ~30s snapshot reload, runs last).
"""
import os
from collections import Counter

import pytest

from naja_scope import api

_SNAP = os.path.join(os.path.dirname(__file__), "..", "internal", "eval",
                     ".cache", "cva6-small", "snapshot")

pytestmark = pytest.mark.skipif(
    not os.path.isfile(os.path.join(_SNAP, "snl.mf")),
    reason="cva6-small snapshot absent; skipping slow regression")

# The 10 real submodules of the cva6 top, by model name. The cache subsystem
# model differs by config (cv32 = cva6_hpdcache_subsystem, cv64 =
# wt_cache_subsystem), so it is matched separately.
_STABLE_SUBMODULES = {
    "frontend", "id_stage", "issue_stage", "ex_stage", "commit_stage",
    "csr_regfile", "perf_counters", "controller", "cva6_rvfi_probes",
}


@pytest.fixture(scope="module")
def cva6_session():
    api.SESSION.reset()
    try:
        api.load_snapshot(_SNAP)
    except RuntimeError as exc:
        if "Incompatible SNL snapshot producer" in str(exc):
            pytest.skip(f"cva6-small snapshot is stale: {exc}")
        raise
    yield api.SESSION
    api.SESSION.reset()


def test_top_hierarchy_surfaces_all_submodules(cva6_session):
    out = api.get_hierarchy(depth=1, limit=100)
    root = out["root"]

    # Honest breakdown: glue counted, not dumped.
    assert root["assign_count"] > 1000           # the swamping glue
    # najaeda 0.7.33 shares four identical inverters at cva6.sv:1317 as
    # one. Raw snapshot comparison confirms all 10 submodules remain present.
    assert root["non_assign_total"] == 21        # 10 submodules + 11 leaves
    assert root["children_total"] == (
        root["assign_count"] + root["non_assign_total"])
    # 21 non-assign fits under limit=100 -> single bounded call, no glue shown.
    assert root["has_more"] is False
    assert len(root["children"]) == 21

    submodules = [c for c in root["children"] if not c.get("leaf")]
    leaves = [c for c in root["children"] if c.get("leaf")]
    assert len(submodules) == 10
    assert len(leaves) == 11
    assert Counter(c["model"] for c in leaves) == {
        "and_2": 5, "not_1": 4, "or_2": 1, "naja_mux2__w111": 1,
    }

    models = {c["model"] for c in submodules}
    assert _STABLE_SUBMODULES <= models
    assert any("cache_subsystem" in m for m in models)


def test_top_hierarchy_paginates_non_assign_set(cva6_session):
    # With a small limit the non-assign set itself paginates (cursor over the
    # 21 non-assign children, never over the thousands of assigns).
    first = api.get_hierarchy(depth=1, limit=20)
    root = first["root"]
    assert len(root["children"]) == 20
    assert root["has_more"] is True
    assert root["next_cursor"] == "20"

    second = api.get_hierarchy(depth=1, limit=20, cursor=root["next_cursor"])
    sroot = second["root"]
    assert len(sroot["children"]) == 1          # 21 - 20
    assert sroot["has_more"] is False

    # Union covers all 10 submodules across the two pages.
    names = {c["name"] for c in root["children"]}
    names |= {c["name"] for c in sroot["children"]}
    for inst in ("i_frontend", "id_stage_i", "issue_stage_i", "ex_stage_i",
                 "commit_stage_i", "csr_regfile_i", "controller_i"):
        assert inst in names
