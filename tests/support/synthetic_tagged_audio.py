"""Tiny synthetic MP3 and FLAC files for tag tests (#132): silent, generated in the test, never real music.

The MP3 is a run of MPEG-1 Layer III frame headers with zeroed payloads; the FLAC is a STREAMINFO block
followed by placeholder frame bytes. Both open in mutagen, which is all a tag test needs.
"""
import struct
from pathlib import Path

MP3_AUDIO = (bytes([0xFF, 0xFB, 0x90, 0x00]) + bytes(413)) * 20
FLAC_AUDIO = b'\xff\xf8' + bytes(range(200))


def synthetic_mp3(path: Path) -> Path:
    path.write_bytes(MP3_AUDIO)
    return path


def synthetic_flac(path: Path) -> Path:
    stream_info_bits = (44100 << 44) | (0 << 41) | (15 << 36) | 44100
    stream_info = (struct.pack('>HH', 4096, 4096) + bytes(6) + stream_info_bits.to_bytes(8, 'big') + bytes(16))
    path.write_bytes(b'fLaC' + bytes([0x80]) + len(stream_info).to_bytes(3, 'big') + stream_info + FLAC_AUDIO)
    return path
