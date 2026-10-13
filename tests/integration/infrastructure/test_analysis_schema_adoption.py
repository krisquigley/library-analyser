"""Writer adoption rejects altered historical view contracts before migration."""
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from music_analyzer.application.dto.analysis import AnalysisError
from music_analyzer.infrastructure.persistence.analysis import SQLiteAnalysisRepository
from tests.integration.infrastructure.analysis_historical_schema_fixture import create_historical_schema
from tests.integration.infrastructure.test_analysis_schema_adoption_red import logical_snapshot


class AnalysisViewAdoptionTests(unittest.TestCase):
    def test_supported_versions_reject_changed_or_missing_views_without_migration(self):
        for version in range(6, 11):
            for view in ('active_tracks', 'active_locations'):
                for change in ('predicate', 'missing'):
                    with self.subTest(version=version, view=view, change=change), tempfile.TemporaryDirectory() as directory:
                        path = Path(directory) / 'analysis.sqlite'
                        create_historical_schema(path, version)
                        with closing(sqlite3.connect(path)) as db:
                            sql = db.execute(
                                "SELECT sql FROM sqlite_master WHERE type='view' AND name=?", (view,)
                            ).fetchone()[0]
                            db.execute(f'DROP VIEW {view}')
                            if change == 'predicate':
                                self.assertIn("a.status='eligible'", sql)
                                db.execute(sql.replace("a.status='eligible'", "a.status='excluded'"))
                            db.commit()
                        before = logical_snapshot(path)
                        with self.assertRaisesRegex(AnalysisError, '(?i)schema|view'):
                            SQLiteAnalysisRepository(str(path))
                        self.assertEqual(logical_snapshot(path), before)
