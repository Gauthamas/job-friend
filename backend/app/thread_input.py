import json


def build_propose_threads_message(statements: list[tuple[str, str]]) -> str:
    """statements: list of (small_statement_id, text)."""
    return json.dumps({"statements": [{"id": sid, "text": text} for sid, text in statements]})


def build_assign_unused_message(threads: list[tuple[str, str]], statement_id: str, statement_text: str) -> str:
    """threads: list of (small_thread_id, idea)."""
    return json.dumps({
        "threads": [{"id": tid, "idea": idea} for tid, idea in threads],
        "statement": {"id": statement_id, "text": statement_text},
    })


def build_verify_thread_message(thread_idea: str, unit_text: str) -> str:
    return json.dumps({"thread_idea": thread_idea, "unit_text": unit_text})
