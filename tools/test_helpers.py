#!/usr/bin/env python3
"""Offline, synthetic tests for the optional vulnerability gate example.

Run from any directory:
  python3 tools/test_helpers.py

Only imports the example helper and launches that same local stdlib-only helper
against temporary synthetic JSON. No repository application code or network.
"""
import datetime as dt
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "examples/helpers/audit_gate.py"
spec = importlib.util.spec_from_file_location("ci_example_audit_gate", HELPER)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
TODAY = dt.date(2026, 10, 13)
INVALID = (ValueError, KeyError, TypeError, AttributeError)


def npm_record(severity="high", advisory="GHSA-aaaa-bbbb-cccc"):
    return {"severity": severity, "via": [{
        "url": "https://github.com/advisories/" + advisory,
        "severity": severity,
    }]}


def npm_report(severity="high"):
    return {"vulnerabilities": {"demo": npm_record(severity)}}


def exception(**overrides):
    value = {"package": "demo", "id": "GHSA-aaaa-bbbb-cccc",
             "owner": "maintainer", "reason": "Synthetic test only",
             "tracking_url": "https://example.com/issues/1",
             "expires": "2026-10-14"}
    value.update(overrides)
    return value


class AuditFindingsTests(unittest.TestCase):
    def test_npm_clean(self):
        self.assertEqual(module.findings("npm", {"vulnerabilities": {}}), [])

    def test_npm_high_and_critical_block(self):
        for severity in ("high", "critical"):
            with self.subTest(severity=severity):
                result = module.gate("npm", npm_report(severity), [], TODAY)
                self.assertEqual(result["blocking"], [("demo", "GHSA-aaaa-bbbb-cccc")])

    def test_npm_below_threshold_retained_without_block(self):
        for severity in ("info", "low", "moderate"):
            with self.subTest(severity=severity):
                self.assertEqual(module.gate("npm", npm_report(severity), [], TODAY)["blocking"], [])

    def test_npm_transitive_reference_resolves(self):
        report = npm_report()
        report["vulnerabilities"]["parent"] = {"severity": "high", "via": ["demo"]}
        self.assertEqual(module.findings("npm", report),
                         [("demo", "GHSA-aaaa-bbbb-cccc"), ("parent", "GHSA-aaaa-bbbb-cccc")])

    def test_npm_duplicate_advisories_are_deduplicated(self):
        report = npm_report()
        report["vulnerabilities"]["demo"]["via"] *= 2
        self.assertEqual(len(module.findings("npm", report)), 1)

    def test_npm_network_error_fails_closed(self):
        report = {"error": {"code": "ENETUNREACH", "summary": "Synthetic network error"},
                  "vulnerabilities": {}}
        with self.assertRaises(INVALID):
            module.findings("npm", report)

    def test_npm_schema_errors_fail_closed(self):
        cases = [None, [], {}, {"vulnerabilities": []},
                 {"vulnerabilities": {"demo": {"severity": "high"}}},
                 {"vulnerabilities": {"demo": {"severity": "unknown", "via": []}}},
                 {"vulnerabilities": {"demo": {"severity": "high", "via": ["missing"]}}},
                 {"vulnerabilities": {"demo": {"severity": "high", "via": [{}]}}}]
        for report in cases:
            with self.subTest(report=report), self.assertRaises(INVALID):
                module.findings("npm", report)

    def test_npm_via_must_be_nonempty_list(self):
        for via in ([], "", {}, None):
            with self.subTest(via=via), self.assertRaises(INVALID):
                module.findings("npm", {"vulnerabilities": {"demo": {"severity": "high", "via": via}}})

    def test_npm_circular_transitive_only_records_fail_closed(self):
        report = {"vulnerabilities": {
            "first": {"severity": "critical", "via": ["second"]},
            "second": {"severity": "critical", "via": ["first"]},
        }}
        with self.assertRaises(INVALID):
            module.findings("npm", report)

    def test_pnpm_clean(self):
        self.assertEqual(module.findings("pnpm", {"advisories": {}}), [])

    def test_pnpm_high_critical_and_threshold(self):
        report = {"advisories": {
            "1": {"module_name": "high-package", "severity": "high", "url": "https://example.com/GHSA-high"},
            "2": {"module_name": "critical-package", "severity": "critical", "url": "https://example.com/GHSA-critical/"},
            "3": {"module_name": "low-package", "severity": "low", "url": "https://example.com/GHSA-low"},
        }}
        self.assertEqual(module.findings("pnpm", report),
                         [("critical-package", "GHSA-critical"), ("high-package", "GHSA-high")])

    def test_pnpm_network_and_schema_errors_fail_closed(self):
        cases = [{"error": {"code": "ECONNRESET"}, "advisories": {}},
                 {"advisories": []}, {"advisories": {"1": None}},
                 {"advisories": {"1": {"module_name": "demo", "severity": "high"}}}]
        for report in cases:
            with self.subTest(report=report), self.assertRaises(INVALID):
                module.findings("pnpm", report)

    def test_pip_list_and_object_clean_schema(self):
        for report in ([], {"dependencies": []}, [{"name": "demo", "vulns": []}]):
            with self.subTest(report=report):
                self.assertEqual(module.findings("pip", report), [])

    def test_pip_blocks_all_vulnerabilities_without_cvss_claim(self):
        report = {"dependencies": [{"name": "demo", "vulns": [
            {"id": "PYSEC-2026-1", "fix_versions": []},
            {"id": "GHSA-aaaa-bbbb-cccc", "aliases": ["CVE-2026-0001"]},
        ]}]}
        self.assertEqual(module.findings("pip", report),
                         [("demo", "GHSA-aaaa-bbbb-cccc"), ("demo", "PYSEC-2026-1")])

    def test_pip_skipped_dependency_fails_closed(self):
        for reason in ("not found on index", "", None):
            with self.subTest(reason=reason), self.assertRaises(INVALID):
                module.findings("pip", {"dependencies": [{"name": "demo", "vulns": [], "skip_reason": reason}]})

    def test_pip_schema_errors_fail_closed(self):
        for report in ({}, {"dependencies": {}}, [None], [{"name": "demo"}],
                       [{"name": "demo", "vulns": [{}]}]):
            with self.subTest(report=report), self.assertRaises(INVALID):
                module.findings("pip", report)

    def test_pip_explicit_error_fails_closed(self):
        with self.assertRaises(INVALID):
            module.findings("pip", {"dependencies": [], "error": "Synthetic service unavailable"})

    def test_unknown_format_fails_closed(self):
        with self.assertRaises(INVALID):
            module.findings("future-format", {})


