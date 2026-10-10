"""Pure public synthetic indexed-v3 payloads for browser-only diagnostics.

This outward development tool has no catalogue, SQLite, audio, network or file
inputs. The large profile inflates public explanation strings to exactly 41 MiB;
it models transfer/parse/render work, not catalogue fidelity or server speed.
Only the explicit large opt-in allocates that payload. Each call owns its bytes
and manifest; nothing is cached or shared with callers.
"""
import gzip
import hashlib
import io
import json


_SOURCE = 'public-synthetic-browser-only'
_DTO_VERSION = 'mood-axis-graph-indexed-v1'
_LARGE_BYTES = 41 * 2**20


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')


def _validate_options(profile, seed, allow_large):
    if (type(profile) is not str or profile not in ('small', 'stress-41mib')
            or type(seed) is not int or not 0 <= seed < 2**32
            or type(allow_large) is not bool):
        raise ValueError('Invalid public browser graph fixture options')
    if profile == 'stress-41mib' and not allow_large:
        raise ValueError('Large browser graph fixture requires explicit opt-in')


def _document(node_count, seed):
    return {
        'dto_version': _DTO_VERSION,
        'selected_mood': None,
        'available_moods': [],
        'metadata': {'track_count': node_count},
        'axis': [
            {'key': 'x', 'label': 'valence', 'scale': 'native-emomusic-valence-regression'},
            {'key': 'y', 'label': 'arousal', 'scale': 'native-emomusic-arousal-regression'},
            {'key': 'z', 'label': 'BPM', 'scale': 'fixed-BPM/20-display-units'},
        ],
        'genre_labels': ['Public synthetic genre'],
        'reason_text': [],
        'provenance_table': [{'source': _SOURCE}],
        'explanation_table': [f'Public synthetic link {i:05d}; '
                              for i in range(node_count - 1)],
        'link_defaults': {'explanation': 0, 'provenance': 0},
        'nodes': [[f'public-{i:05d}', f'Public synthetic {seed} node {i:05d}',
                   (i % 11) / 10, (i % 11) / 10, (i % 7) / 6, (i % 7) / 6,
                   120, 6, 120, None, [[0, 0.75]], [], 0.5]
                  for i in range(node_count)],
        'unpositioned': [],
        'links': [[i, i + 1, 0.5, 1, i, 0] for i in range(node_count - 1)],
    }


def _inflate_explanations(document, unpadded_bytes):
    explanations = document['explanation_table']
    padding, remainder = divmod(_LARGE_BYTES - unpadded_bytes, len(explanations))
    # ASCII x needs no JSON escaping: every appended character adds one byte.
    document['explanation_table'] = [
        text + 'x' * (padding + (index < remainder))
        for index, text in enumerate(explanations)
    ]


def _gzip(body):
    stream = io.BytesIO()
    with gzip.GzipFile(fileobj=stream, mode='wb', filename='', mtime=0,
                       compresslevel=9) as encoder:
        encoder.write(body)
    return stream.getvalue()


def _body_manifest(body):
    return {'body_bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest()}


def public_browser_graph_fixture(profile='small', seed=70, allow_large=False):
    """Return canonical decoded JSON, deterministic gzip and a public manifest.

    Profiles fix cardinality (12 or 20,000 positioned nodes, a chain of links).
    Seed changes public names only and must be an unsigned 32-bit integer.
    Unsupported options deliberately raise TypeError rather than accepting
    arbitrary targets, byte sizes or unbounded cardinalities.
    """
    _validate_options(profile, seed, allow_large)
    node_count = 12 if profile == 'small' else 20000
    document = _document(node_count, seed)
    decoded = _canonical(document)
    if profile == 'stress-41mib':
        _inflate_explanations(document, len(decoded))
        decoded = _canonical(document)
    encoded = _gzip(decoded)
    return {
        'decoded_body': decoded,
        'encoded_body': encoded,
        'manifest': {
            'source': _SOURCE,
            'profile': profile,
            'seed': seed,
            'dto_version': _DTO_VERSION,
            'content_encoding': 'gzip',
            'encoding_profile': 'gzip-mtime0-level9',
            'counts': {'nodes': node_count, 'links': node_count - 1, 'unpositioned': 0},
            'decoded': _body_manifest(decoded),
            'encoded': _body_manifest(encoded),
        },
    }
