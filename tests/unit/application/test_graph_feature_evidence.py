import unittest

from music_analyzer.application.dto.analysis import StageResult
from music_analyzer.application.use_cases.graph_feature_evidence import build_graph_feature_evidence
from music_analyzer.domain.analysis import ScoreSummary


class GraphFeatureEvidenceTests(unittest.TestCase):
    def test_builds_compact_deterministic_evidence_for_completed_graph_stages(self):
        stages = (
            StageResult('bpm', (('algorithm', 'b'),), 'tempo uncertainty', (('bpm', 120.0),)),
            StageResult('key', (('algorithm', 'k'),), '', (('key', '8A'),)),
            StageResult('genres', (('algorithm', 'g'),), '', (('genre', 'house'), ('genre', 'deep house'))),
            StageResult('mood', (('algorithm', 'm'),), '', summary=ScoreSummary(('happy', 'dark'), (0.8, 0.1), (0.7, 0.0), (0.9, 0.2), 1.0)),
            StageResult('energy', (('algorithm', 'e'),), '', summary=ScoreSummary(('energy',), (0.6,), (0.5,), (0.7,), 1.0)),
        )

        evidence = build_graph_feature_evidence('track-1', 'run-1', stages)
        same = build_graph_feature_evidence('track-1', 'run-1', reversed(stages))

        self.assertIsNotNone(evidence)
        self.assertEqual(evidence, same)
        self.assertEqual(evidence.payload['feature_contract_version'], 'graph-feature-evidence-v1')
        self.assertEqual(evidence.payload['features']['bpm']['values'], (('bpm', 120.0),))
        self.assertEqual(evidence.payload['features']['mood']['summary_values'], (('happy', 0.8), ('dark', 0.1)))
        self.assertRegex(evidence.fingerprint, r'^[0-9a-f]{64}$')

    def test_summary_uncertainty_changes_persisted_payload_and_fingerprint(self):
        base_stages = (
            StageResult('bpm', (('algorithm', 'b'),), '', (('bpm', 120.0),)),
            StageResult('key', (('algorithm', 'k'),), '', (('key', '8A'),)),
            StageResult('genres', (('algorithm', 'g'),), '', (('genre', 'house'),)),
            StageResult('mood', (('algorithm', 'm'),), '', summary=ScoreSummary(('happy',), (0.8,), (0.7,), (0.9,), 1.0, uncertainty='low spread')),
            StageResult('energy', (('algorithm', 'e'),), '', summary=ScoreSummary(('energy',), (0.6,), (0.5,), (0.7,), 1.0)),
        )
        changed_stages = base_stages[:3] + (
            StageResult('mood', (('algorithm', 'm'),), '', summary=ScoreSummary(('happy',), (0.8,), (0.7,), (0.9,), 1.0, uncertainty='high spread')),
            base_stages[4],
        )

        base = build_graph_feature_evidence('track-1', 'run-1', base_stages)
        changed = build_graph_feature_evidence('track-1', 'run-1', changed_stages)

        self.assertEqual(base.payload['features']['mood']['summary']['uncertainty'], 'low spread')
        self.assertEqual(changed.payload['features']['mood']['summary']['uncertainty'], 'high spread')
        self.assertNotEqual(base.payload_json(), changed.payload_json())
        self.assertNotEqual(base.fingerprint, changed.fingerprint)

    def test_returns_none_until_all_graph_relevant_stages_are_available(self):
        stages = (StageResult('bpm', (), '', (('bpm', 120.0),)),)

        self.assertIsNone(build_graph_feature_evidence('track-1', 'run-1', stages))


import hashlib
import json

from music_analyzer.application.use_cases.graph_feature_evidence import validate_graph_feature_evidence_payload


def _canonical_json(payload):
    return json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def _fingerprint(payload):
    return hashlib.sha256(_canonical_json(payload).encode('utf-8')).hexdigest()


def _producer_key_evidence_payload(key_values=(('key', '8A'), ('scale', 'minor'), ('strength', 0.731), ('coverage', 1.0))):
    stages = (
        StageResult('bpm', (('algorithm', 'test-bpm'),), 'tempo uncertainty', (('bpm', 120.0),)),
        StageResult('key', (('algorithm', 'test-key'),), 'producer key uncertainty', key_values),
        StageResult('genres', (('algorithm', 'test-genre'),), '', (('genre', 'house'),)),
        StageResult('mood', (('algorithm', 'test-mood'),), '', summary=ScoreSummary(('happy',), (0.8,), (0.7,), (0.9,), 1.0)),
        StageResult('energy', (('algorithm', 'test-energy'),), '', summary=ScoreSummary(('energy',), (0.6,), (0.5,), (0.7,), 1.0)),
    )
    evidence = build_graph_feature_evidence('track-1', 'run-1', stages)
    assert evidence is not None
    return evidence.payload


class GraphFeatureEvidenceKeyContractRedTests(unittest.TestCase):
    def test_validator_accepts_current_producer_generated_mixed_key_stage_values(self):
        payload = _producer_key_evidence_payload()

        validate_graph_feature_evidence_payload('track-1', 'run-1', _fingerprint(payload), payload)

    def test_validator_preserves_legacy_minimal_key_only_fixture(self):
        payload = _producer_key_evidence_payload((('key', '8A'),))

        validate_graph_feature_evidence_payload('track-1', 'run-1', _fingerprint(payload), payload)

    def test_validator_rejects_unknown_key_label_even_with_recomputed_fingerprint(self):
        payload = _producer_key_evidence_payload((('key', '8A'), ('mode', 'dorian')))

        with self.assertRaises(ValueError):
            validate_graph_feature_evidence_payload('track-1', 'run-1', _fingerprint(payload), payload)

    def test_validator_rejects_duplicate_key_labels_even_with_recomputed_fingerprint(self):
        payload = _producer_key_evidence_payload((('key', '8A'), ('key', '9A')))

        with self.assertRaises(ValueError):
            validate_graph_feature_evidence_payload('track-1', 'run-1', _fingerprint(payload), payload)

    def test_validator_rejects_wrong_type_boolean_and_nonfinite_key_values(self):
        invalid_values = (
            (('key', '8A'), ('scale', 'minor'), ('strength', '0.7'), ('coverage', 1.0)),
            (('key', '8A'), ('scale', True), ('strength', 0.7), ('coverage', 1.0)),
            (('key', '8A'), ('scale', 'minor'), ('strength', True), ('coverage', 1.0)),
            (('key', ''), ('scale', 'minor'), ('strength', 0.7), ('coverage', 1.0)),
        )
        for values in invalid_values:
            with self.subTest(values=values):
                payload = _producer_key_evidence_payload(values)
                with self.assertRaises((ValueError, OverflowError)):
                    validate_graph_feature_evidence_payload('track-1', 'run-1', _fingerprint(payload), payload)

if __name__ == '__main__':
    unittest.main()
