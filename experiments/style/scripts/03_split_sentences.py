"""Splits every cleaned sample into sentences. Writes two files:
  - sentences.jsonl: length-filtered, used for clustering (and holdout).
  - sentences_all.jsonl: unfiltered, used by habits.py.

Each row in sentences.jsonl gets a stable integer "id" (its line number) and
an "is_holdout" flag, so later steps can filter and rejoin by id."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config
from style_exp import headers, io_utils, runlog, sample_groups, sentences


def main() -> None:
    files = headers.parse_samples(config.SAMPLES_DIR)
    known_ids = {f.sample_id for f in files}

    group_errors = sample_groups.validate_groups(config.GROUPS, known_ids)
    if group_errors:
        for e in group_errors:
            print(f"config error: {e}")
        raise SystemExit(1)

    holdout_id = Path(config.HOLDOUT_FILE).stem
    if holdout_id not in known_ids:
        raise SystemExit(f"config.HOLDOUT_FILE={config.HOLDOUT_FILE!r} not found in samples/")

    cleaned_dir = config.OUT_DIR / "cleaned"

    filtered_rows = []
    all_rows = []
    next_id = 0
    for f in files:
        cleaned_text = (cleaned_dir / f"{f.sample_id}.txt").read_text(encoding="utf-8")
        group_id = sample_groups.resolve_group_id(f.sample_id, config.GROUPS)
        is_holdout = f.sample_id == holdout_id

        for sent in sentences.sentences_from_cleaned(
            cleaned_text, f.sample_id, group_id, f.kind, f.register, config.MIN_SENTENCE_WORDS,
        ):
            filtered_rows.append({
                "id": next_id, "text": sent.text, "sample_id": sent.sample_id,
                "group_id": sent.group_id, "kind": sent.kind, "register": sent.register,
                "paragraph_index": sent.paragraph_index, "is_holdout": is_holdout,
            })
            next_id += 1

        for text in sentences.split_sentences(cleaned_text):
            all_rows.append({"text": text, "sample_id": f.sample_id})

    io_utils.write_jsonl(config.OUT_DIR / "sentences.jsonl", filtered_rows)
    io_utils.write_jsonl(config.OUT_DIR / "sentences_all.jsonl", all_rows)

    n_holdout = sum(1 for r in filtered_rows if r["is_holdout"])
    runlog.record(config.OUT_DIR, "03_split_sentences", {
        "seed": config.SEED, "min_sentence_words": config.MIN_SENTENCE_WORDS,
        "n_sentences": len(filtered_rows), "n_holdout_sentences": n_holdout,
    })
    print(f"Wrote {len(filtered_rows)} sentences ({n_holdout} holdout) to out/sentences.jsonl")
    print(f"Wrote {len(all_rows)} unfiltered sentences to out/sentences_all.jsonl")


if __name__ == "__main__":
    main()
