"""Shared by 06_report.py and 09_name_clusters.py so "what counts as
cross-group" is defined in exactly one place."""

from collections import Counter
from dataclasses import dataclass


@dataclass
class ClusterStats:
    size: int
    n_groups: int
    n_kinds: int
    register_counts: dict[str, int]
    cross_group: bool


def compute_stats(rows: list[dict]) -> ClusterStats:
    """rows: sentence dicts with at least group_id, kind, register."""
    group_ids = {r["group_id"] for r in rows}
    kinds = {r["kind"] for r in rows}
    registers = Counter(r["register"] for r in rows)
    return ClusterStats(
        size=len(rows),
        n_groups=len(group_ids),
        n_kinds=len(kinds),
        register_counts=dict(registers),
        cross_group=len(group_ids) >= 2,
    )
