from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
PATCH = PROJECT / 'desktop/labwc/0004-overview.patch'


def added_file(patch, name):
    """The contents of a file the patch creates."""
    lines = patch.splitlines()
    start = lines.index(f'+++ b/{name}') + 2
    body = []
    for line in lines[start:]:
        if line.startswith('diff --git'):
            break
        body.append(line[1:])
    return '\n'.join(body) + '\n'


class OverviewMath(unittest.TestCase):
    @unittest.skipUnless(shutil.which('cc'), 'needs a C compiler')
    def test_overview_math_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            (work / 'overview-math.h').write_text(added_file(PATCH.read_text(), 'include/overview-math.h'))
            subprocess.run(['cc', '-Wall', '-Werror', '-I', str(work), '-o', str(work / 'test'),
                            str(PROJECT / 'desktop/labwc/test-overview.c'), '-lm'], check=True)
            result = subprocess.run([str(work / 'test')], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_choosing_a_window_moves_it_only_from_the_overview_choice(self):
        source = added_file(PATCH.read_text(), 'src/overview.c')
        # Brought on screen in one place only: when a choice leaves the overview.
        self.assertEqual(source.count('bring_on_screen('), 2)
        finish = source[source.index('\nfinish(struct view *chosen)'):]
        self.assertIn('bring_on_screen(chosen);', finish[:finish.index('\n}\n')])


if __name__ == '__main__':
    unittest.main()
