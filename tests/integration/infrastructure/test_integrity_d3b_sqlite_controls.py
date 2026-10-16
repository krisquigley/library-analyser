"""Positive admission/instrumentation controls only: NOT D3b RED.

Literal diagnostic text stays in these tiny public fixture controls only. The
production proposal admits numeric markers, not raw SQLite diagnostic text.
Synthetic streams qualify transparent instrumentation, never disk corruption.
"""
from contextlib import closing
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

from tests.integration.infrastructure.integrity_d1_public_fixture import (
    create_public_core_database,
)

PHYSICAL_LITERAL = 'PRAGMA integrity_check'
PHYSICAL_MARKER = ("SELECT CASE WHEN integrity_check='ok' THEN 1 ELSE 0 END "
                   'AS marker FROM pragma_integrity_check')
FK_LITERAL = 'PRAGMA foreign_key_check'
FK_MARKER = 'SELECT 1 AS marker FROM pragma_foreign_key_check'


def drain(db, sql):
    with closing(db.execute(sql)) as cursor:
        return list(cursor)


def read_snapshot(path):
    db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    db.execute('PRAGMA query_only=ON')
    db.execute('BEGIN')
    # Materialize a real read to pin the snapshot before either comparison.
    drain(db, 'SELECT name FROM sqlite_schema')
    return db


class ObservedCursor:
    def __init__(self, rows, owner):
        self.rows = iter(rows)
        self.owner = owner
        self.real = rows if hasattr(rows, 'close') else None

    def __iter__(self):
        return self

    def __next__(self):
        try:
            row = next(self.rows)
        except StopIteration:
            self.owner.eof += 1
            raise
        self.owner.delivered += 1
        return row

    def close(self):
        if self.real is not None:
            self.real.close()
        self.owner.closed += 1


class DiagnosticProxy:
    """Exact SQL targeting, with explicit already-projected injected rows.

    Malformed markers must NOT be normalized by an injector. Valid real target
    SQL executes first; only its stream is replaced. All other SQL delegates.
    """
    def __init__(self, db, literal_rows=None, marker_rows=None):
        self.db = db
        self.literal_rows = literal_rows
        self.marker_rows = marker_rows
        self.targets = self.non_targets = 0
        self.eof = self.closed = self.delivered = 0

    def execute(self, sql):
        if sql not in (PHYSICAL_LITERAL, PHYSICAL_MARKER):
            self.non_targets += 1
            return ObservedCursor(self.db.execute(sql), self)
        self.targets += 1
        rows = self.literal_rows if sql == PHYSICAL_LITERAL else self.marker_rows
        if rows is None:
            return ObservedCursor(self.db.execute(sql), self)
        with closing(self.db.execute(sql)) as real:
            list(real)
        return ObservedCursor(rows, self)


