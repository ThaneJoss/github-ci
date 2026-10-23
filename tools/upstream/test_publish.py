"""Check publication boundaries without creating branches or PRs on GitHub."""

import base64
import copy
import json
import unittest

import publish


CURRENT = {'version': '2.7.0', 'asset': 'osv-scanner_linux_amd64', 'sha256': '1' * 64}
CANDIDATE = {'version': '2.8.0', 'asset': 'osv-scanner_linux_amd64', 'sha256': '2' * 64}


class FakeGitHub:
    repository = 'example/template'

    def __init__(self, current=CURRENT, branch_pin=None, pulls=None, failure=None, branch_files=None,
                 moved_head=False):
        self.current = copy.deepcopy(current)
        self.branch_pin = copy.deepcopy(branch_pin)
        self.branch_sha = 'existing-update' if branch_pin is not None else None
        self.branch_reads = 0
        self.moved_head = moved_head
        self.pulls = [] if pulls is None else pulls
        self.failure = failure
        self.branch_files = ([{'filename': publish.PIN_PATH, 'status': 'modified'}]
                             if branch_files is None else branch_files)
        self.calls = []

    def request(self, method, path, data=None):
        self.calls.append((method, path, data))
        if self.failure and self.failure[:2] == (method, path):
            raise self.failure[2]
        if path == 'git/ref/heads/main':
            return {'object': {'sha': 'main-commit'}}
        if path.startswith('contents/'):
            pin = self.current if 'ref=main-commit' in path else self.branch_pin
            return {'type': 'file', 'encoding': 'base64',
                    'content': base64.b64encode(json.dumps(pin).encode()).decode()}
        if method == 'GET' and path.startswith('git/ref/heads/automation/'):
            self.branch_reads += 1
            if self.branch_sha is None:
                raise publish.APIError(404, 'Not Found')
            sha = 'moved-commit' if self.moved_head and self.branch_reads > 1 else self.branch_sha
            return {'object': {'sha': sha}}
        if path == 'git/commits/main-commit':
            return {'tree': {'sha': 'main-tree'}}
        if path == 'compare/main-commit...existing-update':
            return {'files': self.branch_files}
        if method == 'GET' and path.startswith('pulls?'):
            return self.pulls
        if method == 'POST':
            if path == 'git/refs':
                self.branch_sha = data['sha']
            return {'sha': 'created-object', 'html_url': 'https://github.com/example/template/pull/9',
                    'head': {'sha': self.branch_sha}}
        raise AssertionError(f'Unexpected API call: {method} {path}')


