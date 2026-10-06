# naja-scope

## Always use the low-level naja Python API, never najaeda's high-level API

When writing code that talks to najaeda — inside `src/naja_scope/` or in
throwaway exploration scripts — always go through `from najaeda import naja`
(the raw `naja.so` binding: `NLUniverse`, `NLDB`, `SNL*` objects) and never
through `najaeda.netlist` (the high-level `load_verilog`/`load_system_verilog`/
`Instance`/`Term` wrapper).

**Why:** `src/naja_scope/loader.py` is deliberately built this way already —
see its module docstring: "driven directly through the raw `naja` DB/universe
API ... rather than the high-level najaeda.netlist loaders. This keeps
naja-scope on the raw layer end to end." The high-level API is a convenience
wrapper that can lag, rename, or diverge from the raw layer (e.g. the
`allow_unknown_designs` -> `blackbox_unknown_modules` rename in najaeda 0.7.11
broke the raw `NLDB.loadVerilog` binding's kwarg, independent of whatever the
`najaeda.netlist` wrapper did to stay compatible). Exploring or prototyping
against the high-level API produces findings that don't reflect what
naja-scope itself does at runtime.

**How to apply:** For any one-off inspection (checking pin roles, instance
types, hierarchy, etc.), use `naja.NLUniverse` / `naja.NLDB` /
`naja.SNL*` objects directly, the same way `loader.py`, `session.py`, and
`api.py` do. Do not import or call `najaeda.netlist.*` even for quick
throwaway scripts.

## Regularly recheck the latest CVA6 revision

When upgrading najaeda, preparing a naja-scope release, or maintaining the
CVA6 regressions, check the latest upstream CVA6 release and default-branch
revision to see whether the pinned baseline can be updated. Do not leave
CVA6 pinned indefinitely without retrying newer revisions.

As of 2026-10-06, the verified local regression baseline is CVA6 v5.3.0
(`2ef1c1b1fca419354920c5487293bc605294904e`), configuration
`cv32a6_imac_sv32`, with najaeda 0.7.27. All three tests in
`tests/test_zzz_cone_cva6.py` and `tests/test_zzz_hierarchy_cva6.py` pass
against its rebuilt snapshot. The demo also pins v5.3.0 in
`examples/_cva6_fetch.sh`; its default `cv64a6_imafdc_sv39` demo also passes
with najaeda 0.7.27.

The latest upstream release remains v5.3.0. Upstream master
`81245a47fad8fe1a5d562d953ef2662e099def76` was retried on 2026-10-06 in an
isolated checkout with its pinned submodules and najaeda 0.7.27. The
`cv32a6_imac_sv32` raw-API elaboration still fails: the MMU's `always_comb`
condition contains an `InvalidExpression` at `core/cva6_mmu/cva6_mmu.sv:404`,
and six continuous assignments in hpdcache report unsupported RHS calls
(lines 1196, 1204, 1212, 1268, 1269, 1270). The related upstream issue
[CVA6 #3594](https://github.com/openhwfoundation/cva6/issues/3594), covering
the reversed Sv32 part-select, remains open with no comments. Retain the
working baseline, and check the issue status and retry newer revisions on
the next upgrade rather than assuming these limitations remain.

Test candidate revisions in an isolated checkout with their pinned
submodules, preserving the user's working checkout. Elaborate through the
raw naja API, rebuild and reload the snapshot, and run all three regressions
without weakening their assertions. Before changing the shared demo pin,
also validate its default `cv64a6_imafdc_sv39` configuration. Promote a newer
revision only after these checks pass; record its exact commit and najaeda
version. Otherwise retain the working baseline and record the remaining
failure and date of the check.
