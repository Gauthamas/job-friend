import hashlib

import numpy as np

from app.vectors import normalize

_DIM = 16


def _hash_vector(text: str) -> np.ndarray:
    """Deterministic fallback vector for any text not explicitly registered
    with MockEmbeddingClient — same text always produces the same vector,
    different text (almost always) produces a different one, with no
    network call."""
    digest = hashlib.sha256(text.encode()).digest()
    raw = np.frombuffer(digest[:_DIM], dtype=np.uint8).astype(np.float32)
    return normalize(raw)


class MockEmbeddingClient:
    """No network calls. Returns a hash-derived vector for any text by
    default; tests can register exact vectors for specific texts via
    `set_vector` to construct known similarity relationships."""

    def __init__(self):
        self._overrides: dict[str, np.ndarray] = {}

    def set_vector(self, text: str, vector: list[float]) -> None:
        self._overrides[text] = normalize(np.array(vector, dtype=np.float32))

    def embed(self, texts: list[str]) -> list[np.ndarray]:
        return [self._overrides.get(text, _hash_vector(text)) for text in texts]
