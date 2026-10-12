"""Positive controls for existing SQLite and trusted-duration normalization."""
from pathlib import Path
import tempfile
import unittest

from music_analyzer.application.dto.catalogue import Inventory, ScannedFile, TrackMetadata
from music_analyzer.domain.catalogue import FileIdentity
from music_analyzer.infrastructure.persistence.analysis import SQLiteAnalysisRepository
from music_analyzer.infrastructure.persistence.explorer_readonly import ReadOnlyExplorerSQLiteRepository


class CatalogueNumericCompatibilityTests(unittest.TestCase):
    def test_integral_and_boolean_sizes_and_trusted_duration_text_remain_readable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'catalogue.sqlite')
            writer = SQLiteAnalysisRepository(path)
            files = tuple(
                ScannedFile(
                    f'/synthetic/{suffix}.flac', FileIdentity(suffix * 64, size), 0, 'flac',
                    TrackMetadata(duration_seconds='180', duration_source='mutagen'),
                )
                for suffix, size in (('a', 123.0), ('b', True))
            )
            self.assertEqual(writer.register(Inventory('/synthetic', files, (), True)), ())
            reopened = SQLiteAnalysisRepository(path)
            reader = ReadOnlyExplorerSQLiteRepository(path)
            expected_ids = tuple(file.identity.track_id for file in files)
            self.assertEqual(tuple(reopened.track_ids()), expected_ids)
            self.assertEqual(reader.track_ids(), expected_ids)
            for file, expected_size in zip(files, (123, 1)):
                for repository in (reopened, reader):
                    with self.subTest(repository=type(repository).__name__, size=file.identity.size):
                        track = repository.read_track(file.identity.track_id)
                        self.assertEqual(track.size, expected_size)
                        self.assertIsInstance(track.size, int)
                        self.assertEqual(track.metadata.duration_seconds, 180.0)
                        self.assertEqual(track.metadata.duration_source, 'mutagen')
