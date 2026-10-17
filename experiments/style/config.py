"""All settings for the style-clustering experiment in one place. Every
script imports this and logs the relevant bits to out/run_log.jsonl."""

from pathlib import Path

SEED = 42

ROOT = Path(__file__).parent
SAMPLES_DIR = ROOT / "samples"
OUT_DIR = ROOT / "out"

# The file held out of clustering and tested against it afterward. Its kind
# is whatever its own header says -- nothing here invents or overrides that.
HOLDOUT_FILE = "coverletter.txt"

# Files that are one sample group (e.g. two emails from the same trip), so a
# cluster that only draws on both of them isn't mistaken for drawing on two
# independent pieces of writing. Keys are your own names; values are sample
# filenames, with or without ".txt" -- same as HOLDOUT_FILE above, both
# forms resolve to the same sample id. A file not listed here is its own
# group.
GROUPS: dict[str, list[str]] = {
    "travelogue_trip1": ["travelogue", "travelogue2"],
}

MIN_SENTENCE_WORDS = 6
CLUSTER_KS = [10, 15, 20]
HOLDOUT_FIT_PERCENTILE = 10  # flag a holdout sentence below this percentile
                              # of training sentences' similarity to their
                              # own cluster centroid

EMBED_MODEL_NAME = "StyleDistance/styledistance"
EMBED_CACHE_PATH = OUT_DIR / "embeddings" / "cache.npz"

# Step 9 only -- the one step allowed to call a model, and only a local one.
LLM_BASE_URL = "http://localhost:1234/v1"
LLM_MODEL = "qwen/qwen3-8b"  # change to whatever you have loaded in LM Studio
LLM_TEMPERATURE = 0
LLM_MAX_TOKENS = 80
LLM_MAX_SENTENCES_PER_CLUSTER = 8
NAME_MAX_WORDS = 25
