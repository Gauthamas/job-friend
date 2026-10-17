"""Shared dataclasses so the pipeline passes typed objects around instead
of loose dicts. Every field that's a statement or unit id refers back to
units.json / statements.json's own ids -- s_label and thread label are the
only ids this harness invents, and only for talking to the model."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Unit:
    id: str
    title: str
    text: str


@dataclass
class Statement:
    pair_id: str
    unit_a: str
    unit_b: str
    text: Optional[str]  # None means "none" (no relation) or unresolved
    # "human" | "human_none" | "model" | "model_none" | "failed"
    source: str
    s_label: str = ""  # set by pipeline.assign_labels(), only on real statements


@dataclass
class Thread:
    label: str  # "T1", "T2", ...
    idea: str
    supporting_statement_ids: list[str] = field(default_factory=list)  # pair ids
    units: set[str] = field(default_factory=set)
    coverage_yes: int = 0
    coverage_partly: int = 0


@dataclass
class VerifyResult:
    thread_label: str
    unit_id: str
    verdict: str  # "yes" | "partly" | "no"
    quote: str
    quote_exact: bool
