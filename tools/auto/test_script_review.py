"""Regression coverage for nested package scripts and built-in test evidence."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('automatic_scripts', Path(__file__).with_name('runtime.py'))
auto = importlib.util.module_from_spec(spec)
spec.loader.exec_module(auto)


class NestedScripts(unittest.TestCase):
    def check(self, command, child='node --test'):
        checks = auto.select_scripts({'scripts': {'test': command, 'unit': child}}, '.', 'npm')
        return next(check for check in checks if check['kind'] == 'test')

    def test_options_around_run_follow_the_same_child(self):
        for command in [
            'npm run --silent unit', 'npm --silent run unit', 'npm -s run unit',
            'npm --loglevel silent run unit', 'npm run --loglevel=silent unit',
            'npm run unit --loglevel silent', 'npm run-script --silent "unit"',
            'pnpm run --silent unit', 'pnpm --silent run unit',
            'pnpm --reporter append-only run unit', 'pnpm run --reporter=append-only unit',
            'npm -- run unit', 'npm run -- unit',
        ]:
            with self.subTest(command=command):
                self.assertTrue(self.check(command)['node_test'])
                with self.assertRaisesRegex(auto.Invalid, 'deployment, release'):
                    self.check(command, 'npm publish')

    def test_ambiguous_options_fail_before_the_wrong_package_is_validated(self):
        for command in [
            'npm --prefix elsewhere run unit', 'npm run --workspace=b unit',
            'npm run unit --workspace=b', 'npm run unit -w b',
            'npm run unit --prefix="some;directory"', 'pnpm --filter b run unit',
            'pnpm run --recursive unit', 'npm --mystery run unit',
        ]:
            with self.subTest(command=command), self.assertRaisesRegex(auto.Invalid, 'Unsupported nested'):
                self.check(command)

    def test_arguments_are_not_reinterpreted_as_manager_options(self):
        self.assertTrue(self.check('npm run unit -- --workspace=b --test-reporter=tap')['node_test'])
        self.assertTrue(self.check('pnpm run unit --test-reporter=tap')['node_test'])

    def test_non_run_commands_are_not_parsed_as_nested_scripts(self):
        for command in ['npm --version && node --test', 'pnpm --version; node --test',
                        'echo npm --version && node --test', 'npm exec -- tsc --noEmit',
                        'echo "npm run missing"', 'node -e "console.log(\'npm run missing\')"']:
            with self.subTest(command=command):
                self.assertEqual(list(auto.nested_scripts(command)), [])

    def test_all_commands_and_recursive_children_are_validated(self):
        for separator in [' && ', '; ', '\n']:
            with self.subTest(separator=separator):
                scripts = {'test': 'npm --silent run first' + separator + 'npm run --silent second',
                           'first': 'node --test', 'second': 'npm run --loglevel=silent bad',
                           'bad': 'npm publish'}
                with self.assertRaisesRegex(auto.Invalid, 'deployment, release'):
                    auto.select_scripts({'scripts': scripts}, '.', 'npm')

    def test_transitive_node_test_detection_and_non_test_wrapper(self):
        scripts = {'test': 'npm run --silent unit', 'unit': 'npm --silent run real', 'real': 'node --test'}
        self.assertTrue(auto.select_scripts({'scripts': scripts}, '.', 'npm')[0]['node_test'])
        self.assertFalse(self.check('npm run --silent unit', 'node verify.cjs')['node_test'])

    def test_missing_names_and_option_values_fail_clearly(self):
        for command, message in [
            ('npm run --silent absent', 'Unknown nested script'),
            ('npm run --silent', 'literal script name'),
            ('npm run --loglevel', 'Missing value'),
            ('npm run --loglevel= unit', 'Missing value'),
            ('npm run "$NAME"', 'literal script name'),
        ]:
            with self.subTest(command=command), self.assertRaisesRegex(auto.Invalid, message):
                self.check(command)

    @unittest.skipUnless(shutil.which('npm') and shutil.which('node'), 'requires local Node and npm')
    def test_wrapped_runner_rejects_empty_skipped_and_todo_suites(self):
        for source, error in [
            (None, 'no test cases'),
            ("require('node:test').skip('not executed', () => {});\n", 'skipped tests/todo'),
            ("require('node:test').todo('not implemented');\n", 'skipped tests/todo'),
            ("require('node:test')('executed', () => {});\n", None),
        ]:
            with self.subTest(source=source), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                package = {'scripts': {'test': 'npm --silent run unit',
                                       'unit': 'npm run --silent native', 'native': 'node --test'}}
                (root / 'package.json').write_text(json.dumps(package))
                if source is not None:
                    (root / 'suite.test.cjs').write_text(source)
                plan = {'checks': auto.select_scripts(package, '.', 'npm'), 'node': None,
                        'python': None, 'locks': {}}
                state_file = root / 'state.json'
                with patch.dict(os.environ, {'npm_config_ignore_scripts': 'true'}):
                    if error:
                        with self.assertRaisesRegex(auto.Invalid, error):
                            auto.execute(plan, root, state_file)
                        state = json.loads(state_file.read_text())
                        self.assertFalse(state['complete'])
                        self.assertEqual(state['checks'][0]['result'], 'failure')
                    else:
                        state = auto.execute(plan, root, state_file)
                        self.assertTrue(state['complete'])
                        self.assertEqual(state['tests'], 'executed')


if __name__ == '__main__':
    unittest.main()
