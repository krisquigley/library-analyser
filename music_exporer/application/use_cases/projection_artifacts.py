"""Application orchestration for prepared Phase3 projection artifacts."""
from dataclasses import dataclass
import hashlib
import json
from math import isfinite
import platform

from music_exporer.application.ports.explorer import ExplorerRepository
from music_exporer.application.ports.projection_artifacts import ProjectionArtifactStore
from music_exporer.application.use_cases.candidates import _features
from music_exporer.domain.projection import (
    DISTANCE_POLICY_VERSION,
    NEIGHBOUR_POLICY_VERSION,
    PROJECTION_POLICY_VERSION,
    ProjectionAnchor,
    ProjectionParameters,
    ProjectionTransform,
    fit_projection_transform,
    project_tracks,
)

ARTIFACT_VERSION = 'journey-projection-artifact-v1'
FINGERPRINT_VERSION = 'projection-fingerprint-v1'
FEATURE_CONTRACT_VERSION = 'projection-features-v1'
REFRESH_POLICY_VERSION = 'fixed-transform-refresh-v1'


def _contract_versions():
    return {
        'artifact_version': ARTIFACT_VERSION,
        'projection_policy_version': PROJECTION_POLICY_VERSION,
        'projection_feature_contract_version': FEATURE_CONTRACT_VERSION,
        'projection_fingerprint_version': FINGERPRINT_VERSION,
        'projection_refresh_policy_version': REFRESH_POLICY_VERSION,
        '3d_coordinate_policy': 'deterministic-missing-evidence-z-v1',
        'neighbour_policy_version': NEIGHBOUR_POLICY_VERSION,
        'distance_policy_version': DISTANCE_POLICY_VERSION,
        'transform_recipe_version': PROJECTION_POLICY_VERSION,
    }


class ProjectionArtifactError(Exception):
    """Expected actionable projection artifact failure."""


@dataclass(frozen=True)
class ProjectionArtifactResult:
    artifact: dict[str, object]
    committed: bool = True
    warning: str | None = None




@dataclass(frozen=True)
class LiveProjectionResult:
    policy_versions: dict[str, str]
    tracks: tuple[dict[str, object], ...]
    edges: tuple[dict[str, object], ...]


class BuildLiveProjection:
    def __init__(self, repository: ExplorerRepository, k: int = 10):
        self.repository = repository
        self.k = k

    def execute(self):
        artifact = _build_artifact(self.repository, ProjectionParameters(self.k, False), None)
        return LiveProjectionResult(artifact['policy_versions'], artifact['tracks'], artifact['edges'])


class PrepareProjectionArtifact:
    def __init__(self, repository: ExplorerRepository, store: ProjectionArtifactStore, k: int = 10):
        self.repository = repository
        self.store = store
        self.k = k

    def execute(self):
        artifact = _build_artifact(self.repository, ProjectionParameters(self.k, False), None)
        outcome = self.store.replace(artifact)
        return _artifact_result(artifact, outcome)


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
        transform = None if explicit_relayout else _transform_from_mapping(existing.get('transform'))
        artifact = _build_artifact(self.repository, ProjectionParameters(self.k, explicit_relayout), transform)
        outcome = self.store.replace(artifact)
        return _artifact_result(artifact, outcome)


def _artifact_result(artifact, outcome):
    if outcome is None:
        return ProjectionArtifactResult(artifact)
    return ProjectionArtifactResult(artifact, bool(outcome.committed), outcome.warning)


def _build_artifact(repository, parameters, existing_transform):
    metadata, records = repository.candidate_snapshot()
    features = tuple(_features(record) for record in records)
    transform = fit_projection_transform(features, parameters) if existing_transform is None else _transform_with_parameters(existing_transform, parameters)
    projection = project_tracks(features, transform)
    fingerprint = _fingerprint(metadata, records, parameters)
    artifact = {
        'artifact_version': ARTIFACT_VERSION,
        'fingerprint_version': FINGERPRINT_VERSION,
        'fingerprint': fingerprint,
        'metadata': {'application_id': metadata.get('application_id'), 'schema_version': metadata.get('schema_version'), 'read_policy': metadata.get('read_policy')},
        'policy_versions': _contract_versions(),
        'runtime': {'python': platform.python_version(), 'implementation': platform.python_implementation()},
        'transform': _transform_mapping(projection.transform, parameters),
        'transform_object': projection.transform,
        'tracks': tuple({'track_id': p.track_id, 'x': p.x, 'y': p.y, 'z': _z_coordinate(p), 'layout_state': p.layout_state, 'missing_groups': p.missing_groups, 'missing_reasons': p.missing_reasons} for p in projection.points),
        'edges': tuple({'a': e.a, 'b': e.b, 'distance': e.distance, 'supported_group_count': e.supported_group_count} for e in projection.edges),
        'resource_limits': {'k': parameters.k, 'track_count': len(projection.points), 'edge_count': len(projection.edges)},
    }
    _validate_artifact(artifact)
    return artifact


