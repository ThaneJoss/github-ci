"""Each workspace member must own the checks that justify its source support."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest


spec = importlib.util.spec_from_file_location('member_coverage_auto', Path(__file__).with_name('runtime.py'))
auto = importlib.util.module_from_spec(spec)
spec.loader.exec_module(auto)


class MemberCoverage(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)

    def put(self, path, value):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(value) if isinstance(value, dict) else value)
        subprocess.run(['git', 'add', '--', path], cwd=self.root, check=True)

    def workspace(self, scripts=None, patterns=None):
        self.put('package.json', {'workspaces': patterns or ['packages/*'], 'scripts': scripts or {}})

    def member(self, name, scripts=None):
        self.put(name + '/package.json', {'scripts': scripts or {}})

    def test_unrelated_build_rejects_invalid_sibling_typescript_before_execution(self):
        self.workspace()
        self.member('packages/a', {'build': 'node --check index.cjs'})
        self.put('packages/a/index.cjs', 'const okay = 1;\n')
        self.member('packages/b')
        self.put('packages/b/broken.ts', 'const : = syntax error !!!\n')
        with self.assertRaisesRegex(auto.Invalid, r'owning package.*packages/b/broken.ts.*packages/b'):
            auto.discover(self.root)
        self.assertFalse((self.root / 'state.json').exists())

    def test_root_standard_script_does_not_cover_a_member(self):
        self.member('packages/a')
        self.put('packages/a/index.ts', 'const value: number = 1;\n')
        for kind in ['lint', 'typecheck', 'build']:
            with self.subTest(kind=kind):
                self.workspace({kind: 'node --check root.cjs'})
                self.put('root.cjs', 'const root = 1;\n')
                with self.assertRaisesRegex(auto.Invalid, 'owning package.*packages/a'):
                    auto.discover(self.root)

    def test_member_script_does_not_cover_root_sources(self):
        self.workspace()
        self.member('packages/a', {'build': 'node build.cjs'})
        self.put('packages/a/build.cjs', 'console.log("member build");\n')
        self.put('src/index.ts', 'const value: number = 1;\n')
        with self.assertRaisesRegex(auto.Invalid, r"src/index.ts.*'\.'"):
            auto.discover(self.root)

    def test_nested_member_needs_its_own_check(self):
        self.workspace(patterns=['packages/**'])
        self.member('packages/a', {'build': 'node build.cjs'})
        self.put('packages/a/build.cjs', 'console.log("parent build");\n')
        self.member('packages/a/inner')
        self.put('packages/a/inner/view.vue', '<template><div/></template>\n')
        with self.assertRaisesRegex(auto.Invalid, 'owning package.*packages/a/inner/view.vue.*packages/a/inner'):
            auto.discover(self.root)

    def test_all_frontend_extensions_require_member_coverage(self):
        self.workspace({'build': 'node --check root.cjs'})
        self.put('root.cjs', 'const root = 1;\n')
        self.member('packages/a')
        for extension in ['ts', 'tsx', 'jsx', 'vue', 'html', 'css', 'scss', 'sass', 'less']:
            with self.subTest(extension=extension):
                path = 'packages/a/source.' + extension
                self.put(path, 'intentionally unchecked source\n')
                with self.assertRaisesRegex(auto.Invalid, 'owning package.*' + extension):
                    auto.discover(self.root)
                subprocess.run(['git', 'rm', '-q', '-f', '--', path], cwd=self.root, check=True)

    def test_each_member_and_root_can_declare_their_own_checks(self):
        self.workspace({'build': 'node --check root.cjs'}, patterns=['packages/**'])
        self.put('root.cjs', 'const root = 1;\n')
        self.put('root.css', 'body {}\n')
        self.member('packages/a', {'lint': 'eslint .'})
        self.put('packages/a/index.ts', 'const value: number = 1;\n')
        self.member('packages/a/inner', {'typecheck': 'tsc --noEmit'})
        self.put('packages/a/inner/index.tsx', 'const value = <div/>;\n')
        plan = auto.discover(self.root)
        checks = {(c['cwd'], c['kind']) for c in plan['checks'] if c['kind'] in {'lint', 'typecheck', 'build'}}
        self.assertEqual(checks, {('.', 'build'), ('packages/a', 'lint'), ('packages/a/inner', 'typecheck')})

    def test_root_override_covers_root_only(self):
        self.put('package.json', {})
        self.put('index.ts', 'const value: number = 1;\n')
        plan = auto.discover(self.root, {'typecheck-command': 'tsc --noEmit'})
        checks = [c for c in plan['checks'] if c['kind'] == 'typecheck']
        self.assertEqual(checks[0]['argv'], ['bash', '-e', '-o', 'pipefail', '-c', 'tsc --noEmit'])
        self.workspace()
        self.member('packages/a')
        self.put('packages/a/index.ts', 'const value: number = 1;\n')
        with self.assertRaisesRegex(auto.Invalid, 'owning package.*packages/a'):
            auto.discover(self.root, {'typecheck-command': 'tsc --noEmit'})

    def test_override_cannot_count_member_checks_it_replaces(self):
        self.workspace()
        self.member('packages/a', {'build': 'tsc'})
        self.put('packages/a/index.ts', 'const value: number = 1;\n')
        self.assertTrue(auto.discover(self.root)['checks'])
        with self.assertRaisesRegex(auto.Invalid, 'owning package.*packages/a'):
            auto.discover(self.root, {'build-command': 'node --version'})

    def test_unrelated_override_preserves_member_check(self):
        self.workspace()
        self.member('packages/a', {'typecheck': 'tsc --noEmit'})
        self.put('packages/a/index.ts', 'const value: number = 1;\n')
        plan = auto.discover(self.root, {'build-command': 'node --version'})
        self.assertTrue(any(c['kind'] == 'typecheck' and c['cwd'] == 'packages/a' for c in plan['checks']))

    def test_package_prefix_does_not_steal_sibling_source(self):
        self.workspace()
        self.member('packages/a', {'build': 'node --version'})
        self.member('packages/ab')
        self.put('packages/ab/index.ts', 'const value: number = 1;\n')
        with self.assertRaisesRegex(auto.Invalid, 'owning package.*packages/ab/index.ts.*packages/ab'):
            auto.discover(self.root)

    def test_pnpm_uses_the_same_member_boundary(self):
        self.put('package.json', {'packageManager': 'pnpm@10.18.3', 'scripts': {'build': 'node --version'}})
        self.put('pnpm-workspace.yaml', "packages:\n  - 'packages/*'\n")
        self.member('packages/a')
        self.put('packages/a/index.ts', 'const value: number = 1;\n')
        with self.assertRaisesRegex(auto.Invalid, 'owning package.*packages/a'):
            auto.discover(self.root)
        self.member('packages/a', {'typecheck': 'tsc --noEmit'})
        self.assertTrue(any(c.get('argv') == ['pnpm', 'run', 'typecheck'] for c in auto.discover(self.root)['checks']))


if __name__ == '__main__':
    unittest.main()
