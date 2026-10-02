"""Application boundaries for explicit graph snapshot persistence."""
from __future__ import annotations

from typing import Protocol

from music_analyzer.domain.projection import ProjectionEdge


class GraphSnapshotWriter(Protocol):
    def replace_graph_snapshot(self, edges: tuple[ProjectionEdge, ...], sparse_k: int, source_fingerprint: str, positioned_edges: tuple[ProjectionEdge, ...] = ()) -> None: ...
