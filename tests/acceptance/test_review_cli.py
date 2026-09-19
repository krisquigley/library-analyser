import csv
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch
from music_analyzer.frameworks.cli.main import main
from music_analyzer.application.dto.analysis import AudioSource, StageResult
from music_analyzer.infrastructure.persistence.analysis import SQLiteAnalysisRepository
from music_analyzer.infrastructure.filesystem.inventory import LocalInventory
from music_analyzer.application.use_cases.scan_library import ScanLibrary


class ReviewCLITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.db = self.root/'analysis.db'
        (self.root/'音,".flac').write_bytes(b'fixture not audio')
        self.repo = SQLiteAnalysisRepository(str(self.db))
        self.track = ScanLibrary(LocalInventory(), self.repo).execute(str(self.root)).files[0].identity.track_id

    def call(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err), patch('music_analyzer.frameworks.cli.main.load_backend', side_effect=AssertionError('no inference')), patch('music_analyzer.frameworks.cli.main.FFmpegDecoder', side_effect=AssertionError('no decode')):
            code = main(['--database', str(self.db), *args])
        return code, out.getvalue(), err.getvalue()

    def test_inspect_override_reanalysis_clear_export_and_errors(self):
        code, out, err = self.call('show', self.track, '--json')
        self.assertEqual((code, err), (0, '')); self.assertIsNone(json.loads(out)['run'])
        self.assertIn(self.track, self.call('list', '--needs-review')[1])
        manual = ' \t=SUM(1,2) "été"\nnext'
        self.assertEqual(self.call('override', 'set', self.track, 'genres', manual)[0], 0)
        run = self.repo.start(AudioSource('fixture', self.track))
        stage = StageResult('genres', (('engine', 'fake only'),), 'uncalibrated', raw_predictions=(((.2, .8),),))
        self.repo.save_stage(run, stage); self.repo.finish(run, 'failed', 'fixture partial')
        result = json.loads(self.call('show', self.track, '--json')[1])
        self.assertEqual(result['effective']['genres'], manual)
        self.assertEqual(result['run']['stages'][0]['raw_predictions'], [[[.2, .8]]])
        for format in ('json', 'csv'):
            output = self.root/('export.' + format)
            code, out, err = self.call('export', '--format', format, '--output', str(output))
            self.assertEqual((code, err), (0, ''))
            if format == 'json':
                self.assertEqual(json.loads(output.read_text())[0], result)
            else:
                rows = list(csv.DictReader(io.StringIO(output.read_text())))
                self.assertEqual(rows[0]['track_id'], self.track)
                self.assertEqual(rows[0]['override_genres'], "'" + manual)
                self.assertEqual(json.loads(rows[0]['record'])['run'], result['run'])
        self.assertEqual(self.call('override', 'clear', self.track, 'genres')[0], 0)
        self.assertEqual(json.loads(self.call('show', self.track, '--json')[1])['overrides'], {})
        code, out, err = self.call('show', 'absent', '--json')
        self.assertEqual(code, 1); self.assertEqual(out, ''); self.assertIn('Unknown track', err)
        code, out, err = self.call('export', '--format', 'json', '--output', str(self.root/'absent'/'x'))
        self.assertEqual(code, 1); self.assertFalse(out); self.assertTrue(err)

    def test_reaggregate_json_uses_retained_windows_and_preserves_database(self):
        from music_analyzer.domain.analysis import ScoreWindow, summarize_scores
        windows = (ScoreWindow(0, 10, (.2, .8)),)
        run = self.repo.start(AudioSource('fixture', self.track))
        self.repo.save_stage(run, StageResult('genres', (), 'raw', windows=windows,
            summary=summarize_scores(('a','b'), windows, 10)))
        self.repo.finish(run, 'completed', '')
        before = self.db.read_bytes()
        code, out, err = self.call('reaggregate', self.track, '--threshold', '.5', '--json')
        self.assertEqual((code, err), (0, ''))
        self.assertEqual(json.loads(out)['selections']['genres'], ['b'])
        self.assertEqual(self.db.read_bytes(), before)
        self.assertEqual(self.call('reaggregate', self.track, '--threshold', 'nan')[0], 1)
        self.assertIn('TRACK_ID', self.call('show', self.track)[1])
