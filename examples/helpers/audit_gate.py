#!/usr/bin/env python3
"""Fail-closed JSON vulnerability gate; copy to caller scripts/ci/audit_gate.py.
Formats: npm audit v2, pnpm classic advisories, pip-audit JSON.
Usage: audit_gate.py FORMAT REPORT [EXCEPTIONS_JSON]
Raw audit command transport/schema failures must not be discarded.
"""
import datetime as dt
import json
import os
import sys
from pathlib import Path


def findings(fmt, report):
    found = []
    if fmt == 'npm':
        if not isinstance(report, dict) or report.get('error') or not isinstance(report.get('vulnerabilities'), dict):
            raise ValueError('invalid npm audit schema or registry failure')
        records = report['vulnerabilities']
        severities = ('info','low','moderate','high','critical')
        def resolve(pkg, seen):
            if pkg in seen or pkg not in records:
                raise ValueError('cyclic or unresolved transitive advisory')
            item = records[pkg]
            if not isinstance(item, dict) or item.get('severity') not in severities or not isinstance(item.get('via'), list) or not item['via']:
                raise ValueError('invalid npm vulnerability record')
            result = []
            for via in item['via']:
                if isinstance(via, str):
                    result.extend(resolve(via, seen | {pkg}))
                elif isinstance(via, dict) and isinstance(via.get('url'), str) and via['url'].startswith('https://') and via.get('severity') in severities:
                    result.append((via['severity'], via['url'].rstrip('/').split('/')[-1]))
                else:
                    raise ValueError('invalid npm advisory')
            if item['severity'] in ('high','critical') and not any(sev in ('high','critical') for sev, _ in result):
                raise ValueError('severity inconsistent with resolved npm advisories')
            return result
        for pkg in records:
            if not isinstance(pkg, str) or not pkg:
                raise ValueError('invalid package name')
            for severity, advisory_id in resolve(pkg, set()):
                if severity in ('high','critical'):
                    found.append((pkg, advisory_id))
    elif fmt == 'pnpm':
        if not isinstance(report, dict) or report.get('error') or not isinstance(report.get('advisories'), dict):
            raise ValueError('invalid pnpm audit schema or registry failure')
        for item in report['advisories'].values():
            if not item.get('module_name') or item.get('severity') not in ('info','low','moderate','high','critical') or not item.get('url'):
                raise ValueError('invalid pnpm advisory')
            if item['severity'] in ('high', 'critical'):
                found.append((item['module_name'], item['url'].rstrip('/').split('/')[-1]))
    elif fmt == 'pip':
        if isinstance(report, dict) and report.get('error'):
            raise ValueError('pip-audit service failure')
        deps = report.get('dependencies') if isinstance(report, dict) else report
        if not isinstance(deps, list):
            raise ValueError('invalid pip-audit schema')
        for dep in deps:
            if not isinstance(dep, dict) or not dep.get('name') or 'skip_reason' in dep or not isinstance(dep.get('vulns'), list):
                raise ValueError('invalid or skipped dependency audit record')
            for vuln in dep['vulns']:
                if not vuln.get('id'):
                    raise ValueError('missing vulnerability ID')
                # pip-audit does not uniformly expose CVSS: block all returned findings.
                found.append((dep['name'], vuln['id']))
    else:
        raise ValueError('unsupported format')
    return sorted(set(found))


def gate(fmt, report, exceptions, today=None):
    today = today or dt.datetime.now(dt.timezone.utc).date()
    if not isinstance(exceptions, list):
        raise ValueError('exceptions must be a list')
    allowed = set()
    for ex in exceptions:
        if not isinstance(ex, dict) or set(ex) != {'package','id','owner','reason','tracking_url','expires'}:
            raise ValueError('unsupported exception fields; path/dev scopes require a dedicated verified policy')
        for key in ('package','id','owner','reason','tracking_url','expires'):
            if not isinstance(ex.get(key), str) or not ex[key].strip():
                raise ValueError('exception missing ' + key)
        if not ex['tracking_url'].startswith('https://') or dt.date.fromisoformat(ex['expires']) < today:
            raise ValueError('expired or unauditable exception')
        key = (ex['package'], ex['id'])
        if key in allowed:
            raise ValueError('duplicate exception')
        allowed.add(key)
    all_findings = findings(fmt, report)
    denied = [x for x in all_findings if x not in allowed]
    return {'findings': all_findings, 'excepted': [x for x in all_findings if x in allowed], 'blocking': denied}


if __name__ == '__main__':
    try:
        fmt, report_path, *optional = sys.argv[1:]
        if len(optional) > 1:
            raise ValueError('too many arguments')
        report = json.loads(Path(report_path).read_text())
        result = gate(fmt, report, json.loads(Path(optional[0]).read_text()) if optional else [])
        raw_exit = os.environ.get('AUDIT_EXIT_CODE')
        if raw_exit is not None:
            if raw_exit not in ('0', '1'):
                raise ValueError('unexpected audit process exit code')
            if fmt == 'npm':
                has_raw_findings = bool(report['vulnerabilities'])
            elif fmt == 'pnpm':
                has_raw_findings = bool(report['advisories'])
            else:
                deps = report['dependencies'] if isinstance(report, dict) else report
                has_raw_findings = any(dep['vulns'] for dep in deps)
            if raw_exit == '1' and not has_raw_findings:
                raise ValueError('audit failed without vulnerability evidence')
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(1 if result['blocking'] else 0)
    except (ValueError, KeyError, TypeError, AttributeError, OSError) as exc:
        print('Audit gate failed: ' + str(exc), file=sys.stderr)
        sys.exit(2)
