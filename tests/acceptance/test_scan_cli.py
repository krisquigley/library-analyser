import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from music_analyzer.application.dto.analysis import AnalysisReport
from music_analyzer.frameworks.cli.main import main


class ScanCLITests(unittest.TestCase):
    def test_scan_then_analyze_track_and_stale_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'selected'
            root.mkdir()
            audio = root / '日本語.flac'
            audio.write_bytes(b'temporary fixture not real inference')
            database = str(Path(tmp) / 'analysis.sqlite')
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(main(['scan', str(root), '--database', database, '--json']), 0)
            track = json.loads(out.getvalue())['files'][0]['track_id']
            with patch('music_analyzer.frameworks.cli.main.build_analysis') as build:
                build.return_value.execute.return_value = AnalysisReport('run', 'completed', ())
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(main(['analyze', '--track', track, '--database', database]), 0)
                self.assertEqual(build.return_value.execute.call_args.args[0].location, str(audio))
                audio.write_bytes(b'changed')
                build.reset_mock()
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    self.assertEqual(main(['analyze', '--track', track, '--database', database, '--json']), 1)
                build.assert_not_called()
                self.assertIn('scan', json.loads(out.getvalue())['detail'])

    def test_scan_partial_and_setup_errors_are_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'root'
            root.mkdir()
            (root / 'large.mp3').write_bytes(b'12345')
            for selected in (root, root / 'absent'):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    self.assertEqual(main(['scan', str(selected), '--max-file-bytes', '2', '--database', str(Path(tmp) / 'db'), '--json']), 1)
                self.assertTrue(json.loads(out.getvalue())['issues'])

    def test_track_and_file_are_exclusive(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            main(['analyze', '--file', 'x', '--track', 'id'])
