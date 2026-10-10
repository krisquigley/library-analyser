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
    requests = list(requests)
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
        'server_observation': _server_observation(requests),
        'scope': 'public-synthetic-http-only',
        'browser_evidence': 'not_measured',
        'latency_budget_result': 'not_asserted',
    }


_SERVER_PHASES = frozenset((
    'request', 'validation', 'validation_schema', 'validation_rows', 'validation_graph',
    'validation_evidence', 'validation_evidence_preflight',
    'validation_evidence_fetch', 'validation_evidence_decode',
    'validation_evidence_payload', 'membership', 'selected_read',
    'selected_sql_execute', 'selected_sql_fetch', 'observer_explain', 'stage_preflight',
    'stage_decode', 'mapping', 'dto_serialization', 'utf8_encoding',
    'socket_write',
))


def _union_duration(intervals):
    """Union on one validated clock/thread, never a sum of child durations."""
    total = 0
    end = None
    for start, stop in sorted(intervals):
        total += max(0, stop - max(start, end)) if end is not None else stop - start
        end = max(end, stop) if end is not None else stop
    return total


def _server_observation(requests):
    modes = {_label(r.get('observer_mode'), ('observer_on', 'observer_off')) for r in requests}
    mode = next(iter(modes)) if len(modes) == 1 else 'unknown'
    identities = {'request': {}, 'thread': {}}
    spans, keys, raw_spans = [], [], []

    def opaque(kind, value):
        # Invalid identities do not become a shared fabricated correlation.
        if not isinstance(value, (str, int)) or isinstance(value, bool):
            return None
        labels = identities[kind]
        if value not in labels:
            labels[value] = f'{kind}-{len(labels) + 1}'
        return labels[value]

    for request in requests:
        if request.get('observer_mode') != 'observer_on':
            continue
        route = request_inventory([{
            'method': request.get('method') if isinstance(request.get('method'), str) else 'UNKNOWN',
            'url': request.get('url') if isinstance(request.get('url'), str) else '',
        }])['requests'][0]
        for raw in request.get('server_spans', ()):
            if not isinstance(raw, dict):
                continue
            start, end = raw.get('start_ms'), raw.get('end_ms')
            valid = (_finite_number(start) and _finite_number(end) and
                     end >= start and _finite_number(end - start))
            clock = _label(raw.get('clock'), ('monotonic',))
            status = _label(raw.get('status'), ('ok', 'failed', 'partial'))
            if clock != 'monotonic':
                status = 'invalid_clock'
            elif not valid and not (status in ('failed', 'partial') and end is None and _finite_number(start)):
                status = 'invalid_duration'
            duration = end - start if valid and clock == 'monotonic' else None
            request_id = opaque('request', raw.get('request_id'))
            thread_id = opaque('thread', raw.get('thread_id'))
            raw_id = raw.get('span_id')
            key = (request_id, thread_id, raw_id) if isinstance(raw_id, (str, int)) and not isinstance(raw_id, bool) else None
            keys.append(key)
            raw_spans.append(raw)
            spans.append({
                'phase': _label(raw.get('phase'), _SERVER_PHASES),
                'start_ms': start if _finite_number(start) else None,
                'end_ms': end if _finite_number(end) else None,
                'inclusive_ms': duration, 'exclusive_ms': duration,
                'status': status, 'clock': clock,
                'request_id': request_id, 'thread_id': thread_id,
                'span_id': f'span-{len(spans) + 1}', 'parent_id': None,
                'method': route['method'], 'route': route['route'],
                'bytes': raw.get('bytes') if type(raw.get('bytes')) is int and raw['bytes'] >= 0 else None,
                'scope': _label(raw.get('scope'), ('server_socket_write_not_client_receipt',)),
            })
    # Resolve only unique, same-request/thread identities before union arithmetic.
    indices = {}
    for index, key in enumerate(keys):
        if key is not None:
            indices.setdefault(key, []).append(index)
    children = {}
    parents = {}
    for index, (raw, span) in enumerate(zip(raw_spans, spans)):
        parent = raw.get('parent_id')
        if not isinstance(parent, (str, int)) or isinstance(parent, bool):
            continue
        key = (span['request_id'], span['thread_id'], parent)
        candidates = indices.get(key, [])
        if len(candidates) != 1 or None in key[:2]:
            continue
        parent_index = candidates[0]
        if spans[parent_index]['clock'] != span['clock']:
            continue
        span['parent_id'] = spans[parent_index]['span_id']
        children.setdefault(parent_index, []).append(index)
        parents[index] = parent_index
    # A cycle is not nested timing, even when equal bounds look plausible.
    finished, cyclic = set(), set()
    for index in parents:
        path, positions = [], {}
        current = index
        while current in parents and current not in finished:
            if current in positions:
                cyclic.update(path[positions[current]:])
                break
            positions[current] = len(path)
            path.append(current)
            current = parents[current]
        finished.update(path)
    for index in cyclic:
        spans[index]['status'] = 'invalid_hierarchy'
        spans[index]['exclusive_ms'] = None
        spans[index]['parent_id'] = None
    for index, child_indices in children.items():
        parent = spans[index]
        valid_children = [spans[i] for i in child_indices]
        if index in cyclic or parent['inclusive_ms'] is None or any(
                child['status'] == 'invalid_hierarchy' or
                child['inclusive_ms'] is None or child['start_ms'] < parent['start_ms'] or
                child['end_ms'] > parent['end_ms'] for child in valid_children):
            parent['exclusive_ms'] = None
        else:
            parent['exclusive_ms'] -= _union_duration([
                (child['start_ms'], child['end_ms']) for child in valid_children])
    phases = {}
    for phase in sorted(_SERVER_PHASES):
        observed = [s for s in spans if s['phase'] == phase]
        phases[phase] = {
            'status': 'measured' if observed and all(s['inclusive_ms'] is not None and s['status'] == 'ok' for s in observed) else ('partial' if observed else 'unavailable'),
            # Repeated/parallel observations have no single additive duration.
            'duration_ms': observed[0]['inclusive_ms'] if len(observed) == 1 else None,
            'samples': len(observed),
        }
    return {'observer_mode': mode, 'scope': 'server-process-monotonic',
            'spans': spans, 'phases': phases, 'sequential_total_ms': None}
