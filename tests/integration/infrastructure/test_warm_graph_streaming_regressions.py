"""Public synthetic PR B regressions; spies keep only scalars and weakrefs."""
from collections import Counter
from contextlib import closing
import gc
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import weakref

from music_analyzer.application.use_cases import explorer as analyzer_projection
from music_explorer.application.use_cases import explorer as standalone_projection
from music_analyzer.infrastructure.persistence.analysis import SQLiteAnalysisRepository
from tests.integration.infrastructure.test_warm_graph_read_work_budget import (
    MIRRORS, create_public_warm_fixture, store_evidence, observe_real_evidence,
    graph_http_endpoint, fetch_graph,
)


class WeakPayload(dict):
    pass


def extend_batch_fixture(path, count=451):
    """Clone public metadata with independent runs (schema10 requires this)."""
    tracks, identities = create_public_warm_fixture(path)
    with closing(sqlite3.connect(path)) as db, db:
        run = next(run for track, run, current in identities if track == tracks[0] and current)
        template = json.loads(db.execute(
            'SELECT evidence_json FROM graph_feature_evidence WHERE track_id=? AND run_id=?',
            (tracks[0], run)).fetchone()[0])
        for index in range(count - len(tracks)):
            track = f'sha256:{index + 1000:064x}'
            db.execute('INSERT INTO tracks VALUES(?,?,?)', (track, f'{index + 1000:064x}', 10))
            db.execute('INSERT INTO locations VALUES(?,?,?,?,?)',
                       (f'/music/clone-{index:04d}.flac', track, 1, 'flac', 1))
            for table in ('track_audio', 'track_metadata'):
                columns = [row[1] for row in db.execute(f'PRAGMA table_info({table})')]
                original = list(db.execute(f'SELECT * FROM {table} WHERE track_id=?', (tracks[0],)).fetchone())
                original[columns.index('track_id')] = track
                db.execute(f'INSERT INTO {table} VALUES({",".join("?" for _ in columns)})', original)
            clone_run = f'public-clone-run-{index:04d}'
            columns = [row[1] for row in db.execute('PRAGMA table_info(runs)')]
            original = list(db.execute('SELECT * FROM runs WHERE id=?', (run,)).fetchone())
            original[columns.index('id')] = clone_run
            db.execute(f'INSERT INTO runs VALUES({",".join("?" for _ in columns)})', original)
            db.execute('INSERT INTO run_tracks(run_id,track_id) VALUES(?,?)', (clone_run, track))
            payload = json.loads(json.dumps(template))
            payload['track_id'] = track
            payload['run_id'] = clone_run
            payload['features']['bpm']['values'][0][1] = 100.0 + index % 70
            db.execute('INSERT INTO graph_feature_evidence SELECT ?,?, '
                       'fingerprint,evidence_json,is_current,created_at FROM graph_feature_evidence '
                       'WHERE track_id=? AND run_id=?', (track, clone_run, tracks[0], run))
            store_evidence(db, (track, clone_run), payload)
    SQLiteAnalysisRepository(str(path)).replace_graph_snapshot((), 10, 'public-batch-boundary', positioned_edges=())
    with closing(sqlite3.connect(path)) as db:
        return tuple(db.execute('SELECT track_id,run_id,is_current FROM graph_feature_evidence'))


