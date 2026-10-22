"""Regression cases for unsupported source detection in mixed repositories."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from test_runtime import auto


class MixedSources(unittest.TestCase):
    def detect(self, files):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            for name, content in files.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(content) if isinstance(content, dict) else content)
            subprocess.run(['git', 'add', '.'], cwd=root, check=True)
            return auto.discover(root)

    def test_secondary_sources_rejected_with_each_supported_runtime(self):
        runtimes = [
            {'package.json': {'name': 'mixed'}, 'index.js': 'const n = 1;\n'},
            {'index.js': 'const n = 1;\n'},
            {'pyproject.toml': '[project]\nname = "mixed"\nversion = "1"\n', 'app.py': 'value = 1\n'},
            {'app.py': 'value = 1\n'},
            {'index.js': 'const n = 1;\n', 'app.py': 'value = 1\n'},
        ]
        for runtime in runtimes:
            for source in ['infra/main.tf', 'src/Main.java', 'main.rs', 'script.sh', 'source.unknown']:
                with self.subTest(runtime=list(runtime), source=source):
                    with self.assertRaisesRegex(auto.Invalid, 'Unsupported source'):
                        self.detect({**runtime, source: 'invalid unchecked source\n'})

    def test_supported_mixed_sources_and_runtime_metadata_remain_valid(self):
        plan = self.detect({
            'package.json': {'name': 'mixed'}, 'index.js': 'const n = 1;\n',
            'app.py': 'value = 1\n', '.nvmrc': '24\n', '.node-version': '24\n',
            '.python-version': '3.13\n', '.npmrc': 'fund=false\n',
            'README.md': '# Mixed\n', 'assets/icon.svg': '<svg/>\n',
        })
        self.assertIsNotNone(plan['node'])
        self.assertIsNotNone(plan['python'])

    def test_frontend_sources_require_a_declared_check(self):
        files = {'package.json': {'name': 'web'}, 'index.html': '<html/>', 'style.css': 'body {}'}
        with self.assertRaisesRegex(auto.Invalid, 'Unsupported source'):
            self.detect(files)
        files['package.json']['scripts'] = {'build': 'node build.cjs'}
        files['build.cjs'] = 'console.log("build");\n'
        self.assertTrue(any(c['kind'] == 'build' for c in self.detect(files)['checks']))

    def test_docs_only_sources_still_rejected(self):
        with self.assertRaisesRegex(auto.Invalid, 'Unsupported source'):
            self.detect({'README.md': '# Docs\n', 'infra/main.tf': 'unchecked'})

    def test_python_does_not_imply_node_source_support(self):
        with self.assertRaisesRegex(auto.Invalid, 'Unsupported source'):
            self.detect({'app.py': 'value = 1\n', 'web/index.ts': 'const value: number = 1;\n'})

    def test_python_linter_does_not_cover_frontend_sources(self):
        with self.assertRaisesRegex(auto.Invalid, 'Unsupported source'):
            self.detect({'package.json': {'name': 'web'}, 'style.css': 'body {}',
                         'pyproject.toml': '[dependency-groups]\nci = ["ruff==0.14.0"]\n',
                         'uv.lock': 'version = 1\n'})


if __name__ == '__main__':
    unittest.main()
