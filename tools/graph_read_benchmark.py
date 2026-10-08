"""Bounded synthetic graph-read integrity reporting, not a latency benchmark.

Probes supply a public http.client-like response. No server, database, resource
limit or live-library access is created by the measurement API.
"""
from __future__ import annotations

import hashlib
import json
import math
from fractions import Fraction

from music_explorer.interface_adapters.mood_axis_graph_http import INDEXED_DTO_VERSION


def nearest_rank(values, percentile):
    """Return the observed value at ceil(p/100 * N), without interpolation."""
    ordered = sorted(values)
    if not ordered or not 0 < percentile <= 100:
        raise ValueError('Require samples and a percentile in (0, 100]')
    # Preserve decimal percentile boundaries instead of rounding them in float arithmetic.
    rank = math.ceil(Fraction(str(percentile)) * len(ordered) / 100)
    return ordered[rank - 1]


def summarize_work(*, raw_rows, validations):
    """Copy observed per-identity counters; never infer work from SQL or N."""
    return {
        'raw_rows': dict(raw_rows),
        'validations': dict(validations),
        'raw_row_total': sum(raw_rows.values()),
        'validation_total': sum(validations.values()),
    }


def _index(value, table):
    return type(value) is int and 0 <= value < len(table)


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _v3_counts(payload):
    """Check the indexed envelope, row shapes and table references.

    This is response integrity checking, not a replacement for the readers'
    complete graph-feature-evidence semantic validation.
    """
    if not isinstance(payload, dict) or payload.get('dto_version') != INDEXED_DTO_VERSION:
        raise ValueError('Not an indexed v3 response')
    arrays = ('axis', 'available_moods', 'genre_labels', 'reason_text',
              'provenance_table', 'explanation_table', 'nodes', 'links', 'unpositioned')
    if any(not isinstance(payload.get(key), list) for key in arrays):
        raise ValueError('Missing indexed array')
    if not isinstance(payload.get('metadata'), dict) or not isinstance(payload.get('link_defaults'), dict):
        raise ValueError('Missing indexed mapping')
    if payload.get('selected_mood') is not None and not isinstance(payload['selected_mood'], str):
        raise ValueError('Invalid selected mood')
    for key in ('available_moods', 'genre_labels', 'reason_text', 'explanation_table'):
        if any(not isinstance(value, str) for value in payload[key]):
            raise ValueError('Invalid string table')
    if len(payload['axis']) != 3 or any(
        not isinstance(axis, dict) or any(
            not isinstance(axis.get(key), str) or not axis[key] for key in ('key', 'label', 'scale')
        )
        for axis in payload['axis']
    ):
        raise ValueError('Invalid axes')
    if {axis['key'] for axis in payload['axis']} != {'x', 'y', 'z'}:
        raise ValueError('Invalid axis keys')
    if any(not isinstance(item, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in item.items())
           for item in payload['provenance_table']):
        raise ValueError('Invalid provenance table')
    identities = set()
    for node in payload['nodes']:
        if not isinstance(node, list) or len(node) != 13:
            raise ValueError('Invalid indexed node')
        if not all(isinstance(node[i], str) for i in (0, 1)) or node[0] in identities:
            raise ValueError('Invalid node identity')
        identities.add(node[0])
        if not all(_number(node[i]) for i in (*range(2, 8), 12)) or any(
            node[i] is not None and not _number(node[i]) for i in (8, 9)
        ):
            raise ValueError('Invalid node number')
        if not isinstance(node[10], list) or any(
            not isinstance(genre, list) or len(genre) != 2 or
            not _index(genre[0], payload['genre_labels']) or not _number(genre[1])
            for genre in node[10]
        ):
            raise ValueError('Invalid genres')
        if not isinstance(node[11], list) or any(not _index(i, payload['reason_text']) for i in node[11]):
            raise ValueError('Invalid reasons')
    for track in payload['unpositioned']:
        if not isinstance(track, list) or len(track) != 3 or not all(isinstance(track[i], str) for i in (0, 1)):
            raise ValueError('Invalid unpositioned track')
        if track[0] in identities or not isinstance(track[2], list) or any(not _index(i, payload['reason_text']) for i in track[2]):
            raise ValueError('Invalid unpositioned identity/reasons')
        identities.add(track[0])
    defaults = payload['link_defaults']
    for key, table in (('explanation', 'explanation_table'), ('provenance', 'provenance_table')):
        if key in defaults and not _index(defaults[key], payload[table]):
            raise ValueError('Invalid link default')
    for link in payload['links']:
        if not isinstance(link, list) or len(link) not in (4, 6):
            raise ValueError('Invalid indexed link')
        if not all(_index(link[i], payload['nodes']) for i in (0, 1)) or not _number(link[2]) or type(link[3]) is not int or link[3] < 0:
            raise ValueError('Invalid link values')
        for position, key, table in ((4, 'explanation', 'explanation_table'), (5, 'provenance', 'provenance_table')):
            reference = link[position] if len(link) == 6 else defaults.get(key)
            if not _index(reference, payload[table]):
                raise ValueError('Invalid link table reference')
    return {key: len(payload[key]) for key in ('nodes', 'links', 'unpositioned')}


