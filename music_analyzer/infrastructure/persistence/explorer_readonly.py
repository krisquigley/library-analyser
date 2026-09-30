"""Read-only SQLite explorer adapter.

Uses bounded read transactions against the selected live analysis database.  The
adapter opens SQLite with ``mode=ro`` so committed WAL frames are visible, avoids
``immutable=1``, enables ``query_only`` defense, and never creates or migrates
schemas.
"""
from contextlib import contextmanager
from math import isfinite
import json
from pathlib import Path
import re
import sqlite3

from music_analyzer.application.dto.analysis import AnalysisError, AnalysisReport
from music_analyzer.application.dto.catalogue import TrackMetadata
from music_analyzer.application.dto.explorer import ExplorerStoredTrack, ExplorerTrackSummary
from music_analyzer.domain.library_duration_policy import DurationVerification, TRUSTED_DURATION_SOURCES, active_library_duration_policy
from music_analyzer.infrastructure.persistence.analysis import APPLICATION_ID
from music_analyzer.infrastructure.persistence.stage_mapping import stage_from_mapping

_SHA256_RE = re.compile(r'^[0-9a-f]{64}$')
_TRACK_ID_RE = re.compile(r'^sha256:[0-9a-f]{64}$')


def _duration_decision(duration_seconds, source):
    return active_library_duration_policy(DurationVerification(duration_seconds, source) if source else None)


def _expected_audio_status(duration_seconds, source):
    decision = _duration_decision(duration_seconds, source)
    if decision.active:
        return 'eligible'
    if source in TRUSTED_DURATION_SOURCES and duration_seconds is not None:
        return 'excluded'
    return 'unknown'


_EXPECTED_SCHEMA = {
    'runs': {
        'columns': ((('id', 'TEXT', False, 1), ('location', 'TEXT', True, 0), ('status', 'TEXT', True, 0),
                     ('detail', 'TEXT', True, 0), ('created_at', 'TEXT', True, 0)),
                    (('id', 'TEXT', False, 1), ('location', 'TEXT', False, 0), ('status', 'TEXT', False, 0),
                     ('detail', 'TEXT', False, 0), ('created_at', 'TEXT', False, 0))),
        'foreign_keys': ((),),
        'unique_indexes': (),
        'checks': (("CHECK(status IN ('running','completed','failed','interrupted'))",), ()),
    },
    'stages': {
        'columns': ((('run_id', 'TEXT', True, 1), ('stage', 'TEXT', True, 2), ('result', 'TEXT', True, 0)),
                    (('run_id', 'TEXT', False, 1), ('stage', 'TEXT', False, 2), ('result', 'TEXT', False, 0))),
        'foreign_keys': ((('runs', ('run_id',), ('id',)),), ()),
        'unique_indexes': (),
        'checks': ((),),
    },
    'tracks': {
        'columns': ((('id', 'TEXT', False, 1), ('sha256', 'TEXT', True, 0), ('size', 'INTEGER', True, 0)),),
        'foreign_keys': ((),),
        'unique_indexes': (('sha256',),),
        'checks': ((),),
    },
    'locations': {
        'columns': ((('path', 'TEXT', False, 1), ('track_id', 'TEXT', True, 0), ('mtime_ns', 'INTEGER', True, 0),
                     ('format', 'TEXT', True, 0), ('available', 'INTEGER', True, 0)),),
        'foreign_keys': ((('tracks', ('track_id',), ('id',)),),),
        'unique_indexes': (),
        'checks': (('CHECK(available IN (0,1))',),),
    },
    'scan_roots': {
        'columns': ((('root', 'TEXT', True, 1), ('path', 'TEXT', True, 2)),),
        'foreign_keys': ((('locations', ('path',), ('path',)),),),
        'unique_indexes': (),
        'checks': ((),),
    },
    'batch_jobs': {
        'columns': ((('track_id', 'TEXT', False, 1), ('fingerprint', 'TEXT', True, 0), ('state', 'TEXT', True, 0),
                     ('attempts', 'INTEGER', True, 0), ('run_id', 'TEXT', False, 0), ('detail', 'TEXT', True, 0)),),
        'foreign_keys': ((('tracks', ('track_id',), ('id',)),),),
        'unique_indexes': (),
        'checks': (("CHECK(state IN ('pending','running','completed','failed'))", 'CHECK(attempts >= 0)'),),
    },
    'run_tracks': {
        'columns': ((('run_id', 'TEXT', False, 1), ('track_id', 'TEXT', True, 0)),),
        'foreign_keys': ((('runs', ('run_id',), ('id',)), ('tracks', ('track_id',), ('id',))),),
        'unique_indexes': (),
        'checks': ((),),
    },
    'overrides': {
        'columns': ((('track_id', 'TEXT', True, 1), ('field', 'TEXT', True, 2), ('value', 'TEXT', True, 0)),),
        'foreign_keys': ((('tracks', ('track_id',), ('id',)),),),
        'unique_indexes': (),
        'checks': ((),),
    },
    'track_metadata': {
        'columns': ((('track_id', 'TEXT', False, 1), ('common_json', 'TEXT', True, 0), ('tags_json', 'TEXT', True, 0), ('warnings_json', 'TEXT', True, 0)),),
        'foreign_keys': ((('tracks', ('track_id',), ('id',)),),),
        'unique_indexes': (),
        'checks': ((),),
    },
    'track_audio': {
        'columns': ((('track_id', 'TEXT', False, 1), ('duration_seconds', 'REAL', False, 0), ('duration_source', 'TEXT', True, 0), ('status', 'TEXT', True, 0), ('reason', 'TEXT', True, 0)),),
        'foreign_keys': ((('tracks', ('track_id',), ('id',)),),),
        'unique_indexes': (),
        'checks': (("CHECK(status IN ('eligible','excluded','unknown'))",),),
    },
}
_EXPECTED_VIEWS = {
    'active_tracks': (
        ('id', 'sha256', 'size'),
        "CREATE VIEW active_tracks AS SELECT t.id,t.sha256,t.size FROM tracks t JOIN track_audio a ON a.track_id=t.id WHERE a.status='eligible'",
    ),
    'active_locations': (
        ('path', 'track_id', 'mtime_ns', 'format', 'available'),
        "CREATE VIEW active_locations AS SELECT l.path,l.track_id,l.mtime_ns,l.format,l.available FROM locations l JOIN track_audio a ON a.track_id=l.track_id WHERE l.available=1 AND a.status='eligible'",
    ),
}


