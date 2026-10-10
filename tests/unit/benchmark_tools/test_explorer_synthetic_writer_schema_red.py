"""PR4b RED contracts for a public writer-owned SQLite fixture, not latency.

Static oracle: twelve tracks, two completed runs per track, five stages per
run. Eight available positioned eligible tracks, one available unpositioned
eligible track, one available excluded track, two unavailable positioned
eligible tracks. Eligibility and availability intentionally remain independent:
active_tracks includes unavailable eligible tracks under the existing writer
views. Each snapshot is a chain over all eleven eligible tracks, with a
separate chain over the ten positioned tracks. Two snapshots are retained.

The generator belongs to outward diagnostic tooling; these tests neither
implement it nor copy writer DDL. Tiny defaults only; no private files/audio,
HTTP, browser, timing assertions or expensive graph cardinalities.
"""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from music_analyzer.application.use_cases.graph_feature_evidence import (
    validate_graph_feature_evidence_payload,
)
from music_analyzer.infrastructure.persistence.analysis import SQLiteAnalysisRepository
from music_analyzer.infrastructure.persistence.stage_mapping import stage_from_mapping
from music_explorer.application.use_cases.explorer import BuildMoodAxisGraph
from music_explorer.infrastructure.explorer_readonly import ReadOnlyExplorerSQLiteRepository
from tests.support.explorer_synthetic_fixture_contract import public_fixture
from tools.graph_read_benchmark import measure_samples
from tools.explorer_fixture_inspection import fingerprint_sqlite_files, inspect_fixture


# Independent literals, not counts derived from generator metadata or output.
TINY_COUNTS = {
    'tracks': 12, 'active_tracks': 11, 'excluded_tracks': 1,
    'unavailable_tracks': 2, 'locations': 12, 'active_locations': 9,
    'runs': 24, 'stages': 120, 'graph_feature_evidence': 22,
    'current_graph_feature_evidence': 11, 'historical_graph_feature_evidence': 11,
    'graph_builds': 2, 'current_graph_builds': 1, 'graph_edges': 10,
    'graph_build_edges': 20, 'graph_positioned_edges': 9,
    'graph_build_positioned_edges': 18,
}
GRAPH_COUNTS = {'nodes': 10, 'links': 9, 'unpositioned': 1}


def readonly(path):
    db = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    db.execute('PRAGMA query_only=ON')
    return closing(db)


