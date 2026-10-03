"""Application boundaries for explicit graph snapshot persistence."""
from __future__ import annotations

from typing import Protocol

from music_analyzer.domain.projection import ProjectionEdge


class GraphSnapshotWriter(Protocol):
    def source_revision(self) -> str: ...
    def current_graph_snapshot(self, sparse_k: int, source_revision: str) -> dict: ...
    def begin_graph_build(self, sparse_k: int, source_revision: str) -> str | None: ...
    def finish_graph_build_attempt(self, build_id: str, status: str, detail: str) -> None: ...
    def replace_graph_snapshot(
        self,
        edges: tuple[ProjectionEdge, ...],
        sparse_k: int,
        source_fingerprint: str,
        positioned_edges: tuple[ProjectionEdge, ...] = (),
        *,
        source_revision: str | None = None,
        attempt_id: str | None = None,
    ) -> None: ...
