"""Exact-file identity domain model."""
from dataclasses import dataclass


@dataclass(frozen=True)
class FileIdentity:
    sha256: str
    size: int

    def __post_init__(self):
        if not is_sha256_digest(self.sha256) or self.size < 0:
            raise ValueError('Identity requires a lowercase SHA-256 digest and nonnegative size')

    @property
    def track_id(self) -> str:
        return f'sha256:{self.sha256}'


def validate_file_size(size: int) -> None:
    """Require a nonnegative whole-byte size without coercing its value.

    Integral floats and booleans retain their existing numeric compatibility.
    This policy is explicit so writers can reject invalid inputs at their
    boundary without changing when FileIdentity construction fails.
    """
    if not isinstance(size, (int, float)) or size < 0 or (
        isinstance(size, float) and not size.is_integer()
    ):
        raise ValueError('Invalid identity size; requires nonnegative integer numeric value')


def is_sha256_digest(value) -> bool:
    """A lowercase hexadecimal SHA-256 digest: how both a file and its audio stream are identified."""
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)