class ExplorerSyntheticWriterSchemaRedTests(unittest.TestCase):
    def test_schema_is_exact_writer_owned_v10_not_legacy_or_custom_ddl(self):
        with public_fixture(self) as fixture, tempfile.TemporaryDirectory() as directory:
            reference = Path(directory) / 'writer.sqlite'
            SQLiteAnalysisRepository(str(reference))
            query = ("SELECT type,name,tbl_name,sql FROM sqlite_master "
                     "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name")
            with readonly(reference) as expected, readonly(fixture['db_path']) as actual:
                self.assertEqual(actual.execute('PRAGMA application_id').fetchone(), (0x4D414E41,))
                self.assertEqual(actual.execute('PRAGMA user_version').fetchone(), (10,))
                self.assertEqual(actual.execute(query).fetchall(), expected.execute(query).fetchall())
                self.assertEqual(actual.execute('PRAGMA integrity_check').fetchall(), [('ok',)])
                self.assertEqual(actual.execute('PRAGMA foreign_key_check').fetchall(), [])
            # Full reader validation is stronger than identifiers + integrity.
            repository = ReadOnlyExplorerSQLiteRepository(str(fixture['db_path']))
            self.assertEqual(len(repository.track_ids()), 11)

    def test_quiescent_writer_reopen_and_readers_preserve_main_and_wal(self):
        with public_fixture(self) as fixture:
            path = fixture['db_path']
            before = fingerprint_sqlite_files(path)
            self.assertIsNone(before['wal_sha256'], 'generator must finish its quiescent fixture lifecycle')
            # This is an ordinary writer constructor, not a nonexistent writer
            # read-only mode. Exact current-schema reopening must not migrate,
            # repair, regenerate evidence or modify the quiescent fixture.
            SQLiteAnalysisRepository(str(path))
            self.assertEqual(fingerprint_sqlite_files(path), before)
            inspected = inspect_fixture(path)
            self.assertEqual(inspected['schema_version'], 10)
            self.assertEqual(inspected['counts']['tracks'], 12)
            self.assertEqual(inspected['counts']['current_graph_feature_evidence'], 11)
            repository = ReadOnlyExplorerSQLiteRepository(str(path))
            self.assertEqual(len(repository.track_ids()), 11)
            graph = BuildMoodAxisGraph(repository).execute()
            self.assertEqual(len(graph.positioned), 10)
            self.assertEqual(len(graph.unpositioned), 1)
            self.assertEqual(fingerprint_sqlite_files(path), before)

    def test_manifest_and_actual_sql_match_independently_fixed_tiny_counts(self):
        with public_fixture(self) as fixture:
            manifest = fixture['manifest']
            self.assertEqual(manifest['schema_version'], 10)
            self.assertEqual(manifest['application_id'], 0x4D414E41)
            for key, count in TINY_COUNTS.items():
                with self.subTest(count=key):
                    self.assertEqual(manifest['counts'][key], count)
            queries = {
                key: 'SELECT count(*) FROM ' + key for key in (
                    'tracks', 'active_tracks', 'locations', 'active_locations',
                    'runs', 'stages', 'graph_feature_evidence', 'graph_builds',
                    'graph_edges', 'graph_build_edges', 'graph_positioned_edges',
                    'graph_build_positioned_edges',
                )
            }
            queries.update({
                'excluded_tracks': "SELECT count(*) FROM track_audio WHERE status='excluded'",
                'unavailable_tracks': 'SELECT count(DISTINCT track_id) FROM locations WHERE available=0',
                'current_graph_feature_evidence': 'SELECT count(*) FROM graph_feature_evidence WHERE is_current=1',
                'historical_graph_feature_evidence': 'SELECT count(*) FROM graph_feature_evidence WHERE is_current=0',
                'current_graph_builds': 'SELECT count(*) FROM graph_builds WHERE is_current=1',
            })
            with readonly(fixture['db_path']) as db:
                observed = {key: db.execute(query).fetchone()[0] for key, query in queries.items()}
                self.assertEqual(observed, TINY_COUNTS)
                self.assertEqual(db.execute(
                    "SELECT status,count(*) FROM runs GROUP BY status"
                ).fetchall(), [('completed', 24)])
                self.assertEqual(db.execute(
                    "SELECT status,is_current,count(*) FROM graph_builds GROUP BY status,is_current ORDER BY is_current"
                ).fetchall(), [('completed', 0, 1), ('completed', 1, 1)])

    def test_available_excluded_and_unavailable_membership_preserves_reader_policy(self):
        with public_fixture(self) as fixture:
            with readonly(fixture['db_path']) as db:
                eligible = {row[0] for row in db.execute('SELECT id FROM active_tracks')}
                excluded = {row[0] for row in db.execute("SELECT track_id FROM track_audio WHERE status='excluded'")}
                unavailable = {row[0] for row in db.execute('SELECT track_id FROM locations WHERE available=0')}
                visible_locations = {row[0] for row in db.execute('SELECT track_id FROM active_locations')}
            self.assertEqual(len(eligible), 11)
            self.assertEqual(len(excluded), 1)
            self.assertEqual(len(unavailable), 2)
            self.assertTrue(unavailable <= eligible, 'unavailable is not synonymous with excluded')
            self.assertFalse(excluded & eligible)
            self.assertEqual(visible_locations, eligible - unavailable)
            repository = ReadOnlyExplorerSQLiteRepository(str(fixture['db_path']))
            self.assertEqual(set(repository.track_ids()), eligible)
            graph = BuildMoodAxisGraph(repository).execute()
            positioned = {node.track_id for node in graph.positioned}
            unpositioned = {node.track_id for node in graph.unpositioned}
            self.assertEqual(len(positioned), 10)
            self.assertEqual(len(unpositioned), 1)
            self.assertEqual(positioned | unpositioned, eligible)
            self.assertFalse(positioned & unpositioned)
            self.assertTrue(unavailable <= positioned)
            self.assertEqual(len(graph.edges), 9)
            self.assertTrue(all(edge.a in positioned and edge.b in positioned for edge in graph.edges))
            self.assertEqual(graph.metadata['graph_status']['state'], 'ready')

    def test_current_and_historical_evidence_is_valid_linked_and_not_reused(self):
        with public_fixture(self) as fixture:
            with readonly(fixture['db_path']) as db:
                rows = db.execute('''
                    SELECT e.track_id,e.run_id,e.fingerprint,e.evidence_json,e.is_current,r.status,rt.track_id
                    FROM graph_feature_evidence e JOIN runs r ON r.id=e.run_id
                    JOIN run_tracks rt ON rt.run_id=e.run_id
                    ORDER BY e.track_id,e.is_current
                ''').fetchall()
                self.assertEqual(len(rows), 22)
                by_track = {}
                for track, run, fingerprint, raw, current, status, linked_track in rows:
                    self.assertEqual(track, linked_track)
                    self.assertEqual(status, 'completed')
                    payload = json.loads(raw)
                    # Validate all history, not merely the current rows.
                    validate_graph_feature_evidence_payload(track, run, fingerprint, payload)
                    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
                    self.assertEqual(fingerprint, hashlib.sha256(canonical.encode('utf-8')).hexdigest())
                    by_track.setdefault(track, []).append((run, fingerprint, current))
                self.assertEqual(len(by_track), 11)
                for track, history in by_track.items():
                    self.assertEqual([row[2] for row in history], [0, 1])
                    self.assertNotEqual(history[0][0], history[1][0])
                    self.assertNotEqual(history[0][1], history[1][1])
                    latest = db.execute('''SELECT r.id FROM runs r JOIN run_tracks rt ON rt.run_id=r.id
                                           WHERE rt.track_id=? ORDER BY r.rowid DESC LIMIT 1''', (track,)).fetchone()[0]
                    self.assertEqual(history[1][0], latest)

    def test_rich_stages_and_metadata_remain_bounded_and_reader_valid(self):
        with public_fixture(self) as fixture:
            with readonly(fixture['db_path']) as db:
                stages = db.execute('SELECT stage,result FROM stages').fetchall()
                self.assertEqual(len(stages), 120)
                with_windows = 0
                with_summary = 0
                for name, raw in stages:
                    self.assertLess(len(raw.encode('utf-8')), 16 * 1024)
                    stage = stage_from_mapping(json.loads(raw))
                    self.assertEqual(stage.stage, name)
                    self.assertTrue(stage.provenance)
                    self.assertLessEqual(len(stage.windows), 8)
                    if stage.windows:
                        with_windows += 1
                        self.assertIsNotNone(stage.summary)
                    if stage.summary is not None:
                        with_summary += 1
                self.assertGreater(with_windows, 0, 'summary-only smoke is not a rich stage fixture')
                self.assertGreater(with_summary, 0)
                metadata = [dict(json.loads(row[0])) for row in db.execute('SELECT common_json FROM track_metadata')]
                self.assertEqual(len(metadata), 12)
                titles = [row['title'] for row in metadata if isinstance(row.get('title'), str)]
                self.assertGreater(len(titles), len(set(titles)), 'duplicate titles exercise pagination ties')
                encoded = json.dumps(metadata, ensure_ascii=False)
                self.assertTrue(any(ord(character) > 127 for character in encoded), 'public Unicode metadata')
                self.assertTrue(any(character in encoded for character in ('%', '_', '\\\\')), 'unusual literal metadata')

    def test_indexed_graph_integrity_uses_static_count_oracle_not_its_manifest(self):
        with public_fixture(self) as fixture:
            body = fixture['graph_body']
            self.assertIsInstance(body, bytes)
            self.assertLess(len(body), 128 * 1024, 'default fixture is not the 41 MiB browser scenario')

            class FakeResponse:
                status = 200

                def read(self):
                    return body

                def getheader(self, name):
                    return str(len(body)) if name == 'Content-Length' else None

            # Counts are static independently fixed literals; only byte digest
            # is derived from the actual entity. No server-latency inference.
            report = measure_samples(
                [FakeResponse],
                expected={'sha256': hashlib.sha256(body).hexdigest(), 'counts': GRAPH_COUNTS},
                db_fingerprint=lambda: 'test-owned-quiescent-fixture',
            )
            self.assertEqual(report['succeeded'], 1)
            self.assertEqual(report['samples'][0]['outcome'], 'ok')
            self.assertEqual(fixture['manifest']['graph']['counts'], GRAPH_COUNTS)
            self.assertEqual(fixture['manifest']['graph']['source'], 'sqlite-backed')
            payload = json.loads(body)
            self.assertEqual({key: len(payload[key]) for key in GRAPH_COUNTS}, GRAPH_COUNTS)
