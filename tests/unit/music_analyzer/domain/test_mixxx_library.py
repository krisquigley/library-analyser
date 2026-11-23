"""Issue #133: how an analysed track's evidence becomes a row in a new Mixxx-compatible library file.

The values follow Mixxx 2.5's own encoding (schema revision 39): `key_id` is the ChromaticKey enum
(src/proto/keys.proto), the key text uses Mixxx's ID3v2 names, and an unknown BPM is 0.0 (src/track/bpm.h).
"""
import unittest

from music_analyzer.domain.mixxx_library import (
    MixxxKey, mixxx_bpm, mixxx_file_type, mixxx_key, mixxx_key_from_text, track_location)


class MixxxKeyTests(unittest.TestCase):
    def test_every_detected_key_has_its_mixxx_id_and_name(self):
        cases = [
            ('C', 'major', 1, 'C'), ('Db', 'major', 2, 'Db'), ('C#', 'major', 2, 'Db'), ('F#', 'major', 7, 'F#'),
            ('Gb', 'major', 7, 'F#'), ('B', 'major', 12, 'B'), ('C', 'minor', 13, 'Cm'), ('C#', 'minor', 14, 'C#m'),
            ('D#', 'minor', 16, 'Ebm'), ('G#', 'minor', 21, 'G#m'), ('Ab', 'minor', 21, 'G#m'), ('A', 'minor', 22, 'Am'),
            ('A#', 'minor', 23, 'Bbm'), ('B', 'minor', 24, 'Bm'),
        ]
        for tonic, scale, key_id, text in cases:
            with self.subTest(tonic=tonic, scale=scale):
                self.assertEqual(MixxxKey(key_id, text), mixxx_key(tonic, scale))

    def test_an_unknown_key_leaves_the_field_empty(self):
        for tonic, scale in [('H', 'major'), ('C', 'dorian'), (None, 'minor'), ('A', None), ('', '')]:
            with self.subTest(tonic=tonic, scale=scale):
                self.assertEqual(MixxxKey(0, ''), mixxx_key(tonic, scale))

    def test_a_manual_key_is_read_from_its_usual_spellings(self):
        cases = [('A minor', 22), ('a Minor', 22), ('Am', 22), ('C#m', 14), ('Bb', 11), ('F# major', 7), (' Eb ', 4)]
        for text, key_id in cases:
            with self.subTest(text=text):
                self.assertEqual(key_id, mixxx_key_from_text(text).key_id)

    def test_a_manual_key_that_cannot_be_read_leaves_the_field_empty(self):
        for text in ['8A', 'unknown', 'A dorian', '', 'Cbm7']:
            with self.subTest(text=text):
                self.assertEqual(MixxxKey(0, ''), mixxx_key_from_text(text))


class MixxxBpmTests(unittest.TestCase):
    def test_a_known_bpm_is_kept_and_an_unknown_one_is_zero(self):
        cases = [(124.0, 124.0), (87.53, 87.53), ('128', 128.0), (' 99.5 ', 99.5), (None, 0.0), (0, 0.0), (-3, 0.0),
                 (float('nan'), 0.0), (float('inf'), 0.0), ('fast', 0.0), (True, 0.0)]
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(expected, mixxx_bpm(value))


class TrackLocationTests(unittest.TestCase):
    def test_an_absolute_path_splits_into_location_filename_and_directory(self):
        location = track_location('/music/Synthetic Artist/Track One.flac')
        self.assertEqual(('/music/Synthetic Artist/Track One.flac', 'Track One.flac', '/music/Synthetic Artist'),
                         (location.location, location.filename, location.directory))

    def test_a_relative_or_empty_path_is_refused(self):
        for path in ['music/a.flac', '', '/']:
            with self.subTest(path=path):
                with self.assertRaises(ValueError):
                    track_location(path)


class MixxxFileTypeTests(unittest.TestCase):
    def test_the_file_type_is_the_lowercase_extension_and_aif_is_aiff(self):
        cases = [('a.FLAC', 'flac'), ('a.mp3', 'mp3'), ('a.aif', 'aiff'), ('a.AIFF', 'aiff'), ('a.m4a', 'm4a'),
                 ('noextension', '?'), ('.hidden', '?'), ('a.waytoolongext', '?')]
        for filename, expected in cases:
            with self.subTest(filename=filename):
                self.assertEqual(expected, mixxx_file_type(filename))


if __name__ == '__main__':
    unittest.main()
