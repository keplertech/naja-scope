# naja-schematic 0.3.0 integration — 2026-11-15

Validated with the published macOS universal2 naja-schematic 0.3.0 wheel,
Python 3.11 and the existing published najaeda 0.7.35. Upstream HEAD and the
v0.3.0 tag both resolve to `3beb9558c6dca3cee1ab1d36c3951de7e01ae1eb`.
The project virtualenv's optional viewer was upgraded from 0.2.0 with
`pip install --no-deps naja-schematic==0.3.0`; najaeda was unchanged.

The schematic extra now requires `naja-schematic>=0.3.0,<0.4`. New MCP/Python
entry points:

- `show_schematic_net`: one pin/port's net or combinational fan-in cone,
  optional trace color, add or replace drawing.
- `export_schematic`: headless SVG/PNG from explicit instance, net and
  fan-in targets; returns the file location and size. PNG scale and export
  decorations are supported. Browser state is independent.
- `open_schematic` additionally accepts upstream drawing options, including
  model labels and fanout grouping by role.

Targets use the existing scope resolver, raw SNL paths, numeric instance
and terminal IDs. All design access, including native renderer protocol
callbacks, remains under `DESIGN_LOCK`. No high-level najaeda loaders or
wrappers were introduced. Optional imports remain lazy.

Validation exercises the real HTTP/WebSocket protocol and bundled native
renderer: anonymous IDs, top-level bus bits, single-bit buses with nonzero
index, options and trace replay, stale selection rejection, snapshot reload,
lock serialization, invalid input, and filesystem failures. Exported SVG
structure and PNG headers/dimensions are checked. A loaded SystemVerilog UART
fan-in export crosses into `u_tx` and contains both logic and state-register
boxes. The simple exported PNG was visually inspected.

The full suite passes with 174 tests passed and 3 skipped. The three unchanged
CVA6 tests skip because the local cache was produced by najaeda 0.7.34
(`16d8d8b`), while the reader is 0.7.35 (`c7ebdfc`). This is not a successful
CVA6 revalidation; the cache was preserved. Neither najaeda nor the CVA6
baseline was upgraded by this integration.

Release-candidate follow-up: the compatible isolated snapshot from the
0.1.25 validation was located at
`/tmp/naja-scope-025-validation/rv32-snapshot`. With its existing
`fresh_cva6` pytest collection plugin, the complete 0.1.26 suite passes
**177 tests, none skipped**, including all three unchanged CVA6 regressions.
The shared cache is still preserved. Package and MCP versions are bumped to
0.1.26. Wheel and sdist build successfully and pass `twine check`.

Platform CI now installs the schematic extra so the integration and native
renderer tests run on Linux x86_64/aarch64, macOS arm64 and Windows x86_64.
These CI jobs have not been executed locally. No release was published.
