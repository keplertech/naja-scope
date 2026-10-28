# SPDX-License-Identifier: Apache-2.0
"""Run with a chosen najaeda environment; exits nonzero on elaboration failure."""
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory

from najaeda import naja

print(f"najaeda {version('najaeda')}", flush=True)
universe = naja.NLUniverse.create()
db = naja.NLDB.create(universe)
universe.setTopDB(db)
try:
    source = str(Path(__file__).resolve().parents[1] / 'tests/fixtures/dynamic_packed_write.sv')
    top = db.loadSystemVerilog([source], diagnostics_report_path=None)
    print(f"Elaborated {top.getName()}")
    with TemporaryDirectory() as directory:
        db.dumpNajaIF(directory)
        universe.destroy()
        naja.NLDB.loadNajaIF(directory)
        restored = naja.NLUniverse.get().getTopDesign()
        assert restored.getName() == "dynamic_packed_write"
        print(f"Reloaded {restored.getName()} from a fresh snapshot")
finally:
    if naja.NLUniverse.get() is not None:
        naja.NLUniverse.get().destroy()
