"""Plain-Python vector math -- no numpy, per the stdlib-only constraint.
Ten units means these lists are tiny; readability matters more than speed."""

import math


def normalize(v: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in v))
    if norm == 0:
        return list(v)
    return [x / norm for x in v]


def cosine(a: list[float], b: list[float]) -> float:
    na, nb = normalize(a), normalize(b)
    return sum(x * y for x, y in zip(na, nb))
