"""Small fresh operational packet: real SQLite connect interception and access."""
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from music_analyzer.infrastructure.persistence.integrity import SQLiteIntegrityScanner
from tests.integration.infrastructure.integrity_d1_public_fixture import create_public_core_database


class ObservedConnection:
    def __init__(self, connection):
        self.connection = connection
        self.sql = []
        self.closed = False
        connection.set_trace_callback(self.sql.append)

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def close(self):
        self.closed = True
        return self.connection.close()


class ConnectObservation:
    def __init__(self):
        self.real_connect = sqlite3.connect
        self.calls = []
        self.connections = []

    def connect(self, database, **kwargs):
        self.calls.append((database, kwargs))
        connection = ObservedConnection(self.real_connect(database, **kwargs))
        self.connections.append(connection)
        return connection


class IntegrityD1AccessSafety(unittest.TestCase):
    def test_real_connect_spy_self_control_distinguishes_database_from_uri_flag(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'public #?.sqlite'
            create_public_core_database(path, 6)
            observation = ConnectObservation()
            with patch('sqlite3.connect', observation.connect):
                with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
                    self.assertEqual(db.execute('PRAGMA user_version').fetchone(), (6,))
            self.assertEqual(len(observation.calls), 1)
            database, kwargs = observation.calls[0]
            self.assertIsInstance(database, str)
            self.assertEqual(kwargs['uri'], True)
            self.assertIn('%23%3F', database)
            self.assertEqual(parse_qs(urlsplit(database).query), {'mode': ['ro']})
            self.assertTrue(observation.connections[0].closed)

    def test_scanner_opens_only_escaped_read_only_uri_and_closes_it(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'public #?.sqlite'
            create_public_core_database(path, 6)
            before = path.read_bytes()
            observation = ConnectObservation()
            with patch('sqlite3.connect', observation.connect):
                result = SQLiteIntegrityScanner().scan(str(path))
            self.assertTrue(result.implemented_scope_complete)
            self.assertEqual(result.stop_reason, 'scope_not_implemented')
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(len(observation.calls), 1, 'scanner must open its explicit read-only target')
            database, kwargs = observation.calls[0]
            self.assertIsInstance(database, str)
            self.assertTrue(kwargs['uri'])
            self.assertIn('%23%3F', database)
            self.assertEqual(parse_qs(urlsplit(database).query), {'mode': ['ro']})
            self.assertTrue(observation.connections[0].closed)

    def test_scanner_enables_query_only_and_pins_explicit_transaction_before_reads(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'public.sqlite'
            create_public_core_database(path, 6)
            observation = ConnectObservation()
            with patch('sqlite3.connect', observation.connect):
                SQLiteIntegrityScanner().scan(str(path))
            statements = [sql.upper().strip() for db in observation.connections for sql in db.sql]
            self.assertIn('BEGIN', statements, 'scanner must pin one explicit snapshot')
            self.assertIn('PRAGMA QUERY_ONLY=ON', statements)
            self.assertLess(statements.index('PRAGMA QUERY_ONLY=ON'), statements.index('BEGIN'))
            self.assertTrue(any(sql.startswith('SELECT') for sql in statements[statements.index('BEGIN') + 1:]))
            self.assertFalse(any(sql.startswith(prefix) for sql in statements for prefix in
                                 ('INSERT', 'UPDATE', 'DELETE', 'CREATE', 'ALTER', 'DROP', 'ATTACH', 'VACUUM')))
            self.assertFalse(any('CHECKPOINT' in sql for sql in statements))


class IntegrityD1Admission(unittest.TestCase):
    def test_schema_sql_value_limit_is_incomplete_before_full_sql_delivery(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'public.sqlite'
            create_public_core_database(path, 6)
            observation = ConnectObservation()
            with patch('sqlite3.connect', observation.connect), patch(
                    'music_analyzer.infrastructure.persistence.integrity.MAX_VALUE_BYTES', 128, create=True):
                result = SQLiteIntegrityScanner().scan(str(path))
            self.assertEqual(result.stop_reason, 'value_limit', 'schema SQL needs preallocation byte admission')
            self.assertFalse(result.implemented_scope_complete)
            self.assertIn('value_limit_reached', [f.code for f in result.findings])
            self.assertTrue(all(db.closed for db in observation.connections))
            sql = [statement.upper() for db in observation.connections for statement in db.sql]
            self.assertFalse(any(statement.startswith('SELECT SQL FROM SQLITE_MASTER') for statement in sql))

    def test_all_delivered_rows_apply_to_row_limit_including_schema(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'public.sqlite'
            create_public_core_database(path, 6)
            with patch('music_analyzer.infrastructure.persistence.integrity.MAX_ROWS', 8, create=True):
                result = SQLiteIntegrityScanner().scan(str(path))
            self.assertEqual(result.stop_reason, 'row_limit', 'scalar/schema delivery needs global row admission')
            self.assertIn('row_limit_reached', [f.code for f in result.findings])
            self.assertFalse(result.implemented_scope_complete)

    def test_cumulative_utf8_admission_stops_incomplete(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'public.sqlite'
            create_public_core_database(path, 6)
            with patch('music_analyzer.infrastructure.persistence.integrity.MAX_UTF8_BYTES', 128, create=True):
                result = SQLiteIntegrityScanner().scan(str(path))
            self.assertEqual(result.stop_reason, 'utf8_limit', 'schema text delivery needs cumulative admission')
            self.assertIn('utf8_limit_reached', [f.code for f in result.findings])
            self.assertFalse(result.implemented_scope_complete)
