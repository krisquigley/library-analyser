"""HTTP DTO mapping for the mood-axis graph browser contract.

This adapter lives at the outer boundary: application use cases continue to
return the verbose ``MoodAxisGraph`` DTO, and HTTP/browser delivery opts in to
compact or indexed HTTP representations explicitly.
"""

from __future__ import annotations

from collections.abc import Mapping
from math import isfinite
from typing import Any

from music_explorer.application.dto.explorer import AxisValue, MoodAxisGraph

DTO_VERSION = 'mood-axis-graph-compact-v1'
INDEXED_DTO_VERSION = 'mood-axis-graph-indexed-v1'

_METADATA_KEYS = (
    'graph_status',
    'source_fingerprint',
    'fingerprint',
    'source_revision',
    'track_count',
    'schema_version',
)


def to_compact_mood_axis_graph_http(graph: MoodAxisGraph) -> dict[str, Any]:
    """Map the application graph DTO to the compact versioned HTTP contract."""

    return {
        'dto_version': DTO_VERSION,
        'selected_mood': graph.selected_mood,
        'available_moods': list(graph.available_moods),
        'metadata': _compact_metadata(graph.metadata),
        'nodes': [
            {
                'id': node.track_id,
                'label': node.display_label,
                'axis': {
                    'x': _axis(node.x),
                    'y': _axis(node.y),
                    'z': _axis(node.z),
                },
                'bpm': node.bpm,
                'genres': [[label, score] for label, score in node.genres],
                'genre_threshold': node.genre_threshold,
                'mood_score': _axis(node.mood_score) if node.mood_score is not None else None,
                'reasons': list(node.reasons),
            }
            for node in graph.positioned
        ],
        'unpositioned': [
            {
                'id': track.track_id,
                'label': track.display_label,
                'reasons': list(track.reasons),
            }
            for track in graph.unpositioned
        ],
        'links': [
            {
                'source': edge.a,
                'target': edge.b,
                'score': edge.score,
                'explanation': edge.explanation,
                'provenance': edge.provenance,
                'supported_group_count': edge.supported_group_count,
            }
            for edge in graph.edges
        ],
    }


def to_indexed_mood_axis_graph_http(graph: MoodAxisGraph) -> dict[str, Any]:
    """Map the application graph DTO to the opt-in indexed v3 HTTP contract."""

    positioned_index = {node.track_id: index for index, node in enumerate(graph.positioned)}
    genre_labels = _Table()
    reason_text = _Table()
    explanation_table = _Table()
    provenance_table = _Table(_freeze_mapping)

    links: list[list[Any]] = []
    for edge in graph.edges:
        if edge.a not in positioned_index or edge.b not in positioned_index:
            raise ValueError('Mood-axis graph edge references an unknown positioned node')
        _finite(edge.score, 'edge score')
        explanation_index = explanation_table.index(edge.explanation)
        provenance_index = provenance_table.index(dict(edge.provenance))
        row: list[Any] = [
            positioned_index[edge.a],
            positioned_index[edge.b],
            edge.score,
            edge.supported_group_count,
        ]
        if explanation_index != 0 or provenance_index != 0:
            row.extend([explanation_index, provenance_index])
        links.append(row)

    nodes = []
    for node in graph.positioned:
        nodes.append([
            node.track_id,
            node.display_label,
            _axis_raw(node.x),
            _axis_normalized(node.x),
            _axis_raw(node.y),
            _axis_normalized(node.y),
            _axis_raw(node.z),
            _axis_normalized(node.z),
            _optional_finite(node.bpm, 'bpm'),
            _optional_finite(node.mood_score.normalized, 'mood score') if node.mood_score is not None else None,
            [[genre_labels.index(label), _finite(score, 'genre score')] for label, score in node.genres],
            [reason_text.index(reason) for reason in node.reasons],
            _finite(node.genre_threshold, 'genre threshold'),
        ])

    unpositioned = [
        [track.track_id, track.display_label, [reason_text.index(reason) for reason in track.reasons]]
        for track in graph.unpositioned
    ]

    return {
        'dto_version': INDEXED_DTO_VERSION,
        'selected_mood': graph.selected_mood,
        'available_moods': list(graph.available_moods),
        'metadata': _compact_metadata(graph.metadata),
        'axis': _axis_table(graph),
        'genre_labels': genre_labels.values,
        'reason_text': reason_text.values,
        'provenance_table': provenance_table.values,
        'explanation_table': explanation_table.values,
        'link_defaults': _link_defaults(explanation_table, provenance_table),
        'nodes': nodes,
        'unpositioned': unpositioned,
        'links': links,
    }


def _axis(value: AxisValue) -> dict[str, Any]:
    return {
        'label': value.label,
        'raw': _finite(value.raw, 'axis raw'),
        'normalized': _finite(value.normalized, 'axis normalized'),
        'scale': value.scale,
    }


def _axis_raw(value: AxisValue) -> float:
    return _finite(value.raw, 'axis raw')


def _axis_normalized(value: AxisValue) -> float:
    return _finite(value.normalized, 'axis normalized')


def _axis_table(graph: MoodAxisGraph) -> list[dict[str, str]]:
    if graph.positioned:
        sample = graph.positioned[0]
        return [
            {'key': 'x', 'label': sample.x.label, 'scale': sample.x.scale},
            {'key': 'y', 'label': sample.y.label, 'scale': sample.y.scale},
            {'key': 'z', 'label': sample.z.label, 'scale': sample.z.scale},
        ]
    return [
        {'key': 'x', 'label': 'valence', 'scale': 'native-emomusic-valence-regression'},
        {'key': 'y', 'label': 'arousal', 'scale': 'native-emomusic-arousal-regression'},
        {'key': 'z', 'label': 'BPM', 'scale': 'fixed-BPM/20-display-units'},
    ]


def _link_defaults(explanation_table: '_Table', provenance_table: '_Table') -> dict[str, int]:
    defaults: dict[str, int] = {}
    if explanation_table.values:
        defaults['explanation'] = 0
    if provenance_table.values:
        defaults['provenance'] = 0
    return defaults


def _compact_metadata(metadata: Mapping[str, object]) -> dict[str, object]:
    compact = {key: metadata[key] for key in _METADATA_KEYS if key in metadata}
    graph_status = compact.get('graph_status')
    if isinstance(graph_status, Mapping):
        compact['graph_status'] = dict(graph_status)
    return compact


def _finite(value: float, label: str) -> float:
    if not isfinite(value):
        raise ValueError(f'Mood-axis graph {label} must be finite')
    return value


def _optional_finite(value: float | None, label: str) -> float | None:
    if value is None:
        return None
    return _finite(value, label)


def _freeze_mapping(value: Mapping[str, str]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((str(key), str(item)) for key, item in value.items()))


class _Table:
    def __init__(self, key=lambda value: value):
        self.values: list[Any] = []
        self._indices: dict[Any, int] = {}
        self._key = key

    def index(self, value: Any) -> int:
        key = self._key(value)
        if key not in self._indices:
            self._indices[key] = len(self.values)
            self.values.append(value)
        return self._indices[key]
