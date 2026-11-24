"""Read-only SQLite explorer adapter.

Uses bounded read transactions against the selected live analysis database.  The
adapter opens SQLite with ``mode=ro`` so committed WAL frames are visible, avoids
``immutable=1``, enables ``query_only`` defense, and never creates or migrates
schemas.
"""
from contextlib import contextmanager
from dataclasses import replace
import json
from math import isfinite
from pathlib import Path
import re
import sqlite3

from music_analyzer.application.use_cases.graph_feature_evidence import validate_graph_feature_evidence_payload
from music_explorer.application.dto.explorer import AnalysisReport, ExplorerStoredTrack, ExplorerTrackSummary, MoodAxisEdge, ScoreSummary, StageResult, TrackMetadata
from music_explorer.application.dto.playlists import PlayableTrackCandidate, PlaylistMoodEvidence
from music_explorer.application.ports.saved_playlist_recipes import SavedPlaylistRecipeRow
from music_explorer.application.use_cases.explorer import _build_mood_axis_graph
from music_explorer.domain.analysis import finite
from music_explorer.domain.projection import DISTANCE_POLICY_VERSION, NEIGHBOUR_POLICY_VERSION
from music_explorer.domain.mood_evidence import AROUSAL_VALENCE_MODEL, MOOD_THEME_MODEL, has_provenance_model, is_mood_score

APPLICATION_ID = 0x4D414E41
ACTIVE_LIBRARY_MAX_DURATION_SECONDS = 1200.0
TRUSTED_DURATION_SOURCES = {'mutagen', 'ffprobe'}
UNKNOWN_DURATION_REASON = 'duration unverified; excluded from active library until mutagen/ffprobe verifies duration; rescan audio metadata'
INVALID_DURATION_REASON = 'duration invalid; excluded from active library until mutagen/ffprobe verifies a positive finite duration; rescan audio metadata'


class AnalysisError(Exception):
    """Expected actionable explorer read failure."""


def _finite_number(value):
    # Domain policy: finite AS A FLOAT (no OverflowError for huge integers).
    return finite(value)


def _duration_warning(duration_seconds, source):
    if source not in TRUSTED_DURATION_SOURCES or duration_seconds is None:
        return UNKNOWN_DURATION_REASON
    if not _finite_number(duration_seconds) or duration_seconds <= 0:
        return INVALID_DURATION_REASON
    if duration_seconds > ACTIVE_LIBRARY_MAX_DURATION_SECONDS:
        return (f'duration exceeds {ACTIVE_LIBRARY_MAX_DURATION_SECONDS:.1f}s; '
                'excluded from active library; rescan metadata or choose a shorter file')
    return ''


def _expected_audio_status(duration_seconds, source):
    if _duration_warning(duration_seconds, source) == '':
        return 'eligible'
    if source in TRUSTED_DURATION_SOURCES and duration_seconds is not None:
        return 'excluded'
    return 'unknown'


