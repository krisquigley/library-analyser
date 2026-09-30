import json
from dataclasses import asdict

from music_analyzer.domain.library_duration_policy import DurationVerification, active_library_duration_policy


def _duration_reason_and_unknown(metadata):
    source = getattr(metadata, 'duration_source', '')
    seconds = getattr(metadata, 'duration_seconds', None)
    decision = active_library_duration_policy(DurationVerification(seconds, source) if source else None)
    if decision.active:
        return '', False
    unknown = source not in {'mutagen', 'ffprobe'} or seconds is None
    return decision.warning or '', unknown


def present_scan(report, as_json=False):
    payload = asdict(report)
    excluded = []
    unknown = []
    for file, original in zip(payload['files'], report.files):
        file['track_id'] = original.identity.track_id
        reason, is_unknown = _duration_reason_and_unknown(original.metadata)
        if reason:
            file['active_exclusion_reason'] = reason
            (unknown if is_unknown else excluded).append((original, reason))
    payload['active_exclusion_count'] = len(excluded)
    payload['duration_unknown_count'] = len(unknown)
    if as_json:
        return json.dumps(payload, ensure_ascii=False)
    lines = [f"Scan {'complete' if report.complete else 'partial'}: {len(report.files)} files, {len(report.missing)} missing locations, {len(excluded)} duration exclusions, {len(unknown)} unknown durations"]
    lines.extend(f'{f.identity.track_id}  {f.location}' for f in report.files)
    lines.extend(f'WARNING {f.location}: {reason}' for f, reason in (*excluded, *unknown))
    lines.extend(f'ERROR {issue.location}: {issue.detail}' for issue in report.issues)
    return '\n'.join(lines)
