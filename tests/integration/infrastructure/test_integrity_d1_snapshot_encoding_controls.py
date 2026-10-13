"""Independent compatibility controls; never retrospective missing-behavior RED."""
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from music_analyzer.infrastructure.persistence.integrity import SQLiteIntegrityScanner
from tests.integration.infrastructure.integrity_d1_public_fixture import create_public_core_database
from tests.integration.infrastructure.test_integrity_d1_safety import ConnectObservation, ObservedConnection


class SnapshotConnection(ObservedConnection):
    def __init__(self, connection, write_callback):
        super().__init__(connection)
        self.write_callback = write_callback
        self.writes = 0

    def execute(self, sql, *params):
        if 'pragma_application_id' in sql and not self.writes:
            self.write_callback()
            self.writes += 1
        return self.connection.execute(sql, *params)


class SnapshotObservation(ConnectObservation):
    def __init__(self, path):
        super().__init__()
        self.path = path

    def write_after_pin(self):
        with closing(self.real_connect(self.path)) as writer:
            writer.execute('UPDATE tracks SET size=-1 WHERE sha256=?', ('2' * 64,))
            writer.commit()

    def connect(self, database, **kwargs):
        self.calls.append((database, kwargs))
        db = SnapshotConnection(self.real_connect(database, **kwargs), self.write_after_pin)
        self.connections.append(db)
        return db


def wal_fixture(path):
    create_public_core_database(path, 6)
    with closing(sqlite3.connect(path)) as db:
        if db.execute('PRAGMA journal_mode=WAL').fetchone() != ('wal',):
            raise AssertionError('Required real WAL mode unavailable')


class SnapshotHelperControl(unittest.TestCase):
    def test_real_callback_changes_writer_but_preserves_pinned_reader(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'public.sqlite'
            wal_fixture(path)
            observation = SnapshotObservation(path)
            with patch('sqlite3.connect', observation.connect):
                with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
                    db.execute('BEGIN')
                    self.assertEqual(db.execute('SELECT size FROM tracks WHERE sha256=?', ('2' * 64,)).fetchone(), (102,))
                    self.assertEqual(db.execute('SELECT application_id FROM pragma_application_id').fetchone(), (0x4D414E41,))
                    self.assertEqual(db.writes, 1)
                    self.assertEqual(db.execute('SELECT size FROM tracks WHERE sha256=?', ('2' * 64,)).fetchone(), (102,))
            self.assertEqual(len(observation.calls), 1)
            self.assertIs(observation.calls[0][1]['uri'], True)
            self.assertTrue(db.closed)
            with closing(sqlite3.connect(path)) as verify:
                self.assertEqual(verify.execute('SELECT size FROM tracks WHERE sha256=?', ('2' * 64,)).fetchone(), (-1,))


class IntegrityD1SnapshotEncodingControls(unittest.TestCase):
    def test_scanner_uses_same_real_wal_snapshot_for_schema_and_core(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'public.sqlite'
            wal_fixture(path)
            observation = SnapshotObservation(path)
            with patch('sqlite3.connect', observation.connect):
                result = SQLiteIntegrityScanner().scan(str(path))
            self.assertTrue(result.implemented_scope_complete)
            self.assertFalse(result.findings, 'snapshot predates the independently committed corruption')
            self.assertEqual(observation.connections[0].writes, 1)
            self.assertTrue(observation.connections[0].closed)
            with closing(sqlite3.connect(path)) as verify:
                self.assertEqual(verify.execute('SELECT size FROM tracks WHERE sha256=?', ('2' * 64,)).fetchone(), (-1,))

    def test_true_utf16_schema_and_nul_multibyte_size_preflight(self):
        for encoding in ('UTF-16le', 'UTF-16be'):
            with self.subTest(encoding=encoding), tempfile.TemporaryDirectory() as td:
                path = Path(td) / 'public.sqlite'
                with closing(sqlite3.connect(path)) as db:
                    db.execute(f"PRAGMA encoding='{encoding}'")
                    db.execute('CREATE TABLE encoding_control(x TEXT)')
                    db.execute('DROP TABLE encoding_control')
                    db.commit()
                create_public_core_database(path, 6)
                with closing(sqlite3.connect(path)) as db:
                    self.assertEqual(db.execute('PRAGMA encoding').fetchone(), (encoding,))
                healthy = SQLiteIntegrityScanner().scan(str(path))
                self.assertTrue(healthy.implemented_scope_complete)
                self.assertFalse(healthy.findings)
                with closing(sqlite3.connect(path)) as db:
                    db.execute('UPDATE track_audio SET reason=? WHERE track_id=?', ('\x00' + '界' * 2000, 'sha256:' + '2' * 64))
                    db.commit()
                with patch('music_analyzer.infrastructure.persistence.integrity.MAX_VALUE_BYTES', 4096):
                    limited = SQLiteIntegrityScanner().scan(str(path))
                self.assertEqual(limited.stop_reason, 'value_limit')
                self.assertFalse(limited.implemented_scope_complete)
                self.assertFalse(any(f.severity == 'corruption' for f in limited.findings))

    def test_dedicated_schema_literals_and_fixed_budget_defaults_equal_contract(self):
        from music_analyzer.infrastructure.persistence import integrity, integrity_schema, explorer_readonly
        for name in vars(integrity_schema):
            if name.startswith('_EXPECTED_'):
                self.assertEqual(getattr(integrity_schema, name), getattr(explorer_readonly, name))
        self.assertEqual((integrity.MAX_ROWS, integrity.MAX_UTF8_BYTES, integrity.MAX_VALUE_BYTES, integrity.MAX_GROUPS),
                         (1_000_000, 1 << 30, 32 << 20, 100))
