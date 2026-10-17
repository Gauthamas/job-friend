"""Proves the StyleDistance model downloads and runs on CPU, and that it
actually separates register before you point it at real samples. Run this
first, before anything else.

8 sentences: casual/formal x 2 topics x 2 each. Asserts same-register pairs
average at least 0.1 more similar than different-register pairs.
"""

import sys
from itertools import combinations
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config
from style_exp.embed import get_model

SENTENCES = [
    ("casual", "weather", "it's so hot today, i can't even think straight lol"),
    ("casual", "weather", "ugh this heat is killing me, when's it gonna cool down"),
    ("casual", "work", "my boss is kinda annoying ngl, keeps pinging me for no reason"),
    ("casual", "work", "work's been a mess lately, i'm so done with these meetings"),
    ("formal", "weather", "the current heatwave has significantly exceeded seasonal temperature norms"),
    ("formal", "weather", "meteorological data indicates an extended period of elevated temperatures"),
    ("formal", "work", "the quarterly review highlighted several areas requiring immediate attention"),
    ("formal", "work", "management has scheduled additional meetings to address outstanding concerns"),
]


def main() -> None:
    model = get_model(config.EMBED_MODEL_NAME)
    texts = [s for _, _, s in SENTENCES]
    vectors = model.encode(texts, convert_to_numpy=True)
    normed = vectors / np.linalg.norm(vectors, axis=1, keepdims=True)
    sims = normed @ normed.T

    print(f"{'':28}" + "".join(f"{i:>6}" for i in range(len(SENTENCES))))
    for i, (register, topic, text) in enumerate(SENTENCES):
        print(f"{i:2} {register:7} {topic:8} " + "".join(f"{sims[i, j]:6.2f}" for j in range(len(SENTENCES))))

    same_register = []
    diff_register = []
    for i, j in combinations(range(len(SENTENCES)), 2):
        pair_sim = sims[i, j]
        if SENTENCES[i][0] == SENTENCES[j][0]:
            same_register.append(pair_sim)
        else:
            diff_register.append(pair_sim)

    same_mean = float(np.mean(same_register))
    diff_mean = float(np.mean(diff_register))
    gap = same_mean - diff_mean

    print(f"\nsame-register mean similarity: {same_mean:.3f}")
    print(f"different-register mean similarity: {diff_mean:.3f}")
    print(f"gap: {gap:.3f} (need >= 0.1)")

    assert gap >= 0.1, (
        f"StyleDistance did not separate register as expected (gap={gap:.3f} < 0.1). "
        "Don't trust the clustering output until this passes."
    )
    print("\nOK: same-register pairs are at least 0.1 more similar than different-register pairs.")


if __name__ == "__main__":
    main()
