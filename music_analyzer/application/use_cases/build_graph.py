"""Application use case for persisting the explicit catalogue graph snapshot."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

from music_analyzer.application.ports.graph import GraphSnapshotWriter
from music_analyzer.application.use_cases.active_library import is_active_library_track
from music_analyzer.application.use_cases.candidates import _features
from music_analyzer.application.use_cases.explorer import _axis_node, _map_track
from music_analyzer.domain.projection import DISTANCE_POLICY_VERSION, NEIGHBOUR_POLICY_VERSION, _bounded_edges


@dataclass(frozen=True)
class GraphBuildResult:
    edge_count: int
    source_fingerprint: str
    distance_policy_version: str = DISTANCE_POLICY_VERSION
    neighbour_policy_version: str = NEIGHBOUR_POLICY_VERSION


class BuildGraphSnapshot:
    """Build and persist the current sparse graph from retained completed evidence.

    The use case depends on repository protocols by shape: the read repository
    provides ``candidate_snapshot()`` and the write repository provides
    ``replace_graph_snapshot(...)``.  SQLite, CLI parsing, and filesystem details
    stay outside this application orchestration.
    """

    def __init__(self, read_repository, write_repository: GraphSnapshotWriter, sparse_k: int = 10):
        self.read_repository = read_repository
        self.write_repository = write_repository
        self.sparse_k = sparse_k

    def execute(self) -> GraphBuildResult:
        _metadata, records = self.read_repository.candidate_snapshot()
        retained = tuple(
            record for record in records
            if is_active_library_track(record) and record.run is not None and record.run.status == 'completed'
        )
        features = tuple(_features(record) for record in retained)
        positioned = tuple(record for record in retained if _axis_node(record, _map_track(record), '')[0] is not None)
        positioned_features = tuple(_features(record) for record in positioned)
        edges = tuple(_bounded_edges(features, self.sparse_k))
        positioned_edges = tuple(_bounded_edges(positioned_features, self.sparse_k))
        fingerprint = _source_fingerprint(retained)
        self.write_repository.replace_graph_snapshot(edges, self.sparse_k, fingerprint, positioned_edges)
        return GraphBuildResult(len(edges), fingerprint)


def _source_fingerprint(records) -> str:
    evidence = []
    for record in sorted(records, key=lambda item: item.track_id):
        stages = []
        for stage in sorted(record.run.stages, key=lambda item: item.stage):
            stages.append({
                'stage': stage.stage,
                'provenance': stage.provenance,
                'uncertainty': stage.uncertainty,
                'values': stage.values,
                'summary': (
                    None if stage.summary is None else {
                        'labels': stage.summary.labels,
                        'mean': stage.summary.mean,
                        'minimum': stage.summary.minimum,
                        'maximum': stage.summary.maximum,
                        'coverage': stage.summary.coverage,
                        'provisional': stage.summary.provisional,
                        'uncertainty': stage.summary.uncertainty,
                    }
                ),
            })
        evidence.append({'track_id': record.track_id, 'run_id': record.run.run_id, 'stages': stages})
    payload = json.dumps(evidence, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()
