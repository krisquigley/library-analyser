import json
from dataclasses import asdict

from music_analyzer.application.dto.doctor import DoctorReport


def present_doctor(report: DoctorReport, *, as_json: bool) -> str:
    if as_json:
        return json.dumps(asdict(report), ensure_ascii=False, indent=2)
    lines = ['Foundation ready: ' + ('yes' if report.foundation_ready else 'no'),
             'Analysis ready: no (partial Phase 1; availability checks only)']
    for check in report.checks:
        lines.append(f'{"OK" if check.available else "FAIL"} {check.name}: {check.detail}')
        if not check.available:
            lines.append(f'  Next: {check.remediation}')
    lines.append('Remaining validation:')
    lines.extend(f'  - {item}' for item in report.remaining_validation)
    return '\n'.join(lines)