class ReadOnlyExplorerSQLiteRepository:
    def __init__(self, path: str):
        self._path = Path(path).absolute()
        self._check_path()

    def metadata(self):
        with self._transaction() as db:
            return self._metadata(db)

    def list_tracks(self, limit: int, after: str | None = None):
        with self._transaction() as db:
            metadata = self._metadata(db)
            where = '' if after is None else 'WHERE id > ?'
            params = () if after is None else (after,)
            track_count = db.execute(f'SELECT count(*) FROM active_tracks {where}', params).fetchone()[0]
            ids = tuple(row[0] for row in db.execute(f'SELECT id FROM active_tracks {where} ORDER BY id LIMIT ?', (*params, limit)))
            return metadata, track_count, tuple(self._read_track(db, track_id) for track_id in ids)


    def list_track_summaries(self, limit: int, cursor: str | None = None, query: str = '', order: str = 'title'):
        with self._transaction() as db:
            metadata = self._metadata(db)
            where = []
            params = []
            q = (query or '').strip().lower()
            if q:
                like = '%' + q.replace('%', '\\%').replace('_', '\\_') + '%'
                where.append("(lower(id) LIKE ? ESCAPE '\\' OR lower(COALESCE(first_path,'')) LIKE ? ESCAPE '\\' OR lower(COALESCE(common_json,'')) LIKE ? ESCAPE '\\' OR lower(COALESCE(tags_json,'')) LIKE ? ESCAPE '\\')")
                params.extend([like, like, like, like])
            cursor_key, cursor_id = self._decode_summary_cursor(cursor)
            order_expr = 'lower(display_label)' if order in ('title', 'artist') else 'id'
            if cursor_key is not None and cursor_id is not None:
                where.append(f"({order_expr} > ? OR ({order_expr} = ? AND id > ?))")
                params.extend([cursor_key, cursor_key, cursor_id])
            where_sql = ('WHERE ' + ' AND '.join(where)) if where else ''
            base = """
                WITH first_location AS (
                    SELECT track_id, min(path) AS path, count(*) AS available_locations
                    FROM active_locations GROUP BY track_id
                ), summary AS (
                    SELECT t.id, t.sha256, t.size, COALESCE(first_location.path, '') AS first_path,
                           COALESCE(first_location.available_locations, 0) AS available_locations,
                           COALESCE(tm.common_json, '[]') AS common_json,
                           COALESCE(tm.tags_json, '[]') AS tags_json,
                           lower(CASE WHEN COALESCE(first_location.path, '') = '' THEN t.id ELSE COALESCE(first_location.path, '') END) AS display_label
                    FROM active_tracks t
                    LEFT JOIN first_location ON first_location.track_id=t.id
                    LEFT JOIN track_metadata tm ON tm.track_id=t.id
                )
                SELECT id, sha256, size, first_path, available_locations, common_json, tags_json, display_label
                FROM summary
            """
            track_count = db.execute('SELECT count(*) FROM (' + base + where_sql + ')', tuple(params)).fetchone()[0]
            rows = db.execute(base + where_sql + f' ORDER BY {order_expr}, id LIMIT ?', (*params, limit + 1)).fetchall()
            page_rows = rows[:limit]
            summaries = tuple(self._summary_from_row(row) for row in page_rows)
            next_cursor = None
            if len(rows) > limit and page_rows:
                last = page_rows[-1]
                key = last[7] if order in ('title', 'artist') else last[0]
                next_cursor = self._encode_summary_cursor(key, last[0])
            return metadata, track_count, summaries, next_cursor

    def candidate_snapshot(self):
        with self._transaction() as db:
            metadata = self._metadata(db)
            ids = tuple(row[0] for row in db.execute('SELECT id FROM active_tracks ORDER BY id'))
            return metadata, tuple(self._read_track(db, track_id) for track_id in ids)

    def track_ids(self):
        with self._transaction() as db:
            return tuple(row[0] for row in db.execute('SELECT id FROM active_tracks ORDER BY id'))

    def available_audio_paths(self):
        with self._transaction() as db:
            return tuple(row[0] for row in db.execute('SELECT path FROM active_locations ORDER BY path'))

    def read_track(self, track_id: str):
        with self._transaction() as db:
            return self._read_track(db, track_id)

    def _metadata(self, db):
        return {
            'application_id': db.execute('PRAGMA application_id').fetchone()[0],
            'schema_version': db.execute('PRAGMA user_version').fetchone()[0],
            'read_policy': 'bounded_read_transaction',
        }

    def _read_track(self, db, track_id: str):
        track = db.execute('SELECT id,sha256,size FROM tracks WHERE id=?', (track_id,)).fetchone()
        if not track:
            raise AnalysisError('Unknown explorer track')
        locations = db.execute('SELECT path FROM locations WHERE track_id=? AND available=1 ORDER BY path', (track_id,)).fetchall()
        display_label = Path(locations[0][0]).name if locations else ''
        row = db.execute('SELECT r.id,r.status,r.detail FROM runs r JOIN run_tracks t ON t.run_id=r.id WHERE t.track_id=? ORDER BY r.rowid DESC LIMIT 1', (track_id,)).fetchone()
        run = None
        if row:
            stages = []
            for stage, size in db.execute('SELECT stage,length(CAST(result AS BLOB)) FROM stages WHERE run_id=? ORDER BY stage', (row[0],)):
                if size > 16 * 1024 * 1024:
                    raise AnalysisError('Oversized stored stage (16 MiB limit)')
                payload = db.execute('SELECT result FROM stages WHERE run_id=? AND stage=?', (row[0], stage)).fetchone()[0]
                try:
                    data = json.loads(payload)
                    if not isinstance(data, dict):
                        raise ValueError('Stage payload must be a JSON object')
                    result = stage_from_mapping(data)
                    if result.stage != stage:
                        raise ValueError('Stage name mismatch')
                    # Do not expose raw prediction tensors through explorer DTOs.
                    result = type(result)(result.stage, result.provenance, result.uncertainty, result.values, result.windows, result.summary, ())
                    stages.append(result)
                except (ValueError, KeyError, TypeError, IndexError, AttributeError, json.JSONDecodeError) as error:
                    raise AnalysisError('Invalid stored stage: ' + str(error)) from error
            run = AnalysisReport(row[0], row[1], tuple(stages), row[2])
        overrides = tuple(db.execute('SELECT field,value FROM overrides WHERE track_id=? ORDER BY field', (track_id,)))
        metadata = self._read_metadata(db, track_id)
        return ExplorerStoredTrack(track[0], track[1], track[2], display_label, len(locations), run, overrides, metadata)


    def _summary_from_row(self, row):
        track_id, _sha, _size, first_path, available_locations, common_json, tags_json, display_label = row
        label = Path(first_path).name if first_path else display_label
        metadata = self._metadata_from_json(common_json, tags_json, '[]', None)
        title = self._metadata_value(metadata, 'title') or label or track_id
        artist = self._metadata_value(metadata, 'artist') or 'Unknown artist'
        return ExplorerTrackSummary(track_id, title, artist, label, int(available_locations))

    def _metadata_from_json(self, common_json, tags_json, warnings_json, audio):
        warnings = tuple(str(x) for x in json.loads(warnings_json))
        return TrackMetadata(tuple((str(k), tuple(v) if isinstance(v, list) else str(v)) for k, v in json.loads(common_json)), tuple((str(k), tuple(str(x) for x in v)) for k, v in json.loads(tags_json)), warnings, audio[0] if audio else None, audio[1] if audio else '')

    def _metadata_value(self, metadata, semantic):
        wanted = {'title': ('title',), 'artist': ('artist', 'artists')}[semantic]
        for key, value in metadata.common:
            if str(key).strip().lower().replace(' ', '_') in wanted:
                if isinstance(value, tuple):
                    joined = '; '.join(str(v).strip() for v in value if str(v).strip())
                    if joined:
                        return joined
                elif str(value).strip():
                    return str(value).strip()
        for key, values in metadata.tags:
            if str(key).strip().lower().replace(' ', '_') in wanted:
                joined = '; '.join(str(v).strip() for v in (values or ()) if str(v).strip())
                if joined:
                    return joined
        return None

    def _encode_summary_cursor(self, key, track_id):
        import base64
        return base64.urlsafe_b64encode(json.dumps([key, track_id], separators=(',', ':')).encode('utf-8')).decode('ascii')

    def _decode_summary_cursor(self, cursor):
        if not cursor:
            return None, None
        try:
            import base64
            value = json.loads(base64.urlsafe_b64decode(str(cursor).encode('ascii')).decode('utf-8'))
            if isinstance(value, list) and len(value) == 2 and all(isinstance(x, str) for x in value):
                return value[0], value[1]
        except Exception:
            pass
        raise AnalysisError('Invalid explorer summary cursor')

    def _read_metadata(self, db, track_id):
        row = db.execute('SELECT common_json,tags_json,warnings_json FROM track_metadata WHERE track_id=?', (track_id,)).fetchone()
        audio = db.execute('SELECT duration_seconds,duration_source,status,reason FROM track_audio WHERE track_id=?', (track_id,)).fetchone()
        if not row:
            return TrackMetadata(duration_seconds=(audio[0] if audio else None), duration_source=(audio[1] if audio else ''))
        try:
            return self._metadata_from_json(row[0], row[1], row[2], audio)
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise AnalysisError('Invalid stored metadata') from error

    def _check_path(self):
        if self._path.stem.lower() == 'mixxx' or any(p.is_symlink() for p in (self._path, *self._path.parents)):
            raise AnalysisError('Refusing Mixxx-named or symlink database path')
        if not self._path.exists():
            raise AnalysisError('Explorer database must already exist')

    @contextmanager
    def _connection(self):
        self._check_path()
        db = None
        try:
            uri = self._path.as_uri() + '?mode=ro'
            db = sqlite3.connect(uri, uri=True, timeout=1)
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('PRAGMA query_only=ON')
            yield db
        except (sqlite3.Error, OSError) as error:
            raise AnalysisError(f'Analysis database error: {error}') from error
        finally:
            if db is not None:
                db.close()

    @contextmanager
    def _transaction(self):
        with self._connection() as db:
            db.execute('BEGIN')
            self._validate(db)
            yield db
            db.execute('COMMIT')

    def _validate(self, db):
        if (db.execute('PRAGMA application_id').fetchone()[0] != APPLICATION_ID
                or db.execute('PRAGMA user_version').fetchone()[0] != 6):
            raise AnalysisError('Not a supported music-analyzer analysis database')
        objects = set(db.execute("SELECT name,type FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' AND type IN ('table','view')"))
        expected_objects = {(name, 'table') for name in _EXPECTED_SCHEMA} | {(name, 'view') for name in _EXPECTED_VIEWS}
        if objects != expected_objects:
            raise AnalysisError('Unexpected analysis database schema')
        for view, (columns, expected_sql) in _EXPECTED_VIEWS.items():
            actual_columns = tuple(row[1] for row in db.execute(f'PRAGMA table_info({view})'))
            actual_sql = db.execute("SELECT sql FROM sqlite_master WHERE type='view' AND name=?", (view,)).fetchone()[0]
            normalize = lambda sql: ' '.join(sql.rstrip(';').split())
            if actual_columns != columns or normalize(actual_sql) != normalize(expected_sql):
                raise AnalysisError('Unexpected analysis database schema')
        for table, expected in _EXPECTED_SCHEMA.items():
            sql = db.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()[0]
            actual_columns = tuple(
                (row[1], row[2].upper(), bool(row[3]), row[5])
                for row in db.execute(f'PRAGMA table_info({table})')
            )
            if actual_columns not in expected['columns']:
                raise AnalysisError('Unexpected analysis database schema')
            if self._foreign_keys(db, table) not in expected['foreign_keys']:
                raise AnalysisError('Unexpected analysis database schema')
            if self._unique_indexes(db, table) != expected['unique_indexes']:
                raise AnalysisError('Unexpected analysis database schema')
            compact_sql = ' '.join(sql.split())
            if not any(all(check in compact_sql for check in checks) for checks in expected['checks']):
                raise AnalysisError('Unexpected analysis database schema')
        self._validate_rows(db)

    def _validate_rows(self, db):
        for track_id, sha256, size in db.execute('SELECT id,sha256,size FROM tracks'):
            if (not isinstance(track_id, str) or not _TRACK_ID_RE.fullmatch(track_id)
                    or not isinstance(sha256, str) or not _SHA256_RE.fullmatch(sha256)
                    or track_id != f'sha256:{sha256}'
                    or not isinstance(size, int) or size < 0):
                raise AnalysisError('Unexpected analysis database rows')
        missing_audio = db.execute('SELECT 1 FROM tracks t LEFT JOIN track_audio a ON a.track_id=t.id WHERE a.track_id IS NULL LIMIT 1').fetchone()
        orphan_audio = db.execute('SELECT 1 FROM track_audio a LEFT JOIN tracks t ON t.id=a.track_id WHERE t.id IS NULL LIMIT 1').fetchone()
        if missing_audio or orphan_audio:
            raise AnalysisError('Unexpected analysis database rows')
        for duration, source, status, reason in db.execute('SELECT duration_seconds,duration_source,status,reason FROM track_audio'):
            if isinstance(duration, (int, float)) and not isinstance(duration, bool) and not isfinite(duration):
                raise AnalysisError('Unexpected analysis database rows')
            decision = _duration_decision(duration, source)
            if status != _expected_audio_status(duration, source) or reason != (decision.warning or ''):
                raise AnalysisError('Unexpected analysis database rows')

    def _foreign_keys(self, db, table):
        keys = {}
        for row in db.execute(f'PRAGMA foreign_key_list({table})'):
            keys.setdefault(row[0], [row[2], [], []])
            keys[row[0]][1].append(row[3])
            keys[row[0]][2].append(row[4])
        return tuple(sorted((target, tuple(from_columns), tuple(to_columns))
                            for target, from_columns, to_columns in keys.values()))

    def _unique_indexes(self, db, table):
        indexes = []
        for row in db.execute(f'PRAGMA index_list({table})'):
            if row[2] and row[3] == 'u':
                columns = tuple(info[2] for info in db.execute(f'PRAGMA index_info({row[1]})'))
                indexes.append(columns)
        return tuple(sorted(indexes))
