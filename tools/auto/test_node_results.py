"""Node evidence must reject failures masked by another successful command."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('node_results_auto', Path(__file__).with_name('runtime.py'))
auto = importlib.util.module_from_spec(spec)
spec.loader.exec_module(auto)


class NodeResults(unittest.TestCase):
    def summary(self, *, marker='#', **counts):
        values = {'tests': 1, 'suites': 0, 'pass': 1, 'fail': 0,
                  'cancelled': 0, 'skipped': 0, 'todo': 0}
        values.update(counts)
        return '\n'.join(f'{marker} {name} {count}' for name, count in values.items()) + '\n'

    def execute_output(self, output, error=None, *, node_test=True):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state_file = root / 'state.json'
            plan = {'checks': [{'kind': 'test', 'cwd': '.', 'argv': ['npm', 'run', 'test'],
                                'label': 'test', 'node_test': node_test}],
                    'node': None, 'python': None, 'locks': {}}
            with patch.object(auto, 'run', return_value=output):
                if error:
                    with self.assertRaisesRegex(auto.Invalid, error):
                        auto.execute(plan, root, state_file)
                    state = json.loads(state_file.read_text())
                    self.assertFalse(state['complete'])
                    self.assertEqual(state['checks'][0]['result'], 'failure')
                    self.assertEqual(state['tests'], 'not-run')
                    return state
                return auto.execute(plan, root, state_file)

    def test_tap_spec_and_ansi_summaries_record_real_counts(self):
        for marker in ['#', 'ℹ']:
            for color in [False, True]:
                with self.subTest(marker=marker, color=color):
                    output = self.summary(marker=marker) + self.summary(marker=marker, tests=3, **{'pass': 3})
                    if color:
                        output = ''.join('\x1b[32m' + line + '\x1b[39m\n' for line in output.splitlines())
                    state = self.execute_output(output)
                    self.assertTrue(state['complete'])
                    self.assertEqual(state['tests'], 'executed')
                    self.assertEqual(state['checks'][0]['executed_tests'], 4)

    def test_failure_or_cancellation_cannot_be_masked_by_success(self):
        for marker in ['#', 'ℹ']:
            for bad in ['fail', 'cancelled']:
                for first in [False, True]:
                    with self.subTest(marker=marker, bad=bad, first=first):
                        failed = self.summary(marker=marker, **{'pass': 0, bad: 1})
                        good = self.summary(marker=marker)
                        self.execute_output(failed + good if first else good + failed, 'failed or cancelled')

    def test_any_empty_skipped_or_todo_runner_blocks_completion(self):
        for counts, message in [
            ({'tests': 0, 'pass': 0}, 'no test cases'),
            ({'pass': 0, 'skipped': 1}, 'skipped tests/todo'),
            ({'pass': 0, 'todo': 1}, 'skipped tests/todo'),
        ]:
            for first in [False, True]:
                with self.subTest(counts=counts, first=first):
                    bad, good = self.summary(**counts), self.summary()
                    self.execute_output(bad + good if first else good + bad, message)

    def test_partial_or_duplicate_summaries_are_not_success_proof(self):
        for missing in ['tests', 'suites', 'pass', 'fail', 'cancelled', 'skipped', 'todo']:
            partial = '\n'.join(line for line in self.summary().splitlines() if not line.startswith(f'# {missing} ')) + '\n'
            for output in [partial, partial + self.summary(), self.summary() + partial]:
                with self.subTest(missing=missing, output=output):
                    self.execute_output(output, 'incomplete or duplicate|incomplete summary')
        self.execute_output(self.summary() + '# pass 1\n', 'duplicate')
        self.execute_output('command finished successfully\n', 'no test cases')

    def test_inconsistent_counts_and_embedded_summary_text_are_rejected(self):
        self.execute_output(self.summary(tests=2), 'inconsistent test counts')
        self.execute_output('console.log("# tests 1");\n', 'no test cases')

    def test_unknown_runner_keeps_explicitly_unknown_count_contract(self):
        state = self.execute_output('custom runner succeeded\n', node_test=False)
        self.assertTrue(state['complete'])
        self.assertEqual(state['tests'], 'command-passed-count-unknown')
        self.assertNotIn('executed_tests', state['checks'][0])

    @unittest.skipUnless(shutil.which('npm') and shutil.which('node'), 'requires local Node and npm')
    def test_real_masked_failure_and_empty_runner_fail_but_two_successes_pass(self):
        for reporter in ['tap', 'spec']:
            for source, error, expected_count in [
                ("require('node:test')('fails', () => { throw Error('real regression'); });\n", 'failed or cancelled', None),
                ("require('node:test')('unfinished', {timeout:20}, async () => await new Promise(() => {}));\n", 'failed or cancelled', None),
                (None, 'no test cases', None),
                ("require('node:test')('passes', () => {});\n", None, 2),
                ("const {describe,it,test}=require('node:test');\n"
                 "describe('suite',()=>{it('leaf',()=>{});});\n"
                 "test('parent',async t=>{await t.test('child',()=>{});});\n", None, 4),
            ]:
                with self.subTest(reporter=reporter, error=error), tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    if source is None:
                        (root / 'empty').mkdir()
                        first = f'(cd empty && node --test --test-reporter={reporter})'
                    else:
                        (root / 'first.test.cjs').write_text(source)
                        first = f'node --test --test-reporter={reporter} first.test.cjs'
                    (root / 'second.test.cjs').write_text("require('node:test')('passes', () => {});\n")
                    command = (first + '; '
                               f'node --test --test-reporter={reporter} second.test.cjs')
                    package = {'scripts': {'test': command}}
                    (root / 'package.json').write_text(json.dumps(package))
                    plan = {'checks': auto.select_scripts(package, '.', 'npm'),
                            'node': None, 'python': None, 'locks': {}}
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
                            self.assertEqual(state['checks'][0]['executed_tests'], expected_count)


if __name__ == '__main__':
    unittest.main()