class ExceptionTests(unittest.TestCase):
    def test_exception_for_advisory_source_does_not_exempt_affected_parent(self):
        report = npm_report()
        report["vulnerabilities"]["parent"] = {"severity": "high", "via": ["demo"]}
        result = module.gate("npm", report, [exception()], TODAY)
        self.assertEqual(result["blocking"], [("parent", "GHSA-aaaa-bbbb-cccc")])

    def test_valid_exception_is_auditable_and_scoped(self):
        result = module.gate("npm", npm_report(), [exception()], TODAY)
        self.assertEqual(result["blocking"], [])
        self.assertEqual(result["excepted"], [("demo", "GHSA-aaaa-bbbb-cccc")])

    def test_exception_does_not_allow_other_package_or_id(self):
        for ex in (exception(package="other"), exception(id="GHSA-other")):
            with self.subTest(ex=ex):
                self.assertTrue(module.gate("npm", npm_report(), [ex], TODAY)["blocking"])

    def test_expiry_date_is_inclusive(self):
        self.assertEqual(module.gate("npm", npm_report(), [exception(expires=TODAY.isoformat())], TODAY)["blocking"], [])

    def test_expired_exception_fails_even_without_findings(self):
        with self.assertRaises(INVALID):
            module.gate("npm", {"vulnerabilities": {}}, [exception(expires="2026-10-12")], TODAY)

    def test_missing_empty_or_wrong_type_exception_fields_fail(self):
        for field in ("package", "id", "owner", "reason", "tracking_url", "expires"):
            for value in (None, "", " ", 1):
                with self.subTest(field=field, value=value), self.assertRaises(INVALID):
                    module.gate("npm", npm_report(), [exception(**{field: value})], TODAY)

    def test_duplicate_exception_fails(self):
        with self.assertRaises(INVALID):
            module.gate("npm", npm_report(), [exception(), exception()], TODAY)

    def test_bad_exception_date_or_non_https_url_fails(self):
        for ex in (exception(expires="tomorrow"), exception(tracking_url="http://example.com/1")):
            with self.subTest(ex=ex), self.assertRaises(INVALID):
                module.gate("npm", npm_report(), [ex], TODAY)

    def test_invalid_exception_container_fails(self):
        for exceptions in ({}, None, [None], ["demo"]):
            with self.subTest(exceptions=exceptions), self.assertRaises(INVALID):
                module.gate("npm", npm_report(), exceptions, TODAY)

    def test_unknown_exception_scope_fields_are_rejected(self):
        for field, value in (("paths", ["dev/only"]), ("dev_scope", True), ("scope", "development")):
            with self.subTest(field=field), self.assertRaises(INVALID):
                module.gate("npm", npm_report(), [exception(**{field: value})], TODAY)


