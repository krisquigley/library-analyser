import json
from music_analyzer.interface_adapters.mappers.review import review_to_mapping


def present_review(report, as_json=False):
    if as_json:
        return json.dumps(review_to_mapping(report), ensure_ascii=False, allow_nan=False)
    lines = [f'TRACK_ID: {report.track.track_id}', f'SHA256: {report.track.sha256}',
             f'Run: {report.track.run.run_id if report.track.run else "missing"}',
             f'Needs review: {report.needs_review}']
    for field, value in report.effective:
        source = 'manual' if field in dict(report.track.overrides) else 'automatic/provisional'
        lines.append(f'{field} ({source}): {value if value is not None else "missing / no selection"}')
    lines.extend('Review: ' + reason for reason in report.reasons)
    return '\n'.join(lines)
