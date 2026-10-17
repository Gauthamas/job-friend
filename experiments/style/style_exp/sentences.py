"""Splits cleaned text into sentences with pysbd, and filters short ones.

Two entry points:
  - sentences_from_cleaned(): paragraph-aware, applies the min-word filter.
    Used for clustering input, where paragraph_index matters.
  - split_sentences(): no filter, no paragraph tracking. Used by habits.py,
    which wants every sentence (a one-word "Really?" is still a habit)."""

from dataclasses import dataclass

import pysbd

_segmenter = pysbd.Segmenter(language="en", clean=False)


@dataclass
class Sentence:
    text: str
    sample_id: str
    group_id: str
    kind: str
    register: str
    paragraph_index: int


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _segmenter.segment(text) if s.strip()]


def word_count(text: str) -> int:
    return len(text.split())


def sentences_from_cleaned(
    cleaned_text: str, sample_id: str, group_id: str, kind: str, register: str,
    min_words: int,
) -> list[Sentence]:
    paragraphs = [p for p in cleaned_text.split("\n\n") if p.strip()]
    out: list[Sentence] = []
    for p_idx, para in enumerate(paragraphs):
        for sent in split_sentences(para):
            if word_count(sent) < min_words:
                continue
            out.append(Sentence(sent, sample_id, group_id, kind, register, p_idx))
    return out
