import pytest

from style_exp.sample_groups import build_lookup, normalize_sample_id, resolve_group_id, validate_groups


GROUPS = {"travelogue_trip1": ["email1", "email2"]}


def test_grouped_file_resolves_to_group_id():
    assert resolve_group_id("email1", GROUPS) == "travelogue_trip1"
    assert resolve_group_id("email2", GROUPS) == "travelogue_trip1"


def test_group_membership_accepts_dot_txt_suffix():
    groups_with_txt = {"travelogue_trip1": ["email1.txt", "email2.txt"]}
    assert resolve_group_id("email1", groups_with_txt) == "travelogue_trip1"


def test_normalize_sample_id_strips_extension_and_directory():
    assert normalize_sample_id("email1") == "email1"
    assert normalize_sample_id("email1.txt") == "email1"
    assert normalize_sample_id("samples/email1.txt") == "email1"


def test_ungrouped_file_is_its_own_group():
    assert resolve_group_id("cover_letter", GROUPS) == "cover_letter"


def test_empty_groups_config():
    assert resolve_group_id("anything", {}) == "anything"


def test_build_lookup_rejects_duplicate_membership():
    bad = {"g1": ["a"], "g2": ["a"]}
    with pytest.raises(ValueError):
        build_lookup(bad)


def test_validate_groups_flags_unknown_sample_id():
    errors = validate_groups(GROUPS, known_sample_ids={"email1"})
    assert len(errors) == 1
    assert "email2" in errors[0]


def test_validate_groups_passes_when_all_known():
    errors = validate_groups(GROUPS, known_sample_ids={"email1", "email2", "cover_letter"})
    assert errors == []
