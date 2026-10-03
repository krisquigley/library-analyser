import json
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path

from music_analyzer.application.dto.catalogue import Inventory, ScannedFile, TrackMetadata
from music_analyzer.application.use_cases.build_graph import BuildGraphSnapshot, _source_fingerprint
from music_analyzer.application.use_cases.candidates import _features
from music_analyzer.application.use_cases.explorer import _axis_node, _map_track
from music_analyzer.domain.catalogue import FileIdentity
from music_analyzer.domain.projection import _bounded_edges
from music_analyzer.infrastructure.persistence.analysis import AnalysisError, SQLiteAnalysisRepository
from music_analyzer.infrastructure.persistence.explorer_readonly import ReadOnlyExplorerSQLiteRepository
from tests.acceptance.test_explorer_3d_graph_assets import create_three_track_graph_db


def _build_graph(db_path: Path):
    return BuildGraphSnapshot(ReadOnlyExplorerSQLiteRepository(str(db_path)), SQLiteAnalysisRepository(str(db_path))).execute()


def _current_builds(db_path: Path):
    with closing(sqlite3.connect(db_path)) as db:
        return tuple(db.execute('''
            SELECT status,is_current,source_fingerprint,source_revision,edge_count
            FROM graph_builds ORDER BY created_at,rowid
        '''))


def _register_available_paths_as_scan_root(db_path: Path, root: str = '/music') -> None:
    with closing(sqlite3.connect(db_path)) as db:
        paths = tuple(row[0] for row in db.execute('SELECT path FROM locations WHERE available=1'))
        db.executemany('INSERT OR IGNORE INTO scan_roots(root,path) VALUES(?,?)', ((root, path) for path in paths))
        db.commit()


def _scanned_file(db_path: Path, path: str, track_id: str, mtime_ns: int = 2) -> ScannedFile:
    with closing(sqlite3.connect(db_path)) as db:
        sha256, size = db.execute('SELECT sha256,size FROM tracks WHERE id=?', (track_id,)).fetchone()
        common_json, tags_json, warnings_json = db.execute(
            'SELECT common_json,tags_json,warnings_json FROM track_metadata WHERE track_id=?', (track_id,)
        ).fetchone()
    return ScannedFile(
        path,
        FileIdentity(sha256, size),
        mtime_ns,
        'flac',
        TrackMetadata(tuple(tuple(item) for item in json.loads(common_json)),
                      tuple((key, tuple(values)) for key, values in json.loads(tags_json)),
                      tuple(json.loads(warnings_json)),
                      120.0,
                      'mutagen'),
    )


