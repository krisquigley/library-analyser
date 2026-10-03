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


GRAPH_SOURCE_OVERRIDE_FIELDS = frozenset({'bpm', 'key', 'genres', 'mood', 'energy'})


@dataclass(frozen=True)
class GraphBuildResult:
    edge_count: int
    source_fingerprint: str
    distance_policy_version: str = DISTANCE_POLICY_VERSION
    neighbour_policy_version: str = NEIGHBOUR_POLICY_VERSION
    state: str = 'built'
    reason: str = ''


@dataclass(frozen=True)
class GraphEnsureResult:
    state: str
    built: bool
    edge_count: int | None = None
    reason: str = ''
    action: str = ''


class EnsureCurrentGraphSnapshot:
    """Ensure a current durable graph snapshot exists without duplicate work.

    This application service owns the post-analysis orchestration decision.  It
    asks the persistence port whether the exact v10 graph snapshot for the
    current source revision and policy is already available or actively being
    built.  Only stale/missing/failed/interrupted states are delegated to the
    graph builder.
    """

    def __init__(self, read_repository, write_repository, sparse_k: int = 10, builder_factory=None):
        self.read_repository = read_repository
        self.write_repository = write_repository
        self.sparse_k = sparse_k
        self.builder_factory = builder_factory

    def execute(self) -> GraphEnsureResult:
        source_revision = self.write_repository.source_revision()
        status = self.write_repository.current_graph_snapshot(self.sparse_k, source_revision)
        state = status.get('state', '')
        if state in {'ready', 'building'}:
            return GraphEnsureResult(state, False, status.get('edge_count'), status.get('reason', ''), status.get('action', ''))
        builder_factory = self.builder_factory or BuildGraphSnapshot
        if self.sparse_k == 10:
            builder = builder_factory(self.read_repository, self.write_repository)
        else:
            builder = builder_factory(self.read_repository, self.write_repository, self.sparse_k)
        result = builder.execute()
        if getattr(result, 'state', '') == 'building':
            return GraphEnsureResult('building', False, None, getattr(result, 'reason', 'warm graph build is running'))
        return GraphEnsureResult('built', True, getattr(result, 'edge_count', None))


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
        source_revision = self.write_repository.source_revision() if hasattr(self.write_repository, 'source_revision') else None
        claimed = source_revision is None or not hasattr(self.write_repository, 'begin_graph_build')
        attempt_id = None
        if source_revision is not None and hasattr(self.write_repository, 'begin_graph_build'):
            attempt_id = self.write_repository.begin_graph_build(self.sparse_k, source_revision)
            claimed = attempt_id is not None
        if not claimed:
            return GraphBuildResult(0, str(source_revision), state='building', reason='warm graph build is running')
        try:
            _metadata, records = self.read_repository.candidate_snapshot()
            retained = tuple(
                record for record in records
                if _is_graph_source_track(record) and record.run is not None and record.run.status == 'completed'
            )
            features = tuple(_features(record) for record in retained)
            positioned = tuple(record for record in retained if _axis_node(record, _map_track(record), '')[0] is not None)
            positioned_features = tuple(_features(record) for record in positioned)
            edges = tuple(_bounded_edges(features, self.sparse_k))
            positioned_edges = tuple(_bounded_edges(positioned_features, self.sparse_k))
            fingerprint = _source_fingerprint(retained)
            self.write_repository.replace_graph_snapshot(
                edges, self.sparse_k, fingerprint, positioned_edges,
                source_revision=source_revision, attempt_id=attempt_id,
            )
            return GraphBuildResult(len(edges), fingerprint)
        except KeyboardInterrupt:
            if attempt_id is not None and hasattr(self.write_repository, 'finish_graph_build_attempt'):
                self.write_repository.finish_graph_build_attempt(attempt_id, 'interrupted', 'explicit graph build interrupted')
            raise
        except Exception as error:
            if attempt_id is not None and hasattr(self.write_repository, 'finish_graph_build_attempt'):
                self.write_repository.finish_graph_build_attempt(attempt_id, 'failed', str(error))
            raise


def _is_graph_source_track(record) -> bool:
    if not is_active_library_track(record):
        return False
    available_locations = getattr(record, 'available_locations', None)
    if available_locations is not None:
        return int(available_locations) > 0
    locations = getattr(record, 'locations', None)
    if locations is not None:
        return bool(locations)
    return True


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
        raw_locations = getattr(record, 'source_locations', ()) or getattr(record, 'locations', ())
        locations = tuple(sorted(str(path) for path in raw_locations))
        display_label = str(getattr(record, 'display_label', ''))
        evidence.append({
            'track_id': record.track_id,
            'run_id': record.run.run_id,
            'available_locations': int(getattr(record, 'available_locations', len(locations))),
            'locations': locations,
            'display_label': display_label,
            'overrides': tuple(
                sorted(
                    (field, value) for field, value in getattr(record, 'overrides', ())
                    if field in GRAPH_SOURCE_OVERRIDE_FIELDS
                )
            ),
            'stages': stages,
        })
    payload = json.dumps(evidence, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()
