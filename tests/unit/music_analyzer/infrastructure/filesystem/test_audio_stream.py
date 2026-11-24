"""Issue #223: where the audio sits inside an MP3 or FLAC file, so a tags-only change keeps its audio hash."""
import unittest

from music_analyzer.infrastructure.filesystem.audio_stream import audio_stream_span
from tests.support.synthetic_tagged_audio import FLAC_AUDIO, MP3_AUDIO


def syncsafe(size):
    return bytes([(size >> 21) & 0x7F, (size >> 14) & 0x7F, (size >> 7) & 0x7F, size & 0x7F])


def id3v2(body, *, footer=False):
    flags = 0x10 if footer else 0x00
    header = b'ID3\x04\x00' + bytes([flags]) + syncsafe(len(body))
    return header + body + ((b'3DI\x04\x00' + bytes([flags]) + syncsafe(len(body))) if footer else b'')


def id3v1(title=b'synthetic'):
    return b'TAG' + title.ljust(125, b'\x00')


def ape_footer(items_size, *, with_header):
    flags = (1 << 31) if with_header else 0
    footer = b'APETAGEX' + (2000).to_bytes(4, 'little') + (items_size + 32).to_bytes(4, 'little') \
        + (1).to_bytes(4, 'little') + flags.to_bytes(4, 'little') + bytes(8)
    header = (b'APETAGEX' + bytes(24)) if with_header else b''
    return header + bytes(items_size) + footer


def flac(blocks, audio=FLAC_AUDIO):
    encoded = b''
    for index, (kind, body) in enumerate(blocks):
        last = 0x80 if index == len(blocks) - 1 else 0
        encoded += bytes([last | kind]) + len(body).to_bytes(3, 'big') + body
    return b'fLaC' + encoded + audio


def span_of(data, file_format):
    return audio_stream_span(file_format, lambda offset, length: data[offset:offset + length], len(data))


def audio_of(data, file_format):
    start, end = span_of(data, file_format)
    return data[start:end]


class Mp3AudioStreamTests(unittest.TestCase):
    def test_an_untagged_mp3_is_all_audio(self):
        self.assertEqual(span_of(MP3_AUDIO, 'mp3'), (0, len(MP3_AUDIO)))

    def test_leading_id3v2_tags_with_or_without_a_footer_are_skipped(self):
        for leading in (id3v2(b'TBPM' + bytes(40)), id3v2(bytes(300), footer=True), id3v2(bytes(10)) + id3v2(bytes(20))):
            with self.subTest(size=len(leading)):
                self.assertEqual(audio_of(leading + MP3_AUDIO, 'mp3'), MP3_AUDIO)

    def test_trailing_id3v1_and_ape_tags_are_skipped(self):
        for trailing in (id3v1(), ape_footer(50, with_header=False), ape_footer(50, with_header=True) + id3v1()):
            with self.subTest(size=len(trailing)):
                self.assertEqual(audio_of(id3v2(bytes(30)) + MP3_AUDIO + trailing, 'mp3'), MP3_AUDIO)

    def test_tags_alone_or_a_tag_claiming_more_than_the_file_have_no_audio(self):
        self.assertIsNone(span_of(id3v2(bytes(30)) + id3v1(), 'mp3'))
        claims_too_much = b'ID3\x04\x00\x00' + syncsafe(10_000) + MP3_AUDIO
        self.assertIsNone(span_of(claims_too_much, 'mp3'))


class FlacAudioStreamTests(unittest.TestCase):
    def test_the_audio_follows_the_last_metadata_block(self):
        stream_info = bytes(34)
        for blocks in ([(0, stream_info)], [(0, stream_info), (4, bytes(90)), (1, bytes(1024))]):
            with self.subTest(blocks=len(blocks)):
                self.assertEqual(audio_of(flac(blocks), 'flac'), FLAC_AUDIO)

    def test_a_leading_id3v2_or_trailing_id3v1_tag_is_skipped(self):
        self.assertEqual(audio_of(id3v2(bytes(25)) + flac([(0, bytes(34))]) + id3v1(), 'flac'), FLAC_AUDIO)

    def test_a_file_that_is_not_flac_or_whose_blocks_overrun_has_no_audio(self):
        self.assertIsNone(span_of(b'OggS' + bytes(100), 'flac'))
        overrun = b'fLaC' + bytes([0x80]) + (5000).to_bytes(3, 'big') + bytes(40)
        self.assertIsNone(span_of(overrun, 'flac'))
        self.assertIsNone(span_of(flac([(0, bytes(34))], audio=b''), 'flac'))


class OtherFormatTests(unittest.TestCase):
    def test_formats_whose_tags_are_never_written_have_no_audio_span(self):
        for file_format in ('wav', 'm4a', 'ogg', 'opus', 'aiff'):
            with self.subTest(file_format=file_format):
                self.assertIsNone(span_of(MP3_AUDIO, file_format))


if __name__ == '__main__':
    unittest.main()
