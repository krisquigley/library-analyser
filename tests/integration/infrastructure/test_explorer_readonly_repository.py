import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from music_analyzer.application.dto.analysis import AnalysisError
from music_analyzer.application.dto.catalogue import Inventory, ScannedFile, TrackMetadata
from music_analyzer.domain.catalogue import FileIdentity
from music_analyzer.domain.projection import DISTANCE_POLICY_VERSION, NEIGHBOUR_POLICY_VERSION
from music_analyzer.infrastructure.persistence.analysis import SQLiteAnalysisRepository
from music_analyzer.infrastructure.persistence.explorer_readonly import ReadOnlyExplorerSQLiteRepository

APP_ID = 0x4D414E41


def create_db(path):
    db = sqlite3.connect(path)
    try:
        db.executescript('''
    CREATE TABLE runs (id TEXT PRIMARY KEY, location TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('running','completed','failed','interrupted')), detail TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE stages (run_id TEXT NOT NULL REFERENCES runs(id), stage TEXT NOT NULL, result TEXT NOT NULL, PRIMARY KEY(run_id,stage));
    CREATE TABLE tracks(id TEXT PRIMARY KEY, sha256 TEXT NOT NULL UNIQUE, size INTEGER NOT NULL);
    CREATE TABLE locations(path TEXT PRIMARY KEY, track_id TEXT NOT NULL REFERENCES tracks(id), mtime_ns INTEGER NOT NULL, format TEXT NOT NULL, available INTEGER NOT NULL CHECK(available IN (0,1)));
    CREATE TABLE scan_roots(root TEXT NOT NULL, path TEXT NOT NULL REFERENCES locations(path), PRIMARY KEY(root,path));
    CREATE TABLE batch_jobs(track_id TEXT PRIMARY KEY REFERENCES tracks(id), fingerprint TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('pending','running','completed','failed')), attempts INTEGER NOT NULL CHECK(attempts >= 0), run_id TEXT, detail TEXT NOT NULL);
    CREATE TABLE run_tracks(run_id TEXT PRIMARY KEY REFERENCES runs(id), track_id TEXT NOT NULL REFERENCES tracks(id));
    CREATE TABLE overrides(track_id TEXT NOT NULL REFERENCES tracks(id), field TEXT NOT NULL, value TEXT NOT NULL, PRIMARY KEY(track_id,field));
    CREATE TABLE track_metadata(track_id TEXT PRIMARY KEY REFERENCES tracks(id), common_json TEXT NOT NULL, tags_json TEXT NOT NULL, warnings_json TEXT NOT NULL);
    CREATE TABLE track_audio(track_id TEXT PRIMARY KEY REFERENCES tracks(id), duration_seconds REAL, duration_source TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('eligible','excluded','unknown')), reason TEXT NOT NULL);
    CREATE TRIGGER test_track_audio_default AFTER INSERT ON tracks BEGIN INSERT INTO track_audio VALUES(NEW.id, 120.0, 'mutagen', 'eligible', ''); END;
    CREATE VIEW active_tracks AS SELECT t.id,t.sha256,t.size FROM tracks t JOIN track_audio a ON a.track_id=t.id WHERE a.status='eligible';
    CREATE VIEW active_locations AS SELECT l.path,l.track_id,l.mtime_ns,l.format,l.available FROM locations l JOIN track_audio a ON a.track_id=l.track_id WHERE l.available=1 AND a.status='eligible';
    ''')
        db.execute(f'PRAGMA application_id={APP_ID}')
        db.execute('PRAGMA user_version=6')
        return db
    except Exception:
        db.close()
        raise


def stage(name, value=1.0):
    return json.dumps({'stage': name, 'provenance': [['fixture', 'unit']], 'uncertainty': '', 'values': [[name, value]]})


def create_v7_graph_db(path):
    db = create_db(path)
    try:
        db.executescript('''
    CREATE TABLE graph_builds(
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
        CHECK(status = 'completed' OR is_current = 0));
    CREATE UNIQUE INDEX idx_graph_builds_one_current ON graph_builds(is_current) WHERE is_current = 1;
    CREATE TABLE graph_edges(
        source_track_id TEXT NOT NULL REFERENCES tracks(id),
        target_track_id TEXT NOT NULL REFERENCES tracks(id),
        score REAL NOT NULL CHECK(score >= 0.0 AND score <= 1.0),
        distance REAL NOT NULL CHECK(distance >= 0.0 AND distance <= 1.0),
        supported_group_count INTEGER NOT NULL CHECK(supported_group_count > 0),
        distance_policy_version TEXT NOT NULL,
        neighbour_policy_version TEXT NOT NULL,
        built_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(source_track_id,target_track_id),
        CHECK(source_track_id < target_track_id));
    CREATE INDEX idx_graph_edges_source_track_id ON graph_edges(source_track_id);
    CREATE INDEX idx_graph_edges_target_track_id ON graph_edges(target_track_id);
    CREATE TABLE graph_build_edges(
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
        CHECK(source_track_id < target_track_id));
    CREATE INDEX idx_graph_build_edges_build_id ON graph_build_edges(build_id);
    CREATE INDEX idx_graph_build_edges_source_track_id ON graph_build_edges(build_id,source_track_id);
    CREATE INDEX idx_graph_build_edges_target_track_id ON graph_build_edges(build_id,target_track_id);
    ''')
        db.execute('PRAGMA user_version=7')
        return db
    except Exception:
        db.close()
        raise


