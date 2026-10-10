"""Allowlisted publication of supplied observations, never browser evidence."""
import math
import re

from tools.explorer_http_report import publish_http_report, _finite_number, _label
from tools.explorer_interaction_measurement import validate_phase_intervals

_MILESTONES = ('navigation', 'graph_request', 'graph_headers', 'graph_body',
               'graph_json', 'graph_model', 'graph_usable_render', 'search_usable',
               'search_input', 'search_rows', 'selection_intent', 'selection_feedback',
               'detail_painted', 'focus_start', 'focus_end',
               'graph_body_start', 'graph_body_end',
               'graph_native_json_start', 'graph_native_json_end',
               'graph_json_start', 'graph_json_end',
               'graph_verification_start', 'graph_verification_end',
               'graph_model_start', 'graph_model_end',
               'graph_scene_start', 'graph_scene_end',
               'graph_first_presentation', 'graph_post_focus_readback')
_INTERVAL_LABELS = {
    'clock': frozenset(('browser-performance', 'monotonic')),
    'flow': frozenset(('graph', 'selection', 'search', 'startup')),
    'phase': frozenset(('request', 'headers', 'body', 'json', 'model', 'render',
                        'input', 'rows', 'detail', 'focus')),
}


def _nonnegative(value):
    return value if _finite_number(value) and value >= 0 else None


_INPUT_LABELS = {
    'action': frozenset(('input', 'selection')),
    'attempt_clock': frozenset(('host-monotonic',)),
    'receipt_clock': frozenset(('browser-performance',)),
    'phase_at_attempt': frozenset(('body', 'native-json', 'unavailable')),
    'phase_at_receipt': frozenset(('body', 'json', 'verification', 'model', 'scene',
                                 'native-json', 'after-scene', 'pending')),
    'outcome': frozenset(('ok', 'timeout', 'invalid_response', 'unavailable')),
}


def _input_observations(source):
    """Keep host intent and browser receipt on distinct, explicitly named clocks."""
    source = source if isinstance(source, list) else []
    records = []
    for record in source:
        record = record if isinstance(record, dict) else {}
        published = {key: _label(record.get(key), allowed)
                     for key, allowed in _INPUT_LABELS.items()}
        for key in ('attempt_ms', 'received_ms', 'frame_ms'):
            published[key] = _nonnegative(record.get(key))
        trusted = record.get('is_trusted')
        published['is_trusted'] = trusted if type(trusted) is bool else None
        if published['received_ms'] is None:
            published['frame_ms'] = None
            published['is_trusted'] = None
            if published['outcome'] == 'ok':
                published['outcome'] = 'unavailable'
        elif published['frame_ms'] is not None and published['frame_ms'] < published['received_ms']:
            published['frame_ms'] = None
            if published['outcome'] == 'ok':
                published['outcome'] = 'invalid_response'
        if published['outcome'] == 'ok' and not _trusted_receipt(published):
            published['outcome'] = ('unavailable' if published['frame_ms'] is None
                                    else 'invalid_response')
        records.append(published)
    return records


def _trusted_receipt(record):
    """Validate only sanitized browser-clock observations, not host-clock intent."""
    return (record['action'] in ('input', 'selection')
            and record['receipt_clock'] == 'browser-performance'
            and record['is_trusted'] is True
            and record['received_ms'] is not None
            and record['frame_ms'] is not None
            and record['frame_ms'] >= record['received_ms'])


def _published_contention_status(status, records):
    """Supplied success requires distinct trusted actions; never upgrade a failure."""
    if status != 'observed-trusted-input':
        return status
    if (len(records) == 2 and {record['action'] for record in records} == {'input', 'selection'}
            and all(record['outcome'] == 'ok' and _trusted_receipt(record) for record in records)):
        return status
    return ('invalid_response' if any(record['outcome'] == 'invalid_response' for record in records)
            else 'unavailable')


def _task_number(value):
    """Keep supplied overlap operands within safe IEEE754 magnitude, unchanged.

    Check integers directly: converting first can overflow or round an unsafe
    mixed int/float endpoint into a plausible but untruthful zero-length span.
    """
    value = _nonnegative(value)
    return value if value is not None and value <= 2**53 - 1 else None


def _task_observations(source, milestones):
    """Publish numeric task spans; overlap is not exclusive CPU/GPU attribution."""
    source = source if isinstance(source, dict) else {}
    tasks = source.get('long_tasks', [])
    tasks = tasks if isinstance(tasks, list) else []
    published_tasks, overlaps = [], []
    for task in tasks:
        task = task if isinstance(task, dict) else {}
        published = {key: _task_number(task.get(key))
                     for key in ('start_ms', 'end_ms', 'duration_ms')}
        published_tasks.append(published)
        overlap = {}
        for phase in ('body', 'native_json', 'json', 'verification', 'model', 'scene'):
            start = _task_number(milestones.get('graph_' + phase + '_start'))
            end = _task_number(milestones.get('graph_' + phase + '_end'))
            task_start, task_end = published['start_ms'], published['end_ms']
            duration = published['duration_ms']
            valid = (all(value is not None for value in (start, end, task_start, task_end, duration))
                     and end >= start and task_end >= task_start
                     and math.isclose(task_end - task_start, duration, rel_tol=1e-9, abs_tol=1e-6))
            overlap[phase] = max(0, min(end, task_end) - max(start, task_start)) if valid else None
        overlaps.append(overlap)
    status = source.get('long_tasks_status')
    status = status if isinstance(status, str) and status in ('observed', 'unavailable') else 'unavailable'
    return {'long_tasks': published_tasks, 'long_tasks_status': status,
            'phase_task_overlap_ms': overlaps,
            'attribution': 'overlap-not-causation', 'gpu_time_ms': None}


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
        if 'observer_mode' in original:
            mode = _label(original['observer_mode'], frozenset(('verified', 'native-json')))
            sample['observer_mode'] = mode
            response = original.get('graph_response', {})
            response = response if isinstance(response, dict) else {}
            digest = response.get('consumed_sha256')
            size = response.get('consumed_bytes')
            verified = (mode == 'verified' and response.get('consumed_identity_status') == 'verified'
                        and isinstance(digest, str) and re.fullmatch('[0-9a-f]{64}', digest)
                        and type(size) is int and size >= 0)
            sample['graph_response'] = {
                'consumed_identity_status': ('verified' if verified else
                    'unavailable-native-json' if mode == 'native-json' else 'unavailable'),
                'consumed_bytes': size if verified else None,
                'consumed_sha256': digest if verified else None,
            }
        records = _input_observations(original.get('input_observations'))
        if 'input_observations' in original:
            sample['input_observations'] = records
        if 'contention_status' in original:
            status = _label(original['contention_status'], frozenset((
                'observed-trusted-input', 'unavailable', 'invalid_response')))
            sample['contention_status'] = _published_contention_status(status, records)
        if 'responsiveness' in original:
            sample['responsiveness'] = _task_observations(
                original['responsiveness'], sample.get('milestones_ms', {}))
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
