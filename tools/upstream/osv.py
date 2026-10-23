#!/usr/bin/env python3
"""Update and run the pinned official OSV Scanner without third-party Python code."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parents[2]
PIN = Path(__file__).with_name('osv-scanner.json')
RELEASE_API = 'https://api.github.com/repos/google/osv-scanner/releases/latest'
RELEASE_BASE = 'https://github.com/google/osv-scanner/releases/download/'
ASSET = 'osv-scanner_linux_amd64'
CHECKSUM_ASSET = 'osv-scanner_SHA256SUMS'
LOCKS = ('tools/requirements-ci.txt', 'tools/auto/requirements-formats.txt')
VERSION = re.compile(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z')
SHA256 = re.compile(r'[0-9a-f]{64}\Z')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def version_tuple(value):
    require(isinstance(value, str) and VERSION.fullmatch(value), 'Invalid stable OSV version')
    return tuple(map(int, value.split('.')))


def validate_pin(pin):
    require(isinstance(pin, dict) and set(pin) == {'version', 'asset', 'sha256'},
            'OSV pin must contain exactly version, asset and sha256')
    version_tuple(pin['version'])
    require(pin['asset'] == ASSET, 'Unsupported OSV release asset')
    require(isinstance(pin['sha256'], str) and SHA256.fullmatch(pin['sha256']),
            'Invalid OSV SHA256')
    return pin


def asset_url(version, asset):
    version_tuple(version)
    require(asset in (ASSET, CHECKSUM_ASSET), 'Unsupported OSV release asset')
    return f'{RELEASE_BASE}v{version}/{asset}'


def fetch_bytes(url, limit=2 * 1024 * 1024):
    # No token is sent to release assets or redirected download hosts.
    request = urllib.request.Request(url, headers={
        'Accept': 'application/vnd.github+json' if url == RELEASE_API else 'application/octet-stream',
        'User-Agent': 'github-ci-osv-updater',
    })
    with urllib.request.urlopen(request, timeout=30) as response:
        content = response.read(limit + 1)
    require(len(content) <= limit, 'OSV upstream response exceeds size limit')
    return content


def release_pin(release, fetch=fetch_bytes):
    require(isinstance(release, dict), 'Invalid upstream release metadata')
    require(release.get('draft') is False and release.get('prerelease') is False,
            'OSV update must be a published stable release')
    tag = release.get('tag_name', '')
    require(isinstance(tag, str) and tag.startswith('v'), 'Invalid OSV release tag')
    version = tag[1:]
    version_tuple(version)
    assets = release.get('assets')
    require(isinstance(assets, list), 'Missing OSV release assets')
    selected = {}
    for name in (ASSET, CHECKSUM_ASSET):
        matches = [item for item in assets if isinstance(item, dict) and item.get('name') == name]
        require(len(matches) == 1, f'Missing or duplicate OSV release asset: {name}')
        selected[name] = matches[0]
        require(matches[0].get('browser_download_url') == asset_url(version, name),
                f'Unexpected upstream URL for {name}')
    digest = selected[ASSET].get('digest', '')
    require(isinstance(digest, str) and digest.startswith('sha256:') and SHA256.fullmatch(digest[7:]),
            'Official release asset has no valid SHA256 digest')
    checksum_text = fetch(asset_url(version, CHECKSUM_ASSET)).decode('utf-8')
    checksums = []
    for line in checksum_text.splitlines():
        match = re.fullmatch(r'([0-9a-f]{64}) [ *](\S+)', line)
        if match and match.group(2) == ASSET:
            checksums.append(match.group(1))
    require(len(checksums) == 1, 'Official checksum list must contain exactly one scanner asset')
    require(checksums[0] == digest[7:], 'Official checksum list disagrees with release digest')
    return validate_pin({'version': version, 'asset': ASSET, 'sha256': checksums[0]})


def update_pin(path=PIN, fetch=fetch_bytes):
    current = validate_pin(json.loads(path.read_text()))
    candidate = release_pin(json.loads(fetch(RELEASE_API)), fetch)
    previous_version = current['version']
    require(version_tuple(candidate['version']) >= version_tuple(previous_version),
            'Refusing to downgrade the OSV Scanner pin')
    if candidate['version'] == previous_version:
        require(candidate == current, 'Upstream changed the contents of the pinned release')
    changed = candidate != current
    if changed:
        payload = json.dumps(candidate, indent=2) + '\n'
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix='.osv-pin-', delete=False) as output:
            temporary = Path(output.name)
            output.write(payload)
        try:
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    return {'changed': changed, 'previous_version': previous_version, 'version': candidate['version']}


def download_scanner(pin, target, fetch=fetch_bytes):
    validate_pin(pin)
    binary = fetch(asset_url(pin['version'], pin['asset']), limit=150 * 1024 * 1024)
    require(hashlib.sha256(binary).hexdigest() == pin['sha256'], 'OSV binary SHA256 mismatch')
    target.write_bytes(binary)
    target.chmod(0o700)


def validate_report(report, root=ROOT):
    expected = {str((root / path).resolve()) for path in LOCKS}
    require(isinstance(report, dict) and isinstance(report.get('results'), list), 'Invalid OSV report')
    seen = set()
    count = 0
    for result in report['results']:
        require(isinstance(result, dict), 'Invalid OSV source result')
        source, packages = result.get('source'), result.get('packages')
        require(isinstance(source, dict) and source.get('type') == 'lockfile', 'Invalid OSV source')
        require(isinstance(packages, list) and packages, 'OSV did not scan a nonempty required lockfile')
        path = source.get('path')
        require(path in expected and path not in seen, 'Unexpected or duplicate OSV lockfile')
        seen.add(path)
        for package in packages:
            require(isinstance(package, dict), 'Invalid OSV package result')
            require(not package.get('vulnerabilities'), 'OSV reported vulnerabilities')
        count += len(packages)
    require(seen == expected, 'OSV report does not cover exactly the required tool locks')
    return count


def scan(pin_path=PIN):
    pin = validate_pin(json.loads(pin_path.read_text()))
    with tempfile.TemporaryDirectory(prefix='github-ci-osv-', dir=os.environ.get('RUNNER_TEMP')) as directory:
        work = Path(directory)
        binary = work / 'osv-scanner'
        download_scanner(pin, binary)
        version = subprocess.run([str(binary), '--version'], check=True, timeout=15,
                                 capture_output=True, text=True).stdout
        require(f'osv-scanner version: {pin["version"]}' in version.splitlines(),
                'Downloaded OSV Scanner reported an unexpected version')
        print(version, end='', flush=True)
        config, report = work / 'strict-config.toml', work / 'results.json'
        config.write_text('')
        command = [str(binary), 'scan', 'source', '--config', str(config),
                   '--no-call-analysis=go', '--no-call-analysis=rust', '--no-resolve', '--all-vulns']
        for lock in LOCKS:
            command.extend(['--lockfile', f'requirements.txt:{lock}'])
        command.extend(['--format', 'json', '--all-packages', '--output-file', str(report)])
        # A failed API lookup may still produce a package list. Check the exit code first.
        subprocess.run(command, cwd=ROOT, check=True, timeout=120)
        count = validate_report(json.loads(report.read_text()))
        print(f'Google OSV: {len(LOCKS)} tool locks, {count} package entries, no reported vulnerabilities.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    update = commands.add_parser('update', help='Check stable upstream release and update the pin when needed')
    update.add_argument('--github-output', type=Path)
    commands.add_parser('scan', help='Download, verify and scan template tool locks using the current pin')
    args = parser.parse_args()
    try:
        if args.command == 'scan':
            scan()
        else:
            result = update_pin()
            if args.github_output:
                with args.github_output.open('a', encoding='utf-8') as output:
                    for key, value in result.items():
                        print(f'{key}={str(value).lower() if isinstance(value, bool) else value}', file=output)
            print(json.dumps(result))
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as error:
        print(f'OSV check failed: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
