# Latest naja reevaluation — 2026-10-31

Evaluated clean upstream naja main commit
`52620d2012be118c28cafd6089400984b5c3e674` (VHDL RAM initialization, #509)
against naja-scope 0.1.21. This is an unreleased revision beyond tag v0.7.33;
the engine still reports version 0.7.33, with git hash `52620d20`.

A clean isolated CMake Release build used the revision's pinned submodules,
Python 3.11 and macOS arm64. The extension was selected explicitly through
PYTHONPATH, without replacing the published wheel or including local naja
checkout modifications. No C++ engine patch was applied.

## Compatibility finding and proposed naja-scope change

Upstream removed the raw `NLDB.loadSystemVerilog(default_timescale=...)`
keyword in favor of `frontend_options`. Naja-scope passed the removed keyword
on every SystemVerilog load, including when it was None. Before adaptation,
the non-CVA6 suite had 11 failures and 65 setup errors.

The proposed loader change passes the existing public `default_timescale`
setting as `--timescale=...` in the temporary frontend file list instead.
This retains the naja-scope Python/MCP API and snapshot/intent metadata and
works on both published 0.7.33 and latest main. Added coverage checks a file
list without an explicit top, and rejects invalid/injected file-list tokens.

## Results after adaptation

- **131 non-CVA6 tests pass** on latest naja, including schematic integration.
- **131 non-CVA6 tests pass** on published najaeda 0.7.33 as a compatibility check.
- **All three unchanged CVA6 tests pass** against a newly built/reloaded latest-
  naja snapshot. A temporary pytest plugin selects the isolated cache; the
  active published-wheel snapshot is preserved and assertions are unmodified.
- The nested packed-write raw reproducer elaborates and round-trips a snapshot.
- The complete CVA6 RV64 demo passes, including its zero-blackbox cone checks.

## CVA6 baseline and latest master

The latest upstream release remains v5.3.0, commit
`2ef1c1b1fca419354920c5487293bc605294904e`. Its `cv32a6_imac_sv32` configuration
elaborates, saves and reloads a fresh snapshot; `cv64a6_imafdc_sv39` passes the
complete demo. Both use an unmodified isolated checkout with pinned submodules.

Default-branch commit remains `742dc82a0c706e0a3bfb98b709fd3ee06d50d12a`.
Retrying unmodified `cv32a6_imac_sv32` with its pinned submodules now reports
**one** unsupported element: MMU InvalidExpression in the always_comb condition
at `core/cva6_mmu/cva6_mmu.sv:404` (block starts at line 380).
The hpdcache RHS call failures at lines 1212 and 1270 are gone.
[CVA6 #3594](https://github.com/openhwfoundation/cva6/issues/3594) remains open
with two comments. Retain the working v5.3.0 baseline.

## CORE-V-MCU fingerprint drift

Pinned CORE-V-MCU commit `4608714d3f6c2a2e67141b03a7aeb24ccdb3f73d` loads
successfully from identical FuseSoC-resolved inputs, but the complete demo
fails its 0.7.33 exact leaf-count assertion:

| Metric | Published 0.7.33 | Latest naja |
| --- | ---: | ---: |
| Flattened leaf instances | 285,546 | 303,257 |
| Sequential instances | 6,501 | 6,501 |
| Hierarchical module variants | 320 | 320 |
| Expected blackboxes | 12 | 12 |
| CDC clock endpoints | 1,705 | 1,705 |

Raw enumeration independently reproduces the latest count. All module names,
hierarchical child-model multiplicities and per-module sequential counts match.
The largest primitive changes are OR2 (62,117 to 103,621), scalar mux2
(29,491 to 11,845) and 16-bit mux2 (3,068 to 844), consistent with upstream
function-lowering/mux changes. This structural comparison is not a formal
whole-design equivalence proof. The demo assertion remains unchanged during
this reevaluation; review and update its exact fingerprint for the next released
engine after acceptance of the changed lowering.

## Publication assessment

The two hpdcache naja limitations are resolved on tested main. Naja-scope needs
the loader adaptation before the next najaeda release reaches its unbounded
`najaeda>=0.7.33` dependency. CORE-V-MCU's exact-count demo also needs a reviewed
fingerprint update for that release. No dependency floor/version bump, tag,
commit, push or publication was performed. Validation covers this macOS CMake
build, not unreleased wheels, other platforms, Bazel or BCR delivery.
