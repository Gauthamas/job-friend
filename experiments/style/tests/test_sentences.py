from style_exp.sentences import sentences_from_cleaned, split_sentences, word_count


def test_split_sentences_basic():
    sents = split_sentences("This is one sentence. This is another one!")
    assert sents == ["This is one sentence.", "This is another one!"]


def test_word_count():
    assert word_count("one two three four") == 4


def test_min_words_filter_boundary():
    # Exactly 5 words: dropped. Exactly 6 words: kept.
    text = "Too short to keep here. Exactly six words long now yes."
    out = sentences_from_cleaned(text, "s1", "g1", "email", "formal", min_words=6)
    texts = [s.text for s in out]
    assert "Too short to keep here." not in texts
    assert "Exactly six words long now yes." in texts


def test_paragraph_index_tracked():
    text = "First paragraph has six words here.\n\nSecond paragraph also six words here."
    out = sentences_from_cleaned(text, "s1", "g1", "email", "formal", min_words=6)
    assert [s.paragraph_index for s in out] == [0, 1]


def test_metadata_carried_through():
    text = "This sentence has six words total."
    [s] = sentences_from_cleaned(text, "my_sample", "my_group", "article", "casual", min_words=6)
    assert s.sample_id == "my_sample"
    assert s.group_id == "my_group"
    assert s.kind == "article"
    assert s.register == "casual"
