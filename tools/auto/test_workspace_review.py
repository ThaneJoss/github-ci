"""Regression cases for workspace coverage and package-manager metadata."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest


spec = importlib.util.spec_from_file_location('workspace_auto', Path(__file__).with_name('runtime.py'))
auto = importlib.util.module_from_spec(spec)
spec.loader.exec_module(auto)


class WorkspaceReview(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        self.put('index.js', 'const value = 1;\n')

    def put(self, path, value):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(value) if isinstance(value, dict) else value)
        subprocess.run(['git', 'add', '--', path], cwd=self.root, check=True)

    def native(self, path, body="test('runs', () => {});"):
        self.put(path, "const test = require('node:test');\n" + body + '\n')

    def selected_tests(self):
        return [c for c in auto.discover(self.root)['checks'] if c['kind'] == 'test']

    def test_member_script_preserves_sibling_and_root_native_tests(self):
        self.put('package.json', {'workspaces': ['packages/*']})
        self.put('packages/a/package.json', {'scripts': {'test': 'node --test'}})
        self.put('packages/b/package.json', {})
        self.native('packages/a/a.test.cjs')
        self.native('packages/b/b.test.cjs')
        self.native('root.test.cjs')
        checks = {c['cwd']: c for c in self.selected_tests()}
        self.assertEqual(set(checks), {'.', 'packages/a', 'packages/b'})
        self.assertEqual(checks['packages/a']['argv'], ['npm', 'run', 'test'])
        self.assertEqual(checks['packages/b']['argv'][-1], 'b.test.cjs')
        self.assertEqual(checks['.']['argv'][-1], 'root.test.cjs')
        self.assertNotIn('packages/a/a.test.cjs', checks['.']['argv'])

    def test_root_script_does_not_suppress_member_fallback(self):
        self.put('package.json', {'workspaces': ['packages/*'], 'scripts': {'test': 'node --test root.test.cjs'}})
        self.put('packages/a/package.json', {})
        self.native('root.test.cjs')
        self.native('packages/a/a.test.cjs')
        self.assertEqual({c['cwd'] for c in self.selected_tests()}, {'.', 'packages/a'})

    def test_nested_member_owns_its_native_tests(self):
        self.put('package.json', {'workspaces': ['packages/**']})
        self.put('packages/a/package.json', {})
        self.put('packages/a/nested/package.json', {})
        self.native('packages/a/a.test.cjs')
        self.native('packages/a/nested/inner.test.cjs')
        checks = {c['cwd']: c for c in self.selected_tests()}
        self.assertEqual(set(checks), {'packages/a', 'packages/a/nested'})
        self.assertEqual(checks['packages/a']['argv'][3:], ['a.test.cjs'])
        self.assertEqual(checks['packages/a/nested']['argv'][3:], ['inner.test.cjs'])

    def test_sibling_native_failure_reaches_gate(self):
        self.put('package.json', {'workspaces': ['packages/*']})
        self.put('packages/a/package.json', {'scripts': {'test': 'node --test'}})
        self.put('packages/b/package.json', {})
        self.native('packages/a/a.test.cjs')
        self.native('packages/b/b.test.cjs', "test('fails', () => { throw new Error('member regression'); });")
        state_file = self.root / 'result.json'
        with self.assertRaisesRegex(auto.Invalid, 'Command failed'):
            auto.execute(auto.discover(self.root), self.root, state_file)
        state = json.loads(state_file.read_text())
        self.assertFalse(state['complete'])
        self.assertEqual(state['checks'][-1]['result'], 'failure')
        self.assertIn('packages/b', state['checks'][-1]['label'])

    def test_pnpm_requires_its_workspace_file(self):
        self.put('package.json', {'packageManager': 'pnpm@10.18.3', 'workspaces': ['packages/*']})
        self.put('packages/a/package.json', {})
        with self.assertRaisesRegex(auto.Invalid, 'pnpm workspaces require pnpm-workspace.yaml'):
            auto.discover(self.root)

    def test_pnpm_lock_fallback_also_requires_its_workspace_file(self):
        self.put('package.json', {'workspaces': ['packages/*']})
        self.put('pnpm-lock.yaml', "lockfileVersion: '9.0'\n")
        self.put('packages/a/package.json', {})
        with self.assertRaisesRegex(auto.Invalid, 'pnpm workspaces require pnpm-workspace.yaml'):
            auto.discover(self.root)

    def test_npm_cannot_use_pnpm_workspace_file(self):
        self.put('package.json', {'packageManager': 'npm@11.6.0'})
        self.put('pnpm-workspace.yaml', "packages:\n  - 'packages/*'\n")
        self.put('packages/a/package.json', {})
        with self.assertRaisesRegex(auto.Invalid, 'npm workspaces require package.json workspaces'):
            auto.discover(self.root)

    def test_valid_manager_specific_workspaces(self):
        self.put('packages/a/package.json', {})
        self.put('package.json', {'workspaces': ['packages/*']})
        self.assertEqual(auto.discover(self.root)['node']['members'], ['packages/a'])
        self.put('package.json', {'packageManager': 'pnpm@10.18.3'})
        self.put('pnpm-workspace.yaml', "packages:\n  - 'packages/*'\n")
        self.assertEqual(auto.discover(self.root)['node']['members'], ['packages/a'])

    def test_matching_dual_metadata_uses_selected_manager(self):
        self.put('packages/a/package.json', {})
        self.put('pnpm-workspace.yaml', "packages:\n  - 'packages/*'\n")
        for manager in ['npm@11.6.0', 'pnpm@10.18.3']:
            with self.subTest(manager=manager):
                self.put('package.json', {'packageManager': manager, 'workspaces': ['packages/*']})
                node = auto.discover(self.root)['node']
                self.assertEqual(node['manager'], manager.split('@')[0])
                self.assertEqual(node['members'], ['packages/a'])

    def test_hash_declarations_fail_instead_of_dropping_integrity(self):
        for manager in ['npm@11.6.0', 'pnpm@10.18.3']:
            for algorithm in ['224', '256', '384', '512']:
                with self.subTest(manager=manager, algorithm=algorithm):
                    self.put('package.json', {'packageManager': manager + '+sha' + algorithm + '.deadbeef'})
                    with self.assertRaisesRegex(auto.Invalid, 'integrity hashes.*explicit workflow'):
                        auto.discover(self.root)

    def test_exact_manager_without_hash_still_supported(self):
        for manager in ['npm@11.6.0', 'pnpm@10.18.3']:
            with self.subTest(manager=manager):
                self.put('package.json', {'packageManager': manager})
                node = auto.discover(self.root)['node']
                self.assertEqual(node['manager_version'], manager.split('@')[1])


if __name__ == '__main__':
    unittest.main()
