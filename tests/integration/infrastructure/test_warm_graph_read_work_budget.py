"""PR B work contract: each warm request fully validates every identity once.

Public synthetic schema10 only. Constructor work is excluded; requests reuse a
repository but never counters or validation results. Spies retain identities,
not decoded evidence, and delegate to the actual reader and semantic validator.
These two work-budget tests are deliberately RED on merged PR68 (0421f946).
"""
from collections import Counter
from contextlib import closing, contextmanager
import hashlib
import http.client
import json
import threading
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from music_analyzer.application.use_cases.explorer import BuildMoodAxisGraph as AnalyzerGraph
from music_analyzer.domain.catalogue import FileIdentity
from music_analyzer.domain.projection import ProjectionEdge
from music_analyzer.infrastructure.persistence.analysis import SQLiteAnalysisRepository
from music_analyzer.infrastructure.persistence import explorer_readonly as analyzer_reader
from music_explorer.application.use_cases.explorer import BuildMoodAxisGraph as StandaloneGraph
from music_explorer.infrastructure import explorer_readonly as standalone_reader
from music_explorer.frameworks.explorer import server as http_server
from music_explorer.interface_adapters.mood_axis_graph_http import to_indexed_mood_axis_graph_http
from tests.integration.infrastructure.test_compact_mood_axis_graph_red import (
    add_positioned_track, add_positioned_track_identity,
)

MIRRORS = ((analyzer_reader, AnalyzerGraph), (standalone_reader, StandaloneGraph))


def encode(payload):
    return json.dumps(payload, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False)


def store_evidence(db, identity, payload):
    text = encode(payload)
    db.execute('UPDATE graph_feature_evidence SET evidence_json=?,fingerprint=? '
               'WHERE track_id=? AND run_id=?',
               (text, hashlib.sha256(text.encode('utf-8')).hexdigest(), *identity))


def create_public_warm_fixture(path):
    """Two positioned current rows and one historical row with fixed run IDs."""
    with patch('music_analyzer.infrastructure.persistence.analysis.uuid4',
               side_effect=('public-history-a', 'public-current-a', 'public-current-b',
                            'public-build', 'public-attempt')):
        writer = SQLiteAnalysisRepository(str(path))
        first = add_positioned_track(writer, 'a', bpm=119.0)
        add_positioned_track(writer, 'a', bpm=120.0)
        second = add_positioned_track_identity(
            writer, FileIdentity('b' * 64, 10), '/music/楽しい β.flac', bpm=128.0,
            genres=(('jazz', 'rock'), (0.8, 0.1)))
        with closing(sqlite3.connect(path)) as db, db:
            rows = tuple(db.execute('SELECT track_id,run_id,evidence_json '
                                    'FROM graph_feature_evidence'))
            for track, run, text in rows:
                payload = json.loads(text)
                for stage in ('energy', 'mood', 'genres'):
                    summary = payload['features'][stage]['summary']
                    summary['minimum'] = [value - 0.01 for value in summary['mean']]
                    summary['maximum'] = [value + 0.01 for value in summary['mean']]
                    summary['coverage'] = 0.75
                    summary['uncertainty'] = 'Public synthetic résumé uncertainty'
                store_evidence(db, (track, run), payload)
            db.execute("UPDATE runs SET created_at='2026-01-01 00:00:00'")
        edge = ProjectionEdge(first, second, 0.25, 2)
        writer.replace_graph_snapshot((edge,), 10, 'public-warm-work-budget',
                                      positioned_edges=(edge,))
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("UPDATE graph_builds SET created_at='2026-01-01 00:00:00', "
                   "completed_at='2026-01-01 00:00:00'")
        assert db.execute('PRAGMA user_version').fetchone() == (10,)
        identities = tuple(db.execute('SELECT track_id,run_id,is_current '
                                      'FROM graph_feature_evidence ORDER BY track_id,run_id'))
    return (first, second), identities


@contextmanager
def observe_real_evidence(repo, module):
    """Count actual yielded raw rows and complete semantic/canonical validation."""
    raw_rows, validations = Counter(), Counter()
    original_chunks = repo._iter_graph_feature_evidence_payload_chunks
    original_validate = module.validate_graph_feature_evidence_payload

    def chunks(*args, **kwargs):
        for chunk in original_chunks(*args, **kwargs):
            def rows(source=chunk):
                for row in source:
                    raw_rows[row[:2]] += 1
                    yield row
            yield rows()

    def validate(track, run, fingerprint, payload):
        validations[(track, run)] += 1
        return original_validate(track, run, fingerprint, payload)

    with patch.object(repo, '_iter_graph_feature_evidence_payload_chunks', chunks), \
            patch.object(module, 'validate_graph_feature_evidence_payload', validate):
        yield raw_rows, validations


