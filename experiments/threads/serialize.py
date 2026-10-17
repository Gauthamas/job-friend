"""dataclasses.asdict() chokes on sets (Thread.units); these convert each
record type to a plain JSON-able dict explicitly instead."""

from .data_model import Statement, Thread, VerifyResult


def statement_to_dict(s: Statement) -> dict:
    return {
        "pair_id": s.pair_id, "unit_a": s.unit_a, "unit_b": s.unit_b,
        "text": s.text, "source": s.source, "s_label": s.s_label,
    }


def thread_to_dict(t: Thread) -> dict:
    return {
        "label": t.label, "idea": t.idea,
        "supporting_statement_ids": list(t.supporting_statement_ids),
        "units": sorted(t.units), "coverage_yes": t.coverage_yes, "coverage_partly": t.coverage_partly,
    }


def verify_result_to_dict(v: VerifyResult) -> dict:
    return {
        "thread_label": v.thread_label, "unit_id": v.unit_id, "verdict": v.verdict,
        "quote": v.quote, "quote_exact": v.quote_exact,
    }