def _z_coordinate(point):
    if point.x is None and point.y is None:
        return None
    missing_count = len(point.missing_groups or ())
    # Deterministic display-only third axis: tracks with fewer missing projection
    # groups sit forward; this is not calibrated audio-feature depth.
    return max(-1.0, min(1.0, 1.0 - 0.4 * missing_count))


def _fingerprint(metadata, records, parameters):
    safe = {
        'version': FINGERPRINT_VERSION,
        'contract_versions': _contract_versions(),
        'metadata': {'application_id': metadata.get('application_id'), 'schema_version': metadata.get('schema_version'), 'read_policy': metadata.get('read_policy')},
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


def _transform_with_parameters(transform, parameters):
    return ProjectionTransform(
        transform.policy_version,
        parameters,
        transform.anchors,
        transform.center_x,
        transform.center_y,
        transform.range_x,
        transform.range_y,
        transform.degenerate_axes,
    )


def _transform_mapping(transform, parameters):
    return {
        'policy_version': transform.policy_version,
        'parameters': {'k': parameters.k, 'explicit_relayout': parameters.explicit_relayout},
        'anchors': {name: {'low_track_id': anchor.low_track_id, 'high_track_id': anchor.high_track_id, 'low_value': anchor.low_value, 'high_value': anchor.high_value, 'metadata': anchor.metadata, 'low_feature': anchor.low_feature, 'high_feature': anchor.high_feature} for name, anchor in sorted(transform.anchors.items())},
        'center_x': transform.center_x,
        'center_y': transform.center_y,
        'range_x': transform.range_x,
        'range_y': transform.range_y,
        'degenerate_axes': transform.degenerate_axes,
    }


def _transform_from_mapping(mapping):
    if not isinstance(mapping, dict):
        raise ProjectionArtifactError('missing transform')
    params = mapping.get('parameters', {})
    anchors = {}
    for name, anchor in mapping.get('anchors', {}).items():
        anchors[name] = ProjectionAnchor(
            anchor['low_track_id'], anchor['high_track_id'], float(anchor['low_value']), float(anchor['high_value']),
            _tuple_pairs(anchor.get('metadata', ())), _tuple_pairs(anchor.get('low_feature', ())), _tuple_pairs(anchor.get('high_feature', ()))
        )
    return ProjectionTransform(
        mapping.get('policy_version'), ProjectionParameters(int(params.get('k', 10)), bool(params.get('explicit_relayout', False))), anchors,
        float(mapping.get('center_x', 0.0)), float(mapping.get('center_y', 0.0)), float(mapping.get('range_x', 0.0)), float(mapping.get('range_y', 0.0)),
        tuple(mapping.get('degenerate_axes', ())),
    )


def _tuple_pairs(value):
    return tuple((item[0], item[1]) for item in value)


def _validate_artifact(artifact):
    if not isinstance(artifact, dict) or artifact.get('artifact_version') != ARTIFACT_VERSION:
        raise ProjectionArtifactError('unsupported_version')
    if artifact.get('fingerprint_version') != FINGERPRINT_VERSION:
        raise ProjectionArtifactError('stale unsupported fingerprint_version')
    versions = artifact.get('policy_versions')
    if not isinstance(versions, dict):
        raise ProjectionArtifactError('stale unsupported policy_versions')
    for key, expected in _contract_versions().items():
        if versions.get(key) != expected:
            raise ProjectionArtifactError(f'stale unsupported policy_versions.{key}')
    transform = artifact.get('transform')
    if not isinstance(transform, dict) or transform.get('policy_version') != PROJECTION_POLICY_VERSION:
        raise ProjectionArtifactError('unsupported transform')
    tracks = artifact.get('tracks', ())
    edges = artifact.get('edges', ())
    if len(edges) > max(0, len(tracks) * 100):
        raise ProjectionArtifactError('resource_limit_exceeded')
    ids = set()
    for point in tracks:
        if point['track_id'] in ids:
            raise ProjectionArtifactError('duplicate track id')
        ids.add(point['track_id'])
        for key in ('x', 'y', 'z'):
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
