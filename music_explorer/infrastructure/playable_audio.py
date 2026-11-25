"""A track's audio as the browser is served it (#269), read only.

A native FLAC is served without its PICTURE and PADDING metadata blocks: playback needs neither, and Chromium
refuses a whole file whose picture block names no MIME type. The remaining blocks keep their order, the last is
re-marked as last, and the audio frames follow untouched. Byte ranges address that served stream. Anything that is
not a well-formed native FLAC, or a FLAC with nothing to leave out, is served exactly as it is. The file is never
written.
"""
import os

_FLAC_MARKER = b'fLaC'
_LAST_BLOCK = 0x80
_BLOCK_KIND = 0x7f
_INVALID_KIND = 127
_LEFT_OUT_KINDS = frozenset({1, 6})  # PADDING, PICTURE
_BLOCK_HEADER_BYTES = 4


class PlayableAudio:
    """The served stream: a short in-memory head (empty when the file is served as it is), then the file from an offset."""

    def __init__(self, file, head: bytes, body_start: int, file_size: int):
        self._file = file
        self._head = head
        self._body_start = body_start
        self.size = len(head) + file_size - body_start

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self._file.close()

    def chunks(self, first: int, last: int, chunk_size: int):
        """The served bytes first..last inclusive, at most chunk_size at a time."""
        position = first
        while position <= last and position < len(self._head):
            end = min(last + 1, len(self._head), position + chunk_size)
            yield self._head[position:end]
            position = end
        self._file.seek(self._body_start + position - len(self._head))
        while position <= last:
            chunk = self._file.read(min(chunk_size, last + 1 - position))
            if not chunk:
                return
            yield chunk
            position += len(chunk)


def open_playable_audio(location: str) -> PlayableAudio:
    """Opens the track's file for reading, to be closed with `with`; an OSError means it cannot be read."""
    file = open(location, 'rb')
    try:
        file_size = os.fstat(file.fileno()).st_size
        head, body_start = _flac_head_without_pictures(file, file_size) or (b'', 0)
    except BaseException:
        file.close()
        raise
    return PlayableAudio(file, head, body_start, file_size)


def _flac_head_without_pictures(file, file_size):
    """The served FLAC head and where the frames start, or None to serve the file as it is."""
    if file.read(len(_FLAC_MARKER)) != _FLAC_MARKER:
        return None
    kept, left_out, last = [], False, False
    while not last:
        header = file.read(_BLOCK_HEADER_BYTES)
        if len(header) < _BLOCK_HEADER_BYTES or header[0] & _BLOCK_KIND == _INVALID_KIND:
            return None
        last, kind, length = bool(header[0] & _LAST_BLOCK), header[0] & _BLOCK_KIND, int.from_bytes(header[1:], 'big')
        if file.tell() + length > file_size:
            return None
        if kind in _LEFT_OUT_KINDS:
            left_out = True
            file.seek(length, os.SEEK_CUR)
        else:
            kept.append((kind, file.read(length)))
    if not left_out or not kept:
        return None
    blocks = [_block(kind, body, place == len(kept) - 1) for place, (kind, body) in enumerate(kept)]
    return _FLAC_MARKER + b''.join(blocks), file.tell()


def _block(kind, body, last):
    return bytes([(_LAST_BLOCK if last else 0) | kind]) + len(body).to_bytes(3, 'big') + body
