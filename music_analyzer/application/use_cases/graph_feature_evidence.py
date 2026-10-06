"""Pure graph feature evidence mapping for persisted warm graph inputs."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Iterable

from music_analyzer.application.dto.analysis import StageResult
from music_analyzer.domain.analysis import finite

GRAPH_FEATURE_CONTRACT_VERSION = 'graph-feature-evidence-v1'
GRAPH_RELEVANT_STAGES = ('bpm', 'key', 'genres', 'mood', 'energy')


@dataclass(frozen=True)
class GraphFeatureEvidence:
    track_id: str
    run_id: str
    fingerprint: str
    payload: dict

    def payload_json(self) -> str:
        return _canonical_json(self.payload)


def build_graph_feature_evidence(track_id: str, run_id: str, stages: Iterable[StageResult]) -> GraphFeatureEvidence | None:
    """Build compact deterministic graph feature evidence from retained stage results.

    Returns ``None`` until all graph-relevant completed-analysis stage results are
    present.  This function is intentionally framework- and storage-agnostic so
    persistence adapters can store its output atomically without leaking SQL
    details into application policy.
    """
    by_stage = {stage.stage: stage for stage in stages if stage.stage in GRAPH_RELEVANT_STAGES}
    if any(name not in by_stage for name in GRAPH_RELEVANT_STAGES):
        return None
    features = {name: _stage_payload(by_stage[name]) for name in GRAPH_RELEVANT_STAGES}
    payload = {
        'feature_contract_version': GRAPH_FEATURE_CONTRACT_VERSION,
        'track_id': str(track_id),
        'run_id': str(run_id),
        'features': features,
    }
    fingerprint = hashlib.sha256(_canonical_json(payload).encode('utf-8')).hexdigest()
    return GraphFeatureEvidence(str(track_id), str(run_id), fingerprint, payload)


def _stage_payload(stage: StageResult) -> dict:
    summary_values = ()
    summary = None
    if stage.summary is not None:
        summary_values = tuple(zip(stage.summary.labels, stage.summary.mean))
        summary = {
            'labels': tuple(stage.summary.labels),
            'mean': tuple(stage.summary.mean),
            'minimum': tuple(stage.summary.minimum),
            'maximum': tuple(stage.summary.maximum),
            'coverage': stage.summary.coverage,
            'provisional': bool(stage.summary.provisional),
            'uncertainty': stage.summary.uncertainty,
        }
    return {
        'values': tuple(stage.values),
        'summary_values': summary_values,
        'summary': summary,
        'provenance': tuple(stage.provenance),
        'uncertainty': stage.uncertainty,
    }


def validate_graph_feature_evidence_payload(track_id: str, run_id: str, fingerprint: str, payload: dict) -> None:
    """Validate the canonical graph feature evidence contract and fingerprint.

    Raises ``ValueError`` when persisted evidence does not match the strict v9
    payload shape produced by ``build_graph_feature_evidence``.  Kept pure so
    storage adapters and read-only consumers can share identical fail-closed
    policy without depending on SQLite details.
    """
    if (not isinstance(fingerprint, str)
            or len(fingerprint) != 64
            or any(ch not in '0123456789abcdef' for ch in fingerprint)):
        raise ValueError('Invalid graph feature evidence fingerprint')
    if not isinstance(payload, dict):
        raise ValueError('Invalid graph feature evidence payload')
    if set(payload) != {'feature_contract_version', 'track_id', 'run_id', 'features'}:
        raise ValueError('Invalid graph feature evidence payload')
    if (payload.get('feature_contract_version') != GRAPH_FEATURE_CONTRACT_VERSION
            or payload.get('track_id') != track_id
            or payload.get('run_id') != run_id):
        raise ValueError('Invalid graph feature evidence identity')
    features = payload.get('features')
    if not isinstance(features, dict) or set(features) != set(GRAPH_RELEVANT_STAGES):
        raise ValueError('Invalid graph feature evidence features')
    _validate_scalar_stage(features['bpm'], _is_finite_number)
    _validate_key_stage(features['key'])
    _validate_genres_stage(features['genres'])
    _validate_summary_stage(features['mood'])
    _validate_summary_stage(features['energy'])
    expected = hashlib.sha256(_canonical_json(payload).encode('utf-8')).hexdigest()
    if fingerprint != expected:
        raise ValueError('Invalid graph feature evidence fingerprint')


def _validate_stage_common(stage_payload: object) -> dict:
    if not isinstance(stage_payload, dict):
        raise ValueError('Invalid graph feature evidence stage')
    if set(stage_payload) != {'values', 'summary_values', 'summary', 'provenance', 'uncertainty'}:
        raise ValueError('Invalid graph feature evidence stage')
    provenance = stage_payload.get('provenance')
    if (not _is_sequence(provenance)
            or any(not _is_pair(item, _is_nonempty_string, _is_string) for item in provenance)):
        raise ValueError('Invalid graph feature evidence provenance')
    if not _is_string(stage_payload.get('uncertainty')):
        raise ValueError('Invalid graph feature evidence uncertainty')
    return stage_payload


def _validate_scalar_stage(stage_payload: object, value_validator) -> None:
    stage = _validate_stage_common(stage_payload)
    if (stage.get('summary') is not None
            or tuple(stage.get('summary_values')) != ()
            or not _is_sequence(stage.get('values'))
            or any(not _is_pair(item, _is_nonempty_string, value_validator) for item in stage.get('values'))):
        raise ValueError('Invalid graph feature evidence scalar stage')


def _validate_key_stage(stage_payload: object) -> None:
    stage = _validate_stage_common(stage_payload)
    values = stage.get('values')
    if (stage.get('summary') is not None
            or tuple(stage.get('summary_values')) != ()
            or not _is_sequence(values)):
        raise ValueError('Invalid graph feature evidence key stage')
    seen = set()
    validators = {
        'key': _is_nonempty_string,
        'scale': _is_nonempty_string,
        'strength': _is_finite_number,
        'coverage': _is_finite_number,
    }
    for item in values:
        if not (_is_sequence(item) and len(item) == 2 and _is_nonempty_string(item[0])):
            raise ValueError('Invalid graph feature evidence key stage')
        label, value = item
        validator = validators.get(label)
        if validator is None or label in seen or not validator(value):
            raise ValueError('Invalid graph feature evidence key stage')
        seen.add(label)


def _validate_genres_stage(stage_payload: object) -> None:
    stage = _validate_stage_common(stage_payload)
    if stage.get('summary') is not None:
        _validate_summary_stage(stage_payload)
        return
    if (tuple(stage.get('summary_values')) != ()
            or not _is_sequence(stage.get('values'))
            or any(not _is_pair(item, _is_nonempty_string, _is_nonempty_string) for item in stage.get('values'))):
        raise ValueError('Invalid graph feature evidence genre stage')


def _validate_summary_stage(stage_payload: object) -> None:
    stage = _validate_stage_common(stage_payload)
    if tuple(stage.get('values')) != ():
        raise ValueError('Invalid graph feature evidence summary stage')
    summary = stage.get('summary')
    if summary is None:
        if tuple(stage.get('summary_values')) != ():
            raise ValueError('Invalid graph feature evidence summary values')
        return
    if not isinstance(summary, dict):
        raise ValueError('Invalid graph feature evidence summary')
    if set(summary) != {'labels', 'mean', 'minimum', 'maximum', 'coverage', 'provisional', 'uncertainty'}:
        raise ValueError('Invalid graph feature evidence summary')
    labels = summary.get('labels')
    mean = summary.get('mean')
    minimum = summary.get('minimum')
    maximum = summary.get('maximum')
    if (not _is_sequence(labels)
            or not labels
            or any(not _is_nonempty_string(label) for label in labels)
            or len(set(labels)) != len(labels)
            or not _is_numeric_sequence(mean, len(labels))
            or not _is_numeric_sequence(minimum, len(labels))
            or not _is_numeric_sequence(maximum, len(labels))
            or not _is_finite_number(summary.get('coverage'))
            or not 0.0 <= float(summary.get('coverage')) <= 1.0
            or not isinstance(summary.get('provisional'), bool)
            or not _is_string(summary.get('uncertainty'))):
        raise ValueError('Invalid graph feature evidence summary')
    if tuple(tuple(item) for item in stage.get('summary_values')) != tuple(zip(labels, mean)):
        raise ValueError('Invalid graph feature evidence summary values')


def _is_sequence(value: object) -> bool:
    return isinstance(value, (list, tuple))


def _is_string(value: object) -> bool:
    return isinstance(value, str)


def _is_nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value)


def _is_finite_number(value: object) -> bool:
    return finite(value)


def _is_numeric_sequence(value: object, length: int) -> bool:
    return _is_sequence(value) and len(value) == length and all(_is_finite_number(item) for item in value)


def _is_pair(value: object, key_validator, value_validator) -> bool:
    return (_is_sequence(value)
            and len(value) == 2
            and key_validator(value[0])
            and value_validator(value[1]))


def _canonical_json(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
