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

As of 2026-10-18, the verified local regression baseline is CVA6 v5.3.0
(`2ef1c1b1fca419354920c5487293bc605294904e`), configuration
`cv32a6_imac_sv32`, with najaeda 0.7.30. All three tests in
`tests/test_zzz_cone_cva6.py` and `tests/test_zzz_hierarchy_cva6.py` pass
against its rebuilt snapshot (built from an isolated v5.3.0 checkout with
pinned submodules). The demo also pins v5.3.0 in `examples/_cva6_fetch.sh`;
its default `cv64a6_imafdc_sv39` configuration also elaborates with najaeda
0.7.30.

The latest upstream release remains v5.3.0. Upstream master
`81245a47fad8fe1a5d562d953ef2662e099def76` (unchanged since 2026-10-06) was
retried on 2026-10-18 in an isolated checkout with its pinned submodules and
najaeda 0.7.30. The `cv32a6_imac_sv32` raw-API elaboration still fails with
3 unsupported elements: the MMU's `always_comb`
condition contains an `InvalidExpression` at `core/cva6_mmu/cva6_mmu.sv:404`,
and two continuous assignments in hpdcache report unsupported RHS calls
(lines 1212 and 1270; lines 1196, 1204, 1268 and 1269 now pass). The related
upstream issue
[CVA6 #3594](https://github.com/openhwfoundation/cva6/issues/3594), covering
the reversed Sv32 part-select, remains open (two comments; the contributor
reports a local fix and passing Slang elaboration for Sv32 and two RV64
configurations, with formatting and final review pending before PR
submission). Retain the working baseline, and check the issue status and
retry newer revisions on the next upgrade rather than assuming these
limitations remain.

Test candidate revisions in an isolated checkout with their pinned
submodules, preserving the user's working checkout. Elaborate through the
raw naja API, rebuild and reload the snapshot, and run all three regressions
without weakening their assertions. Before changing the shared demo pin,
also validate its default `cv64a6_imafdc_sv39` configuration. Promote a newer
revision only after these checks pass; record its exact commit and najaeda
version. Otherwise retain the working baseline and record the remaining
failure and date of the check.

### 2026-10-27 recheck with najaeda 0.7.32

Latest CVA6 release is still v5.3.0
(`2ef1c1b1fca419354920c5487293bc605294904e`). Its default demo configuration
`cv64a6_imafdc_sv39` elaborates with 0.7.32, but `cv32a6_imac_sv32` now fails
at hpdcache `rtl/src/common/hpdcache_data_upsize.sv:154`: unsupported dynamic
sequential assignment LHS (`buf_q[wrptr_q][words_q[wrptr_q]] <= wdata_i`).
An isolated raw-API reproducer in `ci/repro_dynamic_packed_write.py`
passes with 0.7.30 and fails with 0.7.32. The 0.7.30 baseline snapshot was
preserved; 0.7.32 rejects its schema 0.2.0 (expects 0.3.0), so all three
unchanged CVA6 regression tests error at reload and cannot yet be reverified.

Current upstream master `742dc82a0c706e0a3bfb98b709fd3ee06d50d12a` was retried
with its pinned submodules and 0.7.32 in a separate checkout. It has four
unsupported elements: the existing MMU `InvalidExpression` at line 404, the
two hpdcache RHS calls at lines 1212 and 1270, and the same dynamic sequential
write at `hpdcache_data_upsize.sv:162`. CVA6 #3594 remains open with two
comments. Retain v5.3.0 and the last verified 0.7.30 baseline; naja-scope
0.1.21 is a candidate blocked from publication pending the engine fix and a
successful snapshot rebuild/reload plus all three regressions. See
`docs/releases/0.1.21.md`. Do not work around this by blackboxing the module
or weakening regression assertions.

### 2026-10-28 recheck with published najaeda 0.7.33

Najaeda 0.7.33 (`64164ffe27c27168f58c4fa8363cc77b4d99af2b`, upstream #501)
fixes the nested dynamic packed write. CVA6 v5.3.0
(`2ef1c1b1fca419354920c5487293bc605294904e`) `cv32a6_imac_sv32` now elaborates,
saves and reloads a fresh schema 0.3.0 snapshot using the published wheel,
without local engine patches or RTL changes. The raw synthetic reproducer
and a dependent-index/canonical-DB0 snapshot check also pass. The demo's
`cv64a6_imafdc_sv39` configuration elaborates successfully.

The new hierarchy has 21 non-assign children: all ten submodules and eleven
leaves. Comparison against the preserved 0.7.30 snapshot verifies that four
inverters of the same input bit at `cva6.sv:1317` are now shared as one.
The hierarchy tests retain exact counts and pagination assertions, updated
for this lowering change, and additionally check the exact leaf-model
histogram. The cross-hierarchy cone assertions are unchanged. All three
CVA6 regressions pass against this rebuilt cache; the other 127 tests pass
as well, including schematic integration.

The latest upstream release is still v5.3.0. Default-branch commit
`742dc82a0c706e0a3bfb98b709fd3ee06d50d12a` was retried with its pinned
submodules and 0.7.33: three issues remain (MMU InvalidExpression at line
404, hpdcache RHS calls at lines 1212 and 1270). CVA6 #3594 remains open
with two comments. Retain v5.3.0; retry newer revisions on the next upgrade.
Snapshot schema evolution is expected: regenerate snapshots rather than
requiring backward compatibility. Keep 0.1.21 unpublished until a release
is explicitly requested. See `docs/releases/0.1.21.md` for validation details.
