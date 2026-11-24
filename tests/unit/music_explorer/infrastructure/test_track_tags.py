"""Issue #132: without mutagen the Explorer still starts, and tagging says why it cannot write."""
import builtins
import unittest
from unittest import mock

from music_explorer.application.ports.track_tags import OwnedTags, TrackTagsError
from music_explorer.infrastructure.track_tags import MutagenTrackTags

_import = builtins.__import__


def _without_mutagen(name, *args, **kwargs):
    if name == 'mutagen' or name.startswith('mutagen.'):
        raise ImportError(f'No module named {name!r}')
    return _import(name, *args, **kwargs)


class WithoutMutagenTests(unittest.TestCase):
    def test_reading_or_writing_tags_reports_that_mutagen_is_missing(self):
        with mock.patch('builtins.__import__', side_effect=_without_mutagen):
            for call in (lambda: MutagenTrackTags().read_owned('/music/synthetic.mp3'),
                         lambda: MutagenTrackTags().write_owned('/music/synthetic.flac', OwnedTags('124'))):
                with self.assertRaisesRegex(TrackTagsError, 'mutagen is not installed'):
                    call()


if __name__ == '__main__':
    unittest.main()
