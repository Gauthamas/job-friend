"""Per-sample writing-habit metrics. Runs on every sentence (no length
filter, unlike clustering input) -- a one-word "Really?" is still evidence
of a habit, and dropping it would understate the question/exclamation
counts."""

import re
from dataclasses import dataclass

from style_exp.sentences import split_sentences, word_count

CONTRACTION_RE = re.compile(r"\b\w+'(t|re|ll|ve|m|d|s)\b", re.IGNORECASE)
FIRST_PERSON_RE = re.compile(r"\b(i|me|my|mine|myself|we|us|our|ours)\b", re.IGNORECASE)


@dataclass
class Habits:
    sample_id: str
    n_sentences: int
    mean_words_per_sentence: float
    question_count: int
    contraction_count: int
    first_person_count: int
    exclamation_count: int


def measure_habits(sample_id: str, cleaned_text: str) -> Habits:
    sentences = split_sentences(cleaned_text)
    n = len(sentences)
    mean_words = sum(word_count(s) for s in sentences) / n if n else 0.0
    question_count = sum(1 for s in sentences if s.rstrip().endswith("?"))
    # Note: 's also matches a possessive ("the dog's bone"), not just a
    # contraction ("it's") -- a known over-count, acceptable for this
    # experiment's purpose (a rough per-sample habit signal, not a precise
    # linguistic count).
    contraction_count = len(CONTRACTION_RE.findall(cleaned_text))
    first_person_count = len(FIRST_PERSON_RE.findall(cleaned_text))
    exclamation_count = cleaned_text.count("!")
    return Habits(
        sample_id=sample_id, n_sentences=n, mean_words_per_sentence=round(mean_words, 2),
        question_count=question_count, contraction_count=contraction_count,
        first_person_count=first_person_count, exclamation_count=exclamation_count,
    )
