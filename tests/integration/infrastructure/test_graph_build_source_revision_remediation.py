import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from music_analyzer.application.dto.catalogue import Inventory
from music_analyzer.application.use_cases.build_graph import BuildGraphSnapshot, _source_fingerprint
from music_analyzer.application.use_cases.candidates import _features
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


class GraphBuildSourceRevisionRemediationTests(unittest.TestCase):
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
