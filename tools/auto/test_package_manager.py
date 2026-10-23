"""Package-manager launch compatibility without enabling lifecycle scripts."""
import errno
import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('package_manager_auto', Path(__file__).with_name('runtime.py'))
auto = importlib.util.module_from_spec(spec)
spec.loader.exec_module(auto)


class PackageManagerLaunch(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='package manager ')
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.root = self.folder / 'project'
        self.root.mkdir()
        self.bin = self.folder / 'bin'
        self.bin.mkdir()
        self.log = self.folder / 'calls.jsonl'
        self.driver = self.folder / 'record command.py'
        self.driver.write_text('''import json, os, sys
manager, args = sys.argv[1], sys.argv[2:]
with open(os.environ['PM_CALL_LOG'], 'a') as log:
    log.write(json.dumps({'manager': manager, 'args': args, 'cwd': os.getcwd()}) + '\\n')
if args == ['--version']:
    print(os.environ['PM_VERSION'])
elif args[:1] == ['run']:
    print('# tests 1\\n# suites 0\\n# pass 1\\n# fail 0\\n# cancelled 0\\n# skipped 0\\n# todo 0')
if args[:1] == [os.environ.get('PM_FAIL_COMMAND', 'fail')]:
    sys.exit(42)
''')
        environment = patch.dict(os.environ, {
            'PATH': str(self.bin) + os.pathsep + os.environ['PATH'],
            'PM_CALL_LOG': str(self.log), 'PM_VERSION': '12.14.0',
            'CI_NODE_STORE': str(self.folder / 'store'),
        })
        environment.start()
        self.addCleanup(environment.stop)
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)

    def launcher(self, manager='pnpm', *, shebang=False):
        target = self.bin / manager
        source = '#!/bin/sh\n' if shebang else '# Intentionally shebang-less, as shipped by pnpm 12.\n'
        source += 'exec ' + shlex.join([sys.executable, '-I', str(self.driver), manager]) + ' "$@"\n'
        target.write_text(source)
        target.chmod(0o755)
        return target

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def put(self, name, value):
        (self.root / name).write_text(json.dumps(value) if isinstance(value, dict) else value)
        subprocess.run(['git', 'add', '--', name], cwd=self.root, check=True)

    def plan(self, manager='pnpm', version='12.14.0'):
        self.put('package.json', {'name': 'launch-fixture', 'packageManager': manager + '@' + version,
                                 'scripts': {'test': 'node --test'}})
        self.put('pnpm-lock.yaml' if manager == 'pnpm' else 'package-lock.json',
                 "lockfileVersion: '9.0'\n" if manager == 'pnpm' else '{}\n')
        return auto.discover(self.root)

    def test_shebangless_launcher_reproduces_exec_format_error(self):
        target = self.launcher()
        with self.assertRaises(OSError) as failure:
            subprocess.run([str(target), '--version'], cwd=self.root, check=True)
        self.assertEqual(failure.exception.errno, errno.ENOEXEC)
        self.assertEqual(auto.run(['pnpm', '--version'], self.root, capture=True), '12.14.0\n')

    def test_shell_characters_and_empty_arguments_remain_literal(self):
        self.launcher()
        marker = self.root / 'must-not-exist'
        args = ['echo', '', 'two words', "single'quote", 'double"quote',
                '$(touch ' + shlex.quote(str(marker)) + ')',
                '`touch ' + shlex.quote(str(marker)) + '`',
                '; touch ' + shlex.quote(str(marker)), '*', '$HOME', 'line\nbreak']
        auto.run(['pnpm', *args], self.root, capture=True)
        self.assertEqual(self.calls(), [{'manager': 'pnpm', 'args': args, 'cwd': str(self.root)}])
        self.assertFalse(marker.exists())

    def test_existing_shebang_launcher_still_runs(self):
        self.launcher(shebang=True)
        self.assertEqual(auto.run(['pnpm', '--version'], self.root, capture=True), '12.14.0\n')

    def test_project_bash_on_path_cannot_intercept_pnpm(self):
        self.launcher()
        # execute() prepends .venv/bin for mixed Python/Node projects. A Python
        # console script named bash must not replace the runner's fallback shell.
        venv_bin = self.root / '.venv/bin'
        venv_bin.mkdir(parents=True)
        shadow = venv_bin / 'bash'
        shadow.write_text('#!/bin/sh\nexit 0\n')
        shadow.chmod(0o755)
        with patch.dict(os.environ, {'PATH': str(venv_bin) + os.pathsep + os.environ['PATH']}):
            self.assertEqual(auto.run(['pnpm', '--version'], self.root, capture=True), '12.14.0\n')
        self.assertEqual(self.calls()[0]['args'], ['--version'])

    def test_native_executable_still_runs(self):
        native = Path('/bin/echo')
        self.assertEqual(native.read_bytes()[:4], b'\x7fELF')
        (self.bin / 'pnpm').symlink_to(native)
        self.assertEqual(auto.run(['pnpm', 'native', 'two words'], self.root, capture=True),
                         'native two words\n')

    def test_npm_keeps_direct_exec_semantics(self):
        self.launcher('npm')
        # An exec PATH search may continue past ENOEXEC to another installed npm.
        with patch.dict(os.environ, {'PATH': str(self.bin)}):
            with self.assertRaises(OSError) as failure:
                auto.run(['npm', '--version'], self.root, capture=True)
        self.assertEqual(failure.exception.errno, errno.ENOEXEC)
        self.launcher('npm', shebang=True)
        self.assertEqual(auto.run(['npm', '--version'], self.root, capture=True), '12.14.0\n')

    def test_nonzero_exit_is_not_suppressed(self):
        self.launcher()
        with self.assertRaisesRegex(auto.Invalid, r'Command failed \(exit 42\): pnpm'):
            auto.run(['pnpm', 'fail'], self.root, capture=True)

    def test_version_install_selected_check_and_audit_use_launcher(self):
        self.launcher()
        self.launcher('npm', shebang=True)
        plan = self.plan()
        with patch.object(auto, 'node_versions'):
            auto.install(plan, self.root)
        state = auto.execute(plan, self.root, self.folder / 'state.json')
        self.assertTrue(state['complete'])
        self.assertEqual(state['tests'], 'executed')
        self.assertEqual([(c['manager'], c['args']) for c in self.calls()], [
            ('npm', ['install', '--global', '--ignore-scripts', '--no-audit', '--no-fund', 'pnpm@12.14.0']),
            ('pnpm', ['--version']),
            ('pnpm', ['install', '--frozen-lockfile', '--ignore-scripts', '--store-dir', os.environ['CI_NODE_STORE']]),
            ('pnpm', ['run', 'test']),
            ('pnpm', ['audit', '--audit-level=high']),
        ])

    def test_pinned_npm_install_and_checks_preserve_existing_commands(self):
        self.launcher('npm', shebang=True)
        with patch.dict(os.environ, {'PM_VERSION': '11.6.0'}):
            plan = self.plan('npm', '11.6.0')
            with patch.object(auto, 'node_versions'):
                auto.install(plan, self.root)
            state = auto.execute(plan, self.root, self.folder / 'state.json')
        self.assertTrue(state['complete'])
        self.assertEqual([c['args'] for c in self.calls()], [
            ['install', '--global', '--ignore-scripts', '--no-audit', '--no-fund', 'npm@11.6.0'],
            ['--version'], ['ci', '--ignore-scripts', '--no-audit', '--no-fund'],
            ['run', 'test'], ['audit', '--audit-level=high'],
        ])

    def test_version_mismatch_still_stops_install(self):
        self.launcher()
        self.launcher('npm', shebang=True)
        plan = self.plan()
        with patch.object(auto, 'node_versions'), patch.dict(os.environ, {'PM_VERSION': '12.4.2'}):
            with self.assertRaisesRegex(auto.Invalid, 'Package manager version mismatch'):
                auto.install(plan, self.root)
        self.assertEqual([c['args'] for c in self.calls() if c['manager'] == 'pnpm'], [['--version']])

    def test_check_and_audit_failure_never_mark_complete(self):
        self.launcher()
        plan = self.plan()
        for command, kind in [('run', 'test'), ('audit', 'audit')]:
            with self.subTest(command=command), patch.dict(os.environ, {'PM_FAIL_COMMAND': command}):
                state_file = self.folder / 'state.json'
                with self.assertRaisesRegex(auto.Invalid, r'Command failed \(exit 42\)'):
                    auto.execute(plan, self.root, state_file)
                state = json.loads(state_file.read_text())
                self.assertFalse(state['complete'])
                self.assertEqual(state['checks'][-1]['kind'], kind)
                self.assertEqual(state['checks'][-1]['result'], 'failure')

    def test_yarn_declaration_remains_unsupported(self):
        self.put('package.json', {'packageManager': 'yarn@1.22.22'})
        with self.assertRaisesRegex(auto.Invalid, 'packageManager must pin npm or pnpm'):
            auto.discover(self.root)

    def test_yarn_lock_remains_unsupported(self):
        self.put('package.json', {'name': 'yarn-fixture'})
        self.put('yarn.lock', '# yarn lockfile v1\n')
        with self.assertRaisesRegex(auto.Invalid, 'Unsupported dependency/build metadata'):
            auto.discover(self.root)

    def test_explicit_node_profile_still_rejects_yarn(self):
        self.put('package.json', {'packageManager': 'yarn@1.22.22'})
        self.put('yarn.lock', '# yarn lockfile v1\n')
        workflow = yaml.safe_load((ROOT / '.github/workflows/node.yml').read_text())
        source = next(step['run'] for step in workflow['jobs']['quality']['steps'] if step.get('id') == 'config')
        env = {**os.environ, 'GITHUB_WORKSPACE': str(self.root), 'WORKING_DIRECTORY': '.',
               'JOB_TIMEOUT': '5', 'ARTIFACT_KEY': 'launch-test', 'LOCKFILE': 'yarn.lock',
               'PACKAGE_MANAGER': 'yarn', 'PACKAGE_MANAGER_VERSION': '1.22.22',
               'TEST_COMMAND': 'node --test'}
        env.update({name: '' for name in ['LINT_COMMAND', 'TYPECHECK_COMMAND', 'BUILD_COMMAND',
                                        'INTEGRATION_COMMAND', 'BROWSER_COMMAND']})
        result = subprocess.run(['bash', '-e', '-c', source], cwd=self.root, env=env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('package-manager must be npm or pnpm', result.stderr)


if __name__ == '__main__':
    unittest.main(verbosity=2)
