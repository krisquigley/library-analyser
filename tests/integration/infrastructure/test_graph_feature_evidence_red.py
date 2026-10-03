from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from music_analyzer.application.dto.analysis import AnalysisError, AudioSource, StageResult
from music_analyzer.application.dto.catalogue import Inventory, ScannedFile, TrackMetadata
from music_analyzer.domain.analysis import ScoreSummary
from music_analyzer.domain.catalogue import FileIdentity
from music_analyzer.domain.projection import ProjectionEdge
from music_analyzer.infrastructure.persistence.analysis import APPLICATION_ID, SQLiteAnalysisRepository
from music_analyzer.infrastructure.persistence.explorer_readonly import ReadOnlyExplorerSQLiteRepository


GRAPH_FEATURE_TABLE_HINTS = {
    'track_id',
    'run_id',
    'fingerprint',
    'is_current',
}
GRAPH_FEATURE_PAYLOAD_COLUMNS = ('evidence_json', 'features_json', 'feature_json')


def _register_track(repository, suffix='a', location='/music/song.flac'):
    identity = FileIdentity(suffix * 64, 123)
    repository.register(Inventory('/music', (
        ScannedFile(location, identity, 1, 'flac', TrackMetadata(duration_seconds=180.0, duration_source='mutagen')),
    ), (), True))
    return identity


def _graph_relevant_stages():
    return (
        StageResult('bpm', (('algorithm', 'test-bpm'),), 'steady enough for graph feature', (('bpm', 124.0),)),
        StageResult('key', (('algorithm', 'test-key'),), 'classifier top label only', (('key', '8A'),)),
        StageResult('genres', (('algorithm', 'test-genre'),), 'multi-label summary', (('genre', 'house'), ('genre', 'deep house'))),
        StageResult(
            'mood',
            (('algorithm', 'test-mood'),),
            'uncalibrated mood scores',
            summary=ScoreSummary(('happy', 'dark'), (0.75, 0.20), (0.70, 0.10), (0.80, 0.30), 1.0),
        ),
        StageResult(
            'energy',
            (('algorithm', 'test-energy'),),
            'uncalibrated energy score',
            summary=ScoreSummary(('energy',), (0.66,), (0.60,), (0.70,), 1.0),
        ),
    )


def _complete_graph_relevant_run(repository, identity, location='/music/song.flac'):
    run_id = repository.start(AudioSource(location, identity.track_id))
    for stage in _graph_relevant_stages():
        repository.save_stage(run_id, stage)
    repository.finish(run_id, 'completed', '')
    return run_id


def _graph_feature_table(db):
    candidates = []
    for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
        columns = {row[1] for row in db.execute(f'PRAGMA table_info({table})')}
        if GRAPH_FEATURE_TABLE_HINTS.issubset(columns) and any(column in columns for column in GRAPH_FEATURE_PAYLOAD_COLUMNS):
            candidates.append((table, columns))
    if not candidates:
        raise AssertionError(
            'schema v9 must expose a compact per-track graph feature evidence table with '
            'track_id, run_id, fingerprint, is_current and a compact evidence JSON payload column'
        )
    if len(candidates) != 1:
        raise AssertionError(f'expected one graph feature evidence table, found {candidates!r}')
    return candidates[0]


def _current_graph_feature_rows(db):
    table, columns = _graph_feature_table(db)
    payload_column = next(column for column in GRAPH_FEATURE_PAYLOAD_COLUMNS if column in columns)
    return tuple(db.execute(
        f'SELECT track_id,run_id,fingerprint,{payload_column} FROM {table} WHERE is_current=1 ORDER BY track_id'
    ))


class GraphFeatureEvidencePersistenceRedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'analysis.sqlite'

    def test_v8_migrates_to_v9_without_losing_catalogue_runs_stages_graph_history_or_overrides(self):
        repository = SQLiteAnalysisRepository(str(self.path))
        identity = _register_track(repository)
        run_id = _complete_graph_relevant_run(repository, identity)
        repository.set_override(identity.track_id, 'key', '9A')
        other_identity = _register_track(repository, 'b', '/music/other.flac')
        build_id = repository.replace_graph_snapshot((ProjectionEdge(identity.track_id, other_identity.track_id, 0.25, 2),), 10, 'source-fp')

        SQLiteAnalysisRepository(str(self.path))

        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('PRAGMA application_id').fetchone()[0], APPLICATION_ID)
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 9)
            self.assertEqual(db.execute('SELECT status FROM runs WHERE id=?', (run_id,)).fetchone(), ('completed',))
            self.assertEqual(db.execute('SELECT count(*) FROM stages WHERE run_id=?', (run_id,)).fetchone(), (5,))
            self.assertEqual(db.execute('SELECT value FROM overrides WHERE track_id=? AND field=?', (identity.track_id, 'key')).fetchone(), ('9A',))
            self.assertEqual(db.execute('SELECT id,is_current,source_fingerprint FROM graph_builds WHERE id=?', (build_id,)).fetchone(), (build_id, 1, 'source-fp'))
            self.assertEqual(db.execute('SELECT count(*) FROM graph_build_edges WHERE build_id=?', (build_id,)).fetchone(), (1,))
        self.assertEqual(ReadOnlyExplorerSQLiteRepository(str(self.path)).track_ids(), (identity.track_id, other_identity.track_id))

    def test_completed_run_persists_current_compact_graph_feature_evidence_with_fingerprint(self):
        repository = SQLiteAnalysisRepository(str(self.path))
        identity = _register_track(repository)
        run_id = _complete_graph_relevant_run(repository, identity)

        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 9)
            rows = _current_graph_feature_rows(db)

        self.assertEqual(len(rows), 1)
        track_id, evidence_run_id, fingerprint, payload = rows[0]
        self.assertEqual((track_id, evidence_run_id), (identity.track_id, run_id))
        self.assertRegex(fingerprint, r'^[0-9a-f]{64}$')
        compact = json.loads(payload)
        self.assertEqual(compact['track_id'], identity.track_id)
        self.assertEqual(compact['run_id'], run_id)
        self.assertEqual(compact['feature_contract_version'], 'graph-feature-evidence-v1')
        self.assertEqual(set(compact['features']), {'bpm', 'key', 'genres', 'mood', 'energy'})

    def test_failed_latest_run_does_not_serve_older_completed_evidence_as_current(self):
        repository = SQLiteAnalysisRepository(str(self.path))
        identity = _register_track(repository)
        completed_run = _complete_graph_relevant_run(repository, identity)
        failed_run = repository.start(AudioSource('/music/song.flac', identity.track_id))
        repository.save_stage(failed_run, StageResult('bpm', (('algorithm', 'test-bpm'),), 'partial', (('bpm', 90.0),)))
        repository.finish(failed_run, 'failed', 'key: unavailable')

        with closing(sqlite3.connect(self.path)) as db:
            rows = _current_graph_feature_rows(db)
            all_rows = tuple(db.execute('SELECT status FROM runs WHERE id IN (?,?) ORDER BY rowid', (completed_run, failed_run)))

        self.assertEqual(all_rows, (('completed',), ('failed',)))
        self.assertEqual(rows, ())

    def test_failed_finish_rolls_back_without_half_current_feature_evidence(self):
        repository = SQLiteAnalysisRepository(str(self.path))
        identity = _register_track(repository)
        run_id = repository.start(AudioSource('/music/song.flac', identity.track_id))
        for stage in _graph_relevant_stages():
            repository.save_stage(run_id, stage)
        with closing(sqlite3.connect(self.path)) as db:
            table, columns = _graph_feature_table(db)
            blocker = f'block_{table}_insert'
            db.execute(f"CREATE TRIGGER {blocker} BEFORE INSERT ON {table} BEGIN SELECT RAISE(ABORT, 'forced feature evidence insert failure'); END")
            db.commit()

        with self.assertRaises(AnalysisError):
            repository.finish(run_id, 'completed', '')

        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT status FROM runs WHERE id=?', (run_id,)).fetchone(), ('running',))
            self.assertEqual(_current_graph_feature_rows(db), ())
