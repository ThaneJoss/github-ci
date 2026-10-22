"""Static format checks; embedded beside the trusted controller, never sourced.

Recognition uses extensions, documented file conventions or explicit module syntax.
No repository identities, deployment commands, database connections or shell eval.
"""
from __future__ import annotations

import argparse
import configparser
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tomllib
import xml.etree.ElementTree as ET

MAX_FILE = 8 * 1024 * 1024
TOOL_KINDS = {'sqlite', 'gitignore'}


class Invalid(ValueError):
    pass


def require(ok, message):
    if not ok:
        raise Invalid(message)


def read(path):
    require(path.is_file() and not path.is_symlink(), f'Expected regular file: {path}')
    require(path.stat().st_size <= MAX_FILE, f'File exceeds 8 MiB: {path}')
    return path.read_text(encoding='utf-8')


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'Duplicate JSON key')
        result[key] = value
    return result


def json_data(text, *, comments=False):
    if comments:
        # Preserve strings and line positions. A regex comment substitution would
        # corrupt URLs, escaped quotes and comment delimiters inside strings.
        output = []
        index = 0
        while index < len(text):
            start = index
            if text[index] == '"':
                index += 1
                while index < len(text):
                    if text[index] == '\\':
                        index += 2
                    elif text[index] == '"':
                        index += 1
                        break
                    else:
                        index += 1
                output.append(text[start:index])
            elif text.startswith('//', index):
                index += 2
                while index < len(text) and text[index] not in '\r\n':
                    index += 1
                output.append(' ' * (index - start))
            elif text.startswith('/*', index):
                end = text.find('*/', index + 2)
                require(end >= 0, 'Unterminated JSONC comment')
                index = end + 2
                output.append(''.join(c if c in '\r\n' else ' ' for c in text[start:index]))
            else:
                output.append(text[index])
                index += 1
        text = ''.join(output)
        # JSONC ecosystem extension: one trailing comma after a value/member.
        tokens = list(re.finditer(r'"(?:[^"\\]|\\.)*"|[^\s]', text))
        positions = {token.start() for i, token in enumerate(tokens)
                     if token[0] == ',' and i and i + 1 < len(tokens)
                     and tokens[i - 1][0] not in {'[', '{', ',', ':'}
                     and tokens[i + 1][0] in {']', '}'}}
        text = ''.join(' ' if i in positions else c for i, c in enumerate(text))
    def constant(_):
        raise Invalid('Non-finite JSON number')
    return json.loads(text, object_pairs_hook=unique, parse_constant=constant)


