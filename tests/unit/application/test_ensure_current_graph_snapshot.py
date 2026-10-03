import unittest
from unittest.mock import Mock

from music_analyzer.application.use_cases.build_graph import EnsureCurrentGraphSnapshot, GraphBuildResult


class EnsureCurrentGraphSnapshotTests(unittest.TestCase):
    def test_noops_when_current_snapshot_matches_source_and_policy(self):
        writer = Mock()
        writer.source_revision.return_value = 'rev-current'
        writer.current_graph_snapshot.return_value = {'state': 'ready', 'build_id': 'build-1'}
        builder = Mock()

        result = EnsureCurrentGraphSnapshot(Mock(), writer, builder_factory=lambda *_: builder).execute()

        self.assertFalse(result.built)
        self.assertEqual(result.state, 'ready')
        builder.execute.assert_not_called()
        writer.current_graph_snapshot.assert_called_once_with(10, 'rev-current')

    def test_builds_once_for_missing_or_stale_snapshot_after_all_jobs(self):
        writer = Mock()
        writer.source_revision.return_value = 'rev-after-batch'
        writer.current_graph_snapshot.return_value = {'state': 'stale'}
        builder = Mock()
        builder.execute.return_value = GraphBuildResult(3, 'fingerprint')

        result = EnsureCurrentGraphSnapshot(Mock(), writer, builder_factory=lambda *_: builder).execute()

        self.assertTrue(result.built)
        self.assertEqual(result.state, 'built')
        self.assertEqual(result.edge_count, 3)
        builder.execute.assert_called_once_with()

    def test_existing_current_building_attempt_does_not_start_second_build(self):
        writer = Mock()
        writer.source_revision.return_value = 'rev-current'
        writer.current_graph_snapshot.return_value = {'state': 'building', 'reason': 'explicit graph build is running'}
        builder = Mock()

        result = EnsureCurrentGraphSnapshot(Mock(), writer, builder_factory=lambda *_: builder).execute()

        self.assertFalse(result.built)
        self.assertEqual(result.state, 'building')
        self.assertIn('running', result.reason)
        builder.execute.assert_not_called()

    def test_failed_or_interrupted_attempt_is_retryable(self):
        for state in ('failed', 'interrupted'):
            with self.subTest(state=state):
                writer = Mock()
                writer.source_revision.return_value = 'rev-current'
                writer.current_graph_snapshot.return_value = {'state': state}
                builder = Mock()
                builder.execute.return_value = GraphBuildResult(1, 'fingerprint')

                result = EnsureCurrentGraphSnapshot(Mock(), writer, builder_factory=lambda *_: builder).execute()

                self.assertTrue(result.built)
                self.assertEqual(result.state, 'built')
                builder.execute.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
