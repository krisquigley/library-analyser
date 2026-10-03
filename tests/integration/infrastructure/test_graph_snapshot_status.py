import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from music_analyzer.infrastructure.persistence.analysis import SQLiteAnalysisRepository
from tests.acceptance.test_graph_build_cli import create_candidate_database


class GraphSnapshotStatusTests(unittest.TestCase):
    def test_current_graph_snapshot_ready_only_when_revision_policy_and_k_match(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            create_candidate_database(path)
            repository = SQLiteAnalysisRepository(str(path))
            revision = repository.source_revision()
            build_id = repository.replace_graph_snapshot((), 10, 'fingerprint', source_revision=revision)

            ready = repository.current_graph_snapshot(10, revision)
            stale_k = repository.current_graph_snapshot(5, revision)
            stale_revision = repository.current_graph_snapshot(10, 'changed-source-revision')

        self.assertEqual(ready['state'], 'ready')
        self.assertEqual(ready['build_id'], build_id)
        self.assertEqual(stale_k['state'], 'stale')
        self.assertEqual(stale_revision['state'], 'stale')

    def test_current_graph_snapshot_reports_matching_building_attempt(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            create_candidate_database(path)
            repository = SQLiteAnalysisRepository(str(path))
            revision = repository.source_revision()
            build_id = repository.begin_graph_build(10, revision)

            status = repository.current_graph_snapshot(10, revision)

        self.assertEqual(status['state'], 'building')
        self.assertEqual(status['build_id'], build_id)
        self.assertIn('running', status['reason'])

    def test_failed_and_interrupted_attempts_are_not_current_and_remain_retryable(self):
        for terminal in ('failed', 'interrupted'):
            with self.subTest(terminal=terminal), tempfile.TemporaryDirectory() as td:
                path = Path(td) / 'analysis.sqlite'
                create_candidate_database(path)
                repository = SQLiteAnalysisRepository(str(path))
                revision = repository.source_revision()
                build_id = repository.begin_graph_build(10, revision)
                repository.finish_graph_build_attempt(build_id, terminal, terminal)

                status = repository.current_graph_snapshot(10, revision)

                self.assertEqual(status['state'], terminal)
                with closing(sqlite3.connect(path)) as db:
                    self.assertEqual(db.execute('SELECT is_current FROM graph_builds WHERE id=?', (build_id,)).fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
