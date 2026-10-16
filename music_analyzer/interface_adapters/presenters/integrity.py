"""Deterministic presentation of sanitized application diagnostic reports."""
from dataclasses import asdict
import json

from music_analyzer.application.dto.integrity import IntegrityReport


def present_integrity(report: IntegrityReport, as_json=False):
    if as_json:
        payload = {
            'report_version': report.report_version,
            'coverage_revision': report.coverage_revision,
            'required_scope_revision': report.required_scope_revision,
            'supported_schema_versions': list(report.supported_schema_versions),
            'schema_version': report.schema_version,
            'status': report.status,
            'complete': report.complete,
            'implemented_scope_complete': report.implemented_scope_complete,
            'stop_reason': report.stop_reason,
            'exit_code': report.exit_code,
            'checks': [asdict(item) for item in report.checks],
            'findings': [asdict(item) for item in report.findings],
            'findings_truncated': report.findings_truncated,
        }
        return json.dumps(payload, ensure_ascii=True, separators=(',', ':'))
    lines = [
        'D3 offline integrity diagnostic — snapshot checks, not writer parity or a trust token.',
        f'report_version={report.report_version} coverage_revision={report.coverage_revision} required_scope_revision={report.required_scope_revision}',
        'supported_schema_versions=6,7,8,9,10',
        f'schema_version={report.schema_version} status={report.status} complete={str(report.complete).lower()} implemented_scope_complete={str(report.implemented_scope_complete).lower()}',
        f'stop_reason={report.stop_reason} exit={report.exit_code}',
    ]
    for item in report.checks:
        count = 'unavailable' if item.count is None else str(item.count)
        lines.append(f'check {item.check_id}: {item.state} count={count} unit={item.count_unit} precision={item.count_precision}')
    for item in report.findings:
        lines.append(f'finding {item.check_id}/{item.code}: severity={item.severity} count={item.count} unit={item.count_unit} precision={item.count_precision}')
    lines.append(f'findings_truncated={str(report.findings_truncated).lower()}')
    return '\n'.join(lines)
