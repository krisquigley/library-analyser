import multiprocessing
import sqlite3
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path

from music_analyzer.application.use_cases.build_graph import BuildGraphSnapshot
from music_analyzer.infrastructure.persistence.analysis import SQLiteAnalysisRepository
from music_analyzer.infrastructure.persistence.explorer_readonly import ReadOnlyExplorerSQLiteRepository
from tests.acceptance.test_graph_build_cli import create_candidate_database


class _CountingGraphReader:
    def __init__(self, db_path: str, counter):
        self._reader = ReadOnlyExplorerSQLiteRepository(db_path)
        self._counter = counter

    def candidate_snapshot(self):
        with self._counter.get_lock():
            self._counter.value += 1
        time.sleep(0.5)
        return self._reader.candidate_snapshot()


def _racy_auto_graph_process(db_path: str, barrier, counter, result_queue) -> None:
    writer = SQLiteAnalysisRepository(db_path)
    revision = writer.source_revision()
    status = writer.current_graph_snapshot(10, revision)
    barrier.wait(timeout=5)
    result = BuildGraphSnapshot(_CountingGraphReader(db_path, counter), writer).execute()
    result_queue.put((status['state'], result.state, result.edge_count))


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

    def test_two_racy_auto_builders_compute_once_and_publish_one_completed_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            create_candidate_database(path)
            context = multiprocessing.get_context('fork')
            barrier = context.Barrier(2)
            counter = context.Value('i', 0)
            result_queue = context.Queue()
            processes = [
                context.Process(target=_racy_auto_graph_process, args=(str(path), barrier, counter, result_queue))
                for _ in range(2)
            ]
            for process in processes:
                process.start()
            for process in processes:
                process.join(timeout=10)
            for process in processes:
                if process.is_alive():
                    process.kill()
                    process.join(timeout=2)
            self.assertEqual([process.exitcode for process in processes], [0, 0])
            results = [result_queue.get(timeout=1) for _ in processes]

            self.assertEqual(counter.value, 1)
            self.assertEqual([item[0] for item in results], ['build_needed', 'build_needed'])
            self.assertEqual(sorted(item[1] for item in results), ['building', 'built'])
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute("SELECT count(*) FROM graph_builds WHERE status='building'").fetchone()[0], 0)
                self.assertEqual(db.execute("SELECT count(*) FROM graph_builds WHERE status='completed' AND is_current=1").fetchone()[0], 1)

    def test_atomic_begin_graph_build_allows_only_one_active_owner_for_same_revision_and_policy(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            create_candidate_database(path)
            first = SQLiteAnalysisRepository(str(path))
            second = SQLiteAnalysisRepository(str(path))
            revision = first.source_revision()

            first_build_id = first.begin_graph_build(10, revision)
            second_build_id = second.begin_graph_build(10, revision)
            status = second.current_graph_snapshot(10, revision)

            self.assertIsNotNone(first_build_id)
            self.assertIsNone(second_build_id)
            self.assertEqual(status['state'], 'building')
            self.assertEqual(status['build_id'], first_build_id)
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute("SELECT count(*) FROM graph_builds WHERE status='building'").fetchone()[0], 1)

    def test_orphaned_building_attempt_is_interrupted_and_retryable_without_timer_lease(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            create_candidate_database(path)
            repository = SQLiteAnalysisRepository(str(path))
            revision = repository.source_revision()
            with closing(sqlite3.connect(path)) as db, db:
                db.execute(
                    '''INSERT INTO graph_builds(
                        id,status,detail,edge_count,sparse_k,source_fingerprint,source_revision,attempt_revision,
                        distance_policy_version,neighbour_policy_version,is_current,completed_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,0,NULL)''',
                    ('orphan-build', 'building', '{"reason":"warm graph build is running","owner_pid":999999,"owner_start":"missing"}',
                     0, 10, revision, revision, 'attempt', 'symmetric-feature-distance-v1',
                     'endpoint-local-exact-top-k-neighbours-v2'),
                )

            status = repository.current_graph_snapshot(10, revision)
            retry_id = repository.begin_graph_build(10, revision)

            self.assertEqual(status['state'], 'interrupted')
            self.assertIsNotNone(retry_id)
            self.assertNotEqual(retry_id, 'orphan-build')
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute("SELECT status FROM graph_builds WHERE id='orphan-build'").fetchone()[0], 'interrupted')
                self.assertEqual(db.execute("SELECT count(*) FROM graph_builds WHERE status='building'").fetchone()[0], 1)

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
