"""Input boundary for a bounded, offline, read-only database diagnostic."""
from typing import Protocol

from music_analyzer.application.dto.integrity import IntegrityScan


class IntegrityScanner(Protocol):
    def scan(self, database: str, deadline_seconds: float = 120) -> IntegrityScan: ...
