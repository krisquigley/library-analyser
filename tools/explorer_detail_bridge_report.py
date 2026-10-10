"""Loss-aware selected-detail publication. Supplied observations are not evidence.

Only browser-performance operands are compared. Handles and raw bodies never
cross this boundary; request identities are replaced with local opaque labels.
"""
import re

from tools.explorer_http_report import _finite_number, _label


def _number(value):
    return value if _finite_number(value) and 0 <= value <= 2**53 - 1 else None


def _integer(value):
    return value if type(value) is int and 0 <= value <= 2**53 - 1 else None


def _boolean(value):
    return value if type(value) is bool else None


def _mapping(value):
    return value if isinstance(value, dict) else {}


def publish_detail_bridge(source):
    """Return sanitized partial observations and whether success is supported.

    This checks correlation assertions supplied by the owned observer, not raw
    identity independently. Unknown or missing evidence never becomes success.
    """
    source = _mapping(source)
    identities = {}

    def request(value):
        if not isinstance(value, (str, int)) or isinstance(value, bool):
            return None
        if value not in identities:
            identities[value] = f'request-{len(identities) + 1}'
        return identities[value]

    def phase(raw, post=False):
        if raw is None:
            return None
        raw = _mapping(raw)
        result = {key: _number(raw.get(key)) for key in
                  ('request_ms', 'headers_ms', 'body_ms', 'parse_ms')}
        result['request_id'] = request(raw.get('request_id'))
        status = raw.get('status')
        result['status'] = status if type(status) is int and 100 <= status <= 599 else None
        result['identity_matches'] = _boolean(raw.get('identity_matches'))
        if post:
            result['accepted'] = _boolean(raw.get('accepted'))
        return result

    fixture = _mapping(source.get('fixture'))
    published = {
        'fixture': {'source': _label(fixture.get('source'), ('public-synthetic-sqlite',)),
                    **{key: _integer(fixture.get(key)) for key in
                       ('schema_version', 'track_count', 'seed', 'history_count')}},
        'server': _label(source.get('server'), ('packaged-explorer-loopback',)),
        'database_unchanged': _boolean(source.get('database_unchanged')),
        **{key: _integer(source.get(key)) for key in
           ('initial_summary_requests', 'unrelated_detail_requests', 'graph_requests',
            'latest_selection_sequence')},
        'graph_outcome': _label(source.get('graph_outcome'),
                                ('ok', 'http_error', 'timeout', 'invalid_response', 'pending')),
        # This bridge has no server observer. Never copy spans or clocks supplied
        # here; request-local server observation has its own publication boundary.
        'server_phases': {'status': 'unavailable', 'clock': None, 'spans': None},
        'cleanup': {key: _boolean(_mapping(source.get('cleanup')).get(key)) for key in
                    ('browser_closed', 'server_closed', 'scratch_removed')},
        'selections': [],
    }
    retry_count = _integer(source.get('graph_retry_count', 0))
    outcomes = source.get('graph_attempt_outcomes')
    published['graph_retry_count'] = retry_count
    if 'graph_attempt_outcomes' in source:
        published['graph_attempt_outcomes'] = [
            _label(value, ('ok', 'http_error', 'timeout', 'invalid_response'))
            for value in outcomes] if isinstance(outcomes, list) else []
    valid_graph_inventory = (published['graph_requests'] == 1 and retry_count == 0) or (
        published['graph_requests'] == 2 and retry_count == 1
        and published.get('graph_attempt_outcomes') == ['http_error', 'ok'])
    if 'graph_consumed' in source:
        consumed = _mapping(source['graph_consumed'])
        digest = consumed.get('sha256')
        published['graph_consumed'] = {
            'body_bytes': _integer(consumed.get('body_bytes')),
            'sha256': digest if isinstance(digest, str) and re.fullmatch('[0-9a-f]{64}', digest) else None,
        }
    if 'graph_matches_fixture' in source:
        published['graph_matches_fixture'] = _boolean(source['graph_matches_fixture'])
    raw_selections = source.get('selections')
    for raw in raw_selections if isinstance(raw_selections, list) else []:
        raw = _mapping(raw)
        selected = {
            'sequence': _integer(raw.get('sequence')),
            'clock': _label(raw.get('clock'), ('browser-performance',)),
            **{key: _number(raw.get(key)) for key in
               ('receipt_ms', 'loading_dom_ms', 'loading_frame_ms',
                'detail_dom_ready_ms', 'detail_next_frame_ms')},
            'loading_frame_was_busy': _boolean(raw.get('loading_frame_was_busy')),
            'post': phase(raw.get('post'), post=True),
            'detail': phase(raw.get('detail')),
        }
        if 'is_trusted' in raw:
            selected['is_trusted'] = _boolean(raw['is_trusted'])
        # Presentation evidence and visible DOM identity are distinct from
        # request/DTO correlation. Missing fields retain supplied-mock compatibility.
        for key in ('detail_presented', 'dom_identity_matches'):
            if key in raw:
                selected[key] = _boolean(raw[key])
        published['selections'].append(selected)

    def ordered(values):
        return all(value is not None for value in values) and all(
            earlier <= later for earlier, later in zip(values, values[1:]))

    def complete(selected):
        post, detail = selected['post'], selected['detail']
        if not post or not detail:
            return False
        return (('is_trusted' not in selected or selected['is_trusted'] is True)
                and ('detail_presented' not in selected or selected['detail_presented'] is True)
                and selected['clock'] == 'browser-performance'
                and post['accepted'] is True and post['identity_matches'] is True
                and detail['identity_matches'] is True
                and post['status'] == 200 and detail['status'] == 200
                and post['request_id'] is not None and detail['request_id'] is not None
                and post['request_id'] != detail['request_id']
                and ordered([selected['receipt_ms'], selected['loading_dom_ms']])
                and ordered([selected['loading_dom_ms'], selected['loading_frame_ms']])
                and ordered([selected['receipt_ms'], *[post[key] for key in
                             ('request_ms', 'headers_ms', 'body_ms', 'parse_ms')],
                             *[detail[key] for key in ('request_ms', 'headers_ms', 'body_ms', 'parse_ms')],
                             selected['detail_dom_ready_ms'], selected['detail_next_frame_ms']]))

    selections = published['selections']
    sequences = [s['sequence'] for s in selections]
    request_ids = [s[phase]['request_id'] for s in selections for phase in ('post', 'detail')
                   if s[phase] is not None]
    valid = (published['fixture']['source'] == 'public-synthetic-sqlite'
             and published['fixture']['schema_version'] == 10
             and published['fixture']['track_count'] is not None
             and 12 <= published['fixture']['track_count'] <= 20000
             and published['fixture']['seed'] is not None
             and 0 <= published['fixture']['seed'] <= 2**32 - 1
             and published['fixture']['history_count'] in (1, 2, 3)
             and ('graph_matches_fixture' not in published or published['graph_matches_fixture'] is True)
             and ('graph_consumed' not in published or
                  (published['graph_consumed']['sha256'] is not None
                   and published['graph_consumed']['body_bytes'] is not None))
             and published['server'] == 'packaged-explorer-loopback'
             and published['database_unchanged'] is True
             and published['initial_summary_requests'] == 0
             and published['unrelated_detail_requests'] == 0
             and valid_graph_inventory
             and all(value is True for value in published['cleanup'].values())
             and bool(selections) and all(s is not None and s > 0 for s in sequences)
             and sequences == sorted(set(sequences))
             and published['latest_selection_sequence'] == sequences[-1]
             and len(set(request_ids)) == len(request_ids)
             and all(complete(s) for s in selections))
    return published, valid
