"""orchard's buildenv.py, loaded by path from the orchard snapshot (ORCHARD_CHECKOUT).

buildenv.py is standard-library only and part of orchard's distribution
contract (orchard docs/distribution-contract.md): the build container, or the
native build of a recipe. No orchard package is imported.
"""
import importlib.util
import os
from pathlib import Path


def load():
    root = os.environ.get('ORCHARD_CHECKOUT')
    path = Path(root) / 'src/orchard/buildenv.py' if root else None
    if path is None or not path.is_file():
        raise SystemExit('Set ORCHARD_CHECKOUT to the orchard snapshot (orchard build and tools/build.py set it)')
    spec = importlib.util.spec_from_file_location('orchard_snapshot_buildenv', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


buildenv = load()
