"""Discover the optional device monitor's isolated stdlib tests."""
import importlib.util
from pathlib import Path
import sys
from unittest.mock import patch


def load_tests(loader, tests, pattern):
    directory = Path(__file__).resolve().parents[1] / 'extras/device-monitor'
    spec = importlib.util.spec_from_file_location(
        'device_monitor_tests', directory / 'test_system_telemetry.py')
    module = importlib.util.module_from_spec(spec)
    with patch.object(sys, 'path', [str(directory), *sys.path]):
        spec.loader.exec_module(module)
    return loader.loadTestsFromModule(module)
