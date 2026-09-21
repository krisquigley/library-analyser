import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from music_analyzer.application.dto.models import ModelError
from music_analyzer.infrastructure.models.manifest import load_manifest, validate_manifest
from music_analyzer.infrastructure.models.storage import FileModelStorage


class Transfer:
    def __init__(self, fail=False):
        self.calls = 0
        self.fail = fail

    def download(self, url, destination, expected_size):
        self.calls += 1
        Path(destination).write_bytes(b'abc')
        if self.fail:
            raise ModelError('Interrupted transfer')


class ModelStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'models'
        self.manifest = load_manifest()
        self.model_id = next(iter(self.manifest))
        self.manifest[self.model_id]['size'] = 3
        self.transfer = Transfer()
        self.storage = FileModelStorage(str(self.root), self.manifest, self.transfer)

    def test_missing_install_verify_and_repeat_without_network(self):
        with self.assertRaises(ModelError):
            self.storage.verify(self.model_id)
        self.assertFalse(self.root.exists())
        result = self.storage.install(self.model_id)
        self.assertEqual(result.integrity, 'local-sha256')
        self.assertTrue(result.available)
        self.storage.install(self.model_id)
        self.assertEqual(self.transfer.calls, 1)
        target = self.root / self.model_id
        self.assertTrue((target / 'LICENSE').is_file())
        self.assertTrue((target / 'metadata.json').is_file())
        receipt = json.loads((target / 'receipt.json').read_text())
        self.assertEqual(receipt['sha256'], hashlib.sha256(b'abc').hexdigest())
        self.assertIsNone(receipt['publisher_sha256'])

    def test_corrupt_asset_or_metadata_or_receipt_is_rejected(self):
        for filename in ('model.pb', 'metadata.json', 'receipt.json', 'LICENSE'):
            with self.subTest(filename=filename):
                self.storage.install(self.model_id)
                target = self.root / self.model_id / filename
                original = target.read_bytes()
                target.write_bytes(b'bad')
                with self.assertRaises(ModelError):
                    self.storage.verify(self.model_id)
                with self.assertRaises(ModelError):
                    self.storage.install(self.model_id)
                target.write_bytes(original)

    def test_failed_download_cleans_temp_and_does_not_publish(self):
        self.storage = FileModelStorage(str(self.root), self.manifest, Transfer(fail=True))
        with self.assertRaises(ModelError):
            self.storage.install(self.model_id)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_interrupt_cleans_temp_and_missing_asset_is_rejected(self):
        class Interrupt:
            def download(self, url, destination, expected_size):
                Path(destination).write_bytes(b'a')
                raise KeyboardInterrupt
        interrupted = FileModelStorage(str(self.root), self.manifest, Interrupt())
        with self.assertRaises(KeyboardInterrupt):
            interrupted.install(self.model_id)
        self.assertEqual(list(self.root.iterdir()), [])
        self.storage.install(self.model_id)
        (self.root / self.model_id / 'model.pb').unlink()
        with self.assertRaises(ModelError):
            self.storage.verify(self.model_id)

    def test_publisher_checksum_is_distinguished_when_supplied(self):
        self.manifest[self.model_id]['publisher_sha256'] = hashlib.sha256(b'abc').hexdigest()
        self.assertEqual(self.storage.install(self.model_id).integrity, 'publisher-sha256')

    def test_size_and_publisher_checksum_failure_do_not_publish(self):
        for changes in ({'size': 4}, {'publisher_sha256': '0' * 64}):
            self.manifest[self.model_id].update(changes)
            with self.assertRaises(ModelError):
                self.storage.install(self.model_id)
            self.assertEqual(list(self.root.iterdir()), [])
            self.manifest[self.model_id]['size'] = 3

    def test_invalid_paths_and_symlink_assets_rejected(self):
        with self.assertRaises(ModelError):
            self.storage.install('../escape')
        self.root.write_text('not a directory')
        with self.assertRaises(ModelError):
            self.storage.install(self.model_id)
        self.root.unlink()
        self.storage.install(self.model_id)
        asset = self.root / self.model_id / 'model.pb'
        asset.unlink()
        asset.symlink_to(__file__)
        with self.assertRaises(ModelError):
            self.storage.verify(self.model_id)

    def test_manifest_rejects_malicious_and_invalid_values(self):
        for key, value in [('id', '../escape'), ('url', 'http://example.org/a'),
                           ('url', 'https://evil.example/a'), ('size', -1),
                           ('size', True), ('publisher_sha256', 'guess'),
                           ('metadata', {})]:
            manifest = load_manifest()
            entries = list(manifest.values())
            entries[0][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ModelError):
                validate_manifest(entries)

    def test_official_selection_preserves_class_order_and_versions(self):
        manifest = load_manifest()
        self.assertEqual(len(manifest), 6)
        mood = manifest['mtg_jamendo_moodtheme-discogs-effnet-1']['metadata']
        self.assertEqual(len(mood['classes']), 56)
        self.assertEqual(mood['classes'][:3], ['action', 'adventure', 'advertising'])
        self.assertEqual(manifest['emomusic-msd-musicnn-2']['metadata']['classes'], ['valence', 'arousal'])
