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

from music_analyzer.application.dto.analysis import AnalysisError, AnalysisReport, StageResult
from music_analyzer.application.dto.catalogue import TrackMetadata
from music_analyzer.application.dto.explorer import ExplorerStoredTrack, ExplorerTrackSummary, MoodAxisEdge
from music_analyzer.application.use_cases.explorer import _build_mood_axis_graph
from music_analyzer.application.use_cases.graph_feature_evidence import validate_graph_feature_evidence_payload
from music_analyzer.domain.analysis import ScoreSummary
from music_analyzer.domain.library_duration_policy import DurationVerification, TRUSTED_DURATION_SOURCES, active_library_duration_policy
from music_analyzer.infrastructure.persistence.analysis import APPLICATION_ID
from music_analyzer.domain.projection import DISTANCE_POLICY_VERSION, NEIGHBOUR_POLICY_VERSION
from music_analyzer.infrastructure.persistence.stage_mapping import stage_from_mapping

_SHA256_RE = re.compile(r'^[0-9a-f]{64}$')
_TRACK_ID_RE = re.compile(r'^sha256:[0-9a-f]{64}$')
_SQLITE_OCTET_LENGTH_VERSION = (3, 43, 0)
_GRAPH_FEATURE_EVIDENCE_JSON_LIMIT = 16 * 1024 * 1024



def _graph_feature_evidence_size_expression(column='evidence_json'):
    if column not in ('evidence_json', 'g.evidence_json'):
        raise ValueError('Unsupported graph feature evidence column')
    if sqlite3.sqlite_version_info >= _SQLITE_OCTET_LENGTH_VERSION:
        return f'octet_length({column})'
    # Older SQLite runtimes lack octet_length(). CAST(... AS BLOB) keeps the
    # preflight byte-accurate for UTF-8 TEXT before JSON materialization.
    return f'length(CAST({column} AS BLOB))'


def _database_schema_version(db, default=10):
    try:
        row = db.execute('PRAGMA user_version').fetchone()
        return int(row[0]) if row is not None else default
    except Exception:
        # Test fakes and already-validated read handles may not implement PRAGMA;
        # default to the current compact-evidence schema for those narrow calls.
        return default


def _chunked(values, size):
    for start in range(0, len(values), size):
        yield values[start:start + size]


def _stage_result_size_expression(column='result'):
    if column not in ('result', 's.result'):
        raise ValueError('Unsupported stage result column')
    if sqlite3.sqlite_version_info >= _SQLITE_OCTET_LENGTH_VERSION:
        return f'octet_length({column})'
    # Older SQLite runtimes lack octet_length(). Keep the byte-accurate TEXT
    # fallback rather than length(result), accepting that CAST may materialize
    # large stage payloads during this read-only preflight on those runtimes.
    return f'length(CAST({column} AS BLOB))'


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
_EXPECTED_GRAPH_SCHEMA = {
    'graph_edges': {
        'columns': ((('source_track_id', 'TEXT', True, 1), ('target_track_id', 'TEXT', True, 2), ('score', 'REAL', True, 0),
                     ('distance', 'REAL', True, 0), ('supported_group_count', 'INTEGER', True, 0),
                     ('distance_policy_version', 'TEXT', True, 0), ('neighbour_policy_version', 'TEXT', True, 0),
                     ('built_at', 'TEXT', True, 0)),),
        'foreign_keys': ((('tracks', ('source_track_id',), ('id',)), ('tracks', ('target_track_id',), ('id',))),),
        'unique_indexes': (),
        'checks': (('CHECK(source_track_id < target_track_id)', 'CHECK(score >= 0.0 AND score <= 1.0)', 'CHECK(distance >= 0.0 AND distance <= 1.0)'),),
    },
    'graph_builds': {
        'columns': ((('id', 'TEXT', False, 1), ('status', 'TEXT', True, 0), ('detail', 'TEXT', True, 0),
                     ('edge_count', 'INTEGER', True, 0), ('sparse_k', 'INTEGER', True, 0), ('source_fingerprint', 'TEXT', True, 0),
                     ('source_revision', 'TEXT', True, 0), ('attempt_revision', 'TEXT', True, 0),
                     ('distance_policy_version', 'TEXT', True, 0), ('neighbour_policy_version', 'TEXT', True, 0),
                     ('is_current', 'INTEGER', True, 0), ('created_at', 'TEXT', True, 0), ('completed_at', 'TEXT', False, 0)),),
        'foreign_keys': ((),),
        'unique_indexes': (),
        'checks': (("CHECK(status IN ('building','completed','failed','interrupted'))", 'CHECK(edge_count >= 0)', 'CHECK(sparse_k >= 0)', 'CHECK(is_current IN (0,1))', "CHECK(status = 'completed' OR is_current = 0)"),),
    },
    'graph_build_edges': {
        'columns': ((('build_id', 'TEXT', True, 1), ('source_track_id', 'TEXT', True, 2), ('target_track_id', 'TEXT', True, 3), ('score', 'REAL', True, 0),
                     ('distance', 'REAL', True, 0), ('supported_group_count', 'INTEGER', True, 0),
                     ('distance_policy_version', 'TEXT', True, 0), ('neighbour_policy_version', 'TEXT', True, 0),
                     ('built_at', 'TEXT', True, 0)),),
        'foreign_keys': ((('graph_builds', ('build_id',), ('id',)), ('tracks', ('source_track_id',), ('id',)), ('tracks', ('target_track_id',), ('id',))),),
        'unique_indexes': (),
        'checks': (('CHECK(source_track_id < target_track_id)', 'CHECK(score >= 0.0 AND score <= 1.0)', 'CHECK(distance >= 0.0 AND distance <= 1.0)'),),
    },
}
_EXPECTED_GRAPH_SCHEMA_LEGACY = {
    **_EXPECTED_GRAPH_SCHEMA,
    'graph_builds': {
        **_EXPECTED_GRAPH_SCHEMA['graph_builds'],
        'columns': ((('id', 'TEXT', False, 1), ('status', 'TEXT', True, 0), ('detail', 'TEXT', True, 0),
                     ('edge_count', 'INTEGER', True, 0), ('sparse_k', 'INTEGER', True, 0), ('source_fingerprint', 'TEXT', True, 0),
                     ('distance_policy_version', 'TEXT', True, 0), ('neighbour_policy_version', 'TEXT', True, 0),
                     ('is_current', 'INTEGER', True, 0), ('created_at', 'TEXT', True, 0), ('completed_at', 'TEXT', True, 0)),),
        'checks': (("CHECK(status IN ('completed','failed'))", 'CHECK(edge_count >= 0)', 'CHECK(sparse_k >= 0)', 'CHECK(is_current IN (0,1))', "CHECK(status = 'completed' OR is_current = 0)"),),
    },
}