class PublisherTests(unittest.TestCase):
    def publish(self, api, pin=CANDIDATE):
        return publish.publish(api, pin, 'main', 'https://github.com/example/template/actions/runs/123')

    def test_new_branch_changes_only_pin_and_dispatches_after_pr(self):
        api = FakeGitHub()
        result = self.publish(api)
        self.assertEqual(result['validation'], 'dispatched')
        writes = [(path, data) for method, path, data in api.calls if method == 'POST']
        self.assertEqual([path for path, _ in writes], [
            'git/trees', 'git/commits', 'git/refs', 'pulls',
            'actions/workflows/validate.yml/dispatches'])
        tree = writes[0][1]
        self.assertEqual(tree['base_tree'], 'main-tree')
        self.assertEqual(len(tree['tree']), 1)
        self.assertEqual(tree['tree'][0]['path'], publish.PIN_PATH)
        self.assertEqual(json.loads(tree['tree'][0]['content']), CANDIDATE)
        self.assertEqual(writes[1][1]['parents'], ['main-commit'])
        self.assertEqual(writes[2][1]['ref'], 'refs/heads/automation/osv-scanner-v2.8.0')
        self.assertEqual(writes[-1][1], {'ref': 'automation/osv-scanner-v2.8.0'})
        self.assertIn(CANDIDATE['sha256'], writes[3][1]['body'])

    def test_existing_matching_branch_and_pr_are_reused_without_mutation(self):
        api = FakeGitHub(branch_pin=CANDIDATE, pulls=[{
            'html_url': 'https://github.com/example/template/pull/8',
            'head': {'sha': 'existing-update'},
        }])
        result = self.publish(api)
        self.assertTrue(result['pull_request'].endswith('/8'))
        self.assertEqual([(m, p) for m, p, _ in api.calls if m != 'GET'], [
            ('POST', 'actions/workflows/validate.yml/dispatches')])

    def test_retry_after_pr_failure_uses_completed_branch(self):
        api = FakeGitHub(branch_pin=CANDIDATE)
        self.publish(api)
        self.assertEqual([p for m, p, _ in api.calls if m == 'POST'], [
            'pulls', 'actions/workflows/validate.yml/dispatches'])

    def test_latest_main_already_updated_does_not_create_empty_pr(self):
        api = FakeGitHub(current=CANDIDATE)
        self.assertFalse(self.publish(api)['changed'])
        self.assertTrue(all(method == 'GET' for method, _, _ in api.calls))

    def test_stale_candidate_and_same_version_changed_hash_are_rejected(self):
        for current in [dict(CANDIDATE, version='2.9.0'), dict(CANDIDATE, sha256='3' * 64)]:
            with self.subTest(current=current):
                api = FakeGitHub(current=current)
                with self.assertRaises(ValueError):
                    self.publish(api)
                self.assertTrue(all(method == 'GET' for method, _, _ in api.calls))

    def test_existing_different_branch_is_never_overwritten(self):
        api = FakeGitHub(branch_pin=dict(CANDIDATE, sha256='3' * 64))
        with self.assertRaisesRegex(ValueError, 'refusing to overwrite'):
            self.publish(api)
        self.assertTrue(all(method == 'GET' for method, _, _ in api.calls))

    def test_matching_pin_cannot_hide_other_branch_changes_or_missing_diff(self):
        pin_file = {'filename': publish.PIN_PATH, 'status': 'modified'}
        invalid_diffs = [
            [],
            [pin_file, {'filename': '.github/workflows/validate.yml', 'status': 'modified'}],
            [{'filename': 'README.md', 'status': 'modified'}],
            [{'filename': publish.PIN_PATH, 'status': 'renamed'}],
            [pin_file, pin_file],
        ]
        for files in invalid_diffs:
            with self.subTest(files=files):
                api = FakeGitHub(branch_pin=CANDIDATE, branch_files=files)
                with self.assertRaisesRegex(ValueError, 'must change only the OSV pin'):
                    self.publish(api)
                self.assertTrue(all(method == 'GET' for method, _, _ in api.calls))

    def test_bad_candidate_is_rejected_before_any_api_request(self):
        api = FakeGitHub()
        with self.assertRaises(ValueError):
            self.publish(api, dict(CANDIDATE, version='2.8.0\nref=main'))
        self.assertEqual(api.calls, [])

    def test_permission_failure_has_settings_hint_and_never_dispatches(self):
        api = FakeGitHub(failure=('POST', 'pulls', publish.APIError(403, 'GitHub Actions is not permitted to create pull requests')))
        with self.assertRaisesRegex(RuntimeError, 'Allow GitHub Actions to create and approve pull requests'):
            self.publish(api)
        self.assertFalse(any(path.endswith('/dispatches') for _, path, _ in api.calls))

    def test_branch_lookup_auth_failure_is_not_treated_as_missing(self):
        api = FakeGitHub(failure=('GET', 'git/ref/heads/automation/osv-scanner-v2.8.0', publish.APIError(403, 'Forbidden')))
        with self.assertRaises(publish.APIError):
            self.publish(api)
        self.assertTrue(all(method == 'GET' for method, _, _ in api.calls))

    def test_validation_dispatch_failure_is_not_success(self):
        api = FakeGitHub(failure=('POST', 'actions/workflows/validate.yml/dispatches', publish.APIError(403, 'Forbidden')))
        with self.assertRaises(publish.APIError):
            self.publish(api)

    def test_pr_head_mismatch_prevents_dispatch(self):
        api = FakeGitHub(branch_pin=CANDIDATE, pulls=[{
            'html_url': 'https://github.com/example/template/pull/8',
            'head': {'sha': 'unexpected-commit'},
        }])
        with self.assertRaisesRegex(ValueError, 'PR head differs'):
            self.publish(api)
        self.assertFalse(any(path.endswith('/dispatches') for _, path, _ in api.calls))

    def test_branch_movement_before_dispatch_is_rejected(self):
        for existing in [None, CANDIDATE]:
            with self.subTest(existing=existing is not None):
                api = FakeGitHub(branch_pin=existing, moved_head=True)
                with self.assertRaisesRegex(ValueError, 'branch moved'):
                    self.publish(api)
                self.assertFalse(any(path.endswith('/dispatches') for _, path, _ in api.calls))


if __name__ == '__main__':
    unittest.main()
