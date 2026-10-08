"""Public, deterministic contracts for PR M (not the PR B optimization).

The new outer-layer module is intentionally absent at the tests-only stage.
_call is a test-local unavailable boundary: it returns an empty report, never
invents acceptance, rejection, percentiles, or observed work totals. Only the exact missing module
is caught; broken imports inside an eventual implementation remain real errors.
Proposed API is documented by the inputs and literal output assertions below.
No wall-time threshold, private fixture, live server, or resource cap is required.
"""
import hashlib
import importlib
import json
import sqlite3
import tempfile
import unittest
from collections import Counter
from contextlib import ExitStack, closing
from pathlib import Path
from unittest.mock import patch

from music_analyzer.application.use_cases.graph_feature_evidence import validate_graph_feature_evidence_payload
from music_analyzer.infrastructure.persistence.analysis import SQLiteAnalysisRepository
from music_analyzer.infrastructure.persistence import explorer_readonly as analyzer_reader
from music_analyzer.application.use_cases.explorer import BuildMoodAxisGraph as AnalyzerGraph
from music_explorer.infrastructure import explorer_readonly as standalone_reader
from music_explorer.application.use_cases.explorer import BuildMoodAxisGraph as StandaloneGraph
from music_explorer.interface_adapters.mood_axis_graph_http import to_indexed_mood_axis_graph_http
from tests.acceptance import test_mood_axis_graph_indexed_http_red as public_graph_fixture
from tests.integration.infrastructure.test_compact_mood_axis_graph_red import add_positioned_track

try:
    _harness = importlib.import_module('tools.graph_read_benchmark')
except ModuleNotFoundError as error:
    if error.name != 'tools.graph_read_benchmark':
        raise
    _harness = None


def _call(name, *args, **kwargs):
    if _harness is None:
        if name == 'measure_samples':
            return {'samples': [], 'attempted': 0, 'succeeded': 0}
        if name == 'summarize_work':
            return {'raw_rows': {}, 'validations': {}, 'raw_row_total': 0, 'validation_total': 0}
        return None
    return getattr(_harness, name)(*args, **kwargs)


def _encode(payload):
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False).encode('utf-8')


class FakeResponse:
    """http.client response surface; body must be read to measure full hash."""
    def __init__(self, body, status=200, content_length=None):
        self.status = status
        self.body = body
        self.headers = {'Content-Length': str(len(body) if content_length is None else content_length)}
        self.reads = 0

    def getheader(self, name, default=None):
        return self.headers.get(name, default)

    def read(self):
        self.reads += 1
        return self.body


