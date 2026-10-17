"""Clusters every non-holdout sentence at k=10, 15, 20. Writes
out/clusters_k{K}.json = {"ids": [...], "labels": [...]}, where ids are row
ids from sentences.jsonl, so 06/07/09 can rejoin by id."""

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config
from style_exp import cluster, io_utils, runlog


def main() -> None:
    rows = io_utils.read_jsonl(config.OUT_DIR / "sentences.jsonl")
    embeddings = np.load(config.OUT_DIR / "embeddings.npy")
    if len(rows) != len(embeddings):
        raise SystemExit("sentences.jsonl and embeddings.npy are out of sync -- rerun 04_embed.py")

    train_mask = np.array([not r["is_holdout"] for r in rows])
    train_ids = [r["id"] for r, keep in zip(rows, train_mask) if keep]
    train_embeddings = embeddings[train_mask]

    for k in config.CLUSTER_KS:
        labels = cluster.cluster_embeddings(train_embeddings, k, seed=config.SEED)
        out_path = config.OUT_DIR / f"clusters_k{k}.json"
        out_path.write_text(json.dumps({"ids": train_ids, "labels": labels.tolist()}), encoding="utf-8")
        print(f"k={k}: wrote {out_path} ({len(train_ids)} sentences)")

    runlog.record(config.OUT_DIR, "05_cluster", {
        "seed": config.SEED, "ks": config.CLUSTER_KS, "n_train_sentences": len(train_ids),
        "linkage": "average", "metric": "cosine",
    })


if __name__ == "__main__":
    main()
