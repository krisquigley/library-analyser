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


if __name__ == '__main__':
    unittest.main()
