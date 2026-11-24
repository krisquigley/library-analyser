"""Issue #132: the Explorer writes only BPM and key, to MP3 (ID3) and FLAC (Vorbis comments), atomically,
keeping every other tag, picture and the audio itself unchanged."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC, COMM, ID3, TBPM, TIT2, TKEY

from music_explorer.application.ports.track_tags import OwnedTags, TrackTagsError
from music_explorer.infrastructure.track_tags import MutagenTrackTags
from tests.support.synthetic_tagged_audio import FLAC_AUDIO, MP3_AUDIO, synthetic_flac, synthetic_mp3


class Mp3TrackTagsTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)
        self.path = synthetic_mp3(self.folder / 'synthetic.mp3')
        self.tags = MutagenTrackTags()

    def tag_with(self, *frames, version=3):
        id3 = ID3()
        for frame in frames:
            id3.add(frame)
        id3.save(self.path, v2_version=version)

    def test_an_untagged_file_has_no_owned_values_and_gains_id3v2_3_bpm_and_key(self):
        self.assertEqual(OwnedTags(), self.tags.read_owned(str(self.path)))
        self.tags.write_owned(str(self.path), OwnedTags('124', 'Am'))
        self.assertEqual(OwnedTags('124', 'Am'), self.tags.read_owned(str(self.path)))
        self.assertEqual((2, 3, 0), ID3(self.path).version)
        self.assertTrue(self.path.read_bytes().endswith(MP3_AUDIO))

    def test_other_frames_the_tag_version_and_the_audio_are_kept(self):
        self.tag_with(TIT2(encoding=3, text='Synthetic Title'), COMM(encoding=3, lang='eng', desc='', text='note'),
                      APIC(encoding=3, mime='image/png', type=3, desc='cover', data=b'\x89PNG synthetic'),
                      TKEY(encoding=3, text='C'), version=4)
        self.tags.write_owned(str(self.path), OwnedTags(bpm='128'))
        id3 = ID3(self.path)
        self.assertEqual((2, 4, 0), id3.version)
        self.assertEqual(['Synthetic Title'], id3['TIT2'].text)
        self.assertEqual(['note'], id3.getall('COMM')[0].text)
        self.assertEqual(b'\x89PNG synthetic', id3.getall('APIC')[0].data)
        self.assertEqual(OwnedTags('128', 'C'), self.tags.read_owned(str(self.path)))
        self.assertTrue(self.path.read_bytes().endswith(MP3_AUDIO))

    def test_a_failed_write_leaves_the_file_as_it_was_and_no_temporary_file(self):
        self.tag_with(TBPM(encoding=3, text='100'))
        before = self.path.read_bytes()
        with mock.patch('music_explorer.infrastructure.track_tags.os.replace', side_effect=OSError('disk full')):
            with self.assertRaises(TrackTagsError):
                self.tags.write_owned(str(self.path), OwnedTags('124', 'Am'))
        self.assertEqual(before, self.path.read_bytes())
        self.assertEqual(['synthetic.mp3'], os.listdir(self.folder))


class FlacTrackTagsTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = synthetic_flac(Path(temp.name) / 'synthetic.flac')
        self.tags = MutagenTrackTags()

    def test_bpm_and_initialkey_are_written_and_other_comments_and_pictures_kept(self):
        flac = FLAC(self.path)
        flac.add_tags()
        flac['TITLE'], flac['INITIALKEY'] = 'Synthetic Title', 'Dm'
        picture = Picture()
        picture.type, picture.mime, picture.data = 3, 'image/png', b'\x89PNG synthetic'
        flac.add_picture(picture)
        flac.save()
        self.assertEqual(OwnedTags(None, 'Dm'), self.tags.read_owned(str(self.path)))
        self.tags.write_owned(str(self.path), OwnedTags('124', 'Am'))
        flac = FLAC(self.path)
        self.assertEqual((['124'], ['Am'], ['Synthetic Title']), (flac['BPM'], flac['INITIALKEY'], flac['TITLE']))
        self.assertEqual(b'\x89PNG synthetic', flac.pictures[0].data)
        self.assertTrue(self.path.read_bytes().endswith(FLAC_AUDIO))


class UnsupportedFileTests(unittest.TestCase):
    def test_other_formats_and_missing_or_broken_files_are_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            m4a, broken = Path(temp) / 'synthetic.m4a', Path(temp) / 'broken.flac'
            m4a.write_bytes(b'synthetic')
            broken.write_bytes(b'not flac')
            for path in (m4a, broken, Path(temp) / 'missing.mp3'):
                with self.subTest(path=path.name):
                    with self.assertRaises(TrackTagsError):
                        MutagenTrackTags().read_owned(str(path))
                    with self.assertRaises(TrackTagsError):
                        MutagenTrackTags().write_owned(str(path), OwnedTags('124'))
            self.assertEqual(b'synthetic', m4a.read_bytes())


if __name__ == '__main__':
    unittest.main()
