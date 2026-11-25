"""Synthetic FLAC files built byte by byte (#269): metadata blocks the test chooses, then stand-in audio frames.

Nothing here decodes; the frames are arbitrary bytes after the metadata, which is all a stream-level test needs.
"""
import struct

STREAMINFO, PADDING, SEEKTABLE, VORBIS_COMMENT, PICTURE = 0, 1, 3, 4, 6
FRAMES = bytes([0xff, 0xf8]) + bytes(range(256)) * 40


def metadata_block(kind: int, body: bytes, last: bool = False) -> bytes:
    return bytes([(0x80 if last else 0) | kind]) + len(body).to_bytes(3, 'big') + body


def picture_body(mime: bytes, data: bytes) -> bytes:
    return (struct.pack('>II', 3, len(mime)) + mime + struct.pack('>I', 0) + struct.pack('>IIII', 0, 0, 0, 0)
            + struct.pack('>I', len(data)) + data)


def synthetic_flac(*blocks: tuple[int, bytes]) -> bytes:
    """fLaC, the blocks in order (the last one flagged last), then the stand-in frames."""
    encoded = [metadata_block(kind, body, place == len(blocks) - 1) for place, (kind, body) in enumerate(blocks)]
    return b'fLaC' + b''.join(encoded) + FRAMES
