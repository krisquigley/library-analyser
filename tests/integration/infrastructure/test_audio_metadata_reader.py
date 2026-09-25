import sys
import types
import unittest
from unittest.mock import patch

from music_analyzer.infrastructure.audio.metadata import MutagenMetadataReader


class MutagenMetadataReaderTests(unittest.TestCase):
    def test_preserves_supported_textual_tags_and_normalizes_common_fields_with_bounds(self):
        class FakeAudio:
            tags = {
                'TITLE': ['Tagged Song'],
                'artist': ['One', 'Two', 'One'],
                'custom:rating': ['5'],
                'APIC:cover': [b'binary image'],
                'lyrics': ['private long text'],
            }

        fake_mutagen = types.SimpleNamespace(File=lambda location, easy=False: FakeAudio())
        with patch.dict(sys.modules, {'mutagen': fake_mutagen}):
            metadata = MutagenMetadataReader().read('/music/tagged.flac')

        self.assertIn(('title', 'Tagged Song'), metadata.common)
        self.assertIn(('artist', ('One', 'Two')), metadata.common)
        self.assertIn(('TITLE', ('Tagged Song',)), metadata.tags)
        self.assertIn(('custom:rating', ('5',)), metadata.tags)
        self.assertFalse(any(key.startswith('APIC') for key, _ in metadata.tags))
        self.assertFalse(any(key == 'lyrics' for key, _ in metadata.tags))
        self.assertIn('APIC:cover: embedded artwork/binary metadata omitted', metadata.warnings)
        self.assertIn('lyrics: lyrics omitted pending explicit privacy/size policy', metadata.warnings)

    def test_omits_private_opaque_and_lyrics_id3_frames_before_stringifying_values(self):
        class SecretValue:
            def __str__(self):
                raise AssertionError('private ID3 value should not be stringified')

        class FakeAudio:
            tags = {
                'TIT2': ['Tagged Song'],
                'PRIV:owner': SecretValue(),
                'GEOB:blob': SecretValue(),
                'UFID:owner': SecretValue(),
                'USLT::eng': SecretValue(),
                'SYLT::eng': SecretValue(),
            }

        fake_mutagen = types.SimpleNamespace(File=lambda location, easy=False: FakeAudio())
        with patch.dict(sys.modules, {'mutagen': fake_mutagen}):
            metadata = MutagenMetadataReader().read('/music/tagged.mp3')

        self.assertIn(('title', 'Tagged Song'), metadata.common)
        self.assertIn(('TIT2', ('Tagged Song',)), metadata.tags)
        self.assertFalse(any(key.startswith(('PRIV', 'GEOB', 'UFID', 'USLT', 'SYLT')) for key, _ in metadata.tags))
        self.assertTrue(any('PRIV:owner' in warning and 'private/opaque' in warning for warning in metadata.warnings))
        self.assertTrue(any('GEOB:blob' in warning and 'private/opaque' in warning for warning in metadata.warnings))
        self.assertTrue(any('UFID:owner' in warning and 'private/opaque' in warning for warning in metadata.warnings))
        self.assertTrue(any('USLT::eng' in warning and 'lyrics' in warning for warning in metadata.warnings))
        self.assertTrue(any('SYLT::eng' in warning and 'lyrics' in warning for warning in metadata.warnings))

    def test_normalizes_native_mp4_album_artist_and_track_number_atoms(self):
        class FakeAudio:
            tags = {
                'aART': ['Album Artist'],
                'trkn': [(3, 12)],
            }

        fake_mutagen = types.SimpleNamespace(File=lambda location, easy=False: FakeAudio())
        with patch.dict(sys.modules, {'mutagen': fake_mutagen}):
            metadata = MutagenMetadataReader().read('/music/tagged.m4a')

        self.assertIn(('album_artist', 'Album Artist'), metadata.common)
        self.assertIn(('track_number', '3/12'), metadata.common)
        self.assertIn(('aART', ('Album Artist',)), metadata.tags)
        self.assertIn(('trkn', ('3/12',)), metadata.tags)


if __name__ == '__main__':
    unittest.main()
