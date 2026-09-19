from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from music_analyzer.application.dto.analysis import AnalysisError, AudioSource, StageResult
from music_analyzer.application.ports.batch import BatchJob
from music_analyzer.infrastructure.persistence.analysis import SQLiteAnalysisRepository
from music_analyzer.infrastructure.persistence.batch import SQLiteBatchQueue


class BatchQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / 'analysis.sqlite')
        self.repo = SQLiteAnalysisRepository(self.path)
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("INSERT INTO tracks VALUES('a','hash',1)"); db.commit()

    def test_v2_migration_preserves_runs_stages_and_catalogue(self):
        run = self.repo.start(AudioSource('fixture'))
        self.repo.save_stage(run, StageResult('bpm', (('test', 'fake'),), 'raw'))
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('DROP TABLE batch_jobs'); db.execute('PRAGMA user_version=2'); db.commit()
            before = tuple(db.execute('SELECT * FROM stages'))
        SQLiteAnalysisRepository(self.path)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(tuple(db.execute('SELECT * FROM stages')), before)
            self.assertEqual(db.execute('SELECT id FROM tracks').fetchone(), ('a',))
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 3)

    def test_restart_recovers_running_and_preserves_completed(self):
        queue = SQLiteBatchQueue(self.path)
        queue.put_job(BatchJob('a', 'fp', 'running', 1))
        reopened = SQLiteBatchQueue(self.path)
        with reopened.exclusive(): reopened.recover()
        self.assertEqual(reopened.get_job('a').state, 'pending')
        self.assertEqual(reopened.get_job('a').attempts, 1)
        reopened.put_job(BatchJob('a', 'fp', 'completed', 1, 'run'))
        with reopened.exclusive(): reopened.recover()
        self.assertEqual(reopened.get_job('a').run_id, 'run')

    def test_lock_rejects_second_dispatcher_and_releases_on_interrupt(self):
        one, two = SQLiteBatchQueue(self.path), SQLiteBatchQueue(self.path)
        with self.assertRaises(KeyboardInterrupt):
            with one.exclusive():
                with self.assertRaisesRegex(AnalysisError, 'already running'):
                    with two.exclusive(): pass
                raise KeyboardInterrupt()
        with two.exclusive(): pass

    def test_status_and_invalid_state(self):
        queue = SQLiteBatchQueue(self.path)
        self.assertEqual(queue.status(), ())
        with self.assertRaises(AnalysisError): queue.put_job(BatchJob('a', 'fp', 'oops'))
