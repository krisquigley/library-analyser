"""Literal supported-schema fixtures, independent of runtime production DDL.

DDL scaffold recorded from the public v10 writer; historical table sets follow
v1-v9 migration contracts, including genuine pre10 graph_builds lifecycle DDL.
No PRAGMA-only downgrade, production private schema imports, or default triggers.
Graph/evidence tables are empty: these are schema compatibility controls, not
certificates for historical graph publication or arbitrary external databases.
"""
from contextlib import closing
import sqlite3


LEGACY_GRAPH_BUILDS = """CREATE TABLE graph_builds(
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
    CHECK(status = 'completed' OR is_current = 0))"""


# (first schema version, object name, SQL); indexes follow their owning table.
SCHEMA_OBJECTS = (
    (3, 'batch_jobs', """CREATE TABLE batch_jobs(
                    track_id TEXT PRIMARY KEY REFERENCES tracks(id), fingerprint TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('pending','running','completed','failed')),
                    attempts INTEGER NOT NULL CHECK(attempts >= 0), run_id TEXT, detail TEXT NOT NULL)"""),
    (7, 'graph_build_edges', """CREATE TABLE graph_build_edges(
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
            CHECK(source_track_id < target_track_id))"""),
    (8, 'graph_build_positioned_edges', """CREATE TABLE graph_build_positioned_edges(
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
            CHECK(source_track_id < target_track_id))"""),
    (8, 'graph_build_positioned_snapshots', """CREATE TABLE graph_build_positioned_snapshots(
            build_id TEXT PRIMARY KEY REFERENCES graph_builds(id) ON DELETE CASCADE,
            edge_count INTEGER NOT NULL CHECK(edge_count >= 0),
            built_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"""),
    (7, 'graph_builds', """CREATE TABLE graph_builds(
            id TEXT PRIMARY KEY,
            status TEXT NOT NULL CHECK(status IN ('building','completed','failed','interrupted')),
            detail TEXT NOT NULL,
            edge_count INTEGER NOT NULL CHECK(edge_count >= 0),
            sparse_k INTEGER NOT NULL CHECK(sparse_k >= 0),
            source_fingerprint TEXT NOT NULL,
            source_revision TEXT NOT NULL,
            attempt_revision TEXT NOT NULL,
            distance_policy_version TEXT NOT NULL,
            neighbour_policy_version TEXT NOT NULL,
            is_current INTEGER NOT NULL CHECK(is_current IN (0,1)),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            completed_at TEXT,
            CHECK(status = 'completed' OR is_current = 0))"""),
    (7, 'graph_edges', """CREATE TABLE graph_edges(
            source_track_id TEXT NOT NULL REFERENCES tracks(id),
            target_track_id TEXT NOT NULL REFERENCES tracks(id),
            score REAL NOT NULL CHECK(score >= 0.0 AND score <= 1.0),
            distance REAL NOT NULL CHECK(distance >= 0.0 AND distance <= 1.0),
            supported_group_count INTEGER NOT NULL CHECK(supported_group_count > 0),
            distance_policy_version TEXT NOT NULL,
            neighbour_policy_version TEXT NOT NULL,
            built_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(source_track_id,target_track_id),
            CHECK(source_track_id < target_track_id))"""),
    (9, 'graph_feature_evidence', """CREATE TABLE graph_feature_evidence(
            track_id TEXT NOT NULL REFERENCES tracks(id),
            run_id TEXT NOT NULL REFERENCES runs(id),
            fingerprint TEXT NOT NULL,
            evidence_json TEXT NOT NULL,
            is_current INTEGER NOT NULL CHECK(is_current IN (0,1)),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(track_id,run_id))"""),
    (8, 'graph_positioned_edges', """CREATE TABLE graph_positioned_edges(
            source_track_id TEXT NOT NULL REFERENCES tracks(id),
            target_track_id TEXT NOT NULL REFERENCES tracks(id),
            score REAL NOT NULL CHECK(score >= 0.0 AND score <= 1.0),
            distance REAL NOT NULL CHECK(distance >= 0.0 AND distance <= 1.0),
            supported_group_count INTEGER NOT NULL CHECK(supported_group_count > 0),
            distance_policy_version TEXT NOT NULL,
            neighbour_policy_version TEXT NOT NULL,
            built_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(source_track_id,target_track_id),
            CHECK(source_track_id < target_track_id))"""),
    (2, 'locations', """CREATE TABLE locations(path TEXT PRIMARY KEY, track_id TEXT NOT NULL REFERENCES tracks(id), mtime_ns INTEGER NOT NULL, format TEXT NOT NULL, available INTEGER NOT NULL CHECK(available IN (0,1)))"""),
    (4, 'overrides', """CREATE TABLE overrides(track_id TEXT NOT NULL REFERENCES tracks(id), field TEXT NOT NULL, value TEXT NOT NULL, PRIMARY KEY(track_id,field))"""),
    (4, 'run_tracks', """CREATE TABLE run_tracks(run_id TEXT PRIMARY KEY REFERENCES runs(id), track_id TEXT NOT NULL REFERENCES tracks(id))"""),
    (1, 'runs', """CREATE TABLE runs (
                    id TEXT PRIMARY KEY, location TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('running','completed','failed','interrupted')),
                    detail TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"""),
    (2, 'scan_roots', """CREATE TABLE scan_roots(root TEXT NOT NULL, path TEXT NOT NULL REFERENCES locations(path), PRIMARY KEY(root,path))"""),
    (1, 'stages', """CREATE TABLE stages (
                    run_id TEXT NOT NULL REFERENCES runs(id), stage TEXT NOT NULL,
                    result TEXT NOT NULL, PRIMARY KEY(run_id,stage))"""),
    (6, 'track_audio', """CREATE TABLE track_audio(
                    track_id TEXT PRIMARY KEY REFERENCES tracks(id),
                    duration_seconds REAL,
                    duration_source TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('eligible','excluded','unknown')),
                    reason TEXT NOT NULL)"""),
    (5, 'track_metadata', """CREATE TABLE track_metadata(track_id TEXT PRIMARY KEY REFERENCES tracks(id), common_json TEXT NOT NULL, tags_json TEXT NOT NULL, warnings_json TEXT NOT NULL)"""),
    (2, 'tracks', """CREATE TABLE tracks(id TEXT PRIMARY KEY, sha256 TEXT NOT NULL UNIQUE, size INTEGER NOT NULL)"""),
    (6, 'active_locations', """CREATE VIEW active_locations AS SELECT l.path,l.track_id,l.mtime_ns,l.format,l.available FROM locations l JOIN track_audio a ON a.track_id=l.track_id WHERE l.available=1 AND a.status='eligible'"""),
    (6, 'active_tracks', """CREATE VIEW active_tracks AS SELECT t.id,t.sha256,t.size FROM tracks t JOIN track_audio a ON a.track_id=t.id WHERE a.status='eligible'"""),
    (7, 'idx_graph_build_edges_build_id', """CREATE INDEX idx_graph_build_edges_build_id ON graph_build_edges(build_id)"""),
    (7, 'idx_graph_build_edges_source_track_id', """CREATE INDEX idx_graph_build_edges_source_track_id ON graph_build_edges(build_id,source_track_id)"""),
    (7, 'idx_graph_build_edges_target_track_id', """CREATE INDEX idx_graph_build_edges_target_track_id ON graph_build_edges(build_id,target_track_id)"""),
    (8, 'idx_graph_build_positioned_edges_build_id', """CREATE INDEX idx_graph_build_positioned_edges_build_id ON graph_build_positioned_edges(build_id)"""),
    (8, 'idx_graph_build_positioned_edges_source_track_id', """CREATE INDEX idx_graph_build_positioned_edges_source_track_id ON graph_build_positioned_edges(build_id,source_track_id)"""),
    (8, 'idx_graph_build_positioned_edges_target_track_id', """CREATE INDEX idx_graph_build_positioned_edges_target_track_id ON graph_build_positioned_edges(build_id,target_track_id)"""),
    (7, 'idx_graph_builds_one_current', """CREATE UNIQUE INDEX idx_graph_builds_one_current
                   ON graph_builds(is_current) WHERE is_current = 1"""),
    (7, 'idx_graph_edges_source_track_id', """CREATE INDEX idx_graph_edges_source_track_id ON graph_edges(source_track_id)"""),
    (7, 'idx_graph_edges_target_track_id', """CREATE INDEX idx_graph_edges_target_track_id ON graph_edges(target_track_id)"""),
    (9, 'idx_graph_feature_evidence_one_current_per_track', """CREATE UNIQUE INDEX idx_graph_feature_evidence_one_current_per_track
                   ON graph_feature_evidence(track_id) WHERE is_current = 1"""),
    (9, 'idx_graph_feature_evidence_run_id', """CREATE INDEX idx_graph_feature_evidence_run_id ON graph_feature_evidence(run_id)"""),
    (8, 'idx_graph_positioned_edges_source_track_id', """CREATE INDEX idx_graph_positioned_edges_source_track_id ON graph_positioned_edges(source_track_id)"""),
    (8, 'idx_graph_positioned_edges_target_track_id', """CREATE INDEX idx_graph_positioned_edges_target_track_id ON graph_positioned_edges(target_track_id)"""),
)


def create_historical_schema(path, version):
    """Create a fresh real version-specific schema; never downgrade a v10 file."""
    if version not in range(1, 11):
        raise ValueError('Expected schema version 1 through 10')
    with closing(sqlite3.connect(path)) as db:
        db.execute('PRAGMA foreign_keys=ON')
        for first_version, name, sql in SCHEMA_OBJECTS:
            if first_version <= version:
                if name == 'graph_builds' and version < 10:
                    sql = LEGACY_GRAPH_BUILDS
                db.execute(sql)
        db.execute('PRAGMA application_id=0x4D414E41')
        db.execute(f'PRAGMA user_version={version}')
        db.commit()
