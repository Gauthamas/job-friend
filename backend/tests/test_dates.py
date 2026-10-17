import pytest

from app.llm.dates import normalize_month
from app.llm.schemas import RoleBullets


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Apr 2022", "2022-04"),
        ("April 2022", "2022-04"),
        ("apr. 2022", "2022-04"),
        ("04/2022", "2022-04"),
        ("4/2022", "2022-04"),
        ("2022-04", "2022-04"),
    ],
)
def test_normalize_month(raw, expected):
    assert normalize_month(raw) == expected


def test_unrecognized_value_passes_through():
    assert normalize_month("Present") == "Present"


def test_role_bullets_normalizes_start_and_end():
    role = RoleBullets(
        company="Acme", title="Engineer", start="Apr 2022", end="04/2023",
        section="work", bullets=["did stuff"],
    )
    assert role.start == "2022-04"
    assert role.end == "2023-04"
