"""Focused fresh scanner packets using public literal schemas only."""
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from music_analyzer.infrastructure.persistence.integrity import SQLiteIntegrityScanner
from tests.integration.infrastructure.integrity_d1_public_fixture import create_public_core_database


class IntegrityD1Compatibility(unittest.TestCase):
    def test_literal_supported_versions_are_recognized_without_certification(self):
        for version in range(6, 11):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as td:
                path = Path(td) / 'public.sqlite'
                create_public_core_database(path, version)
                result = SQLiteIntegrityScanner().scan(str(path))
                self.assertEqual(result.schema_version, version, 'scanner must recognize true supported schema')
                self.assertTrue(result.supported)
                self.assertTrue(result.implemented_scope_complete)
                self.assertEqual(result.stop_reason, 'scope_not_implemented')

    def test_wrong_application_never_recognizes_legacy_applicability(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'public.sqlite'
            create_public_core_database(path, 6)
            with closing(sqlite3.connect(path)) as db:
                db.execute('PRAGMA application_id=123')
            result = SQLiteIntegrityScanner().scan(str(path))
            self.assertFalse(result.supported, 'wrong app must be unsupported')
            self.assertIsNone(result.schema_version)
            self.assertEqual(result.stop_reason, 'unsupported_database')
            self.assertEqual([f.code for f in result.findings], ['application_id_mismatch'])

    def test_unsupported_literal_versions_do_not_echo_version(self):
        for version in (5, 11):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as td:
                path = Path(td) / 'public.sqlite'
                create_public_core_database(path, 6)
                with closing(sqlite3.connect(path)) as db:
                    db.execute(f'PRAGMA user_version={version}')
                result = SQLiteIntegrityScanner().scan(str(path))
                self.assertFalse(result.supported, 'unsupported literal version must be rejected')
                self.assertIsNone(result.schema_version)
                self.assertEqual(result.stop_reason, 'unsupported_database')
                self.assertEqual([f.code for f in result.findings], ['schema_version_unsupported'])

    def test_initial_unreadable_has_sanitized_result_and_no_raw_exception(self):
        for content in (None, b'PRIVATE PAYLOAD NOT SQLITE'):
            with self.subTest(content=content is None), tempfile.TemporaryDirectory() as td:
                path = Path(td) / 'PRIVATE TARGET.sqlite'
                if content is not None:
                    path.write_bytes(content)
                result = None
                try:
                    result = SQLiteIntegrityScanner().scan(str(path))
                except sqlite3.Error:
                    pass
                self.assertIsNotNone(result, 'initial failure must return sanitized DTO, not escape exception')
                self.assertFalse(result.supported)
                self.assertEqual(result.stop_reason, 'unreadable_database')
                self.assertEqual([f.code for f in result.findings], ['initial_access_failed'])
                self.assertNotIn('PRIVATE', repr(result))
                self.assertFalse(result.implemented_scope_complete)


def remove_track_digest_unique(path):
    """Readable tiny DDL variant; never edit SQLite's catalog directly."""
    with closing(sqlite3.connect(path)) as db:
        sql = db.execute("SELECT sql FROM sqlite_master WHERE name='tracks'").fetchone()[0]
        if 'sha256 TEXT NOT NULL UNIQUE' not in sql:
            raise AssertionError('Expected literal public UNIQUE descriptor')
        rows = tuple(db.execute('SELECT id,sha256,size FROM tracks'))
        if len(rows) != 2:
            raise AssertionError('Expected two public fixture tracks')
        db.execute('DROP TABLE tracks')
        db.execute(sql.replace('sha256 TEXT NOT NULL UNIQUE', 'sha256 TEXT NOT NULL'))
        db.executemany('INSERT INTO tracks VALUES(?,?,?)', rows)
        db.commit()


class IntegrityD1Schema(unittest.TestCase):
    def test_true_supported_schema_completes_schema_check(self):
        for version in range(6, 11):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as td:
                path = Path(td) / 'public.sqlite'
                create_public_core_database(path, version)
                result = SQLiteIntegrityScanner().scan(str(path))
                schema = next((check for check in result.checks if check.check_id == 'schema'), None)
                self.assertIsNotNone(schema, 'scanner must report schema coverage')
                self.assertEqual(schema.state, 'completed')
                self.assertEqual(schema.count_precision, 'exact')
                self.assertGreater(schema.count, 0)
                self.assertFalse(any(f.check_id == 'schema' for f in result.findings))

    def test_full_v6_rejects_unexpected_objects_and_missing_objects_block_core(self):
        for sql in ('CREATE TABLE private_extra(secret TEXT)', 'DROP TABLE track_metadata'):
            with self.subTest(sql=sql.split()[0]), tempfile.TemporaryDirectory() as td:
                path = Path(td) / 'public.sqlite'
                create_public_core_database(path, 6)
                with closing(sqlite3.connect(path)) as db:
                    db.execute(sql)
                result = SQLiteIntegrityScanner().scan(str(path))
                self.assertIn('schema_object_set_mismatch', [f.code for f in result.findings],
                              'exact FULL object set must be checked')
                self.assertEqual(result.stop_reason, 'schema_blocked')
                self.assertFalse(result.implemented_scope_complete)
                core = next((c for c in result.checks if c.check_id == 'core_rows'), None)
                self.assertIsNotNone(core)
                self.assertEqual(core.state, 'blocked')

    def test_full_schema_descriptor_predicates_reject_drift(self):
        cases = (
            ('active_tracks', 'SELECT t.id,t.sha256,t.size', 'SELECT t.id,t.sha256,t.size+0', 'schema_view_mismatch'),
            ('tracks', 'size INTEGER', 'size TEXT', 'schema_columns_mismatch'),
            ('locations', 'REFERENCES tracks(id)', 'REFERENCES runs(id)', 'schema_foreign_keys_mismatch'),
            ('tracks', 'sha256 TEXT NOT NULL UNIQUE', 'sha256 TEXT NOT NULL', 'schema_unique_indexes_mismatch'),
            ('locations', 'CHECK(available IN (0,1))', 'CHECK(available IN (0,1,2))', 'schema_checks_mismatch'),
        )
        for name, old, new, code in cases:
            with self.subTest(code=code), tempfile.TemporaryDirectory() as td:
                path = Path(td) / 'public.sqlite'
                create_public_core_database(path, 6)
                if code == 'schema_unique_indexes_mismatch':
                    remove_track_digest_unique(path)
                else:
                    with closing(sqlite3.connect(path)) as db:
                        sql = db.execute('SELECT sql FROM sqlite_master WHERE name=?', (name,)).fetchone()[0]
                        self.assertIn(old, sql, 'literal fixture prerequisite')
                        db.execute('PRAGMA writable_schema=ON')
                        db.execute('UPDATE sqlite_master SET sql=? WHERE name=?', (sql.replace(old, new), name))
                        db.commit()
                result = SQLiteIntegrityScanner().scan(str(path))
                self.assertTrue(result.supported, 'drift fixture must retain supported recognition')
                self.assertEqual(result.schema_version, 6)
                self.assertNotIn('initial_access_failed', [f.code for f in result.findings])
                self.assertIn(code, [f.code for f in result.findings], 'FULL predicate drift must be found')
                self.assertEqual(result.stop_reason, 'schema_blocked')

    def test_full_legacy_tolerances_complete_schema_without_hardening(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'public.sqlite'
            create_public_core_database(path, 6)
            with closing(sqlite3.connect(path)) as db:
                db.execute('DROP TABLE stages')
                db.execute('DROP TABLE runs')
                db.execute('CREATE TABLE runs(id TEXT PRIMARY KEY,location TEXT,status TEXT,detail TEXT,created_at TEXT)')
                db.execute('CREATE TABLE stages(run_id TEXT,stage TEXT,result TEXT,PRIMARY KEY(run_id,stage))')
                db.execute('CREATE TRIGGER ignored_trigger AFTER INSERT ON runs BEGIN SELECT 1; END')
            result = SQLiteIntegrityScanner().scan(str(path))
            schema = next((c for c in result.checks if c.check_id == 'schema'), None)
            self.assertIsNotNone(schema, 'scanner must cover legacy descriptor alternatives')
            self.assertEqual(schema.state, 'completed')
            self.assertFalse(any(f.check_id == 'schema' for f in result.findings))


class IntegrityD1SchemaFixtureControls(unittest.TestCase):
    def test_legitimate_unique_drift_is_readable_and_full_rejects_exact_predicate(self):
        from music_analyzer.infrastructure.persistence.explorer_readonly import ReadOnlyExplorerSQLiteRepository
        from music_analyzer.application.dto.analysis import AnalysisError

        class ObservedFullReader(ReadOnlyExplorerSQLiteRepository):
            unique_checks = []

            def _unique_indexes(self, db, table):
                columns = super()._unique_indexes(db, table)
                self.unique_checks.append((table, columns))
                return columns

        def descriptors(path):
            with closing(sqlite3.connect(path)) as db:
                objects = tuple(db.execute("SELECT name,type,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY name"))
                tables = [name for name, kind, sql in objects if kind == 'table']
                return (
                    db.execute('PRAGMA application_id').fetchone(),
                    db.execute('PRAGMA user_version').fetchone(),
                    objects,
                    tuple((name, tuple(db.execute(f'PRAGMA table_info({name})')),
                           tuple(db.execute(f'PRAGMA foreign_key_list({name})')))
                          for name in tables),
                )

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'public.sqlite'
            create_public_core_database(path, 6)
            before = descriptors(path)
            remove_track_digest_unique(path)
            after = descriptors(path)
            self.assertEqual(before[:2], after[:2])
            self.assertEqual(before[3], after[3], 'columns/FK descriptors unchanged for every table')
            expected_objects = tuple((name, kind, sql.replace('sha256 TEXT NOT NULL UNIQUE', 'sha256 TEXT NOT NULL')
                                      if name == 'tracks' else sql) for name, kind, sql in before[2])
            self.assertEqual(expected_objects, after[2], 'all view/other table SQL unchanged')
            with closing(sqlite3.connect(path)) as db:
                physical = db.execute('PRAGMA integrity_check(101)')
                self.assertEqual(tuple(physical), (('ok',),))
                self.assertIsNone(physical.fetchone())
                foreign = db.execute('PRAGMA foreign_key_check')
                self.assertEqual(tuple(foreign), ())
                self.assertIsNone(foreign.fetchone())
            reader = ObservedFullReader(str(path))
            with self.assertRaises(AnalysisError) as failure:
                reader.metadata()
            self.assertEqual(str(failure.exception), 'Unexpected analysis database schema')
            self.assertEqual(reader.unique_checks[-1], ('tracks', ()))
            self.assertEqual([table for table, indexes in reader.unique_checks], ['runs', 'stages', 'tracks'])


class IntegrityD1Core(unittest.TestCase):
    def test_all_public_track_and_audio_rows_complete(self):
        for version in range(6, 11):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as td:
                path = Path(td) / 'public.sqlite'
                create_public_core_database(path, version)
                result = SQLiteIntegrityScanner().scan(str(path))
                core = next((c for c in result.checks if c.check_id == 'core_rows'), None)
                self.assertIsNotNone(core)
                self.assertEqual(core.state, 'completed', 'scanner must drain all core inputs')
                self.assertEqual(core.count, 4)
                self.assertEqual(core.count_precision, 'exact')
                self.assertFalse(any(f.check_id == 'core_rows' for f in result.findings))

    def test_late_core_predicates_emit_owning_code_and_drain(self):
        cases = (
            ("UPDATE tracks SET id='invalid' WHERE sha256=?", 'track_identity_invalid'),
            ("UPDATE tracks SET sha256='ABC' WHERE sha256=?", 'track_digest_invalid'),
            ('UPDATE tracks SET size=-1 WHERE sha256=?', 'track_size_invalid'),
            ('DELETE FROM track_audio WHERE track_id=?', 'track_audio_missing'),
            ("UPDATE track_audio SET track_id='sha256:'||? WHERE track_id NOT LIKE '%1'", 'track_audio_orphan'),
            ('UPDATE track_audio SET duration_seconds=1e999 WHERE track_id=?', 'track_audio_duration_invalid'),
            ("UPDATE track_audio SET reason='wrong' WHERE track_id=?", 'track_audio_policy_invalid'),
        )
        for sql, code in cases:
            with self.subTest(code=code), tempfile.TemporaryDirectory() as td:
                path = Path(td) / 'public.sqlite'
                create_public_core_database(path, 10)
                value = '2' * 64 if 'WHERE sha256' in sql else 'sha256:' + '2' * 64
                if code == 'track_audio_orphan':
                    value = '3' * 64
                with closing(sqlite3.connect(path)) as db:
                    changed = db.execute(sql, (value,)).rowcount
                    self.assertEqual(changed, 1, 'exactly the second public row must change')
                    db.commit()
                result = SQLiteIntegrityScanner().scan(str(path))
                self.assertEqual(result.schema_version, 10)
                self.assertFalse(any(f.check_id == 'schema' for f in result.findings))
                self.assertIn(code, [f.code for f in result.findings], 'late core predicate must be scanned')
                own = next(f for f in result.findings if f.code == code)
                self.assertEqual(own.count, 1)
                self.assertEqual(own.count_precision, 'exact')
                self.assertEqual(result.stop_reason, 'scope_not_implemented')

    def test_embedded_nul_text_is_safely_preflighted_before_core_allocation(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'public.sqlite'
            create_public_core_database(path, 10)
            with closing(sqlite3.connect(path)) as db:
                db.execute('UPDATE track_audio SET reason=? WHERE track_id=?',
                           ('\x00' + '界' * 2000, 'sha256:' + '2' * 64))
                db.commit()
            with patch('music_analyzer.infrastructure.persistence.integrity.MAX_VALUE_BYTES', 4096):
                result = SQLiteIntegrityScanner().scan(str(path))
            self.assertEqual(result.stop_reason, 'value_limit', 'embedded NUL must not defeat UTF8 byte admission')
            self.assertFalse(result.implemented_scope_complete)


class IntegrityD1DescriptorDrain(unittest.TestCase):
    def test_excess_columns_are_drained_before_exact_schema_count(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'public.sqlite'
            create_public_core_database(path, 6)
            with closing(sqlite3.connect(path)) as db:
                for index in range(3):
                    db.execute(f'ALTER TABLE tracks ADD COLUMN extra{index} TEXT')
                objects = tuple(db.execute("SELECT name,type FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' AND type IN ('table','view','index')"))
                expected = len(objects)
                for name, kind in objects:
                    if kind not in ('table', 'view'):
                        continue
                    expected += len(tuple(db.execute('SELECT * FROM pragma_table_info(?)', (name,))))
                    if kind == 'table':
                        expected += len(tuple(db.execute('SELECT * FROM pragma_foreign_key_list(?)', (name,))))
                        indexes = tuple(db.execute('SELECT * FROM pragma_index_list(?)', (name,)))
                        expected += len(indexes)
                        for _, index_name, unique, origin, partial in indexes:
                            if unique and origin == 'u':
                                expected += len(tuple(db.execute('SELECT * FROM pragma_index_info(?)', (index_name,))))
                self.assertEqual(tuple(db.execute('PRAGMA integrity_check(101)')), (('ok',),))
                self.assertEqual(tuple(db.execute('PRAGMA foreign_key_check')), ())
            result = SQLiteIntegrityScanner().scan(str(path))
            self.assertEqual(result.stop_reason, 'schema_blocked')
            self.assertIn('schema_columns_mismatch', [f.code for f in result.findings])
            schema = next(c for c in result.checks if c.check_id == 'schema')
            self.assertEqual(schema.count, expected, 'exact schema count must include all excess delivered descriptors')
