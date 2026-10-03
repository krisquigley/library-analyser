import contextlib
import io
import json
import unittest
from unittest.mock import Mock, patch

from music_analyzer.application.dto.analysis import AnalysisReport, StageResult
from music_analyzer.application.dto.catalogue import TrackMetadata
from music_analyzer.application.dto.settings import Settings
from music_analyzer.application.ports.batch import BatchJob
from music_analyzer.frameworks.cli.main import main


class AnalyzeAutoGraphBuildCLITests(unittest.TestCase):
    def test_completed_batch_invocation_builds_exact_graph_once_after_batch(self):
        events = []
        jobs = (
            BatchJob('track-a', 'recipe-v1', 'completed', attempts=1, run_id='run-a'),
            BatchJob('track-b', 'recipe-v1', 'completed', attempts=1, run_id='run-b'),
        )
        queue = Mock()
        queue.ineligible_tracks.return_value = {}
        batch = Mock()
        batch.execute.side_effect = lambda *args, **kwargs: events.append('batch-finished') or jobs
        graph = Mock()
        graph.execute.side_effect = lambda: events.append('graph-built')

        with patch('music_analyzer.frameworks.cli.main.load_settings', return_value=Settings('', False, '/tmp/issue44.sqlite', '/tmp/models')), \
             patch('music_analyzer.frameworks.cli.main.SQLiteBatchQueue', return_value=queue), \
             patch('music_analyzer.frameworks.cli.main.build_batch', return_value=(batch, lambda: 'recipe-v1')), \
             patch('music_analyzer.frameworks.cli.main.BuildGraphSnapshot', return_value=graph) as build_graph, \
             patch('music_analyzer.frameworks.cli.main.ReadOnlyExplorerSQLiteRepository') as read_repo, \
             patch('music_analyzer.frameworks.cli.main.SQLiteAnalysisRepository') as write_repo:
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = main(['analyze', '--limit', '2', '--database', '/tmp/issue44.sqlite', '--json'])

        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout.getvalue())['counts']['completed'], 2)
        self.assertEqual(events, ['batch-finished', 'graph-built'])
        build_graph.assert_called_once_with(read_repo.return_value, write_repo.return_value)
        graph.execute.assert_called_once_with()

    def test_completed_explicit_track_builds_exact_graph_once_after_analysis(self):
        events = []
        queue = Mock()
        queue.ineligible_tracks.return_value = {}
        source = Mock(location='/music/track-a.flac')
        resolver = Mock()
        resolver.execute.side_effect = lambda track_id: source
        analysis = Mock()
        analysis.execute.side_effect = lambda *args: events.append('analysis-finished') or AnalysisReport(
            'run-a', 'completed', (StageResult('bpm', (), 'provisional', (('bpm', 120.0),)),)
        )
        graph = Mock()
        graph.execute.side_effect = lambda: events.append('graph-built')

        with patch('music_analyzer.frameworks.cli.main.load_settings', return_value=Settings('', False, '/tmp/issue44.sqlite', '/tmp/models')), \
             patch('music_analyzer.frameworks.cli.main.SQLiteBatchQueue', return_value=queue), \
             patch('music_analyzer.frameworks.cli.main.ResolveTrack', return_value=resolver), \
             patch('music_analyzer.frameworks.cli.main.LocalInventory'), \
             patch('music_analyzer.frameworks.cli.main.build_analysis', return_value=analysis), \
             patch('music_analyzer.frameworks.cli.main.BuildGraphSnapshot', return_value=graph) as build_graph, \
             patch('music_analyzer.frameworks.cli.main.ReadOnlyExplorerSQLiteRepository') as read_repo, \
             patch('music_analyzer.frameworks.cli.main.SQLiteAnalysisRepository') as write_repo:
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = main(['analyze', '--track', 'track-a', '--database', '/tmp/issue44.sqlite', '--json'])

        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout.getvalue())['status'], 'completed')
        self.assertEqual(events, ['analysis-finished', 'graph-built'])
        build_graph.assert_called_once_with(read_repo.return_value, write_repo.return_value)
        graph.execute.assert_called_once_with()

    def test_rebuild_failure_preserves_completed_analysis_json_and_reports_stale_action(self):
        report = AnalysisReport('run-a', 'completed', (StageResult('bpm', (), 'provisional', (('bpm', 120.0),)),))
        graph = Mock()
        graph.execute.side_effect = RuntimeError('database is locked')

        with patch('music_analyzer.frameworks.cli.main.MutagenMetadataReader.read', return_value=TrackMetadata(duration_seconds=60.0, duration_source='mutagen')), \
             patch('music_analyzer.frameworks.cli.main.build_analysis') as build_analysis, \
             patch('music_analyzer.frameworks.cli.main.BuildGraphSnapshot', return_value=graph), \
             patch('music_analyzer.frameworks.cli.main.ReadOnlyExplorerSQLiteRepository'), \
             patch('music_analyzer.frameworks.cli.main.SQLiteAnalysisRepository'):
            build_analysis.return_value.execute.return_value = report
            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = main(['analyze', '--file', '/tmp/track-a.flac', '--database', '/tmp/issue44.sqlite', '--json'])

        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout.getvalue())['status'], 'completed')
        warning = stderr.getvalue().lower()
        self.assertIn('graph', warning)
        self.assertIn('stale', warning)
        self.assertIn('run graph build', warning)
        graph.execute.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
