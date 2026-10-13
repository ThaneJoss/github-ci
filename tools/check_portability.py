#!/usr/bin/env python3
"""Check common repository-identity coupling in the public CI implementation.

This local maintenance check never queries GitHub or selects a project.
It scans workflows, caller examples and their helper scripts. It is a guard
against common identity-based routing, not a proof against arbitrary obfuscation.
Owner/repository references in `uses` are dependency locations and are allowed.
"""
from pathlib import Path
import argparse
import re

RULES = {
    'github repository identity': r"\bgithub\s*(?:\.\s*repository(?:_owner(?:_id)?|_id)?\b|\[\s*['\"]repository(?:_owner(?:_id)?|_id)?['\"]\s*\])",
    'event repository identity': r"\bgithub\s*\.\s*event\s*\.\s*(?:repository\b|pull_request\s*\.\s*(?:head|base)\s*\.\s*repo\b)",
    'repository environment identity': r"\bGITHUB_REPOSITORY(?:_OWNER(?:_ID)?|_ID)?\b",
    'identity input used for routing': r"\b(?:inputs|vars)\s*\.\s*(?:repository|repo|owner|project_name|project_id|project-name|project-id)\b",
    'repository identity input declaration': r"^\s*(?:repository|repository-name|repo|owner|project-name|project-id):\s*$",
    'git remote identity inspection': r"\bgit\s+(?:remote\s+(?:get-url|-v)|config\s+--get\s+remote\.)",
}
COMPILED = [(name, re.compile(pattern, re.MULTILINE)) for name, pattern in RULES.items()]


def findings(text):
    return [(name, text.count('\n', 0, match.start()) + 1)
            for name, pattern in COMPILED for match in pattern.finditer(text)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', nargs='?', type=Path, default=Path(__file__).resolve().parents[1])
    root = parser.parse_args().root.resolve()
    candidates = sorted(set((root / '.github/workflows').glob('*.yml'))
                        | set((root / '.github/workflows').glob('*.yaml'))
                        | set((root / 'examples').glob('*.yml'))
                        | set((root / 'examples').glob('*.yaml'))
                        | set((root / 'examples/helpers').glob('*.py')))
    if not candidates:
        raise SystemExit('No CI implementation found; empty checks do not count.')
    errors = []
    for path in candidates:
        for rule, line in findings(path.read_text(encoding='utf-8')):
            errors.append(f'{path.relative_to(root)}:{line}: {rule}')
    if errors:
        print('\n'.join(errors))
        return 1
    print(f'PASS: {len(candidates)} implementation/example files; no recognized repository-identity routing.')
    print('Review still required for custom commands, indirect aliases, and future policy changes.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
