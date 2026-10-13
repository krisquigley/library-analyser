"""Issue #88 revised P5: supported identity does not certify view semantics.

Adoption fixtures use the public writer; compatibility fixtures use literal
historical DDL. Two synthetic tracks and sequential connections.
The externally changed file differs solely in active_tracks' eligibility predicate.
These tests deliberately retain the readers' existing FULL validation contract.
"""
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from music_analyzer.application.dto.analysis import AnalysisError
from music_analyzer.application.dto.catalogue import Inventory, ScannedFile, TrackMetadata
from music_analyzer.domain.catalogue import FileIdentity
from music_analyzer.infrastructure.persistence.analysis import (
    APPLICATION_ID,
    SQLiteAnalysisRepository,
)
from music_analyzer.infrastructure.persistence.explorer_readonly import (
    ReadOnlyExplorerSQLiteRepository,
)
from music_explorer.infrastructure.explorer_readonly import (
    AnalysisError as StandaloneAnalysisError,
    ReadOnlyExplorerSQLiteRepository as StandaloneReadOnlyExplorerSQLiteRepository,
)


READERS = {
    ReadOnlyExplorerSQLiteRepository: AnalysisError,
    StandaloneReadOnlyExplorerSQLiteRepository: StandaloneAnalysisError,
}


def logical_snapshot(path):
    """Schema, every persisted table row, and identity; not SQLite file bytes.

    Opening a database may legitimately interact with journals/locks. A byte
    comparison would conflate those effects with schema or catalogue repair.
    """
    with closing(sqlite3.connect(path)) as db:
        schema = tuple(db.execute(
            'SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name'
        ))
        table_rows = []
        for (name,) in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall():
            quoted_name = '"' + name.replace('"', '""') + '"'
            rows = tuple(db.execute(f'SELECT * FROM {quoted_name} ORDER BY rowid'))
            table_rows.append((name, rows))
        return (
            db.execute('PRAGMA application_id').fetchone(),
            db.execute('PRAGMA user_version').fetchone(),
            schema,
            tuple(table_rows),
        )


class AnalysisSchemaAdoptionRedTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'analysis.sqlite'
        identities = (FileIdentity('a' * 64, 123), FileIdentity('b' * 64, 456))
        self.track_ids = tuple(identity.track_id for identity in identities)
        writer = SQLiteAnalysisRepository(str(self.path))
        writer.register(Inventory('/music', tuple(
            ScannedFile(
                f'/music/{index}.flac', identity, index + 1, 'flac',
                TrackMetadata(
                    common=(('title', f'Adoption control {index}'),),
                    duration_seconds=180.0, duration_source='mutagen',
                ),
            )
            for index, identity in enumerate(identities)
        ), (), True))
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('PRAGMA application_id').fetchone(), (APPLICATION_ID,))
            self.assertEqual(db.execute('PRAGMA user_version').fetchone(), (10,))
            self.assertEqual(tuple(db.execute('SELECT id FROM active_tracks ORDER BY id')),
                             tuple((track_id,) for track_id in self.track_ids))

    def _logical_snapshot(self):
        return logical_snapshot(self.path)

    def _replace_active_tracks_predicate(self):
        before = self._logical_snapshot()
        with closing(sqlite3.connect(self.path)) as db:
            columns_before = tuple(db.execute('PRAGMA table_info(active_tracks)'))
            original_sql = db.execute(
                "SELECT sql FROM sqlite_master WHERE type='view' AND name='active_tracks'"
            ).fetchone()[0]
            self.assertIn("WHERE a.status='eligible'", original_sql)
            changed_sql = original_sql.replace(
                "WHERE a.status='eligible'", "WHERE a.status='excluded'"
            )
            db.execute('DROP VIEW active_tracks')
            db.execute(changed_sql)
            db.commit()
            self.assertEqual(tuple(db.execute('PRAGMA table_info(active_tracks)')), columns_before)
            self.assertEqual(db.execute('SELECT count(*) FROM active_tracks').fetchone(), (0,))
        after = self._logical_snapshot()
        self.assertEqual(after[:2], before[:2])
        self.assertEqual(after[3], before[3])
        expected_schema = tuple(
            (kind, name, table, changed_sql if kind == 'view' and name == 'active_tracks' else sql)
            for kind, name, table, sql in before[2]
        )
        self.assertEqual(after[2], expected_schema)
        return after

    def test_canonical_v10_reopen_preserves_database_and_reader_membership(self):
        before = self._logical_snapshot()

        SQLiteAnalysisRepository(str(self.path))
        for reader in READERS:
            with self.subTest(reader=reader.__module__):
                self.assertEqual(reader(str(self.path)).track_ids(), self.track_ids)

        self.assertEqual(self._logical_snapshot(), before)

    def test_reader_rejects_same_columns_with_wrong_active_tracks_predicate(self):
        before = self._replace_active_tracks_predicate()

        for reader in READERS:
            with self.subTest(reader=reader.__module__):
                try:
                    with self.assertRaisesRegex(READERS[reader], '(?i)schema|view'):
                        reader(str(self.path)).track_ids()
                finally:
                    self.assertEqual(self._logical_snapshot(), before)

    def test_writer_constructor_rejects_wrong_view_before_changing_database(self):
        before = self._replace_active_tracks_predicate()

        # Construction is the adoption boundary: do not invoke a later write to
        # provoke rejection, nor allow replacement of the externally modified view.
        try:
            with self.assertRaisesRegex(AnalysisError, '(?i)schema|view'):
                SQLiteAnalysisRepository(str(self.path))
        finally:
            self.assertEqual(self._logical_snapshot(), before)


