"""Writer-origin metadata shape regressions, without changing reader policy.

The scanner emits common pairs with text or multiple text values, tag pairs
with multiple text values, and textual warnings. A mapping in place of common
pairs and a scalar string in place of tag values are not that contract. Reject
at public register, not on a later reader call or by stringifying malformed data.
"""
import sqlite3
import sys
import tempfile
import types
import unittest
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from music_analyzer.application.dto.analysis import AnalysisError
from music_analyzer.application.dto.catalogue import Inventory, ScannedFile, TrackMetadata
from music_analyzer.application.use_cases.scan_library import ScanLibrary
from music_analyzer.domain.catalogue import FileIdentity
from music_analyzer.domain.projection import ProjectionEdge
from music_analyzer.infrastructure.audio.metadata import MutagenMetadataReader
from music_analyzer.infrastructure.filesystem.inventory import LocalInventory
from music_analyzer.infrastructure.persistence.analysis import SQLiteAnalysisRepository
from music_analyzer.infrastructure.persistence.explorer_readonly import ReadOnlyExplorerSQLiteRepository


class CatalogueMetadataWriterShapeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name) / 'music'
        self.root.mkdir()
        self.path = Path(self.directory.name) / 'analysis.sqlite'
        self.writer = SQLiteAnalysisRepository(str(self.path))

    def _snapshot(self):
        # Independent read-only observation includes all persisted values: track
        # metadata/audio, locations, scan roots, current graph mirrors/history.
        with closing(sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True)) as db:
            db.execute('PRAGMA query_only=ON')
            return '\n'.join(db.iterdump()).encode('utf-8')

    def _assert_invalid_replacement_rolls_back(self, malformed):
        original = tuple(
            ScannedFile(
                str(self.root / f'{suffix}.flac'), FileIdentity(suffix * 64, 123), 1, 'flac',
                TrackMetadata(common=(('title', f'Original {suffix}'),),
                              tags=(('TITLE', (f'Original {suffix}',)),),
                              warnings=('retained warning',),
                              duration_seconds=180.0, duration_source='mutagen'),
            )
            for suffix in ('a', 'b')
        )
        self.writer.register(Inventory(str(self.root), original, (), True))
        revision = self.writer.source_revision()
        edges = (ProjectionEdge(original[0].identity.track_id, original[1].identity.track_id, 0.25, 2),)
        build_id = self.writer.replace_graph_snapshot(
            edges, 2, 'valid-metadata-control', positioned_edges=edges, source_revision=revision,
        )
        self.assertEqual(self.writer.current_graph_snapshot(2, revision)['build_id'], build_id)
        before = self._snapshot()
        track_ids_before = tuple(self.writer.track_ids())
        # First item changes existing metadata/location; second replaces
        # another existing item with bad shape.
        # Complete scan also proposes marking the moved original location missing.
        candidate = (
            replace(original[0], location=str(self.root / 'moved.flac'), mtime_ns=2,
                    metadata=TrackMetadata(common=(('title', 'Changed first'),),
                                           tags=(('TITLE', ('Changed first',)),),
                                           duration_seconds=180.0, duration_source='mutagen')),
            replace(original[1], mtime_ns=3, metadata=malformed),
        )
        with self.assertRaisesRegex(AnalysisError, '[Mm]etadata',
                                    msg='register must reject unsupported metadata shape before commit'):
            self.writer.register(Inventory(str(self.root), candidate, (), True))
        self.assertEqual(self._snapshot(), before, 'invalid inventory must roll back every persisted change')
        self.assertEqual(tuple(self.writer.track_ids()), track_ids_before)
        self.assertEqual(self.writer.source_revision(), revision)
        current = self.writer.current_graph_snapshot(2, revision)
        self.assertEqual(current['state'], 'ready')
        self.assertEqual(current['build_id'], build_id)
        for item in original:
            self.assertEqual(self.writer.locations(item.identity.track_id), (item.location,))
            self.assertEqual(ReadOnlyExplorerSQLiteRepository(str(self.path)).read_track(item.identity.track_id).metadata,
                             item.metadata)

    def test_register_rejects_common_mapping_and_rolls_back_whole_inventory(self):
        self._assert_invalid_replacement_rolls_back(
            TrackMetadata(common={'title': 'Song'}, duration_seconds=180.0, duration_source='mutagen'),
        )

    def test_register_rejects_scalar_tag_values_and_rolls_back_whole_inventory(self):
        self._assert_invalid_replacement_rolls_back(
            TrackMetadata(tags=(('TITLE', 'Song'),), duration_seconds=180.0, duration_source='mutagen'),
        )

    def _scan_audio(self, name, audio):
        (self.root / name).write_bytes(b'bounded synthetic audio identity')
        # Substitute only the external decoder boundary. Real metadata reader,
        # stable-byte inventory, scan use case and catalogue writer all execute.
        fake_mutagen = types.SimpleNamespace(File=lambda location, easy=False: audio)
        with patch.dict(sys.modules, {'mutagen': fake_mutagen}):
            report = ScanLibrary(LocalInventory(MutagenMetadataReader()), self.writer).execute(str(self.root))
        self.assertTrue(report.complete)
        self.assertEqual(report.issues, ())
        self.assertEqual(len(report.files), 1)
        scanned = report.files[0]
        stored = ReadOnlyExplorerSQLiteRepository(str(self.path)).read_track(scanned.identity.track_id)
        self.assertEqual(stored.metadata, scanned.metadata)
        self.assertEqual(self.writer.locations(scanned.identity.track_id), (scanned.location,))
        # Reopen also proves scanner-origin persisted shape remains writer-valid.
        SQLiteAnalysisRepository(str(self.path))
        return scanned.metadata

    def test_real_scanner_single_text_unicode_custom_tags_and_missing_duration_roundtrip(self):
        metadata = self._scan_audio('été.flac', types.SimpleNamespace(tags={
            'TITLE': ['Été 東京'], 'artist': ['Björk'], 'custom:rating': ['5'],
        }))
        self.assertIn(('title', 'Été 東京'), metadata.common)
        self.assertIn(('artist', 'Björk'), metadata.common)
        self.assertIn(('custom:rating', ('5',)), metadata.tags)
        self.assertIsNone(metadata.duration_seconds)
        self.assertEqual(metadata.duration_source, '')
        self.assertTrue(metadata.warnings)
        self.assertTrue(all(isinstance(warning, str) for warning in metadata.warnings))

    def test_real_scanner_multiple_text_mp4_number_comments_and_warnings_roundtrip(self):
        metadata = self._scan_audio('multi.m4a', types.SimpleNamespace(
            info=types.SimpleNamespace(length=1199.5),
            tags={
                'TITLE': ['Été'], 'artist': ['One', '東京', 'One'],
                'COMM::eng': ['short comment'], 'COMM:liner:fra': ['notes françaises'],
                'aART': ['Album Artist'], 'trkn': [(3, 12)],
                'custom:rating': ['5'], 'APIC:cover': [b'binary'], 'lyrics': ['omitted'],
            },
        ))
        self.assertIn(('artist', ('One', '東京')), metadata.common)
        self.assertIn(('comment', ('short comment', 'notes françaises')), metadata.common)
        self.assertIn(('album_artist', 'Album Artist'), metadata.common)
        self.assertIn(('track_number', '3/12'), metadata.common)
        self.assertIn(('trkn', ('3/12',)), metadata.tags)
        self.assertIn(('COMM:liner:fra', ('notes françaises',)), metadata.tags)
        self.assertIn('APIC:cover: embedded artwork/binary metadata omitted', metadata.warnings)
        self.assertIn('lyrics: lyrics omitted pending explicit privacy/size policy', metadata.warnings)
        self.assertEqual(metadata.duration_seconds, 1199.5)
        self.assertEqual(metadata.duration_source, 'mutagen')

    def test_real_scanner_empty_optional_metadata_roundtrips(self):
        metadata = self._scan_audio('empty.ogg', types.SimpleNamespace(tags={}, info=types.SimpleNamespace(length=180.0)))
        self.assertEqual(metadata.common, ())
        self.assertEqual(metadata.tags, ())
        self.assertEqual(metadata.warnings, ())
        self.assertEqual(metadata.duration_seconds, 180.0)
        self.assertEqual(metadata.duration_source, 'mutagen')


if __name__ == '__main__':
    unittest.main()
