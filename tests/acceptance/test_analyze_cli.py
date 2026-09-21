import contextlib
import io
import json
import unittest
from unittest.mock import patch
from music_analyzer.application.dto.analysis import AnalysisReport, StageResult
from music_analyzer.frameworks.cli.main import main


class AnalyzeCLITests(unittest.TestCase):
    def test_explicit_file_preserves_future_track_id_argument(self):
        report = AnalysisReport('run', 'completed', (StageResult('bpm', (), 'provisional', (('bpm', 120.),)),))
        with patch('music_analyzer.frameworks.cli.main.build_analysis') as build:
            build.return_value.execute.return_value = report
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(main(['analyze', '--file', '/tmp/example.flac', '--max-duration', '60', '--json']), 0)
            self.assertEqual(json.loads(out.getvalue())['stages'][0]['values'][0], ['bpm', 120.])
            args = build.return_value.execute.call_args.args
            self.assertEqual(args[0].location, '/tmp/example.flac')
            self.assertEqual(args[1], 60)

    def test_failed_partial_report_is_json_and_nonzero(self):
        with patch('music_analyzer.frameworks.cli.main.build_analysis') as build:
            build.return_value.execute.return_value = AnalysisReport('run', 'failed', (), 'genres: missing model')
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(main(['analyze', '--file', 'x', '--json']), 1)
            self.assertEqual(json.loads(out.getvalue())['status'], 'failed')

    def test_invalid_limit_rejected_before_database(self):
        with patch('music_analyzer.frameworks.cli.main.build_analysis') as build:
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                main(['analyze', '--file', 'x', '--max-duration', 'nan'])
            build.assert_not_called()

    def test_composition_uses_configured_database(self):
        from music_analyzer.application.dto.settings import Settings
        from music_analyzer.frameworks.cli.main import build_analysis
        with patch('music_analyzer.frameworks.cli.main.load_settings', return_value=Settings('', False, '/tmp/dedicated.db', '/tmp/models')), patch('music_analyzer.frameworks.cli.main.load_backend', return_value=(object(), 'test', object())), patch('music_analyzer.frameworks.cli.main.SQLiteAnalysisRepository') as repository:
            build_analysis()
            repository.assert_called_once_with('/tmp/dedicated.db')

    def test_setup_error_is_json_without_claiming_a_run(self):
        from music_analyzer.application.dto.analysis import AnalysisError
        with patch('music_analyzer.frameworks.cli.main.build_analysis', side_effect=AnalysisError('TensorFlow required')):
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(['analyze', '--file', 'x', '--json']), 1)
            data = json.loads(out.getvalue())
            self.assertIsNone(data['run_id'])
            self.assertIn('TensorFlow', data['detail'])
