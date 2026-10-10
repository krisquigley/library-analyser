"""Allowlisted publication of supplied observations, never browser evidence."""
from tools.explorer_http_report import publish_http_report, _finite_number, _label
from tools.explorer_interaction_measurement import validate_phase_intervals

_MILESTONES = ('navigation', 'graph_request', 'graph_headers', 'graph_body',
               'graph_json', 'graph_model', 'graph_usable_render', 'search_usable',
               'search_input', 'search_rows', 'selection_intent', 'selection_feedback',
               'detail_painted', 'focus_start', 'focus_end')
_INTERVAL_LABELS = {
    'clock': frozenset(('browser-performance', 'monotonic')),
    'flow': frozenset(('graph', 'selection', 'search', 'startup')),
    'phase': frozenset(('request', 'headers', 'body', 'json', 'model', 'render',
                        'input', 'rows', 'detail', 'focus')),
}


def publish_browser_report(*, attempts, intervals=(), requests=(), environment=None):
    """Retain failures and null missing observations without publishing raw inputs.

    Environment is deliberately not accepted from untrusted supplied observations.
    Real driver environment reporting is a separate, owned collection boundary.
    """
    attempts = list(attempts)
    intervals = list(intervals)
    report = publish_http_report(attempts=attempts, requests=requests)
    for sample, original in zip(report['samples'], attempts):
        if 'milestones_ms' in original:
            source = original['milestones_ms']
            source = source if isinstance(source, dict) else {}
            sample['milestones_ms'] = {
                key: value if _finite_number(value) and value >= 0 else None
                for key in _MILESTONES for value in (source.get(key),)
            }
    report['interval_validation'] = validate_phase_intervals(intervals)
    report['intervals'] = []
    for interval in intervals:
        published = {key: _label(interval.get(key), allowed)
                     for key, allowed in _INTERVAL_LABELS.items()}
        for key in ('start_ms', 'end_ms'):
            value = interval.get(key)
            published[key] = value if _finite_number(value) else None
        report['intervals'].append(published)
    for request in report['requests']:
        if request['route'] == '/api/tracks/:handle':
            request['route'] = '/api/tracks/<id>'
    for request in report['request_inventory']['requests']:
        if request['route'] == '/api/tracks/:handle':
            request['route'] = '/api/tracks/<id>'
    report.update(scope='public-synthetic-browser-only',
                  browser_evidence='supplied-observations-not-browser-acceptance',
                  environment={})
    return report
