"""Milestone 10: the README structural
check (scripts/check_readme.py) runs clean against the real README.md, and
actually catches each kind of violation it's supposed to."""

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import check_readme  # noqa: E402

README_PATH = Path(__file__).resolve().parent.parent.parent / "README.md"


def test_real_readme_passes_the_check():
    text = README_PATH.read_text(encoding="utf-8")
    errors = (
        check_readme.check_no_numbered_sections_or_lists(text)
        + check_readme.check_results_tables_and_current_result(text)
        + check_readme.check_settings_table_matches_code(text)
        + check_readme.check_task_table_matches_code(text)
    )
    assert errors == []


def test_catches_a_numbered_heading():
    errors = check_readme.check_no_numbered_sections_or_lists("# Title\n\n## 1. Section\n")
    assert any("numbered heading" in e for e in errors)


def test_catches_a_numbered_list_item():
    errors = check_readme.check_no_numbered_sections_or_lists("# Title\n\n1. first step\n")
    assert any("numbered list item" in e for e in errors)


def test_catches_a_digit_in_a_results_table_cell():
    text = "## Results\n\n| Metric | Value |\n| --- | --- |\n| Something | 42 |\n"
    errors = check_readme.check_results_tables_and_current_result(text)
    assert any("digit" in e for e in errors)


def test_passes_a_results_table_of_all_dashes():
    text = "## Results\n\n| Metric | Value |\n| --- | --- |\n| Something | - |\n"
    assert check_readme.check_results_tables_and_current_result(text) == []


def test_catches_a_non_dash_current_result_line():
    errors = check_readme.check_results_tables_and_current_result("Current result: 42 passed\n")
    assert any("Current result" in e for e in errors)


def test_passes_the_correct_current_result_line():
    assert check_readme.check_results_tables_and_current_result("Current result: -\n") == []


def test_settings_table_check_catches_a_missing_setting():
    text = "## Settings\n\n| Name | Default | Range | Meaning | Editable on Settings page |\n| --- | --- | --- | --- | --- |\n| pair_k | 2 | integer >= 1 | x | yes |\n"
    errors = check_readme.check_settings_table_matches_code(text)
    assert any("missing" in e for e in errors)


def test_task_table_check_catches_an_unknown_task_name():
    text = (
        "## What the model does and does not do\n\n"
        "| Name | Input | Output | Thinking | Max tokens | Validated where |\n"
        "| --- | --- | --- | --- | --- | --- |\n"
        "| made_up_task | x | y | off | 100 | nowhere |\n"
    )
    errors = check_readme.check_task_table_matches_code(text)
    assert any("made_up_task" in e for e in errors)
