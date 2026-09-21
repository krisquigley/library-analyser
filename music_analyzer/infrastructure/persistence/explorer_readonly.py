"""Read-only SQLite explorer adapter.

Uses bounded read transactions against the selected live analysis database.  The
adapter opens SQLite with ``mode=ro`` so committed WAL frames are visible, avoids
``immutable=1``, enables ``query_only`` defense, and never creates or migrates
schemas.
"""
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3

from music_analyzer.application.dto.analysis import AnalysisError, AnalysisReport
from music_analyzer.application.dto.explorer import ExplorerStoredTrack
from music_analyzer.infrastructure.persistence.analysis import APPLICATION_ID
from music_analyzer.infrastructure.persistence.stage_mapping import stage_from_mapping

_EXPECTED_COLUMNS = {
    'runs': ('id', 'location', 'status', 'detail', 'created_at'),
    'stages': ('run_id', 'stage', 'result'),
    'tracks': ('id', 'sha256', 'size'),
    'locations': ('path', 'track_id', 'mtime_ns', 'format', 'available'),
    'scan_roots': ('root', 'path'),
    'batch_jobs': ('track_id', 'fingerprint', 'state', 'attempts', 'run_id', 'detail'),
    'run_tracks': ('run_id', 'track_id'),
    'overrides': ('track_id', 'field', 'value'),
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

    def track_ids(self):
        with self._transaction() as db:
            return tuple(row[0] for row in db.execute('SELECT id FROM tracks ORDER BY id'))

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
        return ExplorerStoredTrack(track[0], track[1], track[2], display_label, len(locations), run, overrides)

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
                or db.execute('PRAGMA user_version').fetchone()[0] != 4):
            raise AnalysisError('Not a supported music-analyzer analysis database')
        objects = set(db.execute("SELECT name,type FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"))
        if objects != {(name, 'table') for name in _EXPECTED_COLUMNS}:
            raise AnalysisError('Unexpected analysis database schema')
        for table, columns in _EXPECTED_COLUMNS.items():
            actual = tuple(row[1] for row in db.execute(f'PRAGMA table_info({table})'))
            if actual != columns:
                raise AnalysisError('Unexpected analysis database columns')
