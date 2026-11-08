# Published najaeda 0.7.35 validation — 2026-11-08

Test environment: macOS arm64, CPython 3.11, published PyPI wheel, raw binding
at `.venv/lib/python3.11/site-packages/najaeda/naja.so`, engine commit
`c7ebdfc4f9f580684bf93998fcdc88e3009f2498`. No local engine patches or
experimental PYTHONPATH override. naja-scope candidate: 0.1.24.

## Compatibility and regressions

- The complete local suite passes **155 tests, none skipped**, in 29.0 s,
  including schematic integration and all three CVA6 regressions.
- The raw `ci/repro_dynamic_packed_write.py` elaborates and saves/reloads a fresh
  snapshot.
- CVA6 release v5.3.0 (`2ef1c1b1fca419354920c5487293bc605294904e`),
  `cv32a6_imac_sv32`, elaborates through naja-scope's raw loader, saves a fresh
  snapshot and reloads it after destroying the universe. The top content hash
  is identical before/after reload:
  `bbf4a815dd648598c3b302efb1036044975a27b74679ea197f2fa947af63ef21`
  (content format 1). Elaboration took 14.4 s; elaboration, hashing, save,
  reload and second hash took 42.5 s in this run.
- The isolated release checkout is
  `internal/eval/.cache/cva6-small/src-v5.3.0`, verified clean at the release
  commit, with pinned hpdcache `04de808`, cvfpu `3116391` and nested FPU
  `86e1f55`. The fresh snapshot is at
  `/tmp/naja-scope-024-validation/rv32-snapshot`; all prior caches were retained.
- All three original CVA6 cone/hierarchy regressions use this fresh snapshot
  through a temporary collection plugin overriding only `_SNAP`. No assertions
  or expected counts changed.
- Complete `examples/cva6_demo.py` at default `cv64a6_imafdc_sv39` and
  `examples/core_v_mcu_demo.py` pass with unchanged assertions, including
  CORE-V-MCU's 303,257 leaves and sequential/model/blackbox/CDC checks.
- `examples/walkthrough.py` and `examples/gate_level.py` pass.
- Wheel and sdist build successfully and pass `twine check`. An isolated
  target installation of the wheel loads UART, calls the new MCP query, and
  checks tool registration. Package/registry versions and the minimum engine
  dependency agree; the sdist includes release notes and the new tests.
  Artifacts: `dist/naja_scope-0.1.24-py3-none-any.whl` and
  `dist/naja_scope-0.1.24.tar.gz`.

Full test command (the plugin only selects the temporary fresh snapshot):

```sh
PYTHONPATH=/tmp/naja-scope-024-validation:src .venv/bin/python -m pytest -q -p fresh_cva6
```

Schematic tests require localhost binding, disallowed in the default sandbox;
the complete suite was run with that permission. Logs and temporary validation
scripts are under `/tmp/naja-scope-024-validation/`.

## CVA6 revision recheck

GitHub's latest release is still v5.3.0. Master is unchanged at
`742dc82a0c706e0a3bfb98b709fd3ee06d50d12a`.
[CVA6 #3594](https://github.com/openhwfoundation/cva6/issues/3594) remains open
with two comments. Master was retried in a fresh isolated checkout with pinned
hpdcache `e8f072e`, cvfpu `3eb6afe` and nested FPU `86e1f55`.
Its RV32 elaboration still reports exactly one unsupported element: the MMU
`always_comb` condition contains an `InvalidExpression` at
`core/cva6_mmu/cva6_mmu.sv:404`. Retain the working release pin.

## New capabilities worth using

Compared with 0.7.34, the wheel contains upstream
[#514](https://github.com/najaeda/naja/pull/514) through the timing/reset
updates in [#523](https://github.com/najaeda/naja/pull/523).
See the authoritative
[raw reference at the release commit](https://github.com/najaeda/naja/blob/c7ebdfc4f9f580684bf93998fcdc88e3009f2498/src/najaeda/najaeda/docs/source/raw_api.rst).

### Used now: native content hashing

`get_content_hash(module=None)` is an explicit read-only tool. It returns the
model name, `content_hash`, `algorithm`, `format_version`, and `naja_git_hash`.
No extra Python dependency, high-level wrapper or persistent cache is used.
Tests cover descendant wiring changes propagating to the parent, restoration,
snapshot persistence, top/named model selection, errors and MCP registration.

The engine hash preserves IDs and names. Source metadata and primitive
definitions (including truth tables and sequential/timing models) are excluded;
primitive identity and instance connections/overrides participate. Equal hashes
do not establish HDL equivalence or identical primitive semantics across engine
versions. The explicit query keeps potentially expensive hierarchy hashing out
of routine cards and status calls.

### Next: constrained clock/reset-domain exploration

The raw API provides `NLClock` declarations and generated clocks,
`SNLDesign.analyzeTiming()`, `getClockDomains()`, `getEndpoints(check=...)`,
coverage/diagnostics, and occurrence `getLaunchClocks()`, `getCaptureClocks()`,
`getClocks()`, `getFaninStartpoints()` and `getFanoutEndpoints()`. It includes
clock-gate/mux handling and split inout support.

`NLReset.create(...)` and `getResetDomains()` add explicit reset constraints,
physical reset propagation and reset metadata in cone records. Six selected
upstream raw tests pass against the installed published wheel: crossing
endpoints, synchronous reset synchronizer depth, bitwise vector reset handling,
reset-domain crossing, reset synchronizer, and removing declarations/restoring
original query behavior. These checks use the source tests in
`test/nl/python/naja_wrapping/test_timing_analysis.py`, bound to the wheel's raw
module; they do not use a local native build.

This verifies that declared resets address the scalar/vector reset-mux problem
reported in the [2026-11-06 evaluation](tgraph-latest-naja-2026-11-06.md).
It does not constitute a rerun of the full svgap witness collection or large
design timing benchmarks.

A future naja-scope timing interface should accept explicit clock/reset
constraints, surface uncovered endpoints and cycle diagnostics, page summaries,
and request cell sets only for selected cones. Never infer constraints from
port-name guesses. Netlist/constraint changes invalidate timing analysis.
Related generated clocks require a deliberate crossing policy; structural
analysis alone cannot prove Gray-code or handshake correctness. The previous
large-design `withCells=True` evaluation reached 74–85 GB; that workload has
not been remeasured on 0.7.35, so automatic full-cone enumeration is deferred.

No commit, push, tag, or publication was performed.
