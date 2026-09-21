import json
import tempfile
import unittest
from pathlib import Path

from music_analyzer.application.use_cases.projection_artifacts import ProjectionArtifactError
from music_analyzer.infrastructure.filesystem.projection_artifacts import FileProjectionArtifactStore


VALID = {
    'artifact_version': 'journey-projection-artifact-v1',
    'fingerprint': 'abc',
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

    def test_corrupt_load_is_actionable(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'projection.json'
            path.write_text('{bad json')
            with self.assertRaisesRegex(ProjectionArtifactError, 'corrupt'):
                FileProjectionArtifactStore(path).load()

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


if __name__ == '__main__':
    unittest.main()
