"""HTTP DTO mapping for the mood-axis graph browser contract.

This adapter lives at the outer boundary: application use cases continue to
return the verbose ``MoodAxisGraph`` DTO, and HTTP/browser delivery opts in to
this compact representation explicitly.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from music_explorer.application.dto.explorer import AxisValue, MoodAxisGraph

DTO_VERSION = 'mood-axis-graph-compact-v1'

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


def _axis(value: AxisValue) -> dict[str, Any]:
    return {
        'label': value.label,
        'raw': value.raw,
        'normalized': value.normalized,
        'scale': value.scale,
    }


def _compact_metadata(metadata: Mapping[str, object]) -> dict[str, object]:
    compact = {key: metadata[key] for key in _METADATA_KEYS if key in metadata}
    graph_status = compact.get('graph_status')
    if isinstance(graph_status, Mapping):
        compact['graph_status'] = dict(graph_status)
    return compact