def _bpm_from_stage_payload(payload):
    try:
        data = json.loads(payload)
        for label, value in data.get('values', ()):
            if label == 'bpm' and _finite_number(value):
                return float(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return None


def _arousal(summary_values_json, provenance_json):
    try:
        if not has_provenance_model(_pairs(provenance_json), AROUSAL_VALENCE_MODEL):
            return None
        arousal = dict(_pairs(summary_values_json)).get('arousal')
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return float(arousal) if _finite_number(arousal) and not isinstance(arousal, bool) else None


def _mood_score(score, provenance_json):
    try:
        compatible = has_provenance_model(_pairs(provenance_json), MOOD_THEME_MODEL)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return float(score) if compatible and is_mood_score(score) else None


def _pairs(pairs_json):
    pairs = json.loads(pairs_json) if pairs_json is not None else []
    if not isinstance(pairs, list) or not all(isinstance(pair, list) and len(pair) == 2 for pair in pairs):
        raise ValueError('expected [key, value] pairs')
    return [tuple(pair) for pair in pairs]


def _key_from_stage_payload(payload):
    """Detected key evidence for harmonic mixing; anything malformed is simply unknown."""
    try:
        values = dict(json.loads(payload).get('values', ())) if payload is not None else {}
    except (TypeError, ValueError, AttributeError, json.JSONDecodeError):
        values = {}
    key, scale, strength = values.get('key'), values.get('scale'), values.get('strength')
    return {'key': key if isinstance(key, str) else None,
            'scale': scale if isinstance(scale, str) else None,
            'key_strength': float(strength) if _finite_number(strength) else None}


def stage_from_mapping(data):
    summary = data.get('summary')
    if summary is not None:
        coverage = summary['coverage']
        if not _finite_number(coverage):
            raise ValueError('Invalid summary')
        summary = ScoreSummary(tuple(summary['labels']), tuple(summary['mean']), tuple(summary['minimum']), tuple(summary['maximum']), float(coverage), bool(summary.get('provisional', True)), str(summary.get('uncertainty', 'Raw scores are not calibrated; unsampled audio may differ.')))
        if (not summary.labels or any(not isinstance(label, str) for label in summary.labels)
                or any(len(values) != len(summary.labels) or not all(_finite_number(value) for value in values)
                       for values in (summary.mean, summary.minimum, summary.maximum))
                or not 0 < summary.coverage <= 1):
            raise ValueError('Invalid summary')
    for name in ('provenance', 'values'):
        pairs = data.get(name, ())
        if not isinstance(pairs, (list, tuple)):
            raise ValueError('Invalid ' + name)
        for pair in pairs:
            if (not isinstance(pair, (list, tuple)) or len(pair) != 2 or not isinstance(pair[0], str)
                    or not (isinstance(pair[1], str) or (name == 'values' and _finite_number(pair[1])))):
                raise ValueError('Invalid ' + name)
    if not isinstance(data['stage'], str) or not isinstance(data['uncertainty'], str):
        raise ValueError('Invalid stage text')
    return StageResult(data['stage'], tuple(tuple(item) for item in data['provenance']), data['uncertainty'], tuple(tuple(item) for item in data.get('values', ())), (), summary)

_SHA256_RE = re.compile(r'^[0-9a-f]{64}$')
_TRACK_ID_RE = re.compile(r'^sha256:[0-9a-f]{64}$')
# Scoped active eligibility: identity/audio rows are validated by the
# request-local _explorer_active_candidate UDF as they are consumed.
_ACTIVE_CANDIDATE_JOIN = 'FROM tracks t LEFT JOIN track_audio a ON a.track_id=t.id'
_ACTIVE_CANDIDATE_PREDICATE = ('_explorer_active_candidate(t.id,t.sha256,t.size,'
                               'a.duration_seconds,a.duration_source,a.status,a.reason)')
_ACTIVE_CANDIDATES_FROM = f'{_ACTIVE_CANDIDATE_JOIN} WHERE {_ACTIVE_CANDIDATE_PREDICATE}'
_EDGE_COLUMNS = ('source_track_id,target_track_id,score,distance,supported_group_count,'
                 'distance_policy_version,neighbour_policy_version')


def _non_negative_int(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _build_statuses(version):
    return {'completed', 'failed'} if version < 10 else {'building', 'completed', 'failed', 'interrupted'}


def _validate_edge_row(row):
    source, target, score, distance, count, distance_policy, neighbour_policy = row
    if (not isinstance(source, str) or not isinstance(target, str) or source >= target
            or not isinstance(score, (int, float)) or not 0.0 <= float(score) <= 1.0
            or not isinstance(distance, (int, float)) or not 0.0 <= float(distance) <= 1.0
            or round(1.0 - float(distance), 6) != round(float(score), 6)
            or not isinstance(count, int) or count <= 0
            or not isinstance(distance_policy, str) or not distance_policy
            or not isinstance(neighbour_policy, str) or not neighbour_policy):
        raise AnalysisError('Unexpected analysis database rows')
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


def _playlist_duration(value):
    return float(value) if _finite_number(value) and value > 0 else None


_PLAYLIST_RECIPES_SCHEMA = 11
_SAVED_RECIPE_COLUMNS = 'name,recipe_json,updated_at'


def _saved_playlist_recipe(row):
    name, recipe_json, updated_at = row
    if not isinstance(name, str) or not isinstance(updated_at, str):
        raise AnalysisError('Unexpected analysis database rows')
    try:
        document = json.loads(recipe_json) if isinstance(recipe_json, str) else None
    except ValueError:
        document = None
    return SavedPlaylistRecipeRow(name, document, updated_at)


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
            where = '' if after is None else 'AND t.id > ?'
            params = () if after is None else (after,)
            # One catalogue pass: the window count is taken over the filtered
            # candidates before LIMIT, so each row is eligibility-checked once.
            rows = db.execute(f'SELECT t.id, count(*) OVER () {_ACTIVE_CANDIDATES_FROM} {where} ORDER BY t.id LIMIT ?',
                              (*params, limit)).fetchall()
            track_count = rows[0][1] if rows else 0
            ids = tuple(row[0] for row in rows)
            return metadata, track_count, tuple(self._read_track(db, track_id) for track_id in ids)


    def list_track_summaries(self, limit: int, cursor: str | None = None, query: str = '', order: str = 'title'):
        with self._transaction() as db:
            metadata = self._metadata(db)
            where = []
            params = []
            tokens = (query or '').split()
            if tokens:
                visible_title = "_explorer_summary_fold(_explorer_summary_sort_key('title', common_json, tags_json, display_label, id))"
                visible_artist = "_explorer_summary_fold(_explorer_summary_search_key('artist', common_json, tags_json, display_label, id))"
                for token in tokens:
                    literal = self._summary_fold(token).replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
                    like = '%' + literal + '%'
                    where.append(f"({visible_title} LIKE ? ESCAPE '\\' OR {visible_artist} LIKE ? ESCAPE '\\')")
                    params.extend([like, like])
            match_where_sql = ('WHERE ' + ' AND '.join(where)) if where else ''
            match_params = tuple(params)
            cursor_key, cursor_id = self._decode_summary_cursor(cursor)
            order_key = order if order in ('title', 'artist') else 'id'
            order_expr = '_explorer_summary_fold(sort_key)' if order_key in ('title', 'artist') else 'id'
            cursor_where_sql = ''
            cursor_params = ()
            if cursor_key is not None and cursor_id is not None:
                cursor_where_sql = 'WHERE (page_order > ? OR (page_order = ? AND id > ?))'
                cursor_params = (cursor_key, cursor_key, cursor_id)
            base = """
                WITH first_location AS (
                    SELECT track_id, min(path) AS path, count(*) AS available_locations
                    FROM locations WHERE available=1 GROUP BY track_id
                ), summary AS (
                    SELECT t.id, t.sha256, t.size, COALESCE(first_location.path, '') AS first_path,
                           COALESCE(first_location.available_locations, 0) AS available_locations,
                           COALESCE(tm.common_json, '[]') AS common_json,
                           COALESCE(tm.tags_json, '[]') AS tags_json,
                           CASE WHEN COALESCE(first_location.path, '') = '' THEN '' ELSE _explorer_basename(first_location.path) END AS display_label
                    FROM tracks t
                    LEFT JOIN track_audio a ON a.track_id=t.id
                    LEFT JOIN first_location ON first_location.track_id=t.id
                    LEFT JOIN track_metadata tm ON tm.track_id=t.id
                    WHERE """ + _ACTIVE_CANDIDATE_PREDICATE + """
                )
                SELECT id, sha256, size, first_path, available_locations, common_json, tags_json, display_label,
                       _explorer_summary_sort_key(?, common_json, tags_json, display_label, id) AS sort_key
                FROM summary
            """
            select_order_key_params = (order_key,) if order_key in ('title', 'artist') else ('id',)
            matched = base + match_where_sql
            # The window subquery is materialized once: the whole-match count and
            # page/cursor filtering share a single eligibility/search/sort pass.
            rows = db.execute(
                f'SELECT * FROM (SELECT matched.*, count(*) OVER () AS match_count, {order_expr} AS page_order '
                f'FROM ({matched}) matched) {cursor_where_sql} ORDER BY page_order, id LIMIT ?',
                (*select_order_key_params, *match_params, *cursor_params, limit + 1)).fetchall()
            if rows:
                track_count = rows[0][9]
            elif cursor_where_sql:
                # Past the last page: the count still covers every match.
                track_count = db.execute('SELECT count(*) FROM (' + matched + ')',
                                         (*select_order_key_params, *match_params)).fetchone()[0]
            else:
                track_count = 0
            rows = [row[:9] for row in rows]
            page_rows = rows[:limit]
            summaries = tuple(self._summary_from_row(row) for row in page_rows)
            next_cursor = None
            if len(rows) > limit and page_rows:
                last = page_rows[-1]
                key = last[8] if order_key in ('title', 'artist') else last[0]
                next_cursor = self._encode_summary_cursor(self._summary_fold(key), last[0])
            return metadata, track_count, summaries, next_cursor

    def track_summaries(self, track_ids):
        """#243: the named active tracks' summaries, read by ID; only those rows are read and checked."""
        if not track_ids:
            return ()
        marks = ','.join('?' * len(track_ids))
        with self._transaction() as db:
            rows = db.execute(f"""
                WITH first_location AS (
                    SELECT track_id, min(path) AS path, count(*) AS available_locations
                    FROM locations WHERE available=1 AND track_id IN ({marks}) GROUP BY track_id
                )
                SELECT t.id, t.sha256, t.size, COALESCE(first_location.path, ''),
                       COALESCE(first_location.available_locations, 0),
                       COALESCE(tm.common_json, '[]'), COALESCE(tm.tags_json, '[]'),
                       CASE WHEN COALESCE(first_location.path, '') = '' THEN ''
                            ELSE _explorer_basename(first_location.path) END, ''
                FROM tracks t
                LEFT JOIN track_audio a ON a.track_id=t.id
                LEFT JOIN first_location ON first_location.track_id=t.id
                LEFT JOIN track_metadata tm ON tm.track_id=t.id
                WHERE t.id IN ({marks}) AND {_ACTIVE_CANDIDATE_PREDICATE}
            """, (*track_ids, *track_ids)).fetchall()
            return tuple(self._summary_from_row(row) for row in rows)

    def candidate_snapshot(self):
        with self._transaction() as db:
            metadata = self._metadata(db)
            ids = tuple(row[0] for row in db.execute(f'SELECT t.id {_ACTIVE_CANDIDATES_FROM} ORDER BY t.id'))
            return metadata, tuple(self._read_track(db, track_id) for track_id in ids)

    def mood_axis_graph_snapshot(self, mood: str | None = None, sparse_k: int = 10):
        # Selected scope: active tracks, their current evidence and the current
        # build/snapshots/mirrors are validated as consumed; history is not.
        with self._transaction() as db:
            metadata = self._metadata(db)
            if int(metadata.get('schema_version', 0)) < 8:
                return None
            warm_edges = self._current_positioned_graph_edges(db, sparse_k)
            records = self._compact_graph_tracks(db)
            graph = _build_mood_axis_graph(metadata, records, self, sparse_k, mood, warm_edges=warm_edges)
            # Evidence delivery is deliberately unordered; public DTO order remains
            # the original active-track order (ORDER BY t.id).
            return replace(graph,
                           positioned=tuple(sorted(graph.positioned, key=lambda node: node.track_id)),
                           unpositioned=tuple(sorted(graph.unpositioned, key=lambda node: node.track_id)))

    def current_graph_edges(self, sparse_k: int | None = None):
        with self._transaction() as db:
            return self._current_graph_edges(db, sparse_k)

    def playlist_mood_evidence(self, mood: str | None):
        """Arousal and a selected mood's score from compact graph evidence (#123).

        Only the two summaries are extracted in SQL: full stage payloads carry
        windows and raw predictions that would take seconds to parse.
        """
        with self._transaction() as db:
            if _database_schema_version(db) < 9:
                return {}
            rows = db.execute('''
                WITH latest_run AS (
                    SELECT track_id, run_id FROM (
                        SELECT rt.track_id, r.id AS run_id,
                               row_number() OVER (PARTITION BY rt.track_id ORDER BY r.rowid DESC) AS rn
                        FROM run_tracks rt JOIN runs r ON r.id=rt.run_id
                    ) WHERE rn=1
                )
                SELECT g.track_id,
                       json_extract(g.evidence_json, '$.features.energy.summary_values'),
                       json_extract(g.evidence_json, '$.features.energy.provenance'),
                       (SELECT json_extract(m.value, '$[1]')
                          FROM json_each(g.evidence_json, '$.features.mood.summary_values') m
                         WHERE json_extract(m.value, '$[0]')=?),
                       json_extract(g.evidence_json, '$.features.mood.provenance')
                FROM graph_feature_evidence g
                JOIN latest_run lr ON lr.track_id=g.track_id AND lr.run_id=g.run_id
                WHERE g.is_current=1
            ''', (mood,)).fetchall()
        return {track_id: PlaylistMoodEvidence(_arousal(energy_values, energy_provenance),
                                               _mood_score(mood_score, mood_provenance) if mood else None)
                for track_id, energy_values, energy_provenance, mood_score, mood_provenance in rows}

    def related_track_edges(self, sparse_k: int):
        """The edges the mood-axis graph shows, without building its nodes (#129)."""
        with self._transaction() as db:
            if int(self._metadata(db)['schema_version']) < 8:
                return self._current_graph_edges(db, None)
            return self._current_positioned_graph_edges(db, sparse_k)

    def current_positioned_graph_edges(self, sparse_k: int | None = None):
        with self._transaction() as db:
            return self._current_positioned_graph_edges(db, sparse_k)

    def track_ids(self):
        with self._transaction() as db:
            return tuple(row[0] for row in db.execute(f'SELECT t.id {_ACTIVE_CANDIDATES_FROM} ORDER BY t.id'))

    def contains_active_track(self, track_id: str):
        with self._transaction() as db:
            row = db.execute(f'SELECT {_ACTIVE_CANDIDATE_PREDICATE} {_ACTIVE_CANDIDATE_JOIN} WHERE t.id=?',
                             (track_id,)).fetchone()
            return bool(row is not None and row[0])

    def saved_playlist_recipes(self):
        with self._transaction() as db:
            if _database_schema_version(db) < _PLAYLIST_RECIPES_SCHEMA:
                return ()
            rows = db.execute(f'SELECT {_SAVED_RECIPE_COLUMNS} FROM playlist_recipes ORDER BY name').fetchall()
            return tuple(_saved_playlist_recipe(row) for row in rows)

    def saved_playlist_recipe(self, name: str):
        with self._transaction() as db:
            if _database_schema_version(db) < _PLAYLIST_RECIPES_SCHEMA:
                return None
            row = db.execute(f'SELECT {_SAVED_RECIPE_COLUMNS} FROM playlist_recipes WHERE name=?', (name,)).fetchone()
            return None if row is None else _saved_playlist_recipe(row)

    def _validate_track_identity(self, track_id, sha256, size):
        if (not isinstance(track_id, str) or not _TRACK_ID_RE.fullmatch(track_id)
                or not isinstance(sha256, str) or not _SHA256_RE.fullmatch(sha256)
                or track_id != f'sha256:{sha256}'
                or not isinstance(size, int) or isinstance(size, bool) or size < 0):
            raise AnalysisError('Unexpected analysis database rows')

    def _validate_audio(self, duration, source, status, reason):
        if (not all(isinstance(value, str) for value in (source, status, reason))
                or (duration is not None and (not isinstance(duration, (int, float))
                    or isinstance(duration, bool) or not isfinite(duration)))):
            raise AnalysisError('Unexpected analysis database rows')
        if status != _expected_audio_status(duration, source) or reason != _duration_warning(duration, source):
            raise AnalysisError('Unexpected analysis database rows')

    def _active_candidate(self, track_id, sha256, size, duration, source, status, reason):
        self._validate_track_identity(track_id, sha256, size)
        self._validate_audio(duration, source, status, reason)
        return status == 'eligible'

    def available_audio_paths(self):
        with self._transaction() as db:
            paths = tuple(row[0] for row in db.execute(
                f'SELECT l.path FROM locations l JOIN tracks t ON t.id=l.track_id '
                f'LEFT JOIN track_audio a ON a.track_id=t.id '
                f'WHERE l.available=1 AND {_ACTIVE_CANDIDATE_PREDICATE} ORDER BY l.path'))
            if any(not isinstance(path, str) or not path for path in paths):
                raise AnalysisError('Unexpected analysis database rows')
            return paths

    def playlist_export_tracks(self):
        with self._connection() as db:
            db.execute('BEGIN')
            self._validate_compatibility(db)
            rows = db.execute(f'''
                WITH latest_run AS (
                    SELECT track_id, run_id FROM (
                        SELECT rt.track_id, r.id AS run_id,
                               row_number() OVER (PARTITION BY rt.track_id ORDER BY r.rowid DESC) AS rn
                        FROM run_tracks rt JOIN runs r ON r.id=rt.run_id
                        WHERE r.status='completed'
                    ) WHERE rn=1
                )
                SELECT al.track_id, s.result, al.path, a.duration_seconds,
                       COALESCE(tm.common_json, '[]'), COALESCE(tm.tags_json, '[]'), k.result
                FROM locations al
                JOIN tracks t ON t.id=al.track_id
                LEFT JOIN track_audio a ON a.track_id=t.id
                LEFT JOIN track_metadata tm ON tm.track_id=t.id
                JOIN latest_run lr ON lr.track_id=al.track_id
                JOIN stages s ON s.run_id=lr.run_id AND s.stage='bpm'
                LEFT JOIN stages k ON k.run_id=lr.run_id AND k.stage='key'
                WHERE al.available=1 AND {_ACTIVE_CANDIDATE_PREDICATE}
                ORDER BY al.track_id, al.path
            ''').fetchall()
            overridden = {}
            for track_id, field in db.execute('SELECT track_id, field FROM overrides ORDER BY track_id, field'):
                overridden.setdefault(track_id, []).append(field)
            candidates = []
            selected_track_ids = set()
            for track_id, bpm_payload, path, duration, common_json, tags_json, key_payload in rows:
                if not isinstance(path, str) or not path:
                    raise AnalysisError('Unexpected analysis database rows')
                if track_id in selected_track_ids:
                    continue
                bpm = _bpm_from_stage_payload(bpm_payload)
                if bpm is None:
                    selected_track_ids.add(track_id)
                    continue
                exists = Path(path).is_file()
                if not exists:
                    continue
                metadata = self._summary_metadata(common_json, tags_json)
                candidates.append(PlayableTrackCandidate(track_id, float(bpm), path, exists, True, True,
                                                         title=self._metadata_value(metadata, 'title') or '',
                                                         artist=self._metadata_value(metadata, 'artist') or '',
                                                         manual_overrides=tuple(overridden.get(track_id, ())),
                                                         duration_seconds=_playlist_duration(duration),
                                                         **_key_from_stage_payload(key_payload)))
                selected_track_ids.add(track_id)
            return tuple(candidates)

    def read_track(self, track_id: str):
        with self._transaction() as db:
            return self._read_track(db, track_id)

    def first_available_location(self, track_id: str) -> str | None:
        """The track's first available file path (#132), for an approved tag write; None when it has none."""
        with self._transaction() as db:
            row = db.execute('SELECT min(path) FROM locations WHERE track_id=? AND available=1', (track_id,)).fetchone()
        path = row[0] if row else None
        if path is not None and not isinstance(path, str):
            raise AnalysisError('Unexpected analysis database rows')
        return path

    def find_track(self, track_id: str):
        with self._transaction() as db:
            if db.execute('SELECT 1 FROM tracks WHERE id=?', (track_id,)).fetchone() is None:
                return None
            return self._read_track(db, track_id)

    def _current_graph_edges(self, db, requested_sparse_k=None):
        version = _database_schema_version(db)
        if version < 7:
            return None, ()
        current = self._current_build(db, version)
        action = 'Run music-analyzer graph build --database DB before loading the mood-axis graph.'
        if current is None:
            latest = db.execute('SELECT status,detail FROM graph_builds ORDER BY created_at DESC,rowid DESC LIMIT 1').fetchone()
            if latest is not None and latest[0] not in _build_statuses(version):
                raise AnalysisError('Unexpected analysis database rows')
            # The current-graph mirrors exist only alongside a current build;
            # leftovers contradict the pointer this read consults (O(1) probes).
            if db.execute('SELECT 1 FROM graph_edges LIMIT 1').fetchone() or (
                    version >= 8 and db.execute('SELECT 1 FROM graph_positioned_edges LIMIT 1').fetchone()):
                raise AnalysisError('Unexpected analysis database rows')
            if latest is None:
                return {'state': 'build_needed', 'source': 'graph_build_edges', 'reason': 'no completed warm graph snapshot', 'action': action}, ()
            if latest[0] == 'failed':
                return {'state': 'failed', 'source': 'graph_build_edges', 'reason': latest[1] or 'latest warm graph build failed', 'action': action}, ()
            if latest[0] in {'building', 'interrupted'}:
                return {'state': latest[0], 'source': 'graph_build_edges', 'reason': latest[1] or f'latest warm graph build is {latest[0]}', 'action': action}, ()
            return {'state': 'stale', 'source': 'graph_build_edges', 'reason': 'warm graph snapshot is not current', 'action': action}, ()
        build_id, edge_count, sparse_k, distance_policy, neighbour_policy = current
        if distance_policy != DISTANCE_POLICY_VERSION or neighbour_policy != NEIGHBOUR_POLICY_VERSION:
            return {'state': 'stale', 'source': 'graph_build_edges', 'reason': 'warm graph snapshot policy version is stale', 'action': action, 'build_id': build_id, 'distance_policy': distance_policy, 'edge_policy': neighbour_policy}, ()
        if requested_sparse_k is not None and int(sparse_k) != int(requested_sparse_k):
            return {'state': 'stale', 'source': 'graph_build_edges', 'reason': 'warm graph snapshot sparse_k does not match requested graph sparsity', 'action': action, 'build_id': build_id, 'stored_sparse_k': int(sparse_k), 'requested_sparse_k': int(requested_sparse_k)}, ()
        rows = self._validated_edge_rows(db, 'graph_build_edges', build_id)
        if len(rows) != edge_count or self._mirror_edge_rows(db, 'graph_edges') != rows:
            raise AnalysisError('Unexpected analysis database rows')
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
            for source, target, score, _distance, supported_count, edge_distance_policy, edge_neighbour_policy in rows
        )
        return status, edges

    def _current_build(self, db, version):
        """The one current build descriptor (bounded ambiguity check), or None."""
        current = db.execute('''
            SELECT id,status,edge_count,sparse_k,distance_policy_version,neighbour_policy_version
            FROM graph_builds WHERE is_current=1 LIMIT 2
        ''').fetchall()
        if not current:
            return None
        if len(current) > 1:
            raise AnalysisError('Unexpected analysis database rows')
        build_id, status, edge_count, sparse_k, distance_policy, neighbour_policy = current[0]
        if (status != 'completed' or not isinstance(build_id, str) or not build_id
                or not _non_negative_int(edge_count) or not _non_negative_int(sparse_k)
                or not isinstance(distance_policy, str) or not distance_policy
                or not isinstance(neighbour_policy, str) or not neighbour_policy):
            raise AnalysisError('Unexpected analysis database rows')
        return build_id, edge_count, sparse_k, distance_policy, neighbour_policy

    def _validated_edge_rows(self, db, table, build_id):
        if table not in ('graph_build_edges', 'graph_build_positioned_edges'):
            raise ValueError('Unsupported graph edge table')
        rows = tuple(db.execute(f'''
            SELECT {_EDGE_COLUMNS} FROM {table} WHERE build_id=? ORDER BY source_track_id,target_track_id
        ''', (build_id,)))
        for row in rows:
            _validate_edge_row(row)
        return rows

    def _mirror_edge_rows(self, db, table):
        if table not in ('graph_edges', 'graph_positioned_edges'):
            raise ValueError('Unsupported graph mirror table')
        return tuple(db.execute(f'SELECT {_EDGE_COLUMNS} FROM {table} ORDER BY source_track_id,target_track_id'))

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
        if snapshot is not None and not _non_negative_int(snapshot[0]):
            raise AnalysisError('Unexpected analysis database rows')
        if snapshot is None:
            if db.execute('SELECT 1 FROM graph_positioned_edges LIMIT 1').fetchone():
                raise AnalysisError('Unexpected analysis database rows')
            return {'state': 'build_needed', 'source': 'graph_build_positioned_edges', 'reason': 'exact positioned warm graph snapshot is not available for current build', 'action': action, 'build_id': build_id}, ()
        rows = self._validated_edge_rows(db, 'graph_build_positioned_edges', build_id)
        if len(rows) != snapshot[0] or self._mirror_edge_rows(db, 'graph_positioned_edges') != rows:
            raise AnalysisError('Unexpected analysis database rows')
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
            for source, target, score, _distance, supported_count, edge_distance_policy, edge_neighbour_policy in rows
        )
        return status, edges

    def _metadata(self, db):
        return {
            'application_id': db.execute('PRAGMA application_id').fetchone()[0],
            'schema_version': db.execute('PRAGMA user_version').fetchone()[0],
            'read_policy': 'bounded_read_transaction',
        }

    def _validate_latest_runs(self, db, version, latest_runs):
        """Validate the newest-run state that decides graph projection.

        latest_runs yields (track_id, run_id, status) for selected tracks. A run
        status must be supported, and (schema >= 9) a track's single current
        evidence row must belong to its newest run, which must be completed.
        Identity-only probes: no evidence payload is loaded here.
        """
        latest = {}
        for track_id, run_id, status in latest_runs:
            if run_id is not None and status not in ('running', 'completed', 'failed', 'interrupted'):
                raise AnalysisError('Unexpected analysis database rows')
            latest[track_id] = (run_id, status)
        if version < 9:
            return
        seen = set()
        for track_chunk in _chunked(tuple(latest), 500):
            placeholders = ','.join('?' for _track in track_chunk)
            for track_id, run_id in db.execute(
                    f'SELECT track_id,run_id FROM graph_feature_evidence '
                    f'WHERE is_current=1 AND track_id IN ({placeholders})', track_chunk):
                if track_id in seen or latest.get(track_id) != (run_id, 'completed'):
                    raise AnalysisError('Unexpected analysis database rows')
                seen.add(track_id)

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
                FROM locations WHERE available=1 GROUP BY track_id
            ), latest_run AS (
                SELECT track_id, run_id, status, detail FROM (
                    SELECT rt.track_id, r.id AS run_id, r.status AS status, r.detail AS detail,
                           row_number() OVER (PARTITION BY rt.track_id ORDER BY r.rowid DESC) AS rn
                    FROM run_tracks rt JOIN runs r ON r.id=rt.run_id
                    JOIN track_audio at ON at.track_id=rt.track_id AND at.status='eligible'
                ) WHERE rn=1
            )
            SELECT t.id, t.sha256, t.size,
                   COALESCE(first_location.path, '') AS first_path,
                   COALESCE(first_location.available_locations, 0) AS available_locations,
                   latest_run.run_id, latest_run.status, latest_run.detail,
                   COALESCE(tm.common_json, '[]'), COALESCE(tm.tags_json, '[]'), COALESCE(tm.warnings_json, '[]'),
                   a.duration_seconds, a.duration_source,
                   {evidence_columns}
            FROM tracks t
            LEFT JOIN track_audio a ON a.track_id=t.id
            LEFT JOIN first_location ON first_location.track_id=t.id
            LEFT JOIN latest_run ON latest_run.track_id=t.id
            {evidence_join}
            LEFT JOIN track_metadata tm ON tm.track_id=t.id
            WHERE {_ACTIVE_CANDIDATE_PREDICATE}
            ORDER BY t.id
        """).fetchall()
        self._validate_latest_runs(db, version, ((row[0], row[5], row[6]) for row in rows))
        # Preserve the legacy raw-stage fallback; compact evidence never enters
        # this cache and is projected one validated row at a time below.
        stages_by_run = {}
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
                        JOIN track_audio at ON at.track_id=rt.track_id AND at.status='eligible'
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
            JOIN track_audio at ON at.track_id=o.track_id AND at.status='eligible'
            ORDER BY o.track_id,o.field
        """):
            if not isinstance(field, str) or not isinstance(value, str):
                raise AnalysisError('Unexpected analysis database rows')
            overrides_by_track.setdefault(track_id, []).append((field, value))
        compact_evidence_rows = tuple(
            (row[0], row[5], row[13], row[14]) for row in rows
            if row[5] is not None and row[6] == 'completed' and row[13] is not None
        )
        for _track_id, _run_id, _fingerprint, evidence_json_size in compact_evidence_rows:
            if not isinstance(_fingerprint, str) or not _SHA256_RE.fullmatch(_fingerprint):
                raise AnalysisError('Unexpected analysis database rows')
            if evidence_json_size is None:
                raise AnalysisError('Invalid stored graph feature evidence')
            if int(evidence_json_size) > _GRAPH_FEATURE_EVIDENCE_JSON_LIMIT:
                raise AnalysisError('Oversized stored graph feature evidence (16 MiB limit)')
        compact_evidence_by_identity = {
            (track_id, run_id): fingerprint
            for track_id, run_id, fingerprint, _size in compact_evidence_rows
        }
        rows_by_identity = {(row[0], row[5]): row for row in rows
                            if (row[0], row[5]) in compact_evidence_by_identity}

        def record_from_row(row, stages):
            (track_id, sha256, size, first_path, available_locations, run_id, status, detail,
             common_json, tags_json, warnings_json, duration_seconds, duration_source,
             evidence_fingerprint, evidence_json_size) = row
            if (not isinstance(first_path, str) or not isinstance(available_locations, int)
                    or available_locations < 0 or (run_id is not None and not isinstance(detail, (str, type(None))))):
                raise AnalysisError('Unexpected analysis database rows')
            try:
                metadata = self._metadata_from_json(common_json, tags_json, warnings_json, (duration_seconds, duration_source))
            except (TypeError, ValueError, json.JSONDecodeError) as error:
                raise AnalysisError('Invalid stored graph feature evidence') from error
            run = None
            if run_id is not None:
                run = AnalysisReport(run_id, status, tuple(stages), detail or '')
            return ExplorerStoredTrack(
                track_id,
                sha256,
                size,
                Path(first_path).name if first_path else '',
                int(available_locations),
                run,
                tuple(overrides_by_track.get(track_id, ())),
                metadata,
            )

        if version >= 9:
            for track_id, run_id, payload in self._iter_current_graph_feature_rows(db, compact_evidence_by_identity):
                row = rows_by_identity.pop((track_id, run_id), None)
                if row is not None:
                    # The application consumes and projects this temporary record
                    # before this generator requests another evidence row.
                    yield record_from_row(row, self._stages_from_graph_feature_payload(payload))
                del payload, row
            if rows_by_identity:
                raise AnalysisError('Invalid stored graph feature evidence')
        for row in rows:
            if (row[0], row[5]) not in compact_evidence_by_identity:
                yield record_from_row(row, tuple(stages_by_run.get(row[5], ())))

    def _iter_current_graph_feature_rows(self, db, fingerprints_by_identity):
        """Validate and yield only the selected current evidence rows."""
        loaded_identities = set()
        for payload_chunk in self._iter_graph_feature_evidence_payload_chunks(
                db, tuple(fingerprints_by_identity), current_only=True):
            for track_id, run_id, evidence_json in payload_chunk:
                identity = (track_id, run_id)
                if identity in loaded_identities or identity not in fingerprints_by_identity:
                    raise AnalysisError('Unexpected analysis database rows')
                loaded_identities.add(identity)
                try:
                    payload = json.loads(evidence_json)
                    validate_graph_feature_evidence_payload(track_id, run_id, fingerprints_by_identity[identity], payload)
                except (TypeError, KeyError, ValueError, RecursionError) as error:
                    raise AnalysisError('Unexpected analysis database rows') from error
                yield track_id, run_id, payload
                # Do not keep the previous raw/decoded row while advancing the cursor.
                del payload, evidence_json
        if loaded_identities != set(fingerprints_by_identity):
            raise AnalysisError('Unexpected analysis database rows')

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
        except (ValueError, KeyError, TypeError, IndexError, AttributeError, RecursionError) as error:
            raise AnalysisError('Invalid stored stage') from error

    def _read_track(self, db, track_id: str):
        track = db.execute('SELECT id,sha256,size FROM tracks WHERE id=?', (track_id,)).fetchone()
        if not track:
            raise AnalysisError('Unknown explorer track')
        self._validate_track_identity(*track)
        location_rows = tuple(db.execute('SELECT path,mtime_ns,format FROM locations WHERE track_id=? AND available=1 ORDER BY path', (track_id,)))
        for path, mtime_ns, audio_format in location_rows:
            if (not isinstance(path, str) or not isinstance(mtime_ns, int)
                    or not isinstance(audio_format, str)):
                raise AnalysisError('Unexpected analysis database rows')
        locations = tuple(row[0] for row in location_rows)
        display_label = Path(locations[0]).name if locations else ''
        # Orphan links (no runs row) sort first, so ANY orphan link for the
        # selected track is consumed and rejected below, not skipped.
        row = db.execute('SELECT t.run_id,r.status,r.detail,r.id FROM run_tracks t LEFT JOIN runs r ON r.id=t.run_id '
                         'WHERE t.track_id=? ORDER BY r.id IS NULL DESC, r.rowid DESC LIMIT 1', (track_id,)).fetchone()
        run = None
        if row:
            if (not isinstance(row[0], str) or not row[0] or row[3] != row[0]
                    or row[1] not in ('running', 'completed', 'failed', 'interrupted')
                    or not isinstance(row[2], str)):
                raise AnalysisError('Unexpected analysis database rows')
            stages = []
            size_expression = _stage_result_size_expression()
            stage_sizes = tuple(db.execute(f'SELECT stage,{size_expression} FROM stages WHERE run_id=? ORDER BY stage', (row[0],)))
            for _stage, size in stage_sizes:
                if not isinstance(_stage, str) or not isinstance(size, int) or size < 0:
                    raise AnalysisError('Invalid stored stage')
                if int(size) > 16 * 1024 * 1024:
                    raise AnalysisError('Oversized stored stage (16 MiB limit)')
            for stage, size in stage_sizes:
                payload_row = db.execute('SELECT result FROM stages WHERE run_id=? AND stage=?', (row[0], stage)).fetchone()
                if payload_row is None:
                    raise AnalysisError('Unexpected analysis database rows')
                payload = payload_row[0]
                stages.append(self._stage_from_payload(stage, size, payload))
            run = AnalysisReport(row[0], row[1], tuple(stages), row[2])
        overrides = tuple(db.execute('SELECT field,value FROM overrides WHERE track_id=? ORDER BY field', (track_id,)))
        if any(not isinstance(field, str) or not isinstance(value, str) for field, value in overrides):
            raise AnalysisError('Unexpected analysis database rows')
        metadata = self._read_metadata(db, track_id)
        return ExplorerStoredTrack(track[0], track[1], track[2], display_label, len(locations), run, overrides, metadata)


    def _summary_from_row(self, row):
        track_id, _sha, _size, first_path, available_locations, common_json, tags_json, display_label, _sort_key = row
        self._validate_track_identity(track_id, _sha, _size)
        if (not isinstance(first_path, str) or not isinstance(display_label, str)
                or not isinstance(available_locations, int) or available_locations < 0):
            raise AnalysisError('Unexpected analysis database rows')
        label = Path(first_path).name if first_path else display_label
        metadata = self._summary_metadata(common_json, tags_json)
        title = self._metadata_value(metadata, 'title') or label or track_id
        artist = self._metadata_value(metadata, 'artist') or 'Unknown artist'
        return ExplorerTrackSummary(track_id, title, artist, label, int(available_locations))

    def _metadata_from_json(self, common_json, tags_json, warnings_json, audio):
        try:
            decoded = []
            for common, payload in ((True, common_json), (False, tags_json)):
                pairs = json.loads(payload)
                if not isinstance(pairs, list) or any(
                    not isinstance(pair, list) or len(pair) != 2 for pair in pairs
                ):
                    raise ValueError('Invalid metadata pairs')
                for key, value in pairs:
                    if not isinstance(key, str) or not (
                        (common and isinstance(value, str)) or
                        (isinstance(value, list) and all(isinstance(text, str) for text in value))
                    ):
                        raise ValueError('Invalid metadata values')
                decoded.append(tuple((key, tuple(value) if isinstance(value, list) else value)
                                     for key, value in pairs))
            warnings = json.loads(warnings_json)
            if not isinstance(warnings, list) or not all(isinstance(text, str) for text in warnings):
                raise ValueError('Invalid metadata warnings')
            return TrackMetadata(decoded[0], decoded[1], tuple(warnings),
                                 audio[0] if audio else None, audio[1] if audio else '')
        except (TypeError, ValueError, RecursionError):
            raise AnalysisError('Invalid stored metadata') from None

    def _summary_metadata(self, common_json, tags_json):
        return self._metadata_from_json(common_json, tags_json, '[]', None)

    def _summary_sort_key(self, order, common_json, tags_json, display_label, track_id):
        if order not in ('title', 'artist'):
            # ID ordering does not consume metadata, including its lookahead.
            return str(track_id or '')
        metadata = self._summary_metadata(common_json, tags_json)
        if order == 'artist':
            return self._metadata_value(metadata, 'artist') or 'Unknown artist'
        return self._metadata_value(metadata, 'title') or str(display_label or '') or str(track_id or '')

    def _summary_search_key(self, field, common_json, tags_json, display_label, track_id):
        if field == 'title':
            return self._summary_sort_key('title', common_json, tags_json, display_label, track_id)
        if field == 'artist':
            metadata = self._summary_metadata(common_json, tags_json)
            return self._metadata_value(metadata, 'artist') or ''
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
        if audio is None:
            raise AnalysisError('Unexpected analysis database rows')
        self._validate_audio(*audio)
        if not row:
            return TrackMetadata(duration_seconds=audio[0], duration_source=audio[1])
        return self._metadata_from_json(row[0], row[1], row[2], audio)

    def _check_path(self):
        if self._path.stem.lower() == 'mixxx' or any(p.is_symlink() for p in (self._path, *self._path.parents)):
            raise AnalysisError('Refusing Mixxx-named or symlink database path')
        if not self._path.exists():
            raise AnalysisError('Explorer database must already exist')

    @contextmanager
    def _connection(self):
        self._check_path()
        db = None
        metadata_failed = False
        candidate_failed = False

        def summary_callback(callback):
            def evaluate(*args):
                nonlocal metadata_failed
                try:
                    return callback(*args)
                except AnalysisError:
                    # sqlite3 masks UDF exceptions. Keep only a category flag,
                    # scoped to this connection, never raw metadata or state on
                    # the shared repository instance.
                    metadata_failed = True
                    raise
            return evaluate

        def active_candidate_callback(*args):
            nonlocal candidate_failed
            try:
                return self._active_candidate(*args)
            except AnalysisError:
                candidate_failed = True
                raise

        try:
            uri = self._path.as_uri() + '?mode=ro'
            db = sqlite3.connect(uri, uri=True, timeout=1)
            db.create_function('_explorer_active_candidate', 7, active_candidate_callback)
            db.create_function('_explorer_basename', 1, lambda value: Path(str(value)).name if value else '')
            db.create_function('_explorer_summary_sort_key', 5, summary_callback(self._summary_sort_key))
            db.create_function('_explorer_summary_search_key', 5, summary_callback(self._summary_search_key))
            db.create_function('_explorer_summary_fold', 1, self._summary_fold)
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('PRAGMA query_only=ON')
            yield db
        except (sqlite3.Error, OSError) as error:
            if candidate_failed:
                raise AnalysisError('Unexpected analysis database rows') from None
            if metadata_failed:
                raise AnalysisError('Invalid stored metadata') from None
            raise AnalysisError('Analysis database error') from error
        finally:
            if db is not None:
                db.close()

    @contextmanager
    def _transaction(self):
        # Compatibility guard only; each read validates what it consumes (issue88).
        with self._connection() as db:
            db.execute('BEGIN')
            self._validate_compatibility(db)
            yield db
            db.execute('COMMIT')

    def _validate_compatibility(self, db, version=None):
        # A compatibility guard, not a certificate of schema or retained history.
        if version is None:
            version = db.execute('PRAGMA user_version').fetchone()[0]
        if db.execute('PRAGMA application_id').fetchone()[0] != APPLICATION_ID or version not in (6, 7, 8, 9, 10, 11, 12):
            raise AnalysisError('Not a supported music-analyzer analysis database')

