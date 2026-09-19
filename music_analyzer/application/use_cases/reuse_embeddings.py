from music_analyzer.application.ports.embedding_cache import EmbeddingCache
from music_analyzer.domain.analysis import finite


def valid_embeddings(value, sections, width):
    return (isinstance(value, tuple) and len(value) == sections and
            all(isinstance(matrix, tuple) and 0 < len(matrix) <= 10000 and
                all(isinstance(row, tuple) and len(row) == width and
                    all(finite(v) for v in row) for row in matrix) for matrix in value))


class ReuseEmbeddings:
    """Cache corruption/shape mismatch is a miss; never cache invalid inference."""
    def __init__(self, cache: EmbeddingCache):
        self.cache = cache

    def execute(self, key, sections, width, compute):
        value = self.cache.get(key)
        if valid_embeddings(value, sections, width):
            return value
        value = compute()
        if not valid_embeddings(value, sections, width):
            raise ValueError('invalid embedding output shape or nonfinite output')
        self.cache.put(key, value)
        return value
