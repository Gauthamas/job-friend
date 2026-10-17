"""Embeds sentences with StyleDistance, caching every vector on disk by a
hash of its sentence text so re-running a later step never re-embeds a
sentence whose text hasn't changed. The model loads once per process."""

import hashlib
from pathlib import Path

import numpy as np

_model = None


def get_model(model_name: str):
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(model_name)
    return _model


def sentence_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_cache(cache_path: Path) -> dict[str, np.ndarray]:
    if not cache_path.exists():
        return {}
    data = np.load(cache_path, allow_pickle=False)
    return {k: data[k] for k in data.files}


def save_cache(cache_path: Path, cache: dict[str, np.ndarray]) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(cache_path, **cache)


def embed_sentences(texts: list[str], model_name: str, cache_path: Path) -> np.ndarray:
    cache = load_cache(cache_path)
    hashes = [sentence_hash(t) for t in texts]
    missing_texts = [t for t, h in zip(texts, hashes) if h not in cache]

    if missing_texts:
        model = get_model(model_name)
        vectors = model.encode(missing_texts, show_progress_bar=True, convert_to_numpy=True)
        for t, v in zip(missing_texts, vectors):
            cache[sentence_hash(t)] = v
        save_cache(cache_path, cache)

    return np.stack([cache[h] for h in hashes])
