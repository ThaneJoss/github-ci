"""Generic fixtures for discovery, result truth, versioning and trust boundaries."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import yaml

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('automatic', ROOT / 'tools/auto/runtime.py')
auto = importlib.util.module_from_spec(spec)
spec.loader.exec_module(auto)


class Fixtures(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)

    def put(self, path, value):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(value) if isinstance(value, dict) else value)
        subprocess.run(['git', 'add', '--', path], cwd=self.root, check=True)

    def package(self, **kw):
        self.put('package.json', {'name': 'unfamiliar-quartz-492', **kw})
        self.put('index.js', 'const value = 1;\n')

    def detect(self, **kw):
        return auto.discover(self.root, kw)

    def test_unknown_names_no_identity(self):
        self.package()
        a = self.detect()
        self.package(name='renamed-elsewhere')
        self.assertEqual(a, self.detect())
        self.assertEqual(a['tests'], 'not-run')
        self.assertFalse(any(c['kind'] == 'test' for c in a['checks']))
        self.assertEqual(a['node']['version'], '24')

    def test_declared_node_and_package_manager(self):
        self.package(packageManager='pnpm@10.18.3', engines={'node': '>=24 <25'})
        self.put('pnpm-lock.yaml', "lockfileVersion: '9.0'\n")
        a = self.detect()
        self.assertEqual(a['node']['manager_version'], '10.18.3')
        self.assertEqual(a['node']['version'], '>=24 <25')
        self.put('.nvmrc', '24.10.0\n')
        self.assertEqual(self.detect()['node']['version'], '24.10.0')

    def test_python_setup_ranges_preserve_patch_and_exclusions(self):
        self.assertEqual(auto.python_setup_range('>=3.14.5,<3.15'), '>=3.14.5 <3.15.0')
        self.assertEqual(auto.python_setup_range('==3.13.*'), '>=3.13.0 <3.14.0')
        self.assertEqual(auto.python_setup_range('~=3.13.2'), '>=3.13.2 <3.14.0')
        self.assertEqual(auto.python_setup_range('>3.13'), '>3.13.0')
        self.assertEqual(auto.python_setup_range('>=3.13,!=3.13.1'), '>=3.13.0 <3.13.1 || >=3.13.0 >3.13.1')
        with self.assertRaises(auto.Invalid):
            auto.python_setup_range('~=3')

    def test_zero_required_inputs(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/ci.yml').read_text())
        inputs = workflow['on']['workflow_call']['inputs']
        self.assertEqual(inputs['profile']['default'], 'auto')
        self.assertFalse(any(value.get('required', False) for value in inputs.values()))

    def test_lock_mutation_fails(self):
        self.package()
        self.put('package-lock.json', {})
        plan = self.detect()
        self.put('package-lock.json', {'mutated': True})
        with self.assertRaisesRegex(auto.Invalid, 'Lock changed'):
            auto.unchanged(plan, self.root)

    def test_unknown_stack_does_not_become_docs_green(self):
        self.put('README.md', 'content\n')
        self.put('go.mod', 'module generic.invalid/service\n')
        with self.assertRaisesRegex(auto.Invalid, 'Unsupported'):
            self.detect()

    def test_unknown_source_extension_is_not_pure_docs(self):
        self.put('README.md', 'content\n')
        self.put('source.unrecognized-language', 'something executable\n')
        with self.assertRaisesRegex(auto.Invalid, 'Unsupported source'):
            self.detect()

    def test_native_tests_without_package_script(self):
        self.package()
        self.put('small.test.cjs', "const test = require('node:test'); test('real',()=>{});\n")
        self.assertTrue(any(c.get('node_test') for c in self.detect()['checks']))

    def test_pnpm_fallback(self):
        self.package()
        self.put('pnpm-lock.yaml', "lockfileVersion: '9.0'\n")
        self.assertEqual(self.detect()['node']['manager_version'], '10.18.3')

    def test_lock_conflicts_and_missing(self):
        self.package(dependencies={'some-dependency': '1.0.0'})
        with self.assertRaisesRegex(auto.Invalid, 'no committed'):
            self.detect()
        self.put('package-lock.json', {})
        self.put('pnpm-lock.yaml', "lockfileVersion: '9.0'\n")
        with self.assertRaisesRegex(auto.Invalid, 'Ambiguous'):
            self.detect()

    def test_lock_manager_conflict(self):
        self.package(packageManager='pnpm@10.18.3')
        self.put('package-lock.json', {})
        with self.assertRaisesRegex(auto.Invalid, 'conflicts'):
            self.detect()

    def test_monorepo_requires_manifest(self):
        self.package()
        self.put('apps/a/package.json', {})
        with self.assertRaisesRegex(auto.Invalid, 'outside declared'):
            self.detect()
        self.package(workspaces=['apps/*'])
        self.assertEqual(self.detect()['node']['members'], ['apps/a'])
        self.put('apps/a/package-lock.json', {})
        with self.assertRaisesRegex(auto.Invalid, 'Nested/independent'):
            self.detect()

    def test_pnpm_workspace_subset(self):
        self.package(packageManager='pnpm@10.18.3')
        self.put('pnpm-workspace.yaml', "packages:\n  - 'packages/*'\n  - '!packages/ignored'\nsettings: {}\n")
        self.put('packages/a/package.json', {'scripts': {'test': 'node --test'}})
        self.assertEqual(self.detect()['node']['members'], ['packages/a'])
        self.assertFalse(auto.patterns_match('packages/a/nested', ['packages/*']))

    def test_npm_member_checks_not_silently_lost(self):
        self.package(workspaces=['apps/*'], scripts={'test': 'node --test'})
        self.put('apps/a/package.json', {'scripts': {'test': 'node --test'}})
        self.assertEqual(len([c for c in self.detect()['checks'] if c['kind'] == 'test']), 2)

    def test_bounded_tracked_discovery(self):
        self.package()
        self.put('node_modules/unknown/package.json', {'dependencies': {'bad': '*'}})
        self.put('dist/unknown/package.json', {})
        (self.root / 'other').mkdir()
        (self.root / 'other/package.json').write_text('{}')
        self.assertEqual(self.detect()['node']['members'], [])

    def test_symlink_rejected(self):
        self.package()
        (self.root / 'link.py').symlink_to('/etc/passwd')
        subprocess.run(['git', 'add', 'link.py'], cwd=self.root, check=True)
        with self.assertRaisesRegex(auto.Invalid, 'Symlink'):
            self.detect()

    def test_script_priority_and_no_arbitrary_entrypoints(self):
        self.package(scripts={'test': 'node --test', 'test:ci': 'node --test test.cjs', 'deploy': 'wrangler deploy', 'train': 'python train.py', 'pretest:ci': 'exit 1'})
        checks = self.detect()['checks']
        self.assertEqual([c['argv'] for c in checks if c['kind'] == 'test'], [['npm', 'run', 'test:ci']])
        self.assertFalse(any(c['kind'] in {'deploy', 'train'} for c in checks))

    def test_dangerous_selected_script_rejected(self):
        for command in ['wrangler deploy', 'npm publish', 'python train.py', 'npm run deploy', 'echo no test specified', 'vitest --passWithNoTests', 'false || true']:
            with self.subTest(command=command):
                self.package(scripts={'test': command, 'deploy': 'wrangler deploy'})
                with self.assertRaises(auto.Invalid):
                    self.detect()
        auto.safe_script('wrangler deploy --dry-run')

    def test_python_requires_precision(self):
        for constraint in ['>=3.14.5', '>=3.14.5,<3.15', '==3.13.*']:
            self.put('pyproject.toml', f'[project]\nname="molecule"\nversion="0.0.0"\nrequires-python="{constraint}"\n')
            self.put('module.py', 'value = 1\n')
            self.assertEqual(self.detect()['python']['version'], constraint)
        self.put('.python-version', '3.14.5\n')
        self.assertEqual(self.detect()['python']['version'], '3.14.5')

    def test_uv_lock_not_treated_as_pip_requirements(self):
        self.put('pyproject.toml', '[project]\nname="molecule"\nversion="0.0.0"\ndependencies=["some-dep==1.0"]\n[dependency-groups]\nci=["pytest==8.4.2"]\n')
        self.put('tests/test_a.py', 'def test_a(): assert 1 == 1\n')
        with self.assertRaisesRegex(auto.Invalid, 'without uv.lock'):
            self.detect()
        self.put('uv.lock', 'version = 1\n')
        plan = self.detect()
        self.assertTrue(plan['python']['uv'])
        self.assertEqual(plan['python']['selection'], ['--only-group', 'ci'])
        self.assertTrue(any(c.get('mode') == 'pytest' for c in plan['checks']))

    def test_uv_precedence_over_root_pip_exports(self):
        self.put('pyproject.toml', '[project]\nname="molecule"\nversion="0.0.0"\ndependencies=["six==1.17.0"]\n')
        self.put('uv.lock', 'version = 1\n')
        self.put('requirements.txt', 'six==1.17.0\n')
        self.put('module.py', 'value = 1\n')
        self.assertTrue(self.detect()['python']['uv'])
        self.assertTrue(any('takes precedence' in note for note in self.detect()['notes']))

    def test_python_stdlib_and_no_build_guess(self):
        self.put('build.py', 'raise RuntimeError("not an automatic entrypoint")\n')
        self.put('tests/test_a.py', 'import unittest\nclass TestA(unittest.TestCase):\n def test_a(self): self.assertTrue(True)\n')
        a = self.detect()
        self.assertTrue(any(c.get('mode') == 'unittest' for c in a['checks']))
        self.assertFalse(any(c['kind'] == 'build' for c in a['checks']))

    def test_docs_real_validation(self):
        self.put('README.md', '[guide](guide.md)\n')
        self.put('guide.md', 'ok\n')
        state = auto.execute(self.detect(), self.root, self.root / 'result.json')
        self.assertTrue(state['complete'])
        self.assertEqual(state['tests'], 'not-run')
        self.put('README.md', '[bad](missing.md)\n')
        with self.assertRaises(auto.Invalid):
            auto.execute(self.detect(), self.root, self.root / 'result.json')

    def test_junit_empty_and_skipped_fail(self):
        path = self.root / 'junit.xml'
        for value in ['<testsuite/>', '<testsuite><testcase><skipped/></testcase></testsuite>', '<testsuite><testcase><failure/></testcase></testsuite>']:
            path.write_text(value)
            with self.assertRaises(auto.Invalid):
                auto.test_report(path)
        path.write_text('<testsuite><testcase name="a"/></testsuite>')
        self.assertEqual(auto.test_report(path), 1)

    def test_failed_check_has_no_completion(self):
        self.package(scripts={'test': 'node --test'})
        with patch.object(auto, 'run', side_effect=auto.Invalid('failure')):
            with self.assertRaises(auto.Invalid):
                auto.execute(self.detect(), self.root, self.root / 'result.json')
        state = json.loads((self.root / 'result.json').read_text())
        self.assertFalse(state['complete'])
        self.assertEqual(state['checks'][0]['result'], 'failure')

    def test_node_skips_and_zero_tests_fail(self):
        self.package(scripts={'test': 'node --test'})
        for output in ['# tests 0\n# skipped 0\n', '# tests 2\n# skipped 1\n']:
            with patch.object(auto, 'run', return_value=output):
                with self.assertRaises(auto.Invalid):
                    auto.execute(self.detect(), self.root, self.root / 'result.json')

    def test_native_audit_failure_not_suppressed(self):
        self.package()
        self.put('package-lock.json', {})
        def fake(argv, *args, **kwargs):
            if 'audit' in argv:
                raise auto.Invalid('vulnerability or network failure')
            return ''
        with patch.object(auto, 'run', side_effect=fake):
            with self.assertRaisesRegex(auto.Invalid, 'vulnerability'):
                auto.execute(self.detect(), self.root, self.root / 'result.json')
        self.assertFalse(json.loads((self.root / 'result.json').read_text())['complete'])

    def test_called_workflow_embeds_trusted_runtime(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/auto.yml').read_text())
        script = next(s['run'] for s in workflow['jobs']['quality']['steps'] if s.get('id') == 'discover')
        embedded = script.split("<<'PY_RUNTIME'\n", 1)[1].split('\nPY_RUNTIME', 1)[0]
        self.assertEqual(embedded, (ROOT / 'tools/auto/runtime.py').read_text().rstrip())
        self.assertNotIn('raw.githubusercontent.com', script)
        self.assertNotIn('python3 tools/', script)

    def test_controller_cannot_import_caller_json(self):
        self.put('README.md', 'fixture\n')
        self.put('json.py', 'raise Exception("caller shadow imported")\n')
        env = {**os.environ, 'CI_AUTO_DIR': str(self.root / 'temp'), 'GITHUB_WORKSPACE': str(self.root),
               'GITHUB_OUTPUT': str(self.root / 'output')}
        result = subprocess.run(['python3', '-I', str(ROOT / 'tools/auto/runtime.py'), 'detect'], cwd=self.root, env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


class Gate(unittest.TestCase):
    def test_all_profile_results(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/ci.yml').read_text())
        script = workflow['jobs']['gate']['steps'][0]['run']
        profiles = ['auto', 'node', 'python', 'docs']
        cases = 0
        with tempfile.TemporaryDirectory() as tmp:
            for profile in profiles:
                for result in ['success', 'failure', 'cancelled', 'skipped', '']:
                    for proof in ['true', 'false', '']:
                        needs = {p: {'result': 'skipped', 'outputs': {}} for p in profiles + ['invalid-profile']}
                        needs[profile] = {'result': result, 'outputs': {'quality-passed': proof}}
                        env = {**os.environ, 'PROFILE': profile, 'NEEDS': json.dumps(needs), 'GITHUB_OUTPUT': tmp + '/output'}
                        run = subprocess.run(['bash', '-e', '-c', script], env=env, capture_output=True)
                        self.assertEqual(run.returncode == 0, result == 'success' and proof == 'true')
                        cases += 1
            needs = {p: {'result': 'skipped', 'outputs': {}} for p in profiles + ['invalid-profile']}
            needs['auto'] = {'result': 'success', 'outputs': {'quality-passed': 'true'}}
            for other in ['node', 'python', 'docs', 'invalid-profile']:
                for result in ['success', 'failure', 'cancelled', '']:
                    broken = json.loads(json.dumps(needs))
                    broken[other]['result'] = result
                    run = subprocess.run(['bash', '-e', '-c', script], env={**os.environ, 'PROFILE': 'auto', 'NEEDS': json.dumps(broken), 'GITHUB_OUTPUT': tmp + '/output'}, capture_output=True)
                    self.assertNotEqual(run.returncode, 0)
                    cases += 1
        print(f'Gate truth table: {cases} cases')


if __name__ == '__main__':
    unittest.main(verbosity=2)
