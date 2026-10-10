"""Loss-aware public encoding for caller-owned HTTP diagnostic observations.

The raw PR4a helpers remain unchanged: validate original interval identities
before replacing labels, then summarize sanitized copies for strict JSON.
No payload, exception text, hostname, filesystem path or track handle is
accepted into this publication boundary.
"""
import math

from tools.explorer_interaction_measurement import (
    request_inventory, summarize_interactions, validate_phase_intervals,
)


_PROFILES = frozenset(('process-cold', 'warm'))
_OUTCOMES = frozenset((
    'ok', 'timeout', 'http_error', 'connection_error', 'invalid_response',
    'invalid_duration', 'unknown',
))
_INTERVAL_LABELS = {
    'clock': frozenset(('monotonic',)),
    'flow': frozenset(('selection', 'search', 'startup')),
    'phase': frozenset(('get_state', 'get_summary', 'post_current', 'get_detail')),
}


def _label(value, allowed):
    return value if isinstance(value, str) and value in allowed else 'unknown'


def _finite_number(value):
    return type(value) is int or (type(value) is float and math.isfinite(value))


def publish_http_report(*, attempts, intervals=(), requests=()):
    """Publish all observations using fixed labels and finite numeric fields.

    Failed attempts retain finite elapsed time when supplied, but never enter
    successful-duration aggregates. Invalid successful durations become explicit
    failures instead of disappearing or producing nonstandard JSON numbers.
    """
    samples = []
    for attempt in attempts:
        elapsed = attempt.get('elapsed_ms')
        valid_duration = _finite_number(elapsed) and elapsed >= 0
        outcome = _label(attempt.get('outcome'), _OUTCOMES)
        if outcome == 'ok' and not valid_duration:
            outcome = 'invalid_duration'
        samples.append({
            'profile': _label(attempt.get('profile'), _PROFILES),
            'outcome': outcome,
            'elapsed_ms': elapsed if valid_duration else None,
        })

    original_intervals = list(intervals)
    validation = validate_phase_intervals(original_intervals)
    published_intervals = []
    for interval in original_intervals:
        published = {
            field: _label(interval.get(field), allowed)
            for field, allowed in _INTERVAL_LABELS.items()
        }
        for field in ('start_ms', 'end_ms'):
            value = interval.get(field)
            published[field] = value if _finite_number(value) else None
        published_intervals.append(published)

    # Inventory is an outward sanitizer: give it only string-valued inputs,
    # leaving route-template normalization and stable ordering to PR4a.
    inventory_inputs = []
    published_requests = []
    for request in requests:
        method, url = request.get('method'), request.get('url')
        inventory_input = {
            'method': method if isinstance(method, str) else 'UNKNOWN',
            'url': url if isinstance(url, str) else '',
        }
        inventory_inputs.append(inventory_input)
        labels = request_inventory([inventory_input])['requests'][0]
        status = request.get('status')
        elapsed = request.get('elapsed_ms')
        response_bytes = request.get('response_bytes')
        published_requests.append({
            'method': labels['method'], 'route': labels['route'],
            'status': status if type(status) is int and 100 <= status <= 599 else None,
            'outcome': _label(request.get('outcome'), _OUTCOMES),
            'elapsed_ms': elapsed if _finite_number(elapsed) and elapsed >= 0 else None,
            'response_bytes': response_bytes if type(response_bytes) is int and response_bytes >= 0 else None,
        })
    return {
        **summarize_interactions(samples),
        'intervals': published_intervals,
        'interval_validation': validation,
        'request_inventory': request_inventory(inventory_inputs),
        'requests': published_requests,
        'scope': 'public-synthetic-http-only',
        'browser_evidence': 'not_measured',
        'latency_budget_result': 'not_asserted',
    }