_EXPECTED_POSITIONED_GRAPH_SCHEMA = {
    'graph_positioned_edges': _EXPECTED_GRAPH_SCHEMA['graph_edges'],
    'graph_build_positioned_edges': _EXPECTED_GRAPH_SCHEMA['graph_build_edges'],
    'graph_build_positioned_snapshots': {
        'columns': ((('build_id', 'TEXT', False, 1), ('edge_count', 'INTEGER', True, 0), ('built_at', 'TEXT', True, 0)),),
        'foreign_keys': ((('graph_builds', ('build_id',), ('id',)),),),
        'unique_indexes': (),
        'checks': (('CHECK(edge_count >= 0)',),),
    },
}
_EXPECTED_GRAPH_INDEXES = {('idx_graph_edges_source_track_id', 'index'), ('idx_graph_edges_target_track_id', 'index'), ('idx_graph_build_edges_build_id', 'index'), ('idx_graph_build_edges_source_track_id', 'index'), ('idx_graph_build_edges_target_track_id', 'index'), ('idx_graph_builds_one_current', 'index')}
_EXPECTED_POSITIONED_GRAPH_INDEXES = {('idx_graph_positioned_edges_source_track_id', 'index'), ('idx_graph_positioned_edges_target_track_id', 'index'), ('idx_graph_build_positioned_edges_build_id', 'index'), ('idx_graph_build_positioned_edges_source_track_id', 'index'), ('idx_graph_build_positioned_edges_target_track_id', 'index')}
_EXPECTED_GRAPH_FEATURE_SCHEMA = {
    'graph_feature_evidence': {
        'columns': ((('track_id', 'TEXT', True, 1), ('run_id', 'TEXT', True, 2), ('fingerprint', 'TEXT', True, 0),
                     ('evidence_json', 'TEXT', True, 0), ('is_current', 'INTEGER', True, 0), ('created_at', 'TEXT', True, 0)),),
        'foreign_keys': ((('runs', ('run_id',), ('id',)), ('tracks', ('track_id',), ('id',))),),
        'unique_indexes': (),
        'checks': (('CHECK(is_current IN (0,1))',),),
    },
}
_EXPECTED_GRAPH_FEATURE_INDEXES = {('idx_graph_feature_evidence_one_current_per_track', 'index'), ('idx_graph_feature_evidence_run_id', 'index')}

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
            q = (query or '').strip()
            if q:
                like = '%' + self._summary_fold(q).replace('%', '\\%').replace('_', '\\_') + '%'
                visible_title = "_explorer_summary_fold(_explorer_summary_sort_key('title', common_json, tags_json, display_label, id))"
                visible_artist = "_explorer_summary_fold(_explorer_summary_search_key('artist', common_json, tags_json, display_label, id))"
                where.append(f"({visible_title} LIKE ? ESCAPE '\\' OR {visible_artist} LIKE ? ESCAPE '\\')")
                params.extend([like, like])
            count_where_sql = ('WHERE ' + ' AND '.join(where)) if where else ''
            count_params = tuple(params)
            cursor_key, cursor_id = self._decode_summary_cursor(cursor)
            order_key = order if order in ('title', 'artist') else 'id'
            order_expr = "_explorer_summary_fold(_explorer_summary_sort_key(?, common_json, tags_json, display_label, id))" if order_key in ('title', 'artist') else 'id'
            if cursor_key is not None and cursor_id is not None:
                where.append(f"({order_expr} > ? OR ({order_expr} = ? AND id > ?))")
                if order_key in ('title', 'artist'):
                    params.extend([order_key, cursor_key, order_key, cursor_key, cursor_id])
                else:
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
                           CASE WHEN COALESCE(first_location.path, '') = '' THEN '' ELSE _explorer_basename(first_location.path) END AS display_label
                    FROM active_tracks t
                    LEFT JOIN first_location ON first_location.track_id=t.id
                    LEFT JOIN track_metadata tm ON tm.track_id=t.id
                )
                SELECT id, sha256, size, first_path, available_locations, common_json, tags_json, display_label,
                       _explorer_summary_sort_key(?, common_json, tags_json, display_label, id) AS sort_key
                FROM summary
            """
            select_order_key_params = (order_key,) if order_key in ('title', 'artist') else ('id',)
            order_params = (order_key,) if order_key in ('title', 'artist') else ()
            track_count = db.execute('SELECT count(*) FROM (' + base + count_where_sql + ')', (*select_order_key_params, *count_params)).fetchone()[0]
            rows = db.execute(base + where_sql + f' ORDER BY {order_expr}, id LIMIT ?', (*select_order_key_params, *params, *order_params, limit + 1)).fetchall()
            page_rows = rows[:limit]
            summaries = tuple(self._summary_from_row(row) for row in page_rows)
            next_cursor = None
            if len(rows) > limit and page_rows:
                last = page_rows[-1]
                key = last[8] if order_key in ('title', 'artist') else last[0]
                next_cursor = self._encode_summary_cursor(self._summary_fold(key), last[0])
            return metadata, track_count, summaries, next_cursor

    def candidate_snapshot(self):
        with self._transaction() as db:
            metadata = self._metadata(db)
            ids = tuple(row[0] for row in db.execute('SELECT id FROM active_tracks ORDER BY id'))
            return metadata, tuple(self._read_track(db, track_id) for track_id in ids)

    def graph_source_tracks(self):
        with self._transaction() as db:
            version = _database_schema_version(db)
            evidence_size_expression = _graph_feature_evidence_size_expression('g.evidence_json')
            evidence_columns = f'g.fingerprint,{evidence_size_expression}' if version >= 9 else 'NULL AS fingerprint,NULL AS evidence_json_size'
            evidence_join = """
                LEFT JOIN graph_feature_evidence g ON g.track_id=t.id AND g.run_id=latest_run.run_id AND g.is_current=1
            """ if version >= 9 else ''
            rows = db.execute(f"""
                WITH first_location AS (
                    SELECT track_id, min(path) AS path, count(*) AS available_locations
                    FROM active_locations GROUP BY track_id
                ), latest_run AS (
                    SELECT track_id, run_id, status FROM (
                        SELECT rt.track_id, r.id AS run_id, r.status AS status,
                               row_number() OVER (PARTITION BY rt.track_id ORDER BY r.rowid DESC) AS rn
                        FROM run_tracks rt JOIN runs r ON r.id=rt.run_id
                        JOIN active_tracks at ON at.id=rt.track_id
                    ) WHERE rn=1
                )
                SELECT t.id,t.sha256,t.size,COALESCE(first_location.path,''),
                       COALESCE(first_location.available_locations,0),latest_run.run_id,
                       latest_run.status,COALESCE(tm.common_json,'[]'),COALESCE(tm.tags_json,'[]'),
                       COALESCE(tm.warnings_json,'[]'),a.duration_seconds,a.duration_source,
                       {evidence_columns}
                FROM active_tracks t
                JOIN first_location ON first_location.track_id=t.id
                LEFT JOIN latest_run ON latest_run.track_id=t.id
                {evidence_join}
                LEFT JOIN track_metadata tm ON tm.track_id=t.id
                LEFT JOIN track_audio a ON a.track_id=t.id
                ORDER BY t.id
            """)
            for row in rows:
                record = self._graph_source_track_from_row(db, row)
                if record is not None:
                    yield record

    def mood_axis_graph_snapshot(self, mood: str | None = None, sparse_k: int = 10):
        with self._transaction() as db:
            metadata = self._metadata(db)
            if int(metadata.get('schema_version', 0)) < 8:
                return None
            warm_edges = self._current_positioned_graph_edges(db, sparse_k)
            records = self._compact_graph_tracks(db)
            return _build_mood_axis_graph(metadata, records, self, sparse_k, mood, warm_edges=warm_edges)

    def current_graph_edges(self, sparse_k: int | None = None):
        with self._transaction() as db:
            return self._current_graph_edges(db, sparse_k)

    def current_positioned_graph_edges(self, sparse_k: int | None = None):
        with self._transaction() as db:
            return self._current_positioned_graph_edges(db, sparse_k)

    def track_ids(self):
        with self._transaction() as db:
            return tuple(row[0] for row in db.execute('SELECT id FROM active_tracks ORDER BY id'))

    def available_audio_paths(self):
        with self._transaction() as db:
            return tuple(row[0] for row in db.execute('SELECT path FROM active_locations ORDER BY path'))

    def read_track(self, track_id: str):
        with self._transaction() as db:
            return self._read_track(db, track_id)

    def _current_graph_edges(self, db, requested_sparse_k=None):
        version = _database_schema_version(db)
        if version < 7:
            return None, ()
        current = db.execute("""
            SELECT id,edge_count,sparse_k,distance_policy_version,neighbour_policy_version
            FROM graph_builds WHERE is_current=1 AND status='completed'
        """).fetchone()
        action = 'Run music-analyzer graph build --database DB before loading the mood-axis graph.'
        if current is None:
            latest = db.execute('SELECT status,detail FROM graph_builds ORDER BY created_at DESC,rowid DESC LIMIT 1').fetchone()
            if latest is None:
                return {'state': 'build_needed', 'source': 'graph_build_edges', 'reason': 'no completed warm graph snapshot', 'action': action}, ()
            if latest[0] == 'failed':
                return {'state': 'failed', 'source': 'graph_build_edges', 'reason': latest[1] or 'latest warm graph build failed', 'action': action}, ()
            if latest[0] in {'building', 'interrupted'}:
                return {'state': latest[0], 'source': 'graph_build_edges', 'reason': latest[1] or f'latest warm graph build is {latest[0]}', 'action': action}, ()
            return {'state': 'stale', 'source': 'graph_build_edges', 'reason': 'warm graph snapshot is not current', 'action': action}, ()
        build_id, edge_count, sparse_k, distance_policy, neighbour_policy = current
        if distance_policy != DISTANCE_POLICY_VERSION or neighbour_policy != NEIGHBOUR_POLICY_VERSION:
            return {
                'state': 'stale',
                'source': 'graph_build_edges',
                'reason': 'warm graph snapshot policy version is stale',
                'action': action,
                'build_id': build_id,
                'distance_policy': distance_policy,
                'edge_policy': neighbour_policy,
            }, ()
        if requested_sparse_k is not None and int(sparse_k) != int(requested_sparse_k):
            return {
                'state': 'stale',
                'source': 'graph_build_edges',
                'reason': 'warm graph snapshot sparse_k does not match requested graph sparsity',
                'action': action,
                'build_id': build_id,
                'stored_sparse_k': int(sparse_k),
                'requested_sparse_k': int(requested_sparse_k),
            }, ()
        rows = db.execute('''
            SELECT source_track_id,target_track_id,score,supported_group_count,
                   distance_policy_version,neighbour_policy_version
            FROM graph_build_edges WHERE build_id=? ORDER BY source_track_id,target_track_id
        ''', (build_id,)).fetchall()
        status = {
            'state': 'ready',
            'source': 'graph_build_edges',
            'build_id': build_id,
            'edge_count': int(edge_count),
            'sparse_k': int(sparse_k),
            'distance_policy': distance_policy,
            'edge_policy': neighbour_policy,
        }
        edges = tuple(
            MoodAxisEdge(
                source,
                target,
                round(float(score), 6),
                'axis-independent relatedness from persisted warm graph_build_edges snapshot',
                {'policy': edge_distance_policy, 'neighbour_policy': edge_neighbour_policy, 'source': 'graph_build_edges'},
                int(supported_count),
            )
            for source, target, score, supported_count, edge_distance_policy, edge_neighbour_policy in rows
        )
        return status, edges

    def _current_positioned_graph_edges(self, db, requested_sparse_k=None):
        version = _database_schema_version(db)
        action = 'Run music-analyzer graph build --database DB before loading the mood-axis graph.'
        if version < 8:
            return {'state': 'build_needed', 'source': 'graph_build_positioned_edges', 'reason': 'exact positioned warm graph snapshot requires schema v8 rebuild', 'action': action}, ()
        status, _global_edges = self._current_graph_edges(db, requested_sparse_k)
        if not status or status.get('state') != 'ready':
            if status:
                status = {**status, 'source': 'graph_build_positioned_edges'}
            return status, ()
        build_id = status['build_id']
        snapshot = db.execute('SELECT edge_count FROM graph_build_positioned_snapshots WHERE build_id=?', (build_id,)).fetchone()
        if snapshot is None:
            return {'state': 'build_needed', 'source': 'graph_build_positioned_edges', 'reason': 'exact positioned warm graph snapshot is not available for current build', 'action': action, 'build_id': build_id}, ()
        rows = db.execute('''
            SELECT source_track_id,target_track_id,score,supported_group_count,
                   distance_policy_version,neighbour_policy_version
            FROM graph_build_positioned_edges WHERE build_id=? ORDER BY source_track_id,target_track_id
        ''', (build_id,)).fetchall()
        status = {**status, 'source': 'graph_build_positioned_edges', 'edge_count': len(rows)}
        edges = tuple(
            MoodAxisEdge(
                source,
                target,
                round(float(score), 6),
                'axis-independent relatedness from persisted exact positioned graph_build_positioned_edges snapshot',
                {'policy': edge_distance_policy, 'neighbour_policy': edge_neighbour_policy, 'source': 'graph_build_positioned_edges'},
                int(supported_count),
            )
            for source, target, score, supported_count, edge_distance_policy, edge_neighbour_policy in rows
        )
        return status, edges

    def _metadata(self, db):
        return {
            'application_id': db.execute('PRAGMA application_id').fetchone()[0],
            'schema_version': db.execute('PRAGMA user_version').fetchone()[0],
            'read_policy': 'bounded_read_transaction',
        }

    def _graph_source_track_from_row(self, db, row):
        (track_id, sha256, size, first_path, available_locations, run_id, status,
         common_json, tags_json, warnings_json, duration_seconds, duration_source,
         evidence_fingerprint, evidence_json_size) = row
        if run_id is None or status != 'completed':
            return None
        if evidence_fingerprint is None:
            return self._read_track(db, track_id)
        try:
            evidence_json = self._load_graph_feature_evidence_payload(db, track_id, run_id, evidence_json_size)
            payload = json.loads(evidence_json)
            validate_graph_feature_evidence_payload(track_id, run_id, evidence_fingerprint, payload)
            metadata = self._metadata_from_json(common_json, tags_json, warnings_json, (duration_seconds, duration_source))
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise AnalysisError('Invalid stored graph feature evidence') from error
        locations = tuple(row[0] for row in db.execute('SELECT path FROM active_locations WHERE track_id=? ORDER BY path', (track_id,)))
        overrides = tuple(db.execute(
            "SELECT field,value FROM overrides WHERE track_id=? AND field IN ('bpm','key','genres','mood','energy') ORDER BY field",
            (track_id,),
        ))
        run = AnalysisReport(run_id, 'completed', self._stages_from_graph_feature_payload(payload), '')
        return ExplorerStoredTrack(
            track_id,
            sha256,
            size,
            Path(first_path).name if first_path else '',
            int(available_locations),
            run,
            overrides,
            metadata,
            locations,
        )

    def _stages_from_graph_feature_payload(self, payload):
        stages = []
        for stage_name in sorted(payload['features']):
            feature = payload['features'][stage_name]
            summary = None
            if feature.get('summary') is not None:
                raw = feature['summary']
                summary = ScoreSummary(
                    tuple(raw['labels']),
                    tuple(raw['mean']),
                    tuple(raw['minimum']),
                    tuple(raw['maximum']),
                    float(raw['coverage']),
                    bool(raw['provisional']),
                    str(raw['uncertainty']),
                )
            stages.append(StageResult(
                str(stage_name),
                tuple((str(key), str(value)) for key, value in feature.get('provenance', ())),
                str(feature.get('uncertainty', '')),
                tuple((str(key), value) for key, value in feature.get('values', ())),
                (),
                summary,
                (),
            ))
        return tuple(stages)

    def _compact_graph_tracks(self, db):
        version = _database_schema_version(db)
        evidence_size_expression = _graph_feature_evidence_size_expression('g.evidence_json')
        evidence_columns = f'g.fingerprint, {evidence_size_expression}' if version >= 9 else 'NULL AS fingerprint, NULL AS evidence_json_size'
        evidence_join = """
            LEFT JOIN graph_feature_evidence g
                   ON g.track_id=t.id AND g.run_id=latest_run.run_id AND g.is_current=1
        """ if version >= 9 else ''
        rows = db.execute(f"""
            WITH first_location AS (
                SELECT track_id, min(path) AS path, count(*) AS available_locations
                FROM active_locations GROUP BY track_id
            ), latest_run AS (
                SELECT track_id, run_id, status, detail FROM (
                    SELECT rt.track_id, r.id AS run_id, r.status AS status, r.detail AS detail,
                           row_number() OVER (PARTITION BY rt.track_id ORDER BY r.rowid DESC) AS rn
                    FROM run_tracks rt JOIN runs r ON r.id=rt.run_id
                    JOIN active_tracks at ON at.id=rt.track_id
                ) WHERE rn=1
            )
            SELECT t.id, t.sha256, t.size,
                   COALESCE(first_location.path, '') AS first_path,
                   COALESCE(first_location.available_locations, 0) AS available_locations,
                   latest_run.run_id, latest_run.status, latest_run.detail,
                   COALESCE(tm.common_json, '[]'), COALESCE(tm.tags_json, '[]'), COALESCE(tm.warnings_json, '[]'),
                   a.duration_seconds, a.duration_source,
                   {evidence_columns}
            FROM active_tracks t
            LEFT JOIN first_location ON first_location.track_id=t.id
            LEFT JOIN latest_run ON latest_run.track_id=t.id
            {evidence_join}
            LEFT JOIN track_metadata tm ON tm.track_id=t.id
            LEFT JOIN track_audio a ON a.track_id=t.id
            ORDER BY t.id
        """).fetchall()
        stages_by_run = {}
        compact_stages_by_run = {}
        legacy_run_ids = tuple(
            row[5] for row in rows
            if row[5] is not None and not (row[6] == 'completed' and row[13] is not None)
        )
        size_expression = _stage_result_size_expression('s.result')
        stage_sizes = []
        if legacy_run_ids:
            for run_id_chunk in _chunked(legacy_run_ids, 500):
                placeholders = ','.join('?' for _run_id in run_id_chunk)
                stage_sizes.extend(db.execute(f"""
                    SELECT s.run_id, s.stage, {size_expression}
                    FROM stages s
                    WHERE s.run_id IN ({placeholders})
                    ORDER BY s.run_id, s.stage
                """, run_id_chunk))
        else:
            stage_sizes.extend(db.execute(f"""
                WITH latest_run AS (
                    SELECT track_id, run_id FROM (
                        SELECT rt.track_id, r.id AS run_id,
                               row_number() OVER (PARTITION BY rt.track_id ORDER BY r.rowid DESC) AS rn
                        FROM run_tracks rt JOIN runs r ON r.id=rt.run_id
                        JOIN active_tracks at ON at.id=rt.track_id
                    ) WHERE rn=1
                )
                SELECT s.run_id, s.stage, {size_expression}
                FROM latest_run JOIN stages s ON s.run_id=latest_run.run_id
                WHERE 0
                ORDER BY latest_run.track_id, s.stage
            """))
        stage_sizes = tuple(stage_sizes)
        for run_id, stage, size in stage_sizes:
            if size > 16 * 1024 * 1024:
                raise AnalysisError('Oversized stored stage (16 MiB limit)')
        for run_id, stage, size in stage_sizes:
            payload = db.execute('SELECT result FROM stages WHERE run_id=? AND stage=?', (run_id, stage)).fetchone()[0]
            stages_by_run.setdefault(run_id, []).append(self._stage_from_payload(stage, size, payload))
        overrides_by_track = {}
        for track_id, field, value in db.execute("""
            SELECT o.track_id,o.field,o.value FROM overrides o
            JOIN active_tracks at ON at.id=o.track_id
            ORDER BY o.track_id,o.field
        """):
            overrides_by_track.setdefault(track_id, []).append((field, value))
        compact_evidence_rows = tuple(
            (row[0], row[5], row[13], row[14]) for row in rows
            if row[5] is not None and row[6] == 'completed' and row[13] is not None
        )
        for _track_id, _run_id, _fingerprint, evidence_json_size in compact_evidence_rows:
            if evidence_json_size is None:
                raise AnalysisError('Invalid stored graph feature evidence')
            if int(evidence_json_size) > _GRAPH_FEATURE_EVIDENCE_JSON_LIMIT:
                raise AnalysisError('Oversized stored graph feature evidence (16 MiB limit)')
        compact_evidence_by_identity = {
            (track_id, run_id): fingerprint
            for track_id, run_id, fingerprint, _size in compact_evidence_rows
        }
        loaded_compact_identities = set()
        for payload_chunk in self._iter_graph_feature_evidence_payload_chunks(
                db, tuple((track_id, run_id) for track_id, run_id, _fingerprint, _size in compact_evidence_rows), current_only=True):
            for track_id, run_id, evidence_json in payload_chunk:
                loaded_compact_identities.add((track_id, run_id))
                try:
                    payload = json.loads(evidence_json)
                    validate_graph_feature_evidence_payload(track_id, run_id, compact_evidence_by_identity[(track_id, run_id)], payload)
                    compact_stages_by_run[run_id] = self._stages_from_graph_feature_payload(payload)
                except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
                    raise AnalysisError('Invalid stored graph feature evidence') from error
        if loaded_compact_identities != set(compact_evidence_by_identity):
            raise AnalysisError('Invalid stored graph feature evidence')
        records = []
        for row in rows:
            (track_id, sha256, size, first_path, available_locations, run_id, status, detail,
             common_json, tags_json, warnings_json, duration_seconds, duration_source,
             evidence_fingerprint, evidence_json_size) = row
            try:
                metadata = self._metadata_from_json(common_json, tags_json, warnings_json, (duration_seconds, duration_source))
            except (TypeError, ValueError, json.JSONDecodeError) as error:
                raise AnalysisError('Invalid stored graph feature evidence') from error
            run = None
            if run_id is not None:
                stages = compact_stages_by_run.get(run_id, tuple(stages_by_run.get(run_id, ())))
                run = AnalysisReport(run_id, status, tuple(stages), detail or '')
            records.append(ExplorerStoredTrack(
                track_id,
                sha256,
                size,
                Path(first_path).name if first_path else '',
                int(available_locations),
                run,
                tuple(overrides_by_track.get(track_id, ())),
                metadata,
            ))
        return tuple(records)

    def _load_graph_feature_evidence_payload(self, db, track_id, run_id, size):
        if size is None:
            raise AnalysisError('Invalid stored graph feature evidence')
        if int(size) > _GRAPH_FEATURE_EVIDENCE_JSON_LIMIT:
            raise AnalysisError('Oversized stored graph feature evidence (16 MiB limit)')
        payloads = self._load_graph_feature_evidence_payloads(db, ((track_id, run_id),))
        try:
            return payloads[(track_id, run_id)]
        except KeyError as error:
            raise AnalysisError('Invalid stored graph feature evidence') from error

    def _load_graph_feature_evidence_payloads(self, db, identities):
        payloads = {}
        for payload_chunk in self._iter_graph_feature_evidence_payload_chunks(db, identities, current_only=True):
            for track_id, run_id, evidence_json in payload_chunk:
                payloads[(track_id, run_id)] = evidence_json
        return payloads

    def _iter_graph_feature_evidence_payload_chunks(self, db, identities, *, current_only):
        current_clause = 'is_current=1 AND ' if current_only else ''
        for identity_chunk in _chunked(tuple(identities), 450):
            placeholders = ','.join('(?,?)' for _identity in identity_chunk)
            parameters = tuple(value for identity in identity_chunk for value in identity)
            cursor = db.execute(f'''
                SELECT track_id,run_id,evidence_json FROM graph_feature_evidence
                WHERE {current_clause}(track_id,run_id) IN ({placeholders})
            ''', parameters)
            try:
                yield cursor
            finally:
                close = getattr(cursor, 'close', None)
                if close is not None:
                    close()

    def _stage_from_payload(self, stage, size, payload):
        if size > 16 * 1024 * 1024:
            raise AnalysisError('Oversized stored stage (16 MiB limit)')
        try:
            data = json.loads(payload)
            if not isinstance(data, dict):
                raise ValueError('Stage payload must be a JSON object')
            result = stage_from_mapping(data)
            if result.stage != stage:
                raise ValueError('Stage name mismatch')
            return type(result)(result.stage, result.provenance, result.uncertainty, result.values, result.windows, result.summary, ())
        except (ValueError, KeyError, TypeError, IndexError, AttributeError, json.JSONDecodeError) as error:
            raise AnalysisError('Invalid stored stage: ' + str(error)) from error

    def _read_track(self, db, track_id: str):
        track = db.execute('SELECT id,sha256,size FROM tracks WHERE id=?', (track_id,)).fetchone()
        if not track:
            raise AnalysisError('Unknown explorer track')
        locations = tuple(row[0] for row in db.execute('SELECT path FROM locations WHERE track_id=? AND available=1 ORDER BY path', (track_id,)))
        display_label = Path(locations[0]).name if locations else ''
        row = db.execute('SELECT r.id,r.status,r.detail FROM runs r JOIN run_tracks t ON t.run_id=r.id WHERE t.track_id=? ORDER BY r.rowid DESC LIMIT 1', (track_id,)).fetchone()
        run = None
        if row:
            stages = []
            size_expression = _stage_result_size_expression()
            stage_sizes = tuple(db.execute(f'SELECT stage,{size_expression} FROM stages WHERE run_id=? ORDER BY stage', (row[0],)))
            for _stage, size in stage_sizes:
                if int(size) > 16 * 1024 * 1024:
                    raise AnalysisError('Oversized stored stage (16 MiB limit)')
            for stage, size in stage_sizes:
                payload = db.execute('SELECT result FROM stages WHERE run_id=? AND stage=?', (row[0], stage)).fetchone()[0]
                stages.append(self._stage_from_payload(stage, size, payload))
            run = AnalysisReport(row[0], row[1], tuple(stages), row[2])
        overrides = tuple(db.execute('SELECT field,value FROM overrides WHERE track_id=? ORDER BY field', (track_id,)))
        metadata = self._read_metadata(db, track_id)
        return ExplorerStoredTrack(track[0], track[1], track[2], display_label, len(locations), run, overrides, metadata, locations)


    def _summary_from_row(self, row):
        track_id, _sha, _size, first_path, available_locations, common_json, tags_json, display_label, _sort_key = row
        label = Path(first_path).name if first_path else display_label
        metadata = self._metadata_from_json(common_json, tags_json, '[]', None)
        title = self._metadata_value(metadata, 'title') or label or track_id
        artist = self._metadata_value(metadata, 'artist') or 'Unknown artist'
        return ExplorerTrackSummary(track_id, title, artist, label, int(available_locations))

    def _metadata_from_json(self, common_json, tags_json, warnings_json, audio):
        warnings = tuple(str(x) for x in json.loads(warnings_json))
        return TrackMetadata(tuple((str(k), tuple(v) if isinstance(v, list) else str(v)) for k, v in json.loads(common_json)), tuple((str(k), tuple(str(x) for x in v)) for k, v in json.loads(tags_json)), warnings, audio[0] if audio else None, audio[1] if audio else '')

    def _summary_sort_key(self, order, common_json, tags_json, display_label, track_id):
        try:
            metadata = self._metadata_from_json(common_json or '[]', tags_json or '[]', '[]', None)
            label = str(display_label or '')
            if order == 'artist':
                return self._metadata_value(metadata, 'artist') or 'Unknown artist'
            if order == 'title':
                return self._metadata_value(metadata, 'title') or label or str(track_id or '')
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
        return str(track_id or '')

    def _summary_search_key(self, field, common_json, tags_json, display_label, track_id):
        if field == 'title':
            return self._summary_sort_key('title', common_json, tags_json, display_label, track_id)
        if field == 'artist':
            try:
                metadata = self._metadata_from_json(common_json or '[]', tags_json or '[]', '[]', None)
                return self._metadata_value(metadata, 'artist') or ''
            except (TypeError, ValueError, json.JSONDecodeError):
                return ''
        return ''

    def _summary_fold(self, value):
        return str(value or '').casefold()

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
            db.create_function('_explorer_basename', 1, lambda value: Path(str(value)).name if value else '')
            db.create_function('_explorer_summary_sort_key', 5, self._summary_sort_key)
            db.create_function('_explorer_summary_search_key', 5, self._summary_search_key)
            db.create_function('_explorer_summary_fold', 1, self._summary_fold)
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
        version = _database_schema_version(db)
        if db.execute('PRAGMA application_id').fetchone()[0] != APPLICATION_ID or version not in (6, 7, 8, 9, 10):
            raise AnalysisError('Not a supported music-analyzer analysis database')
        objects = set(db.execute("SELECT name,type FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' AND type IN ('table','view','index')"))
        schema = dict(_EXPECTED_SCHEMA)
        expected_objects = {(name, 'table') for name in schema} | {(name, 'view') for name in _EXPECTED_VIEWS}
        if version >= 7:
            graph_schema = _EXPECTED_GRAPH_SCHEMA if version >= 10 else _EXPECTED_GRAPH_SCHEMA_LEGACY
            schema.update(graph_schema)
            expected_objects |= {(name, 'table') for name in graph_schema} | _EXPECTED_GRAPH_INDEXES
        if version >= 8:
            schema.update(_EXPECTED_POSITIONED_GRAPH_SCHEMA)
            expected_objects |= {(name, 'table') for name in _EXPECTED_POSITIONED_GRAPH_SCHEMA} | _EXPECTED_POSITIONED_GRAPH_INDEXES
        if version >= 9:
            schema.update(_EXPECTED_GRAPH_FEATURE_SCHEMA)
            expected_objects |= {(name, 'table') for name in _EXPECTED_GRAPH_FEATURE_SCHEMA} | _EXPECTED_GRAPH_FEATURE_INDEXES
        if objects != expected_objects:
            raise AnalysisError('Unexpected analysis database schema')
        for view, (columns, expected_sql) in _EXPECTED_VIEWS.items():
            actual_columns = tuple(row[1] for row in db.execute(f'PRAGMA table_info({view})'))
            actual_sql = db.execute("SELECT sql FROM sqlite_master WHERE type='view' AND name=?", (view,)).fetchone()[0]
            normalize = lambda sql: ' '.join(sql.rstrip(';').split())
            if actual_columns != columns or normalize(actual_sql) != normalize(expected_sql):
                raise AnalysisError('Unexpected analysis database schema')
        for table, expected in schema.items():
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
        if version >= 7:
            self._validate_graph_rows(db)
        if version >= 9:
            self._validate_graph_feature_rows(db)

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

    def _validate_graph_rows(self, db):
        current_count = db.execute('SELECT count(*) FROM graph_builds WHERE is_current=1').fetchone()[0]
        if current_count > 1:
            raise AnalysisError('Unexpected analysis database rows')
        current_build = db.execute('SELECT id FROM graph_builds WHERE is_current=1').fetchone()
        allowed_build_statuses = {'completed', 'failed'} if db.execute('PRAGMA user_version').fetchone()[0] < 10 else {'building', 'completed', 'failed', 'interrupted'}
        for build_id, status, edge_count, sparse_k, distance_policy, neighbour_policy, is_current in db.execute(
                'SELECT id,status,edge_count,sparse_k,distance_policy_version,neighbour_policy_version,is_current FROM graph_builds'):
            historical_edges = db.execute('SELECT count(*) FROM graph_build_edges WHERE build_id=?', (build_id,)).fetchone()[0]
            if (status not in allowed_build_statuses or not isinstance(edge_count, int) or edge_count < 0
                    or not isinstance(sparse_k, int) or sparse_k < 0
                    or not isinstance(distance_policy, str) or not distance_policy
                    or not isinstance(neighbour_policy, str) or not neighbour_policy
                    or is_current not in (0, 1) or (status != 'completed' and is_current)
                    or (status == 'completed' and edge_count != historical_edges)
                    or (status == 'failed' and historical_edges != 0)):
                raise AnalysisError('Unexpected analysis database rows')
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
        evidence_size_expression = _graph_feature_evidence_size_expression('g.evidence_json')
        rows = tuple(db.execute(f'''
            WITH latest_run AS (
                SELECT track_id, run_id, status FROM (
                    SELECT rt.track_id, r.id AS run_id, r.status AS status,
                           row_number() OVER (PARTITION BY rt.track_id ORDER BY r.rowid DESC) AS rn
                    FROM run_tracks rt JOIN runs r ON r.id=rt.run_id
                ) WHERE rn=1
            )
            SELECT g.track_id,g.run_id,g.fingerprint,{evidence_size_expression},g.is_current,
                   r.status, linked.run_id, latest_run.run_id, latest_run.status
            FROM graph_feature_evidence g
            LEFT JOIN runs r ON r.id=g.run_id
            LEFT JOIN run_tracks linked ON linked.run_id=g.run_id AND linked.track_id=g.track_id
            LEFT JOIN latest_run ON latest_run.track_id=g.track_id
            ORDER BY g.track_id,g.run_id
        '''))
        for track_id, run_id, fingerprint, evidence_json_size, is_current, status, linked_run_id, latest_run_id, latest_status in rows:
            if (not isinstance(track_id, str) or not _TRACK_ID_RE.fullmatch(track_id)
                    or not isinstance(run_id, str) or not run_id
                    or not isinstance(fingerprint, str) or not _SHA256_RE.fullmatch(fingerprint)
                    or is_current not in (0, 1)):
                raise AnalysisError('Unexpected analysis database rows')
            if status != 'completed' or linked_run_id is None:
                raise AnalysisError('Unexpected analysis database rows')
            if is_current and (latest_run_id != run_id or latest_status != 'completed'):
                raise AnalysisError('Unexpected analysis database rows')
            if int(evidence_json_size) > _GRAPH_FEATURE_EVIDENCE_JSON_LIMIT:
                raise AnalysisError('Oversized stored graph feature evidence (16 MiB limit)')
        fingerprints_by_identity = {
            (track_id, run_id): fingerprint
            for track_id, run_id, fingerprint, _evidence_json_size, _is_current, *_rest in rows
        }
        loaded_identities = set()
        for payload_chunk in self._iter_graph_feature_evidence_payload_chunks(
                db, tuple(fingerprints_by_identity), current_only=False):
            for track_id, run_id, evidence_json in payload_chunk:
                loaded_identities.add((track_id, run_id))
                try:
                    payload = json.loads(evidence_json)
                except (TypeError, ValueError, json.JSONDecodeError) as error:
                    raise AnalysisError('Unexpected analysis database rows') from error
                try:
                    validate_graph_feature_evidence_payload(track_id, run_id, fingerprints_by_identity[(track_id, run_id)], payload)
                except (KeyError, ValueError) as error:
                    raise AnalysisError('Unexpected analysis database rows') from error
        if loaded_identities != set(fingerprints_by_identity):
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