def dotenv(text):
    """Strict Node-style assignment grammar; values are never interpolated."""
    require(not re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', text), 'Control character in dotenv')
    index = 0
    keys = set()
    while index < len(text):
        blank = re.match(r'[ \t\r\n]*(?:#[^\n]*(?:\n|$))?', text[index:])
        index += blank.end()
        if index == len(text):
            break
        if blank[0].lstrip().startswith('#'):
            continue
        assignment = re.match(r'(?:export[ \t]+)?([A-Za-z_][A-Za-z0-9_]*)[ \t]*=[ \t]*', text[index:])
        require(assignment, 'Expected dotenv NAME=value assignment')
        require(assignment[1] not in keys, 'Duplicate dotenv variable')
        keys.add(assignment[1])
        index += assignment.end()
        if index < len(text) and text[index] in {'"', "'"}:
            quote = text[index]
            index += 1
            while index < len(text) and text[index] != quote:
                if text[index] == '\\' and quote == '"':
                    index += 1
                index += 1
            require(index < len(text), 'Unterminated dotenv quoted value')
            index += 1
            tail = re.match(r'[ \t\r]*(?:#[^\n]*)?(?:\n|$)', text[index:])
            require(tail, 'Unexpected text after dotenv quoted value')
            index += tail.end()
        else:
            end = text.find('\n', index)
            index = len(text) if end < 0 else end + 1


def headers(text):
    """Cloudflare/Netlify-style _headers blocks, HTTP field-name grammar."""
    field = r"[!#$%&'*+.^_`|~0-9A-Za-z-]+"
    rules = 0
    entries = 0
    for line in text.splitlines():
        require(len(line) <= 2000, '_headers line exceeds 2000 characters')
        require(not re.search(r'[\x00-\x08\x0b-\x1f\x7f]', line), 'Control character in _headers')
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        if not line.startswith((' ', '\t')):
            require(not rules or entries, '_headers route has no header entries')
            require(re.fullmatch(r'(?:/[^\s]*|https://[^/\s?#]+/[^\s]*)', line)
                    and not line.startswith('//') and '?' not in line and '#' not in line,
                    'Expected _headers absolute path or HTTPS URL pattern')
            require(line.count('*') <= 1, '_headers supports at most one splat per route')
            placeholders = re.findall(r':([A-Za-z]\w*)', line.removeprefix('https://'))
            require(len(set(placeholders)) == len(placeholders), 'Duplicate _headers route placeholder')
            rules += 1
            require(rules <= 100, '_headers exceeds 100 rules')
            entries = 0
        else:
            require(rules, '_headers field before a route')
            entry = line.strip()
            require(re.fullmatch(r'!\s+' + field, entry)
                    or re.fullmatch(field + r':[ \t]*[^\r\n]*', entry), 'Invalid _headers field')
            entries += 1
    require(not rules or entries, '_headers route has no header entries')


def sqlfluff_config(path):
    config = configparser.ConfigParser(interpolation=None)
    config.read_string(read(path))
    return config.get('sqlfluff', 'dialect', fallback='').strip()


def sqlite_paths(root, files):
    """Resolve dialects from standard declarations, without executing config."""
    scopes = []
    declarations = {}
    for value in files:
        path = Path(value)
        if path.name == '.sqlfluff':
            dialect = sqlfluff_config(root / value)
            if dialect:
                declarations[path.parent] = dialect
        elif path.name in {'wrangler.json', 'wrangler.jsonc', 'wrangler.toml'}:
            text = read(root / value)
            config = tomllib.loads(text) if path.suffix == '.toml' else json_data(text, comments=path.suffix == '.jsonc')
            require(isinstance(config, dict), f'Expected configuration object: {value}')
            environments = config.get('env', {})
            require(isinstance(environments, dict), f'Expected Wrangler env object: {value}')
            for section in [config, *environments.values()]:
                require(isinstance(section, dict), f'Expected Wrangler environment object: {value}')
                bindings = section.get('d1_databases', [])
                require(isinstance(bindings, list), f'Expected D1 binding list: {value}')
                for binding in bindings:
                    require(isinstance(binding, dict), f'Expected D1 binding object: {value}')
                    directory = binding.get('migrations_dir', 'migrations')
                    require(isinstance(directory, str) and directory and not Path(directory).is_absolute(),
                            f'D1 migrations_dir must be a relative directory: {value}')
                    resolved = (root / path.parent / directory).resolve()
                    require(resolved.is_relative_to(root), f'D1 migrations_dir leaves checkout: {value}')
                    scopes.append(resolved.relative_to(root))
    result = []
    for value in files:
        path = Path(value)
        if path.suffix.lower() != '.sql':
            continue
        dialect = next((declarations[p] for p in path.parents if p in declarations), '')
        d1 = any(path.is_relative_to(scope) for scope in scopes)
        require(not dialect or dialect == 'sqlite', f'Unsupported SQL dialect {dialect!r}: {value}; automatic SQL currently supports SQLite only')
        require(dialect == 'sqlite' or d1,
                f'SQL dialect is not declared: {value}; use .sqlfluff [sqlfluff] dialect=sqlite or a Wrangler D1 migrations_dir')
        result.append(value)
    return result


def known_kind(path):
    name, suffix = path.name, path.suffix.lower()
    if suffix in {'.json', '.jsonc', '.toml', '.xml', '.svg'}:
        return suffix[1:]
    if re.fullmatch(r'\.(?:env|dev\.vars)(?:\.[A-Za-z0-9_-]+)*', name) or suffix == '.env':
        return 'dotenv'
    if name in {'.gitignore', '.assetsignore'}:
        return 'gitignore'
    if name == '.nojekyll':
        return 'empty-marker'
    if name == '_headers':
        return 'headers'
    if name == '.sqlfluff':
        return 'sqlfluff-config'
    if suffix in {'.sh', '.bash'}:
        return 'shell'
    return None


def content_kind(path):
    """Conservative fallback for otherwise unknown filenames, not all text files."""
    try:
        text = read(path)
    except UnicodeError:
        return None
    if re.match(r'#![^\n]*\b(?:bash|sh|dash)(?:\s|$)', text):
        return 'shell'
    if re.search(r'^\s*(?:export\s+(?:default\b|(?:async\s+)?function\b|class\b|const\b|let\b|var\b|\{|\*)|import\s+(?:[\w*{]|[\'\"]))', text, re.M):
        return 'javascript-module'
    return None


def syntax_process(argv, text, *, path):
    # Do not inherit loader/startup injection into a static parser subprocess.
    env = {k: v for k, v in os.environ.items()
           if k not in {'BASH_ENV', 'ENV', 'NODE_OPTIONS', 'SHELLOPTS', 'BASHOPTS'}
           and not k.startswith('BASH_FUNC_')}
    result = subprocess.run(argv, input=text, text=True, capture_output=True, env=env, timeout=60, cwd='/')
    # Syntax diagnostics can contain literal env values/source: only report path/status.
    require(result.returncode == 0, f'Syntax validation failed: {path} ({Path(argv[0]).name}, exit {result.returncode})')


def validate(kind, root, files, *, node=None):
    for value in files:
        path = root / value
        try:
            text = read(path)
            if kind in {'json', 'jsonc'}:
                json_data(text, comments=kind == 'jsonc')
            elif kind == 'toml':
                tomllib.loads(text)
            elif kind == 'dotenv':
                dotenv(text)
            elif kind in {'xml', 'svg'}:
                require(not re.search(r'<!\s*(?:DOCTYPE|ENTITY)\b', text, re.I), 'DTD/entities are not supported')
                ET.fromstring(text)
            elif kind == 'headers':
                headers(text)
            elif kind == 'empty-marker':
                require(not text, '.nojekyll must be empty')
            elif kind == 'sqlfluff-config':
                sqlfluff_config(path)
            elif kind == 'gitignore':
                from pathspec import GitIgnoreSpec
                require(not re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', text), 'Control character in ignore rules')
                GitIgnoreSpec.from_lines(text.splitlines())
            elif kind == 'shell':
                require('\0' not in text, 'NUL in shell source')
                shebang = text.splitlines()[0] if text else ''
                if shebang.startswith('#!'):
                    match = re.fullmatch(r'#!\s*(?:/usr/bin/env[ \t]+)?(?:/(?:usr/)?bin/)?(bash|sh|dash)[ \t]*', shebang)
                    require(match, 'Unsupported shell shebang/options; use an explicit syntax check')
                    shell = match[1]
                else:
                    shell = 'bash'
                argv = ['/bin/bash', '--noprofile', '--norc', '-n'] if shell == 'bash' else ['/bin/dash', '-n']
                syntax_process(argv, text, path=value)
            elif kind == 'javascript-module':
                binary = node or shutil.which('node')
                require(binary, 'Node is required for module syntax validation')
                syntax_process([binary, '--input-type=module', '--check'], text, path=value)
            elif kind == 'sqlite':
                from sqlfluff.core import FluffConfig, Linter
                # No local/user config, templates, noqa suppression, or in-file
                # config that could switch dialect/templater or skip a file.
                require(not re.search(r'^\s*--\s*sqlfluff\b', text, re.M), 'SQL inline parser directives are unsupported')
                config = FluffConfig(overrides={'dialect': 'sqlite', 'templater': 'raw',
                                               'large_file_skip_byte_limit': 0}, ignore_local_config=True)
                parsed = Linter(config=config).parse_string(text)
                if parsed.violations:
                    error = parsed.violations[0]
                    raise Invalid(f'SQLFluff SQLite parse error at line {error.line_no}, column {error.line_pos}')
                variant = parsed.root_variant()
                require(variant and variant.tree, 'SQL parser returned no tree')
                require(not list(variant.tree.recursive_crawl('unparsable')), 'Unparsed SQL content')
            else:
                raise Invalid(f'Unknown validator: {kind}')
        except Invalid as error:
            raise Invalid(f'Invalid {kind} file: {value}: {error}') from None
        except (ValueError, UnicodeError, ET.ParseError, configparser.Error) as error:
            # Do not echo source data, duplicate keys, dotenv values or SQL literals.
            raise Invalid(f'Invalid {kind} file: {value} ({type(error).__name__})') from None


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('kind', choices=sorted(TOOL_KINDS))
    parser.add_argument('files', nargs='+')
    args = parser.parse_args()
    try:
        validate(args.kind, Path.cwd(), args.files)
    except (Invalid, OSError, subprocess.SubprocessError) as error:
        print(error, file=sys.stderr)
        raise SystemExit(1)
