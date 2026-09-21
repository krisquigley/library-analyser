"""Optional, disposable cache. Values are plain finite rectangular matrices."""
from typing import Protocol

Embeddings = tuple[tuple[tuple[float, ...], ...], ...]


class EmbeddingCache(Protocol):
    def get(self, key: str) -> Embeddings | None: ...
    def put(self, key: str, value: Embeddings) -> None: ...