class GraphReadMeasurementContractTests(unittest.TestCase):
    def setUp(self):
        # Existing public synthetic DTO/real v3 mapper: no pretend v3 JSON.
        graph = public_graph_fixture.IndexedMoodAxisGraphHttpContractRedTests()._synthetic_repeated_string_graph(3)
        self.payload = to_indexed_mood_axis_graph_http(graph)
        self.body = _encode(self.payload)
        self.expected = {
            'sha256': hashlib.sha256(self.body).hexdigest(),
            'counts': {'nodes': 3, 'links': 2, 'unpositioned': 0},
        }

    def measure(self, probes, fingerprint=lambda: 'unchanged-public-db'):
        # Probes perform one full public response exchange. Runner must call the
        # DB fingerprint before and after each attempt, including failures.
        report = _call('measure_samples', probes, expected=self.expected, db_fingerprint=fingerprint)
        self.assertEqual(len(report['samples']), len(probes), 'Every attempted measurement must retain a sample')
        return report

    def test_valid_response_records_full_bytes_hash_counts_and_sample_identity(self):
        response = FakeResponse(self.body)
        report = self.measure([lambda: response])
        self.assertEqual(len(report['samples']), 1)
        sample = report['samples'][0]
        self.assertEqual(sample['index'], 0)
        self.assertEqual(sample['outcome'], 'ok')
        self.assertEqual(sample['http_status'], 200)
        self.assertEqual(sample['body_bytes'], len(self.body))
        self.assertEqual(sample['sha256'], self.expected['sha256'])
        self.assertEqual(sample['counts'], self.expected['counts'])
        self.assertEqual(response.reads, 1)

    def test_non_200_is_a_retained_failure_not_a_success_or_dropped_sample(self):
        report = self.measure([lambda: FakeResponse(self.body, status=400)])
        self.assertEqual(len(report['samples']), 1)
        self.assertEqual(report['samples'][0]['outcome'], 'http_status')
        self.assertEqual(report['samples'][0]['http_status'], 400)

    def test_full_body_hash_mismatch_even_when_json_counts_are_unchanged(self):
        # Valid JSON with unchanged topology/counts but different full bytes
        # must not be accepted solely because those structural counts match.
        changed = dict(self.payload, selected_mood='synthetic-other-mood')
        report = self.measure([lambda: FakeResponse(_encode(changed))])
        self.assertEqual(report['samples'][0]['outcome'], 'body_hash')

    def test_wrong_counts_are_rejected_even_with_matching_full_hash(self):
        self.expected['counts']['nodes'] = 4
        report = self.measure([lambda: FakeResponse(self.body)])
        self.assertEqual(report['samples'][0]['outcome'], 'counts')

    def test_content_length_is_exact_utf8_bytes_not_characters(self):
        changed = dict(self.payload, selected_mood='楽しい')
        body = _encode(changed)
        self.expected['sha256'] = hashlib.sha256(body).hexdigest()
        report = self.measure([lambda: FakeResponse(body, content_length=len(body.decode('utf-8')))])
        self.assertEqual(report['samples'][0]['outcome'], 'content_length')

    def test_malformed_json_and_non_v3_json_are_rejected_with_matching_hash(self):
        missing_table = {key: value for key, value in self.payload.items() if key != 'provenance_table'}
        for body in (b'{broken', _encode(dict(self.payload, dto_version='mood-axis-graph-compact-v1')),
                     _encode(dict(self.payload, nodes='not-an-array')), _encode(missing_table)):
            with self.subTest(body=body[:40]):
                self.expected['sha256'] = hashlib.sha256(body).hexdigest()
                report = self.measure([lambda: FakeResponse(body)])
                self.assertEqual(report['samples'][0]['outcome'], 'invalid_v3')

    def test_database_mutation_is_detected_around_the_measured_exchange(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'public.sqlite'
            with closing(sqlite3.connect(path)) as db, db:
                db.execute('CREATE TABLE marker(value INTEGER)')
                db.execute('INSERT INTO marker VALUES (1)')
            def fingerprint():
                return hashlib.sha256(path.read_bytes()).hexdigest()
            def mutate():
                with closing(sqlite3.connect(path)) as db, db:
                    db.execute('UPDATE marker SET value=2')
                return FakeResponse(self.body)
            report = self.measure([mutate], fingerprint)
            self.assertEqual(report['samples'][0]['outcome'], 'db_changed')

    def test_timeout_and_oom_samples_remain_in_order_between_successes(self):
        events = []
        def fingerprint():
            events.append('fingerprint')
            return 'unchanged-public-db'
        def success():
            events.append('success')
            return FakeResponse(self.body)
        def timeout():
            events.append('timeout')
            raise TimeoutError('public synthetic timeout')
        def oom():
            events.append('oom')
            raise MemoryError('public synthetic OOM')
        report = self.measure([success, timeout, oom, success], fingerprint)
        self.assertEqual(events, [
            'fingerprint', 'success', 'fingerprint',
            'fingerprint', 'timeout', 'fingerprint',
            'fingerprint', 'oom', 'fingerprint',
            'fingerprint', 'success', 'fingerprint',
        ])
        self.assertEqual([sample['index'] for sample in report['samples']], [0, 1, 2, 3])
        self.assertEqual([sample['outcome'] for sample in report['samples']], ['ok', 'timeout', 'oom', 'ok'])
        self.assertEqual(report['attempted'], 4)
        self.assertEqual(report['succeeded'], 2)

    def test_nearest_rank_p95_uses_rank_19_of_20_not_interpolation(self):
        values = [200, *range(1, 20)]
        value = _call('nearest_rank', values, 95)
        self.assertEqual(value, 19)
        self.assertEqual(_call('nearest_rank', [7], 95), 7)
        self.assertEqual(_call('nearest_rank', [7, 1, 6, 2, 5, 3, 4], 95), 7)
        self.assertEqual(_call('nearest_rank', [4, 1, 3, 2], 50), 2)
        self.assertEqual(_call('nearest_rank', [4, 1, 3, 2], 100), 4)


class GraphReadWorkCharacterizationTests(unittest.TestCase):
    """Counts real yielded rows and complete validation, never SQL spelling.

    Constructor validation is excluded. Each measured request starts fresh
    counters; the semantic validator still parses every nested rule/canonical
    hash. The streaming warm reader requires N+H complete validations per request.
    """
    def _measure_work(self, module, builder, path):
        repo = module.ReadOnlyExplorerSQLiteRepository(str(path))
        raw_rows, validations = Counter(), Counter()
        original_chunks = repo._iter_graph_feature_evidence_payload_chunks
        def chunks(*args, **kwargs):
            for chunk in original_chunks(*args, **kwargs):
                def rows(source=chunk):
                    for row in source:
                        raw_rows[row[:2]] += 1
                        yield row
                yield rows()
        def validate(track_id, run_id, fingerprint, payload):
            validations[(track_id, run_id)] += 1
            return validate_graph_feature_evidence_payload(track_id, run_id, fingerprint, payload)
        with ExitStack() as stack:
            stack.enter_context(patch.object(repo, '_iter_graph_feature_evidence_payload_chunks', chunks))
            stack.enter_context(patch.object(module, 'validate_graph_feature_evidence_payload', validate))
            graph = builder(repo).execute('relaxing')
        self.assertEqual(len(graph.positioned), 2)
        return raw_rows, validations

    def test_real_readers_revalidate_all_identities_on_each_request_at_n_plus_h(self):
        self._characterize(require_report=False)

    def test_observed_per_identity_work_report_preserves_streaming_counts(self):
        self._characterize(require_report=True)

    def _characterize(self, *, require_report):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'public.sqlite'
            writer = SQLiteAnalysisRepository(str(path))
            add_positioned_track(writer, 'a')
            add_positioned_track(writer, 'a', bpm=121.0)  # one historical identity
            add_positioned_track(writer, 'b')
            with closing(sqlite3.connect(path)) as db, db:
                identities = tuple(db.execute('SELECT track_id,run_id,is_current FROM graph_feature_evidence'))
            expected = Counter({(track, run): 1 for track, run, _current in identities})
            self.assertEqual(sum(expected.values()), 2 + 1)
            for module, builder in ((analyzer_reader, AnalyzerGraph), (standalone_reader, StandaloneGraph)):
                for request in range(2):
                    with self.subTest(reader=module.__name__, request=request):
                        raw_rows, validations = self._measure_work(module, builder, path)
                        self.assertEqual(raw_rows, expected)
                        self.assertEqual(validations, expected)
                        if not require_report:
                            continue
                        report = _call('summarize_work', raw_rows=raw_rows, validations=validations)
                        self.assertEqual(report['raw_rows'], dict(expected))
                        self.assertEqual(report['validations'], dict(expected))
                        self.assertEqual(report['raw_row_total'], 3)
                        self.assertEqual(report['validation_total'], 3)


if __name__ == '__main__':
    unittest.main()
