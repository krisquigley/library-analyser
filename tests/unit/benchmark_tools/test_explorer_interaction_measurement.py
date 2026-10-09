"""PR4 red contract: bounded diagnosis/report primitives, NOT a timing harness.

Future public seam: tools.explorer_interaction_measurement. Only the absent
module uses the explicit test-local empty-result stub. It makes discovery and
compilation succeed while every new contract fails a behavioral assertion;
errors inside an implemented module must still propagate. No production stub.

No HTTP/browser runs, private input, large payload or speed thresholds here.
The tiny writer-owned v10 DB is not the proposed rich 5k/20k generator. The
small indexed payload is browser-only and proves no SQLite/server latency.
File fingerprints cover this test-owned quiescent lifecycle; sequential main/
WAL hashes are not an atomic live snapshot or proof against checkpoint races.
"""
from contextlib import closing
import hashlib
import importlib
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest

from music_analyzer.infrastructure.persistence.analysis import SQLiteAnalysisRepository
from tests.support.graph_evidence_backfill_fixture import (
    complete_graph_relevant_run, register_track,
)
from music_explorer.interface_adapters.mood_axis_graph_http import INDEXED_DTO_VERSION
from tools.graph_read_benchmark import measure_samples, nearest_rank


def _unimplemented_contract(*args, **kwargs):
    """Benign RED seam: no observations, measurements or fixture fabrication."""
    return {}


try:
    measurement = importlib.import_module('tools.explorer_interaction_measurement')
except ModuleNotFoundError as error:
    if error.name != 'tools.explorer_interaction_measurement':
        raise
    measurement = SimpleNamespace(**dict.fromkeys((
        'summarize_interactions', 'validate_phase_intervals', 'request_inventory',
        'graph_manifest', 'inspect_fixture', 'fingerprint_sqlite_files',
    ), _unimplemented_contract))


