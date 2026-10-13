"""Passing baseline controls for the fresh D1 dispatch RED packet.

These assert existing FULL readers and tiny physical/FK fixture health only.
They do not implement or certify D1: healthy D1 must remain incomplete/exit4
with scope_not_implemented until full P7 coverage ships in D3.
"""
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from music_analyzer.infrastructure.persistence.explorer_readonly import (
    ReadOnlyExplorerSQLiteRepository as AnalyzerReader,
)
from music_explorer.infrastructure.explorer_readonly import (
    ReadOnlyExplorerSQLiteRepository as StandaloneReader,
)
from tests.integration.infrastructure.integrity_d1_public_fixture import (
    PUBLIC_TRACK_IDS,
    create_public_core_database,
)


class IntegrityD1PublicFixtureControls(unittest.TestCase):
    def test_literal_supported_schemas_have_version_correct_objects(self):
        for version in range(6, 11):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as td:
                path = Path(td) / 'public.sqlite'
                create_public_core_database(path, version)
                with closing(sqlite3.connect(path)) as db:
                    self.assertEqual(db.execute('PRAGMA application_id').fetchone(),
                                     (0x4D414E41,))
                    self.assertEqual(db.execute('PRAGMA user_version').fetchone(), (version,))
                    for table, first_version in (
                        ('graph_builds', 7), ('graph_build_positioned_edges', 8),
                        ('graph_feature_evidence', 9),
                    ):
                        present = db.execute(
                            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                            (table,),
                        ).fetchone()
                        self.assertEqual(bool(present), version >= first_version)
                    if version >= 7:
                        columns = tuple(row[1] for row in db.execute('PRAGMA table_info(graph_builds)'))
                        self.assertEqual('source_revision' in columns, version == 10)
                        self.assertEqual('attempt_revision' in columns, version == 10)
                    self.assertEqual(db.execute(
                        "SELECT count(*) FROM sqlite_master WHERE type='trigger'"
                    ).fetchone(), (0,))

    def test_all_core_rows_are_populated_with_matching_digest_and_audio(self):
        for version in range(6, 11):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as td:
                path = Path(td) / 'public.sqlite'
                self.assertEqual(create_public_core_database(path, version), PUBLIC_TRACK_IDS)
                with closing(sqlite3.connect(path)) as db:
                    rows = tuple(db.execute(
                        'SELECT t.id,t.sha256,t.size,a.duration_seconds,a.duration_source,'
                        'a.status,a.reason FROM tracks t JOIN track_audio a ON a.track_id=t.id '
                        'ORDER BY t.id'
                    ))
                    self.assertEqual(rows, tuple(
                        (track_id, str(index) * 64, 100 + index, 180.0 + index,
                         'mutagen', 'eligible', '')
                        for index, track_id in enumerate(PUBLIC_TRACK_IDS, start=1)
                    ))
                    self.assertEqual(db.execute('SELECT count(*) FROM active_locations').fetchone(), (2,))

    def test_existing_full_readers_accept_all_supported_fixtures_without_mutation(self):
        for version in range(6, 11):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as td:
                path = Path(td) / 'public.sqlite'
                create_public_core_database(path, version)
                before = path.read_bytes()
                for reader_type in (AnalyzerReader, StandaloneReader):
                    with self.subTest(reader=reader_type.__module__):
                        reader = reader_type(str(path))
                        self.assertEqual(reader.metadata()['schema_version'], version)
                        self.assertEqual(reader.track_ids(), PUBLIC_TRACK_IDS)
                        self.assertEqual(path.read_bytes(), before)

    def test_tiny_physical_and_foreign_key_baseline_cursors_exhaust_healthy(self):
        for version in range(6, 11):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as td:
                path = Path(td) / 'public.sqlite'
                create_public_core_database(path, version)
                with closing(sqlite3.connect(path)) as db:
                    physical = db.execute('PRAGMA integrity_check(101)')
                    self.assertEqual(tuple(physical), (('ok',),))
                    self.assertIsNone(physical.fetchone())
                    foreign_keys = db.execute('PRAGMA foreign_key_check')
                    self.assertEqual(tuple(foreign_keys), ())
                    self.assertIsNone(foreign_keys.fetchone())

    def test_fixture_rejects_unsupported_versions_before_creating_a_database(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'not-created.sqlite'
            for version in (5, 11):
                with self.subTest(version=version), self.assertRaises(ValueError):
                    create_public_core_database(path, version)
                self.assertFalse(path.exists())
