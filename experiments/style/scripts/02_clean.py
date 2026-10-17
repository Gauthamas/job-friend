"""Cleans every sample's body and reports what was removed."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config
from style_exp import clean, headers, runlog


def main() -> None:
    files = headers.parse_samples(config.SAMPLES_DIR)
    cleaned_dir = config.OUT_DIR / "cleaned"
    cleaned_dir.mkdir(parents=True, exist_ok=True)

    summary = []
    for f in files:
        result = clean.clean_text(f.body)
        (cleaned_dir / f"{f.sample_id}.txt").write_text(result.text, encoding="utf-8")

        counts: dict[str, int] = {}
        for r in result.removed:
            counts[r.rule] = counts.get(r.rule, 0) + 1
        examples = [f"[{r.rule}] {r.text.strip()[:80]}" for r in result.removed[:3]]

        print(f"\n{f.sample_id}: removed {sum(counts.values())} -> {counts}")
        for ex in examples:
            print(f"  e.g. {ex}")

        summary.append({"sample_id": f.sample_id, "removed_counts": counts, "examples": examples})

    (config.OUT_DIR / "clean_report.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    runlog.record(config.OUT_DIR, "02_clean", {"seed": config.SEED, "n_files": len(files)})
    print(f"\nWrote cleaned files to {cleaned_dir} and out/clean_report.json")


if __name__ == "__main__":
    main()
