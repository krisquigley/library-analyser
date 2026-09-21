import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from music_analyzer.application.use_cases.projection_artifacts import ProjectionArtifactError
from music_analyzer.frameworks.cli.main import main
from music_analyzer.infrastructure.filesystem.projection_artifacts import FileProjectionArtifactStore
from music_analyzer.infrastructure.persistence.analysis import APPLICATION_ID


VALID = {
    'artifact_version': 'journey-projection-artifact-v1',
    'fingerprint_version': 'projection-fingerprint-v1',
    'fingerprint': 'abc',
    'policy_versions': {
        'artifact_version': 'journey-projection-artifact-v1',
        'projection_policy_version': 'anchor-distance-projection-v1',
        'projection_feature_contract_version': 'projection-features-v1',
        'projection_fingerprint_version': 'projection-fingerprint-v1',
        'projection_refresh_policy_version': 'fixed-transform-refresh-v1',
        'neighbour_policy_version': 'endpoint-local-exact-top-k-neighbours-v2',
        'distance_policy_version': 'symmetric-feature-distance-v1',
        'transform_recipe_version': 'anchor-distance-projection-v1',
    },
    'transform': {'policy_version': 'anchor-distance-projection-v1'},
    'tracks': ({'track_id': 'a', 'x': 0.0, 'y': None, 'layout_state': 'partial', 'missing_groups': (), 'missing_reasons': ()},),
    'edges': (),
    'resource_limits': {'k': 10},
}


