import json
from dataclasses import asdict


def present_scan(report, as_json=False):
    payload = asdict(report)
    for file, original in zip(payload['files'], report.files):
        file['track_id'] = original.identity.track_id
    if as_json:
        return json.dumps(payload, ensure_ascii=False)
    lines = [f"Scan {'complete' if report.complete else 'partial'}: {len(report.files)} files, {len(report.missing)} missing locations"]
    lines.extend(f'{f.identity.track_id}  {f.location}' for f in report.files)
    lines.extend(f'ERROR {issue.location}: {issue.detail}' for issue in report.issues)
    return '\n'.join(lines)
