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

    def test_returns_none_until_all_graph_relevant_stages_are_available(self):
        stages = (StageResult('bpm', (), '', (('bpm', 120.0),)),)

        self.assertIsNone(build_graph_feature_evidence('track-1', 'run-1', stages))


if __name__ == '__main__':
    unittest.main()
