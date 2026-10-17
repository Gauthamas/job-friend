import numpy as np
from sklearn.preprocessing import normalize

from style_exp.cluster import cluster_centroid


def assign_holdout(
    train_embeddings: np.ndarray, train_labels: np.ndarray,
    holdout_embeddings: np.ndarray, percentile: float,
) -> list[dict]:
    """For each cluster, builds a centroid and the distribution of its own
    members' similarity to it; the `percentile`-th value of that pooled
    distribution is the fit threshold. Returns one dict per holdout
    sentence: best cluster label, its similarity, and whether that's below
    the threshold."""
    normed_train = normalize(train_embeddings)
    normed_holdout = normalize(holdout_embeddings)

    labels = sorted(set(train_labels.tolist()))
    centroids = {}
    own_similarities: list[float] = []
    for label in labels:
        member_vectors = train_embeddings[train_labels == label]
        centroid = cluster_centroid(member_vectors)
        centroids[label] = centroid
        sims = normed_train[train_labels == label] @ centroid
        own_similarities.extend(sims.tolist())

    threshold = float(np.percentile(own_similarities, percentile))

    centroid_matrix = np.stack([centroids[label] for label in labels])  # (n_clusters, dim)
    sims = normed_holdout @ centroid_matrix.T  # (n_holdout, n_clusters)
    best_idx = sims.argmax(axis=1)

    results = []
    for i, idx in enumerate(best_idx):
        best_sim = float(sims[i, idx])
        results.append({
            "index": i,
            "cluster": labels[idx],
            "similarity": best_sim,
            "threshold": threshold,
            "fits_poorly": best_sim < threshold,
        })
    return results
