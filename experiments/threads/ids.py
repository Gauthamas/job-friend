"""Pair-id formatting, shared by pairs.py and statements.py so every
strategy produces the same "U3-U4" shape regardless of how the pair was
chosen."""

import re

_TRAILING_NUMBER = re.compile(r"^(.*?)(\d+)$")


def pair_sort_key(unit_id: str):
    m = _TRAILING_NUMBER.match(unit_id)
    if m:
        return (0, int(m.group(2)), unit_id)
    return (1, 0, unit_id)


def pair_id(a: str, b: str) -> str:
    x, y = sorted([a, b], key=pair_sort_key)
    return f"{x}-{y}"


def split_pair_id(pid: str) -> tuple[str, str]:
    a, b = pid.split("-", 1)
    return a, b
