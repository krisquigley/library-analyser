from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from music_analyzer.application.dto.analysis import AnalysisError, AudioSource, StageResult
from music_analyzer.infrastructure.persistence.analysis import SQLiteAnalysisRepository, APPLICATION_ID


class AnalysisRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'analysis.sqlite'

    def test_new_database_has_identity_version_and_durable_stage_provenance(self):
        repository = SQLiteAnalysisRepository(str(self.path))
        run = repository.start(AudioSource('/music/空 白.flac'))
        repository.save_stage(run, StageResult('bpm', (('algorithm', 'test-fake'),), 'not beat grid',
                                               (('bpm', 120.0),)))
        repository.finish(run, 'failed', 'key: unavailable')
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('PRAGMA application_id').fetchone()[0], APPLICATION_ID)
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 3)
            self.assertEqual(db.execute('SELECT location,status,detail FROM runs').fetchone(),
                             ('/music/空 白.flac', 'failed', 'key: unavailable'))
            stage = json.loads(db.execute('SELECT result FROM stages').fetchone()[0])
            self.assertEqual(stage['provenance'], [['algorithm', 'test-fake']])
            self.assertEqual(stage['values'], [['bpm', 120.0]])
        SQLiteAnalysisRepository(str(self.path))  # valid reopen, no destructive recovery

    def test_rejects_foreign_empty_identified_and_future_databases_without_modification(self):
        for setup in ('CREATE TABLE library (id INTEGER)', 'PRAGMA application_id=123',
                      f'PRAGMA application_id={APPLICATION_ID}; PRAGMA user_version=999',
                      'PRAGMA user_version=1',
                      f'PRAGMA application_id={APPLICATION_ID}; PRAGMA user_version=1'):
            with self.subTest(setup=setup):
                self.path.unlink(missing_ok=True)
                with closing(sqlite3.connect(self.path)) as db:
                    db.executescript(setup)
                before = self.path.read_bytes()
                with self.assertRaises(AnalysisError):
                    SQLiteAnalysisRepository(str(self.path))
                self.assertEqual(self.path.read_bytes(), before)

    def test_rejects_symlink_and_mixxx_named_empty_database(self):
        for name in ('mixxx.sqlite', 'Mixxx.db'):
            path = Path(self.temp.name) / name
            path.touch()
            with self.assertRaises(AnalysisError):
                SQLiteAnalysisRepository(str(path))
            self.assertEqual(path.read_bytes(), b'')
        self.path.touch()
        link = Path(self.temp.name) / 'link.sqlite'
        link.symlink_to(self.path)
        with self.assertRaises(AnalysisError):
            SQLiteAnalysisRepository(str(link))

    def test_runs_are_distinct_and_completed_run_cannot_be_overwritten(self):
        repository = SQLiteAnalysisRepository(str(self.path))
        one = repository.start(AudioSource('same.flac'))
        two = repository.start(AudioSource('same.flac'))
        self.assertNotEqual(one, two)
        repository.save_stage(one, StageResult('key', (), 'uncertain'))
        with self.assertRaises(AnalysisError):
            repository.save_stage(one, StageResult('key', (), 'replacement'))
        repository.finish(one, 'completed', '')
        with self.assertRaises(AnalysisError):
            repository.save_stage(one, StageResult('bpm', (), 'late'))
        with self.assertRaises(AnalysisError):
            repository.finish('missing', 'completed', '')
