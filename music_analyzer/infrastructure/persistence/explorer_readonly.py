"""Read-only SQLite explorer adapter.

Uses bounded read transactions against the selected live analysis database.  The
adapter opens SQLite with ``mode=ro`` so committed WAL frames are visible, avoids
``immutable=1``, enables ``query_only`` defense, and never creates or migrates
schemas.
"""
from contextlib import contextmanager
import json
from pathlib import Path
import re
import sqlite3

from music_analyzer.application.dto.analysis import AnalysisError, AnalysisReport
from music_analyzer.application.dto.catalogue import TrackMetadata
from music_analyzer.application.dto.explorer import ExplorerStoredTrack
from music_analyzer.infrastructure.persistence.analysis import APPLICATION_ID
from music_analyzer.infrastructure.persistence.stage_mapping import stage_from_mapping

_SHA256_RE = re.compile(r'^[0-9a-f]{64}$')
_TRACK_ID_RE = re.compile(r'^sha256:[0-9a-f]{64}$')

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
            track_count = db.execute(f'SELECT count(*) FROM tracks {where}', params).fetchone()[0]
            ids = tuple(row[0] for row in db.execute(f'SELECT id FROM tracks {where} ORDER BY id LIMIT ?', (*params, limit)))
            return metadata, track_count, tuple(self._read_track(db, track_id) for track_id in ids)

    def candidate_snapshot(self):
        with self._transaction() as db:
            metadata = self._metadata(db)
            ids = tuple(row[0] for row in db.execute('SELECT id FROM tracks ORDER BY id'))
            return metadata, tuple(self._read_track(db, track_id) for track_id in ids)

    def track_ids(self):
        with self._transaction() as db:
            return tuple(row[0] for row in db.execute('SELECT id FROM tracks ORDER BY id'))

    def available_audio_paths(self):
        with self._transaction() as db:
            return tuple(row[0] for row in db.execute('SELECT path FROM locations WHERE available=1 ORDER BY path'))

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

    def _read_metadata(self, db, track_id):
        row = db.execute('SELECT common_json,tags_json,warnings_json FROM track_metadata WHERE track_id=?', (track_id,)).fetchone()
        if not row:
            return TrackMetadata()
        try:
            return TrackMetadata(tuple((str(k), tuple(v) if isinstance(v, list) else str(v)) for k, v in json.loads(row[0])), tuple((str(k), tuple(str(x) for x in v)) for k, v in json.loads(row[1])), tuple(str(x) for x in json.loads(row[2])))
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
                or db.execute('PRAGMA user_version').fetchone()[0] != 5):
            raise AnalysisError('Not a supported music-analyzer analysis database')
        objects = set(db.execute("SELECT name,type FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"))
        if objects != {(name, 'table') for name in _EXPECTED_SCHEMA}:
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
