import errno
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from music_analyzer.application.dto.analysis import AnalysisError
from music_analyzer.infrastructure.persistence.analysis import SQLiteAnalysisRepository
from tests.acceptance.test_graph_build_cli import create_candidate_database


class GraphBuildOwnerLivenessTests(unittest.TestCase):
    def _repository_with_build(self, detail):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / 'analysis.sqlite'
        create_candidate_database(path)
        repository = SQLiteAnalysisRepository(str(path))
        revision = repository.source_revision()
        with closing(sqlite3.connect(path)) as db, db:
            db.execute(
                '''INSERT INTO graph_builds(
                    id,status,detail,edge_count,sparse_k,source_fingerprint,source_revision,attempt_revision,
                    distance_policy_version,neighbour_policy_version,is_current,completed_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,0,NULL)''',
                ('owner-build', 'building', detail, 0, 10, revision, revision, 'attempt',
                 'symmetric-feature-distance-v1', 'endpoint-local-exact-top-k-neighbours-v2'),
            )
        return path, repository, revision

    def _owner_detail(self, pid=4242, owner_start='start-token'):
        return json.dumps({
            'reason': 'warm graph build is running',
            'owner_pid': pid,
            'owner_start': owner_start,
        }, sort_keys=True, separators=(',', ':'))

    def test_legacy_plain_text_building_detail_from_pr49_is_recovered_and_completed_history_retained(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / 'analysis.sqlite'
        create_candidate_database(path)
        repository = SQLiteAnalysisRepository(str(path))
        revision = repository.source_revision()
        with closing(sqlite3.connect(path)) as db, db:
            db.execute(
                '''INSERT INTO graph_builds(
                    id,status,detail,edge_count,sparse_k,source_fingerprint,source_revision,attempt_revision,
                    distance_policy_version,neighbour_policy_version,is_current,completed_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,0,CURRENT_TIMESTAMP)''',
                ('completed-history', 'completed', '', 0, 10, 'previous-fingerprint', revision, 'completed-attempt',
                 'symmetric-feature-distance-v1', 'endpoint-local-exact-top-k-neighbours-v2'),
            )
            db.execute(
                '''INSERT INTO graph_builds(
                    id,status,detail,edge_count,sparse_k,source_fingerprint,source_revision,attempt_revision,
                    distance_policy_version,neighbour_policy_version,is_current,completed_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,0,NULL)''',
                ('legacy-pr49-build', 'building', 'explicit graph build is running', 0, 10, revision, revision, 'legacy-attempt',
                 'symmetric-feature-distance-v1', 'endpoint-local-exact-top-k-neighbours-v2'),
            )

        status = repository.current_graph_snapshot(10, revision)
        retry = repository.begin_graph_build(10, revision)

        self.assertEqual(status['state'], 'interrupted')
        self.assertEqual(status['build_id'], 'legacy-pr49-build')
        self.assertIsNotNone(retry)
        self.assertNotEqual(retry, 'legacy-pr49-build')
        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(db.execute("SELECT status FROM graph_builds WHERE id='legacy-pr49-build'").fetchone()[0], 'interrupted')
            self.assertEqual(db.execute("SELECT status,is_current FROM graph_builds WHERE id='completed-history'").fetchone(), ('completed', 0))
            self.assertEqual(db.execute("SELECT count(*) FROM graph_builds WHERE status='building'").fetchone()[0], 1)

    def test_live_pid_with_unreadable_proc_start_token_remains_building_and_second_claim_is_noop(self):
        _path, repository, revision = self._repository_with_build(self._owner_detail())

        with patch('music_analyzer.infrastructure.persistence.analysis.os.kill') as kill, \
                patch.object(SQLiteAnalysisRepository, '_process_start_token', return_value=''):
            status = repository.current_graph_snapshot(10, revision)
            second_claim = repository.begin_graph_build(10, revision)

        kill.assert_any_call(4242, 0)
        self.assertEqual(status['state'], 'building')
        self.assertEqual(status['build_id'], 'owner-build')
        self.assertIsNone(second_claim)

    def test_legacy_plain_text_building_row_is_interrupted_and_retryable(self):
        path, repository, revision = self._repository_with_build('explicit graph build is running')

        status = repository.current_graph_snapshot(10, revision)
        retry = repository.begin_graph_build(10, revision)

        self.assertEqual(status['state'], 'interrupted')
        self.assertIsNotNone(retry)
        self.assertNotEqual(retry, 'owner-build')
        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(db.execute("SELECT status FROM graph_builds WHERE id='owner-build'").fetchone()[0], 'interrupted')
            self.assertEqual(db.execute("SELECT count(*) FROM graph_builds WHERE status='building'").fetchone()[0], 1)

    def test_interrupted_legacy_attempt_cannot_later_promote_over_retry(self):
        path, repository, revision = self._repository_with_build('explicit graph build is running')
        status = repository.current_graph_snapshot(10, revision)
        retry = repository.begin_graph_build(10, revision)

        self.assertEqual(status['state'], 'interrupted')
        self.assertIsNotNone(retry)
        with self.assertRaisesRegex(AnalysisError, 'no longer promotable'):
            repository.replace_graph_snapshot((), 10, revision, source_revision=revision, attempt_id='owner-build')
        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(db.execute("SELECT status FROM graph_builds WHERE id='owner-build'").fetchone()[0], 'interrupted')
            self.assertEqual(db.execute('SELECT count(*) FROM graph_builds WHERE is_current=1').fetchone()[0], 0)

    def test_dead_pid_esrch_recovers_interrupted_and_allows_retry(self):
        path, repository, revision = self._repository_with_build(self._owner_detail())

        with patch('music_analyzer.infrastructure.persistence.analysis.os.kill', side_effect=ProcessLookupError(errno.ESRCH, 'missing')):
            status = repository.current_graph_snapshot(10, revision)
            retry = repository.begin_graph_build(10, revision)

        self.assertEqual(status['state'], 'interrupted')
        self.assertIsNotNone(retry)
        self.assertNotEqual(retry, 'owner-build')
        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(db.execute("SELECT status FROM graph_builds WHERE id='owner-build'").fetchone()[0], 'interrupted')
            self.assertEqual(db.execute("SELECT count(*) FROM graph_builds WHERE status='building'").fetchone()[0], 1)

    def test_start_token_mismatch_handles_pid_reuse_as_interrupted_and_retryable(self):
        path, repository, revision = self._repository_with_build(self._owner_detail(owner_start='old-start'))

        with patch('music_analyzer.infrastructure.persistence.analysis.os.kill') as kill, \
                patch.object(SQLiteAnalysisRepository, '_process_start_token', return_value='new-start'):
            status = repository.current_graph_snapshot(10, revision)
            retry = repository.begin_graph_build(10, revision)

        kill.assert_any_call(4242, 0)
        self.assertEqual(status['state'], 'interrupted')
        self.assertIsNotNone(retry)
        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(db.execute("SELECT status FROM graph_builds WHERE id='owner-build'").fetchone()[0], 'interrupted')
            self.assertEqual(db.execute("SELECT count(*) FROM graph_builds WHERE status='building'").fetchone()[0], 1)

    def test_eperm_indeterminate_live_fails_safe_as_building(self):
        _path, repository, revision = self._repository_with_build(self._owner_detail())

        with patch('music_analyzer.infrastructure.persistence.analysis.os.kill', side_effect=PermissionError(errno.EPERM, 'denied')):
            status = repository.current_graph_snapshot(10, revision)
            second_claim = repository.begin_graph_build(10, revision)

        self.assertEqual(status['state'], 'building')
        self.assertEqual(status['build_id'], 'owner-build')
        self.assertIsNone(second_claim)

    def test_non_proc_platform_explicit_build_without_start_token_is_not_broken(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / 'analysis.sqlite'
        create_candidate_database(path)
        repository = SQLiteAnalysisRepository(str(path))
        revision = repository.source_revision()

        with patch.object(SQLiteAnalysisRepository, '_process_start_token', return_value=''):
            build_id = repository.begin_graph_build(10, revision)
            status = repository.current_graph_snapshot(10, revision)
            second_claim = repository.begin_graph_build(10, revision)

        self.assertIsNotNone(build_id)
        self.assertEqual(status['state'], 'building')
        self.assertEqual(status['build_id'], build_id)
        self.assertIsNone(second_claim)
        with closing(sqlite3.connect(path)) as db:
            stored_detail = json.loads(db.execute('SELECT detail FROM graph_builds WHERE id=?', (build_id,)).fetchone()[0])
            self.assertEqual(stored_detail['owner_start'], '')
            self.assertEqual(db.execute('SELECT status FROM graph_builds WHERE id=?', (build_id,)).fetchone()[0], 'building')


if __name__ == '__main__':
    unittest.main()
