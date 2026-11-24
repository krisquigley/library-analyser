"""The identity of an audio file as the analyzer records it: the SHA-256 of the whole file (#132)."""
from typing import Protocol


class FileIdentity(Protocol):
    def sha256(self, location: str) -> str | None:
        """The file's SHA-256, or None when it cannot be read."""
        ...
