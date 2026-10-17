from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="JOB_FRIEND_", env_file=".env")

    db_path: str = "./job_friend.db"

    lm_studio_base_url: str = "http://localhost:1234/v1"
    llm_model: str = "qwen/qwen3-8b"
    embed_model: str = "text-embedding-nomic-embed-text-v2-moe"

    top_k: int = 5
    near_duplicate_threshold: float = 0.9

    # v2 draft 3 §3/§4: the judging window itself is fixed at 20 minutes,
    # not a setting (see app.judging.JUDGING_WINDOW_MINUTES) -- these are
    # the only configurable knobs left.
    judge_batch_size: int = 2
    judge_max_tokens: int = 810
    # Don't start a new batch with less than this many minutes left in the
    # window -- an estimate of one batch's duration, not a timeout.
    judge_start_min_left: int = 2
    # /think (True) vs /no_think (False) for the batch judge call. Tried
    # True at batch_size=2/max_tokens=1400: reasoning alone ate 78-85% of
    # the token budget, leaving too little room for 2 results per batch
    # (both calls hit finish_reason="length") and ran 7-8x slower overall
    # with no verdict-quality benefit observed -- reverted to False.
    judge_batch_thinking: bool = False

    # §5: fixed, not model-generated -- editable so wording can be tuned
    # without a code change. Answers go into the existing unit.context/
    # contribution/outcome columns.
    enrich_question_context: str = (
        "Situation: What was the situation, and what was wrong or missing before you acted?"
    )
    enrich_question_contribution: str = "Contribution: What exactly did you do yourself, and how?"
    enrich_question_outcome: str = (
        "Result: What changed afterwards, with a number or a concrete sign if you have one?"
    )

    # §6: pair builder. pair_n=None means "default = number of units",
    # computed per job since the job's own matched-unit count isn't known
    # at settings-load time.
    pair_k: int = 2
    pair_n: Optional[int] = None
    pair_global_on: bool = True
    # Hard cap on the rebuilt pair set -- answered pairs (written/none) are
    # always kept and count toward it, so the actual count can exceed this
    # when there are more answered pairs than the cap.
    pair_max: int = 11

    # §7: thread discovery.
    n_threads: int = 4
    min_support: int = 3
    thread_thinking: bool = False
    propose_threads_max_tokens: int = 600
    assign_unused_max_tokens: int = 200
    verify_thread_max_tokens: int = 200

    # §10/§11: writing view. matched_sections has a live stepper in the
    # view header (PATCH /api/settings/matched-sections) that updates this
    # process-wide, same as every other "editable in settings" knob here.
    matched_sections: int = 2
    # None means no character limit (the default) -- a section's text box
    # only shows a character counter when this is set.
    section_char_limit: Optional[int] = None


settings = Settings()
