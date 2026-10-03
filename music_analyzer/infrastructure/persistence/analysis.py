"""Dedicated analysis database, with transactional v0 -> v1 -> ... -> v9 migrations.

Existing unrelated schemas are rejected before any persistent pragma or DDL.
Exact-file catalogue identity; each explicit analysis request is still a new run.
"""
from contextlib import contextmanager
from dataclasses import asdict
import json
from math import isfinite
from pathlib import Path
import sqlite3
from uuid import uuid4

from music_analyzer.application.dto.analysis import AnalysisError, AudioSource, StageResult
from music_analyzer.application.use_cases.graph_feature_evidence import build_graph_feature_evidence
from music_analyzer.domain.projection import DISTANCE_POLICY_VERSION, NEIGHBOUR_POLICY_VERSION
from music_analyzer.domain.library_duration_policy import (
    DurationVerification,
    TRUSTED_DURATION_SOURCES,
    UNKNOWN_DURATION_REASON,
    active_library_duration_policy,
)


def _normalized_sqlite_duration(duration_seconds):
    if isinstance(duration_seconds, (int, float)) and not isinstance(duration_seconds, bool) and not isfinite(duration_seconds):
        return None
    return duration_seconds


def _duration_decision(duration_seconds, source=''):
    return active_library_duration_policy(DurationVerification(duration_seconds, source) if source else None)


def _duration_eligibility_reason(duration_seconds, source=''):
    return _duration_decision(duration_seconds, source).warning or ''


def _duration_status(duration_seconds, source=''):
    decision = _duration_decision(duration_seconds, source)
    if decision.active:
        return 'eligible'
    if source in TRUSTED_DURATION_SOURCES and duration_seconds is not None:
        return 'excluded'
    return 'unknown'


def _trusted_duration_evidence(duration_seconds, source):
    if source not in TRUSTED_DURATION_SOURCES or duration_seconds is None:
        return None
    if isinstance(duration_seconds, bool):
        return ('invalid', None, source)
    try:
        seconds = float(duration_seconds)
    except (TypeError, ValueError):
        return ('invalid', None, source)
    if isfinite(seconds) and seconds > 0:
        return ('measured', seconds, source)
    return ('invalid', None, source)


