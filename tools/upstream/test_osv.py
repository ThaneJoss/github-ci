import copy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import osv


DIGEST = 'a' * 64


def release(version='2.8.0', digest=DIGEST):
    return {
        'tag_name': f'v{version}', 'draft': False, 'prerelease': False,
        'assets': [
            {'name': name, 'browser_download_url': osv.asset_url(version, name),
             'digest': f'sha256:{digest}'}
            for name in (osv.ASSET, osv.CHECKSUM_ASSET)
        ],
    }


def fake_fetch(metadata, checksum=DIGEST):
    def fetch(url, limit=None):
        if url == osv.RELEASE_API:
            return json.dumps(metadata).encode()
        if url == osv.asset_url(metadata['tag_name'][1:], osv.CHECKSUM_ASSET):
            return f'{checksum}  {osv.ASSET}\n'.encode()
        raise AssertionError(f'Unexpected network request: {url}')
    return fetch


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.pin = Path(self.temp.name) / 'pin.json'
        self.original = {'version': '2.7.0', 'asset': osv.ASSET, 'sha256': DIGEST}
        self.pin.write_text(json.dumps(self.original) + '\n')

    def test_new_stable_release_updates_only_verified_pin(self):
        result = osv.update_pin(self.pin, fake_fetch(release()))
        self.assertEqual(result, {'changed': True, 'version': '2.8.0', 'previous_version': '2.7.0'})
        self.assertEqual(json.loads(self.pin.read_text()), {**self.original, 'version': '2.8.0'})
        self.assertEqual(list(self.pin.parent.iterdir()), [self.pin])

    def test_no_update_preserves_exact_file_and_mtime(self):
        before, modified = self.pin.read_bytes(), self.pin.stat().st_mtime_ns
        result = osv.update_pin(self.pin, fake_fetch(release('2.7.0')))
        self.assertFalse(result['changed'])
        self.assertEqual(self.pin.read_bytes(), before)
        self.assertEqual(self.pin.stat().st_mtime_ns, modified)

    def test_downgrade_and_replaced_existing_release_are_rejected(self):
        cases = [(release('2.6.0'), DIGEST), (release('2.7.0', 'b' * 64), 'b' * 64)]
        for metadata, checksum in cases:
            with self.subTest(metadata=metadata), self.assertRaises(ValueError):
                osv.update_pin(self.pin, fake_fetch(metadata, checksum))
        self.assertEqual(json.loads(self.pin.read_text()), self.original)

    def test_checksum_conflict_does_not_mutate_pin(self):
        with self.assertRaisesRegex(ValueError, 'disagrees'):
            osv.update_pin(self.pin, fake_fetch(release(), 'b' * 64))
        self.assertEqual(json.loads(self.pin.read_text()), self.original)

    def test_network_failure_does_not_mutate_pin(self):
        with self.assertRaises(OSError):
            osv.update_pin(self.pin, mock.Mock(side_effect=OSError('network unavailable')))
        self.assertEqual(json.loads(self.pin.read_text()), self.original)

    def test_unstable_malformed_or_untrusted_release_is_rejected(self):
        cases = []
        for key, value in [('draft', True), ('prerelease', True), ('tag_name', 'v2.8.0-rc1'),
                           ('tag_name', 'v02.8.0'), ('assets', [])]:
            candidate = release()
            candidate[key] = value
            cases.append(candidate)
        candidate = release()
        candidate['assets'].append(copy.deepcopy(candidate['assets'][0]))
        cases.append(candidate)
        for key, value in [('browser_download_url', 'https://example.test/scanner'),
                           ('digest', None), ('digest', 'sha256:invalid')]:
            candidate = release()
            candidate['assets'][0][key] = value
            cases.append(candidate)
        for metadata in cases:
            with self.subTest(metadata=metadata), self.assertRaises(ValueError):
                osv.update_pin(self.pin, fake_fetch(metadata))
        self.assertEqual(json.loads(self.pin.read_text()), self.original)

    def test_invalid_pin_never_requests_upstream(self):
        for change in [{'version': '../2.7.0'}, {'asset': 'other'}, {'sha256': 'bad'}, {'extra': 1}]:
            self.pin.write_text(json.dumps({**self.original, **change}))
            network = mock.Mock()
            with self.subTest(change=change), self.assertRaises(ValueError):
                osv.update_pin(self.pin, network)
            network.assert_not_called()


class ScanTests(unittest.TestCase):
    def report(self):
        return {'results': [
            {'source': {'type': 'lockfile', 'path': str((osv.ROOT / lock).resolve())},
             'packages': [{'package': {'name': 'example', 'version': '1.0'}}]}
            for lock in osv.LOCKS
        ]}

    def test_complete_nonempty_report_passes(self):
        self.assertEqual(osv.validate_report(self.report()), 2)

    def test_missing_empty_duplicate_extra_and_vulnerable_reports_fail(self):
        cases = [{'results': []}]
        candidate = self.report()
        candidate['results'].pop()
        cases.append(candidate)
        candidate = self.report()
        candidate['results'][0]['packages'] = []
        cases.append(candidate)
        candidate = self.report()
        candidate['results'].append(copy.deepcopy(candidate['results'][0]))
        cases.append(candidate)
        candidate = self.report()
        candidate['results'][0]['source']['path'] = '/not-a-required-lock'
        cases.append(candidate)
        candidate = self.report()
        candidate['results'][0]['packages'][0]['vulnerabilities'] = [{'id': 'EXAMPLE-1'}]
        cases.append(candidate)
        for report in cases:
            with self.subTest(report=report), self.assertRaises(ValueError):
                osv.validate_report(report)

    def test_binary_checksum_is_checked_before_writing_executable(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'scanner'
            pin = {'version': '2.7.0', 'asset': osv.ASSET, 'sha256': DIGEST}
            with self.assertRaisesRegex(ValueError, 'SHA256 mismatch'):
                osv.download_scanner(pin, target, lambda *args, **kwargs: b'unverified')
            self.assertFalse(target.exists())
            pin['sha256'] = hashlib.sha256(b'verified').hexdigest()
            osv.download_scanner(pin, target, lambda *args, **kwargs: b'verified')
            self.assertEqual(target.read_bytes(), b'verified')
            self.assertEqual(target.stat().st_mode & 0o777, 0o700)

    def test_scan_api_failure_cannot_pass_using_a_package_only_report(self):
        version = subprocess.CompletedProcess([], 0, stdout='osv-scanner version: 2.7.0\n')
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(osv, 'download_scanner'), \
                mock.patch.object(osv.subprocess, 'run', side_effect=[version, subprocess.CalledProcessError(127, 'scan')]), \
                mock.patch.object(osv, 'validate_report') as validate:
            pin = Path(directory) / 'pin.json'
            pin.write_text(json.dumps({'version': '2.7.0', 'asset': osv.ASSET, 'sha256': DIGEST}))
            with self.assertRaises(subprocess.CalledProcessError):
                osv.scan(pin)
            validate.assert_not_called()


if __name__ == '__main__':
    unittest.main()
