import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config
from style_exp import io_utils, report, runlog


def main() -> None:
    rows_by_id = {r["id"]: r for r in io_utils.read_jsonl(config.OUT_DIR / "sentences.jsonl")}
    reports_dir = config.OUT_DIR / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    for k in config.CLUSTER_KS:
        data = json.loads((config.OUT_DIR / f"clusters_k{k}.json").read_text(encoding="utf-8"))
        clusters: dict[int, list[dict]] = {}
        for sid, label in zip(data["ids"], data["labels"]):
            clusters.setdefault(label, []).append(rows_by_id[sid])

        md = report.render_cluster_report(k, clusters, seed=config.SEED)
        out_path = reports_dir / f"clusters_k{k}.md"
        out_path.write_text(md, encoding="utf-8")
        print(f"k={k}: wrote {out_path} ({len(clusters)} clusters)")

    runlog.record(config.OUT_DIR, "06_report", {"seed": config.SEED, "ks": config.CLUSTER_KS})


if __name__ == "__main__":
    main()
