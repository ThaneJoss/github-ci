#!/usr/bin/env python3
"""Offline contract regression checks with generic fixtures."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('portability', ROOT / 'tools/check_portability.py')
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)
blocked = [
    '${{ github.repository }}', '${{ github.repository_owner }}',
    '${{ github.repository_id }}', '${{ github.repository_owner_id }}',
    "${{ github['repository'] }}", '${{ github["repository_owner"] }}',
    '${{ github.event.repository.name }}',
    '${{ github.event.pull_request.head.repo.full_name }}',
    '${{ github.event.pull_request.base.repo.name }}',
    '$GITHUB_REPOSITORY', '${GITHUB_REPOSITORY_OWNER}',
    '${{ inputs.owner }}', '${{ inputs.project-name }}',
    '${{ vars.repository }}', '    repository-name:\n',
    '    project-id:\n', 'git remote get-url origin',
    'git remote -v', 'git config --get remote.origin.url',
]
allowed = [
    '${{ inputs.profile }}', '${{ inputs.working-directory }}',
    '${{ inputs.artifact-key }}', '${{ github.workflow }}',
    '${{ github.event_name }}', '${{ github.event.pull_request.number }}',
    '${{ github.ref }}', '${{ runner.os }}',
    'uses: example-org/workflow-library/.github/workflows/ci.yml@' + 'a' * 40,
    'profile: node\nnode-version: 24\npackage-manager: npm\n',
    'owner: maintainer\nreason: reviewed temporary advisory exception\n',
]
for text in blocked:
    assert guard.findings(text), text
for text in allowed:
    assert not guard.findings(text), text
assert guard.findings('\n\n${{ github.repository }}')[0][1] == 3
run = subprocess.run([sys.executable, str(ROOT / 'tools/check_portability.py')],
                     text=True, capture_output=True)
assert run.returncode == 0, run.stdout + run.stderr
guard_log = run.stdout
with tempfile.TemporaryDirectory() as tmp:
    fake = Path(tmp)
    run = subprocess.run([sys.executable, str(ROOT / 'tools/check_portability.py'), tmp],
                         text=True, capture_output=True)
    assert run.returncode != 0
    workflows = fake / '.github/workflows'
    workflows.mkdir(parents=True)
    (workflows / 'ci.yml').write_text('${{ github.repository }}')
    run = subprocess.run([sys.executable, str(ROOT / 'tools/check_portability.py'), tmp],
                         text=True, capture_output=True)
    assert run.returncode != 0

print(f'PASS: {len(blocked) + len(allowed) + 3} portability cases.')
