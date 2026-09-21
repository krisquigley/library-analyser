"""SQLite queue with a process-lifetime, nonblocking POSIX advisory lock.

The lock file is never unlinked: all cooperating dispatchers lock the same inode.
Only batch dispatchers participate; this is not a hostile-filesystem boundary.
"""
from contextlib import contextmanager
from dataclasses import astuple
import fcntl
import os
from uuid import uuid4

from music_analyzer.application.dto.analysis import AnalysisError
from music_analyzer.application.ports.batch import BatchJob
from music_analyzer.infrastructure.persistence.analysis import SQLiteAnalysisRepository


class SQLiteBatchQueue(SQLiteAnalysisRepository):
    @contextmanager
    def exclusive(self):
        self._check_path()
        descriptor = os.open(str(self._path) + '.batch.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise AnalysisError('A batch dispatcher is already running for this database') from error
            yield
        finally:
            os.close(descriptor)

    def start(self, source):
        run_id = str(uuid4())
        with self._transaction() as db:
            running = db.execute("SELECT track_id FROM batch_jobs WHERE state='running'").fetchall()
            if len(running) != 1:
                raise AnalysisError('Batch worker requires exactly one running job')
            db.execute('INSERT INTO runs(id,location,status) VALUES(?,?,?)', (run_id, source.location, 'running'))
            db.execute('UPDATE batch_jobs SET run_id=? WHERE track_id=?', (run_id, running[0][0]))
            self._link_run(db, run_id, running[0][0])
        return run_id

    def recover(self):
        with self._transaction() as db:
            db.execute("UPDATE runs SET status='interrupted',detail='Dispatcher stopped; stage checkpoints retained' WHERE status='running' AND id IN (SELECT run_id FROM batch_jobs WHERE state IN ('running','pending','failed'))")
            db.execute("UPDATE batch_jobs SET state='pending', detail='Interrupted dispatcher; retained prior run stages' WHERE state='running'")

    def tracks(self):
        with self._transaction() as db:
            return tuple(row[0] for row in db.execute('SELECT DISTINCT track_id FROM locations WHERE available=1 ORDER BY track_id'))

    def get_job(self, track_id):
        with self._transaction() as db:
            row = db.execute('SELECT * FROM batch_jobs WHERE track_id=?', (track_id,)).fetchone()
            return BatchJob(*row) if row else None

    def put_job(self, job):
        with self._transaction() as db:
            db.execute('INSERT INTO batch_jobs VALUES(?,?,?,?,?,?) ON CONFLICT(track_id) DO UPDATE SET fingerprint=excluded.fingerprint,state=excluded.state,attempts=excluded.attempts,run_id=excluded.run_id,detail=excluded.detail', astuple(job))

    def status(self):
        with self._transaction() as db:
            return tuple(BatchJob(*row) for row in db.execute('SELECT * FROM batch_jobs ORDER BY track_id'))
