"""Embeds every sentence in sentences.jsonl. The only step that downloads
anything (the StyleDistance model, once, via sentence-transformers)."""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config
from style_exp import embed, io_utils, runlog


def main() -> None:
    rows = io_utils.read_jsonl(config.OUT_DIR / "sentences.jsonl")
    if not rows:
        raise SystemExit("out/sentences.jsonl is empty -- run 03_split_sentences.py first")

    texts = [r["text"] for r in rows]
    vectors = embed.embed_sentences(texts, config.EMBED_MODEL_NAME, config.EMBED_CACHE_PATH)

    out_path = config.OUT_DIR / "embeddings.npy"
    np.save(out_path, vectors)

    runlog.record(config.OUT_DIR, "04_embed", {
        "model": config.EMBED_MODEL_NAME, "n_sentences": len(rows), "dim": int(vectors.shape[1]),
    })
    print(f"Wrote {vectors.shape} to {out_path} (aligned to out/sentences.jsonl row order)")


if __name__ == "__main__":
    main()
