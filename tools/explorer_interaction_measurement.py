"""Public synthetic observation contracts, not an end-to-end timing harness.

Callers supply observations; no HTTP/browser/clock probes run here. Samples
and profile labels are caller-owned and are not sanitized for publication.
Filesystem/SQLite details live in the separate outward inspection adapter.
"""
from collections import Counter
from copy import deepcopy
import hashlib
import json
import math
from urllib.parse import urlsplit

from tools.explorer_fixture_inspection import fingerprint_sqlite_files, inspect_fixture
from tools.graph_read_benchmark import nearest_rank

__all__ = [
    'summarize_interactions', 'validate_phase_intervals', 'request_inventory',
    'graph_manifest', 'inspect_fixture', 'fingerprint_sqlite_files',
]


def _finite_number(value):
    # Python integers are finite without converting them to bounded floats.
    return type(value) is int or (type(value) is float and math.isfinite(value))


def summarize_interactions(attempts):
    """Retain attempts; aggregate successful finite nonnegative durations only.

    Invalid successful durations count as invalid_duration failures, without
    altering the original observation. Quantiles use observed nearest ranks;
    profiles (including process-cold/warm) are never merged or inferred.
    """
    samples = deepcopy(list(attempts))
    groups = {}
    for sample in samples:
        groups.setdefault(sample['profile'], []).append(sample)
    profiles = {}
    for profile, group in groups.items():
        durations = []
        failures = Counter()
        for sample in group:
            outcome = sample['outcome']
            elapsed = sample.get('elapsed_ms')
            if outcome == 'ok' and _finite_number(elapsed) and elapsed >= 0:
                durations.append(elapsed)
            else:
                failures['invalid_duration' if outcome == 'ok' else outcome] += 1
        profiles[profile] = {
            'attempted': len(group), 'succeeded': len(durations),
            'failures': dict(failures),
            'p50_ms': nearest_rank(durations, 50) if durations else None,
            'p95_ms': nearest_rank(durations, 95) if durations else None,
            'max_ms': max(durations) if durations else None,
        }
    return {'attempted': len(samples), 'samples': samples, 'profiles': profiles}


def validate_phase_intervals(intervals):
    """Validate supplied sequential phases separately for each clock/flow.

    Input order is observation order. Nested spans need distinct flows: this
    is not a span-tree validator, clock alignment, or proof of completeness.
    Errors identify input indexes without echoing labels or raw payloads.
    """
    errors = []
    ends = {}
    for index, interval in enumerate(intervals):
        start, end = interval.get('start_ms'), interval.get('end_ms')
        labels = [interval.get(field) for field in ('clock', 'flow', 'phase')]
        if not all(isinstance(label, str) and label for label in labels):
            reason = 'invalid_labels'
        elif not _finite_number(start) or not _finite_number(end):
            reason = 'invalid_boundary'
        elif end < start:
            reason = 'reversed_interval'
        else:
            key = (interval['clock'], interval['flow'])
            reason = 'out_of_order' if key in ends and start < ends[key] else None
            ends[key] = max(ends.get(key, end), end)
        if reason:
            errors.append({'index': index, 'reason': reason})
    return {'valid': not errors, 'errors': errors}


_KNOWN_ROUTES = frozenset((
    '/api/state', '/api/current', '/api/tracks', '/api/tracks/summary',
    '/api/track-summaries', '/api/mood-axis-graph', '/api/history',
    '/api/undo', '/api/reset',
))
_METHODS = frozenset(('GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'))


def request_inventory(requests):
    """Count every request with allowlisted method/route labels only.

    Hosts, query strings, handles and unknown paths are never echoed. The
    summary alias remains separate; no count is discarded to enforce policy.
    """
    counts = Counter()
    for request in requests:
        method = str(request['method']).upper()
        if method not in _METHODS:
            method = 'UNKNOWN'
        try:
            path = urlsplit(request['url']).path
        except ValueError:
            path = ''
        if path in _KNOWN_ROUTES:
            route = path
        elif (path.startswith('/api/tracks/') and path[len('/api/tracks/'):]
              and '/' not in path[len('/api/tracks/'):]):
            route = '/api/tracks/:handle'
        else:
            route = 'unknown'
        counts[method, route] += 1
    return {'requests': [
        {'method': method, 'route': route, 'count': count}
        for (method, route), count in sorted(counts.items())
    ]}


def graph_manifest(body, *, source):
    """Hash entity bytes and count arrays, without asserting graph integrity.

    Only browser-only provenance is supported here: neither a schema nor DB
    timing can be inferred from a JSON body. Use the existing independent
    indexed-v3 integrity API when structural validation is required.
    """
    if source != 'browser-only':
        raise ValueError('Require browser-only provenance')
    try:
        payload = json.loads(body.decode('utf-8'))
        counts = {}
        for key in ('nodes', 'links', 'unpositioned'):
            rows = payload[key]
            if not isinstance(rows, list):
                raise ValueError('Require graph arrays')
            counts[key] = len(rows)
    except (UnicodeError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise ValueError('Require UTF-8 graph JSON with arrays') from error
    return {
        'sha256': hashlib.sha256(body).hexdigest(), 'body_bytes': len(body),
        'counts': counts, 'source': source, 'db_schema_version': None,
    }
