"""Pure, finite diagnostic policy for compact graph evidence.

Adapters own JSON decoding, admission and relational observation. These predicates
classify decoded values without changing the builder or fail-closed FULL reader.
No exception text is part of the diagnostic contract.
"""
from __future__ import annotations

from enum import Enum
import hashlib
import json

from music_analyzer.application.use_cases.graph_feature_evidence import (
    GRAPH_FEATURE_CONTRACT_VERSION, GRAPH_RELEVANT_STAGES,
)
from music_analyzer.domain.analysis import finite


class EvidenceCode(str, Enum):
    ENVELOPE_INVALID = 'evidence_envelope_invalid'
    LINK_INVALID = 'evidence_link_invalid'
    JSON_INVALID = 'evidence_json_invalid'
    CONTRACT_INVALID = 'evidence_contract_invalid'
    FEATURE_INVALID = 'evidence_feature_invalid'
    SUMMARY_INVALID = 'evidence_summary_invalid'
    FINGERPRINT_INVALID = 'evidence_fingerprint_invalid'
    DELIVERY_INVALID = 'evidence_delivery_invalid'
    PAYLOAD_OVERSIZED = 'evidence_payload_oversized'


def _hex_digest(value: object) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(char in '0123456789abcdef' for char in value))


def classify_envelope(track_id: object, run_id: object, is_current: object) -> tuple[EvidenceCode, ...]:
    """One OR-ed envelope occurrence; numeric membership is intentionally loose."""
    valid = (isinstance(track_id, str) and track_id.startswith('sha256:')
             and _hex_digest(track_id[7:]) and _nonempty(run_id)
             and is_current in (0, 1))
    return () if valid else (EvidenceCode.ENVELOPE_INVALID,)


def classify_links(*, run_completed: bool, pair_exists: bool,
                   current: bool, latest_matches: bool) -> tuple[EvidenceCode, ...]:
    """Relational facts are supplied by the adapter's pinned snapshot."""
    valid = run_completed and pair_exists and (not current or latest_matches)
    return () if valid else (EvidenceCode.LINK_INVALID,)


def classify_fingerprint_syntax(fingerprint: object) -> tuple[EvidenceCode, ...]:
    """Independent stored syntax, even when payload admission or parsing fails."""
    return () if _hex_digest(fingerprint) else (EvidenceCode.FINGERPRINT_INVALID,)


def classify_payload(track_id: object, run_id: object, fingerprint: object,
                     payload: object) -> tuple[EvidenceCode, ...]:
    """Classify decoded content, preserving independent digest syntax findings.

    JSON/codec failures belong to the adapter. Contract failure suppresses child
    predicates; common stage failure suppresses that stage's summary predicate.
    Canonical hashing runs only after all content predicates succeed. Resource
    failures (notably MemoryError) deliberately propagate to the operational layer.
    """
    codes: set[EvidenceCode] = set()
    digest_valid = _hex_digest(fingerprint)
    if not digest_valid:
        codes.add(EvidenceCode.FINGERPRINT_INVALID)
    if (not isinstance(payload, dict)
            or set(payload) != {'feature_contract_version', 'track_id', 'run_id', 'features'}
            or payload['feature_contract_version'] != GRAPH_FEATURE_CONTRACT_VERSION
            or payload['track_id'] != track_id or payload['run_id'] != run_id):
        codes.add(EvidenceCode.CONTRACT_INVALID)
        return _ordered(codes)
    features = payload['features']
    if not isinstance(features, dict) or set(features) != set(GRAPH_RELEVANT_STAGES):
        codes.add(EvidenceCode.FEATURE_INVALID)
        return _ordered(codes)
    for name in GRAPH_RELEVANT_STAGES:
        stage = features[name]
        if not _common(stage):
            codes.add(EvidenceCode.FEATURE_INVALID)
        elif name == 'bpm':
            if not _scalar(stage, finite):
                codes.add(EvidenceCode.FEATURE_INVALID)
        elif name == 'key':
            if not _key(stage):
                codes.add(EvidenceCode.FEATURE_INVALID)
        elif name == 'genres' and stage['summary'] is None:
            if not _scalar(stage, _nonempty):
                codes.add(EvidenceCode.FEATURE_INVALID)
        elif not _summary(stage):
            codes.add(EvidenceCode.SUMMARY_INVALID)
    if not codes.intersection((EvidenceCode.FEATURE_INVALID, EvidenceCode.SUMMARY_INVALID)) and digest_valid:
        try:
            canonical = json.dumps(payload, sort_keys=True, separators=(',', ':'),
                                   ensure_ascii=False, allow_nan=False).encode('utf-8')
            if hashlib.sha256(canonical).hexdigest() != fingerprint:
                codes.add(EvidenceCode.FINGERPRINT_INVALID)
        except (UnicodeError, RecursionError):
            codes.add(EvidenceCode.FINGERPRINT_INVALID)
    return _ordered(codes)


