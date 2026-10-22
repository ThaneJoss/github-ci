"""Network smoke: real package-manager releases with frozen locks and no hooks.

Each case runs the production detect/install/execute stages in separate processes.
Only disposable fixtures and tool prefixes are changed, never the host toolchain.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import yaml

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / 'tools/auto/runtime.py'
VERSIONS = ['npm@bundled', 'npm@11.6.0', 'pnpm@8.15.9', 'pnpm@10.18.3',
            'pnpm@12.4.2', 'pnpm@12.14.0']


def smoke(release):
    manager, version = release.split('@')
    with tempfile.TemporaryDirectory(prefix='github-ci-manager-') as temporary:
        folder = Path(temporary)
        root = folder / 'project with spaces'
        shutil.copytree(ROOT / 'tests/fixtures' / manager, root)
        manifest = json.loads((root / 'package.json').read_text())
        if version != 'bundled':
            manifest['packageManager'] = release
        manifest['scripts']['test:ci'] = manager + ' run test'
        for hook in ['preinstall', 'install', 'postinstall', 'pretest:ci', 'posttest:ci', 'posttest']:
            manifest['scripts'][hook] = 'node -e "throw Error(\'lifecycle hook must not run\')"'
        (root / 'package.json').write_text(json.dumps(manifest))
        if release == 'pnpm@8.15.9':
            shutil.copyfile(ROOT / 'tests/package-manager/pnpm-v6.yaml', root / 'pnpm-lock.yaml')
        elif manager == 'pnpm' and version.startswith('12.'):
            shutil.copyfile(ROOT / f'tests/package-manager/pnpm-{version}.yaml', root / 'pnpm-lock.yaml')
        subprocess.run(['git', 'init', '-q', str(root)], check=True)
        subprocess.run(['git', 'add', '.'], cwd=root, check=True)
        policy = yaml.safe_load((ROOT / '.github/workflows/auto.yml').read_text())['jobs']['quality']['env']
        env = {**os.environ, **policy, 'GITHUB_WORKSPACE': str(root),
               'GITHUB_OUTPUT': str(folder / 'outputs'), 'CI_AUTO_DIR': str(folder / 'controller'),
               'CI_NODE_STORE': str(folder / 'store'), 'CI_WORKING_DIRECTORY': '.', 'CI_OVERRIDES': '{}',
               'npm_config_cache': str(folder / 'npm-cache'), 'COREPACK_ENABLE_NETWORK': '0'}
        # Seed the Node-bundled npm version (including semver for node_versions),
        # then let install() select any declared release in this isolated prefix.
        bundled = subprocess.check_output(['npm', '--version'], text=True).strip()
        prefix = folder / 'toolchain'
        subprocess.run(['npm', 'install', '--global', '--prefix', str(prefix), '--ignore-scripts',
                        '--no-audit', '--no-fund', 'npm@' + bundled], env=env, cwd=folder, check=True)
        env['npm_config_prefix'] = str(prefix)
        env['PATH'] = str(prefix / 'bin') + os.pathsep + env['PATH']

        def stage(name, *, succeeds=True):
            result = subprocess.run([sys.executable, '-I', str(RUNTIME), name], cwd=root, env=env,
                                    text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180)
            print(result.stdout, end='', flush=True)
            if (result.returncode == 0) != succeeds:
                raise AssertionError(f'{release}: {name} returned {result.returncode}, expected success={succeeds}')
            return result.stdout

        print(f'\n=== {release} ===', flush=True)
        for name in ['detect', 'install', 'execute']:
            stage(name)
        state_path = folder / 'controller/state.json'
        state = json.loads(state_path.read_text())
        assert state['complete'] and state['tests'] == 'executed', state
        assert any(c['kind'] == 'audit' and c['result'] == 'success' for c in state['checks']), state
        lock = root / ('pnpm-lock.yaml' if manager == 'pnpm' else 'package-lock.json')
        original = lock.read_bytes()

        # A real failed nested test must never produce quality completion.
        (root / 'test/behavior.test.cjs').write_text("const test = require('node:test'); test('fails', () => { throw Error('expected regression'); });\n")
        output = stage('execute', succeeds=False)
        state = json.loads(state_path.read_text())
        assert 'expected regression' in output and not state['complete'], state
        assert state['checks'][-1]['kind'] == 'test' and state['checks'][-1]['result'] == 'failure', state

        # Frozen install rejects a manifest/lock mismatch instead of relocking.
        manifest['dependencies']['picocolors'] = '1.0.0'
        (root / 'package.json').write_text(json.dumps(manifest))
        output = stage('install', succeeds=False)
        diagnostic = 'OUTDATED_LOCKFILE' if manager == 'pnpm' else 'can only install packages when your package.json'
        assert diagnostic in output, 'Install failed for a reason other than the frozen lock mismatch'
        assert lock.read_bytes() == original, 'Frozen install changed the lock'
        print(f'PASS {release}: frozen install, nested tests, audit, disabled hooks, failure propagation', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('releases', nargs='*', choices=VERSIONS)
    for release in parser.parse_args().releases or VERSIONS:
        smoke(release)
