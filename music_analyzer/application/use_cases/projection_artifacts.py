"""Application orchestration for prepared Phase3 projection artifacts."""
from dataclasses import dataclass
import hashlib
import json
from math import isfinite
import platform

from music_analyzer.application.ports.explorer import ExplorerRepository
from music_analyzer.application.ports.projection_artifacts import ProjectionArtifactStore
from music_analyzer.application.use_cases.candidates import _features
from music_analyzer.domain.projection import (
    NEIGHBOUR_POLICY_VERSION,
    PROJECTION_POLICY_VERSION,
    ProjectionParameters,
    fit_projection_transform,
    project_tracks,
)

ARTIFACT_VERSION = 'journey-projection-artifact-v1'
FINGERPRINT_VERSION = 'projection-fingerprint-v1'


class ProjectionArtifactError(Exception):
    """Expected actionable projection artifact failure."""


@dataclass(frozen=True)
class ProjectionArtifactResult:
    artifact: dict[str, object]


class PrepareProjectionArtifact:
    def __init__(self, repository: ExplorerRepository, store: ProjectionArtifactStore, k: int = 10):
        self.repository = repository
        self.store = store
        self.k = k

    def execute(self):
        artifact = _build_artifact(self.repository, ProjectionParameters(self.k, False), None)
        self.store.replace(artifact)
        return ProjectionArtifactResult(artifact)


class LoadProjectionArtifact:
    def __init__(self, store: ProjectionArtifactStore):
        self.store = store

    def execute(self):
        artifact = self.store.load()
        _validate_artifact(artifact)
        return artifact


class RefreshProjectionArtifact:
    def __init__(self, repository: ExplorerRepository, store: ProjectionArtifactStore, k: int = 10):
        self.repository = repository
        self.store = store
        self.k = k

    def execute(self, explicit_relayout: bool = False):
        existing = self.store.load()
        _validate_artifact(existing)
        transform = None if explicit_relayout else existing.get('transform_object')
        artifact = _build_artifact(self.repository, ProjectionParameters(self.k, explicit_relayout), transform)
        self.store.replace(artifact)
        return ProjectionArtifactResult(artifact)


def _build_artifact(repository, parameters, existing_transform):
    metadata, records = repository.candidate_snapshot()
    features = tuple(_features(record) for record in records)
    transform = fit_projection_transform(features, parameters) if existing_transform is None else existing_transform
    projection = project_tracks(features, transform)
    fingerprint = _fingerprint(metadata, records, parameters)
    artifact = {
        'artifact_version': ARTIFACT_VERSION,
        'fingerprint_version': FINGERPRINT_VERSION,
        'fingerprint': fingerprint,
        'metadata': {'application_id': metadata.get('application_id'), 'schema_version': metadata.get('schema_version'), 'read_policy': metadata.get('read_policy')},
        'policy_versions': {'projection_policy_version': PROJECTION_POLICY_VERSION, 'neighbour_policy_version': NEIGHBOUR_POLICY_VERSION},
        'runtime': {'python': platform.python_version(), 'implementation': platform.python_implementation()},
        'transform': _transform_mapping(projection.transform, parameters),
        'transform_object': projection.transform,
        'tracks': tuple({'track_id': p.track_id, 'x': p.x, 'y': p.y, 'layout_state': p.layout_state, 'missing_groups': p.missing_groups, 'missing_reasons': p.missing_reasons} for p in projection.points),
        'edges': tuple({'a': e.a, 'b': e.b, 'distance': e.distance, 'supported_group_count': e.supported_group_count} for e in projection.edges),
        'resource_limits': {'k': parameters.k, 'track_count': len(projection.points), 'edge_count': len(projection.edges)},
    }
    _validate_artifact(artifact)
    return artifact


def _fingerprint(metadata, records, parameters):
    safe = {
        'version': FINGERPRINT_VERSION,
        'metadata': {'application_id': metadata.get('application_id'), 'schema_version': metadata.get('schema_version')},
        'parameters': {'k': parameters.k, 'explicit_relayout': parameters.explicit_relayout},
        'tracks': [],
    }
    for record in sorted(records, key=lambda r: r.track_id):
        stages = []
        if record.run:
            for stage in sorted(record.run.stages, key=lambda s: s.stage):
                stages.append({'stage': stage.stage, 'values': stage.values, 'summary': ((stage.summary.labels, stage.summary.mean, stage.summary.coverage) if stage.summary else None), 'provenance': stage.provenance, 'uncertainty': stage.uncertainty})
        safe['tracks'].append({'track_id': record.track_id, 'sha256': record.sha256, 'size': record.size, 'display_label': record.display_label, 'available_locations': record.available_locations, 'run_id': record.run.run_id if record.run else None, 'run_status': record.run.status if record.run else None, 'stages': stages, 'overrides': tuple(sorted(record.overrides))})
    encoded = json.dumps(safe, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest()


def _transform_mapping(transform, parameters):
    return {
        'policy_version': transform.policy_version,
        'parameters': {'k': parameters.k, 'explicit_relayout': parameters.explicit_relayout},
        'anchors': {name: {'low_track_id': anchor.low_track_id, 'high_track_id': anchor.high_track_id, 'low_value': anchor.low_value, 'high_value': anchor.high_value, 'metadata': anchor.metadata} for name, anchor in sorted(transform.anchors.items())},
        'center_x': transform.center_x,
        'center_y': transform.center_y,
        'range_x': transform.range_x,
        'range_y': transform.range_y,
        'degenerate_axes': transform.degenerate_axes,
    }


def _validate_artifact(artifact):
    if not isinstance(artifact, dict) or artifact.get('artifact_version') != ARTIFACT_VERSION:
        raise ProjectionArtifactError('unsupported_version')
    tracks = artifact.get('tracks', ())
    edges = artifact.get('edges', ())
    if len(edges) > max(0, len(tracks) * 100):
        raise ProjectionArtifactError('resource_limit_exceeded')
    ids = set()
    for point in tracks:
        if point['track_id'] in ids:
            raise ProjectionArtifactError('duplicate track id')
        ids.add(point['track_id'])
        for key in ('x', 'y'):
            value = point.get(key)
            if value is not None and (not isinstance(value, (int, float)) or not isfinite(float(value))):
                raise ProjectionArtifactError('coordinate shape error')
    degree = {track_id: 0 for track_id in ids}
    k = int(artifact.get('resource_limits', {}).get('k', 10))
    for edge in edges:
        if edge.get('a') not in ids or edge.get('b') not in ids:
            raise ProjectionArtifactError('edge references unknown track')
        distance = edge.get('distance')
        if not isinstance(distance, (int, float)) or not isfinite(float(distance)):
            raise ProjectionArtifactError('non-finite distance')
        degree[edge['a']] += 1; degree[edge['b']] += 1
    if degree and max(degree.values()) > k:
        raise ProjectionArtifactError('endpoint degree exceeds k')
