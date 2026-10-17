import numpy as np
from sklearn.cluster import AgglomerativeClustering
from sklearn.preprocessing import normalize


def cluster_embeddings(embeddings: np.ndarray, k: int, seed: int) -> np.ndarray:
    # AgglomerativeClustering itself isn't seed-sensitive (it's
    # deterministic given the data), but normalize() and any future
    # swap to a seeded method should still go through one seed; kept as a
    # parameter so that's a one-line change, not a hunt through the file.
    del seed
    normed = normalize(embeddings)
    model = AgglomerativeClustering(n_clusters=k, metric="cosine", linkage="average")
    return model.fit_predict(normed)


def cluster_centroid(embeddings: np.ndarray) -> np.ndarray:
    """Mean of the normalized member vectors, renormalized -- a unit vector
    so cosine similarity to it is a plain dot product."""
    normed = normalize(embeddings)
    centroid = normed.mean(axis=0)
    norm = np.linalg.norm(centroid)
    return centroid / norm if norm > 0 else centroid
