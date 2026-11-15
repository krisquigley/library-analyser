"""Exact decoded-size preflight must be linear in the stored value size.

Fixed 4096-byte storage fragments are read incrementally from the pinned
snapshot. Slicing with SQL (substr(CAST(value AS BLOB), ...)) makes SQLite load
the whole stored value for every fragment, so a 36 MiB value cost ~9,000 full
reloads and exceeded the audit deadline on slower hardware. These tests run the
real scanner with a short deadline that only a linear preflight can meet; they
assert the same admission outcome as the unbounded empirical qualification.

One database (<80 MiB) and one connection per test; run serially.
"""
import tempfile
import unittest
from pathlib import Path

from music_analyzer.infrastructure.persistence.integrity import SQLiteIntegrityScanner
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


if __name__ == '__main__':
    unittest.main()
