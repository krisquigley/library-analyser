"""Where the audio sits inside an MP3 or FLAC file, between its tag blocks (#223).

A tag write (#132) rewrites only the tag blocks, so the bytes between them identify the audio across a
tags-only change. Only the container's framing is read; the audio itself is never decoded. A layout that
cannot be read with certainty has no span, so the file simply keeps no audio identity.
"""
from __future__ import annotations

from typing import Callable

ReadAt = Callable[[int, int], bytes]

_ID3V2_HEADER = 10
_ID3V1_SIZE = 128
_APE_FOOTER = 32
_FLAC_BLOCK_HEADER = 4


def audio_stream_span(file_format: str, read: ReadAt, size: int) -> tuple[int, int] | None:
    """The [start, end) byte range of the audio, or None when the format or layout gives none."""
    skip_container = _CONTAINERS.get(file_format)
    if skip_container is None:
        return None
    start = _after_id3v2_tags(read, 0, size)
    start = skip_container(read, start, size) if start is not None else None
    end = _before_trailing_tags(read, size)
    if start is None or end is None or start >= end:
        return None
    return start, end


def _after_id3v2_tags(read: ReadAt, offset: int, size: int) -> int | None:
    while True:
        header = read(offset, _ID3V2_HEADER)
        if len(header) < _ID3V2_HEADER or header[:3] != b'ID3':
            return offset
        body = _syncsafe(header[6:10])
        if body is None:
            return None
        footer = _ID3V2_HEADER if header[5] & 0x10 else 0
        offset += _ID3V2_HEADER + body + footer
        if offset > size:
            return None


def _mp3_audio_start(read: ReadAt, offset: int, size: int) -> int | None:
    return offset


def _flac_audio_start(read: ReadAt, offset: int, size: int) -> int | None:
    if read(offset, 4) != b'fLaC':
        return None
    offset += 4
    while True:
        header = read(offset, _FLAC_BLOCK_HEADER)
        if len(header) < _FLAC_BLOCK_HEADER:
            return None
        offset += _FLAC_BLOCK_HEADER + int.from_bytes(header[1:4], 'big')
        if offset > size:
            return None
        if header[0] & 0x80:
            return offset


def _before_trailing_tags(read: ReadAt, size: int) -> int | None:
    end = size
    if end >= _ID3V1_SIZE and read(end - _ID3V1_SIZE, 3) == b'TAG':
        end -= _ID3V1_SIZE
    if end >= _APE_FOOTER:
        footer = read(end - _APE_FOOTER, _APE_FOOTER)
        if footer[:8] == b'APETAGEX':
            tag_size = int.from_bytes(footer[12:16], 'little')
            has_header = int.from_bytes(footer[20:24], 'little') & (1 << 31)
            end -= tag_size + (_APE_FOOTER if has_header else 0)
            if end < 0:
                return None
    return end


def _syncsafe(encoded: bytes) -> int | None:
    if any(byte & 0x80 for byte in encoded):
        return None
    return (encoded[0] << 21) | (encoded[1] << 14) | (encoded[2] << 7) | encoded[3]


_CONTAINERS = {'mp3': _mp3_audio_start, 'flac': _flac_audio_start}
