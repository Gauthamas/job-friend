"""Loads and validates config.yaml into a plain dataclass. Nothing else in
this package reads the YAML file directly."""

from dataclasses import dataclass
from pathlib import Path

import yaml

VALID_STRATEGIES = {"fixed", "random_cycle", "embedding"}
VALID_SOURCES = {"human", "model", "human_then_model"}


@dataclass
class MaxTokens:
    suggest_similarity: int = 150
    propose_threads: int = 595
    assign_unused: int = 200
    verify_thread: int = 200


@dataclass
class Config:
    endpoint: str
    model: str
    embed_model: str
    temperature: float
    max_tokens: MaxTokens
    request_timeout_s: float
    runs: int
    strategies: list[str]
    pairs_per_unit: int
    n_threads: int
    min_support: int
    statement_source: str
    seed: int
    thinking: bool
    out_dir: Path
    data_dir: Path
    pairs_file: Path | None = None


def _parse_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("on", "true", "1", "yes")


def validate_config(cfg: Config) -> list[str]:
    """Returns a list of error strings; empty means the config is fine."""
    errors = []
    for s in cfg.strategies:
        if s not in VALID_STRATEGIES:
            errors.append(f"unknown strategy {s!r}, must be one of {sorted(VALID_STRATEGIES)}")
    if not cfg.strategies:
        errors.append("strategies must list at least one strategy")
    if cfg.statement_source not in VALID_SOURCES:
        errors.append(f"unknown statement_source {cfg.statement_source!r}, must be one of {sorted(VALID_SOURCES)}")
    if cfg.min_support < 1:
        errors.append("min_support must be >= 1")
    if cfg.n_threads < 1:
        errors.append("n_threads must be >= 1")
    if cfg.runs < 1:
        errors.append("runs must be >= 1")
    if cfg.pairs_per_unit < 1:
        errors.append("pairs_per_unit must be >= 1")
    if cfg.temperature == 0 and cfg.runs > 1:
        errors.append(
            "temperature is 0 with runs > 1 -- stability will read as a flat 1.0 or 0.0 "
            "and won't tell you anything; use a non-zero temperature if you want runs to vary"
        )
    return errors


def load_config(path: Path) -> Config:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    mt_raw = raw.get("max_tokens", {}) or {}
    defaults = MaxTokens()
    cfg = Config(
        endpoint=raw["endpoint"],
        model=raw["model"],
        embed_model=raw["embed_model"],
        temperature=float(raw["temperature"]),
        max_tokens=MaxTokens(
            suggest_similarity=int(mt_raw.get("suggest_similarity", defaults.suggest_similarity)),
            propose_threads=int(mt_raw.get("propose_threads", defaults.propose_threads)),
            assign_unused=int(mt_raw.get("assign_unused", defaults.assign_unused)),
            verify_thread=int(mt_raw.get("verify_thread", defaults.verify_thread)),
        ),
        request_timeout_s=float(raw.get("request_timeout_s", 120)),
        runs=int(raw["runs"]),
        strategies=list(raw["strategies"]),
        pairs_per_unit=int(raw.get("pairs_per_unit", 2)),
        n_threads=int(raw["n_threads"]),
        min_support=int(raw["min_support"]),
        statement_source=raw["statement_source"],
        seed=int(raw["seed"]),
        thinking=_parse_bool(raw.get("thinking", "off")),
        out_dir=Path(raw["out_dir"]),
        data_dir=Path(raw.get("data_dir", "experiments/threads/data")),
        pairs_file=Path(raw["pairs_file"]) if raw.get("pairs_file") else None,
    )
    errors = validate_config(cfg)
    if errors:
        raise ValueError("invalid config:\n" + "\n".join(f"  - {e}" for e in errors))
    return cfg
