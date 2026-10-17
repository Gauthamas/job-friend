"""Resolves a sample id to its group id, per config.GROUPS. A file not
listed in any group is its own group -- this is what lets the cluster
reports count "how many independent pieces of writing" a cluster draws on,
without two emails from the same trip inflating that count."""

from pathlib import Path


def normalize_sample_id(name: str) -> str:
    """"travelogue" and "travelogue.txt" (and any leading directory) all
    resolve to the same sample id, so config.HOLDOUT_FILE and
    config.GROUPS can be written in whichever form matches what you see
    in samples/, without the two having to agree on a convention."""
    return Path(name).stem


def build_lookup(groups: dict[str, list[str]]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for group_id, members in groups.items():
        for raw_id in members:
            sample_id = normalize_sample_id(raw_id)
            if sample_id in lookup:
                raise ValueError(f"sample id {sample_id!r} listed in two groups: {lookup[sample_id]!r} and {group_id!r}")
            lookup[sample_id] = group_id
    return lookup


def resolve_group_id(sample_id: str, groups: dict[str, list[str]]) -> str:
    lookup = build_lookup(groups)
    normalized = normalize_sample_id(sample_id)
    return lookup.get(normalized, normalized)


def validate_groups(groups: dict[str, list[str]], known_sample_ids: set[str]) -> list[str]:
    """Returns a list of error strings for group members that don't
    correspond to an actual sample file -- empty means the config is fine."""
    errors = []
    for group_id, members in groups.items():
        for raw_id in members:
            sample_id = normalize_sample_id(raw_id)
            if sample_id not in known_sample_ids:
                errors.append(
                    f"config.GROUPS[{group_id!r}] references unknown sample id {raw_id!r} "
                    f"(resolved to {sample_id!r})"
                )
    return errors
