"""ci/nightly: a scheduled run builds only when the nightly's inputs changed; no GitHub calls."""
import contextlib
from datetime import datetime, timezone
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
import io
import json
from pathlib import Path
import re
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
loader = SourceFileLoader('ci_nightly', str(ROOT / 'ci/nightly'))
nightly = module_from_spec(spec_from_loader('ci_nightly', loader))
loader.exec_module(nightly)

COMMIT, OTHER = 'a' * 40, 'b' * 40
ORCHARD = 'nightly-20261115-8c6374fa3157'
NOW = datetime(2026, 11, 16, 4, 30, 5, tzinfo=timezone.utc)


def run(*argv, stdin=''):
    output = io.StringIO()
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
        import sys
        saved, sys.stdin = sys.stdin, io.StringIO(stdin)
        try:
            nightly.main(list(argv), now=NOW)
        finally:
            sys.stdin = saved
    return output.getvalue()


class Plan(unittest.TestCase):
    def planned(self, previous, *extra, event='schedule', commit=COMMIT, orchard=ORCHARD, wanted='', ref=''):
        with tempfile.TemporaryDirectory() as directory:
            argv = ['plan', '--event', event, '--ref', ref, '--wanted', wanted, '--commit', commit,
                    '--input', 'orchard=' + orchard, *extra]
            if previous is not None:
                path = Path(directory) / 'latest.json'
                path.write_text(previous if isinstance(previous, str) else json.dumps(previous))
                argv += ['--previous', str(path)]
            else:
                argv += ['--previous', str(Path(directory) / 'missing.json')]
            return dict(line.split('=', 1) for line in run(*argv).splitlines())

    def last(self, **inputs):
        return json.loads(run('record', '--name', 'nightly-20261115-' + 'a' * 12, '--commit', COMMIT, '--run-id', '7',
                              *(part for name, value in inputs.items() for part in ('--input', f'{name}={value}'))))

    def test_a_scheduled_run_with_the_inputs_of_the_last_nightly_builds_nothing(self):
        self.assertEqual(self.planned(self.last(orchard=ORCHARD)), {'nightly': 'false', 'name': ''})

    def test_a_new_commit_here_or_a_new_orchard_nightly_builds(self):
        last = self.last(orchard=ORCHARD)
        self.assertEqual(self.planned(last, commit=OTHER), {'nightly': 'true', 'name': 'nightly-20261116-' + 'b' * 12})
        self.assertEqual(self.planned(last, orchard='nightly-20261116-0123456789ab'),
                         {'nightly': 'true', 'name': 'nightly-20261116-' + 'a' * 12})

    def test_no_or_an_unreadable_earlier_record_builds(self):
        for previous in (None, 'not json', {'schema': 1, 'name': 'x'}, {'inputs': 'none'}):
            with self.subTest(previous=previous):
                self.assertEqual(self.planned(previous)['nightly'], 'true')

    def test_a_further_input_takes_part_in_the_comparison(self):
        packages = ('--input', 'packages=sha256:1111')
        # The first night with the new input builds once; after that only its change does.
        self.assertEqual(self.planned(self.last(orchard=ORCHARD), *packages)['nightly'], 'true')
        last = self.last(orchard=ORCHARD, packages='sha256:1111')
        self.assertEqual(self.planned(last, *packages)['nightly'], 'false')
        self.assertEqual(self.planned(last, '--input', 'packages=sha256:2222')['nightly'], 'true')
        self.assertEqual(self.planned(last)['nightly'], 'true')

    def test_a_dispatch_builds_only_when_it_asks_and_other_events_never(self):
        last = self.last(orchard=ORCHARD)
        self.assertEqual(self.planned(last, event='workflow_dispatch', wanted='true')['nightly'], 'true')
        self.assertEqual(self.planned(last, event='workflow_dispatch', wanted='false'), {'nightly': 'false', 'name': ''})
        self.assertEqual(self.planned(None, event='pull_request', commit=OTHER, ref='refs/pull/1/merge')['nightly'],
                         'false')

    def test_every_merge_to_main_is_a_nightly_and_a_tag_or_branch_push_is_not(self):
        last = self.last(orchard=ORCHARD)
        # Whatever the last nightly was built from: the nightly follows main.
        self.assertEqual(self.planned(last, event='push', commit=OTHER, ref='refs/heads/main'),
                         {'nightly': 'true', 'name': 'nightly-20261116-' + 'b' * 12})
        for ref in ('refs/tags/v0.3.9', 'refs/heads/feature', ''):
            with self.subTest(ref=ref):
                self.assertEqual(self.planned(last, event='push', commit=OTHER, ref=ref), {'nightly': 'false', 'name': ''})

    def test_the_record_names_what_the_nightly_was_built_from(self):
        self.assertEqual(self.last(orchard=ORCHARD),
                         {'schema': 1, 'name': 'nightly-20261115-' + 'a' * 12, 'commit': COMMIT,
                          'built': '2026-11-16T04:30:05Z', 'run_id': 7,
                          'inputs': {'omarchy-a': COMMIT, 'orchard': ORCHARD}})

    def test_malformed_inputs_are_refused(self):
        for argv in (['--commit', 'main', '--input', 'orchard=x'], ['--commit', COMMIT, '--input', 'orchard'],
                     ['--commit', COMMIT, '--input', 'omarchy-a=x'], ['--commit', COMMIT, '--input', 'a=1', '--input', 'a=2']):
            with self.subTest(argv=argv), self.assertRaises(SystemExit):
                run('plan', '--event', 'schedule', *argv)