class SQLiteAdmissionControls(unittest.TestCase):
    assertions = 0

    def assertEqual(self, first, second, msg=None):
        type(self).assertions += 1
        return super().assertEqual(first, second, msg)

    def assertLess(self, first, second, msg=None):
        type(self).assertions += 1
        return super().assertLess(first, second, msg)

    @classmethod
    def tearDownClass(cls):
        print(f'POSITIVE CONTROL ASSERTIONS={cls.assertions}; NOT RED')
        print(f'RUNTIME python={sys.version.split()[0]} sqlite={sqlite3.sqlite_version}')

    def test_genuine_public_versions_6_through_10_same_readonly_snapshot(self):
        for version in range(6, 11):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / 'public.sqlite'
                create_public_core_database(path, version)
                self.assertLess(path.stat().st_size, 512 * 1024 * 1024)
                self.assertLess(sum(p.stat().st_size for p in Path(tmp).iterdir()),
                                1024 * 1024 * 1024)
                with closing(read_snapshot(path)) as db:
                    self.assertEqual(drain(db, 'PRAGMA user_version'), [(version,)])
                    self.assertEqual(drain(db, 'PRAGMA query_only'), [(1,)])
                    self.assertEqual(drain(db, PHYSICAL_LITERAL), [('ok',)])
                    self.assertEqual(drain(db, PHYSICAL_MARKER), [(1,)])
                    self.assertEqual(drain(db, FK_LITERAL), [])
                    self.assertEqual(drain(db, FK_MARKER), [])

    def test_public_deliberate_orphan_one_violation_same_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'orphan.sqlite'
            create_public_core_database(path)
            with closing(sqlite3.connect(path)) as writer:
                writer.execute('PRAGMA foreign_keys=OFF')
                writer.execute('INSERT INTO track_audio VALUES(?,?,?,?,?)',
                               ('sha256:' + '9' * 64, 1.0, 'mutagen', 'eligible', ''))
                writer.commit()
            with closing(read_snapshot(path)) as db:
                literal = drain(db, FK_LITERAL)
                self.assertEqual(len(literal), 1)
                self.assertEqual(literal[0][0], 'track_audio')
                self.assertEqual(drain(db, FK_MARKER), [(1,)])
                self.assertEqual(drain(db, PHYSICAL_LITERAL), [('ok',)])
                self.assertEqual(drain(db, PHYSICAL_MARKER), [(1,)])

    def test_without_rowid_null_rowid_multiple_constraints_full_multiplicity(self):
        with closing(sqlite3.connect(':memory:')) as db:
            db.executescript('CREATE TABLE p(id TEXT PRIMARY KEY); '
                             'CREATE TABLE q(id TEXT PRIMARY KEY); '
                             'CREATE TABLE c(id TEXT PRIMARY KEY, '
                             'p_id TEXT REFERENCES p(id), '
                             'q_id TEXT REFERENCES q(id)) WITHOUT ROWID; '
                             "INSERT INTO c VALUES('one','missing','missing'); "
                             "INSERT INTO c VALUES('two','missing','missing');")
            db.execute('PRAGMA query_only=ON')
            db.execute('BEGIN')
            literal = drain(db, FK_LITERAL)
            self.assertEqual(len(literal), 4)
            self.assertEqual([row[1] for row in literal], [None] * 4)
            self.assertEqual(sorted((row[0], row[2], row[3]) for row in literal),
                             [('c', 'p', 1)] * 2 + [('c', 'q', 0)] * 2)
            self.assertEqual(drain(db, FK_MARKER), [(1,)] * 4)
            self.assertEqual(drain(db, PHYSICAL_LITERAL), [('ok',)])
            self.assertEqual(drain(db, PHYSICAL_MARKER), [(1,)])

    def test_transparent_healthy_target_non_target_eof_cleanup(self):
        with closing(sqlite3.connect(':memory:')) as db:
            db.execute('BEGIN')
            proxy = DiagnosticProxy(db)
            self.assertEqual(drain(proxy, 'SELECT 7'), [(7,)])
            self.assertEqual(drain(proxy, PHYSICAL_LITERAL), [('ok',)])
            self.assertEqual(drain(proxy, PHYSICAL_MARKER), [(1,)])
            self.assertEqual(drain(proxy, FK_LITERAL), [])
            self.assertEqual(drain(proxy, FK_MARKER), [])
            self.assertEqual((proxy.targets, proxy.non_targets, proxy.eof,
                              proxy.closed, proxy.delivered), (2, 3, 5, 5, 3))

    def test_synthetic_physical_1_99_100_multiplicity_not_disk_corruption(self):
        for count in (1, 99, 100):
            with self.subTest(count=count), closing(sqlite3.connect(':memory:')) as db:
                proxy = DiagnosticProxy(db, [('synthetic diagnostic',)] * count,
                                        [(0,)] * count)
                self.assertEqual(drain(proxy, 'SELECT 7'), [(7,)])
                self.assertEqual(drain(proxy, PHYSICAL_LITERAL),
                                 [('synthetic diagnostic',)] * count)
                self.assertEqual(drain(proxy, PHYSICAL_MARKER), [(0,)] * count)
                self.assertEqual((proxy.targets, proxy.non_targets, proxy.eof,
                                  proxy.closed, proxy.delivered),
                                 (2, 1, 3, 3, 2 * count + 1))

    def test_synthetic_malformed_marker_streams_preserved_not_normalized(self):
        cases = {'empty': [], 'mixed': [(1,), (0,)],
                 'multiok': [(1,), (1,)], 'string': [('0',)],
                 'float': [(0.0,)], 'bool': [(False,)], 'null': [(None,)],
                 'unexpected_value': [(2,)], 'shape': [(0, 0)]}
        for name, rows in cases.items():
            with self.subTest(protocol=name), closing(sqlite3.connect(':memory:')) as db:
                proxy = DiagnosticProxy(db, marker_rows=rows)
                observed = drain(proxy, PHYSICAL_MARKER)
                self.assertEqual(observed, rows)
                self.assertEqual([tuple(type(value) for value in row) for row in observed],
                                 [tuple(type(value) for value in row) for row in rows])
                self.assertEqual(drain(proxy, 'SELECT 7'), [(7,)])
                self.assertEqual((proxy.targets, proxy.non_targets, proxy.eof,
                                  proxy.closed, proxy.delivered),
                                 (1, 1, 2, 2, len(rows) + 1))


if __name__ == '__main__':
    unittest.main()
