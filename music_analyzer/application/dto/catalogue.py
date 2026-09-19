from dataclasses import dataclass
from music_analyzer.domain.catalogue import FileIdentity


@dataclass(frozen=True)
class ScanLimits:
    max_entries: int = 10000
    max_file_bytes: int = 512 * 1024 * 1024
    max_total_bytes: int = 8 * 1024 * 1024 * 1024

    def __post_init__(self):
        if not 0 < self.max_entries <= 100000 or not 0 < self.max_file_bytes <= 2**31 or not 0 < self.max_total_bytes <= 2**36:
            raise ValueError('Scan limits must be positive; ceilings: 100000 entries, 2 GiB/file, 64 GiB total')


@dataclass(frozen=True)
class ScannedFile:
    location: str
    identity: FileIdentity
    mtime_ns: int
    format: str


@dataclass(frozen=True)
class ScanIssue:
    location: str
    detail: str


@dataclass(frozen=True)
class Inventory:
    root: str
    files: tuple[ScannedFile, ...]
    issues: tuple[ScanIssue, ...]
    complete: bool


@dataclass(frozen=True)
class ScanReport:
    root: str
    files: tuple[ScannedFile, ...]
    issues: tuple[ScanIssue, ...]
    complete: bool
    missing: tuple[str, ...]