class WarmGraphStreamingRegressions(unittest.TestCase):
    def test_projection_interleaves_with_delivery_and_releases_transient_objects(self):
        for (module, builder), projection in zip(MIRRORS, (analyzer_projection, standalone_projection)):
            with self.subTest(reader=module.__name__), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'public.sqlite'
                _tracks, identities = create_public_warm_fixture(path)
                current = {(track, run) for track, run, flag in identities if flag}
                repo = module.ReadOnlyExplorerSQLiteRepository(str(path))
                original_chunks = repo._iter_graph_feature_evidence_payload_chunks
                original_loads = json.loads
                original_add = projection._WarmMoodAxisProjection.add
                refs, projected = [], set()
                previous = None

                def loads(text, *args, **kwargs):
                    value = original_loads(text, *args, **kwargs)
                    if isinstance(value, dict) and 'feature_contract_version' in value:
                        value = WeakPayload(value)
                        refs.append(weakref.ref(value))
                    return value

                def add(accumulator, record):
                    projected.add(record.track_id)
                    refs.append(weakref.ref(record))
                    if record.run:
                        refs.append(weakref.ref(record.run))
                        refs.extend(weakref.ref(stage) for stage in record.run.stages)
                    return original_add(accumulator, record)

                def chunks(*args, **kwargs):
                    nonlocal previous
                    for chunk in original_chunks(*args, **kwargs):
                        def rows(source=chunk):
                            nonlocal previous
                            for row in source:
                                if previous is not None:
                                    if previous in current:
                                        self.assertIn(previous[0], projected,
                                                      'Current record must reach projection before next evidence row')
                                    gc.collect()
                                    self.assertFalse(any(ref() is not None for ref in refs),
                                                     'Decoded payload, stages and records must not survive next row')
                                    refs.clear()
                                previous = row[:2]
                                yield row
                        yield rows()
                with patch.object(repo, '_iter_graph_feature_evidence_payload_chunks', chunks), \
                        patch.object(module.json, 'loads', loads), \
                        patch.object(projection._WarmMoodAxisProjection, 'add', add):
                    graph = builder(repo).execute('relaxing')
                self.assertEqual(len(graph.positioned), 2)
                gc.collect()
                self.assertFalse(any(ref() is not None for ref in refs))

    def test_duplicate_only_delivery_fails_closed_even_when_all_identities_are_present(self):
        for module, builder in MIRRORS:
            with self.subTest(reader=module.__name__), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'public.sqlite'
                create_public_warm_fixture(path)
                repo = module.ReadOnlyExplorerSQLiteRepository(str(path))
                original_chunks = repo._iter_graph_feature_evidence_payload_chunks
                def duplicated(*args, **kwargs):
                    for chunk in original_chunks(*args, **kwargs):
                        def rows(source=chunk):
                            for row in source:
                                yield row
                                yield row
                        yield rows()
                before = path.read_bytes()
                with patch.object(repo, '_iter_graph_feature_evidence_payload_chunks', duplicated):
                    with self.assertRaises(module.AnalysisError):
                        builder(repo).execute('relaxing')
                self.assertEqual(path.read_bytes(), before)

    def test_451_current_identities_cross_batch_boundary_keep_per_track_features(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'public.sqlite'
            identities = extend_batch_fixture(path)
            expected = Counter({(track, run): 1 for track, run, _ in identities})
            before = path.read_bytes()
            for module, builder in MIRRORS:
                with self.subTest(reader=module.__name__):
                    repo = module.ReadOnlyExplorerSQLiteRepository(str(path))
                    with observe_real_evidence(repo, module) as (raw, validated):
                        graph = builder(repo).execute('relaxing')
                    self.assertEqual(len(graph.positioned), 451)
                    nodes = {node.track_id: node for node in graph.positioned}
                    self.assertEqual(nodes[f'sha256:{1000:064x}'].bpm, 100.0)
                    self.assertEqual(nodes[f'sha256:{1001:064x}'].bpm, 101.0)
                    self.assertTrue(raw == expected and validated == expected,
                                    f'Each of {len(expected)} identities must be delivered/validated once; '
                                    f'observed totals raw={sum(raw.values())}, validated={sum(validated.values())}')
                    self.assertEqual(path.read_bytes(), before)

    def test_schema10_rejects_shared_run_association_without_changing_graph(self):
        # A valid shared-run fixture cannot exist under the mandatory UNIQUE
        # run_tracks.run_id schema. Do not weaken that invariant for this test.
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'public.sqlite'
            tracks, identities = create_public_warm_fixture(path)
            run = next(run for track, run, current in identities if track == tracks[0] and current)
            with closing(sqlite3.connect(path)) as db, db:
                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute('INSERT INTO run_tracks(run_id,track_id) VALUES(?,?)', (run, tracks[1]))
            for module, builder in MIRRORS:
                with self.subTest(reader=module.__name__):
                    graph = builder(module.ReadOnlyExplorerSQLiteRepository(str(path))).execute('relaxing')
                    self.assertEqual(tuple(node.track_id for node in graph.positioned), tracks)

    def test_last_historical_corruption_aborts_after_current_projection_and_closes_delivery(self):
        for (module, builder), projection in zip(MIRRORS, (analyzer_projection, standalone_projection)):
            with self.subTest(reader=module.__name__), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'public.sqlite'
                _tracks, identities = create_public_warm_fixture(path)
                historical = next((track, run) for track, run, flag in identities if not flag)
                repo = module.ReadOnlyExplorerSQLiteRepository(str(path))
                with closing(sqlite3.connect(path)) as db, db:
                    text = db.execute('SELECT evidence_json FROM graph_feature_evidence '
                                      'WHERE track_id=? AND run_id=?', historical).fetchone()[0]
                    payload = json.loads(text)
                    payload['features']['mood']['summary']['coverage'] = 1.25
                    store_evidence(db, historical, payload)
                original_chunks = repo._iter_graph_feature_evidence_payload_chunks
                original_add = projection._WarmMoodAxisProjection.add
                projected, closed = set(), []
                def add(accumulator, record):
                    projected.add(record.track_id)
                    return original_add(accumulator, record)
                def historical_last(*args, **kwargs):
                    try:
                        for chunk in original_chunks(*args, **kwargs):
                            # Three public rows only; this ordering fixture is not a lifetime spy.
                            yield iter(sorted(chunk, key=lambda row: row[:2] == historical))
                    finally:
                        closed.append(True)
                with patch.object(repo, '_iter_graph_feature_evidence_payload_chunks', historical_last), \
                        patch.object(projection._WarmMoodAxisProjection, 'add', add), \
                        graph_http_endpoint(repo, builder) as port:
                    status, length, body = fetch_graph(port)
                self.assertEqual(status, 400)
                self.assertEqual(int(length), len(body))
                self.assertIn('error', json.loads(body))
                self.assertEqual(len(projected), 2, 'Last historical failure must follow both current projections')
                self.assertEqual(closed, [True])


if __name__ == '__main__':
    unittest.main()
