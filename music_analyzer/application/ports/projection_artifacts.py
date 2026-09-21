"""Prepared explorer projection artifact boundary."""
from typing import Protocol


class ProjectionArtifactStore(Protocol):
    def load(self) -> dict[str, object]: ...
    def replace(self, artifact: dict[str, object]) -> None: ...
