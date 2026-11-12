"""The build imports none of orchard's Python: orchard's producers run as commands (orchard docs/distribution-contract.md).

Tests may import orchard; they test against it.
"""
import ast
from pathlib import Path
import unittest

PROJECT = Path(__file__).resolve().parents[1]


def python_files():
    for path in sorted(PROJECT.rglob('*')):
        relative = path.relative_to(PROJECT)
        if not path.is_file() or relative.parts[0] in ('tests', 'out', '.orchard', '.venv', '.git') \
                or '__pycache__' in relative.parts:
            continue
        if path.suffix == '.py':
            yield path
        elif not path.suffix and path.read_bytes()[:64].startswith(b'#!') and b'python' in path.read_bytes()[:64]:
            yield path


class NoOrchardImports(unittest.TestCase):
    def test_no_build_file_imports_orchard(self):
        files = list(python_files())
        self.assertIn(PROJECT / 'tools/build.py', files)
        self.assertIn(PROJECT / 'desktop/build-labwc', files)
        for path in files:
            for node in ast.walk(ast.parse(path.read_text(), str(path))):
                names = ([alias.name for alias in node.names] if isinstance(node, ast.Import) else
                         [node.module or ''] if isinstance(node, ast.ImportFrom) and not node.level else [])
                for name in names:
                    with self.subTest(path=str(path.relative_to(PROJECT)), module=name):
                        self.assertNotEqual(name.split('.')[0], 'orchard')


if __name__ == '__main__':
    unittest.main()