class AnalysisHistoricalSchemaCompatibilityTests(unittest.TestCase):
    def _seed_historical_database(self, path, version):
        # Literal historical DDL, not a current database with its version changed.
        from tests.integration.infrastructure.analysis_historical_schema_fixture import (
            create_historical_schema,
        )
        create_historical_schema(path, version)
        track_ids = tuple('sha256:' + digest * 64 for digest in ('a', 'b'))
        with closing(sqlite3.connect(path)) as db:
            db.execute('PRAGMA foreign_keys=ON')
            for index, track_id in enumerate(track_ids):
                location = f'/music/historical-{index}.flac'
                run_id = f'historical-run-{index}'
                db.execute('INSERT INTO runs VALUES(?,?,?,?,?)',
                           (run_id, location, 'failed', 'retained failure', '2020-01-01'))
                db.execute('INSERT INTO stages VALUES(?,?,?)', (
                    run_id, 'bpm',
                    '{"stage":"bpm","provenance":[["fixture","historical"]],'
                    '"uncertainty":"retained","values":[["bpm",120.0]]}',
                ))
                if version >= 2:
                    db.execute('INSERT INTO tracks VALUES(?,?,?)',
                               (track_id, ('a', 'b')[index] * 64, 123 + index))
                    db.execute('INSERT INTO locations VALUES(?,?,?,?,?)',
                               (location, track_id, index + 1, 'flac', 1))
                    db.execute('INSERT INTO scan_roots VALUES(?,?)', ('/music', location))
                if version >= 3:
                    db.execute('INSERT INTO batch_jobs VALUES(?,?,?,?,?,?)',
                               (track_id, 'historic-recipe', 'failed', 1, run_id, 'retained job'))
                if version >= 4:
                    db.execute('INSERT INTO run_tracks VALUES(?,?)', (run_id, track_id))
                    db.execute('INSERT INTO overrides VALUES(?,?,?)', (track_id, 'bpm', '120'))
                if version >= 5:
                    db.execute('INSERT INTO track_metadata VALUES(?,?,?,?)',
                               (track_id, '[["title","Historical track"]]', '[]', '[]'))
                if version >= 6:
                    db.execute('INSERT INTO track_audio VALUES(?,?,?,?,?)',
                               (track_id, 180.0, 'mutagen', 'eligible', ''))
            db.commit()
        return track_ids

    def test_real_supported_versions_migrate_without_losing_historical_rows(self):
        for version in range(1, 11):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'historical.sqlite'
                track_ids = self._seed_historical_database(path, version)
                before = logical_snapshot(path)
                self.assertEqual(before[1], (version,))
                with closing(sqlite3.connect(path)) as db:
                    has_catalogue = db.execute(
                        "SELECT 1 FROM sqlite_master WHERE name='tracks' AND type='table'"
                    ).fetchone()
                    self.assertEqual(bool(has_catalogue), version >= 2)
                    if version >= 7:
                        build_columns = tuple(row[1] for row in db.execute('PRAGMA table_info(graph_builds)'))
                        self.assertEqual('source_revision' in build_columns, version == 10)
                        self.assertEqual('attempt_revision' in build_columns, version == 10)

                SQLiteAnalysisRepository(str(path))

                after = logical_snapshot(path)
                self.assertEqual(after[:2], ((APPLICATION_ID,), (10,)))
                migrated_rows = dict(after[3])
                for table, rows in before[3]:
                    self.assertEqual(migrated_rows[table], rows, table)
                if version == 10:
                    self.assertEqual(after, before)
                for reader in READERS:
                    self.assertEqual(reader(str(path)).track_ids(), track_ids if version >= 6 else ())

    def test_both_readers_accept_real_supported_versions_without_migration(self):
        for version in range(6, 11):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'historical.sqlite'
                track_ids = self._seed_historical_database(path, version)
                before = logical_snapshot(path)
                for reader in READERS:
                    with self.subTest(reader=reader.__module__):
                        repository = reader(str(path))
                        self.assertEqual(repository.metadata()['schema_version'], version)
                        self.assertEqual(repository.track_ids(), track_ids)
                        self.assertEqual(logical_snapshot(path), before)
