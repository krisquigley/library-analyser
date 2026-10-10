"""PR4c RED: public HTTP fixture provenance, bound plans and read-only bytes.

The proposed outward tool is deliberately absent. Each contract checks for it
before setup, so RED means a missing diagnostic, not an import/setup error.
Only writer-generated twelve-track disposable catalogues are used. No private
paths, migrations, indexes, ANALYZE, browser payload or speed assertions.
"""
from contextlib import closing, contextmanager
import hashlib
import importlib
import importlib.util
import json
import math
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools.explorer_fixture_inspection import fingerprint_sqlite_files
from tools.explorer_synthetic_fixture import public_synthetic_fixture


MODULE = 'tools.explorer_http_diagnostic'


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')


class PublicHTTPDiagnosticProvenanceRedTests(unittest.TestCase):
    def tool(self):
        self.assertIsNotNone(
            importlib.util.find_spec(MODULE),
            'PR4c missing public HTTP diagnostic tool: tools.explorer_http_diagnostic')
        return importlib.import_module(MODULE)

    def run_tool(self, tool, **options):
        return tool.run_public_http_diagnostic(
            sample_count=1, timeout_seconds=5.0, **options)

    def test_report_carries_exact_writer_fixture_manifest_not_browser_graph_provenance(self):
        tool = self.tool()
        with public_synthetic_fixture() as independent:
            expected = independent['manifest']
        report = self.run_tool(tool)
        self.assertEqual(report['fixture_manifest'], expected)
        manifest = report['fixture_manifest']
        unsigned = {key: value for key, value in manifest.items()
                    if key != 'content_sha256'}
        self.assertEqual(manifest['content_sha256'],
                         hashlib.sha256(canonical_json(unsigned)).hexdigest())
        self.assertEqual(manifest['source'], 'public-synthetic-sqlite')
        self.assertEqual(manifest['schema_version'], 10)
        self.assertEqual(manifest['counts']['tracks'], 12)
        self.assertEqual(manifest['counts']['runs'], 24)
        self.assertEqual(manifest['graph']['source'], 'sqlite-backed')
        self.assertEqual(manifest['distributions']['evidence'],
                         {'current': 11, 'historical': 11})
        # This HTTP slice must not claim browser parse/paint or 41MB evidence.
        self.assertNotIn('browser-only', canonical_json(manifest).decode())

    def test_changed_profile_provenance_matches_generated_content(self):
        tool = self.tool()
        options = {'track_count': 12, 'seed': 71, 'history_count': 1}
        with public_synthetic_fixture(**options) as independent:
            expected = independent['manifest']
        report = self.run_tool(tool, **options)
        self.assertEqual(report['fixture_manifest'], expected)
        self.assertEqual(report['fixture_manifest']['counts']['runs'], 12)
        self.assertEqual(report['fixture_manifest']['counts']['historical_graph_feature_evidence'], 0)

    @contextmanager
    def observed_fixture(self, observations, *, wal=False, **options):
        """Observe adapter SQL after construction; never instrument the writer.

        The held writer creates committed WAL before diagnostics and stays idle
        until after fingerprint comparison. Closing it earlier could checkpoint
        and falsely make a read-only diagnostic look like a writer.
        """
        with public_synthetic_fixture(**options) as fixture:
            path = Path(fixture['db_path'])
            writer = sqlite3.connect(path) if wal else None
            try:
                if writer is not None:
                    writer.execute('PRAGMA journal_mode=WAL')
                    writer.execute('PRAGMA wal_autocheckpoint=0')
                    # Test-owned, semantically unchanged write solely creates WAL.
                    writer.execute('UPDATE tracks SET size=size')
                    writer.commit()
                    self.assertTrue(Path(str(path) + '-wal').is_file())
                observations['before'] = fingerprint_sqlite_files(path)
                observations['path'] = path
                observations['manifest'] = fixture['manifest']
                observations['executed'] = []
                observations['connections'] = []
                with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
                    observations['indexes'] = [
                        {'name': name, 'sql': sql} for name, sql in db.execute(
                            "SELECT name,sql FROM sqlite_master WHERE type='index' ORDER BY name")]
                connect = sqlite3.connect

                class ObservedConnection(sqlite3.Connection):
                    def execute(connection, sql, parameters=()):
                        cursor = super().execute(sql, parameters)
                        normalized = sql.lstrip().upper()
                        if normalized.startswith(('SELECT', 'WITH')):
                            # Use the same connection: repository metadata UDFs
                            # and actual bindings, not a hand-written facsimile.
                            rows = sqlite3.Connection.execute(
                                connection, 'EXPLAIN QUERY PLAN ' + sql,
                                parameters).fetchall()
                            query_only = sqlite3.Connection.execute(
                                connection, 'PRAGMA query_only').fetchone()[0]
                            observations['executed'].append({
                                'sql': sql, 'parameters': list(parameters),
                                'rows': [list(row) for row in rows],
                                'query_only': query_only})
                        return cursor

                def observe_connect(database, *args, **kwargs):
                    observations['connections'].append(str(database))
                    kwargs['factory'] = ObservedConnection
                    return connect(database, *args, **kwargs)

                with patch.object(sqlite3, 'connect', side_effect=observe_connect):
                    yield fixture
                observations['after'] = fingerprint_sqlite_files(path)
            finally:
                if writer is not None:
                    writer.close()

    def run_observed(self, tool, *, wal=False):
        observations = {}

        @contextmanager
        def fixture_factory(**options):
            with self.observed_fixture(observations, wal=wal, **options) as fixture:
                yield fixture

        # Fixture generation is an outward seam, not a new private DB input.
        report = self.run_tool(tool, fixture_factory=fixture_factory)
        self.assertFalse(observations['path'].parent.exists())
        return report, observations

    def test_explain_uses_actual_bound_summary_and_selected_queries_with_udfs(self):
        tool = self.tool()
        report, observed = self.run_observed(tool)
        sql_report = report['sqlite']
        self.assertEqual(sql_report['version'], sqlite3.sqlite_version)
        self.assertEqual(sorted(sql_report['indexes'], key=lambda item: item['name']),
                         observed['indexes'])
        required = {
            'summary_count', 'summary_page', 'selected_track',
            'selected_locations', 'selected_latest_run',
        }
        plans = sql_report['plans']
        self.assertTrue(required.issubset({plan['operation'] for plan in plans}))
        for plan in plans:
            with self.subTest(operation=plan['operation']):
                matches = [query for query in observed['executed']
                           if query['sql'] == plan['sql']
                           and query['parameters'] == plan['parameters']]
                self.assertTrue(matches, 'reported SQL/bindings must actually execute')
                self.assertTrue(all(query['query_only'] == 1 for query in matches))
                self.assertTrue(plan['rows'], 'a query name is not EXPLAIN evidence')
                self.assertIn(plan['rows'], [query['rows'] for query in matches])
        by_operation = {plan['operation']: plan for plan in plans}
        # Labels alone must not allow an unrelated validation SELECT to masquerade
        # as the requested summary or selected lookup plan.
        expected_fragments = {
            'summary_count': ('SELECT count(*) FROM (', 'FROM summary'),
            'summary_page': ('FROM summary', 'ORDER BY', 'LIMIT ?'),
            'selected_track': ('SELECT id,sha256,size FROM tracks WHERE id=?',),
            'selected_locations': ('FROM locations WHERE track_id=?', 'available=1'),
            'selected_latest_run': ('JOIN run_tracks', 'WHERE t.track_id=?', 'LIMIT 1'),
        }
        for operation, fragments in expected_fragments.items():
            compact = ' '.join(by_operation[operation]['sql'].split())
            for fragment in fragments:
                self.assertIn(fragment, compact)
        # A count/page plan with literalized/omitted bound filters is insufficient.
        for operation in ('summary_count', 'summary_page'):
            self.assertIn('_explorer_summary_', by_operation[operation]['sql'])
            self.assertIn('?', by_operation[operation]['sql'])
            self.assertTrue(by_operation[operation]['parameters'])
        for operation in ('selected_track', 'selected_locations', 'selected_latest_run'):
            self.assertIn('?', by_operation[operation]['sql'])
            self.assertEqual(len(by_operation[operation]['parameters']), 1)
        self.assertTrue(observed['connections'])
        for uri in observed['connections']:
            self.assertIn('mode=ro', uri)
            self.assertNotIn('immutable=1', uri)

    def test_absent_wal_is_explicit_and_main_bytes_are_preserved(self):
        tool = self.tool()
        report, observed = self.run_observed(tool)
        self.assertIsNone(observed['before']['wal_sha256'])
        self.assert_readonly_report(report, observed)

    def test_committed_wal_is_fingerprinted_without_checkpoint_or_main_changes(self):
        tool = self.tool()
        report, observed = self.run_observed(tool, wal=True)
        self.assertIsNotNone(observed['before']['wal_sha256'])
        self.assert_readonly_report(report, observed)

    def test_server_phases_are_measured_or_explicitly_unavailable_not_inferred_from_http(self):
        tool = self.tool()
        report = self.run_tool(tool)
        for name in ('validation', 'membership', 'selected_sql', 'stage_parse',
                     'mapping', 'serialization'):
            with self.subTest(phase=name):
                phase = report['phases'][name]
                self.assertIn(phase['status'], ('measured', 'unavailable'))
                if phase['status'] == 'unavailable':
                    self.assertIsInstance(phase['reason'], str)
                    self.assertTrue(phase['reason'].strip())
                    self.assertNotIn('samples_ms', phase)
                else:
                    self.assertTrue(phase['samples_ms'])
                    for duration in phase['samples_ms']:
                        self.assertIsNot(type(duration), bool)
                        self.assertIsInstance(duration, (int, float))
                        self.assertTrue(math.isfinite(duration))
                        self.assertGreaterEqual(duration, 0)
                    # A phase measurement must identify its clock/source, not
                    # relabel whole-request elapsed time as SQL/validation time.
                    self.assertTrue(phase['source'].strip())

    def test_corrupt_historical_evidence_remains_rejected_without_readonly_changes(self):
        tool = self.tool()
        observed = {}

        @contextmanager
        def corrupt_fixture(**options):
            with public_synthetic_fixture(**options) as fixture:
                path = Path(fixture['db_path'])
                with closing(sqlite3.connect(path)) as db, db:
                    # Historical evidence is not the selected latest run. The
                    # diagnostic must retain full reader trust validation.
                    db.execute("UPDATE graph_feature_evidence SET fingerprint=? "
                               "WHERE rowid=(SELECT max(rowid) FROM graph_feature_evidence "
                               "WHERE is_current=0)", ('0' * 64,))
                observed['before'] = fingerprint_sqlite_files(path)
                yield fixture
                observed['after'] = fingerprint_sqlite_files(path)
                observed['path'] = path

        report = self.run_tool(tool, fixture_factory=corrupt_fixture)
        self.assertEqual(observed['before'], observed['after'])
        self.assertFalse(observed['path'].parent.exists())
        rejected = [request for request in report['requests']
                    if request['status'] is not None and request['status'] >= 400]
        self.assertTrue(rejected, 'unrelated corrupt history must not become a successful baseline')
        self.assertTrue(all(request['outcome'] == 'http_error' for request in rejected))
        self.assertGreater(sum(profile['failures'].get('http_error', 0)
                               for profile in report['profiles'].values()), 0)
        self.assertEqual(report['readonly']['before'], observed['before'])
        self.assertEqual(report['readonly']['after'], observed['after'])
        self.assertIs(report['readonly']['unchanged'], True)

    @unittest.skipUnless(os.environ.get('RUN_EXPLORER_HTTP_DIAGNOSTIC_LARGE') == '1',
                         '5k/20k HTTP integrity profiles require explicit opt-in')
    def test_opt_in_large_profiles_match_fresh_deterministic_writer_manifests(self):
        self.tool()  # Missing-tool RED precedes expensive subprocess construction.
        for count in (5000, 20000):
            with self.subTest(track_count=count):
                script = '''
import json
from tools.explorer_synthetic_fixture import public_synthetic_fixture
from tools.explorer_http_diagnostic import run_public_http_diagnostic
options = dict(track_count=COUNT, seed=70, history_count=2, allow_large=True)
with public_synthetic_fixture(**options) as first:
    expected = first['manifest']
with public_synthetic_fixture(**options) as second:
    assert second['manifest'] == expected
report = run_public_http_diagnostic(**options, sample_count=1, timeout_seconds=60.0)
assert report['fixture_manifest'] == expected
assert expected['counts']['tracks'] == COUNT
assert expected['schema_version'] == 10
assert report['readonly']['unchanged'] is True
assert report['requests'] and all(r['status'] == 200 for r in report['requests'])
print(json.dumps({'tracks': COUNT, 'manifest': expected['content_sha256']}))
'''.replace('COUNT', str(count))
                with tempfile.TemporaryDirectory(prefix='explorer-http-large-contract-') as scratch:
                    child = subprocess.Popen(
                        [sys.executable, '-B', '-c', script],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                        start_new_session=True,
                        env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1',
                             'TMPDIR': scratch, 'TEMP': scratch, 'TMP': scratch})
                    try:
                        stdout, stderr = child.communicate(timeout=900)
                    except subprocess.TimeoutExpired:
                        self.fail('public HTTP integrity profile exceeded 900-second safety bound')
                    finally:
                        if child.poll() is None:
                            try:
                                os.killpg(child.pid, signal.SIGKILL)
                            except ProcessLookupError:
                                pass  # Child exited between poll and group kill.
                            child.communicate()
                self.assertEqual(child.returncode, 0, stderr[-4000:])
                result = json.loads(stdout)
                self.assertEqual(result['tracks'], count)
                self.assertRegex(result['manifest'], r'^[0-9a-f]{64}$')

    def assert_readonly_report(self, report, observed):
        readonly = report['readonly']
        self.assertEqual(observed['before'], observed['after'])
        self.assertEqual(readonly['before'], observed['before'])
        self.assertEqual(readonly['after'], observed['after'])
        self.assertIs(readonly['unchanged'], True)
        self.assertEqual(readonly['context'], 'caller-owned-quiescent')
        self.assertEqual(report['fixture_manifest'], observed['manifest'])
        # Publish public bound values, never the random scratch filesystem path.
        self.assertNotIn(str(observed['path']), canonical_json(report).decode())


if __name__ == '__main__':
    unittest.main()
