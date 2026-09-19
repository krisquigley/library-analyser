"""Exact-file identity, deliberately not an acoustic recording identity."""
from dataclasses import dataclass


@dataclass(frozen=True)
class FileIdentity:
    sha256: str
    size: int

    def __post_init__(self):
        if len(self.sha256) != 64 or any(c not in '0123456789abcdef' for c in self.sha256) or self.size < 0:
            raise ValueError('Identity requires a lowercase SHA-256 digest and nonnegative size')

    @property
    def track_id(self) -> str:
        return f'sha256:{self.sha256}'
