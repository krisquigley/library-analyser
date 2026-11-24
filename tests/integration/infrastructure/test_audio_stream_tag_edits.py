"""Issue #223: a real tag editor (mutagen) changes a file's bytes but not its audio span."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

from music_analyzer.infrastructure.filesystem.audio_stream import audio_stream_span
from tests.support.synthetic_tagged_audio import FLAC_AUDIO, MP3_AUDIO, synthetic_flac, synthetic_mp3

if importlib.util.find_spec('mutagen') is None:
    raise unittest.SkipTest('mutagen is not installed in the dependency-free test environment')

from mutagen.flac import FLAC  # noqa: E402
from mutagen.id3 import ID3, TBPM, TIT2, TKEY  # noqa: E402


def audio_bytes(path, file_format):
    data = path.read_bytes()
    span = audio_stream_span(file_format, lambda offset, length: data[offset:offset + length], len(data))
    return None if span is None else data[span[0]:span[1]]


class TagEditKeepsAudioSpanTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)

    def test_id3_edits_change_the_file_but_not_its_audio(self):
        path = synthetic_mp3(self.folder / 'synthetic.mp3')
        tags = ID3()
        tags.add(TIT2(encoding=3, text='Synthetic'))
        tags.save(path, v2_version=3)
        tagged = path.read_bytes()
        tags = ID3(path)
        tags.add(TBPM(encoding=3, text='124'))
        tags.add(TKEY(encoding=3, text='Am'))
        tags.save(path, v2_version=3)
        self.assertNotEqual(path.read_bytes(), tagged)
        self.assertEqual(audio_bytes(path, 'mp3'), MP3_AUDIO)

    def test_vorbis_comment_edits_change_the_file_but_not_its_audio(self):
        path = synthetic_flac(self.folder / 'synthetic.flac')
        before = path.read_bytes()
        audio = FLAC(path)
        audio['BPM'] = '124'
        audio['INITIALKEY'] = 'Am'
        audio.save()
        self.assertNotEqual(path.read_bytes(), before)
        self.assertEqual(audio_bytes(path, 'flac'), FLAC_AUDIO)


if __name__ == '__main__':
    unittest.main()
