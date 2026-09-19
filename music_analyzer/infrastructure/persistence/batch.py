"""SQLite queue with a process-lifetime, nonblocking POSIX advisory lock.

The lock file is never unlinked: all cooperating dispatchers lock the same inode.
Only batch dispatchers participate; this is not a hostile-filesystem boundary.
"""
from contextlib import contextmanager
from dataclasses import astuple
import fcntl
import os

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

    def recover(self):
        with self._transaction() as db:
            db.execute("UPDATE batch_jobs SET state=CASE WHEN attempts >= 3 THEN 'failed' ELSE 'pending' END, detail='Interrupted dispatcher; retained prior run stages' WHERE state='running'")

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
