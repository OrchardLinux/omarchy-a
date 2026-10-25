"""Contracts for public-only release attestations; no GitHub calls."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
CASES = [["build.yml","assets","omarchy-a-build.sigstore.jsonl","omarchy-release-assets","draft"]]
GUARD = "if: toJSON(github.event.repository.private) == 'false'"
ACTION = 'actions/attest@1e69f48acb82d1966a394da916b4c1698aa569d6'


def job(text, name):
    match = re.search(r'^  ' + re.escape(name) + r':\n(.*?)(?=^  [\w-]+:\n|\Z)', text, re.M | re.S)
    if match is None:
        raise AssertionError('Missing job: ' + name)
    return match.group(1)


def step(text, name):
    match = re.search(r'^      - name: ' + re.escape(name) + r'\n(.*?)(?=^      - |\Z)', text, re.M | re.S)
    if match is None:
        raise AssertionError('Missing step: ' + name)
    return match.group(1)


class WorkflowAttestation(unittest.TestCase):
    def test_permissions_are_scoped_to_the_signing_job(self):
        for filename, signer, _, _, _ in CASES:
            with self.subTest(workflow=filename):
                text = (ROOT / '.github/workflows' / filename).read_text()
                body = job(text, signer)
                for scope in ('id-token', 'attestations', 'artifact-metadata'):
                    permission = scope + ': write'
                    self.assertEqual(text.count(permission), 1)
                    self.assertIn(permission, body)
                self.assertIn('contents: read', body)
                self.assertNotIn('contents: write', body)
                self.assertNotIn('pull_request_target:', text)

    def test_private_or_unknown_visibility_cannot_attest_or_copy_a_bundle(self):
        for filename, signer, _, _, _ in CASES:
            with self.subTest(workflow=filename):
                body = job((ROOT / '.github/workflows' / filename).read_text(), signer)
                attest = step(body, 'Attest public build')
                retain = step(body, 'Include public attestation bundle')
                # JSON boolean false is explicit: null and string "false" do not match.
                self.assertIn(GUARD, attest)
                self.assertIn(GUARD, retain)
                self.assertEqual(body.count(GUARD), 2)
                self.assertIn('uses: ' + ACTION, attest)
                self.assertIn('subject-path: out/publication/*', attest)
                self.assertNotIn('continue-on-error:', body)

    def test_bundle_reaches_both_workflow_artifacts_and_release_upload(self):
        for filename, signer, bundle, artifact, consumer in CASES:
            with self.subTest(workflow=filename):
                text = (ROOT / '.github/workflows' / filename).read_text()
                body = job(text, signer)
                self.assertIn('steps.attest.outputs.bundle-path', body)
                self.assertIn('cp "$BUNDLE_PATH" "out/publication/' + bundle + '"', body)
                self.assertLess(body.index('name: Attest public build'), body.index('name: Include public attestation bundle'))
                self.assertLess(body.index('name: Include public attestation bundle'), body.index('uses: actions/upload-artifact@'))
                self.assertIn('name: ' + artifact, body)
                self.assertIn('path: out/publication/*', body)
                # Do not mutate the signed checksum manifest after attesting it.
                self.assertNotIn('sha256sum', body[body.index('name: Attest public build'):])
                release = job(text, consumer)
                self.assertIn('name: ' + artifact, release)
                self.assertIn('assets/*', release)


if __name__ == '__main__':
    unittest.main()