def _reject_nonfinite_json(value):
    raise ValueError(f'Nonfinite JSON number: {value}')


def _inspect_response(response, expected, sample):
    sample['http_status'] = response.status
    body = response.read()
    sample['body_bytes'] = len(body)
    sample['sha256'] = hashlib.sha256(body).hexdigest()
    if response.status != 200:
        return 'http_status'
    try:
        length = int(response.getheader('Content-Length'))
    except (ValueError, TypeError):
        return 'content_length'
    if length != len(body):
        return 'content_length'
    try:
        payload = json.loads(body, parse_constant=_reject_nonfinite_json)
        sample['counts'] = _v3_counts(payload)
    except (ValueError, TypeError, UnicodeError):
        return 'invalid_v3'
    if sample['sha256'] != expected['sha256']:
        return 'body_hash'
    if sample['counts'] != expected['counts']:
        return 'counts'
    return 'ok'


def measure_samples(probes, *, expected, db_fingerprint):
    """Retain each attempted exchange and bracket it with DB fingerprints.

    Timeout/OOM are reported failures, never absent samples. The supplied probe
    owns its transport timeout; this synchronous API cannot impose one safely.
    No timing claim is made for fake responses.
    """
    samples = []
    for index, probe in enumerate(probes):
        sample = {'index': index}
        before = None
        before_available = False
        try:
            before = db_fingerprint()
            before_available = True
            sample['outcome'] = _inspect_response(probe(), expected, sample)
        except TimeoutError:
            sample['outcome'] = 'timeout'
        except MemoryError:
            sample['outcome'] = 'oom'
        except Exception as error:
            sample['outcome'] = 'error'
            sample['error_type'] = type(error).__name__
        finally:
            try:
                after = db_fingerprint()
                if before_available and before != after:
                    sample['exchange_outcome'] = sample['outcome']
                    sample['outcome'] = 'db_changed'
            except Exception as error:
                sample['exchange_outcome'] = sample['outcome']
                sample['outcome'] = 'fingerprint_error'
                sample['error_type'] = type(error).__name__
        samples.append(sample)
    return {'samples': samples, 'attempted': len(samples),
            'succeeded': sum(sample['outcome'] == 'ok' for sample in samples)}


def _synthetic_smoke():
    from music_explorer.application.dto.explorer import (
        AxisValue, MoodAxisEdge, MoodAxisGraph, MoodAxisNode, UnpositionedTrack,
    )
    from music_explorer.interface_adapters.mood_axis_graph_http import to_indexed_mood_axis_graph_http

    x = AxisValue('valence', 0.3, 0.3, 'synthetic')
    y = AxisValue('arousal', 0.4, 0.4, 'synthetic')
    z = AxisValue('BPM', 120.0, 6.0, 'fixed-BPM/20-display-units')
    graph = MoodAxisGraph(
        metadata={'track_count': 3}, selected_mood='relaxing', available_moods=('relaxing',),
        positioned=tuple(
            MoodAxisNode(identity, label, x, y, z, 120.0, (('synthetic genre', 0.8),),
                         reasons=('Public synthetic evidence only',))
            for identity, label in (('synthetic-a', '楽しい'), ('synthetic-b', 'Synthetic B'))
        ),
        unpositioned=(UnpositionedTrack('synthetic-c', 'Synthetic C', ('No position',)),),
        edges=(MoodAxisEdge('synthetic-a', 'synthetic-b', 0.8, 'Synthetic link',
                            {'source': 'public synthetic'}, 1),),
    )
    body = json.dumps(to_indexed_mood_axis_graph_http(graph), sort_keys=True,
                      ensure_ascii=False, allow_nan=False).encode('utf-8')

    class SyntheticResponse:
        status = 200

        def read(self):
            return body

        def getheader(self, name, default=None):
            return str(len(body)) if name == 'Content-Length' else default

    measurement = measure_samples(
        [SyntheticResponse],
        expected={'sha256': hashlib.sha256(body).hexdigest(),
                  'counts': {'nodes': 2, 'links': 1, 'unpositioned': 1}},
        db_fingerprint=lambda: 'no-database-in-synthetic-smoke',
    )
    return {
        'synthetic_only': True,
        'scope': 'public-synthetic-smoke',
        'measurement': measurement,
        'limitations': ['Fake HTTP response; no transport timing or resource measurement',
                        'No database opened; no database work characterized'],
    }


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--synthetic-smoke', action='store_true',
                        help='check one public synthetic DTO through the real v3 mapper')
    args = parser.parse_args(argv)
    if not args.synthetic_smoke:
        parser.error('Select --synthetic-smoke; live/private targets are not supported')
    report = _synthetic_smoke()
    print(json.dumps(report, sort_keys=True, ensure_ascii=False, allow_nan=False))
    return 0 if report['measurement']['succeeded'] == report['measurement']['attempted'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
