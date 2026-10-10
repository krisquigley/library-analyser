"""Outward, opt-in observation of actual disposable-fixture reader SQL.

This process-local observer temporarily wraps the Explorer repository connection
boundary. It is intended for one owned diagnostic lifecycle, not concurrent
unrelated repository activity. Queries and bindings are never reconstructed:
EXPLAIN runs on the executing connection with its existing metadata UDFs.
"""
from contextlib import closing, contextmanager
from pathlib import Path
import sqlite3
from threading import Lock
from unittest.mock import patch

from music_explorer.infrastructure.explorer_readonly import ReadOnlyExplorerSQLiteRepository


def _operation(sql):
    compact = ' '.join(sql.split())
    if compact.startswith('SELECT count(*) FROM (') and 'FROM summary' in compact:
        return 'summary_count'
    if compact.startswith('WITH first_location AS (') and 'FROM summary' in compact:
        return 'summary_page'
    if compact == 'SELECT id,sha256,size FROM tracks WHERE id=?':
        return 'selected_track'
    if compact == 'SELECT path FROM locations WHERE track_id=? AND available=1 ORDER BY path':
        return 'selected_locations'
    if compact == ('SELECT r.id,r.status,r.detail FROM runs r JOIN run_tracks t '
                   'ON t.run_id=r.id WHERE t.track_id=? ORDER BY r.rowid DESC LIMIT 1'):
        return 'selected_latest_run'
    return None


class _ObservedConnection:
    def __init__(self, connection, observation):
        self._connection = connection
        self._observation = observation

    def execute(self, sql, parameters=()):
        cursor = self._connection.execute(sql, parameters)
        operation = _operation(sql)
        if operation is not None:
            # The original connection retains all adapter UDFs and bindings.
            # No result rows, paths or evidence payloads enter the report.
            rows = self._connection.execute('EXPLAIN QUERY PLAN ' + sql, parameters).fetchall()
            self._observation.record(operation, sql, parameters, rows)
        return cursor

    def __getattr__(self, name):
        return getattr(self._connection, name)


class _SQLiteObservation:
    def __init__(self):
        self._plans = {}
        self._lock = Lock()

    def record(self, operation, sql, parameters, rows):
        with self._lock:
            # Retain one actually executed representative for each operation.
            self._plans.setdefault(operation, {
                'operation': operation, 'sql': sql,
                'parameters': list(parameters), 'rows': [list(row) for row in rows],
            })

    def report(self, db_path):
        uri = Path(db_path).resolve().as_uri() + '?mode=ro'
        with closing(sqlite3.connect(uri, uri=True)) as db:
            db.execute('PRAGMA query_only=ON')
            indexes = [{'name': name, 'sql': sql} for name, sql in db.execute(
                "SELECT name,sql FROM sqlite_master WHERE type='index' ORDER BY name")]
        with self._lock:
            plans = list(self._plans.values())
        return {'version': sqlite3.sqlite_version, 'indexes': indexes, 'plans': plans}


@contextmanager
def observe_sqlite():
    """Observe actual validated repository reads; restore boundary on all exits.

    The caller must finish its HTTP server before leaving this context and
    publish only writer-generated public fixtures. This changes no SQL, reader
    trust checks, transactions, connection pragmas or runtime server behavior.
    """
    observation = _SQLiteObservation()
    original = ReadOnlyExplorerSQLiteRepository._connection

    @contextmanager
    def connection(repository):
        with original(repository) as db:
            yield _ObservedConnection(db, observation)

    with patch.object(ReadOnlyExplorerSQLiteRepository, '_connection', connection):
        yield observation
