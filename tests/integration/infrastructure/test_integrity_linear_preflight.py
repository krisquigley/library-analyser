"""Exact decoded-size preflight must be linear in the stored value size.

Fixed 4096-byte storage fragments are read incrementally from the pinned
snapshot. Slicing with SQL (substr(CAST(value AS BLOB), ...)) makes SQLite load
the whole stored value for every fragment, so a 36 MiB value cost ~9,000 full
reloads and exceeded the audit deadline on slower hardware. These tests run the
real scanner with a short deadline that only a linear preflight can meet; they
assert the same admission outcome as the unbounded empirical qualification.

One database (<80 MiB) and one connection per test; run serially.
"""
from contextlib import closing
import re
import sqlite3
import tempfile
import unittest
from pathlib import Path
from time import monotonic

from music_analyzer.application.use_cases.integrity_evidence import EvidenceCode
from music_analyzer.infrastructure.persistence import integrity_evidence as evidence_adapter
from music_analyzer.infrastructure.persistence.integrity import Delivery, SQLiteIntegrityScanner
from tests.integration.infrastructure.integrity_d2_evidence_public_fixture import OLD_RUNS, store_payload
import json

from tests.integration.infrastructure.integrity_d3_public_fixture import create_public_retained_database, replace_stage, stage_payload
from tests.integration.infrastructure.test_integrity_d2_evidence_admission import create_encoded, selected, sized_payload

# Far above a linear preflight (well under a second locally), far below the
# quadratic SQL-slicing cost of these fixtures (~47 s locally, ~180 s on CI).
SHORT_DEADLINE_SECONDS = 15


class LinearDecodedSizePreflightTests(unittest.TestCase):
    def database(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        return Path(temporary.name) / 'public.sqlite'

    def test_large_blob_evidence_preflight_meets_short_deadline(self):
        path = self.database()
        ids = create_encoded(path, 'UTF-8', 10)
        value, text = sized_payload(ids[0], OLD_RUNS[0], 9 << 20)
        raw = text.encode('utf-32')
        self.assertGreater(len(raw), 32 << 20)
        store_payload(path, OLD_RUNS[0], value, text=raw)

        scan = SQLiteIntegrityScanner().scan(str(path), SHORT_DEADLINE_SECONDS)

        self.assertEqual(scan.stop_reason, 'value_limit')
        self.assertEqual(selected(scan, 'historical_evidence').state, 'interrupted')

    def test_large_blob_retained_stage_preflight_meets_short_deadline(self):
        path = self.database()
        create_public_retained_database(path)
        document = stage_payload()
        document['padding'] = 'x' * (9 << 20)  # 9 MiB decoded: inside the 16 MiB stage domain
        raw = json.dumps(document).encode('utf-32')
        self.assertGreater(len(raw), 32 << 20)
        replace_stage(path, raw, raw=True)

        scan = SQLiteIntegrityScanner().scan(str(path), SHORT_DEADLINE_SECONDS)

        self.assertNotEqual(scan.stop_reason, 'deadline')
        self.assertEqual(scan.stop_reason, 'value_limit')



def rebuild_table(path, table, variant):
    """Accepted-by-schema table shapes that incremental BLOB I/O cannot open."""
    with closing(sqlite3.connect(path)) as db:
        sql, = db.execute("SELECT sql FROM sqlite_master WHERE name=?", (table,)).fetchone()
        indexes = [row[0] for row in db.execute(
            "SELECT sql FROM sqlite_master WHERE tbl_name=? AND type='index' AND sql IS NOT NULL", (table,))]
        columns = ','.join(row[1] for row in db.execute(f'PRAGMA table_info({table})'))
        new = sql.replace(table, 'rebuilt', 1)
        if variant == 'without_rowid':
            new += ' WITHOUT ROWID'
        else:
            match = re.search(r',\s*(PRIMARY KEY|UNIQUE|FOREIGN KEY|CHECK)', new)
            cut = match.start() if match else new.rfind(')')
            new = new[:cut] + ', gen_x AS (1) VIRTUAL' + new[cut:]
        db.execute('PRAGMA foreign_keys=OFF')
        db.execute('PRAGMA legacy_alter_table=ON')
        db.execute(new)
        db.execute(f'INSERT INTO rebuilt({columns}) SELECT {columns} FROM {table}')
        db.execute(f'DROP TABLE {table}')
        db.execute(f'ALTER TABLE rebuilt RENAME TO {table}')
        for index in indexes:
            db.execute(index)
        db.commit()


class PreflightTableShapeFallbackTests(unittest.TestCase):
    """Shapes the schema gate accepts must audit exactly as before."""

    def database(self, encoding, blob):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / 'public.sqlite'
        create_encoded(path, encoding, 10)
        if blob:
            with closing(sqlite3.connect(path)) as db:
                db.execute('UPDATE graph_feature_evidence SET evidence_json=CAST(evidence_json AS BLOB)')
                db.commit()
        return path

    def outcome(self, path):
        scan = SQLiteIntegrityScanner().scan(str(path))
        return scan.stop_reason, [(f.check_id, f.code) for f in scan.findings]

    def test_evidence_table_shapes_without_blob_io_still_complete(self):
        for variant in ('without_rowid', 'generated'):
            for encoding, blob in (('UTF-8', True), ('UTF-16le', False)):
                with self.subTest(variant=variant, encoding=encoding, blob=blob):
                    path = self.database(encoding, blob)
                    expected = self.outcome(path)
                    self.assertEqual(expected, ('completed', []))
                    rebuild_table(path, 'graph_feature_evidence', variant)
                    self.assertEqual(self.outcome(path), expected)

    def test_retained_metadata_with_generated_column_still_completes(self):
        path = self.database('UTF-16le', False)
        expected = self.outcome(path)
        rebuild_table(path, 'track_metadata', 'generated')
        self.assertEqual(self.outcome(path), expected)

    def test_null_evidence_value_remains_delivery_invalid(self):
        track, run = 'sha256:' + 'a' * 64, OLD_RUNS[0]
        with closing(sqlite3.connect(':memory:')) as db:
            db.execute('CREATE TABLE graph_feature_evidence (track_id TEXT, run_id TEXT, evidence_json BLOB)')
            db.execute('INSERT INTO graph_feature_evidence VALUES (?,?,NULL)', (track, run))
            delivery = Delivery(db, deadline=monotonic() + 60)
            result = evidence_adapter._document_size(delivery, track, run, 10, 'blob')
        self.assertEqual(result, (None, EvidenceCode.DELIVERY_INVALID))
        self.assertIsNone(delivery.first_error)


if __name__ == '__main__':
    unittest.main()
