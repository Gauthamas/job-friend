import threading

# Only one LLM call may be in flight at a time (spec §3: "Model calls are
# sequential — never parallel"). Nothing else serializes this across
# concurrent HTTP requests (e.g. a double-clicked Submit), so both real
# client methods acquire this before talking to LM Studio.
llm_call_lock = threading.Lock()