class ExplorerInteractionMeasurementContractTests(unittest.TestCase):
    def test_nearest_rank_oracle_is_observed_not_interpolated(self):
        self.assertEqual(nearest_rank([40, 10, 20, 30], 50), 20)
        self.assertEqual(nearest_rank(range(1, 21), 95), 19)
        self.assertEqual(nearest_rank(range(100), 7), 6)

    def test_summary_retains_failures_and_separates_process_cold_from_warm(self):
        attempts = [
            {'sample': 0, 'profile': 'process-cold', 'outcome': 'ok', 'elapsed_ms': 100},
            *({'sample': i, 'profile': 'warm', 'outcome': 'ok', 'elapsed_ms': i * 10}
              for i in range(1, 21)),
            {'sample': 21, 'profile': 'warm', 'outcome': 'timeout', 'elapsed_ms': None},
            {'sample': 22, 'profile': 'warm', 'outcome': 'oom', 'elapsed_ms': None},
            {'sample': 23, 'profile': 'warm', 'outcome': 'http_error', 'elapsed_ms': 900},
        ]
        report = measurement.summarize_interactions(attempts)
        self.assertEqual(report.get('attempted'), 24, 'all attempts, including failures, must survive')
        self.assertEqual(report['samples'], attempts)
        self.assertEqual(report['profiles']['process-cold'], {
            'attempted': 1, 'succeeded': 1, 'failures': {},
            'p50_ms': 100, 'p95_ms': 100, 'max_ms': 100,
        })
        self.assertEqual(report['profiles']['warm'], {
            'attempted': 23, 'succeeded': 20,
            'failures': {'timeout': 1, 'oom': 1, 'http_error': 1},
            'p50_ms': 100, 'p95_ms': 190, 'max_ms': 200,
        })
        failed = measurement.summarize_interactions([
            {'sample': 0, 'profile': 'warm', 'outcome': 'timeout', 'elapsed_ms': None},
        ])
        self.assertIsNone(failed['profiles']['warm']['p95_ms'], 'no invented zero on total failure')

    def test_phase_order_is_checked_per_clock_not_across_browser_and_server(self):
        # Server and browser clocks have independent origins. Concurrent graph
        # activity is not required to finish before a selected detail request.
        intervals = [
            {'clock': 'browser', 'flow': 'detail', 'phase': 'request', 'start_ms': 100, 'end_ms': 110},
            {'clock': 'browser', 'flow': 'detail', 'phase': 'json', 'start_ms': 110, 'end_ms': 112},
            {'clock': 'browser', 'flow': 'detail', 'phase': 'paint', 'start_ms': 113, 'end_ms': 114},
            {'clock': 'server', 'flow': 'detail', 'phase': 'validation', 'start_ms': 5, 'end_ms': 7},
            {'clock': 'server', 'flow': 'detail', 'phase': 'selected_sql', 'start_ms': 7, 'end_ms': 8},
            {'clock': 'browser', 'flow': 'graph', 'phase': 'body', 'start_ms': 90, 'end_ms': 200},
        ]
        valid = measurement.validate_phase_intervals(intervals)
        self.assertEqual(valid.get('valid'), True, 'independent clock/flow intervals are legal')
        self.assertEqual(valid['errors'], [])
        for bad in (
            dict(intervals[2], start_ms=109),  # paint before JSON finishes
            dict(intervals[2], end_ms=112),  # reversed interval
            dict(intervals[2], start_ms=float('nan')),
        ):
            with self.subTest(bad=bad):
                invalid = measurement.validate_phase_intervals(intervals[:2] + [bad])
                self.assertFalse(invalid['valid'])
                self.assertTrue(invalid['errors'], 'bad observations must not silently disappear')

    def test_request_inventory_is_deterministic_bounded_and_sanitized(self):
        requests = [
            {'method': 'GET', 'url': 'http://127.0.0.1:8000/api/mood-axis-graph?contract=v3'},
            {'method': 'GET', 'url': 'http://127.0.0.1:8000/api/tracks/summary?query=Public&limit=100'},
            {'method': 'POST', 'url': 'http://127.0.0.1:8000/api/current'},
            {'method': 'GET', 'url': 'http://127.0.0.1:8000/api/tracks/sha256%3A' + 'a' * 64},
            {'method': 'GET', 'url': 'http://127.0.0.1:8000/api/tracks/summary?query=Public&cursor=opaque'},
        ]
        expected = [
            {'method': 'GET', 'route': '/api/mood-axis-graph', 'count': 1},
            {'method': 'GET', 'route': '/api/tracks/:handle', 'count': 1},
            {'method': 'GET', 'route': '/api/tracks/summary', 'count': 2},
            {'method': 'POST', 'route': '/api/current', 'count': 1},
        ]
        report = measurement.request_inventory(requests)
        self.assertEqual(report.get('requests'), expected, 'sort by method/route, retain every request count')
        self.assertEqual(report, measurement.request_inventory(list(reversed(requests))))
        encoded = json.dumps(report)
        for secret in ('Public', 'opaque', '127.0.0.1', 'a' * 64):
            self.assertNotIn(secret, encoded)

    @staticmethod
    def tiny_browser_only_body():
        payload = {
            'dto_version': INDEXED_DTO_VERSION,
            'axis': [{'key': k, 'label': k, 'scale': 'synthetic'} for k in 'xyz'],
            'metadata': {}, 'selected_mood': None, 'available_moods': [],
            'genre_labels': [], 'reason_text': [], 'provenance_table': [],
            'explanation_table': [], 'link_defaults': {},
            'nodes': [['synthetic-a', '楽しい', 0, 0, 0, 0, 0, 0, None, None, [], [], 0]],
            'links': [], 'unpositioned': [],
        }
        return json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')

    def test_tiny_indexed_fixture_is_valid_fake_integrity_only(self):
        body = self.tiny_browser_only_body()

        class FakeResponse:
            status = 200

            def read(self):
                return body

            def getheader(self, name):
                return str(len(body)) if name == 'Content-Length' else None

        report = measure_samples(
            [FakeResponse],
            expected={'sha256': hashlib.sha256(body).hexdigest(),
                      'counts': {'nodes': 1, 'links': 0, 'unpositioned': 0}},
            db_fingerprint=lambda: 'no-db-opened',
        )
        self.assertEqual(report['succeeded'], 1)
        self.assertEqual(report['samples'][0]['outcome'], 'ok')
        self.assertNotIn('elapsed_ms', report['samples'][0])

    def test_graph_manifest_uses_wire_bytes_and_labels_browser_only_provenance(self):
        body = self.tiny_browser_only_body()
        report = measurement.graph_manifest(body, source='browser-only')
        self.assertEqual(report.get('sha256'), hashlib.sha256(body).hexdigest(), 'hash actual HTTP entity bytes')
        self.assertEqual(report['body_bytes'], len(body))
        self.assertEqual(report['counts'], {'nodes': 1, 'links': 0, 'unpositioned': 0})
        self.assertEqual(report['source'], 'browser-only')
        self.assertIsNone(report['db_schema_version'], 'a generated response cannot imply a v10 DB read')
        self.assertLess(len(body), 4096, 'default unit RED must not allocate the 41 MiB scenario')

    def test_bounded_writer_v10_fixture_inspection_is_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'public.sqlite'
            writer = SQLiteAnalysisRepository(str(path))
            identity = register_track(writer, 'a', location='/synthetic/a.flac')
            complete_graph_relevant_run(writer, identity, location='/synthetic/a.flac')
            before = path.read_bytes()
            report = measurement.inspect_fixture(path)
            self.assertEqual(report.get('schema_version'), 10, 'inspect real writer schema, not legacy v6 smoke')
            self.assertEqual(report['application_id'], 0x4D414E41)
            self.assertEqual(report['integrity_check'], 'ok')
            self.assertEqual(report['foreign_key_check'], [])
            self.assertEqual(report['counts']['tracks'], 1)
            self.assertEqual(report['counts']['current_graph_feature_evidence'], 1)
            self.assertEqual(path.read_bytes(), before, 'inspection must not migrate or modify fixture')

    def test_read_only_fingerprint_includes_live_wal_and_absence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'public.sqlite'
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute('PRAGMA journal_mode=WAL').fetchone(), ('wal',))
                db.execute('PRAGMA wal_autocheckpoint=0')
                db.execute('CREATE TABLE synthetic(value INTEGER)')
                db.commit()
                wal = Path(str(path) + '-wal')
                before_bytes = (path.read_bytes(), wal.read_bytes())
                before = measurement.fingerprint_sqlite_files(path)
                self.assertEqual(before.get('main_sha256'), hashlib.sha256(before_bytes[0]).hexdigest())
                self.assertEqual(before['wal_sha256'], hashlib.sha256(before_bytes[1]).hexdigest())
                self.assertEqual((path.read_bytes(), wal.read_bytes()), before_bytes)
                db.execute('INSERT INTO synthetic VALUES(1)')
                db.commit()
                after = measurement.fingerprint_sqlite_files(path)
                self.assertEqual(after['main_sha256'], before['main_sha256'])
                self.assertNotEqual(after['wal_sha256'], before['wal_sha256'])
                self.assertNotEqual(before, after, 'main-file-only hash misses committed live WAL changes')
            absent = measurement.fingerprint_sqlite_files(path)
            self.assertIsNone(absent['wal_sha256'], 'absent WAL is explicit, never a fake unchanged sentinel')
