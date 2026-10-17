"""Assigns each holdout sentence to its nearest cluster, for all three k
values, and flags the ones that fit poorly (below the 10th percentile of
training sentences' similarity to their own cluster's centroid)."""

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config
from style_exp import holdout as holdout_mod
from style_exp import io_utils, runlog


def main() -> None:
    rows = io_utils.read_jsonl(config.OUT_DIR / "sentences.jsonl")
    embeddings = np.load(config.OUT_DIR / "embeddings.npy")
    id_to_row = {r["id"]: r for r in rows}
    id_to_index = {r["id"]: i for i, r in enumerate(rows)}

    holdout_rows = [r for r in rows if r["is_holdout"]]
    if not holdout_rows:
        raise SystemExit("No holdout sentences found -- check config.HOLDOUT_FILE and 03_split_sentences.py")
    holdout_embeddings = np.stack([embeddings[id_to_index[r["id"]]] for r in holdout_rows])

    lines = ["# Holdout fit\n"]
    for k in config.CLUSTER_KS:
        data = json.loads((config.OUT_DIR / f"clusters_k{k}.json").read_text(encoding="utf-8"))
        train_ids = data["ids"]
        train_labels = np.array(data["labels"])
        train_embeddings = np.stack([embeddings[id_to_index[i]] for i in train_ids])

        results = holdout_mod.assign_holdout(
            train_embeddings, train_labels, holdout_embeddings, config.HOLDOUT_FIT_PERCENTILE,
        )

        n_poor = sum(1 for r in results if r["fits_poorly"])
        lines.append(f"## k={k} (threshold similarity: {results[0]['threshold']:.3f}, {n_poor}/{len(results)} fit poorly)\n")
        for res, row in zip(results, holdout_rows):
            flag = "POOR FIT" if res["fits_poorly"] else "ok"
            lines.append(f"- [{flag}] cluster {res['cluster']} sim={res['similarity']:.3f} -- {row['text']}")
        lines.append("")

        print(f"k={k}: {n_poor}/{len(results)} holdout sentences fit poorly")

    (config.OUT_DIR / "holdout.md").write_text("\n".join(lines), encoding="utf-8")
    runlog.record(config.OUT_DIR, "07_holdout", {
        "seed": config.SEED, "ks": config.CLUSTER_KS, "percentile": config.HOLDOUT_FIT_PERCENTILE,
        "n_holdout_sentences": len(holdout_rows),
    })
    print("Wrote out/holdout.md")


if __name__ == "__main__":
    main()
