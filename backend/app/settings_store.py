"""Milestone 7 part A: DB-backed overrides for the editable knobs in
app/config.py. Defaults stay in code -- a row in app_setting overrides its
key at startup; deleting the row restores the default. Unknown keys and
invalid values are logged and ignored (fall back to the default)."""

import json
import logging
import sqlite3
from typing import Any

from app.config import settings

logger = logging.getLogger("job_friend.settings")

# type: "int" | "float" | "bool" | "str" | "int_or_none"
# group: for the frontend's Settings page sections.
EDITABLE_SETTINGS: dict[str, dict] = {
    "judge_batch_size": {"type": "int", "group": "Judging", "min": 1},
    "judge_max_tokens": {"type": "int", "group": "Judging", "min": 1},
    "judge_start_min_left": {"type": "int", "group": "Judging", "min": 0},
    "judge_batch_thinking": {"type": "bool", "group": "Judging"},
    "enrich_question_context": {"type": "str", "group": "Enrichment"},
    "enrich_question_contribution": {"type": "str", "group": "Enrichment"},
    "enrich_question_outcome": {"type": "str", "group": "Enrichment"},
    "pair_k": {"type": "int", "group": "Pairs", "min": 1},
    "pair_n": {"type": "int_or_none", "group": "Pairs", "min": 0},
    "pair_global_on": {"type": "bool", "group": "Pairs"},
    "pair_max": {"type": "int", "group": "Pairs", "min": 1},
    "n_threads": {"type": "int", "group": "Threads", "min": 1},
    "min_support": {"type": "int", "group": "Threads", "min": 1},
    "thread_thinking": {"type": "bool", "group": "Threads"},
    "propose_threads_max_tokens": {"type": "int", "group": "Threads", "min": 1},
    "assign_unused_max_tokens": {"type": "int", "group": "Threads", "min": 1},
    "verify_thread_max_tokens": {"type": "int", "group": "Threads", "min": 1},
    "matched_sections": {"type": "int", "group": "Writing", "min": 0},
    "section_char_limit": {"type": "int_or_none", "group": "Writing", "min": 1},
}

# Pristine pydantic defaults, snapshotted the first time this module is
# imported -- before load_settings_from_db ever runs, so these never see
# a DB override.
def _snapshot(value: Any) -> Any:
    return list(value) if isinstance(value, list) else value


DEFAULTS: dict[str, Any] = {key: _snapshot(getattr(settings, key)) for key in EDITABLE_SETTINGS}


class InvalidSettingValue(ValueError):
    pass


def coerce(key: str, value: Any) -> Any:
    """Validates type/range for `key`. Raises InvalidSettingValue if `value`
    doesn't fit; otherwise returns the coerced value."""
    spec = EDITABLE_SETTINGS[key]
    kind = spec["type"]
    if kind == "bool":
        if not isinstance(value, bool):
            raise InvalidSettingValue(f"{key} must be a boolean")
        return value
    if kind == "str":
        if not isinstance(value, str):
            raise InvalidSettingValue(f"{key} must be a string")
        return value
    if kind == "str_list":
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise InvalidSettingValue(f"{key} must be a list of strings")
        return list(value)
    if kind == "int_or_none" and value is None:
        return None
    if kind in ("int", "int_or_none"):
        if isinstance(value, bool) or not isinstance(value, int):
            raise InvalidSettingValue(f"{key} must be an integer")
        if "min" in spec and value < spec["min"]:
            raise InvalidSettingValue(f"{key} must be >= {spec['min']}")
        return value
    raise InvalidSettingValue(f"unknown type for {key}")


def load_settings_from_db(conn: sqlite3.Connection) -> None:
    """Applies every stored override on top of the code defaults. Called
    once at startup, after migrations. Unknown keys and invalid values are
    logged and skipped -- the default (already on `settings`) stands."""
    rows = conn.execute("SELECT key, value_json FROM app_setting").fetchall()
    for row in rows:
        key = row["key"]
        if key not in EDITABLE_SETTINGS:
            logger.warning("app_setting has unknown key %r, ignoring", key)
            continue
        try:
            value = coerce(key, json.loads(row["value_json"]))
        except (json.JSONDecodeError, InvalidSettingValue) as e:
            logger.warning("app_setting %r has an invalid stored value, using default: %s", key, e)
            continue
        setattr(settings, key, value)


def current_value(key: str) -> Any:
    return getattr(settings, key)


def set_setting(conn: sqlite3.Connection, key: str, value: Any) -> Any:
    """Validates, persists, and applies immediately (no restart needed)."""
    if key not in EDITABLE_SETTINGS:
        raise InvalidSettingValue(f"unknown setting {key!r}")
    coerced = coerce(key, value)
    conn.execute(
        "INSERT INTO app_setting (key, value_json, updated_at) VALUES (?, ?, datetime('now')) "
        "ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at",
        (key, json.dumps(coerced)),
    )
    conn.commit()
    setattr(settings, key, coerced)
    return coerced


def reset_setting(conn: sqlite3.Connection, key: str) -> Any:
    """Deletes the stored override and restores the code default."""
    if key not in EDITABLE_SETTINGS:
        raise InvalidSettingValue(f"unknown setting {key!r}")
    conn.execute("DELETE FROM app_setting WHERE key = ?", (key,))
    conn.commit()
    default = _snapshot(DEFAULTS[key])
    setattr(settings, key, default)
    return default


def all_settings(conn: sqlite3.Connection) -> list[dict]:
    overridden = {
        row["key"] for row in conn.execute("SELECT key FROM app_setting").fetchall() if row["key"] in EDITABLE_SETTINGS
    }
    return [
        {
            "key": key,
            "group": spec["group"],
            "type": spec["type"],
            "default": DEFAULTS[key],
            "value": current_value(key),
            "is_default": key not in overridden,
        }
        for key, spec in EDITABLE_SETTINGS.items()
    ]