class CLITests(unittest.TestCase):
    def call_cli(self, report, fmt="npm", raw=False, raw_exit=None):
        with tempfile.TemporaryDirectory(prefix="ci-audit-test-") as directory:
            path = Path(directory) / "report.json"
            path.write_text(report if raw else json.dumps(report), encoding="utf-8")
            environment = {key: value for key, value in os.environ.items() if key != "AUDIT_EXIT_CODE"}
            if raw_exit is not None:
                environment["AUDIT_EXIT_CODE"] = str(raw_exit)
            return subprocess.run([sys.executable, str(HELPER), fmt, str(path)], env=environment,
                                  capture_output=True, text=True, timeout=5, check=False)

    def test_raw_exit_one_without_findings_fails_closed(self):
        for fmt, report in (("npm", {"vulnerabilities": {}}),
                            ("pnpm", {"advisories": {}}),
                            ("pip", {"dependencies": []})):
            with self.subTest(fmt=fmt):
                result = self.call_cli(report, fmt=fmt, raw_exit=1)
                self.assertEqual(result.returncode, 2)
                self.assertIn("failed without vulnerability evidence", result.stderr)

    def test_raw_transport_or_invalid_exit_fails_closed(self):
        for code in (2, 23, 127, -1, "invalid"):
            with self.subTest(code=code):
                result = self.call_cli({"vulnerabilities": {}}, raw_exit=code)
                self.assertEqual(result.returncode, 2)

    def test_raw_exit_one_with_below_threshold_findings_is_allowed(self):
        result = self.call_cli(npm_report("moderate"), raw_exit=1)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["blocking"], [])

    def test_raw_exit_one_with_high_findings_blocks(self):
        result = self.call_cli(npm_report(), raw_exit=1)
        self.assertEqual(result.returncode, 1, result.stderr)

    def test_raw_exit_zero_does_not_override_high_findings(self):
        result = self.call_cli(npm_report(), raw_exit=0)
        self.assertEqual(result.returncode, 1, result.stderr)

    def test_clean_exit_zero_and_json(self):
        result = self.call_cli({"vulnerabilities": {}})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["blocking"], [])

    def test_vulnerability_exit_one(self):
        result = self.call_cli(npm_report())
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertTrue(json.loads(result.stdout)["blocking"])

    def test_network_error_exit_two(self):
        result = self.call_cli({"error": {"code": "ENETUNREACH"}})
        self.assertEqual(result.returncode, 2)
        self.assertIn("Audit gate failed", result.stderr)

    def test_pip_skipped_exit_two(self):
        result = self.call_cli([{"name": "demo", "skip_reason": "index unavailable"}], fmt="pip")
        self.assertEqual(result.returncode, 2)

    def test_malformed_json_exit_two(self):
        result = self.call_cli("{broken", raw=True)
        self.assertEqual(result.returncode, 2)

    def test_missing_args_and_file_exit_two(self):
        for arguments in ([], ["npm", "/path-that-does-not-exist/ci-audit-test.json"]):
            with self.subTest(arguments=arguments):
                result = subprocess.run([sys.executable, str(HELPER), *arguments],
                                        capture_output=True, text=True, timeout=5, check=False)
                self.assertEqual(result.returncode, 2)


class DocsHelperTests(unittest.TestCase):
    """Small synthetic checks for the stdlib-only content example; no URLs fetched."""

    def call_docs(self, contents, selected=("README.md",)):
        helper = ROOT / "examples/helpers/check_docs.py"
        with tempfile.TemporaryDirectory(prefix="ci-docs-test-") as directory:
            root = Path(directory)
            for filename, data in contents.items():
                path = root / filename
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
            return subprocess.run([sys.executable, str(helper), *selected], cwd=root,
                                  capture_output=True, text=True, timeout=5, check=False)

    def test_existing_local_links_and_remote_links(self):
        result = self.call_docs({"README.md": "[local](docs/page.md#ignored) [remote](https://example.com/no-fetch)\n",
                                 "docs/page.md": "# Fixture\n"})
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_missing_local_link(self):
        result = self.call_docs({"README.md": "[missing](missing.md)\n"})
        self.assertNotEqual(result.returncode, 0)

    def test_link_escaping_repository(self):
        result = self.call_docs({"README.md": "[escape](../outside.md)\n"})
        self.assertNotEqual(result.returncode, 0)

    def test_code_fence_and_inline_code_are_not_link_checks(self):
        text = "```md\n[missing](missing.md)\n```\n`[missing](missing.md)`\n"
        result = self.call_docs({"README.md": text})
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_duplicate_json_key_rejected(self):
        result = self.call_docs({"manifest.json": '{"name":"first","name":"second"}'}, ("manifest.json",))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("duplicate JSON key", result.stdout)

    def test_nonstandard_json_constants_rejected(self):
        for constant in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(constant=constant):
                result = self.call_docs({"manifest.json": '{"value":' + constant + '}'}, ("manifest.json",))
                self.assertNotEqual(result.returncode, 0)

    def test_invalid_utf8_rejected(self):
        result = self.call_docs({"README.md": b"invalid \xff\xfe"})
        self.assertNotEqual(result.returncode, 0)

    def test_empty_content_selection_rejected(self):
        result = self.call_docs({"fixture.txt": "not selected content"}, ("fixture.txt",))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("No Markdown/JSON content selected", result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
