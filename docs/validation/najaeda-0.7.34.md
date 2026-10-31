# Published najaeda 0.7.34 validation

Tested the PyPI macOS arm64 CPython 3.11 wheel, commit
`16d8d8b9343340245cd309d02d32626fd8a3b843`, against naja-scope's 0.1.22 candidate.
The extension is loaded from the installed wheel; no local native patches or
PYTHONPATH-selected experimental build is used.

- 131 regular tests pass, including optional schematic integration.
- The raw nested packed-write reproducer and snapshot round-trip are covered
  by prior checks; the CVA6 RV32 design now elaborates and writes a fresh
  schema 0.3.0 snapshot. A separate raw process reloads it successfully.
- All three unchanged CVA6 cone/hierarchy tests pass against the newly rebuilt
  0.7.34 snapshot (selected by a temporary pytest plugin).
- The full CVA6 default RV64 demo passes, including source and cone assertions.
- The complete CORE-V-MCU demo passes with the reviewed exact leaf count
  303,257; its sequential/model/blackbox/CDC assertions are unchanged.

## CVA6 revision check

Latest upstream release remains v5.3.0,
`2ef1c1b1fca419354920c5487293bc605294904e`. Tests use unmodified isolated
checkouts with pinned hpdcache, cvfpu and nested FPU submodules, preserving the
user's working checkout and published 0.7.33 baseline cache.

Default-branch commit remains `742dc82a0c706e0a3bfb98b709fd3ee06d50d12a`.
Retrying its `cv32a6_imac_sv32` configuration on the published wheel reports
only the MMU InvalidExpression at `core/cva6_mmu/cva6_mmu.sv:404`. The hpdcache
RHS call errors at lines 1212 and 1270 are resolved. Retain v5.3.0.

## New VHDL intent API

Raw `NLDB.loadVHDL(..., keep_ast_link=True)` followed by `intentAvailable`,
`intentTypeOf` and `intentDescribe` succeeds on a synthetic enum design.
The returned enum includes literal ordinals, representation, width, declaration
identity, library/architecture ownership and source coordinates. This confirms
engine availability only: naja-scope's VHDL intent integration is not implemented
or claimed by this candidate.

## Compatibility adaptation

The removed raw `default_timescale` keyword would break unmodified 0.1.21 SV
loads. The loader now uses an equivalent frontend file-list option. Tests cover
snapshot/intent reload, file lists without a top override and invalid tokens.
The same adaptation passed 131 tests on published 0.7.33 before the upgrade.
