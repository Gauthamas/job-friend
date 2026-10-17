"""Parses every samples/*.txt header, prints a table, and stops -- review it
before running 02_clean.py."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config
from style_exp import headers, runlog


def main() -> None:
    files = headers.parse_samples(config.SAMPLES_DIR)

    print(f"{'sample_id':30} {'kind':15} {'register':12} {'words':>6}")
    print("-" * 66)
    rows = []
    for f in files:
        wc = headers.word_count(f.body)
        print(f"{f.sample_id:30} {f.kind:15} {f.register:12} {wc:6d}")
        rows.append({"sample_id": f.sample_id, "kind": f.kind, "register": f.register, "word_count": wc})

    out_path = config.OUT_DIR / "headers.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")

    runlog.record(config.OUT_DIR, "01_parse_headers", {"seed": config.SEED, "n_files": len(files)})

    holdout_present = any(r["sample_id"] == Path(config.HOLDOUT_FILE).stem for r in rows)
    print(f"\nWrote {out_path}")
    print(f"Holdout file ({config.HOLDOUT_FILE}): {'found' if holdout_present else 'NOT FOUND -- check config.HOLDOUT_FILE'}")
    print("Review the table above, then run 02_clean.py.")


if __name__ == "__main__":
    main()
