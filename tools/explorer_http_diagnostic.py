"""Opt-in diagnostic against disposable public data over loopback HTTP only.

Fixture construction and SQLite observation are outside request timing. This
outward composition tool neither changes the server nor accepts private paths.
No browser, rendering, server sub-phase or host-independent latency is inferred.
"""
from contextlib import contextmanager
import json
import math
import socket
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from music_explorer.frameworks.explorer.server import create_server
from tools.explorer_fixture_inspection import fingerprint_sqlite_files
from tools.explorer_http_report import publish_http_report
from tools.explorer_http_sqlite_observation import observe_sqlite
from tools.explorer_synthetic_fixture import public_synthetic_fixture, _validate_options

__all__ = ['publish_http_report', 'run_public_http_diagnostic']


def _validate_request_options(sample_count, timeout_seconds):
    if type(sample_count) is not int or not 1 <= sample_count <= 100:
        raise ValueError('Require integer sample_count between 1 and 100')
    if (type(timeout_seconds) not in (int, float)
            or not 0 < timeout_seconds <= 60 or not math.isfinite(timeout_seconds)):
        raise ValueError('Require finite timeout_seconds greater than zero and at most 60')


@contextmanager
def _running_server(factory, database_path):
    server = factory(str(database_path), host='127.0.0.1', port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    started = False
    try:
        thread.start()
        started = True
        yield 'http://127.0.0.1:' + str(server.server_port)
    finally:
        try:
            if started:
                server.shutdown()
        finally:
            try:
                server.server_close()
            finally:
                if started:
                    thread.join()


def _request(base, path, method, timeout, requests, intervals, phase, body=None):
    start = time.monotonic()
    observation = {'method': method, 'url': base + path, 'status': None,
                   'outcome': 'connection_error', 'response_bytes': 0}
    payload = None
    data = None if body is None else json.dumps(body, allow_nan=False).encode('utf-8')
    request = Request(base + path, data=data, method=method,
                      headers={'Content-Type': 'application/json'} if data is not None else {})
    try:
        with urlopen(request, timeout=timeout) as response:
            observation['status'] = response.status
            entity = response.read()
            observation['response_bytes'] = len(entity)
            try:
                payload = json.loads(entity)
                observation['outcome'] = 'ok'
            except (ValueError, UnicodeError):
                observation['outcome'] = 'invalid_response'
    except HTTPError as error:
        with error:
            observation['status'] = error.code
            observation['response_bytes'] = len(error.read())
            observation['outcome'] = 'http_error'
    except (TimeoutError, socket.timeout):
        observation['outcome'] = 'timeout'
    except URLError as error:
        observation['outcome'] = ('timeout' if isinstance(error.reason, TimeoutError)
                                  else 'connection_error')
    except OSError:
        observation['outcome'] = 'connection_error'
    end = time.monotonic()
    observation['elapsed_ms'] = (end - start) * 1000
    requests.append(observation)
    intervals.append({'clock': 'monotonic', 'flow': 'selection', 'phase': phase,
                      'start_ms': start * 1000, 'end_ms': end * 1000})
    return payload, observation['outcome']


def _sample(base, timeout, requests, intervals, token):
    start = time.monotonic()
    state, outcome = _request(base, '/api/state', 'GET', timeout, requests, intervals, 'get_state')
    if outcome == 'ok':
        if not isinstance(state, dict) or type(state.get('selection_epoch')) is not int:
            outcome = 'invalid_response'
    summary = None
    if outcome == 'ok':
        query = urlencode({'limit': 1, 'query': 'Synthetic', 'order': 'id'})
        summary, outcome = _request(base, '/api/tracks/summary?' + query,
                                    'GET', timeout, requests, intervals, 'get_summary')
    handle = None
    if outcome == 'ok':
        try:
            handle = summary['tracks'][0]['handle']
            if not isinstance(handle, str) or not handle:
                outcome = 'invalid_response'
        except (KeyError, IndexError, TypeError):
            outcome = 'invalid_response'
    if outcome == 'ok':
        selected, outcome = _request(
            base, '/api/current', 'POST', timeout, requests, intervals, 'post_current',
            {'track_id': handle, 'selection_token': token,
             'selection_epoch': state['selection_epoch'],
             'selection_client_id': 'public-http-diagnostic'})
        if outcome == 'ok' and (not isinstance(selected, dict)
                                or selected.get('current_track_id') != handle):
            outcome = 'invalid_response'
    if outcome == 'ok':
        _, outcome = _request(base, '/api/tracks/' + quote(handle, safe=''), 'GET',
                              timeout, requests, intervals, 'get_detail')
    # In-process execution does not establish process-cold conditions. A single
    # warm profile retains every attempted sequential interaction honestly.
    return {'profile': 'warm', 'outcome': outcome,
            'elapsed_ms': (time.monotonic() - start) * 1000}


def run_public_http_diagnostic(*, track_count=12, seed=70, history_count=2,
                               allow_large=False, sample_count=1,
                               timeout_seconds=5.0, server_factory=create_server,
                               fixture_factory=public_synthetic_fixture):
    """Run bounded selection/detail samples; retain failures and clean ownership.

    Factories are outward test seams, not private catalogue path inputs. Reader
    validation remains enabled, including unrelated historical evidence checks.
    The fixture owner is quiescent throughout before/after byte fingerprints.
    """
    _validate_request_options(sample_count, timeout_seconds)
    # Reuse the outward writer's bounds even when the fixture seam is injected.
    # This tool-to-tool private helper avoids divergent expensive-profile policy.
    _validate_options(track_count, seed, history_count, allow_large)
    requests, intervals, attempts = [], [], []
    with fixture_factory(track_count=track_count, seed=seed, history_count=history_count,
                         allow_large=allow_large) as fixture:
        database = fixture['db_path']
        before = fingerprint_sqlite_files(database)
        with observe_sqlite() as observation:
            with _running_server(server_factory, database) as base:
                for token in range(1, sample_count + 1):
                    attempts.append(_sample(base, timeout_seconds, requests, intervals, token))
            sqlite_report = observation.report(database)
        after = fingerprint_sqlite_files(database)
        report = publish_http_report(attempts=attempts, intervals=intervals, requests=requests)
        report.update({
            'fixture_manifest': fixture['manifest'], 'sqlite': sqlite_report,
            'readonly': {'before': before, 'after': after, 'unchanged': before == after,
                         'context': 'caller-owned-quiescent'},
            'phases': {name: {'status': 'unavailable',
                             'reason': 'Uninstrumented server phase; HTTP duration is not phase evidence'}
                       for name in ('validation', 'membership', 'selected_sql',
                                    'stage_parse', 'mapping', 'serialization')},
        })
        return report
