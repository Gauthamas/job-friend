from typing import Protocol

import numpy as np
from openai import OpenAI

from app.vectors import normalize


class EmbeddingClient(Protocol):
    def embed(self, texts: list[str]) -> list[np.ndarray]:
        """Embed each text, returning one L2-normalized vector per input,
        in the same order. The caller is responsible for adding any
        nomic-style task prefix ("search_document: " / "search_query: ")."""
        ...


class LMStudioEmbeddingClient:
    def __init__(self, base_url: str, model: str):
        self._client = OpenAI(base_url=base_url, api_key="lm-studio")
        self._model = model

    def embed(self, texts: list[str]) -> list[np.ndarray]:
        if not texts:
            return []
        response = self._client.embeddings.create(model=self._model, input=texts)
        # response.data isn't guaranteed to preserve input order across all
        # server implementations; `index` is the documented way to map back.
        ordered = sorted(response.data, key=lambda d: d.index)
        return [normalize(np.array(d.embedding, dtype=np.float32)) for d in ordered]
