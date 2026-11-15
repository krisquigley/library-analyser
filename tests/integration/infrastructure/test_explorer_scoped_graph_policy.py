"""Issue88 R2: graph/candidate/projection/export reads validate selected scope.

The current graph build, its full/positioned snapshots and mirrors, and current
evidence for active tracks are consumed and stay fail-closed. Unrelated
historical builds, historical evidence payloads and schema topology are not
audited on ordinary requests (explicit D3 `music-analyzer integrity` does that).

External SQL edits below are NOT supported-writer defects; they model unrelated
old/external damage versus damage to data a request actually consumes.
"""
from contextlib import closing
import sqlite3
import tempfile
import unittest
from pathlib import Path

from music_analyzer.application.dto.analysis import StageResult
from music_analyzer.application.use_cases.graph_feature_evidence import build_graph_feature_evidence
from music_analyzer.domain.analysis import ScoreSummary
from music_analyzer.infrastructure.persistence import explorer_readonly as analyzer
from music_analyzer.infrastructure.persistence.integrity import SQLiteIntegrityScanner
from music_explorer.infrastructure import explorer_readonly as standalone
from tests.integration.infrastructure.integrity_d2_public_fixture import (
    CURRENT_BUILD, OLD_BUILD, STAMP, create_public_graph_database,
)
from tests.integration.infrastructure.test_explorer_scoped_read_policy import observe_sql

MIRRORS = (analyzer, standalone)
HISTORICAL_RUN = 'public-historical-run-1'
STAGES = (
    StageResult('bpm', (), '', (('bpm', 120.0),)),
    StageResult('key', (), '', (('key', '8A'),)),
    StageResult('genres', (), '', (('genre', 'house'),)),
    StageResult('mood', (), '', summary=ScoreSummary(('happy',), (0.8,), (0.7,), (0.9,), 1.0)),
    StageResult('energy', (), '', summary=ScoreSummary(('energy',), (0.6,), (0.5,), (0.7,), 1.0)),
)


def create_fixture(path):
    identities = create_public_graph_database(path)
    with closing(sqlite3.connect(path)) as db, db:
        # Older (lower rowid) completed run with retained historical evidence.
        db.execute('INSERT INTO runs(rowid,id,location,status,detail,created_at) VALUES(?,?,?,?,?,?)',
                   (-1, HISTORICAL_RUN, '/public/d1-fixture/track-1.flac', 'completed', '', STAMP))
        db.execute('INSERT INTO run_tracks(run_id,track_id) VALUES(?,?)', (HISTORICAL_RUN, identities[0]))
        evidence = build_graph_feature_evidence(identities[0], HISTORICAL_RUN, STAGES)
        db.execute('INSERT INTO graph_feature_evidence(track_id,run_id,fingerprint,evidence_json,is_current,created_at) '
                   'VALUES(?,?,?,?,?,?)', (identities[0], HISTORICAL_RUN, evidence.fingerprint, evidence.payload_json(), 0, STAMP))
    return identities


def change(path, *statements):
    with closing(sqlite3.connect(path)) as db, db:
        db.execute('PRAGMA foreign_keys=OFF')
        db.execute('PRAGMA ignore_check_constraints=ON')
        for sql, params in statements:
            db.execute(sql, params)


UNRELATED = {
    'historical_evidence_json': (
        ('UPDATE graph_feature_evidence SET evidence_json=? WHERE run_id=?', ('{', HISTORICAL_RUN)),),
    'historical_build_edge_count': (
        ('UPDATE graph_builds SET edge_count=5 WHERE id=?', (OLD_BUILD,)),),
    'historical_build_edge_row': (
        ('UPDATE graph_build_edges SET score=7.0 WHERE build_id=?', (OLD_BUILD,)),),
    'historical_positioned_snapshot_count': (
        ('UPDATE graph_build_positioned_snapshots SET edge_count=9 WHERE build_id=?', (OLD_BUILD,)),),
    'unrelated_schema_object': (
        ('CREATE TABLE owner_notes(id INTEGER PRIMARY KEY, note TEXT)', ()),),
}

CONSUMED = {
    'current_evidence_json': (
        ('UPDATE graph_feature_evidence SET evidence_json=? WHERE is_current=1 AND run_id=?', ('{', 'public-run-1')),),
    'current_evidence_fingerprint': (
        ('UPDATE graph_feature_evidence SET fingerprint=? WHERE is_current=1 AND run_id=?', ('0' * 64, 'public-run-1')),),
    'current_build_edge_count': (
        ('UPDATE graph_builds SET edge_count=5 WHERE id=?', (CURRENT_BUILD,)),),
    'current_build_edge_row': (
        ('UPDATE graph_build_edges SET score=7.0 WHERE build_id=?', (CURRENT_BUILD,)),),
    'current_positioned_snapshot_count': (
        ('UPDATE graph_build_positioned_snapshots SET edge_count=9 WHERE build_id=?', (CURRENT_BUILD,)),),
    'current_full_mirror': (
        ('UPDATE graph_edges SET supported_group_count=2', ()),),
    'current_positioned_mirror': (
        ('UPDATE graph_positioned_edges SET supported_group_count=2', ()),),
    'ambiguous_current_build': (
        ('DROP INDEX idx_graph_builds_one_current', ()),
        ('UPDATE graph_builds SET is_current=1 WHERE id=?', (OLD_BUILD,)),),
}