class FileProjectionArtifactStoreTests(unittest.TestCase):
    def test_replace_writes_valid_json_outside_source_db(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db = root / 'analysis.sqlite'
            db.write_text('source-db')
            artifact = root / 'artifacts' / 'projection.json'
            store = FileProjectionArtifactStore(artifact, source_database_path=db)

            store.replace(VALID)

            self.assertEqual(db.read_text(), 'source-db')
            loaded = store.load()
            self.assertEqual(loaded['artifact_version'], 'journey-projection-artifact-v1')
            self.assertNotIn('transform_object', loaded)

    def test_rejects_artifact_path_equal_to_source_database(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            path.write_text('source-db')
            with self.assertRaisesRegex(ProjectionArtifactError, 'safe artifact location'):
                FileProjectionArtifactStore(path, source_database_path=path).replace(VALID)

    def test_rejects_known_audio_location_and_preserves_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            audio = root / 'song.flac'
            audio.write_bytes(b'ORIGINAL_AUDIO_BYTES')
            store = FileProjectionArtifactStore(root / 'song.flac', protected_audio_paths=(audio,))

            with self.assertRaisesRegex(ProjectionArtifactError, 'known catalogue audio'):
                store.replace(VALID)
            self.assertEqual(audio.read_bytes(), b'ORIGINAL_AUDIO_BYTES')

    def test_rejects_source_database_sidecar_path_and_preserves_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db = root / 'analysis.sqlite'
            db.write_text('source-db')
            sidecar = Path(str(db) + '-wal')
            sidecar.write_text('source-db-wal')
            store = FileProjectionArtifactStore(sidecar, source_database_path=db)

            with self.assertRaisesRegex(ProjectionArtifactError, 'source database'):
                store.replace(VALID)
            self.assertEqual(sidecar.read_text(), 'source-db-wal')

    def test_rejects_audio_aliases_symlinks_and_hardlinks(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            audio = root / 'song.flac'
            audio.write_bytes(b'ORIGINAL_AUDIO_BYTES')
            hardlink = root / 'alias.flac'
            hardlink.hardlink_to(audio)
            symlink = root / 'link.flac'
            symlink.symlink_to(audio)

            for target in (hardlink, symlink):
                with self.subTest(target=target.name):
                    store = FileProjectionArtifactStore(target, protected_audio_paths=(audio,))
                    with self.assertRaisesRegex(ProjectionArtifactError, 'known catalogue audio'):
                        store.replace(VALID)
                    self.assertEqual(audio.read_bytes(), b'ORIGINAL_AUDIO_BYTES')

    def test_cli_prepare_projection_rejects_catalogue_audio_path_and_preserves_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db_path = root / 'analysis.sqlite'
            audio = root / 'song.flac'
            audio.write_bytes(b'ORIGINAL_AUDIO_BYTES')
            _write_projection_ready_database(db_path, audio)

            exit_code = main(['--database', str(db_path), 'prepare-projection', '--artifact', str(audio), '--json'])

            self.assertEqual(exit_code, 1)
            self.assertEqual(audio.read_bytes(), b'ORIGINAL_AUDIO_BYTES')

    def test_cli_prepare_projection_human_success_reports_committed_durability_warning(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db_path = root / 'analysis.sqlite'
            audio = root / 'song.flac'
            artifact = root / 'projection.json'
            audio.write_bytes(b'ORIGINAL_AUDIO_BYTES')
            _write_projection_ready_database(db_path, audio)
            stdout = io.StringIO()

            with patch('music_analyzer.infrastructure.filesystem.projection_artifacts._fsync_directory', side_effect=OSError('simulated directory fsync failure')):
                with redirect_stdout(stdout):
                    exit_code = main(['--database', str(db_path), 'prepare-projection', '--artifact', str(artifact)])

            output = stdout.getvalue()
            self.assertEqual(exit_code, 0)
            self.assertIn('Prepared 1 tracks', output)
            self.assertIn('durability', output)
            self.assertIn('committed', output)
            self.assertNotIn('rolled back', output.lower())
            self.assertNotIn('preserved prior', output.lower())
            self.assertTrue(artifact.exists())

    def test_corrupt_load_is_actionable(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'projection.json'
            path.write_text('{bad json')
            with self.assertRaisesRegex(ProjectionArtifactError, 'corrupt'):
                FileProjectionArtifactStore(path).load()


    def test_directory_fsync_after_replace_reports_committed_warning(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'projection.json'
            store = FileProjectionArtifactStore(path)
            store.replace(VALID)
            replacement = dict(VALID)
            replacement['fingerprint'] = 'new-fingerprint'

            with patch('music_analyzer.infrastructure.filesystem.projection_artifacts._fsync_directory', side_effect=OSError('simulated directory fsync failure')):
                outcome = store.replace(replacement)

            self.assertEqual(path.read_text(), json.dumps(replacement, sort_keys=True, separators=(',', ':')))
            self.assertTrue(outcome.committed)
            self.assertIn('durability', outcome.warning)

    def test_replace_failure_before_commit_preserves_prior_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'projection.json'
            store = FileProjectionArtifactStore(path)
            store.replace(VALID)
            prior = path.read_bytes()
            replacement = dict(VALID)
            replacement['fingerprint'] = 'new-fingerprint'

            with patch('music_analyzer.infrastructure.filesystem.projection_artifacts.os.replace', side_effect=OSError('simulated replace failure')):
                with self.assertRaises(OSError):
                    store.replace(replacement)

            self.assertEqual(path.read_bytes(), prior)

    def test_failed_replacement_preserves_prior_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'projection.json'
            store = FileProjectionArtifactStore(path)
            store.replace(VALID)
            prior = path.read_bytes()
            invalid = dict(VALID)
            invalid['edges'] = ({'a': 'a', 'b': 'missing', 'distance': 0.1, 'supported_group_count': 1},)
            with self.assertRaises(ProjectionArtifactError):
                store.replace(invalid)
            self.assertEqual(path.read_bytes(), prior)


def _write_projection_ready_database(db_path, audio_path):
    tid = 'sha256:' + ('1' * 64)
    with sqlite3.connect(db_path) as db:
        db.executescript(f"""
            PRAGMA application_id={APPLICATION_ID};
            PRAGMA user_version=4;
            CREATE TABLE tracks(id TEXT PRIMARY KEY, sha256 TEXT NOT NULL UNIQUE, size INTEGER NOT NULL);
            CREATE TABLE locations(path TEXT PRIMARY KEY, track_id TEXT NOT NULL REFERENCES tracks(id), mtime_ns INTEGER NOT NULL, format TEXT NOT NULL, available INTEGER NOT NULL CHECK(available IN (0,1)));
            CREATE TABLE scan_roots(root TEXT NOT NULL, path TEXT NOT NULL REFERENCES locations(path), PRIMARY KEY(root,path));
            CREATE TABLE runs(id TEXT PRIMARY KEY, location TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('running','completed','failed','interrupted')), detail TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE stages(run_id TEXT NOT NULL REFERENCES runs(id), stage TEXT NOT NULL, result TEXT NOT NULL, PRIMARY KEY(run_id,stage));
            CREATE TABLE batch_jobs(track_id TEXT PRIMARY KEY REFERENCES tracks(id), fingerprint TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('pending','running','completed','failed')), attempts INTEGER NOT NULL CHECK(attempts >= 0), run_id TEXT, detail TEXT NOT NULL);
            CREATE TABLE run_tracks(run_id TEXT PRIMARY KEY REFERENCES runs(id), track_id TEXT NOT NULL REFERENCES tracks(id));
            CREATE TABLE overrides(track_id TEXT NOT NULL REFERENCES tracks(id), field TEXT NOT NULL, value TEXT NOT NULL, PRIMARY KEY(track_id,field));
        """)
        db.execute('INSERT INTO tracks VALUES(?,?,?)', (tid, '1' * 64, 123))
        db.execute('INSERT INTO locations VALUES(?,?,?,?,?)', (str(audio_path), tid, 1, 'flac', 1))
        db.execute('INSERT INTO runs VALUES(?,?,?,?,?)', ('run-1', str(audio_path), 'completed', '', 'now'))
        db.execute('INSERT INTO run_tracks VALUES(?,?)', ('run-1', tid))
        db.execute('INSERT INTO stages VALUES(?,?,?)', ('run-1', 'bpm', json.dumps({'stage': 'bpm', 'provenance': [], 'uncertainty': '', 'values': [['bpm', 120.0]]})))
        db.execute('INSERT INTO stages VALUES(?,?,?)', ('run-1', 'energy', json.dumps({'stage': 'energy', 'provenance': [], 'uncertainty': '', 'summary': {'labels': ['arousal'], 'mean': [0.0], 'minimum': [0.0], 'maximum': [0.0], 'coverage': 1.0, 'provisional': False, 'uncertainty': ''}})))


if __name__ == '__main__':
    unittest.main()
