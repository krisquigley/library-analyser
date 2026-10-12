"""Unrepresentable checkpoint arithmetic must fail through the public boundary."""
from contextlib import closing, contextmanager
from dataclasses import asdict
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from music_analyzer.application.dto.analysis import AnalysisError, AudioSource, DecodedAudio, StageResult
from music_analyzer.application.use_cases.analyze_track import AnalyzeTrack
from music_analyzer.domain.analysis import ScoreSummary, ScoreWindow
from music_analyzer.infrastructure.persistence.analysis import SQLiteAnalysisRepository


def overflowing_stage(stage='mood'):
    return StageResult(stage, (), '', windows=(ScoreWindow(0, 10**309, (0.7,)),),
                       summary=ScoreSummary(('happy',), (0.7,), (0.7,), (0.7,), 1.0))


class StageArithmeticOverflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'analysis.sqlite'
        self.repository = SQLiteAnalysisRepository(str(self.path))
        self.source = AudioSource('/synthetic/track.flac')

    def test_save_stage_rejects_strict_json_window_overflow_without_checkpoint(self):
        result = overflowing_stage()
        payload = json.dumps(asdict(result), allow_nan=False)
        self.assertEqual(json.loads(payload)['windows'][0]['end'], 10**309)
        run_id = self.repository.start(self.source)
        with self.assertRaisesRegex(AnalysisError, 'Invalid .*window'):
            self.repository.save_stage(run_id, result)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT status,detail FROM runs WHERE id=?',
                                        (run_id,)).fetchone(), ('running', ''))
            self.assertEqual(db.execute('SELECT * FROM stages WHERE run_id=?',
                                        (run_id,)).fetchall(), [])
        # A rejected checkpoint leaves the same stage available for a valid retry.
        self.repository.save_stage(run_id, StageResult('mood', (), 'valid retry'))
        self.repository.finish(run_id, 'completed', '')

    def test_analyze_track_finalizes_overflow_as_failed_and_cleans_up(self):
        events = []

        class Decoder:
            @contextmanager
            def decode(self, source, max_duration):
                try:
                    yield DecodedAudio('synthetic-handle', 10, 44100)
                finally:
                    events.append('cleanup')

        class Engine:
            def analyze(self, stage, audio):
                events.append(stage)
                return overflowing_stage(stage) if stage == 'mood' else StageResult(stage, (), '')

        report = AnalyzeTrack(Decoder(), Engine(), self.repository).execute(self.source)
        self.assertEqual(report.status, 'failed')
        self.assertEqual(tuple(result.stage for result in report.stages), ('bpm', 'key', 'genres'))
        self.assertRegex(report.detail, r'^mood: Invalid .*window')
        self.assertEqual(events, ['bpm', 'key', 'genres', 'mood', 'cleanup'])
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT status,detail FROM runs WHERE id=?',
                                        (report.run_id,)).fetchone(), ('failed', report.detail))
            self.assertEqual(db.execute('SELECT stage FROM stages WHERE run_id=? ORDER BY rowid',
                                        (report.run_id,)).fetchall(), [('bpm',), ('key',), ('genres',)])
