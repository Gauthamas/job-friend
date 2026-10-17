"""Names every cross-group cluster from the k=15 clustering, using a local
LM Studio model. This is the ONLY script in this experiment that calls a
model -- everything else is clustering and reports.

The model's job is a one-sentence description plus a style/topic/unclear
flag; the evidence shown to you is always the real sentences from the
cluster, never anything the model wrote. A name that fails a check is
marked invalid and the run continues to the next cluster.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config
from style_exp import io_utils, name_clusters, report, runlog
from style_exp.cluster_stats import compute_stats

K_FOR_NAMING = 15


def refuse_unless_local(base_url: str) -> None:
    allowed_prefixes = ("http://localhost", "http://127.0.0.1")
    if not any(base_url.startswith(p) for p in allowed_prefixes):
        raise SystemExit(
            f"Refusing to call {base_url!r}: config.LLM_BASE_URL must start with "
            f"{allowed_prefixes!r}. This step only talks to a local model."
        )


def load_cross_group_clusters() -> dict[int, list[dict]]:
    rows_by_id = {r["id"]: r for r in io_utils.read_jsonl(config.OUT_DIR / "sentences.jsonl")}
    data = json.loads((config.OUT_DIR / f"clusters_k{K_FOR_NAMING}.json").read_text(encoding="utf-8"))

    clusters: dict[int, list[dict]] = {}
    for sid, label in zip(data["ids"], data["labels"]):
        clusters.setdefault(label, []).append(rows_by_id[sid])

    return {label: rows for label, rows in clusters.items() if compute_stats(rows).cross_group}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="print prompts, call nothing")
    args = parser.parse_args()

    refuse_unless_local(config.LLM_BASE_URL)

    cross_group = load_cross_group_clusters()
    print(f"{len(cross_group)} cross-group clusters out of k={K_FOR_NAMING}")

    client = None
    if not args.dry_run:
        from openai import OpenAI
        client = OpenAI(base_url=config.LLM_BASE_URL, api_key="lm-studio", max_retries=0)

    results = []
    for label in sorted(cross_group):
        rows = cross_group[label]
        example_rows = report.example_sentences(rows, config.LLM_MAX_SENTENCES_PER_CLUSTER, seed=config.SEED + label)
        sentences = [r["text"] for r in example_rows]
        prompt = name_clusters.build_prompt(sentences)

        print(f"\n=== cluster {label} ({len(rows)} sentences, {len(sentences)} shown to the model) ===")
        print(prompt)

        if args.dry_run:
            continue

        response = client.chat.completions.create(
            model=config.LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=config.LLM_TEMPERATURE,
            max_tokens=config.LLM_MAX_TOKENS,
        )
        raw_text = response.choices[0].message.content or ""
        name, flag = name_clusters.parse_response(raw_text)
        errors = name_clusters.validate_name(name, sentences, config.NAME_MAX_WORDS)
        valid = not errors and flag != "invalid"

        print(f"name: {name!r}")
        print(f"flag: {flag}")
        if errors:
            print(f"INVALID: {errors}")

        results.append({
            "cluster": label,
            "name": name,
            "flag": flag,
            "valid": valid,
            "errors": errors,
            "sentences": [{"sample_id": r["sample_id"], "text": r["text"]} for r in example_rows],
        })

    if args.dry_run:
        print("\n--dry-run: no model was called, nothing written.")
        return

    (config.OUT_DIR / "cluster_names.json").write_text(json.dumps(results, indent=2), encoding="utf-8")

    md_lines = [f"# Cluster names (k={K_FOR_NAMING}, cross-group clusters only)\n"]
    for r in results:
        status = "valid" if r["valid"] else f"INVALID: {r['errors']}"
        md_lines.append(f"## Cluster {r['cluster']} -- {status}\n")
        md_lines.append(f"**{r['name']}** ({r['flag']})\n")
        md_lines.append("Evidence:")
        for s in r["sentences"]:
            md_lines.append(f"- ({s['sample_id']}) {s['text']}")
        md_lines.append("")
    (config.OUT_DIR / "cluster_names.md").write_text("\n".join(md_lines), encoding="utf-8")

    runlog.record(config.OUT_DIR, "09_name_clusters", {
        "seed": config.SEED, "k": K_FOR_NAMING, "model": config.LLM_MODEL,
        "base_url": config.LLM_BASE_URL, "temperature": config.LLM_TEMPERATURE,
        "max_tokens": config.LLM_MAX_TOKENS, "n_clusters_named": len(results),
        "n_valid": sum(1 for r in results if r["valid"]),
    })
    print(f"\nWrote out/cluster_names.json and out/cluster_names.md ({len(results)} clusters)")


if __name__ == "__main__":
    main()
