# Structured hierarchical paths — 2026-11-19

Validation uses published najaeda 0.7.35 (`c7ebdfc4f9f580684bf93998fcdc88e3009f2498`)
and the repository's `.venv`.

The standard local CVA6 cache was produced by 0.7.34 and is rejected by 0.7.35.
It was preserved. A fresh RV32 snapshot was built, saved and reloaded with
naja-scope's raw-API loader from the clean isolated CVA6 v5.3.0 checkout at
`2ef1c1b1fca419354920c5487293bc605294904e`, configuration
`cv32a6_imac_sv32`, using its pinned hpdcache and cvfpu revisions. The fresh
snapshot lives in a temporary directory; no baseline cache was replaced.

The CVA6 tests now accept `NAJA_SCOPE_CVA6_SNAPSHOT` to select such an isolated
snapshot. Their exact counts, pagination assertions, model histogram, and
cross-hierarchy cone assertions are retained, with path expectations converted
to lists.

```bash
NAJA_SCOPE_CVA6_SNAPSHOT=/path/to/fresh/snapshot .venv/bin/python -m pytest -q --tb=short
```

Final result: **207 passed, 0 failed, 0 skipped in 33.20 seconds**, including
all three CVA6 regressions. There are no failures to report.

The additional path regressions cover escaped Verilog names, a scalar whose
name contains brackets alongside a bus of the same base name, Yosys dollar
names, literal punctuation and spaces, dotted VHDL generate labels, ambiguous
single-name versus two-level paths, indexed errors and suggestions, output
round trips, rejected string input, nested schematic schemas, and anonymous
addresses colliding with literal names.

Both runnable bundled examples (`examples/walkthrough.py` and
`examples/gate_level.py`) pass. `git diff --check` passes.

Upstream CVA6 was rechecked through GitHub's API: latest release remains
v5.3.0, master remains `742dc82a0c706e0a3bfb98b709fd3ee06d50d12a`, and issue
#3594 remains open with two comments. The engine and upstream revisions are
unchanged from the recorded 0.7.35 validation, so master was not retried and
the demo pin remains v5.3.0. No engine upgrade or publication was performed. The follow-up 0.2.0
candidate updates runtime and MCP Registry versions for the breaking contract.
The 0.2.0 wheel and sdist build successfully and both pass `twine check`.
