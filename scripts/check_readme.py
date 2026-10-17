"""Milestone 10: structural checks for
README.md -- no measured number anywhere it shouldn't be, no numbered
sections/lists, and every settings/task row it lists actually exists in
the code with the stated default. Exits non-zero (with every violation
printed) on failure.

Usage: python scripts/check_readme.py [path/to/README.md]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")


def _sections(text: str) -> list[tuple[str, int, str]]:
    """[(heading_text, level, body), ...] -- body is everything up to the
    next heading of any level."""
    lines = text.splitlines()
    headings = [(i, m.group(2).strip(), len(m.group(1))) for i, line in enumerate(lines) if (m := _HEADING_RE.match(line))]
    sections = []
    for idx, (line_no, heading, level) in enumerate(headings):
        end = headings[idx + 1][0] if idx + 1 < len(headings) else len(lines)
        body = "\n".join(lines[line_no + 1 : end])
        sections.append((heading, level, body))
    return sections


def check_no_numbered_sections_or_lists(text: str) -> list[str]:
    errors = []
    for i, line in enumerate(text.splitlines(), start=1):
        if _HEADING_RE.match(line) and re.match(r"^#{1,6}\s+\d+[.)]\s", line):
            errors.append(f"line {i}: numbered heading: {line!r}")
        if re.match(r"^\s*\d+[.)]\s", line):
            errors.append(f"line {i}: numbered list item: {line!r}")
    return errors


def check_results_tables_and_current_result(text: str) -> list[str]:
    errors = []
    for heading, _level, body in _sections(text):
        if heading.strip().lower() == "results":
            for line in body.splitlines():
                if not line.strip().startswith("|"):
                    continue
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                if all(c in ("", "-", "---") or set(c) == {"-"} for c in cells):
                    continue  # header/separator row
                for cell in cells:
                    if re.search(r"\d", cell):
                        errors.append(f"results table cell contains a digit: {cell!r} (section {heading!r})")
    for i, line in enumerate(text.splitlines(), start=1):
        if line.strip().lower().startswith("current result:"):
            if line.strip() != "Current result: -":
                errors.append(f"line {i}: 'Current result' line must read exactly 'Current result: -': {line!r}")
    return errors


def _parse_md_table(body: str) -> list[dict[str, str]]:
    lines = [ln for ln in body.splitlines() if ln.strip().startswith("|")]
    if len(lines) < 2:
        return []
    headers = [c.strip() for c in lines[0].strip("|").split("|")]
    rows = []
    for line in lines[2:]:  # skip header + separator
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) != len(headers):
            continue
        rows.append(dict(zip(headers, cells)))
    return rows


def check_settings_table_matches_code(text: str) -> list[str]:
    from app.settings_store import DEFAULTS, EDITABLE_SETTINGS

    errors = []
    for heading, _level, body in _sections(text):
        if heading.strip().lower() != "settings":
            continue
        rows = _parse_md_table(body)
        listed = {r["Name"]: r for r in rows if "Name" in r}
        for key, spec in EDITABLE_SETTINGS.items():
            if key not in listed:
                errors.append(f"settings table missing {key!r}")
                continue
            default_str = listed[key]["Default"]
            expected = DEFAULTS[key]
            if expected is None:
                ok = default_str.strip().lower() in ("empty", "none", "-")
            elif isinstance(expected, list):
                ok = (not expected and default_str.strip() in ("[]", "empty")) or (
                    expected and expected[0] in default_str
                )
            else:
                ok = str(expected) in default_str
            if not ok:
                errors.append(f"settings table default for {key!r} is {default_str!r}, code default is {expected!r}")
        for name in listed:
            if name not in EDITABLE_SETTINGS:
                errors.append(f"settings table lists {name!r}, which isn't in app.settings_store.EDITABLE_SETTINGS")
    return errors


def check_task_table_matches_code(text: str) -> list[str]:
    from app.llm import tasks as tasks_module

    task_profiles = {
        v.name: v for v in vars(tasks_module).values() if hasattr(v, "name") and hasattr(v, "max_tokens")
    }
    errors = []
    for heading, _level, body in _sections(text):
        if heading.strip().lower() != "what the model does and does not do":
            continue
        rows = _parse_md_table(body)
        listed = {r["Name"]: r for r in rows if "Name" in r}
        for name in task_profiles:
            if name not in listed:
                errors.append(f"task table missing {name!r}")
        for name in listed:
            if name not in task_profiles:
                errors.append(f"task table lists {name!r}, which isn't a TaskProfile in app.llm.tasks")
    return errors


def main() -> int:
    readme_path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "README.md"
    text = readme_path.read_text(encoding="utf-8")

    all_errors = []
    all_errors += check_no_numbered_sections_or_lists(text)
    all_errors += check_results_tables_and_current_result(text)
    all_errors += check_settings_table_matches_code(text)
    all_errors += check_task_table_matches_code(text)

    if all_errors:
        print(f"{readme_path}: {len(all_errors)} problem(s):")
        for e in all_errors:
            print(f"  - {e}")
        return 1
    print(f"{readme_path}: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
