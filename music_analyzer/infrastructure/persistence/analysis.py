"""Dedicated analysis database, with transactional v0 -> v1 -> v2 -> v3 -> v4 -> v5 migrations.

Existing unrelated schemas are rejected before any persistent pragma or DDL.
Exact-file catalogue identity; each explicit analysis request is still a new run.
"""
from contextlib import contextmanager
from dataclasses import asdict
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from music_analyzer.application.dto.analysis import AnalysisError, AudioSource, StageResult

APPLICATION_ID = 0x4D414E41
_COLUMNS = {
    'runs': ('id', 'location', 'status', 'detail', 'created_at'),
    'stages': ('run_id', 'stage', 'result'),
}
_CATALOGUE_COLUMNS = {
    'tracks': ('id', 'sha256', 'size'),
    'locations': ('path', 'track_id', 'mtime_ns', 'format', 'available'),
    'scan_roots': ('root', 'path'),
}


class SQLiteAnalysisRepository:
    def __init__(self, path: str):
        self._path = Path(path).absolute()
        self._check_path()
        with self._connection() as db:
            db.execute('BEGIN IMMEDIATE')
            identity = db.execute('PRAGMA application_id').fetchone()[0]
            version = db.execute('PRAGMA user_version').fetchone()[0]
            objects = db.execute("SELECT name,type FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall()
            if identity == 0 and version == 0 and not objects:
                db.execute("""CREATE TABLE runs (
                    id TEXT PRIMARY KEY, location TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('running','completed','failed','interrupted')),
                    detail TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
                db.execute("""CREATE TABLE stages (
                    run_id TEXT NOT NULL REFERENCES runs(id), stage TEXT NOT NULL,
                    result TEXT NOT NULL, PRIMARY KEY(run_id,stage))""")
                db.execute(f'PRAGMA application_id={APPLICATION_ID}')
                db.execute('PRAGMA user_version=1')
            elif identity != APPLICATION_ID or version not in (1, 2, 3, 4, 5):
                raise AnalysisError('Not a supported music-analyzer analysis database; use a new dedicated path')
            if db.execute('PRAGMA user_version').fetchone()[0] == 1:
                self._validate(db, 1)
                db.execute('CREATE TABLE tracks(id TEXT PRIMARY KEY, sha256 TEXT NOT NULL UNIQUE, size INTEGER NOT NULL)')
                db.execute('CREATE TABLE locations(path TEXT PRIMARY KEY, track_id TEXT NOT NULL REFERENCES tracks(id), mtime_ns INTEGER NOT NULL, format TEXT NOT NULL, available INTEGER NOT NULL CHECK(available IN (0,1)))')
                db.execute('CREATE TABLE scan_roots(root TEXT NOT NULL, path TEXT NOT NULL REFERENCES locations(path), PRIMARY KEY(root,path))')
                db.execute('PRAGMA user_version=2')
            if db.execute('PRAGMA user_version').fetchone()[0] == 2:
                self._validate(db, 2)
                db.execute("""CREATE TABLE batch_jobs(
                    track_id TEXT PRIMARY KEY REFERENCES tracks(id), fingerprint TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('pending','running','completed','failed')),
                    attempts INTEGER NOT NULL CHECK(attempts >= 0), run_id TEXT, detail TEXT NOT NULL)""")
                db.execute('PRAGMA user_version=3')
            if db.execute('PRAGMA user_version').fetchone()[0] == 3:
                self._validate(db, 3)
                db.execute('CREATE TABLE run_tracks(run_id TEXT PRIMARY KEY REFERENCES runs(id), track_id TEXT NOT NULL REFERENCES tracks(id))')
                db.execute('CREATE TABLE overrides(track_id TEXT NOT NULL REFERENCES tracks(id), field TEXT NOT NULL, value TEXT NOT NULL, PRIMARY KEY(track_id,field))')
                db.execute('PRAGMA user_version=4')
            if db.execute('PRAGMA user_version').fetchone()[0] == 4:
                self._validate(db, 4)
                if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='track_metadata'").fetchone():
                    self._ensure_track_metadata_primary_key(db)
                else:
                    db.execute('CREATE TABLE track_metadata(track_id TEXT PRIMARY KEY REFERENCES tracks(id), common_json TEXT NOT NULL, tags_json TEXT NOT NULL, warnings_json TEXT NOT NULL)')
                db.execute('PRAGMA user_version=5')
            self._validate(db)

    def _check_path(self):
        if self._path.stem.lower() == 'mixxx' or any(p.is_symlink() for p in (self._path, *self._path.parents)):
            raise AnalysisError('Refusing Mixxx-named or symlink database path')

    def _has_single_column_primary_key(self, table_info, column):
        pk_columns = tuple(row[1] for row in sorted((row for row in table_info if row[5]), key=lambda row: row[5]))
        return pk_columns == (column,)

    def _valid_track_metadata_constraints(self, db, table_info):
        return (self._has_single_column_primary_key(table_info, 'track_id')
                and all(row[3] for row in table_info if row[1] in ('common_json', 'tags_json', 'warnings_json'))
                and any(row[2] == 'tracks' and row[3] == 'track_id' and row[4] == 'id'
                        for row in db.execute('PRAGMA foreign_key_list(track_metadata)')))

    def _ensure_track_metadata_primary_key(self, db):
        table_info = tuple(db.execute('PRAGMA table_info(track_metadata)'))
        if self._valid_track_metadata_constraints(db, table_info):
            return
        duplicate = db.execute('SELECT track_id FROM track_metadata GROUP BY track_id HAVING count(*) > 1 LIMIT 1').fetchone()
        if duplicate:
            raise AnalysisError('Duplicate track metadata prevents schema migration')
        db.execute('ALTER TABLE track_metadata RENAME TO track_metadata_v4')
        db.execute('CREATE TABLE track_metadata(track_id TEXT PRIMARY KEY REFERENCES tracks(id), common_json TEXT NOT NULL, tags_json TEXT NOT NULL, warnings_json TEXT NOT NULL)')
        db.execute('INSERT INTO track_metadata(track_id, common_json, tags_json, warnings_json) SELECT track_id, common_json, tags_json, warnings_json FROM track_metadata_v4')
        db.execute('DROP TABLE track_metadata_v4')

    def _validate(self, db, version=5):
        if (db.execute('PRAGMA application_id').fetchone()[0] != APPLICATION_ID
                or db.execute('PRAGMA user_version').fetchone()[0] != version):
            raise AnalysisError('Analysis database identity/version changed')
        columns_by_table = _COLUMNS if version == 1 else {**_COLUMNS, **_CATALOGUE_COLUMNS}
        if version >= 3:
            columns_by_table = {**columns_by_table, 'batch_jobs': ('track_id', 'fingerprint', 'state', 'attempts', 'run_id', 'detail')}
        if version >= 4:
            columns_by_table = {**columns_by_table, 'run_tracks': ('run_id', 'track_id'), 'overrides': ('track_id', 'field', 'value')}
        if version >= 5:
            columns_by_table = {**columns_by_table, 'track_metadata': ('track_id', 'common_json', 'tags_json', 'warnings_json')}
        objects = set(db.execute("SELECT name,type FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"))
        expected = {(name, 'table') for name in columns_by_table}
        if version in (2, 3):
            migration_tables = {'batch_jobs', 'run_tracks', 'overrides', 'track_metadata'} if version == 2 else {'run_tracks', 'overrides', 'track_metadata'}
            expected = {item for item in expected if item[0] not in migration_tables}
            objects = {item for item in objects if item[0] not in migration_tables}
        if version == 4:
            has_track_metadata = ('track_metadata', 'table') in objects
            objects = {item for item in objects if item[0] != 'track_metadata'}
            if has_track_metadata:
                columns_by_table = {**columns_by_table, 'track_metadata': ('track_id', 'common_json', 'tags_json', 'warnings_json')}
        if objects != expected:
            raise AnalysisError('Unexpected analysis database schema')
        for table, columns in columns_by_table.items():
            table_info = tuple(db.execute(f'PRAGMA table_info({table})'))
            if tuple(row[1] for row in table_info) != columns:
                raise AnalysisError('Unexpected analysis database columns')
            if version >= 5 and table == 'track_metadata' and not self._valid_track_metadata_constraints(db, table_info):
                raise AnalysisError('Unexpected analysis database constraints')


    @contextmanager
    def _connection(self):
        self._check_path()
        db = None
        try:
            db = sqlite3.connect(self._path, timeout=5)
            db.execute('PRAGMA foreign_keys=ON')
            with db:
                yield db
        except (sqlite3.Error, OSError) as error:
            raise AnalysisError(f'Analysis database error: {error}') from error
        finally:
            if db is not None:
                db.close()

    @contextmanager
    def _transaction(self):
        with self._connection() as db:
            db.execute('BEGIN IMMEDIATE')
            self._validate(db)
            yield db

    def start(self, source: AudioSource) -> str:
        run_id = str(uuid4())
        with self._transaction() as db:
            db.execute('INSERT INTO runs(id,location,status) VALUES(?,?,?)', (run_id, source.location, 'running'))
            self._link_run(db, run_id, source.expected_identity)
        return run_id

    def save_stage(self, run_id: str, result: StageResult) -> None:
        payload = json.dumps(asdict(result), allow_nan=False, ensure_ascii=False)
        with self._transaction() as db:
            row = db.execute('SELECT status FROM runs WHERE id=?', (run_id,)).fetchone()
            if row != ('running',):
                raise AnalysisError('Stage requires an existing running analysis')
            db.execute('INSERT INTO stages(run_id,stage,result) VALUES(?,?,?)', (run_id, result.stage, payload))

    def finish(self, run_id: str, status: str, detail: str) -> None:
        if status not in {'completed', 'failed', 'interrupted'}:
            raise AnalysisError('Invalid terminal analysis status')
        with self._transaction() as db:
            cursor = db.execute("UPDATE runs SET status=?,detail=? WHERE id=? AND status='running'",
                                (status, detail, run_id))
            if cursor.rowcount != 1:
                raise AnalysisError('Finish requires an existing running analysis')

    def register(self, inventory):
        missing = []
        with self._transaction() as db:
            seen = {file.location for file in inventory.files}
            for file in inventory.files:
                identity = file.identity
                db.execute('INSERT OR IGNORE INTO tracks VALUES(?,?,?)',
                           (identity.track_id, identity.sha256, identity.size))
                db.execute('INSERT INTO locations VALUES(?,?,?,?,1) ON CONFLICT(path) DO UPDATE SET track_id=excluded.track_id,mtime_ns=excluded.mtime_ns,format=excluded.format,available=1',
                           (file.location, identity.track_id, file.mtime_ns, file.format))
                db.execute('INSERT OR IGNORE INTO scan_roots VALUES(?,?)', (inventory.root, file.location))
                db.execute('INSERT INTO track_metadata VALUES(?,?,?,?) ON CONFLICT(track_id) DO UPDATE SET common_json=excluded.common_json,tags_json=excluded.tags_json,warnings_json=excluded.warnings_json',
                           (identity.track_id, json.dumps(file.metadata.common, ensure_ascii=False, allow_nan=False), json.dumps(file.metadata.tags, ensure_ascii=False, allow_nan=False), json.dumps(file.metadata.warnings, ensure_ascii=False, allow_nan=False)))
            if inventory.complete:
                for (path,) in db.execute('SELECT path FROM scan_roots WHERE root=?', (inventory.root,)):
                    if path not in seen:
                        missing.append(path)
                        db.execute('UPDATE locations SET available=0 WHERE path=?', (path,))
        return tuple(sorted(missing))

    def locations(self, track_id):
        with self._transaction() as db:
            return tuple(row[0] for row in db.execute('SELECT path FROM locations WHERE track_id=? AND available=1 ORDER BY path', (track_id,)))

    def _link_run(self, db, run_id, track_id):
        if track_id:
            db.execute('INSERT INTO run_tracks VALUES(?,?)', (run_id, track_id))

    def track_ids(self):
        # Keyset pages: no catalogue-sized materialization or long read transaction.
        after = ''
        while True:
            with self._transaction() as db:
                page = db.execute('SELECT id FROM tracks WHERE id>? ORDER BY id LIMIT 100', (after,)).fetchall()
            if not page: return
            for (track,) in page: yield track
            after = page[-1][0]

    def read_track(self, track_id):
        from music_analyzer.application.dto.analysis import AnalysisReport
        from music_analyzer.application.dto.review import StoredTrack
        from music_analyzer.infrastructure.persistence.stage_mapping import stage_from_mapping
        with self._transaction() as db:
            track = db.execute('SELECT id,sha256,size FROM tracks WHERE id=?', (track_id,)).fetchone()
            if not track: raise AnalysisError('Unknown track ID; scan first')
            locations = tuple(r[0] for r in db.execute('SELECT path FROM locations WHERE track_id=? AND available=1 ORDER BY path', (track_id,)))
            row = db.execute('SELECT r.id,r.status,r.detail FROM runs r JOIN run_tracks t ON t.run_id=r.id WHERE t.track_id=? ORDER BY r.rowid DESC LIMIT 1', (track_id,)).fetchone()
            run = None
            if row:
                stages = []
                for stage, size in db.execute('SELECT stage,length(CAST(result AS BLOB)) FROM stages WHERE run_id=? ORDER BY stage', (row[0],)):
                    if size > 16 * 1024 * 1024: raise AnalysisError('Oversized stored stage (16 MiB limit)')
                    payload = db.execute('SELECT result FROM stages WHERE run_id=? AND stage=?', (row[0], stage)).fetchone()[0]
                    try:
                        result = stage_from_mapping(json.loads(payload))
                        if result.stage != stage: raise ValueError('Stage name mismatch')
                        stages.append(result)
                    except (ValueError, KeyError, TypeError, IndexError) as error:
                        raise AnalysisError('Invalid stored stage: ' + str(error)) from error
                run = AnalysisReport(row[0], row[1], tuple(stages), row[2])
            overrides = tuple(db.execute('SELECT field,value FROM overrides WHERE track_id=? ORDER BY field', (track_id,)))
            metadata = self._read_metadata(db, track_id)
            return StoredTrack(*track, locations, run, overrides, metadata)

    def _read_metadata(self, db, track_id):
        from music_analyzer.application.dto.catalogue import TrackMetadata
        row = db.execute('SELECT common_json,tags_json,warnings_json FROM track_metadata WHERE track_id=?', (track_id,)).fetchone()
        if not row:
            return TrackMetadata()
        try:
            return TrackMetadata(tuple((str(k), tuple(v) if isinstance(v, list) else str(v)) for k, v in json.loads(row[0])), tuple((str(k), tuple(str(x) for x in v)) for k, v in json.loads(row[1])), tuple(str(x) for x in json.loads(row[2])))
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise AnalysisError('Invalid stored metadata') from error

    def set_override(self, track_id, field, value):
        with self._transaction() as db:
            if not db.execute('SELECT 1 FROM tracks WHERE id=?', (track_id,)).fetchone():
                raise AnalysisError('Unknown track ID; scan first')
            if value is None:
                db.execute('DELETE FROM overrides WHERE track_id=? AND field=?', (track_id, field))
            else:
                db.execute('INSERT INTO overrides VALUES(?,?,?) ON CONFLICT(track_id,field) DO UPDATE SET value=excluded.value', (track_id, field, value))
