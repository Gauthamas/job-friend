import csv
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config
from style_exp import habits, headers, runlog


def main() -> None:
    files = headers.parse_samples(config.SAMPLES_DIR)
    cleaned_dir = config.OUT_DIR / "cleaned"

    rows = []
    for f in files:
        cleaned_text = (cleaned_dir / f"{f.sample_id}.txt").read_text(encoding="utf-8")
        rows.append(asdict(habits.measure_habits(f.sample_id, cleaned_text)))

    out_path = config.OUT_DIR / "habits.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    runlog.record(config.OUT_DIR, "08_habits", {"seed": config.SEED, "n_files": len(files)})
    print(f"Wrote {out_path}")
    for r in rows:
        print(f"  {r['sample_id']}: {r}")


if __name__ == "__main__":
    main()