class GraphBuildSourceRevisionRemediationTests(unittest.TestCase):
    def test_source_revision_uses_deferred_read_transaction_so_writer_can_begin_immediate(self):
        class BlockingSourceRevisionRepository(SQLiteAnalysisRepository):
            def __init__(self, path, entered, release):
                super().__init__(path)
                self.entered = entered
                self.release = release

            def _graph_source_revision(self, db):
                db.execute('SELECT count(*) FROM active_tracks').fetchone()
                self.entered.set()
                if not self.release.wait(5):
                    raise AssertionError('timed out waiting to release source_revision probe')
                return super()._graph_source_revision(db)

        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / 'analysis.sqlite'
            create_three_track_graph_db(db_path)
            entered = threading.Event()
            release = threading.Event()
            repo = BlockingSourceRevisionRepository(str(db_path), entered, release)
            result = {}

            def run_source_revision():
                try:
                    result['revision'] = repo.source_revision()
                except BaseException as error:  # pragma: no cover - surfaced below
                    result['error'] = error

            worker = threading.Thread(target=run_source_revision, daemon=True)
            worker.start()
            self.assertTrue(entered.wait(5), 'source_revision did not enter read transaction')
            try:
                with closing(sqlite3.connect(db_path, timeout=0.2)) as db:
                    self.assertEqual(db.execute('PRAGMA journal_mode').fetchone()[0].lower(), 'delete')
                    db.execute('BEGIN IMMEDIATE')
                    db.execute('ROLLBACK')
            finally:
                release.set()
                worker.join(5)
            self.assertFalse(worker.is_alive(), 'source_revision probe thread did not stop')
            if 'error' in result:
                raise result['error']
            self.assertEqual(result['revision'], SQLiteAnalysisRepository(str(db_path)).source_revision())

    def test_in_flight_aba_graph_source_mutation_interrupts_attempt_without_promoting_b_edges_as_a(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / 'analysis.sqlite'
            track_ids = create_three_track_graph_db(db_path)
            writer = SQLiteAnalysisRepository(str(db_path))
            reader = ReadOnlyExplorerSQLiteRepository(str(db_path))

            rev_a = writer.source_revision()
            attempt_id = writer.begin_graph_build(10, rev_a)
            writer.set_override(track_ids[0], 'bpm', '121.0')
            rev_b = writer.source_revision()
            self.assertNotEqual(rev_b, rev_a)
            _metadata, records_b = reader.candidate_snapshot()
            retained_b = tuple(record for record in records_b if record.run is not None and record.run.status == 'completed')
            features_b = tuple(_features(record) for record in retained_b)
            edges_b = tuple(_bounded_edges(features_b, 10))
            fingerprint_b = _source_fingerprint(retained_b)
            self.assertGreater(len(edges_b), 0)

            writer.set_override(track_ids[0], 'bpm', None)
            self.assertEqual(writer.source_revision(), rev_a)

            with self.assertRaisesRegex(AnalysisError, 'Graph source changed before snapshot promotion'):
                writer.replace_graph_snapshot(edges_b, 10, fingerprint_b, source_revision=rev_a, attempt_id=attempt_id)

            with closing(sqlite3.connect(db_path)) as db:
                self.assertEqual(
                    db.execute(
                        'SELECT status,is_current,source_fingerprint,source_revision,edge_count FROM graph_builds WHERE id=?',
                        (attempt_id,),
                    ).fetchone(),
                    ('interrupted', 0, rev_a, rev_a, 0),
                )
                self.assertEqual(db.execute('SELECT count(*) FROM graph_edges').fetchone()[0], 0)
                self.assertEqual(db.execute('SELECT count(*) FROM graph_build_edges WHERE build_id=?', (attempt_id,)).fetchone()[0], 0)
                self.assertEqual(db.execute('SELECT count(*) FROM graph_builds WHERE is_current=1').fetchone()[0], 0)

    def test_in_flight_unchanged_rescan_does_not_interrupt_valid_no_change_promotion(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / 'analysis.sqlite'
            track_ids = create_three_track_graph_db(db_path)
            _register_available_paths_as_scan_root(db_path)
            writer = SQLiteAnalysisRepository(str(db_path))
            reader = ReadOnlyExplorerSQLiteRepository(str(db_path))

            source_revision = writer.source_revision()
            attempt_id = writer.begin_graph_build(10, source_revision)
            _metadata, records = reader.candidate_snapshot()
            retained = tuple(record for record in records if record.run is not None and record.run.status == 'completed')
            features = tuple(_features(record) for record in retained)
            edges = tuple(_bounded_edges(features, 10))
            fingerprint = _source_fingerprint(retained)

            writer.register(Inventory(
                '/music',
                (
                    _scanned_file(db_path, '/music/Alpha.flac', track_ids[0], mtime_ns=1),
                    _scanned_file(db_path, '/music/Beta.flac', track_ids[1], mtime_ns=1),
                ),
                (),
                True,
            ))

            build_id = writer.replace_graph_snapshot(edges, 10, fingerprint, source_revision=source_revision, attempt_id=attempt_id)

            self.assertEqual(build_id, attempt_id)
            with closing(sqlite3.connect(db_path)) as db:
                self.assertEqual(
                    db.execute('SELECT status,is_current,source_revision,edge_count FROM graph_builds WHERE id=?', (attempt_id,)).fetchone(),
                    ('completed', 1, source_revision, len(edges)),
                )
                self.assertEqual(db.execute('SELECT count(*) FROM graph_edges').fetchone()[0], len(edges))

    def test_complete_rescan_path_move_changes_fingerprint_and_rebuild_revision_matches(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / 'analysis.sqlite'
            track_ids = create_three_track_graph_db(db_path)
            _register_available_paths_as_scan_root(db_path)
            first = _build_graph(db_path)
            writer = SQLiteAnalysisRepository(str(db_path))
            first_revision = writer.source_revision()

            missing = writer.register(Inventory(
                '/music',
                (
                    _scanned_file(db_path, '/music/Alpha moved.flac', track_ids[0]),
                    _scanned_file(db_path, '/music/Beta.flac', track_ids[1]),
                ),
                (),
                True,
            ))
            self.assertEqual(missing, ('/music/Alpha.flac',))
            with closing(sqlite3.connect(db_path)) as db:
                self.assertEqual(
                    tuple(db.execute('SELECT path FROM active_locations WHERE track_id=? ORDER BY path', (track_ids[0],))),
                    (('/music/Alpha moved.flac',),),
                )

            second = _build_graph(db_path)
            third = _build_graph(db_path)
            current_revision = writer.source_revision()
            builds = _current_builds(db_path)

            self.assertNotEqual(current_revision, first_revision)
            self.assertNotEqual(second.source_fingerprint, first.source_fingerprint)
            self.assertEqual(third.source_fingerprint, second.source_fingerprint)
            self.assertEqual(builds[-2][2], second.source_fingerprint)
            self.assertEqual(builds[-2][3], current_revision)
            self.assertEqual(builds[-1][2], second.source_fingerprint)
            self.assertEqual(builds[-1][3], current_revision)
            self.assertEqual(builds[-1][0:2], ('completed', 1))

    def test_in_flight_path_move_rejects_stale_promotion(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / 'analysis.sqlite'
            track_ids = create_three_track_graph_db(db_path)
            _register_available_paths_as_scan_root(db_path)
            writer = SQLiteAnalysisRepository(str(db_path))
            reader = ReadOnlyExplorerSQLiteRepository(str(db_path))

            source_revision = writer.source_revision()
            attempt_id = writer.begin_graph_build(10, source_revision)
            _metadata, records = reader.candidate_snapshot()
            retained = tuple(record for record in records if record.run is not None and record.run.status == 'completed')
            features = tuple(_features(record) for record in retained)
            edges = tuple(_bounded_edges(features, 10))
            fingerprint = _source_fingerprint(retained)

            writer.register(Inventory(
                '/music',
                (
                    _scanned_file(db_path, '/music/Alpha moved.flac', track_ids[0]),
                    _scanned_file(db_path, '/music/Beta.flac', track_ids[1]),
                ),
                (),
                True,
            ))

            with self.assertRaisesRegex(AnalysisError, 'Graph source changed before snapshot promotion'):
                writer.replace_graph_snapshot(edges, 10, fingerprint, source_revision=source_revision, attempt_id=attempt_id)

    def test_graph_relevant_override_changes_fingerprint_and_rebuild_succeeds_without_permanent_stale_collision(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / 'analysis.sqlite'
            track_ids = create_three_track_graph_db(db_path)
            first = _build_graph(db_path)

            repo = SQLiteAnalysisRepository(str(db_path))
            repo.set_override(track_ids[0], 'bpm', '121.0')
            second = _build_graph(db_path)
            third = _build_graph(db_path)

            self.assertNotEqual(second.source_fingerprint, first.source_fingerprint)
            self.assertEqual(third.source_fingerprint, second.source_fingerprint)
            builds = _current_builds(db_path)
            self.assertEqual(builds[-1][0:2], ('completed', 1))
            self.assertEqual(builds[-1][2], second.source_fingerprint)
            self.assertEqual(
                sum(1 for status, is_current, *_ in builds if status == 'completed' and is_current == 1),
                1,
            )
            self.assertGreater(builds[-1][4], 0)

    def test_manual_text_bpm_override_changes_source_and_removes_track_from_positioned_graph_only(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / 'analysis.sqlite'
            track_ids = create_three_track_graph_db(db_path)
            first = _build_graph(db_path)
            before_record = ReadOnlyExplorerSQLiteRepository(str(db_path)).read_track(track_ids[0])
            self.assertIsNotNone(_axis_node(before_record, _map_track(before_record), '')[0])

            repo = SQLiteAnalysisRepository(str(db_path))
            repo.set_override(track_ids[0], 'bpm', 'manual text BPM')
            after_record = ReadOnlyExplorerSQLiteRepository(str(db_path)).read_track(track_ids[0])
            second = _build_graph(db_path)

            self.assertIsNone(_axis_node(after_record, _map_track(after_record), '')[0])
            self.assertNotEqual(second.source_fingerprint, first.source_fingerprint)
            status, global_edges = ReadOnlyExplorerSQLiteRepository(str(db_path)).current_graph_edges()
            positioned_status, positioned_edges = ReadOnlyExplorerSQLiteRepository(str(db_path)).current_positioned_graph_edges()
            self.assertEqual(status['state'], 'ready')
            self.assertEqual(positioned_status['state'], 'ready')
            self.assertGreater(len(global_edges), 0)
            self.assertEqual(positioned_edges, ())
            builds = _current_builds(db_path)
            self.assertEqual(builds[-1][0:2], ('completed', 1))
            self.assertEqual(builds[-1][2], second.source_fingerprint)

    def test_identical_input_rebuild_does_not_false_block_healthy_noop_build(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / 'analysis.sqlite'
            create_three_track_graph_db(db_path)
            first = _build_graph(db_path)
            second = _build_graph(db_path)

            self.assertEqual(second.source_fingerprint, first.source_fingerprint)
            builds = _current_builds(db_path)
            self.assertEqual(builds[-1][0:2], ('completed', 1))
            self.assertEqual(builds[-1][2], first.source_fingerprint)

    def test_non_graph_instruments_override_keeps_current_graph_and_stable_rebuild_source(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / 'analysis.sqlite'
            track_ids = create_three_track_graph_db(db_path)
            first = _build_graph(db_path)

            repo = SQLiteAnalysisRepository(str(db_path))
            repo.set_override(track_ids[0], 'instruments', 'piano, drums')
            with closing(sqlite3.connect(db_path)) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM graph_builds WHERE is_current=1').fetchone()[0], 1)

            second = _build_graph(db_path)

            self.assertEqual(second.source_fingerprint, first.source_fingerprint)
            builds = _current_builds(db_path)
            self.assertEqual(builds[-1][0:2], ('completed', 1))
            self.assertEqual(builds[-1][2], first.source_fingerprint)

    def test_in_flight_non_graph_instruments_override_does_not_reject_atomic_promotion(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / 'analysis.sqlite'
            track_ids = create_three_track_graph_db(db_path)
            writer = SQLiteAnalysisRepository(str(db_path))
            reader = ReadOnlyExplorerSQLiteRepository(str(db_path))

            source_revision = writer.source_revision()
            attempt_id = writer.begin_graph_build(10, source_revision)
            _metadata, records = reader.candidate_snapshot()
            retained = tuple(record for record in records if record.run is not None and record.run.status == 'completed')
            features = tuple(_features(record) for record in retained)
            edges = tuple(_bounded_edges(features, 10))
            fingerprint = _source_fingerprint(retained)
            self.assertGreater(len(edges), 0)

            writer.set_override(track_ids[0], 'instruments', 'piano, drums')
            build_id = writer.replace_graph_snapshot(edges, 10, fingerprint, source_revision=source_revision, attempt_id=attempt_id)

            self.assertEqual(build_id, attempt_id)
            builds = _current_builds(db_path)
            self.assertEqual(builds[-1][0:2], ('completed', 1))
            self.assertEqual(builds[-1][2], fingerprint)

    def test_in_flight_graph_relevant_bpm_override_rejects_obsolete_promotion(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / 'analysis.sqlite'
            track_ids = create_three_track_graph_db(db_path)
            writer = SQLiteAnalysisRepository(str(db_path))
            reader = ReadOnlyExplorerSQLiteRepository(str(db_path))

            source_revision = writer.source_revision()
            attempt_id = writer.begin_graph_build(10, source_revision)
            _metadata, records = reader.candidate_snapshot()
            retained = tuple(record for record in records if record.run is not None and record.run.status == 'completed')
            features = tuple(_features(record) for record in retained)
            edges = tuple(_bounded_edges(features, 10))
            fingerprint = _source_fingerprint(retained)

            writer.set_override(track_ids[0], 'bpm', '121.0')

            with self.assertRaisesRegex(AnalysisError, 'Graph source changed before snapshot promotion'):
                writer.replace_graph_snapshot(edges, 10, fingerprint, source_revision=source_revision, attempt_id=attempt_id)

    def test_in_flight_attempt_rejects_obsolete_edges_even_when_caller_passes_current_revision(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / 'analysis.sqlite'
            track_ids = create_three_track_graph_db(db_path)
            writer = SQLiteAnalysisRepository(str(db_path))
            reader = ReadOnlyExplorerSQLiteRepository(str(db_path))

            stale_revision = writer.source_revision()
            attempt_id = writer.begin_graph_build(10, stale_revision)
            _metadata, records = reader.candidate_snapshot()
            retained = tuple(record for record in records if record.run is not None and record.run.status == 'completed')
            features = tuple(_features(record) for record in retained)
            stale_edges = tuple(_bounded_edges(features, 10))
            stale_fingerprint = _source_fingerprint(retained)
            self.assertGreater(len(stale_edges), 0)

            writer.set_override(track_ids[0], 'bpm', '121.0')
            current_revision = writer.source_revision()
            self.assertNotEqual(current_revision, stale_revision)

            with self.assertRaisesRegex(AnalysisError, 'Graph source changed before snapshot promotion'):
                writer.replace_graph_snapshot(
                    stale_edges,
                    10,
                    stale_fingerprint,
                    source_revision=current_revision,
                    attempt_id=attempt_id,
                )

            with closing(sqlite3.connect(db_path)) as db:
                self.assertEqual(
                    db.execute(
                        'SELECT status,is_current,edge_count,source_revision FROM graph_builds WHERE id=?',
                        (attempt_id,),
                    ).fetchone(),
                    ('interrupted', 0, 0, stale_revision),
                )
                self.assertEqual(db.execute('SELECT count(*) FROM graph_edges').fetchone()[0], 0)
                self.assertEqual(db.execute('SELECT count(*) FROM graph_build_edges WHERE build_id=?', (attempt_id,)).fetchone()[0], 0)
                self.assertEqual(db.execute('SELECT count(*) FROM graph_builds WHERE is_current=1').fetchone()[0], 0)

    def test_complete_scan_availability_loss_rejects_stale_promotion_and_readonly_reports_no_current_edges(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / 'analysis.sqlite'
            create_three_track_graph_db(db_path)
            writer = SQLiteAnalysisRepository(str(db_path))
            reader = ReadOnlyExplorerSQLiteRepository(str(db_path))

            source_revision = writer.source_revision()
            attempt_id = writer.begin_graph_build(10, source_revision)
            _metadata, records = reader.candidate_snapshot()
            retained = tuple(record for record in records if record.run is not None and record.run.status == 'completed')
            features = tuple(_features(record) for record in retained)
            edges = tuple(_bounded_edges(features, 10))
            fingerprint = _source_fingerprint(retained)
            self.assertGreater(len(edges), 0)

            with closing(sqlite3.connect(db_path)) as db:
                paths = tuple(row[0] for row in db.execute('SELECT path FROM locations WHERE available=1'))
                db.executemany('INSERT OR IGNORE INTO scan_roots(root,path) VALUES(?,?)', (('/music', path) for path in paths))
                db.commit()
            missing = writer.register(Inventory('/music', (), (), True))
            self.assertGreater(len(missing), 0)

            with self.assertRaisesRegex(AnalysisError, 'Graph source changed before snapshot promotion'):
                writer.replace_graph_snapshot(edges, 10, fingerprint, source_revision=source_revision, attempt_id=attempt_id)

            status, current_edges = reader.current_graph_edges()
            self.assertIn(status['state'], {'building', 'interrupted', 'stale', 'build_needed'})
            self.assertEqual(current_edges, ())
            with closing(sqlite3.connect(db_path)) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM graph_builds WHERE is_current=1').fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