class ReadOnlyExplorerSQLiteRepositoryTests(unittest.TestCase):
    def test_rejects_empty_db_without_creating_schema(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'empty.sqlite'
            sqlite3.connect(path).close()
            with self.assertRaisesRegex(AnalysisError, 'supported music-analyzer'):
                ReadOnlyExplorerSQLiteRepository(str(path)).track_ids()
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(), [])

    def test_reads_latest_identity_linked_run_and_redacts_path_to_label(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            db = create_db(path)
            tid = 'sha256:' + 'c' * 64
            db.execute('INSERT INTO tracks VALUES(?,?,?)', (tid, 'c' * 64, 10))
            db.execute('INSERT INTO locations VALUES(?,?,?,?,?)', ('/private/music/Artist/Track.flac', tid, 1, 'flac', 1))
            db.execute('INSERT INTO runs(id,location,status,detail) VALUES(?,?,?,?)', ('old', '/private/music/Artist/Track.flac', 'completed', 'old ok'))
            db.execute('INSERT INTO run_tracks VALUES(?,?)', ('old', tid))
            db.execute('INSERT INTO stages VALUES(?,?,?)', ('old', 'bpm', stage('bpm', 120.0)))
            db.execute('INSERT INTO runs(id,location,status,detail) VALUES(?,?,?,?)', ('new', '/private/music/Artist/Track.flac', 'failed', 'new failed'))
            db.execute('INSERT INTO run_tracks VALUES(?,?)', ('new', tid))
            db.execute('INSERT INTO overrides VALUES(?,?,?)', (tid, 'bpm', 'about 120 maybe'))
            db.commit(); db.close()
            repo = ReadOnlyExplorerSQLiteRepository(str(path))
            self.assertEqual(repo.track_ids(), (tid,))
            track = repo.read_track(tid)
            self.assertEqual(track.display_label, 'Track.flac')
            self.assertEqual(track.available_locations, 1)
            self.assertEqual(track.run.run_id, 'new')
            self.assertEqual(track.run.status, 'failed')
            self.assertEqual(track.run.stages, ())
            self.assertEqual(track.overrides, (('bpm', 'about 120 maybe'),))

    def test_query_only_and_read_only_leave_inventory_unchanged(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            db = create_db(path)
            tid = 'sha256:' + 'd' * 64
            db.execute('INSERT INTO tracks VALUES(?,?,?)', (tid, 'd' * 64, 10))
            db.commit(); db.close()
            before = path.read_bytes()
            repo = ReadOnlyExplorerSQLiteRepository(str(path))
            self.assertEqual(repo.track_ids(), (tid,))
            self.assertEqual(path.read_bytes(), before)

    def test_wal_committed_rows_are_visible_to_readonly_adapter(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            db = create_db(path)
            db.execute('PRAGMA journal_mode=WAL')
            tid = 'sha256:' + 'e' * 64
            db.execute('INSERT INTO tracks VALUES(?,?,?)', (tid, 'e' * 64, 10))
            db.commit()
            # Keep writer open so committed data remains represented through WAL sidecars.
            self.assertTrue(os.path.exists(str(path) + '-wal'))
            repo = ReadOnlyExplorerSQLiteRepository(str(path))
            self.assertIn(tid, repo.track_ids())
            db.close()

    def test_invalid_stage_payload_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            db = create_db(path)
            tid = 'sha256:' + 'f' * 64
            db.execute('INSERT INTO tracks VALUES(?,?,?)', (tid, 'f' * 64, 10))
            db.execute('INSERT INTO runs(id,location,status,detail) VALUES(?,?,?,?)', ('run', '', 'completed', ''))
            db.execute('INSERT INTO run_tracks VALUES(?,?)', ('run', tid))
            db.execute('INSERT INTO stages VALUES(?,?,?)', ('run', 'bpm', '{"stage":"other","provenance":[],"uncertainty":""}'))
            db.commit(); db.close()
            with self.assertRaisesRegex(AnalysisError, 'Invalid stored stage'):
                ReadOnlyExplorerSQLiteRepository(str(path)).read_track(tid)

    def test_non_object_stage_payload_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            db = create_db(path)
            tid = 'sha256:' + 'a' * 64
            db.execute('INSERT INTO tracks VALUES(?,?,?)', (tid, 'a' * 64, 10))
            db.execute('INSERT INTO runs(id,location,status,detail) VALUES(?,?,?,?)', ('run', '', 'completed', ''))
            db.execute('INSERT INTO run_tracks VALUES(?,?)', ('run', tid))
            db.execute('INSERT INTO stages VALUES(?,?,?)', ('run', 'bpm', '[]'))
            db.commit(); db.close()
            with self.assertRaisesRegex(AnalysisError, 'Invalid stored stage'):
                ReadOnlyExplorerSQLiteRepository(str(path)).read_track(tid)

    def test_rejects_v5_schema_with_expected_names_but_missing_constraints(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            with closing(sqlite3.connect(path)) as db, db:
                db.executescript('''
            CREATE TABLE runs (id, location, status, detail, created_at);
            CREATE TABLE stages (run_id, stage, result);
            CREATE TABLE tracks(id, sha256, size);
            CREATE TABLE locations(path, track_id, mtime_ns, format, available);
            CREATE TABLE scan_roots(root, path);
            CREATE TABLE batch_jobs(track_id, fingerprint, state, attempts, run_id, detail);
            CREATE TABLE run_tracks(run_id, track_id);
            CREATE TABLE overrides(track_id, field, value);
            ''')
                db.execute(f'PRAGMA application_id={APP_ID}')
                db.execute('PRAGMA user_version=6')
                db.execute('INSERT INTO tracks VALUES(?,?,?)', ('not-a-sha-id', 'not-sha', 'not-int'))
            with self.assertRaisesRegex(AnalysisError, 'Unexpected analysis database schema'):
                ReadOnlyExplorerSQLiteRepository(str(path)).track_ids()

    def test_rejects_v6_schema_with_loose_active_view_definition(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            db = create_db(path)
            db.execute('DROP VIEW active_tracks')
            db.execute('CREATE VIEW active_tracks AS SELECT id,sha256,size FROM tracks')
            db.commit(); db.close()
            with self.assertRaisesRegex(AnalysisError, 'Unexpected analysis database schema'):
                ReadOnlyExplorerSQLiteRepository(str(path)).track_ids()

    def test_rejects_v5_schema_with_invalid_track_identity_and_size_values(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            db = create_db(path)
            db.execute('INSERT INTO tracks VALUES(?,?,?)', ('not-a-sha-id', 'not-sha', 'not-int'))
            db.commit(); db.close()
            with self.assertRaisesRegex(AnalysisError, 'Unexpected analysis database rows'):
                ReadOnlyExplorerSQLiteRepository(str(path)).track_ids()

    def test_rejects_track_missing_track_audio_row_instead_of_trusting_active_view_inner_join(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            db = create_db(path)
            tid = 'sha256:' + '8' * 64
            db.execute('INSERT INTO tracks VALUES(?,?,?)', (tid, '8' * 64, 10))
            db.execute('DELETE FROM track_audio WHERE track_id=?', (tid,))
            db.commit(); db.close()
            with self.assertRaisesRegex(AnalysisError, 'Unexpected analysis database rows'):
                ReadOnlyExplorerSQLiteRepository(str(path)).track_ids()

    def test_rejects_orphan_track_audio_row_inserted_with_foreign_keys_disabled_before_showing_results(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            db = create_db(path)
            db.execute('PRAGMA foreign_keys=OFF')
            good_tid = 'sha256:' + '8' * 64
            db.execute('INSERT INTO tracks VALUES(?,?,?)', (good_tid, '8' * 64, 10))
            db.execute(
                'INSERT INTO track_audio VALUES(?,?,?,?,?)',
                ('sha256:' + '9' * 64, 120.0, 'mutagen', 'eligible', ''),
            )
            db.commit(); db.close()
            with self.assertRaisesRegex(AnalysisError, 'Unexpected analysis database rows'):
                ReadOnlyExplorerSQLiteRepository(str(path)).track_ids()

    def test_accepts_normalized_trusted_nonfinite_duration_as_unknown(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            db = create_db(path)
            tid = 'sha256:' + '7' * 64
            db.execute('INSERT INTO tracks VALUES(?,?,?)', (tid, '7' * 64, 10))
            db.execute('UPDATE track_audio SET duration_seconds=?,duration_source=?,status=?,reason=? WHERE track_id=?',
                       (None, 'mutagen', 'unknown', 'duration unverified; excluded from active library until mutagen/ffprobe verifies duration; rescan audio metadata', tid))
            db.commit(); db.close()

            repo = ReadOnlyExplorerSQLiteRepository(str(path))
            self.assertEqual(repo.track_ids(), ())
            self.assertIsNone(repo.read_track(tid).metadata.duration_seconds)

    def test_rejects_tampered_track_audio_rows_instead_of_trusting_active_view_status(self):
        for audio_update in (
            (119.0, '', 'eligible', ''),
            (120.0, 'mutagen', 'archived', ''),
            (None, 'mutagen', 'excluded', 'duration invalid; excluded from active library until mutagen/ffprobe verifies a positive finite duration; rescan audio metadata'),
            (float('inf'), 'mutagen', 'excluded', 'duration invalid; excluded from active library until mutagen/ffprobe verifies a positive finite duration; rescan audio metadata'),
        ):
            with self.subTest(audio_update=audio_update), tempfile.TemporaryDirectory() as td:
                path = Path(td) / 'analysis.sqlite'
                db = create_db(path)
                db.execute('PRAGMA ignore_check_constraints=ON')
                tid = 'sha256:' + '9' * 64
                db.execute('INSERT INTO tracks VALUES(?,?,?)', (tid, '9' * 64, 10))
                db.execute('UPDATE track_audio SET duration_seconds=?,duration_source=?,status=?,reason=? WHERE track_id=?', (*audio_update, tid))
                db.commit(); db.close()

                with self.assertRaisesRegex(AnalysisError, 'Unexpected analysis database rows'):
                    ReadOnlyExplorerSQLiteRepository(str(path)).track_ids()

    def test_accepts_schema_migrated_by_analysis_repository(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            repo = SQLiteAnalysisRepository(str(path))
            identity = FileIdentity('3' * 64, 30)
            inventory = Inventory('/music', (ScannedFile('/music/Legacy.flac', identity, 1, 'flac', TrackMetadata(duration_seconds=120.0, duration_source='fixture')),), (), True)
            repo.register(inventory)
            self.assertEqual(ReadOnlyExplorerSQLiteRepository(str(path)).track_ids(), ())

    def test_accepts_valid_v6_and_v7_graph_build_rows(self):
        with tempfile.TemporaryDirectory() as td:
            v6_path = Path(td) / 'v6.sqlite'
            db = create_db(v6_path)
            db.commit(); db.close()
            self.assertEqual(ReadOnlyExplorerSQLiteRepository(str(v6_path)).metadata()['schema_version'], 6)

            v7_path = Path(td) / 'v7.sqlite'
            db = create_v7_graph_db(v7_path)
            try:
                db.execute(
                    '''INSERT INTO graph_builds(
                        id,status,detail,edge_count,sparse_k,source_fingerprint,
                        distance_policy_version,neighbour_policy_version,is_current,created_at,completed_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                    ('build-ok', 'completed', '', 0, 10, 'synthetic', DISTANCE_POLICY_VERSION,
                     NEIGHBOUR_POLICY_VERSION, 1, 'created', 'completed'),
                )
                db.commit()
            finally:
                db.close()
            self.assertEqual(ReadOnlyExplorerSQLiteRepository(str(v7_path)).metadata()['schema_version'], 7)

    def test_current_graph_with_stale_policy_version_reports_stale_instead_of_corrupt(self):
        cases = (
            ('distance_policy_version', 'stale-distance-policy'),
            ('neighbour_policy_version', 'stale-neighbour-policy'),
        )
        for column, value in cases:
            with self.subTest(column=column), tempfile.TemporaryDirectory() as td:
                path = Path(td) / 'analysis.sqlite'
                db = create_v7_graph_db(path)
                source = 'sha256:' + '1' * 64
                target = 'sha256:' + '2' * 64
                try:
                    for tid in (source, target):
                        db.execute('INSERT INTO tracks VALUES(?,?,?)', (tid, tid.split(':')[1], 10))
                    row = {
                        'id': 'build-stale',
                        'status': 'completed',
                        'detail': '',
                        'edge_count': 1,
                        'sparse_k': 10,
                        'source_fingerprint': 'synthetic',
                        'distance_policy_version': DISTANCE_POLICY_VERSION,
                        'neighbour_policy_version': NEIGHBOUR_POLICY_VERSION,
                        'is_current': 1,
                        'created_at': 'created',
                        'completed_at': 'completed',
                    }
                    row[column] = value
                    db.execute(
                        '''INSERT INTO graph_builds(
                            id,status,detail,edge_count,sparse_k,source_fingerprint,
                            distance_policy_version,neighbour_policy_version,is_current,created_at,completed_at)
                           VALUES(:id,:status,:detail,:edge_count,:sparse_k,:source_fingerprint,
                                  :distance_policy_version,:neighbour_policy_version,:is_current,:created_at,:completed_at)''',
                        row,
                    )
                    edge_row = {
                        'build_id': 'build-stale',
                        'source_track_id': source,
                        'target_track_id': target,
                        'score': 0.75,
                        'distance': 0.25,
                        'supported_group_count': 1,
                        'distance_policy_version': row['distance_policy_version'],
                        'neighbour_policy_version': row['neighbour_policy_version'],
                    }
                    db.execute(
                        '''INSERT INTO graph_edges(source_track_id,target_track_id,score,distance,supported_group_count,distance_policy_version,neighbour_policy_version)
                           VALUES(:source_track_id,:target_track_id,:score,:distance,:supported_group_count,:distance_policy_version,:neighbour_policy_version)''',
                        edge_row,
                    )
                    db.execute(
                        '''INSERT INTO graph_build_edges(build_id,source_track_id,target_track_id,score,distance,supported_group_count,distance_policy_version,neighbour_policy_version)
                           VALUES(:build_id,:source_track_id,:target_track_id,:score,:distance,:supported_group_count,:distance_policy_version,:neighbour_policy_version)''',
                        edge_row,
                    )
                    db.commit()
                finally:
                    db.close()

                status, edges = ReadOnlyExplorerSQLiteRepository(str(path)).current_graph_edges()
                self.assertEqual(status['state'], 'stale')
                self.assertIn('policy', status['reason'])
                self.assertEqual(edges, ())

    def test_rejects_tampered_v7_graph_build_rows(self):
        cases = (
            ('status', {'status': 'running'}, True),
            ('edge_count', {'edge_count': -1}, True),
            ('sparse_k', {'sparse_k': -1}, True),
        )
        for name, update, ignore_checks in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as td:
                path = Path(td) / 'analysis.sqlite'
                db = create_v7_graph_db(path)
                db.close()
                row = {
                    'id': 'build-bad',
                    'status': 'completed',
                    'detail': '',
                    'edge_count': 0,
                    'sparse_k': 10,
                    'source_fingerprint': 'synthetic',
                    'distance_policy_version': DISTANCE_POLICY_VERSION,
                    'neighbour_policy_version': NEIGHBOUR_POLICY_VERSION,
                    'is_current': 0,
                    'created_at': 'created',
                    'completed_at': 'completed',
                    **update,
                }
                with closing(sqlite3.connect(path)) as db, db:
                    if ignore_checks:
                        db.execute('PRAGMA ignore_check_constraints=ON')
                    db.execute(
                        '''INSERT INTO graph_builds(
                            id,status,detail,edge_count,sparse_k,source_fingerprint,
                            distance_policy_version,neighbour_policy_version,is_current,created_at,completed_at)
                           VALUES(:id,:status,:detail,:edge_count,:sparse_k,:source_fingerprint,
                                  :distance_policy_version,:neighbour_policy_version,:is_current,:created_at,:completed_at)''',
                        row,
                    )

                with self.assertRaisesRegex(AnalysisError, 'Unexpected analysis database rows'):
                    ReadOnlyExplorerSQLiteRepository(str(path)).metadata()

    def test_accepts_legacy_v1_schema_migrated_to_v6(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            with closing(sqlite3.connect(path)) as db, db:
                db.executescript('''
            CREATE TABLE runs(id TEXT PRIMARY KEY,location TEXT,status TEXT,detail TEXT,created_at TEXT);
                CREATE TABLE stages(run_id TEXT,stage TEXT,result TEXT,PRIMARY KEY(run_id,stage));
                ''')
                db.execute(f'PRAGMA application_id={APP_ID}')
                db.execute('PRAGMA user_version=1')
                db.execute("INSERT INTO runs VALUES('run','old','completed','','then')")
                db.execute("INSERT INTO stages VALUES('run','rhythm',?)", ('{"provenance":"unchanged"}',))
            repo = SQLiteAnalysisRepository(str(path))
            identity = FileIdentity('4' * 64, 40)
            inventory = Inventory('/music', (ScannedFile('/music/Legacy.flac', identity, 1, 'flac', TrackMetadata(duration_seconds=120.0, duration_source='fixture')),), (), True)
            repo.register(inventory)
            self.assertEqual(ReadOnlyExplorerSQLiteRepository(str(path)).track_ids(), ())

    def test_read_transaction_uses_consistent_wal_snapshot_for_count_and_page(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            db = create_db(path)
            db.execute('PRAGMA journal_mode=WAL')
            first = 'sha256:' + '1' * 64
            db.execute('INSERT INTO tracks VALUES(?,?,?)', (first, first.split(':')[1], 10))
            db.commit()
            repo = ReadOnlyExplorerSQLiteRepository(str(path))
            original_read_track = repo._read_track

            def concurrent_insert_after_page_ids_are_selected(connection, track_id):
                writer = sqlite3.connect(path)
                second = 'sha256:' + '2' * 64
                writer.execute('INSERT INTO tracks VALUES(?,?,?)', (second, second.split(':')[1], 20))
                writer.commit(); writer.close()
                return original_read_track(connection, track_id)

            repo._read_track = concurrent_insert_after_page_ids_are_selected
            metadata, track_count, tracks = repo.list_tracks(limit=10)
            self.assertEqual(metadata['read_policy'], 'bounded_read_transaction')
            self.assertEqual(track_count, 1)
            self.assertEqual(tuple(track.track_id for track in tracks), (first,))
            self.assertEqual(ReadOnlyExplorerSQLiteRepository(str(path)).track_ids(), (first, 'sha256:' + '2' * 64))
            db.close()

    def test_list_tracks_reads_page_and_records_in_one_transaction(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            db = create_db(path)
            first = 'sha256:' + '1' * 64
            second = 'sha256:' + '2' * 64
            for tid in (first, second):
                db.execute('INSERT INTO tracks VALUES(?,?,?)', (tid, tid.split(':')[1], 10))
            db.execute('INSERT INTO locations VALUES(?,?,?,?,?)', ('/private/music/First.flac', first, 1, 'flac', 1))
            db.commit(); db.close()
            metadata, track_count, tracks = ReadOnlyExplorerSQLiteRepository(str(path)).list_tracks(limit=1)
            self.assertEqual(metadata['read_policy'], 'bounded_read_transaction')
            self.assertEqual(track_count, 2)
            self.assertEqual(tuple(track.track_id for track in tracks), (first,))
            self.assertEqual(tracks[0].display_label, 'First.flac')


    def test_list_track_summaries_is_compact_paginated_and_does_not_read_stage_results(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            db = create_db(path)
            first = 'sha256:' + '1' * 64
            second = 'sha256:' + '2' * 64
            for tid, label in ((first, 'First.flac'), (second, 'Second.flac')):
                db.execute('INSERT INTO tracks VALUES(?,?,?)', (tid, tid.split(':')[1], 10))
                db.execute('INSERT INTO locations VALUES(?,?,?,?,?)', ('/private/music/' + label, tid, 1, 'flac', 1))
                db.execute('INSERT INTO track_metadata VALUES(?,?,?,?)', (tid, '[["title", "' + label[:-5] + '"]]', '[]', '[]'))
            db.execute('INSERT INTO runs(id,location,status,detail) VALUES(?,?,?,?)', ('run-1', '/private/music/First.flac', 'completed', ''))
            db.execute('INSERT INTO run_tracks VALUES(?,?)', ('run-1', first))
            db.execute('INSERT INTO stages VALUES(?,?,?)', ('run-1', 'bpm', 'not-json-summary-endpoint-must-not-read-this'))
            db.commit(); db.close()

            repo = ReadOnlyExplorerSQLiteRepository(str(path))
            metadata, count, page, cursor = repo.list_track_summaries(1, query='first', order='title')

            self.assertEqual(metadata['read_policy'], 'bounded_read_transaction')
            self.assertEqual(count, 1)
            self.assertEqual(page[0].handle, first)
            self.assertEqual(page[0].title, 'First')
            self.assertIsNone(cursor)
            _metadata, count, first_page, cursor = repo.list_track_summaries(1, order='id')
            self.assertEqual(count, 2)
            self.assertEqual(tuple(row.handle for row in first_page), (first,))
            _metadata, _count, second_page, _cursor = repo.list_track_summaries(1, cursor=cursor, order='id')
            self.assertEqual(tuple(row.handle for row in second_page), (second,))

    def test_list_track_summaries_orders_title_and_artist_by_returned_metadata_with_stable_cursors(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            db = create_db(path)
            rows = (
                ('sha256:' + '1' * 64, 'Gamma Filename.flac', '[]', '[["artist", ["Zulu"]]]'),
                ('sha256:' + '2' * 64, 'Zulu Filename.flac', '[["title", "Alpha Title"], ["artist", ["Bravo"]]]', '[]'),
                ('sha256:' + '3' * 64, 'Beta Filename.flac', '[["title", "Middle Title"], ["artist", ["Alpha"]]]', '[]'),
            )
            for tid, label, common_json, tags_json in rows:
                db.execute('INSERT INTO tracks VALUES(?,?,?)', (tid, tid.split(':')[1], 10))
                db.execute('INSERT INTO locations VALUES(?,?,?,?,?)', ('/private/music/' + label, tid, 1, 'flac', 1))
                db.execute('INSERT INTO track_metadata VALUES(?,?,?,?)', (tid, common_json, tags_json, '[]'))
            db.execute('INSERT INTO runs(id,location,status,detail) VALUES(?,?,?,?)', ('run-1', '/private/music/01-filename.flac', 'completed', ''))
            db.execute('INSERT INTO run_tracks VALUES(?,?)', ('run-1', rows[0][0]))
            db.execute('INSERT INTO stages VALUES(?,?,?)', ('run-1', 'bpm', 'not-json-summary-endpoint-must-not-read-this'))
            db.commit(); db.close()

            repo = ReadOnlyExplorerSQLiteRepository(str(path))

            _metadata, count, title_page_1, title_cursor = repo.list_track_summaries(2, order='title')
            self.assertEqual(count, 3)
            self.assertEqual(tuple(row.title for row in title_page_1), ('Alpha Title', 'Gamma Filename.flac'))
            _metadata, count, title_page_2, title_cursor_2 = repo.list_track_summaries(2, cursor=title_cursor, order='title')
            self.assertEqual(count, 3)
            self.assertEqual(tuple(row.title for row in title_page_2), ('Middle Title',))
            self.assertIsNone(title_cursor_2)

            _metadata, count, artist_page_1, artist_cursor = repo.list_track_summaries(2, order='artist')
            self.assertEqual(count, 3)
            self.assertEqual(tuple(row.artist for row in artist_page_1), ('Alpha', 'Bravo'))
            _metadata, count, artist_page_2, artist_cursor_2 = repo.list_track_summaries(2, cursor=artist_cursor, order='artist')
            self.assertEqual(count, 3)
            self.assertEqual(tuple(row.artist for row in artist_page_2), ('Zulu',))
            self.assertIsNone(artist_cursor_2)

    def test_list_track_summaries_keeps_total_count_while_following_cursors(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            db = create_db(path)
            rows = []
            for idx in range(250):
                hex_id = f'{idx + 1:064x}'
                tid = 'sha256:' + hex_id
                if idx < 150:
                    title = f'Needle Title {idx:03d}'
                    artist = f'Needle Artist {idx:03d}'
                else:
                    title = f'Other Title {idx:03d}'
                    artist = f'Other Artist {idx:03d}'
                rows.append((tid, title, artist))
                db.execute('INSERT INTO tracks VALUES(?,?,?)', (tid, hex_id, idx + 10))
                db.execute('INSERT INTO locations VALUES(?,?,?,?,?)', (f'/private/music/{idx:03d}.flac', tid, idx, 'flac', 1))
                db.execute('INSERT INTO track_metadata VALUES(?,?,?,?)', (
                    tid,
                    '[[' + json.dumps('title') + ', ' + json.dumps(title) + '], [' + json.dumps('artist') + ', [' + json.dumps(artist) + ']]]',
                    '[]',
                    '[]',
                ))
            db.commit(); db.close()

            repo = ReadOnlyExplorerSQLiteRepository(str(path))

            for order in ('title', 'artist'):
                with self.subTest(order=order, query=''):
                    cursor = None
                    handles = []
                    counts = []
                    page_lengths = []
                    for _ in range(3):
                        _metadata, count, page, cursor = repo.list_track_summaries(100, cursor=cursor, order=order)
                        counts.append(count)
                        page_lengths.append(len(page))
                        handles.extend(row.handle for row in page)
                    self.assertEqual(counts, [250, 250, 250])
                    self.assertEqual(page_lengths, [100, 100, 50])
                    self.assertIsNone(cursor)
                    expected = tuple(tid for tid, _title, _artist in sorted(
                        rows,
                        key=(lambda row: (row[1].casefold(), row[0])) if order == 'title' else (lambda row: (row[2].casefold(), row[0])),
                    ))
                    self.assertEqual(tuple(handles), expected)

                with self.subTest(order=order, query='needle'):
                    cursor = None
                    handles = []
                    counts = []
                    page_lengths = []
                    for _ in range(3):
                        _metadata, count, page, cursor = repo.list_track_summaries(50, cursor=cursor, query='needle', order=order)
                        counts.append(count)
                        page_lengths.append(len(page))
                        handles.extend(row.handle for row in page)
                    self.assertEqual(counts, [150, 150, 150])
                    self.assertEqual(page_lengths, [50, 50, 50])
                    self.assertIsNone(cursor)
                    matching_rows = rows[:150]
                    expected = tuple(tid for tid, _title, _artist in sorted(
                        matching_rows,
                        key=(lambda row: (row[1].casefold(), row[0])) if order == 'title' else (lambda row: (row[2].casefold(), row[0])),
                    ))
                    self.assertEqual(tuple(handles), expected)


    def test_list_track_summaries_unicode_cursor_uses_same_fold_as_sql_order(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            db = create_db(path)
            rows = (
                ('sha256:' + '1' * 64, 'First.flac', 'Älpha Artist'),
                ('sha256:' + '2' * 64, 'Second.flac', 'Ålpha Artist'),
            )
            for tid, label, artist in rows:
                db.execute('INSERT INTO tracks VALUES(?,?,?)', (tid, tid.split(':')[1], 10))
                db.execute('INSERT INTO locations VALUES(?,?,?,?,?)', ('/private/music/' + label, tid, 1, 'flac', 1))
                db.execute('INSERT INTO track_metadata VALUES(?,?,?,?)', (tid, '[[' + json.dumps('title') + ', ' + json.dumps(label[:-5]) + ']]', '[[' + json.dumps('artist') + ', [' + json.dumps(artist) + ']]]', '[]'))
            db.execute('INSERT INTO runs(id,location,status,detail) VALUES(?,?,?,?)', ('run-1', '/private/music/First.flac', 'completed', ''))
            db.execute('INSERT INTO run_tracks VALUES(?,?)', ('run-1', rows[0][0]))
            db.execute('INSERT INTO stages VALUES(?,?,?)', ('run-1', 'bpm', 'not-json-summary-endpoint-must-not-read-this'))
            db.commit(); db.close()

            repo = ReadOnlyExplorerSQLiteRepository(str(path))

            _metadata, count, first_page, cursor = repo.list_track_summaries(1, order='artist')
            self.assertEqual(count, 2)
            self.assertEqual(tuple(row.artist for row in first_page), ('Älpha Artist',))
            self.assertIsNotNone(cursor)
            _metadata, count, second_page, second_cursor = repo.list_track_summaries(1, cursor=cursor, order='artist')
            self.assertEqual(count, 2)
            self.assertEqual(tuple(row.artist for row in second_page), ('Ålpha Artist',))
            self.assertIsNone(second_cursor)

    def test_list_track_summaries_searches_visible_title_and_artist_only(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            db = create_db(path)
            rows = (
                ('sha256:' + '1' * 64, 'FalsePositive.flac', '[[' + json.dumps('album_artist') + ', ' + json.dumps('Private Notes') + ']]', '[]'),
                ('sha256:' + '2' * 64, 'Legitimate.flac', '[[' + json.dumps('title') + ', ' + json.dumps('Quiet Song') + '], [' + json.dumps('artist') + ', [' + json.dumps('Visible Artist') + ']]]', '[]'),
                ('sha256:' + '3' * 64, 'Case.flac', '[[' + json.dumps('title') + ', ' + json.dumps('MiXeD Case Title') + ']]', '[]'),
            )
            for tid, label, common_json, tags_json in rows:
                db.execute('INSERT INTO tracks VALUES(?,?,?)', (tid, tid.split(':')[1], 10))
                db.execute('INSERT INTO locations VALUES(?,?,?,?,?)', ('/private/music/' + label, tid, 1, 'flac', 1))
                db.execute('INSERT INTO track_metadata VALUES(?,?,?,?)', (tid, common_json, tags_json, '[]'))
            db.execute('INSERT INTO runs(id,location,status,detail) VALUES(?,?,?,?)', ('run-1', '/private/music/FalsePositive.flac', 'completed', ''))
            db.execute('INSERT INTO run_tracks VALUES(?,?)', ('run-1', rows[0][0]))
            db.execute('INSERT INTO stages VALUES(?,?,?)', ('run-1', 'bpm', 'not-json-summary-endpoint-must-not-read-this'))
            db.commit(); db.close()

            repo = ReadOnlyExplorerSQLiteRepository(str(path))

            _metadata, artist_count, artist_page, _cursor = repo.list_track_summaries(10, query='artist', order='title')
            self.assertEqual(artist_count, 1)
            self.assertEqual(tuple(row.handle for row in artist_page), (rows[1][0],))
            _metadata, private_count, private_page, _cursor = repo.list_track_summaries(10, query='private', order='title')
            self.assertEqual(private_count, 0)
            self.assertEqual(private_page, ())
            _metadata, case_count, case_page, _cursor = repo.list_track_summaries(10, query='mixed case', order='title')
            self.assertEqual(case_count, 1)
            self.assertEqual(tuple(row.handle for row in case_page), (rows[2][0],))

    def test_candidate_snapshot_reads_all_records_in_one_transaction(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            db = create_db(path)
            db.execute('PRAGMA journal_mode=WAL')
            first = 'sha256:' + '1' * 64
            db.execute('INSERT INTO tracks VALUES(?,?,?)', (first, first.split(':')[1], 10))
            db.commit()
            repo = ReadOnlyExplorerSQLiteRepository(str(path))
            original_read_track = repo._read_track

            def concurrent_insert_after_snapshot_ids_are_selected(connection, track_id):
                writer = sqlite3.connect(path)
                second = 'sha256:' + '2' * 64
                writer.execute('INSERT INTO tracks VALUES(?,?,?)', (second, second.split(':')[1], 20))
                writer.commit(); writer.close()
                return original_read_track(connection, track_id)

            repo._read_track = concurrent_insert_after_snapshot_ids_are_selected
            metadata, tracks = repo.candidate_snapshot()
            self.assertEqual(metadata['read_policy'], 'bounded_read_transaction')
            self.assertEqual(tuple(track.track_id for track in tracks), (first,))
            self.assertEqual(ReadOnlyExplorerSQLiteRepository(str(path)).track_ids(), (first, 'sha256:' + '2' * 64))
            db.close()


class _FakeReadTrackCursor:
    def __init__(self, rows):
        self._rows = tuple(rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows

    def __iter__(self):
        return iter(self._rows)


class _FakeOversizedReadTrackDb:
    def __init__(self):
        self.queries = []

    def execute(self, sql, params=()):
        compact = ' '.join(sql.split())
        self.queries.append(compact)
        if compact.startswith('SELECT id,sha256,size FROM tracks'):
            return _FakeReadTrackCursor((('sha256:' + '9' * 64, '9' * 64, 1),))
        if compact.startswith('SELECT path FROM locations'):
            return _FakeReadTrackCursor((('/music/Oversized.flac',),))
        if compact.startswith('SELECT r.id,r.status,r.detail FROM runs'):
            return _FakeReadTrackCursor((('run-oversized', 'completed', ''),))
        if compact.startswith('SELECT stage,length(CAST(result AS BLOB)) FROM stages'):
            return _FakeReadTrackCursor((('bpm', 17 * 1024 * 1024), ('energy', 1)))
        if compact.startswith('SELECT result FROM stages'):
            raise MemoryError('stage payload was fetched before size preflight')
        raise AssertionError('unexpected SQL: ' + compact)


class ReadOnlyExplorerStagePayloadGuardTests(unittest.TestCase):
    def test_read_track_rejects_oversized_stage_before_fetching_any_stage_payload(self):
        repo = ReadOnlyExplorerSQLiteRepository.__new__(ReadOnlyExplorerSQLiteRepository)
        fake_db = _FakeOversizedReadTrackDb()

        with self.assertRaisesRegex(AnalysisError, 'Oversized stored stage'):
            repo._read_track(fake_db, 'sha256:' + '9' * 64)

        self.assertFalse(any(query.startswith('SELECT result FROM stages') for query in fake_db.queries))



if __name__ == '__main__':
    unittest.main()
