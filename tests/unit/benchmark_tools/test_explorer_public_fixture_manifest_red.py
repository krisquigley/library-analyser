"""RED: public writer-owned v10 fixture manifest and disposable lifecycle.

Only tiny 12-track fixtures run by default. The explicit 5k/20k profiles are
isolated subprocesses with bounded wall time; these are integrity tests, never
host-independent latency assertions. No private catalogue, audio or HTTP runs.
Manifest hashes describe canonical public fixture content, not raw SQLite page
layout, random temp paths, a live WAL snapshot, or measured performance.
"""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from music_analyzer.application.dto.analysis import AnalysisError
from music_analyzer.infrastructure.persistence.analysis import SQLiteAnalysisRepository
from music_explorer.application.use_cases.explorer import BuildMoodAxisGraph
from music_explorer.infrastructure.explorer_readonly import ReadOnlyExplorerSQLiteRepository
from music_explorer.interface_adapters.mood_axis_graph_http import to_indexed_mood_axis_graph_http
from tests.support.explorer_synthetic_fixture_contract import public_fixture
from tools.explorer_interaction_measurement import fingerprint_sqlite_files, inspect_fixture


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')


class PublicFixtureManifestRedTests(unittest.TestCase):
    def test_default_is_tiny_explicitly_public_and_current_schema(self):
        with public_fixture(self) as fixture:
            manifest = fixture['manifest']
            self.assertEqual(manifest['source'], 'public-synthetic-sqlite')
            self.assertEqual(manifest['schema_version'], 10)
            self.assertEqual(manifest['application_id'], 0x4D414E41)
            self.assertEqual(manifest['seed'], 70)
            self.assertEqual(manifest['track_count'], 12)
            self.assertEqual(manifest['history_count'], 2)
            self.assertEqual(inspect_fixture(fixture['db_path'])['counts']['tracks'], 12)

    def test_small_configurable_profile_and_history_are_observed_not_only_labelled(self):
        # 24 is still tiny test work; explicit opt-in acknowledges the default
        # 12-track construction bound, not an expensive performance profile.
        for history_count in (1, 3):
            with self.subTest(history_count=history_count):
                with public_fixture(self, track_count=24, history_count=history_count,
                                    allow_large=True) as fixture:
                    manifest = fixture['manifest']
                    self.assertEqual(manifest['track_count'], 24)
                    self.assertEqual(manifest['history_count'], history_count)
                    self.assertEqual(inspect_fixture(fixture['db_path'])['counts']['tracks'], 24)
                    path = Path(fixture['db_path'])
                    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
                        self.assertEqual(db.execute('SELECT count(*) FROM tracks').fetchone()[0], 24)
                        self.assertEqual(db.execute('SELECT count(*) FROM runs').fetchone()[0],
                                         24 * history_count)
                    self.assertEqual(manifest['counts']['runs'], 24 * history_count)

    def test_same_seed_and_profile_have_identical_manifest_and_graph_bytes(self):
        with public_fixture(self, seed=70) as first:
            first_manifest = first['manifest']
            first_body = first['graph_body']
            first_path = Path(first['db_path'])
            with public_fixture(self, seed=70) as second:
                self.assertNotEqual(first_path, Path(second['db_path']))
                self.assertEqual(first_manifest, second['manifest'])
                self.assertEqual(first_body, second['graph_body'])

    def test_changed_seed_changes_content_not_only_seed_label(self):
        with public_fixture(self, seed=70) as first:
            first_body = first['graph_body']
        with public_fixture(self, seed=71) as second:
            self.assertNotEqual(first_body, second['graph_body'])

    def test_manifest_digest_uses_independent_canonical_json_oracle(self):
        with public_fixture(self) as fixture:
            manifest = fixture['manifest']
            unsigned = {key: value for key, value in manifest.items()
                        if key != 'content_sha256'}
            self.assertEqual(manifest['content_sha256'],
                             hashlib.sha256(canonical_json(unsigned)).hexdigest())
            # Public sanitation is structural: do not merely blacklist a known
            # private handle, since arbitrary input labels must never be echoed.
            self.assertEqual(set(manifest), {
                'source', 'schema_version', 'application_id', 'seed',
                'track_count', 'history_count', 'counts', 'distributions',
                'graph', 'content_sha256',
            })
            self.assertNotIn(str(fixture['db_path']), canonical_json(manifest).decode())
            self._assert_aggregate_tree(manifest['counts'])
            self._assert_aggregate_tree(manifest['distributions'])
            # Literal oracle independently pins the default profile rather
            # than accepting arbitrary/empty aggregate distribution objects.
            self.assertEqual(manifest['distributions']['stages'], {
                'bpm': 24, 'key': 24, 'genres': 24, 'mood': 24, 'energy': 24,
            })
            self.assertEqual(manifest['distributions']['evidence'], {
                'current': 11, 'historical': 11,
            })
            self.assertEqual(manifest['distributions']['positioning'], {
                'positioned': 10, 'unpositioned': 1,
            })

    def _assert_aggregate_tree(self, tree):
        self.assertIsInstance(tree, dict)
        for key, value in tree.items():
            self.assertIsInstance(key, str)
            if isinstance(value, dict):
                self._assert_aggregate_tree(value)
            else:
                self.assertIs(type(value), int, 'distribution leaves are counts, not metadata')
                self.assertGreaterEqual(value, 0)

    def test_sqlite_graph_hash_matches_actual_indexed_v3_reader_bytes(self):
        with public_fixture(self) as fixture:
            graph = fixture['manifest']['graph']
            body = fixture['graph_body']
            self.assertIsInstance(body, bytes)
            self.assertEqual(set(graph), {'source', 'sha256', 'body_bytes', 'counts'})
            self.assertEqual(graph['source'], 'sqlite-backed')
            self.assertEqual(graph['sha256'], hashlib.sha256(body).hexdigest())
            self.assertEqual(graph['body_bytes'], len(body))
            decoded = json.loads(body)
            self.assertEqual(graph['counts'], {
                key: len(decoded[key]) for key in ('nodes', 'links', 'unpositioned')
            })
            repository = ReadOnlyExplorerSQLiteRepository(str(fixture['db_path']))
            actual = to_indexed_mood_axis_graph_http(BuildMoodAxisGraph(repository).execute())
            self.assertEqual(body, canonical_json(actual),
                             'not a browser-only fabricated graph labelled SQLite-backed')

    def test_reopen_read_only_reader_and_inspection_preserve_main_and_wal(self):
        with public_fixture(self) as fixture:
            path = Path(fixture['db_path'])
            before = fingerprint_sqlite_files(path)
            for _ in range(2):
                report = inspect_fixture(path)
                self.assertEqual(report['integrity_check'], 'ok')
                self.assertEqual(report['foreign_key_check'], [])
                repository = ReadOnlyExplorerSQLiteRepository(str(path))
                repository.metadata()
                repository.list_track_summaries(limit=2)
                BuildMoodAxisGraph(repository).execute()
            with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
                db.execute('PRAGMA query_only=ON')
                with self.assertRaises(sqlite3.OperationalError):
                    db.execute('DELETE FROM tracks')
            self.assertEqual(before, fingerprint_sqlite_files(path))

    def test_fixture_accepts_symlinked_temporary_directory_ancestry(self):
        with tempfile.TemporaryDirectory(prefix='synthetic-temp-ancestry-') as scratch:
            real = Path(scratch).resolve() / 'real-temp'
            real.mkdir()
            alias = Path(scratch) / 'linked-temp'
            alias.symlink_to(real, target_is_directory=True)
            with patch.object(tempfile, 'tempdir', str(alias)):
                with public_fixture(self) as fixture:
                    path = Path(fixture['db_path'])
                    self.assertEqual(path, path.resolve())
                    self.assertEqual(path.parent.parent, real)
                    self.assertEqual(fixture['manifest']['counts']['tracks'], 12)
                    self.assertEqual(inspect_fixture(path)['integrity_check'], 'ok')
                self.assertFalse(path.parent.exists())
            self.assertEqual(list(real.iterdir()), [])

    def test_external_symlink_to_synthetic_private_database_is_not_a_public_fixture(self):
        # Every path and byte here is test-owned; no actual private data is accessed.
        with tempfile.TemporaryDirectory(prefix='synthetic-private-target-') as scratch:
            private = Path(scratch).resolve() / 'synthetic-private.sqlite'
            with closing(sqlite3.connect(private)) as db, db:
                db.execute('CREATE TABLE sentinel(value TEXT)')
                db.execute("INSERT INTO sentinel VALUES('synthetic-only')")
            before = fingerprint_sqlite_files(private)
            alias = private.parent / 'apparently-public.sqlite'
            alias.symlink_to(private)
            parent_alias = private.parent / 'apparently-public-directory'
            parent_alias.symlink_to(private.parent, target_is_directory=True)
            for supplied_path in (alias, parent_alias / private.name):
                with self.subTest(supplied_path=supplied_path):
                    with self.assertRaisesRegex(AnalysisError, 'symlink database path'):
                        SQLiteAnalysisRepository(str(supplied_path))
            with patch('tools.explorer_synthetic_fixture.tempfile.TemporaryDirectory') as temporary:
                for keyword in ('path', 'db_path', 'catalogue_path'):
                    with self.subTest(keyword=keyword), self.assertRaises(TypeError):
                        with public_fixture(self, **{keyword: alias}):
                            self.fail('external database paths must not be accepted')
                temporary.assert_not_called()
            self.assertEqual(before, fingerprint_sqlite_files(private))
            self.assertTrue(alias.is_symlink())
            self.assertTrue(parent_alias.is_symlink())

    def test_symlinked_temp_root_cleans_sidecars_after_construction_failure(self):
        class ConstructionFailure(Exception):
            pass

        failed_paths = []

        def fail_population(path, *options):
            failed_paths.append(path)
            for suffix in ('-wal', '-shm', '-journal'):
                Path(str(path) + suffix).write_bytes(b'synthetic-only')
            raise ConstructionFailure('synthetic construction failure')

        with tempfile.TemporaryDirectory(prefix='synthetic-temp-failure-') as scratch:
            real = Path(scratch).resolve() / 'real-temp'
            real.mkdir()
            alias = Path(scratch) / 'linked-temp'
            alias.symlink_to(real, target_is_directory=True)
            with patch.object(tempfile, 'tempdir', str(alias)), patch(
                    'tools.explorer_synthetic_fixture._populate', side_effect=fail_population):
                with self.assertRaisesRegex(ConstructionFailure, 'synthetic construction failure'):
                    with public_fixture(self):
                        self.fail('construction failure must propagate before yielding')
            self.assertEqual(len(failed_paths), 1)
            path = failed_paths[0]
            self.assertFalse(path.parent.exists())
            for suffix in ('', '-wal', '-shm', '-journal'):
                self.assertFalse(Path(str(path) + suffix).exists())
            self.assertEqual(list(real.iterdir()), [])

    def test_context_cleans_owned_directory_and_sqlite_sidecars_on_success(self):
        with public_fixture(self) as fixture:
            path = Path(fixture['db_path'])
            root = path.parent
            self.assertTrue(path.is_file())
            self.assertTrue(root.is_dir())
        self.assertFalse(root.exists(), 'owned temporary root and all artifacts must disappear')
        for suffix in ('', '-wal', '-shm', '-journal'):
            self.assertFalse(Path(str(path) + suffix).exists())

    def test_context_cleans_on_consumer_exception_and_does_not_swallow_it(self):
        class ConsumerFailure(Exception):
            pass
        context = public_fixture(self)  # Availability assertion precedes consumer failure expectation.
        with self.assertRaises(ConsumerFailure):
            with context as fixture:
                path = Path(fixture['db_path'])
                root = path.parent
                raise ConsumerFailure('public test failure')
        self.assertFalse(root.exists())

    def test_invalid_sizes_types_seed_and_history_are_rejected_with_safe_message(self):
        invalid_options = [
            {'track_count': value} for value in (True, '12', 0, -1, 11, 20001)
        ] + [
            {'seed': value} for value in (True, '70', -1, 2 ** 32)
        ] + [
            {'history_count': value} for value in (True, '2', 0, -1, 4)
        ] + [
            {'allow_large': value} for value in (0, 1, 'yes', None)
        ]
        for options in invalid_options:
            with self.subTest(options=options):
                with self.assertRaisesRegex(ValueError, '^Invalid public synthetic fixture options$'):
                    with public_fixture(self, **options):
                        self.fail('invalid options must fail before yielding a fixture')

    def test_expensive_profiles_require_explicit_opt_in(self):
        for count in (5000, 20000):
            with self.subTest(track_count=count):
                with self.assertRaisesRegex(ValueError, '^Large synthetic fixture requires explicit opt-in$'):
                    with public_fixture(self, track_count=count):
                        self.fail('large build unexpectedly ran without opt-in')

    @unittest.skipUnless(os.environ.get('RUN_EXPLORER_PUBLIC_FIXTURE_LARGE') == '1',
                         '5k/20k integrity profiles require explicit opt-in')
    def test_opt_in_5k_and_20k_profiles_are_isolated_and_bounded(self):
        for count in (5000, 20000):
            with self.subTest(track_count=count):
                script = '''
import json
import unittest
from tests.support.explorer_synthetic_fixture_contract import public_fixture
from tools.explorer_interaction_measurement import inspect_fixture
with public_fixture(unittest.TestCase(), track_count=COUNT, allow_large=True) as fixture:
    manifest = fixture['manifest']
    report = inspect_fixture(fixture['db_path'])
    assert report['counts']['tracks'] == COUNT
    assert report['schema_version'] == 10
    assert report['integrity_check'] == 'ok'
    assert report['foreign_key_check'] == []
    assert manifest['track_count'] == COUNT
    assert manifest['history_count'] == 2
    print(json.dumps({'tracks': COUNT, 'integrity': 'ok'}, sort_keys=True))
'''.replace('COUNT', str(count))
                with tempfile.TemporaryDirectory(prefix='explorer-public-profile-') as scratch:
                    try:
                        completed = subprocess.run(
                            [sys.executable, '-B', '-c', script], capture_output=True,
                            text=True, timeout=300, check=False,
                            env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1',
                                 'TMPDIR': scratch, 'TEMP': scratch, 'TMP': scratch},
                        )
                    except subprocess.TimeoutExpired:
                        self.fail('public synthetic integrity profile exceeded 300-second safety bound')
                self.assertEqual(completed.returncode, 0,
                                 'isolated public fixture contract failed:\n' + completed.stderr[-4000:])
                self.assertEqual(json.loads(completed.stdout), {'tracks': count, 'integrity': 'ok'})
