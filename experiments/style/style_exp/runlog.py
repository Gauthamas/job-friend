import json
import platform
import time
from pathlib import Path


def record(out_dir: Path, script: str, settings: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "script": script,
        "python": platform.python_version(),
        **settings,
    }
    with open(out_dir / "run_log.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