class Expired(unittest.TestCase):
    def test_old_nightlies_go_but_never_the_newest_and_nothing_else(self):
        tags = ['v0.3.0', 'vpreview-43089136668', 'nightly', 'nightly-20261101-' + 'a' * 12,
                'nightly-20261109-' + 'b' * 12, 'nightly-20261114-' + 'c' * 12]
        self.assertEqual(run('expired', '--keep-days', '7', stdin='\n'.join(tags)).split(),
                         ['nightly-20261101-' + 'a' * 12])
        self.assertEqual(run('expired', '--keep-days', '7', stdin='nightly-20260101-' + 'a' * 12), '')


class Workflow(unittest.TestCase):
    """The workflow around it: only a nightly run publishes, only from main, and tags release as before."""
    def setUp(self):
        self.text = (ROOT / '.github/workflows/build.yml').read_text()

    def job(self, name):
        return re.search(r'^  ' + re.escape(name) + r':\n(.*?)(?=^  [\w-]+:\n|\Z)', self.text, re.M | re.S).group(1)

    def test_scheduled_after_orchards_nightly_and_decided_in_the_first_job(self):
        self.assertIn("    - cron: '30 4 * * *'", self.text)
        plan = self.job('orchard')
        self.assertIn('ci/nightly plan --event "$EVENT" --ref "$GITHUB_REF"', plan)
        self.assertIn('--input "orchard=$ORCHARD_TAG"', plan)
        # The third input: the Orchard package repository's index, planned and recorded alike.
        self.assertIn('releases/download/repo-aarch64/orchard.db', plan)
        # A missing index fails the job: it is downloaded before it is hashed, never piped into the checksum.
        self.assertIn('-o orchard.db https://github.com/OrchardLinux/packages/releases/download/repo-aarch64/orchard.db\n', plan)
        self.assertIn('--input "packages=$PACKAGES"', plan)
        self.assertIn('--input "orchard=$ORCHARD_TAG" --input "packages=$PACKAGES" > assets/nightly.json',
                      self.job('nightly'))
        self.assertIn('PACKAGES: ${{ needs.orchard.outputs.packages }}', self.job('nightly'))
        self.assertNotIn('needs:', plan)
        for name in ('artwork-check', 'artwork', 'userspace'):
            self.assertIn("    if: github.ref_type == 'tag' || github.event_name == 'workflow_dispatch' || "
                          "needs.orchard.outputs.nightly == 'true'\n", self.job(name), name)

    def test_only_a_nightly_run_on_main_publishes_and_the_pointer_installs_it(self):
        publish = self.job('nightly')
        self.assertIn("    if: needs.orchard.outputs.nightly == 'true' && github.ref == 'refs/heads/main'\n", publish)
        self.assertIn('needs: [orchard, assets]', publish)
        self.assertIn('sha256sum --check --strict SHA256SUMS', publish)
        self.assertIn('cp assets/nightly.json pointer/latest.json', publish)
        self.assertIn('cp assets/install.sh pointer/', publish)
        self.assertEqual(publish.count('--prerelease --verify-tag --latest=false'), 2)
        self.assertEqual(self.text.count('contents: write'), 2)
        self.assertIn("    if: github.ref_type == 'tag'\n", self.job('draft'))

    def test_the_pointer_is_the_nightly_channels_pacman_repository(self):
        # The userspace job makes it from the package it built, the assembly hosts it with the nightly.
        self.assertIn('ci/nightly-repo out/package out/nightly-repo', self.job('userspace'))
        self.assertIn('cp out/nightly-repo/* out/publication/', self.job('assets'))
        publish = self.job('nightly')
        self.assertIn('cp assets/omarchy-a-nightly.db assets/omarchy-a-nightly.files assets/omarchy-a-*.pkg.tar.zst '
                      'pointer/', publish)
        # Made anew each time: the old package goes with the old pointer.
        self.assertIn('gh release delete nightly --cleanup-tag --yes', publish)
        # An older run finishing last never moves it back.
        self.assertIn('compare/$GITHUB_SHA...$current" --jq .status) == ahead', publish)
        repo = (ROOT / 'ci/nightly-repo').read_text()
        self.assertIn('repo=omarchy-a-nightly', repo)
        self.assertIn('cp "$work/$repo.db.tar.gz" "$output/$repo.db"', repo)
        self.assertIn('https://github.com/OrchardLinux/omarchy-a/releases/download/nightly',
                      (ROOT / 'desktop/shell/bin/omarchy-channel').read_text())

    def test_the_package_version_is_read_where_git_has_the_history(self):
        plan = self.job('orchard')
        self.assertIn('fetch-depth: 0', plan)
        self.assertIn('python3 -m release.package --print-version', plan)
        self.assertIn('VERSION: ${{ needs.orchard.outputs.version }}', self.job('userspace'))

    def test_orchard_comes_from_its_published_release_not_from_a_checkout(self):
        dependencies = (ROOT / 'ci/dependencies').read_text()
        self.assertIn('"$base/orchard-source.tar.gz"', dependencies)
        # Only the tests, which follow orchard main, and a build from a not yet published orchard run clone it.
        self.assertEqual(dependencies.count('git clone'), 1)
        self.assertIn('elif [[ -n "${ORCHARD_REF:-}" || -n "${HARDWARE_ARTIFACT_DIR:-}" ]]; then\n  git clone', dependencies)
        self.assertEqual(self.text.count('ORCHARD_REF'), 1)
        self.assertIn('ORCHARD_REF: main', self.job('test'))


class SnapshotRevision(unittest.TestCase):
    """The release names orchard's commit also when the snapshot is the published archive, unpacked."""
    def test_an_unpacked_archive_names_its_recorded_commit_and_never_the_repository_around_it(self):
        from release import snapshot
        # Below this checkout, as CI's .orchard is: its repository is not orchard's.
        with tempfile.TemporaryDirectory(dir=ROOT / 'tests') as directory:
            root = Path(directory)
            self.assertIsNone(snapshot.revision(root))
            (root / '.source-commit').write_text(COMMIT + '\n')
            self.assertEqual(snapshot.revision(root), {'commit': COMMIT, 'modified': False})
            (root / '.source-commit').write_text('main\n')
            self.assertIsNone(snapshot.revision(root))

    def test_a_checkout_names_its_own_commit(self):
        from release import snapshot
        self.assertRegex(snapshot.revision(ROOT)['commit'], '^[0-9a-f]{40}$')


if __name__ == '__main__':
    unittest.main()
