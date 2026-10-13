#!/usr/bin/env python3
"""Offline checks for explicit Markdown/JSON files; stdlib only.

Validates UTF-8, JSON syntax/duplicate keys, and ordinary Markdown inline and
reference local file links. Ignores code fences, inline code, remote URLs,
root-relative site routes, and fragment anchors. It is deliberately not a full
Markdown, generated-site, Obsidian wiki-link, or external URL validator.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

INLINE = re.compile(r'''!?\[[^\]\n]*\]\(\s*(?:<([^>\n]+)>|([^\s)]+))(?:\s+["'][^\n]*["'])?\s*\)''')
REFERENCE = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*(?:<([^>\n]+)>|(\S+))", re.MULTILINE)
FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")


def duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def invalid_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


def prose_only(content: str) -> str:
    content = re.sub(r"<!--.*?-->", "", content, flags=re.DOTALL)
    output: list[str] = []
    fence = ""
    minimum = 0
    for line in content.splitlines():
        match = FENCE.match(line)
        if match:
            marker = match[1]
            if not fence:
                fence, minimum = marker[0], len(marker)
            elif marker[0] == fence and len(marker) >= minimum:
                fence = ""
            continue
        if not fence and not line.startswith(("    ", "\t")):
            output.append(re.sub(r"`+[^`]*`+", "", line))
    return "\n".join(output)


def check(path: Path, root: Path) -> list[str]:
    errors: list[str] = []
    try:
        content = path.read_text(encoding="utf-8")
        if path.suffix.lower() == ".json":
            json.loads(content, object_pairs_hook=duplicate_keys, parse_constant=invalid_constant)
            return errors
    except (UnicodeError, ValueError, OSError) as error:
        return [f"{path.relative_to(root)}: {error}"]
    prose = prose_only(content)
    for pattern in (INLINE, REFERENCE):
        for match in pattern.finditer(prose):
            target = next(group for group in match.groups() if group is not None)
            try:
                url = urlsplit(target)
            except ValueError as error:
                errors.append(f"{path.relative_to(root)}: invalid link {target!r}: {error}")
                continue
            if url.scheme or url.netloc or not url.path or url.path.startswith("/"):
                continue
            local = (path.parent / unquote(url.path)).resolve()
            if not local.is_relative_to(root) or not local.exists():
                errors.append(f"{path.relative_to(root)}: missing/out-of-repository local link {target!r}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", help="Explicit Markdown/JSON files or content directories")
    args = parser.parse_args()
    root = Path.cwd().resolve()
    files: set[Path] = set()
    errors: list[str] = []
    for value in args.paths:
        path = Path(value).resolve()
        if not path.is_relative_to(root) or not path.exists():
            errors.append(f"Input path missing or outside repository: {value}")
            continue
        for candidate in path.rglob("*") if path.is_dir() else [path]:
            if candidate.is_file() and candidate.suffix.lower() in {".md", ".markdown", ".json"}:
                resolved = candidate.resolve()
                if not resolved.is_relative_to(root):
                    errors.append(f"File resolves outside repository: {candidate}")
                else:
                    files.add(resolved)
    if not files:
        errors.append("No Markdown/JSON content selected; do not use an empty check as CI evidence")
    for path in sorted(files):
        errors.extend(check(path, root))
    if errors:
        for error in errors:
            print(error)
        return 1
    print(f"Validated {len(files)} Markdown/JSON files and supported local file links (offline).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