def _coalesced_duration(file, files, stored_audio=None):
    same_identity = tuple(candidate for candidate in files if candidate.identity.track_id == file.identity.track_id)
    trusted = []
    invalid_trusted = False
    if stored_audio is not None:
        duration, source = stored_audio
        evidence = _trusted_duration_evidence(duration, source)
        if evidence:
            kind, seconds, evidence_source = evidence
            if kind == 'measured':
                trusted.append((seconds, evidence_source))
            else:
                invalid_trusted = True
    for candidate in same_identity:
        source = getattr(candidate.metadata, 'duration_source', '')
        seconds = candidate.metadata.duration_seconds
        evidence = _trusted_duration_evidence(seconds, source)
        if evidence:
            kind, measured_seconds, evidence_source = evidence
            if kind == 'measured':
                trusted.append((measured_seconds, evidence_source))
            else:
                invalid_trusted = True
    distinct = {seconds for seconds, _source in trusted}
    if len(distinct) > 1 or (invalid_trusted and trusted):
        raise AnalysisError('Conflicting trusted duration measurements for duplicate track identity; scan again')
    if trusted:
        seconds, source = sorted(trusted, key=lambda item: (item[0], item[1]))[0]
        return seconds, source
    return file.metadata.duration_seconds, getattr(file.metadata, 'duration_source', '')


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
_AUDIO_ELIGIBILITY_COLUMNS = {'track_audio': ('track_id', 'duration_seconds', 'duration_source', 'status', 'reason')}
_ACTIVE_VIEWS = {
    'active_tracks': "CREATE VIEW active_tracks AS SELECT t.id,t.sha256,t.size FROM tracks t JOIN track_audio a ON a.track_id=t.id WHERE a.status='eligible'",
    'active_locations': "CREATE VIEW active_locations AS SELECT l.path,l.track_id,l.mtime_ns,l.format,l.available FROM locations l JOIN track_audio a ON a.track_id=l.track_id WHERE l.available=1 AND a.status='eligible'",
}
_GRAPH_COLUMNS = {
    'graph_edges': ('source_track_id', 'target_track_id', 'score', 'distance', 'supported_group_count', 'distance_policy_version', 'neighbour_policy_version', 'built_at'),
    'graph_builds': ('id', 'status', 'detail', 'edge_count', 'sparse_k', 'source_fingerprint', 'distance_policy_version', 'neighbour_policy_version', 'is_current', 'created_at', 'completed_at'),
    'graph_build_edges': ('build_id', 'source_track_id', 'target_track_id', 'score', 'distance', 'supported_group_count', 'distance_policy_version', 'neighbour_policy_version', 'built_at'),
}
_POSITIONED_GRAPH_COLUMNS = {
    'graph_positioned_edges': ('source_track_id', 'target_track_id', 'score', 'distance', 'supported_group_count', 'distance_policy_version', 'neighbour_policy_version', 'built_at'),
    'graph_build_positioned_edges': ('build_id', 'source_track_id', 'target_track_id', 'score', 'distance', 'supported_group_count', 'distance_policy_version', 'neighbour_policy_version', 'built_at'),
    'graph_build_positioned_snapshots': ('build_id', 'edge_count', 'built_at'),
}
_GRAPH_FEATURE_COLUMNS = {
    'graph_feature_evidence': ('track_id', 'run_id', 'fingerprint', 'evidence_json', 'is_current', 'created_at'),
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
            elif identity != APPLICATION_ID or version not in (1, 2, 3, 4, 5, 6, 7, 8, 9):
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
            if db.execute('PRAGMA user_version').fetchone()[0] == 5:
                self._validate(db, 5)
                db.execute("""CREATE TABLE track_audio(
                    track_id TEXT PRIMARY KEY REFERENCES tracks(id),
                    duration_seconds REAL,
                    duration_source TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('eligible','excluded','unknown')),
                    reason TEXT NOT NULL)""")
                db.execute("INSERT INTO track_audio(track_id,duration_seconds,duration_source,status,reason) SELECT id,NULL,'','unknown',? FROM tracks", (UNKNOWN_DURATION_REASON,))
                for sql in _ACTIVE_VIEWS.values():
                    db.execute(sql)
                db.execute('PRAGMA user_version=6')
            if db.execute('PRAGMA user_version').fetchone()[0] == 6:
                self._validate(db, 6)
                self._drop_graph_schema(db)
                self._create_graph_schema(db)
                db.execute('PRAGMA user_version=7')
            if db.execute('PRAGMA user_version').fetchone()[0] == 7:
                self._validate(db, 7)
                self._create_positioned_graph_schema(db)
                db.execute('PRAGMA user_version=8')
            if db.execute('PRAGMA user_version').fetchone()[0] == 8:
                self._validate(db, 8)
                self._create_graph_feature_schema(db)
                db.execute('PRAGMA user_version=9')
            self._validate(db, 9)

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

    def _drop_graph_schema(self, db):
        for name in (
                'idx_graph_build_positioned_edges_target_track_id', 'idx_graph_build_positioned_edges_source_track_id',
                'idx_graph_build_positioned_edges_build_id', 'idx_graph_positioned_edges_target_track_id',
                'idx_graph_positioned_edges_source_track_id', 'idx_graph_build_edges_target_track_id', 'idx_graph_build_edges_source_track_id',
                'idx_graph_build_edges_build_id', 'idx_graph_edges_target_track_id',
                'idx_graph_edges_source_track_id', 'idx_graph_feature_evidence_one_current_per_track',
                'idx_graph_feature_evidence_run_id', 'idx_graph_builds_one_current'):
            db.execute(f'DROP INDEX IF EXISTS {name}')
        for name in ('graph_feature_evidence', 'graph_build_positioned_snapshots', 'graph_build_positioned_edges', 'graph_positioned_edges', 'graph_build_edges', 'graph_edges', 'graph_builds'):
            db.execute(f'DROP TABLE IF EXISTS {name}')

    def _create_graph_schema(self, db):
        db.execute("""CREATE TABLE graph_builds(
            id TEXT PRIMARY KEY,
            status TEXT NOT NULL CHECK(status IN ('completed','failed')),
            detail TEXT NOT NULL,
            edge_count INTEGER NOT NULL CHECK(edge_count >= 0),
            sparse_k INTEGER NOT NULL CHECK(sparse_k >= 0),
            source_fingerprint TEXT NOT NULL,
            distance_policy_version TEXT NOT NULL,
            neighbour_policy_version TEXT NOT NULL,
            is_current INTEGER NOT NULL CHECK(is_current IN (0,1)),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            completed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CHECK(status = 'completed' OR is_current = 0))""")
        db.execute("""CREATE UNIQUE INDEX idx_graph_builds_one_current
                   ON graph_builds(is_current) WHERE is_current = 1""")
        db.execute("""CREATE TABLE graph_edges(
            source_track_id TEXT NOT NULL REFERENCES tracks(id),
            target_track_id TEXT NOT NULL REFERENCES tracks(id),
            score REAL NOT NULL CHECK(score >= 0.0 AND score <= 1.0),
            distance REAL NOT NULL CHECK(distance >= 0.0 AND distance <= 1.0),
            supported_group_count INTEGER NOT NULL CHECK(supported_group_count > 0),
            distance_policy_version TEXT NOT NULL,
            neighbour_policy_version TEXT NOT NULL,
            built_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(source_track_id,target_track_id),
            CHECK(source_track_id < target_track_id))""")
        db.execute('CREATE INDEX idx_graph_edges_source_track_id ON graph_edges(source_track_id)')
        db.execute('CREATE INDEX idx_graph_edges_target_track_id ON graph_edges(target_track_id)')
        db.execute("""CREATE TABLE graph_build_edges(
            build_id TEXT NOT NULL REFERENCES graph_builds(id) ON DELETE CASCADE,
            source_track_id TEXT NOT NULL REFERENCES tracks(id),
            target_track_id TEXT NOT NULL REFERENCES tracks(id),
            score REAL NOT NULL CHECK(score >= 0.0 AND score <= 1.0),
            distance REAL NOT NULL CHECK(distance >= 0.0 AND distance <= 1.0),
            supported_group_count INTEGER NOT NULL CHECK(supported_group_count > 0),
            distance_policy_version TEXT NOT NULL,
            neighbour_policy_version TEXT NOT NULL,
            built_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(build_id,source_track_id,target_track_id),
            CHECK(source_track_id < target_track_id))""")
        db.execute('CREATE INDEX idx_graph_build_edges_build_id ON graph_build_edges(build_id)')
        db.execute('CREATE INDEX idx_graph_build_edges_source_track_id ON graph_build_edges(build_id,source_track_id)')
        db.execute('CREATE INDEX idx_graph_build_edges_target_track_id ON graph_build_edges(build_id,target_track_id)')

    def _create_graph_feature_schema(self, db):
        db.execute("""CREATE TABLE graph_feature_evidence(
            track_id TEXT NOT NULL REFERENCES tracks(id),
            run_id TEXT NOT NULL REFERENCES runs(id),
            fingerprint TEXT NOT NULL,
            evidence_json TEXT NOT NULL,
            is_current INTEGER NOT NULL CHECK(is_current IN (0,1)),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(track_id,run_id))""")
        db.execute("""CREATE UNIQUE INDEX idx_graph_feature_evidence_one_current_per_track
                   ON graph_feature_evidence(track_id) WHERE is_current = 1""")
        db.execute('CREATE INDEX idx_graph_feature_evidence_run_id ON graph_feature_evidence(run_id)')

    def _create_positioned_graph_schema(self, db):
        db.execute("""CREATE TABLE graph_positioned_edges(
            source_track_id TEXT NOT NULL REFERENCES tracks(id),
            target_track_id TEXT NOT NULL REFERENCES tracks(id),
            score REAL NOT NULL CHECK(score >= 0.0 AND score <= 1.0),
            distance REAL NOT NULL CHECK(distance >= 0.0 AND distance <= 1.0),
            supported_group_count INTEGER NOT NULL CHECK(supported_group_count > 0),
            distance_policy_version TEXT NOT NULL,
            neighbour_policy_version TEXT NOT NULL,
            built_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(source_track_id,target_track_id),
            CHECK(source_track_id < target_track_id))""")
        db.execute('CREATE INDEX idx_graph_positioned_edges_source_track_id ON graph_positioned_edges(source_track_id)')
        db.execute('CREATE INDEX idx_graph_positioned_edges_target_track_id ON graph_positioned_edges(target_track_id)')
        db.execute("""CREATE TABLE graph_build_positioned_edges(
            build_id TEXT NOT NULL REFERENCES graph_builds(id) ON DELETE CASCADE,
            source_track_id TEXT NOT NULL REFERENCES tracks(id),
            target_track_id TEXT NOT NULL REFERENCES tracks(id),
            score REAL NOT NULL CHECK(score >= 0.0 AND score <= 1.0),
            distance REAL NOT NULL CHECK(distance >= 0.0 AND distance <= 1.0),
            supported_group_count INTEGER NOT NULL CHECK(supported_group_count > 0),
            distance_policy_version TEXT NOT NULL,
            neighbour_policy_version TEXT NOT NULL,
            built_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(build_id,source_track_id,target_track_id),
            CHECK(source_track_id < target_track_id))""")
        db.execute('CREATE INDEX idx_graph_build_positioned_edges_build_id ON graph_build_positioned_edges(build_id)')
        db.execute('CREATE INDEX idx_graph_build_positioned_edges_source_track_id ON graph_build_positioned_edges(build_id,source_track_id)')
        db.execute('CREATE INDEX idx_graph_build_positioned_edges_target_track_id ON graph_build_positioned_edges(build_id,target_track_id)')
        db.execute("""CREATE TABLE graph_build_positioned_snapshots(
            build_id TEXT PRIMARY KEY REFERENCES graph_builds(id) ON DELETE CASCADE,
            edge_count INTEGER NOT NULL CHECK(edge_count >= 0),
            built_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")

    def _validate(self, db, version=9):
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
        if version >= 6:
            columns_by_table = {**columns_by_table, **_AUDIO_ELIGIBILITY_COLUMNS}
        if version >= 7:
            columns_by_table = {**columns_by_table, **_GRAPH_COLUMNS}
        if version >= 8:
            columns_by_table = {**columns_by_table, **_POSITIONED_GRAPH_COLUMNS}
        if version >= 9:
            columns_by_table = {**columns_by_table, **_GRAPH_FEATURE_COLUMNS}
        objects = set(db.execute("SELECT name,type FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"))
        expected = {(name, 'table') for name in columns_by_table}
        if version >= 6:
            expected |= {(name, 'view') for name in _ACTIVE_VIEWS}
        if version >= 7:
            expected |= {('idx_graph_edges_source_track_id', 'index'), ('idx_graph_edges_target_track_id', 'index'), ('idx_graph_build_edges_build_id', 'index'), ('idx_graph_build_edges_source_track_id', 'index'), ('idx_graph_build_edges_target_track_id', 'index'), ('idx_graph_builds_one_current', 'index')}
        if version >= 8:
            expected |= {('idx_graph_positioned_edges_source_track_id', 'index'), ('idx_graph_positioned_edges_target_track_id', 'index'), ('idx_graph_build_positioned_edges_build_id', 'index'), ('idx_graph_build_positioned_edges_source_track_id', 'index'), ('idx_graph_build_positioned_edges_target_track_id', 'index')}
        if version >= 9:
            expected |= {('idx_graph_feature_evidence_one_current_per_track', 'index'), ('idx_graph_feature_evidence_run_id', 'index')}
        if version in (2, 3):
            migration_tables = {'batch_jobs', 'run_tracks', 'overrides', 'track_metadata'} if version == 2 else {'run_tracks', 'overrides', 'track_metadata'}
            expected = {item for item in expected if item[0] not in migration_tables}
            objects = {item for item in objects if item[0] not in migration_tables}
        if version < 7:
            graph_objects = {
                'graph_edges', 'graph_builds', 'graph_build_edges', 'graph_positioned_edges', 'graph_build_positioned_edges', 'graph_build_positioned_snapshots',
                'graph_feature_evidence',
                'idx_graph_edges_source_track_id', 'idx_graph_edges_target_track_id',
                'idx_graph_build_edges_build_id', 'idx_graph_build_edges_source_track_id',
                'idx_graph_build_edges_target_track_id', 'idx_graph_builds_one_current',
                'idx_graph_positioned_edges_source_track_id', 'idx_graph_positioned_edges_target_track_id',
                'idx_graph_build_positioned_edges_build_id', 'idx_graph_build_positioned_edges_source_track_id',
                'idx_graph_build_positioned_edges_target_track_id',
                'idx_graph_feature_evidence_one_current_per_track', 'idx_graph_feature_evidence_run_id',
            }
            objects = {item for item in objects if item[0] not in graph_objects}
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
            if version >= 6 and table == 'track_audio':
                if not self._has_single_column_primary_key(table_info, 'track_id'):
                    raise AnalysisError('Unexpected analysis database constraints')
                sql = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='track_audio'").fetchone()[0]
                if "CHECK(status IN ('eligible','excluded','unknown'))" not in ' '.join(sql.split()):
                    raise AnalysisError('Unexpected analysis database constraints')
                if not any(row[2] == 'tracks' and row[3] == 'track_id' and row[4] == 'id'
                           for row in db.execute('PRAGMA foreign_key_list(track_audio)')):
                    raise AnalysisError('Unexpected analysis database constraints')
            if version >= 7 and table in ('graph_edges', 'graph_positioned_edges'):
                sql = ' '.join(db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()[0].split())
                for fragment in (
                    'PRIMARY KEY(source_track_id,target_track_id)',
                    'CHECK(source_track_id < target_track_id)',
                    'CHECK(score >= 0.0 AND score <= 1.0)',
                    'CHECK(distance >= 0.0 AND distance <= 1.0)',
                ):
                    if fragment not in sql:
                        raise AnalysisError('Unexpected analysis database constraints')
                foreign_keys = tuple((row[3], row[2], row[4]) for row in db.execute(f'PRAGMA foreign_key_list({table})'))
                if (('source_track_id', 'tracks', 'id') not in foreign_keys
                        or ('target_track_id', 'tracks', 'id') not in foreign_keys):
                    raise AnalysisError('Unexpected analysis database constraints')
            if version >= 7 and table in ('graph_build_edges', 'graph_build_positioned_edges'):
                sql = ' '.join(db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()[0].split())
                primary_key = 'PRIMARY KEY(build_id,source_track_id,target_track_id)'
                for fragment in (
                    primary_key,
                    'CHECK(source_track_id < target_track_id)',
                    'CHECK(score >= 0.0 AND score <= 1.0)',
                    'CHECK(distance >= 0.0 AND distance <= 1.0)',
                ):
                    if fragment not in sql:
                        raise AnalysisError('Unexpected analysis database constraints')
                foreign_keys = tuple((row[3], row[2], row[4]) for row in db.execute(f'PRAGMA foreign_key_list({table})'))
                if (('source_track_id', 'tracks', 'id') not in foreign_keys
                        or ('target_track_id', 'tracks', 'id') not in foreign_keys
                        or ('build_id', 'graph_builds', 'id') not in foreign_keys):
                    raise AnalysisError('Unexpected analysis database constraints')
            if version >= 7 and table == 'graph_builds':
                sql = ' '.join(db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='graph_builds'").fetchone()[0].split())
                if ("CHECK(status IN ('completed','failed'))" not in sql
                        or 'CHECK(is_current IN (0,1))' not in sql
                        or "CHECK(status = 'completed' OR is_current = 0)" not in sql):
                    raise AnalysisError('Unexpected analysis database constraints')
            if version >= 9 and table == 'graph_feature_evidence':
                sql = ' '.join(db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='graph_feature_evidence'").fetchone()[0].split())
                if ('PRIMARY KEY(track_id,run_id)' not in sql
                        or 'CHECK(is_current IN (0,1))' not in sql):
                    raise AnalysisError('Unexpected analysis database constraints')
                foreign_keys = tuple((row[3], row[2], row[4]) for row in db.execute('PRAGMA foreign_key_list(graph_feature_evidence)'))
                if (('track_id', 'tracks', 'id') not in foreign_keys
                        or ('run_id', 'runs', 'id') not in foreign_keys):
                    raise AnalysisError('Unexpected analysis database constraints')
        if version >= 6:
            self._validate_track_audio_rows(db)
        if version >= 7:
            self._validate_graph_rows(db)
        if version >= 9:
            self._validate_graph_feature_rows(db)

    def _validate_track_audio_rows(self, db):
        if db.execute('SELECT 1 FROM tracks t LEFT JOIN track_audio a ON a.track_id=t.id WHERE a.track_id IS NULL LIMIT 1').fetchone():
            raise AnalysisError('Unexpected analysis database rows')
        if db.execute('SELECT 1 FROM track_audio a LEFT JOIN tracks t ON t.id=a.track_id WHERE t.id IS NULL LIMIT 1').fetchone():
            raise AnalysisError('Unexpected analysis database rows')
        for track_id, duration, source, status, reason in db.execute('SELECT track_id,duration_seconds,duration_source,status,reason FROM track_audio'):
            if isinstance(duration, (int, float)) and not isinstance(duration, bool) and not isfinite(duration):
                raise AnalysisError('Unexpected analysis database rows')
            expected_reason = _duration_eligibility_reason(duration, source)
            expected_status = _duration_status(duration, source)
            if status != expected_status or reason != expected_reason:
                raise AnalysisError('Unexpected analysis database rows')

    def _validate_graph_rows(self, db):
        current_count = db.execute('SELECT count(*) FROM graph_builds WHERE is_current=1').fetchone()[0]
        if current_count > 1:
            raise AnalysisError('Unexpected analysis database rows')
        for build_id, status, edge_count, sparse_k, source_fingerprint, distance_policy, neighbour_policy, is_current in db.execute(
                'SELECT id,status,edge_count,sparse_k,source_fingerprint,distance_policy_version,neighbour_policy_version,is_current FROM graph_builds'):
            actual_edge_count = db.execute('SELECT count(*) FROM graph_build_edges WHERE build_id=?', (build_id,)).fetchone()[0]
            if (status not in {'completed', 'failed'}
                    or not isinstance(edge_count, int) or edge_count < 0
                    or not isinstance(sparse_k, int) or sparse_k < 0
                    or not isinstance(source_fingerprint, str) or not source_fingerprint
                    or not isinstance(distance_policy, str) or not distance_policy
                    or not isinstance(neighbour_policy, str) or not neighbour_policy
                    or is_current not in (0, 1)
                    or (status != 'completed' and is_current)
                    or (status == 'completed' and edge_count != actual_edge_count)
                    or (status == 'failed' and actual_edge_count != 0)):
                raise AnalysisError('Unexpected analysis database rows')
        current_build = db.execute('SELECT id FROM graph_builds WHERE is_current=1').fetchone()
        if current_build is None and db.execute('SELECT 1 FROM graph_edges LIMIT 1').fetchone():
            raise AnalysisError('Unexpected analysis database rows')
        if (current_build is None and db.execute('PRAGMA user_version').fetchone()[0] >= 8
                and db.execute('SELECT 1 FROM graph_positioned_edges LIMIT 1').fetchone()):
            raise AnalysisError('Unexpected analysis database rows')
        if db.execute('PRAGMA user_version').fetchone()[0] >= 8:
            for build_id, edge_count in db.execute('SELECT build_id,edge_count FROM graph_build_positioned_snapshots'):
                actual_positioned_count = db.execute('SELECT count(*) FROM graph_build_positioned_edges WHERE build_id=?', (build_id,)).fetchone()[0]
                if not isinstance(edge_count, int) or edge_count < 0 or edge_count != actual_positioned_count:
                    raise AnalysisError('Unexpected analysis database rows')
        if current_build is not None:
            current_edges = tuple(db.execute('''
                SELECT source_track_id,target_track_id,score,distance,supported_group_count,
                       distance_policy_version,neighbour_policy_version
                FROM graph_edges ORDER BY source_track_id,target_track_id'''))
            historical_current_edges = tuple(db.execute('''
                SELECT source_track_id,target_track_id,score,distance,supported_group_count,
                       distance_policy_version,neighbour_policy_version
                FROM graph_build_edges WHERE build_id=? ORDER BY source_track_id,target_track_id''', current_build))
            if current_edges != historical_current_edges:
                raise AnalysisError('Unexpected analysis database rows')
            if db.execute('PRAGMA user_version').fetchone()[0] >= 8:
                current_positioned_edges = tuple(db.execute('''
                    SELECT source_track_id,target_track_id,score,distance,supported_group_count,
                           distance_policy_version,neighbour_policy_version
                    FROM graph_positioned_edges ORDER BY source_track_id,target_track_id'''))
                historical_current_positioned_edges = tuple(db.execute('''
                    SELECT source_track_id,target_track_id,score,distance,supported_group_count,
                           distance_policy_version,neighbour_policy_version
                    FROM graph_build_positioned_edges WHERE build_id=? ORDER BY source_track_id,target_track_id''', current_build))
                if current_positioned_edges != historical_current_positioned_edges:
                    raise AnalysisError('Unexpected analysis database rows')
        edge_sources_sql = '''
                SELECT source_track_id,target_track_id,score,distance,supported_group_count,distance_policy_version,neighbour_policy_version FROM graph_edges
                UNION ALL
                SELECT source_track_id,target_track_id,score,distance,supported_group_count,distance_policy_version,neighbour_policy_version FROM graph_build_edges'''
        if db.execute('PRAGMA user_version').fetchone()[0] >= 8:
            edge_sources_sql += '''
                UNION ALL
                SELECT source_track_id,target_track_id,score,distance,supported_group_count,distance_policy_version,neighbour_policy_version FROM graph_positioned_edges
                UNION ALL
                SELECT source_track_id,target_track_id,score,distance,supported_group_count,distance_policy_version,neighbour_policy_version FROM graph_build_positioned_edges'''
        for source, target, score, distance, count, distance_policy, neighbour_policy in db.execute(edge_sources_sql):
            if (not isinstance(source, str) or not isinstance(target, str) or source >= target
                    or not isinstance(score, (int, float)) or not 0.0 <= float(score) <= 1.0
                    or not isinstance(distance, (int, float)) or not 0.0 <= float(distance) <= 1.0
                    or round(1.0 - float(distance), 6) != round(float(score), 6)
                    or not isinstance(count, int) or count <= 0
                    or not isinstance(distance_policy, str) or not distance_policy
                    or not isinstance(neighbour_policy, str) or not neighbour_policy):
                raise AnalysisError('Unexpected analysis database rows')

    def _validate_graph_feature_rows(self, db):
        for track_id, run_id, fingerprint, evidence_json, is_current in db.execute(
                'SELECT track_id,run_id,fingerprint,evidence_json,is_current FROM graph_feature_evidence'):
            if (not isinstance(track_id, str) or not track_id
                    or not isinstance(run_id, str) or not run_id
                    or not isinstance(fingerprint, str) or len(fingerprint) != 64
                    or any(ch not in '0123456789abcdef' for ch in fingerprint)
                    or is_current not in (0, 1)):
                raise AnalysisError('Unexpected analysis database rows')
            run = db.execute('SELECT status FROM runs WHERE id=?', (run_id,)).fetchone()
            if run != ('completed',):
                raise AnalysisError('Unexpected analysis database rows')
            linked = db.execute('SELECT 1 FROM run_tracks WHERE run_id=? AND track_id=?', (run_id, track_id)).fetchone()
            if not linked:
                raise AnalysisError('Unexpected analysis database rows')
            if is_current:
                latest = db.execute('''
                    SELECT r.id,r.status FROM runs r JOIN run_tracks t ON t.run_id=r.id
                    WHERE t.track_id=? ORDER BY r.rowid DESC LIMIT 1''', (track_id,)).fetchone()
                if latest != (run_id, 'completed'):
                    raise AnalysisError('Unexpected analysis database rows')
            try:
                payload = json.loads(evidence_json)
            except (TypeError, ValueError, json.JSONDecodeError) as error:
                raise AnalysisError('Unexpected analysis database rows') from error
            if (not isinstance(payload, dict)
                    or payload.get('track_id') != track_id
                    or payload.get('run_id') != run_id
                    or payload.get('feature_contract_version') != 'graph-feature-evidence-v1'
                    or set((payload.get('features') or {}).keys()) != {'bpm', 'key', 'genres', 'mood', 'energy'}):
                raise AnalysisError('Unexpected analysis database rows')
        for (track_id,) in db.execute('SELECT track_id FROM graph_feature_evidence WHERE is_current=1 GROUP BY track_id HAVING count(*) > 1'):
            raise AnalysisError('Unexpected analysis database rows')


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

    def replace_graph_snapshot(self, edges, sparse_k: int, source_fingerprint: str, positioned_edges=()) -> str:
        edges = tuple(edges)
        positioned_edges = tuple(positioned_edges)
        build_id = str(uuid4())
        with self._transaction() as db:
            db.execute(
                '''INSERT INTO graph_builds(
                    id,status,detail,edge_count,sparse_k,source_fingerprint,
                    distance_policy_version,neighbour_policy_version,is_current)
                   VALUES(?,?,?,?,?,?,?,?,0)''',
                (build_id, 'completed', '', len(edges), int(sparse_k), str(source_fingerprint),
                 DISTANCE_POLICY_VERSION, NEIGHBOUR_POLICY_VERSION),
            )
            for edge in edges:
                distance = round(float(edge.distance), 6)
                score = round(1.0 - distance, 6)
                params = (edge.a, edge.b, score, distance, int(edge.supported_group_count),
                          DISTANCE_POLICY_VERSION, NEIGHBOUR_POLICY_VERSION)
                db.execute(
                    '''INSERT INTO graph_build_edges(
                        build_id,source_track_id,target_track_id,score,distance,supported_group_count,
                        distance_policy_version,neighbour_policy_version)
                       VALUES(?,?,?,?,?,?,?,?)''',
                    (build_id, *params),
                )
            db.execute('INSERT INTO graph_build_positioned_snapshots(build_id,edge_count) VALUES(?,?)', (build_id, len(positioned_edges)))
            for edge in positioned_edges:
                distance = round(float(edge.distance), 6)
                score = round(1.0 - distance, 6)
                params = (edge.a, edge.b, score, distance, int(edge.supported_group_count),
                          DISTANCE_POLICY_VERSION, NEIGHBOUR_POLICY_VERSION)
                db.execute(
                    '''INSERT INTO graph_build_positioned_edges(
                        build_id,source_track_id,target_track_id,score,distance,supported_group_count,
                        distance_policy_version,neighbour_policy_version)
                       VALUES(?,?,?,?,?,?,?,?)''',
                    (build_id, *params),
                )
            db.execute('DELETE FROM graph_edges')
            db.execute('''INSERT INTO graph_edges(
                    source_track_id,target_track_id,score,distance,supported_group_count,
                    distance_policy_version,neighbour_policy_version)
                SELECT source_track_id,target_track_id,score,distance,supported_group_count,
                    distance_policy_version,neighbour_policy_version
                FROM graph_build_edges WHERE build_id=?''', (build_id,))
            db.execute('DELETE FROM graph_positioned_edges')
            db.execute('''INSERT INTO graph_positioned_edges(
                    source_track_id,target_track_id,score,distance,supported_group_count,
                    distance_policy_version,neighbour_policy_version)
                SELECT source_track_id,target_track_id,score,distance,supported_group_count,
                    distance_policy_version,neighbour_policy_version
                FROM graph_build_positioned_edges WHERE build_id=?''', (build_id,))
            db.execute('UPDATE graph_builds SET is_current=0 WHERE is_current=1')
            db.execute('UPDATE graph_builds SET is_current=1 WHERE id=?', (build_id,))
        return build_id

    def record_graph_failure(self, sparse_k: int, source_fingerprint: str, detail: str) -> str:
        build_id = str(uuid4())
        with self._transaction() as db:
            db.execute(
                '''INSERT INTO graph_builds(
                    id,status,detail,edge_count,sparse_k,source_fingerprint,
                    distance_policy_version,neighbour_policy_version,is_current)
                   VALUES(?,?,?,?,?,?,?,?,0)''',
                (build_id, 'failed', str(detail)[:1000], 0, int(sparse_k), str(source_fingerprint),
                 DISTANCE_POLICY_VERSION, NEIGHBOUR_POLICY_VERSION),
            )
        return build_id

    def _invalidate_current_graph_snapshot(self, db, track_id=None):
        version = db.execute('PRAGMA user_version').fetchone()[0]
        if version < 7:
            return
        db.execute('UPDATE graph_builds SET is_current=0 WHERE is_current=1')
        db.execute('DELETE FROM graph_edges')
        if version >= 8:
            db.execute('DELETE FROM graph_positioned_edges')
        if version >= 9 and track_id:
            self._invalidate_current_graph_feature_evidence(db, track_id)

    def _invalidate_current_graph_feature_evidence(self, db, track_id):
        if db.execute('PRAGMA user_version').fetchone()[0] >= 9 and track_id:
            db.execute('UPDATE graph_feature_evidence SET is_current=0 WHERE track_id=? AND is_current=1', (track_id,))

    def start(self, source: AudioSource) -> str:
        run_id = str(uuid4())
        with self._transaction() as db:
            db.execute('INSERT INTO runs(id,location,status) VALUES(?,?,?)', (run_id, source.location, 'running'))
            self._link_run(db, run_id, source.expected_identity)
            if source.expected_identity:
                self._invalidate_current_graph_snapshot(db, source.expected_identity)
        return run_id

    def save_stage(self, run_id: str, result: StageResult) -> None:
        payload = json.dumps(asdict(result), allow_nan=False, ensure_ascii=False)
        with self._transaction() as db:
            row = db.execute('SELECT status FROM runs WHERE id=?', (run_id,)).fetchone()
            if row != ('running',):
                raise AnalysisError('Stage requires an existing running analysis')
            db.execute('INSERT INTO stages(run_id,stage,result) VALUES(?,?,?)', (run_id, result.stage, payload))
            if result.stage in {'bpm', 'key', 'genres', 'mood', 'energy'}:
                self._invalidate_current_graph_snapshot(db, self._run_track_id(db, run_id))

    def finish(self, run_id: str, status: str, detail: str) -> None:
        if status not in {'completed', 'failed', 'interrupted'}:
            raise AnalysisError('Invalid terminal analysis status')
        with self._transaction() as db:
            track_id = self._run_track_id(db, run_id)
            cursor = db.execute("UPDATE runs SET status=?,detail=? WHERE id=? AND status='running'",
                                (status, detail, run_id))
            if cursor.rowcount != 1:
                raise AnalysisError('Finish requires an existing running analysis')
            if status == 'completed':
                self._invalidate_current_graph_snapshot(db, track_id)
                self._persist_graph_feature_evidence(db, track_id, run_id)

    def _run_track_id(self, db, run_id):
        row = db.execute('SELECT track_id FROM run_tracks WHERE run_id=?', (run_id,)).fetchone()
        return row[0] if row else None

    def _persist_graph_feature_evidence(self, db, track_id, run_id):
        if not track_id or db.execute('PRAGMA user_version').fetchone()[0] < 9:
            return
        from music_analyzer.infrastructure.persistence.stage_mapping import stage_from_mapping
        stages = []
        for stage_name, payload in db.execute('SELECT stage,result FROM stages WHERE run_id=? ORDER BY stage', (run_id,)):
            try:
                stage = stage_from_mapping(json.loads(payload))
                if stage.stage != stage_name:
                    raise ValueError('Stage name mismatch')
                stages.append(stage)
            except (ValueError, KeyError, TypeError, IndexError) as error:
                raise AnalysisError('Invalid stored stage: ' + str(error)) from error
        evidence = build_graph_feature_evidence(track_id, run_id, stages)
        if evidence is None:
            return
        db.execute('UPDATE graph_feature_evidence SET is_current=0 WHERE track_id=? AND is_current=1', (track_id,))
        db.execute(
            '''INSERT INTO graph_feature_evidence(track_id,run_id,fingerprint,evidence_json,is_current)
               VALUES(?,?,?,?,1)
               ON CONFLICT(track_id,run_id) DO UPDATE SET
                   fingerprint=excluded.fingerprint,
                   evidence_json=excluded.evidence_json,
                   is_current=1''',
            (track_id, run_id, evidence.fingerprint, evidence.payload_json()),
        )

    def register(self, inventory):
        missing = []
        with self._transaction() as db:
            seen = {file.location for file in inventory.files}
            for file in inventory.files:
                identity = file.identity
                db.execute('INSERT OR IGNORE INTO tracks VALUES(?,?,?)',
                           (identity.track_id, identity.sha256, identity.size))
                stored = db.execute('SELECT sha256,size FROM tracks WHERE id=?', (identity.track_id,)).fetchone()
                if stored != (identity.sha256, identity.size):
                    raise AnalysisError('Duplicate track identity changed while scanning; scan again')
                db.execute('INSERT INTO locations VALUES(?,?,?,?,1) ON CONFLICT(path) DO UPDATE SET track_id=excluded.track_id,mtime_ns=excluded.mtime_ns,format=excluded.format,available=1',
                           (file.location, identity.track_id, file.mtime_ns, file.format))
                db.execute('INSERT OR IGNORE INTO scan_roots VALUES(?,?)', (inventory.root, file.location))
                db.execute('INSERT INTO track_metadata VALUES(?,?,?,?) ON CONFLICT(track_id) DO UPDATE SET common_json=excluded.common_json,tags_json=excluded.tags_json,warnings_json=excluded.warnings_json',
                           (identity.track_id, json.dumps(file.metadata.common, ensure_ascii=False, allow_nan=False), json.dumps(file.metadata.tags, ensure_ascii=False, allow_nan=False), json.dumps(file.metadata.warnings, ensure_ascii=False, allow_nan=False)))
                stored_audio_state = db.execute('SELECT duration_seconds,duration_source,status,reason FROM track_audio WHERE track_id=?', (identity.track_id,)).fetchone()
                stored_audio = stored_audio_state[:2] if stored_audio_state else None
                duration, source = _coalesced_duration(file, inventory.files, stored_audio)
                duration = _normalized_sqlite_duration(duration)
                reason = _duration_eligibility_reason(duration, source)
                status = _duration_status(duration, source)
                new_audio_state = (duration, source, status, reason)
                db.execute('INSERT INTO track_audio VALUES(?,?,?,?,?) ON CONFLICT(track_id) DO UPDATE SET duration_seconds=excluded.duration_seconds,duration_source=excluded.duration_source,status=excluded.status,reason=excluded.reason',
                           (identity.track_id, *new_audio_state))
                if stored_audio_state is not None and stored_audio_state != new_audio_state:
                    self._invalidate_current_graph_feature_evidence(db, identity.track_id)
            if inventory.complete:
                for (path,) in db.execute('SELECT path FROM scan_roots WHERE root=?', (inventory.root,)):
                    if path not in seen:
                        missing.append(path)
                        db.execute('UPDATE locations SET available=0 WHERE path=?', (path,))
            if inventory.files or missing:
                self._invalidate_current_graph_snapshot(db)
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
                page = db.execute("SELECT t.id FROM tracks t JOIN track_audio a ON a.track_id=t.id AND a.status='eligible' WHERE t.id>? ORDER BY t.id LIMIT 100", (after,)).fetchall()
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
        audio = db.execute('SELECT duration_seconds,duration_source,status,reason FROM track_audio WHERE track_id=?', (track_id,)).fetchone()
        if not row:
            return TrackMetadata(duration_seconds=(audio[0] if audio else None), duration_source=(audio[1] if audio else ''))
        try:
            warnings = tuple(str(x) for x in json.loads(row[2]))
            return TrackMetadata(tuple((str(k), tuple(v) if isinstance(v, list) else str(v)) for k, v in json.loads(row[0])), tuple((str(k), tuple(str(x) for x in v)) for k, v in json.loads(row[1])), warnings, audio[0] if audio else None, audio[1] if audio else '')
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
            if field in {'bpm', 'key', 'genres', 'mood', 'energy'}:
                self._invalidate_current_graph_snapshot(db, track_id)