def graph_reads(repo):
    reads = {
        'mood_axis_graph': lambda: repo.mood_axis_graph_snapshot(sparse_k=1),
        'current_graph_edges': lambda: repo.current_graph_edges(),
        'current_positioned_graph_edges': lambda: repo.current_positioned_graph_edges(1),
        'candidate_snapshot': repo.candidate_snapshot,
        'track_ids': repo.track_ids,
        'available_audio_paths': repo.available_audio_paths,
    }
    if hasattr(repo, 'playlist_export_tracks'):
        reads['playlist_export_tracks'] = repo.playlist_export_tracks
    if hasattr(repo, 'graph_source_tracks'):
        reads['graph_source_tracks'] = lambda: tuple(repo.graph_source_tracks())
    return reads


# Which consumed damage each read must reject (others do not consume it).
CONSUMERS = {
    'current_evidence_json': {'mood_axis_graph', 'graph_source_tracks'},
    'current_evidence_fingerprint': {'mood_axis_graph', 'graph_source_tracks'},
    'current_build_edge_count': {'mood_axis_graph', 'current_graph_edges', 'current_positioned_graph_edges'},
    'current_build_edge_row': {'mood_axis_graph', 'current_graph_edges', 'current_positioned_graph_edges'},
    'current_positioned_snapshot_count': {'mood_axis_graph', 'current_positioned_graph_edges'},
    'current_full_mirror': {'mood_axis_graph', 'current_graph_edges', 'current_positioned_graph_edges'},
    'current_positioned_mirror': {'mood_axis_graph', 'current_positioned_graph_edges'},
    'ambiguous_current_build': {'mood_axis_graph', 'current_graph_edges', 'current_positioned_graph_edges'},
}


class GraphFixture(unittest.TestCase):
    def fixture(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / 'public.sqlite'
        self.identities = create_fixture(path)
        return path

    def baseline(self, path):
        results = {}
        for module in MIRRORS:
            repo = module.ReadOnlyExplorerSQLiteRepository(str(path))
            results[module.__name__] = {name: read() for name, read in graph_reads(repo).items()}
        return results


class ScopedGraphPolicyControls(GraphFixture):
    def test_fixture_is_clean_and_ready(self):
        path = self.fixture()
        self.assertFalse(SQLiteIntegrityScanner().scan(str(path)).findings)
        for module in MIRRORS:
            repo = module.ReadOnlyExplorerSQLiteRepository(str(path))
            status, edges = repo.current_positioned_graph_edges(1)
            self.assertEqual((status['state'], status['build_id'], len(edges)), ('ready', CURRENT_BUILD, 1))

    def test_explicit_diagnostic_still_detects_unrelated_damage(self):
        for name, statements in UNRELATED.items():
            if name == 'unrelated_schema_object':
                continue
            with self.subTest(damage=name):
                path = self.fixture()
                change(path, *statements)
                self.assertTrue(SQLiteIntegrityScanner().scan(str(path)).findings)

    def test_consumed_damage_stays_fail_closed(self):
        for name, statements in CONSUMED.items():
            path = self.fixture()
            change(path, *statements)
            for module in MIRRORS:
                repo = module.ReadOnlyExplorerSQLiteRepository(str(path))
                for read_name, read in graph_reads(repo).items():
                    if read_name not in CONSUMERS[name]:
                        continue
                    with self.subTest(damage=name, mirror=module.__name__, read=read_name):
                        with self.assertRaises(module.AnalysisError):
                            read()


class ScopedGraphPolicyRedTests(GraphFixture):
    def test_unrelated_damage_does_not_block_selected_reads(self):
        for name, statements in UNRELATED.items():
            path = self.fixture()
            expected = self.baseline(path)
            change(path, *statements)
            for module in MIRRORS:
                repo = module.ReadOnlyExplorerSQLiteRepository(str(path))
                for read_name, read in graph_reads(repo).items():
                    with self.subTest(damage=name, mirror=module.__name__, read=read_name):
                        try:
                            result = read()
                        except module.AnalysisError as error:
                            self.fail(f'Unrelated {name} blocked {read_name}: {error}')
                        self.assertEqual(result, expected[module.__name__][read_name])

    def test_selected_reads_do_no_schema_or_historical_payload_work(self):
        path = self.fixture()
        for module in MIRRORS:
            repo = module.ReadOnlyExplorerSQLiteRepository(str(path))
            for read_name, read in graph_reads(repo).items():
                with self.subTest(mirror=module.__name__, read=read_name):
                    with observe_sql(repo) as statements:
                        read()
                    sql = [' '.join(s.lower().split()) for s in statements]
                    schema = [s for s in sql if any(token in s for token in (
                        'sqlite_master', 'table_info(', 'index_list(', 'foreign_key_list(', 'foreign_key_check'))]
                    self.assertEqual(schema, [], 'selected read scanned schema topology')
                    historical = [s for s in sql if 'graph_feature_evidence' in s and 'evidence_json' in s
                                  and 'is_current=1' not in s.replace(' ', '')]
                    self.assertEqual(historical, [], 'selected read loaded non-current evidence payloads')
                    if HISTORICAL_RUN in ' '.join(sql) or OLD_BUILD in ' '.join(sql):
                        self.fail('selected read bound unrelated historical identities')


if __name__ == '__main__':
    unittest.main()
