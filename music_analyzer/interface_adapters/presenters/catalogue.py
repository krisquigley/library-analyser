import json
from dataclasses import asdict
from music_analyzer.domain.catalogue import duration_exclusion_reason


def present_scan(report, as_json=False):
    payload = asdict(report)
    excluded = []
    unknown = []
    for file, original in zip(payload['files'], report.files):
        file['track_id'] = original.identity.track_id
        reason = duration_exclusion_reason(original.metadata.duration_seconds)
        if reason:
            file['active_exclusion_reason'] = reason
            (unknown if original.metadata.duration_seconds is None else excluded).append((original, reason))
    payload['active_exclusion_count'] = len(excluded)
    payload['duration_unknown_count'] = len(unknown)
    if as_json:
        return json.dumps(payload, ensure_ascii=False)
    lines = [f"Scan {'complete' if report.complete else 'partial'}: {len(report.files)} files, {len(report.missing)} missing locations, {len(excluded)} duration exclusions, {len(unknown)} unknown durations"]
    lines.extend(f'{f.identity.track_id}  {f.location}' for f in report.files)
    lines.extend(f'WARNING {f.location}: {reason}' for f, reason in (*excluded, *unknown))
    lines.extend(f'ERROR {issue.location}: {issue.detail}' for issue in report.issues)
    return '\n'.join(lines)
