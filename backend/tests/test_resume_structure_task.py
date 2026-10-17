"""resume_structure must stay in /no_think mode -- a standing project rule
(CLAUDE.md), not a per-task default. Flipping it to /think was tried as a
fix for a real bug (a role listing "Responsibilities" plus a separate
"Requirements"/"Qualifications" sub-list had the second sub-heading's
lines silently dropped), and it did fix that case live, but was reverted:
it's not this task's call to make that tradeoff, and /think also made
call times unpredictable enough to time out on the simplest resume tried.
The sub-heading bug remains open, to be solved without touching
thinking mode."""

from app.llm.tasks import NO_THINK, REQUIREMENT_EXTRACT, RESUME_STRUCTURE, THINK


def test_resume_structure_stays_no_think():
    assert RESUME_STRUCTURE.system_prompt.strip().startswith(NO_THINK)
    assert not RESUME_STRUCTURE.system_prompt.strip().startswith(THINK)


def test_requirement_extract_prompt_covers_multiple_heading_styles():
    prompt = REQUIREMENT_EXTRACT.system_prompt
    for word in ("Responsibilities", "Accountabilities", "Requirements", "Qualifications"):
        assert word in prompt
