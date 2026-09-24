"""Prepared explorer projection artifact boundary."""
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ProjectionArtifactReplaceOutcome:
    committed: bool = True
    warning: str | None = None


class ProjectionArtifactStore(Protocol):
    def load(self) -> dict[str, object]: ...
    def replace(self, artifact: dict[str, object]) -> ProjectionArtifactReplaceOutcome | None: ...
