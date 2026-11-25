"""Issue #269: a track's audio as the browser is served it. Cover pictures and padding stay out of a FLAC's stream,
so a picture the browser cannot read never stops the track playing; the file itself is never changed."""
from pathlib import Path
import tempfile
import unittest

from music_explorer.infrastructure.playable_audio import open_playable_audio
from tests.support.synthetic_flac import (
    FRAMES, PADDING, PICTURE, SEEKTABLE, STREAMINFO, VORBIS_COMMENT, metadata_block, picture_body, synthetic_flac)

STREAM_INFO = bytes(range(34))
SEEK_POINTS = bytes(18)
COMMENTS = b'synthetic comments'


class PlayableAudioTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def _file(self, name, content):
        path = self.root / name
        path.write_bytes(content)
        return path

    def _served(self, path, first=None, last=None):
        with open_playable_audio(str(path)) as audio:
            first, last = (0, audio.size - 1) if first is None else (first, last)
            return audio.size, b''.join(audio.chunks(first, last, chunk_size=97))

    def test_a_flac_is_served_without_its_pictures_or_padding_and_the_last_kept_block_says_so(self):
        content = synthetic_flac((STREAMINFO, STREAM_INFO), (PICTURE, picture_body(b'', bytes(5000))),
                                 (SEEKTABLE, SEEK_POINTS), (VORBIS_COMMENT, COMMENTS), (PADDING, bytes(4096)))
        path = self._file('Unlabelled.flac', content)
        expected = (b'fLaC' + metadata_block(STREAMINFO, STREAM_INFO) + metadata_block(SEEKTABLE, SEEK_POINTS)
                    + metadata_block(VORBIS_COMMENT, COMMENTS, last=True) + FRAMES)
        self.assertEqual((len(expected), expected), self._served(path))
        self.assertEqual(content, path.read_bytes(), 'the file is never changed')

    def test_any_byte_range_reads_the_served_stream_across_the_metadata_and_the_frames(self):
        path = self._file('Seek.flac', synthetic_flac((STREAMINFO, STREAM_INFO), (PICTURE, picture_body(b'', bytes(300)))))
        whole = b'fLaC' + metadata_block(STREAMINFO, STREAM_INFO, last=True) + FRAMES
        for first, last in ((0, 3), (2, 60), (37, 39), (30, 500), (len(whole) - 10, len(whole) - 1)):
            with self.subTest(first=first, last=last):
                self.assertEqual(whole[first:last + 1], self._served(path, first, last)[1])

    def test_a_flac_without_pictures_or_padding_and_anything_else_are_served_as_they_are(self):
        plain = synthetic_flac((STREAMINFO, STREAM_INFO), (VORBIS_COMMENT, COMMENTS))
        truncated = b'fLaC' + bytes([PICTURE]) + (10 ** 6).to_bytes(3, 'big') + bytes(20)
        tagged_first = b'ID3' + synthetic_flac((STREAMINFO, STREAM_INFO), (PICTURE, picture_body(b'', bytes(10))))
        for name, content in (('Plain.flac', plain), ('Truncated.flac', truncated), ('Tagged.flac', tagged_first),
                              ('Song.mp3', b'ID3' + bytes(range(200))), ('Short.flac', b'fL')):
            with self.subTest(name=name):
                self.assertEqual((len(content), content), self._served(self._file(name, content)))


if __name__ == '__main__':
    unittest.main()
