"""Pure graph feature evidence mapping for persisted warm graph inputs."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Iterable

from music_analyzer.application.dto.analysis import StageResult

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
        }
    return {
        'values': tuple(stage.values),
        'summary_values': summary_values,
        'summary': summary,
        'provenance': tuple(stage.provenance),
        'uncertainty': stage.uncertainty,
    }


def _canonical_json(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
