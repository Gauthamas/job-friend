import random

from style_exp.cluster_stats import compute_stats


def example_sentences(rows: list[dict], n: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    pool = list(rows)
    rng.shuffle(pool)
    return pool[:n]


def render_cluster_report(k: int, clusters: dict[int, list[dict]], seed: int, n_examples: int = 6) -> str:
    lines = [f"# Clusters, k={k}\n"]
    for label in sorted(clusters):
        rows = clusters[label]
        stats = compute_stats(rows)
        lines.append(f"## Cluster {label}\n")
        lines.append(f"- size: {stats.size}")
        lines.append(f"- sample groups: {stats.n_groups}")
        lines.append(f"- kinds: {stats.n_kinds}")
        lines.append(f"- registers: {stats.register_counts}")
        lines.append(f"- cross-group: {'yes' if stats.cross_group else 'no'}\n")
        lines.append("Examples:")
        # Reseeded per cluster+k so this is reproducible across runs, but
        # distinct clusters don't all pick the same relative positions.
        for row in example_sentences(rows, n_examples, seed=seed * 1000 + k + label):
            lines.append(f"- ({row['sample_id']}) {row['text']}")
        lines.append("")
    return "\n".join(lines)
