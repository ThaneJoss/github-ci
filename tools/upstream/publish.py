#!/usr/bin/env python3
"""Publish a verified OSV pin as a reviewable PR, then request its validation."""

import base64
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

from osv import validate_pin, version_tuple


PIN_PATH = 'tools/upstream/osv-scanner.json'
SETTINGS_HINT = ('Settings > Actions > General > Workflow permissions > '
                 'Allow GitHub Actions to create and approve pull requests')


class APIError(RuntimeError):
    def __init__(self, status, message):
        self.status = status
        super().__init__(f'GitHub API HTTP {status}: {message}')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, url):
        raise APIError(code, 'Refusing to redirect an authenticated GitHub API request')


class GitHub:
    def __init__(self, repository, token):
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
            raise ValueError('Invalid GITHUB_REPOSITORY')
        if not token:
            raise ValueError('GH_TOKEN is required')
        self.repository = repository
        self.token = token
        self.opener = urllib.request.build_opener(NoRedirect)

    def request(self, method, path, data=None):
        payload = None if data is None else json.dumps(data).encode('utf-8')
        request = urllib.request.Request(
            f'https://api.github.com/repos/{self.repository}/{path}', data=payload,
            method=method, headers={
                'Authorization': f'Bearer {self.token}',
                'Accept': 'application/vnd.github+json',
                'Content-Type': 'application/json',
                'X-GitHub-Api-Version': '2022-11-28',
                'User-Agent': 'github-ci-osv-updater',
            })
        try:
            with self.opener.open(request, timeout=30) as response:
                content = response.read(4 * 1024 * 1024 + 1)
                if len(content) > 4 * 1024 * 1024:
                    raise ValueError('GitHub API response exceeds size limit')
        except urllib.error.HTTPError as error:
            # Report only GitHub's public message, never request headers or token.
            try:
                message = json.loads(error.read(4096)).get('message', error.reason)
            except (ValueError, AttributeError):
                message = error.reason
            raise APIError(error.code, message) from None
        return json.loads(content) if content else None


def read_pin(api, ref):
    result = api.request('GET', f'contents/{PIN_PATH}?{urllib.parse.urlencode({"ref": ref})}')
    if result.get('encoding') != 'base64' or result.get('type') != 'file':
        raise ValueError('GitHub did not return a regular OSV pin file')
    content = base64.b64decode(''.join(result['content'].split()), validate=True)
    return validate_pin(json.loads(content))