@contextmanager
def graph_http_endpoint(repo, builder):
    """Exercise the real HTTP handler with either real SQLite reader mirror."""
    with patch.object(http_server, 'ReadOnlyExplorerSQLiteRepository', return_value=repo), \
            patch.object(http_server, 'BuildMoodAxisGraph', builder):
        server = http_server.create_server(str(repo._path), port=0)
        thread = threading.Thread(target=server.serve_forever,
                                  kwargs={'poll_interval': 0.01}, daemon=True)
        thread.start()
        try:
            yield server.server_port
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            assert not thread.is_alive(), 'Synthetic HTTP server did not stop'


def fetch_graph(port):
    with closing(http.client.HTTPConnection('127.0.0.1', port, timeout=3)) as client:
        client.request('GET', '/api/mood-axis-graph?contract=v3&mood=relaxing')
        response = client.getresponse()
        return response.status, response.getheader('Content-Length'), response.read()


class WarmGraphReadWorkBudgetTests(unittest.TestCase):
    maxDiff = None
    def _assert_once_per_request(self, module, builder):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'public.sqlite'
            tracks, identities = create_public_warm_fixture(path)
            current = {(track, run) for track, run, flag in identities if flag}
            historical = {(track, run) for track, run, flag in identities if not flag}
            self.assertEqual((len(current), len(historical)), (2, 1))
            expected = Counter({(track, run): 1 for track, run, _flag in identities})
            repo = module.ReadOnlyExplorerSQLiteRepository(str(path))
            before = path.read_bytes()
            # A fresh observation for each request on the SAME reader prevents
            # a request-spanning trust cache from satisfying the work budget.
            for request in range(2):
                with self.subTest(request=request):
                    with observe_real_evidence(repo, module) as (raw_rows, validations):
                        graph = builder(repo).execute('relaxing')
                    self.assertEqual(tuple(node.track_id for node in graph.positioned), tracks)
                    self.assertEqual(graph.metadata['graph_status']['state'], 'ready')
                    self.assertEqual(path.read_bytes(), before)
                    self.assertEqual({key: raw_rows[key] for key in historical},
                                     {key: 1 for key in historical})
                    self.assertEqual({key: validations[key] for key in historical},
                                     {key: 1 for key in historical})
                    self.assertEqual(
                        (validations, raw_rows), (expected, expected),
                        'Each current AND historical identity must be yielded and fully '
                        'semantically/canonically validated once per warm request; '
                        'the baseline repeats only selected current identities')

    def test_analyzer_each_evidence_identity_is_loaded_and_fully_validated_once_per_warm_request(self):
        self._assert_once_per_request(analyzer_reader, AnalyzerGraph)

    def test_standalone_each_evidence_identity_is_loaded_and_fully_validated_once_per_warm_request(self):
        self._assert_once_per_request(standalone_reader, StandaloneGraph)


