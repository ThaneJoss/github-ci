#!/usr/bin/env python3
"""Offline syntax and Gate checks; never runs caller application commands."""
import ast
import itertools
import os
from pathlib import Path
import re
import subprocess
import yaml

ROOT = Path(__file__).resolve().parents[1]
files = sorted((ROOT / '.github/workflows').glob('*.yml')) + sorted((ROOT / 'examples').glob('*.yml'))
bash_count = inline_count = gate_count = 0
for file in files:
    doc = yaml.safe_load(file.read_text())
    for job in doc['jobs'].values():
        for step in job.get('steps', []):
            if 'run' not in step:
                continue
            source = step['run']
            subprocess.run(['bash', '-n'], input=source, text=True, check=True)
            bash_count += 1
            for _, body in re.findall(r"<<'([A-Z_]+)'\n(.*?)\n\1(?:\n|$)", source, re.S):
                ast.parse(body)
                inline_count += 1
    if file.parent == ROOT / 'examples' and 'gate' in doc['jobs']:
        steps = doc['jobs']['gate']['steps']
        for state, passed in itertools.product(['success', 'failure', 'cancelled', 'skipped', ''], ['true', 'false', '']):
            env = {**os.environ, 'CI_RESULT': state, 'QUALITY_PASSED': passed}
            run = subprocess.run(['bash', '-e', '-o', 'pipefail', '-c', steps[0]['run']], env=env, capture_output=True)
            assert (run.returncode == 0) == (state == 'success' and passed == 'true'), (file, state, passed)
            gate_count += 1
        assert steps[1]['if'] == '${{ cancelled() }}'
        assert subprocess.run(['bash', '-e', '-o', 'pipefail', '-c', steps[1]['run']], capture_output=True).returncode != 0
        gate_count += 1

maintenance = yaml.safe_load((ROOT / '.github/workflows/validate.yml').read_text())
steps = maintenance['jobs']['gate']['steps']
for checks, docs, passed in itertools.product(['success', 'failure', 'cancelled', 'skipped', ''],
                                             ['success', 'failure', 'cancelled', 'skipped', ''],
                                             ['true', 'false', '']):
    env = {**os.environ, 'CHECKS_RESULT': checks, 'DOCS_RESULT': docs, 'DOCS_PASSED': passed, 'FIXTURES_RESULT': 'success', 'FIXTURES_PASSED': 'true'}
    run = subprocess.run(['bash', '-e', '-o', 'pipefail', '-c', steps[0]['run']], env=env, capture_output=True)
    assert (run.returncode == 0) == (checks == docs == 'success' and passed == 'true')
    gate_count += 1
assert steps[1]['if'] == '${{ cancelled() }}'
assert subprocess.run(['bash', '-e', '-o', 'pipefail', '-c', steps[1]['run']], capture_output=True).returncode != 0
gate_count += 1
for state, proof in itertools.product(['success', 'failure', 'cancelled', 'skipped', ''], ['true', 'false', '']):
    env = {**os.environ, 'CHECKS_RESULT': 'success', 'DOCS_RESULT': 'success', 'DOCS_PASSED': 'true',
           'FIXTURES_RESULT': state, 'FIXTURES_PASSED': proof}
    run = subprocess.run(['bash', '-e', '-o', 'pipefail', '-c', steps[0]['run']], env=env, capture_output=True)
    assert (run.returncode == 0) == (state == 'success' and proof == 'true')
    gate_count += 1

for helper in [*ROOT.glob('examples/helpers/*.py'), *ROOT.glob('tools/*.py'), *ROOT.glob('tools/auto/*.py'), *ROOT.glob('tools/upstream/*.py')]:
    ast.parse(helper.read_text())
print(f'PASS: {len(files)} YAML files; {bash_count} bash blocks; {inline_count} inline Python blocks; {gate_count} Gate cases.')
