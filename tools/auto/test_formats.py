"""Independent synthetic formats in arbitrary directories, with negative cases.

No compatibility repository names, filenames, contents, or remote services.
Run with the locked requirements-formats.txt installed; missing tools fail tests.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from test_runtime import auto, ROOT

formats = auto.formats


class Formats(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)

    def put(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(text) if isinstance(text, dict) else text)
        subprocess.run(['git', 'add', '-f', '--', name], cwd=self.root, check=True)
        return path

    def validate(self, kind, name, text):
        self.put(name, text)
        formats.validate(kind, self.root, [name])

    def test_jsonc_valid_strings_comments_and_trailing_commas(self):
        for value in ['{"url":"https://example.invalid/a/*b*/", // c\n "x":[1,2,],}',
                      '[/*before*/{"x":"\\\"//",},]', '[true, /*after*/ ]',
                      '{"comma":",}","bracket":",]"}', '// intro\r{"a":1}\r// end']:
            with self.subTest(value=value):
                self.validate('jsonc', 'anywhere/deep/options.jsonc', value)

    def test_invalid_json_and_jsonc_are_not_normalized_away(self):
        bad = ['{,}', '[,]', '[1,,]', '{"a":,}', '{"a":1,,}', '/* unfinished',
               '{unquoted:1}', "{'key':1}", '[NaN]', '[Infinity]', '{"a":1,"a":2}',
               '[1 2]', '{"a":"unterminated}', '{"a":"line\nbreak"}']
        for value in bad:
            with self.subTest(value=value), self.assertRaises(formats.Invalid):
                self.validate('jsonc', 'odd/options.jsonc', value)
        for value in ['[1,]', '// comment\n{}', '[NaN]', '{"a":1,"a":2}']:
            with self.subTest(value=value), self.assertRaises(formats.Invalid):
                self.validate('json', 'odd/options.json', value)

    def test_dotenv_is_data_and_never_sources_expansions(self):
        marker = self.root / 'executed'
        self.validate('dotenv', 'q/r/.env.staging.example',
                      f'# header\nexport NAME = "two\nlines" # trailing\nEMPTY=\n'
                      f"LITERAL='$(touch {marker})'\nVALUE=unquoted words # comment\n")
        self.assertFalse(marker.exists())
        for name in ['.dev.vars.example', '.dev.vars.staging', '.env.production', 'arbitrary.env']:
            self.assertEqual(formats.known_kind(Path('any/subdir') / name), 'dotenv')

    def test_dotenv_rejects_malformed_assignments_without_leaking_values(self):
        for text in ['MISSING_VALUE', '3BAD=x', 'BAD-NAME=x', 'A="unclosed', "A='unclosed",
                     'A="ok" unexpected', 'A=x\nA=y', 'A=x\x00y', 'A=x\necho SECRET_VALUE']:
            with self.subTest(text=text), self.assertRaises(formats.Invalid) as raised:
                self.validate('dotenv', 'nested/.env.example', text)
            self.assertNotIn('SECRET_VALUE', str(raised.exception))

    def test_xml_well_formedness_and_no_external_entities(self):
        self.validate('xml', 'arbitrary/a.xml', '<?xml version="1.0"?><root xmlns="urn:example"><item id="a"/></root>')
        for text in ['<a><b></a>', '<a/><b/>', '<a k="1" k="2"/>',
                     '<!DOCTYPE a [<!ENTITY x SYSTEM "file:///etc/passwd">]><a>&x;</a>',
                     '<!DOCTYPE a SYSTEM "https://example.invalid/remote"><a/>']:
            with self.subTest(text=text), self.assertRaises(formats.Invalid):
                self.validate('xml', 'elsewhere/data.xml', text)

    def test_headers_blocks_and_http_field_grammar(self):
        self.validate('headers', 'arbitrary/output/_headers',
                      '# comment\n/*\n  X-Test: a: b\n  ! X-Other\nhttps://example.invalid/:name\n  Example: :name\n')
        for text in ['  X-Test: value', 'relative/path\n  X-Test: value', '/empty',
                     '/empty\n/next\n  X-Test: value', '/*\n  Bad Name: value',
                     '/*\n  missing colon', '/*\n  X-Test: value\x00', '/**\n  X: 1',
                     '/:name/:name\n  X: 1', '/*\n  X: ' + 'a' * 2000]:
            with self.subTest(text=text[:60]), self.assertRaises(formats.Invalid):
                self.validate('headers', 'q/_headers', text)

    def test_ignore_rules_are_compiled_and_markers_must_be_empty(self):
        for name in ['some/path/.assetsignore', 'any/depth/.gitignore']:
            self.validate('gitignore', name, '# comment\n**/cache/\n!keep\n\\#literal\n[ab]*\n')
            for text in ['!\n', 'dangling\\\n', 'nul\x00entry']:
                with self.subTest(name=name, text=text), self.assertRaises(formats.Invalid):
                    self.validate('gitignore', name, text)
        self.validate('empty-marker', 'a/b/.nojekyll', '')
        for text in ['\n', 'source code']:
            with self.assertRaises(formats.Invalid):
                self.validate('empty-marker', 'a/b/.nojekyll', text)
        self.put('unknown.empty', '')
        with self.assertRaisesRegex(auto.Invalid, 'Unsupported source'):
            auto.discover(self.root)

    def test_shell_syntax_never_executes_file_or_startup_scripts(self):
        marker = self.root / 'executed'
        startup = self.put('startup', f'touch {marker}\n')
        for name, header in [('tools/arbitrary.sh', '#!/bin/bash'), ('different/task', '#!/usr/bin/env sh')]:
            with patch.dict(os.environ, {'BASH_ENV': str(startup), 'ENV': str(startup)}):
                self.validate('shell', name, header + f'\ntouch {marker}\necho "$(touch {marker})"\n')
            self.assertFalse(marker.exists())
        for text in ['if true; then\n', 'echo "unterminated', '#!/bin/fish\necho hi',
                     '#!/bin/sh\narr=(a b)', '#!/bin/bash -c\necho hi', 'echo nul\x00']:
            with self.subTest(text=text), self.assertRaises(formats.Invalid):
                self.validate('shell', 'q/task.sh', text)

    def test_module_content_fallback_is_directory_and_extension_independent(self):
        marker = self.root / 'executed'
        for name in ['q/r/entry', 'assets/random.example', 'deeper/a.plugin']:
            path = self.put(name, f'export const value = (() => {{ throw Error("must not execute"); }})();\n')
            self.assertEqual(formats.content_kind(path), 'javascript-module')
        plan = auto.discover(self.root)
        self.assertIsNotNone(plan['node'])
        state = auto.execute(plan, self.root, self.root / 'state.json')
        self.assertTrue(state['complete'])
        self.assertEqual(state['tests'], 'not-run')
        self.assertFalse(marker.exists())
        self.put('q/r/entry', 'export default function ( {')
        with self.assertRaises(formats.Invalid):
            auto.execute(auto.discover(self.root), self.root, self.root / 'state.json')
        self.assertFalse(json.loads((self.root / 'state.json').read_text())['complete'])

    def test_unidentified_source_still_fails_and_all_paths_are_reported(self):
        self.put('package.json', {'name': 'random-name'})
        self.put('main.js', 'const x = 1;')
        for i in range(8):
            self.put(f'arbitrary/source-{i}.novel', 'unchecked source')
        with self.assertRaises(auto.Invalid) as raised:
            auto.discover(self.root)
        self.assertIn('8 files', str(raised.exception))
        self.assertIn('source-7.novel', str(raised.exception))

    def test_known_documentation_is_not_module_sniffed(self):
        self.put('README.md', '# Docs\n')
        self.put('LICENSE', 'Example documentation with a code sample:\nexport const value = 1;\n')
        plan = auto.discover(self.root)
        self.assertIsNone(plan['node'])
        self.assertFalse(any(c.get('format') == 'javascript-module' for c in plan['checks']))

    def test_module_parser_cannot_be_shadowed_by_caller_python_environment(self):
        self.put('q/code.payload', 'export default function ( {')
        marker = self.root / 'shadow-executed'
        binary = self.root / '.venv/bin/node'
        binary.parent.mkdir(parents=True)
        binary.write_text(f'#!/bin/sh\ntouch "{marker}"\nexit 0\n')
        binary.chmod(0o755)
        plan = auto.discover(self.root)
        plan['python'] = {'uv': True}
        with patch.dict(os.environ), self.assertRaises(auto.Invalid):
            auto.execute(plan, self.root, self.root / 'state.json')
        self.assertFalse(marker.exists())

    def test_sql_requires_standard_dialect_and_scopes_d1_to_declared_directory(self):
        self.put('unrelated/query.sql', 'SELECT 1;')
        with self.assertRaisesRegex(auto.Invalid, 'dialect is not declared'):
            auto.discover(self.root)
        self.put('wrangler.jsonc', '{"d1_databases":[{"migrations_dir":"other"}],}')
        with self.assertRaisesRegex(auto.Invalid, 'dialect is not declared'):
            auto.discover(self.root)
        self.put('unrelated/.sqlfluff', '[sqlfluff]\ndialect=sqlite\n')
        self.assertTrue(any(c.get('format') == 'sqlite' for c in auto.discover(self.root)['checks']))
        self.put('unrelated/.sqlfluff', '[sqlfluff]\ndialect=postgres\n')
        with self.assertRaisesRegex(auto.Invalid, 'Unsupported SQL dialect'):
            auto.discover(self.root)

    def test_nested_d1_metadata_and_standard_default_with_no_directory_whitelist(self):
        self.put('one/wrangler.jsonc', '{"env":{"test":{"d1_databases":[{"migrations_dir":"deep/schema"}]}}}')
        self.put('one/deep/schema/001.sql', 'CREATE TABLE a(id INTEGER);')
        self.put('two/wrangler.toml', '[[d1_databases]]\nbinding="DB"\n')
        self.put('two/migrations/002.sql', 'CREATE TABLE a(id INTEGER);')
        plan = auto.discover(self.root)
        check = next(c for c in plan['checks'] if c.get('format') == 'sqlite')
        self.assertEqual(len(check['files']), 2)
        formats.validate('sqlite', self.root, check['files'])
        self.put('one/wrangler.jsonc', '{"d1_databases":[{"migrations_dir":"../../outside"}]}')
        with self.assertRaisesRegex(auto.Invalid, 'leaves checkout'):
            auto.discover(self.root)

    def test_sql_parses_whole_file_without_schema_or_execution(self):
        marker = self.root / 'database-created'
        sql = f"ATTACH DATABASE '{marker}' AS other;\nCREATE TABLE a(id INTEGER PRIMARY KEY, name TEXT);\n"
        sql += "INSERT INTO a VALUES (1, 'semi;colon');\nALTER TABLE a ADD COLUMN extra TEXT;\n"
        sql += "CREATE INDEX idx ON a(extra);\nDELETE FROM a WHERE id = 1;\n"
        self.validate('sqlite', 'anywhere/migration.sql', sql)
        self.assertFalse(marker.exists())
        self.validate('sqlite', 'unrelated/other.sql', 'ALTER TABLE existing RENAME COLUMN old TO new;')
        for text in ['CREATE TABL a(id INT);', 'SELECT FROM;', 'SELECT 1; nonsense;',
                     'CREATE TABLE a (', 'SELECT {{ dangerous() }};', '-- sqlfluff:templater:jinja\nSELECT 1;',
                     '-- sqlfluff:large_file_skip_byte_limit:1\nSELECT FROM;',
                     'SELECT FROM; -- noqa: PRS', 'SELECT `unclosed;', "SELECT 'unclosed;"]:
            with self.subTest(text=text), self.assertRaises(formats.Invalid):
                self.validate('sqlite', 'random/bad.sql', text)

    def test_sql_parser_does_not_load_caller_configs_or_modules(self):
        self.put('.sqlfluff', '[sqlfluff]\ndialect=sqlite\ntemplater=jinja\nlarge_file_skip_byte_limit=1\nignore=parsing\n')
        self.put('sqlfluff.py', 'raise RuntimeError("caller module loaded")')
        self.put('bad.sql', 'SELECT FROM; -- noqa\n')
        command = [sys.executable, '-I', str(ROOT / 'tools/auto/formats.py'), 'sqlite', 'bad.sql']
        result = subprocess.run(command, cwd=self.root, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Invalid sqlite file', result.stderr)
        self.assertNotIn('caller module loaded', result.stderr)

    def test_format_failure_propagates_before_scripts_and_cannot_be_overridden(self):
        self.put('package.json', {'name': 'generic', 'scripts': {'test': 'node --test'}})
        self.put('deep/.env.example', 'BAD VALUE')
        plan = auto.discover(self.root, {'lint-command': 'echo lint', 'test-command': 'echo test'})
        with patch.object(auto, 'run') as run, self.assertRaises(auto.Invalid):
            auto.execute(plan, self.root, self.root / 'state.json')
        run.assert_not_called()
        state = json.loads((self.root / 'state.json').read_text())
        self.assertFalse(state['complete'])
        self.assertEqual(state['checks'][-1]['result'], 'failure')
        self.assertEqual(state['tests'], 'not-run')

    def test_external_parser_failure_and_missing_tool_never_complete(self):
        self.put('.sqlfluff', '[sqlfluff]\ndialect=sqlite\n')
        self.put('q/query.sql', 'SELECT 1;')
        plan = auto.discover(self.root)
        controller = self.root / 'controller'
        controller.mkdir()
        toolchain = controller / 'format-tools'
        toolchain.symlink_to(sys.prefix, target_is_directory=True)
        with patch.dict(os.environ, {'CI_AUTO_DIR': str(controller)}):
            self.assertTrue(auto.execute(plan, self.root, self.root / 'state.json')['complete'])
            self.put('q/query.sql', 'SELECT FROM; -- noqa: PRS')
            with self.assertRaises(auto.Invalid):
                auto.execute(plan, self.root, self.root / 'state.json')
            state = json.loads((self.root / 'state.json').read_text())
            self.assertFalse(state['complete'])
            self.assertEqual(state['checks'][-1]['result'], 'failure')
            toolchain.unlink()
            with self.assertRaises(OSError):
                auto.execute(plan, self.root, self.root / 'state.json')
            self.assertFalse(json.loads((self.root / 'state.json').read_text())['complete'])

    def test_workspace_members_each_keep_their_format_checks(self):
        self.put('package.json', {'name': 'any-root', 'workspaces': ['areas/*']})
        self.put('areas/a/package.json', {'name': 'one'})
        self.put('areas/b/package.json', {'name': 'two'})
        self.put('areas/a/config/options.jsonc', '{"ok":true}')
        self.put('areas/b/config/options.jsonc', '{broken}')
        plan = auto.discover(self.root)
        with self.assertRaises(auto.Invalid):
            auto.execute(plan, self.root, self.root / 'state.json')
        self.assertFalse(json.loads((self.root / 'state.json').read_text())['complete'])


if __name__ == '__main__':
    unittest.main()
