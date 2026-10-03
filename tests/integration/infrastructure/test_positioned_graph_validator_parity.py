import sqlite3
import tempfile
import unittest
from pathlib import Path

from music_analyzer.application.dto.catalogue import Inventory, ScannedFile, TrackMetadata
from music_analyzer.application.dto.analysis import AnalysisError as AnalyzerAnalysisError
from music_analyzer.domain.catalogue import FileIdentity
from music_analyzer.domain.projection import ProjectionEdge
from music_analyzer.infrastructure.persistence.analysis import SQLiteAnalysisRepository
from music_analyzer.infrastructure.persistence.explorer_readonly import ReadOnlyExplorerSQLiteRepository as AnalyzerReadOnlyExplorerSQLiteRepository
from music_explorer.infrastructure.explorer_readonly import AnalysisError as StandaloneAnalysisError
from music_explorer.infrastructure.explorer_readonly import ReadOnlyExplorerSQLiteRepository as StandaloneReadOnlyExplorerSQLiteRepository


class PositionedGraphValidatorParityTests(unittest.TestCase):
    def test_rejects_current_positioned_edges_that_do_not_match_current_build_history(self):
        self._assert_both_adapters_reject_tamper(
            """
            UPDATE graph_positioned_edges
            SET score=0.1, distance=0.1
            """,
        )

    def test_rejects_current_positioned_edges_without_a_current_graph_build(self):
        self._assert_both_adapters_reject_tamper(
            """
            UPDATE graph_builds SET is_current=0;
            DELETE FROM graph_edges;
            """,
        )

    def test_rejects_positioned_snapshot_count_mismatch(self):
        self._assert_both_adapters_reject_tamper(
            """
            UPDATE graph_build_positioned_snapshots SET edge_count=edge_count+1
            """,
        )

    def test_rejects_invalid_positioned_build_edge_fields(self):
        self._assert_both_adapters_reject_tamper(
            """
            PRAGMA ignore_check_constraints=ON;
            UPDATE graph_build_positioned_edges
            SET supported_group_count=0
            """,
        )

    def _assert_both_adapters_reject_tamper(self, tamper_sql):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            self._create_positioned_graph_database(path)
            with sqlite3.connect(path) as db:
                db.executescript(tamper_sql)

            with self.assertRaisesRegex(AnalyzerAnalysisError, 'Unexpected analysis database rows'):
                AnalyzerReadOnlyExplorerSQLiteRepository(str(path)).track_ids()
            with self.assertRaisesRegex(StandaloneAnalysisError, 'Unexpected analysis database rows'):
                StandaloneReadOnlyExplorerSQLiteRepository(str(path)).track_ids()

    def _create_positioned_graph_database(self, path):
        repository = SQLiteAnalysisRepository(str(path))
        first = self._register_track(repository, 'a')
        second = self._register_track(repository, 'b')
        edge = ProjectionEdge(first, second, 0.25, 2)
        repository.replace_graph_snapshot((edge,), 10, 'synthetic-positioned-validator-parity', positioned_edges=(edge,))

    def _register_track(self, repository, suffix):
        identity = FileIdentity(suffix * 64, 10)
        repository.register(Inventory('/music', (
            ScannedFile(f'/music/{suffix}.flac', identity, 1, 'flac', TrackMetadata(duration_seconds=120.0, duration_source='mutagen')),
        ), (), False))
        return identity.track_id


if __name__ == '__main__':
    unittest.main()