class WarmGraphReadSafetyControls(unittest.TestCase):
    def test_recomputed_hash_semantic_corruption_in_last_row_fails_before_http_success(self):
        for module, builder in MIRRORS:
            for historical in (False, True):
                with self.subTest(reader=module.__name__, historical=historical), \
                        tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / 'public.sqlite'
                    tracks, identities = create_public_warm_fixture(path)
                    repo = module.ReadOnlyExplorerSQLiteRepository(str(path))
                    target = next((track, run) for track, run, flag in identities
                                  if bool(flag) != historical)
                    original_chunks = repo._iter_graph_feature_evidence_payload_chunks

                    def target_last(*args, **kwargs):
                        # Only this three-row fixture is reordered; still yield
                        # real SQLite rows, and validate all of them for real.
                        for chunk in original_chunks(*args, **kwargs):
                            rows = sorted(chunk, key=lambda row: row[:2] == target)
                            yield iter(rows)

                    with graph_http_endpoint(repo, builder) as port:
                        self.assertEqual(fetch_graph(port)[0], 200)
                        with closing(sqlite3.connect(path)) as db, db:
                            text = db.execute('SELECT evidence_json FROM graph_feature_evidence '
                                              'WHERE track_id=? AND run_id=?', target).fetchone()[0]
                            payload = json.loads(text)
                            if historical:
                                # Historical evidence is not selected by graph
                                # projection. An unavailable track is still validated.
                                payload['features']['mood']['summary']['coverage'] = 1.25
                                db.execute('UPDATE locations SET available=0 WHERE track_id=?',
                                           (tracks[0],))
                            else:
                                payload['features']['bpm']['values'][0][1] = True
                            store_evidence(db, target, payload)  # correct canonical hash
                        before = path.read_bytes()
                        with patch.object(repo, '_iter_graph_feature_evidence_payload_chunks', target_last), \
                                observe_real_evidence(repo, module) as (raw_rows, validations):
                            status, length, body = fetch_graph(port)
                        self.assertEqual(status, 400, 'No HTTP200/partial success for last-row corruption')
                        self.assertEqual(int(length), len(body))
                        self.assertIn('error', json.loads(body))
                        self.assertEqual(set(raw_rows), {(track, run) for track, run, _flag in identities})
                        self.assertEqual(validations, Counter({key: 1 for key in raw_rows}))
                        self.assertEqual(path.read_bytes(), before)

    def test_missing_identity_and_duplicate_replacement_fail_closed(self):
        # A duplicate replacing another required row leaves an identity missing.
        # This does NOT claim duplicate-only delivery is rejected on the baseline.
        for module, builder in MIRRORS:
            for duplicate_replacement in (False, True):
                with self.subTest(reader=module.__name__, duplicate=duplicate_replacement), \
                        tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / 'public.sqlite'
                    tracks, _identities = create_public_warm_fixture(path)
                    repo = module.ReadOnlyExplorerSQLiteRepository(str(path))
                    self.assertEqual(builder(repo).execute('relaxing').metadata['graph_status']['state'], 'ready')
                    original_chunks = repo._iter_graph_feature_evidence_payload_chunks

                    def incomplete(*args, **kwargs):
                        for chunk in original_chunks(*args, **kwargs):
                            def rows(source=chunk):
                                previous = None
                                for row in source:
                                    if row[0] == tracks[1]:
                                        if duplicate_replacement:
                                            assert previous is not None
                                            yield previous
                                    else:
                                        previous = row
                                        yield row
                            yield rows()

                    before = path.read_bytes()
                    with patch.object(repo, '_iter_graph_feature_evidence_payload_chunks', incomplete):
                        with self.assertRaises(module.AnalysisError):
                            builder(repo).execute('relaxing')
                    self.assertEqual(path.read_bytes(), before)

    def test_oversized_payload_is_rejected_before_any_raw_evidence_is_yielded_or_validated(self):
        for module, builder in MIRRORS:
            with self.subTest(reader=module.__name__), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'public.sqlite'
                tracks, _identities = create_public_warm_fixture(path)
                repo = module.ReadOnlyExplorerSQLiteRepository(str(path))
                self.assertEqual(builder(repo).execute('relaxing').metadata['graph_status']['state'], 'ready')
                with closing(sqlite3.connect(path)) as db, db:
                    db.execute('UPDATE graph_feature_evidence SET evidence_json=? '
                               'WHERE track_id=? AND is_current=1',
                               ('x' * (16 * 1024 * 1024 + 1), tracks[0]))
                before = hashlib.sha256(path.read_bytes()).digest()
                with observe_real_evidence(repo, module) as (raw_rows, validations):
                    with self.assertRaisesRegex(module.AnalysisError, 'Oversized stored graph feature evidence'):
                        builder(repo).execute('relaxing')
                self.assertEqual((raw_rows, validations), (Counter(), Counter()))
                self.assertEqual(hashlib.sha256(path.read_bytes()).digest(), before)

    def test_same_reader_detects_stale_snapshot_after_graph_relevant_source_change(self):
        for module, builder in MIRRORS:
            with self.subTest(reader=module.__name__), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'public.sqlite'
                tracks, _identities = create_public_warm_fixture(path)
                repo = module.ReadOnlyExplorerSQLiteRepository(str(path))
                self.assertEqual(builder(repo).execute('relaxing').metadata['graph_status']['state'], 'ready')
                SQLiteAnalysisRepository(str(path)).set_override(tracks[0], 'bpm', 121.0)
                before = path.read_bytes()
                graph = builder(repo).execute('relaxing')
                self.assertEqual(graph.metadata['graph_status']['state'], 'stale')
                self.assertEqual(graph.edges, ())
                self.assertIn('music-analyzer graph build --database', graph.metadata['graph_status']['action'])
                self.assertEqual(path.read_bytes(), before)

    def test_mirrored_exact_v3_http_bytes_and_order_survive_reversed_evidence_delivery(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'public.sqlite'
            tracks, _identities = create_public_warm_fixture(path)
            expected_graph = AnalyzerGraph(analyzer_reader.ReadOnlyExplorerSQLiteRepository(str(path))).execute('relaxing')
            expected_payload = to_indexed_mood_axis_graph_http(expected_graph)
            # Match the existing HTTP serializer exactly, including UTF-8 and
            # whitespace, not just equivalent parsed JSON or sorted identities.
            expected_body = json.dumps(expected_payload, sort_keys=True,
                                       ensure_ascii=False, allow_nan=False).encode('utf-8')
            self.assertEqual(tuple(node[0] for node in expected_payload['nodes']), tracks)
            self.assertEqual(tuple(node[1] for node in expected_payload['nodes']), ('a.flac', '楽しい β.flac'))
            self.assertEqual(expected_payload['available_moods'], ['heavy', 'relaxing'])
            self.assertEqual(expected_payload['genre_labels'], ['jazz', 'rock'])
            self.assertEqual(expected_payload['links'][0][:4], [0, 1, 0.75, 2])
            self.assertEqual(expected_payload['provenance_table'], [{
                'neighbour_policy': 'endpoint-local-exact-top-k-neighbours-v2',
                'policy': 'symmetric-feature-distance-v1',
                'source': 'graph_build_positioned_edges',
            }])
            # Public synthetic golden independently characterized at 0421f946;
            # protects against simultaneous reader/mapper drift, not just parity.
            self.assertEqual(len(expected_body), 1647)
            self.assertEqual(hashlib.sha256(expected_body).hexdigest(),
                             '5d62a632a8341ba144a7259758b6bfa1e19f532b74553fd4773c2016a2c2fa0b')
            before = path.read_bytes()
            for module, builder in MIRRORS:
                with self.subTest(reader=module.__name__):
                    repo = module.ReadOnlyExplorerSQLiteRepository(str(path))
                    original_chunks = repo._iter_graph_feature_evidence_payload_chunks

                    def reversed_rows(*args, **kwargs):
                        for chunk in original_chunks(*args, **kwargs):
                            yield reversed(tuple(chunk))

                    with patch.object(repo, '_iter_graph_feature_evidence_payload_chunks', reversed_rows), \
                            graph_http_endpoint(repo, builder) as port:
                        for request in range(2):
                            status, length, body = fetch_graph(port)
                            self.assertEqual(status, 200)
                            self.assertEqual(int(length), len(expected_body))
                            self.assertEqual(body, expected_body, f'exact bytes/order changed on request {request}')
                    self.assertEqual(path.read_bytes(), before)

    def test_analyzer_public_graph_source_reader_preserves_all_summary_diagnostics_and_provenance(self):
        # Coverage limitation: standalone has no equivalent public compact
        # graph_source_tracks consumer for minimum/maximum/coverage/provisional/
        # summary uncertainty. Its read_track/candidate_snapshot read raw stages.
        # Mirrored public graph DTO/provenance/exact HTTP coverage remains above;
        # this additional full compact-summary diagnostic control is analyzer-only.
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'public.sqlite'
            tracks, _identities = create_public_warm_fixture(path)
            repo = analyzer_reader.ReadOnlyExplorerSQLiteRepository(str(path))
            before = path.read_bytes()
            records = tuple(repo.graph_source_tracks())
            self.assertEqual(tuple(record.track_id for record in records), tracks)
            for record in records:
                stages = {stage.stage: stage for stage in record.run.stages}
                for name in ('mood', 'energy', 'genres'):
                    summary = stages[name].summary
                    self.assertEqual(summary.coverage, 0.75)
                    self.assertTrue(summary.provisional)
                    self.assertEqual(summary.uncertainty, 'Public synthetic résumé uncertainty')
                    self.assertEqual(summary.minimum, tuple(value - 0.01 for value in summary.mean))
                    self.assertEqual(summary.maximum, tuple(value + 0.01 for value in summary.mean))
                self.assertEqual(stages['energy'].provenance, (
                    ('emomusic-msd-musicnn-2', 'synthetic-sha256'),
                    ('scale', 'native_valence_arousal_regression')))
                self.assertEqual(stages['mood'].provenance, (
                    ('mtg_jamendo_moodtheme-discogs-effnet-1', 'synthetic-sha256'),
                    ('scale', 'sigmoid_mean_score_0_1')))
            self.assertEqual(path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
