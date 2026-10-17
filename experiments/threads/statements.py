"""Sources a statement text for each pair: human (from statements.json),
model (suggest_similarity.txt), or human_then_model (human when a pair is
present in the file, model otherwise)."""

from dataclasses import dataclass

from .config import Config
from .data_model import Statement
from .ids import pair_id
from .llm_client import CallResult, LlmClient
from .prompts import DEFAULT_SYSTEM_PROMPT


@dataclass
class StatementCallLog:
    pair_id: str
    call: CallResult | None  # None when no model call was made (human source)


def _from_human(a: str, b: str, human_map: dict) -> tuple[Statement, StatementCallLog] | None:
    """None return means "skip -- not present", per the fixed-pairs rule."""
    pid = pair_id(a, b)
    if pid not in human_map:
        return None
    text = human_map[pid]
    source = "human_none" if text is None else "human"
    return Statement(pair_id=pid, unit_a=a, unit_b=b, text=text, source=source), StatementCallLog(pid, None)


def _from_model(
    a: str, b: str, llm: LlmClient, cfg: Config, filled_prompt: str,
) -> tuple[Statement, StatementCallLog]:
    pid = pair_id(a, b)
    # filled_prompt is the suggest_similarity template with placeholders
    # already substituted by pipeline.py, which owns the placeholder names.
    call = llm.call_json(
        system_prompt=DEFAULT_SYSTEM_PROMPT, user_message=filled_prompt,
        temperature=cfg.temperature, max_tokens=cfg.max_tokens.suggest_similarity,
    )
    if not call.ok:
        return Statement(pair_id=pid, unit_a=a, unit_b=b, text=None, source="failed"), StatementCallLog(pid, call)

    similarity = call.parsed.get("similarity") if isinstance(call.parsed, dict) else None
    source = "model_none" if similarity is None else "model"
    return Statement(pair_id=pid, unit_a=a, unit_b=b, text=similarity, source=source), StatementCallLog(pid, call)


def source_statements(
    pairs: list[tuple[str, str]], cfg: Config, human_map: dict,
    llm: LlmClient, render_prompt,  # Callable[[unit_a_id, unit_b_id], str] -- see pipeline.py
) -> tuple[list[Statement], list[StatementCallLog]]:
    statements: list[Statement] = []
    logs: list[StatementCallLog] = []

    for a, b in pairs:
        if cfg.statement_source == "human":
            result = _from_human(a, b, human_map)
            if result is None:
                continue  # not present -- skipped, per the fixed-pairs rule
            stmt, log = result
        elif cfg.statement_source == "model":
            stmt, log = _from_model(a, b, llm, cfg, render_prompt(a, b))
        else:  # human_then_model
            result = _from_human(a, b, human_map)
            if result is not None:
                stmt, log = result
            else:
                stmt, log = _from_model(a, b, llm, cfg, render_prompt(a, b))

        statements.append(stmt)
        logs.append(log)

    return statements, logs