def publish(api, candidate, default_branch, run_url):
    candidate = validate_pin(candidate)
    if not default_branch or '\n' in default_branch or '\r' in default_branch:
        raise ValueError('DEFAULT_BRANCH is required')
    main = api.request('GET', 'git/ref/heads/' + urllib.parse.quote(default_branch, safe=''))
    main_sha = main['object']['sha']
    current = read_pin(api, main_sha)
    if version_tuple(candidate['version']) < version_tuple(current['version']):
        raise ValueError('Candidate is older than the latest default-branch pin')
    if candidate['version'] == current['version']:
        if candidate != current:
            raise ValueError('Candidate changes the contents of an already pinned release')
        return {'changed': False, 'reason': 'The default branch already has this verified pin'}

    branch = 'automation/osv-scanner-v' + candidate['version']
    try:
        existing = api.request('GET', 'git/ref/heads/' + branch)
    except APIError as error:
        if error.status != 404:
            raise
        existing = None
    if existing:
        existing_sha = existing['object']['sha']
        expected_head_sha = existing_sha
        if read_pin(api, existing_sha) != candidate:
            raise ValueError('Existing update branch differs from the verified candidate; refusing to overwrite')
        comparison = api.request('GET', f'compare/{main_sha}...{existing_sha}')
        files = comparison.get('files')
        if (not isinstance(files, list) or len(files) != 1 or
                files[0].get('filename') != PIN_PATH or files[0].get('status') != 'modified'):
            raise ValueError('Existing update branch must change only the OSV pin; refusing to reuse it')
    else:
        commit = api.request('GET', 'git/commits/' + main_sha)
        tree = api.request('POST', 'git/trees', {
            'base_tree': commit['tree']['sha'],
            'tree': [{'path': PIN_PATH, 'mode': '100644', 'type': 'blob',
                      'content': json.dumps(candidate, indent=2) + '\n'}],
        })
        new_commit = api.request('POST', 'git/commits', {
            'message': f'ci: update Google OSV Scanner to v{candidate["version"]}',
            'tree': tree['sha'], 'parents': [main_sha],
        })
        expected_head_sha = new_commit['sha']
        # The ref is created only after a complete commit exists. Never force-update it.
        api.request('POST', 'git/refs', {
            'ref': 'refs/heads/' + branch, 'sha': new_commit['sha'],
        })

    query = urllib.parse.urlencode({
        'state': 'open', 'base': default_branch,
        'head': api.repository.split('/')[0] + ':' + branch,
    })
    pulls = api.request('GET', 'pulls?' + query)
    if not isinstance(pulls, list) or len(pulls) > 1:
        raise ValueError('Unexpected pull request lookup result')
    if pulls:
        pull = pulls[0]
    else:
        version = candidate['version']
        body = (
            f'Update Google OSV Scanner from v{current["version"]} to v{version}.\n\n'
            f'Official release: https://github.com/google/osv-scanner/releases/tag/v{version}\n\n'
            f'Asset: `{candidate["asset"]}`\n\nSHA256: `{candidate["sha256"]}`\n\n'
            'The updater matched the official release digest to its checksum list, verified the '
            'downloaded binary, and successfully scanned both template tool locks with this candidate. '
            'Only the pinned version file changes.\n\n'
            f'Candidate verification: {run_url}\n\n'
            'Full template validation is explicitly dispatched on this branch. Review its result '
            'before merging; this automation does not merge pull requests.'
        )
        try:
            pull = api.request('POST', 'pulls', {
                'title': f'ci: update Google OSV Scanner to v{version}',
                'head': branch, 'base': default_branch, 'body': body,
            })
        except APIError as error:
            if error.status == 403:
                raise RuntimeError(f'Cannot create the update PR. Check repository setting: {SETTINGS_HINT}. '
                                   f'GitHub response: {error}') from None
            raise
    if pull.get('head', {}).get('sha') != expected_head_sha:
        raise ValueError('Update PR head differs from the verified branch commit')
    latest_ref = api.request('GET', 'git/ref/heads/' + branch)
    if latest_ref['object']['sha'] != expected_head_sha:
        raise ValueError('Update branch moved before validation dispatch')
    api.request('POST', 'actions/workflows/validate.yml/dispatches', {'ref': branch})
    return {'changed': True, 'pull_request': pull['html_url'], 'branch': branch,
            'validation': 'dispatched'}


def main():
    try:
        repository = os.environ['GITHUB_REPOSITORY']
        run_id = os.environ['GITHUB_RUN_ID']
        if not run_id.isdigit():
            raise ValueError('Invalid GITHUB_RUN_ID')
        result = publish(
            GitHub(repository, os.environ['GH_TOKEN']),
            json.loads(os.environ['OSV_PIN_JSON']), os.environ['DEFAULT_BRANCH'],
            f'https://github.com/{repository}/actions/runs/{run_id}',
        )
        print(json.dumps(result))
        if summary := os.environ.get('GITHUB_STEP_SUMMARY'):
            with open(summary, 'a', encoding='utf-8') as output:
                if result['changed']:
                    output.write(f'OSV update PR: {result["pull_request"]}\n\nTemplate validation dispatched.\n')
                else:
                    output.write(result['reason'] + '\n')
    except (ValueError, KeyError, OSError, RuntimeError) as error:
        print(f'OSV PR publication failed: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
