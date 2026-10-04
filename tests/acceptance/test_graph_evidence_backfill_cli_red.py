import contextlib
import io
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from music_analyzer.frameworks.cli.main import main
from tests.support.graph_evidence_backfill_fixture import (
    complete_graph_relevant_run,
    create_historical_v10_database,
    current_graph_feature_rows,
    current_graph_state,
    fail_latest_run,
    register_track,
)
from music_analyzer.infrastructure.persistence.analysis import SQLiteAnalysisRepository


class GraphEvidenceBackfillCLIRedTests(unittest.TestCase):
    def invoke(self, *args):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            patch('music_analyzer.frameworks.cli.main.build_analysis', side_effect=AssertionError('evidence backfill must not analyze audio')),
            patch('music_analyzer.frameworks.cli.main.build_batch_worker', side_effect=AssertionError('evidence backfill must not build batch worker')),
            patch('music_analyzer.frameworks.cli.main.MutagenMetadataReader.read', side_effect=AssertionError('evidence backfill must not read audio metadata')),
            patch('music_analyzer.frameworks.cli.main.load_backend', side_effect=AssertionError('evidence backfill must not load inference backend')),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            try:
                code = main(list(args))
            except SystemExit as error:
                code = int(error.code or 0)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_explicit_backfill_populates_missing_current_evidence_and_preserves_warm_graph(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            track_ids = create_historical_v10_database(path, track_count=2, include_graph=True)
            before_graph = current_graph_state(path)
            self.assertEqual(current_graph_feature_rows(path), ())

            code, stdout, stderr = self.invoke('graph', 'evidence-backfill', '--database', str(path))

            self.assertEqual((code, stderr), (0, ''))
            rows = current_graph_feature_rows(path)
            self.assertEqual([row[0] for row in rows], list(track_ids))
            self.assertTrue(all(row[2] and len(row[2]) == 64 and row[3] == 1 for row in rows))
            self.assertIn('backfilled=2', stdout)
            self.assertEqual(current_graph_state(path), before_graph)

    def test_limit_resumes_idempotently_without_duplicate_or_changed_fingerprint(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            track_ids = create_historical_v10_database(path, track_count=3)

            first_code, first_stdout, first_stderr = self.invoke('graph', 'evidence-backfill', '--database', str(path), '--limit', '1')
            first_rows = current_graph_feature_rows(path)
            second_code, second_stdout, second_stderr = self.invoke('graph', 'evidence-backfill', '--database', str(path), '--limit', '10')
            second_rows = current_graph_feature_rows(path)
            third_code, third_stdout, third_stderr = self.invoke('graph', 'evidence-backfill', '--database', str(path), '--limit', '10')

            self.assertEqual((first_code, first_stderr), (0, ''))
            self.assertEqual((second_code, second_stderr), (0, ''))
            self.assertEqual((third_code, third_stderr), (0, ''))
            self.assertEqual(len(first_rows), 1)
            self.assertEqual(len(second_rows), 3)
            self.assertEqual(sorted(row[0] for row in second_rows), sorted(track_ids))
            self.assertEqual(current_graph_feature_rows(path), second_rows)
            self.assertIn('backfilled=1', first_stdout)
            self.assertIn('backfilled=2', second_stdout)
            self.assertIn('already_current=3', third_stdout)

    def test_latest_failed_run_clears_stale_current_older_evidence_instead_of_serving_it(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            repository = SQLiteAnalysisRepository(str(path))
            identity = register_track(repository, 'a')
            older_run = complete_graph_relevant_run(repository, identity)
            fail_latest_run(repository, identity)
            with closing(sqlite3.connect(path)) as db, db:
                db.execute('UPDATE graph_feature_evidence SET is_current=1 WHERE run_id=?', (older_run,))
            self.assertEqual(len(current_graph_feature_rows(path)), 1)

            code, stdout, stderr = self.invoke('graph', 'evidence-backfill', '--database', str(path))

            self.assertEqual((code, stderr), (0, ''))
            self.assertEqual(current_graph_feature_rows(path), ())
            self.assertIn('skipped_latest_not_completed=1', stdout)
            self.assertIn('cleared_stale_current=1', stdout)

    def test_opening_writer_does_not_implicitly_backfill_missing_historical_evidence_guard(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            create_historical_v10_database(path, track_count=1)

            SQLiteAnalysisRepository(str(path))

            self.assertEqual(current_graph_feature_rows(path), ())


if __name__ == '__main__':
    unittest.main()
