"""Outward, opt-in observation of actual disposable-fixture reader SQL.

This process-local observer temporarily wraps the Explorer repository connection
boundary. It is intended for one owned diagnostic lifecycle, not concurrent
unrelated repository activity. Queries and bindings are never reconstructed:
EXPLAIN runs on the executing connection with its existing metadata UDFs.
"""
from contextlib import closing, contextmanager, nullcontext
from pathlib import Path
import sqlite3
from threading import Lock
from time import monotonic
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
    if (compact.startswith('SELECT stage,') and
            compact.endswith(' FROM stages WHERE run_id=? ORDER BY stage')):
        return 'selected_stage_sizes'
    selected = {
        'SELECT result FROM stages WHERE run_id=? AND stage=?': 'selected_stage_payload',
        'SELECT field,value FROM overrides WHERE track_id=? ORDER BY field': 'selected_overrides',
        'SELECT common_json,tags_json,warnings_json FROM track_metadata WHERE track_id=?': 'selected_metadata',
        'SELECT duration_seconds,duration_source,status,reason FROM track_audio WHERE track_id=?': 'selected_audio',
    }
    return selected.get(compact)


class _ObservedCursor:
    """Time actual cursor calls, never caller processing between iteration steps.

    Iteration steps remain partial until terminal exhaustion is requested. Closing
    (including connection cleanup) cannot certify that unrequested rows drained.
    """
    def __init__(self, cursor, observation, operation):
        self._cursor = cursor
        self._observation = observation
        self._operation = operation
        self._iteration_spans = []

    @property
    def arraysize(self):
        return self._cursor.arraysize

    @arraysize.setter
    def arraysize(self, size):
        self._cursor.arraysize = size

    def _fetch(self, method, *args, **kwargs):
        with self._observation.measure(self._operation, 'selected_sql_fetch', method):
            return getattr(self._cursor, method)(*args, **kwargs)

    def _complete_iteration(self):
        for previous, context_record in self._iteration_spans:
            if previous['status'] == 'partial':
                previous['status'] = 'ok'
            if context_record is not None and context_record['status'] == 'partial':
                context_record['status'] = 'ok'
        self._iteration_spans.clear()

    def fetchone(self):
        row = self._fetch('fetchone')
        if row is None:
            self._complete_iteration()
        return row

    def fetchall(self):
        rows = self._fetch('fetchall')
        self._complete_iteration()
        return rows

    def fetchmany(self, *args, **kwargs):
        size = args[0] if args else kwargs.get('size', self._cursor.arraysize)
        rows = self._fetch('fetchmany', *args, **kwargs)
        if not rows and size > 0:
            self._complete_iteration()
        return rows

    def __iter__(self):
        return self

    def __next__(self):
        exhausted = False
        with self._observation.measure(
                self._operation, 'selected_sql_fetch', 'iteration') as span:
            try:
                row = next(self._cursor)
            except StopIteration:
                exhausted = True
            else:
                span['status'] = 'partial'
                self._iteration_spans.append((span, span.get('_context_record')))
        # Exhaustion certifies earlier steps only after the observer context
        # exits successfully, just like terminal fetchone/fetchmany/fetchall.
        if exhausted:
            self._complete_iteration()
            raise StopIteration
        return row

    def __getattr__(self, name):
        return getattr(self._cursor, name)


class _ObservedConnection:
    def __init__(self, connection, observation):
        self._connection = connection
        self._observation = observation

    def execute(self, sql, parameters=()):
        operation = _operation(sql)
        if operation is None:
            return self._connection.execute(sql, parameters)
        # Execute excludes EQP overhead; SQLite may do substantial work here,
        # with additional materialization measured only when the caller drains.
        with self._observation.measure(operation, 'selected_sql_execute'):
            cursor = self._connection.execute(sql, parameters)
        with self._observation.measure(operation, 'observer_explain'):
            rows = self._connection.execute('EXPLAIN QUERY PLAN ' + sql, parameters).fetchall()
        self._observation.record(operation, sql, parameters, rows)
        return _ObservedCursor(cursor, self._observation, operation)

    def __getattr__(self, name):
        return getattr(self._connection, name)


class _SQLiteObservation:
    def __init__(self, span_context=None):
        self._span_context = span_context
        self._spans = []
        self._plans = {}
        self._lock = Lock()

    @contextmanager
    def measure(self, operation, phase, fetch_method=None):
        span = {'operation': operation, 'phase': phase, 'clock': 'monotonic',
                'start_ms': monotonic() * 1000, 'status': 'ok'}
        if fetch_method is not None:
            span['fetch_method'] = fetch_method
        context_record = None
        try:
            context = (self._span_context(phase) if self._span_context is not None
                       else nullcontext())
            with context as context_record:
                span['_context_record'] = context_record
                try:
                    yield span
                except StopIteration:
                    raise
                except BaseException:
                    span['status'] = 'failed'
                    raise
                finally:
                    if context_record is not None:
                        context_record['status'] = span['status']
        except StopIteration:
            raise
        except BaseException:
            span['status'] = 'failed'
            # Context exit can fail after the inner status synchronization.
            if context_record is not None:
                context_record['status'] = 'failed'
            raise
        finally:
            span.pop('_context_record', None)
            span['end_ms'] = monotonic() * 1000
            with self._lock:
                self._spans.append(span)

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
            spans = [dict(span) for span in self._spans]
        return {'version': sqlite3.sqlite_version, 'indexes': indexes, 'plans': plans, 'spans': spans}


@contextmanager
def observe_sqlite(*, span_context=None):
    """Observe actual validated repository reads; restore boundary on all exits.

    The caller must finish its HTTP server before leaving this context and
    publish only writer-generated public fixtures. This changes no SQL, reader
    trust checks, transactions, connection pragmas or runtime server behavior.
    ``span_context(phase)`` optionally supplies an outward request-local context;
    it encloses only actual cursor work, not EQP or application row processing.
    Raw iteration spans are individual SQLite steps, not a cursor-lifetime timer.
    """
    observation = _SQLiteObservation(span_context)
    original = ReadOnlyExplorerSQLiteRepository._connection

    @contextmanager
    def connection(repository):
        with original(repository) as db:
            yield _ObservedConnection(db, observation)

    with patch.object(ReadOnlyExplorerSQLiteRepository, '_connection', connection):
        yield observation