def _ordered(codes: set[EvidenceCode]) -> tuple[EvidenceCode, ...]:
    return tuple(code for code in EvidenceCode if code in codes)


def _sequence(value: object) -> bool:
    return isinstance(value, (list, tuple))


def _empty(value: object) -> bool:
    return _sequence(value) and len(value) == 0


def _nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value)


def _pair(value: object, validator) -> bool:
    return (_sequence(value) and len(value) == 2
            and _nonempty(value[0]) and validator(value[1]))


def _common(stage: object) -> bool:
    return (isinstance(stage, dict)
            and set(stage) == {'values', 'summary_values', 'summary', 'provenance', 'uncertainty'}
            and _sequence(stage['provenance'])
            and all(_pair(item, lambda value: isinstance(value, str)) for item in stage['provenance'])
            and isinstance(stage['uncertainty'], str))


def _scalar(stage: dict, validator) -> bool:
    return (stage['summary'] is None and _empty(stage['summary_values'])
            and _sequence(stage['values'])
            and all(_pair(item, validator) for item in stage['values']))


def _key(stage: dict) -> bool:
    if stage['summary'] is not None or not _empty(stage['summary_values']) or not _sequence(stage['values']):
        return False
    validators = {'key': _nonempty, 'scale': _nonempty, 'strength': finite, 'coverage': finite}
    seen = set()
    for item in stage['values']:
        if not _sequence(item) or len(item) != 2 or not _nonempty(item[0]):
            return False
        label, value = item
        if label not in validators or label in seen or not validators[label](value):
            return False
        seen.add(label)
    return True


def _summary(stage: dict) -> bool:
    if not _empty(stage['values']):
        return False
    summary = stage['summary']
    if summary is None:
        return _empty(stage['summary_values'])
    if (not isinstance(summary, dict)
            or set(summary) != {'labels', 'mean', 'minimum', 'maximum', 'coverage', 'provisional', 'uncertainty'}):
        return False
    labels = summary['labels']
    if (not _sequence(labels) or not labels or not all(_nonempty(label) for label in labels)
            or len(set(labels)) != len(labels)):
        return False
    for name in ('mean', 'minimum', 'maximum'):
        vector = summary[name]
        if not _sequence(vector) or len(vector) != len(labels) or not all(finite(value) for value in vector):
            return False
    if (not finite(summary['coverage']) or not 0 <= summary['coverage'] <= 1
            or type(summary['provisional']) is not bool or not isinstance(summary['uncertainty'], str)):
        return False
    values = stage['summary_values']
    # This derived field follows established equality semantics (True == 1,
    # False == 0); finite/nonboolean policy belongs to the vectors above.
    return (_sequence(values)
            and all(_sequence(item) and len(item) == 2 for item in values)
            and tuple(tuple(item) for item in values) == tuple(zip(labels, summary['mean'])))
