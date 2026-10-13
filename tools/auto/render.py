#!/usr/bin/env python3
"""Embed exact-version runtime into reusable workflow, or verify there is no drift."""
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[2]
source = (root / 'tools/auto/runtime.py').read_text()
body = '\n'.join('          ' + line if line else '' for line in source.rstrip().splitlines())
rendered = (root / 'tools/auto/workflow.yml.in').read_text().replace('@@RUNTIME@@', body)
target = root / '.github/workflows/auto.yml'
if '--check' in sys.argv:
    if target.read_text() != rendered:
        raise SystemExit('auto.yml differs from its reviewed runtime/template; run python3 tools/auto/render.py')
    print('PASS: called workflow embeds exact reviewed runtime')
else:
    target.write_text(rendered)
