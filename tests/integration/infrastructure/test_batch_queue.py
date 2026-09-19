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

    def test_worker_run_is_bound_before_stages_and_recovered(self):
        queue = SQLiteBatchQueue(self.path)
        queue.put_job(BatchJob('a', 'fp', 'running', 1))
        run = queue.start(AudioSource('fixture'))
        queue.save_stage(run, StageResult('bpm', (), 'fake'))
        self.assertEqual(queue.get_job('a').run_id, run)
        with queue.exclusive(): queue.recover()
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT status FROM runs WHERE id=?', (run,)).fetchone(), ('interrupted',))
            self.assertEqual(db.execute('SELECT COUNT(*) FROM stages').fetchone()[0], 1)

    def test_lock_is_exclusive_across_processes(self):
        import subprocess
        import sys
        queue = SQLiteBatchQueue(self.path)
        code = '''
import sys
from music_analyzer.infrastructure.persistence.batch import SQLiteBatchQueue
from music_analyzer.application.dto.analysis import AnalysisError
try:
    with SQLiteBatchQueue(sys.argv[1]).exclusive(): pass
except AnalysisError:
    sys.exit(7)
'''
        with queue.exclusive():
            result = subprocess.run([sys.executable, '-c', code, self.path], timeout=10)
            self.assertEqual(result.returncode, 7)
        self.assertEqual(subprocess.run([sys.executable, '-c', code, self.path], timeout=10).returncode, 0)

    def test_failed_job_closes_unfinished_worker_run_on_recovery(self):
        queue = SQLiteBatchQueue(self.path)
        queue.put_job(BatchJob('a', 'fp', 'running', 1))
        run = queue.start(AudioSource('fixture'))
        queue.put_job(BatchJob('a', 'fp', 'failed', 1, run, 'unexpected worker error'))
        with queue.exclusive(): queue.recover()
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT status FROM runs WHERE id=?', (run,)).fetchone(), ('interrupted',))
        self.assertEqual(queue.get_job('a').state, 'failed')
