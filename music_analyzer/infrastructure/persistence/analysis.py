"""Dedicated analysis database, with transactional v0 -> v1 -> v2 migrations.

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
            elif identity != APPLICATION_ID or version not in (1, 2):
                raise AnalysisError('Not a supported music-analyzer analysis database; use a new dedicated path')
            if db.execute('PRAGMA user_version').fetchone()[0] == 1:
                self._validate(db, 1)
                db.execute('CREATE TABLE tracks(id TEXT PRIMARY KEY, sha256 TEXT NOT NULL UNIQUE, size INTEGER NOT NULL)')
                db.execute('CREATE TABLE locations(path TEXT PRIMARY KEY, track_id TEXT NOT NULL REFERENCES tracks(id), mtime_ns INTEGER NOT NULL, format TEXT NOT NULL, available INTEGER NOT NULL CHECK(available IN (0,1)))')
                db.execute('CREATE TABLE scan_roots(root TEXT NOT NULL, path TEXT NOT NULL REFERENCES locations(path), PRIMARY KEY(root,path))')
                db.execute('PRAGMA user_version=2')
            self._validate(db)

    def _check_path(self):
        if self._path.stem.lower() == 'mixxx' or any(p.is_symlink() for p in (self._path, *self._path.parents)):
            raise AnalysisError('Refusing Mixxx-named or symlink database path')

    def _validate(self, db, version=2):
        if (db.execute('PRAGMA application_id').fetchone()[0] != APPLICATION_ID
                or db.execute('PRAGMA user_version').fetchone()[0] != version):
            raise AnalysisError('Analysis database identity/version changed')
        columns_by_table = _COLUMNS if version == 1 else {**_COLUMNS, **_CATALOGUE_COLUMNS}
        objects = set(db.execute("SELECT name,type FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"))
        if objects != {(name, 'table') for name in columns_by_table}:
            raise AnalysisError('Unexpected analysis database schema')
        for table, columns in columns_by_table.items():
            if tuple(row[1] for row in db.execute(f'PRAGMA table_info({table})')) != columns:
                raise AnalysisError('Unexpected analysis database columns')

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
            if inventory.complete:
                for (path,) in db.execute('SELECT path FROM scan_roots WHERE root=?', (inventory.root,)):
                    if path not in seen:
                        missing.append(path)
                        db.execute('UPDATE locations SET available=0 WHERE path=?', (path,))
        return tuple(sorted(missing))

    def locations(self, track_id):
        with self._transaction() as db:
            return tuple(row[0] for row in db.execute('SELECT path FROM locations WHERE track_id=? AND available=1 ORDER BY path', (track_id,)))
