import unittest
from unittest.mock import Mock

from music_analyzer.application.use_cases.build_graph import BuildGraphSnapshot, EnsureCurrentGraphSnapshot


class GraphBuildConcurrencyTests(unittest.TestCase):
    def test_builder_noops_without_expensive_snapshot_when_atomic_claim_is_already_owned(self):
        reader = Mock()
        writer = Mock()
        writer.source_revision.return_value = 'rev-current'
        writer.begin_graph_build.return_value = None

        result = BuildGraphSnapshot(reader, writer).execute()

        self.assertEqual(result.state, 'building')
        reader.candidate_snapshot.assert_not_called()
        writer.replace_graph_snapshot.assert_not_called()

    def test_ensure_reports_building_when_racy_preflight_loses_atomic_claim(self):
        writer = Mock()
        writer.source_revision.return_value = 'rev-current'
        writer.current_graph_snapshot.return_value = {'state': 'build_needed'}
        builder = Mock()
        builder.execute.return_value.state = 'building'
        builder.execute.return_value.reason = 'warm graph build is running'

        result = EnsureCurrentGraphSnapshot(Mock(), writer, builder_factory=lambda *_: builder).execute()

        self.assertFalse(result.built)
        self.assertEqual(result.state, 'building')
        builder.execute.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
