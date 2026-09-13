from crosscheck.ingest.chunker import chunk_text


def test_chunk_text_empty_returns_empty_list():
    assert chunk_text("") == []


def test_chunk_text_single_short_paragraph_returns_one_chunk():
    text = "Net sales were $3,075,121 thousand for the quarter."
    chunks = chunk_text(text, target_words=250)
    assert len(chunks) == 1
    assert chunks[0].text == text
    assert chunks[0].char_start == 0
    assert chunks[0].char_end == len(text)


def test_chunk_text_char_offsets_are_correct():
    text = "First paragraph here.\n\nSecond paragraph here.\n\nThird paragraph here."
    chunks = chunk_text(text, target_words=1)  # force each paragraph into its own window start
    for chunk in chunks:
        assert text[chunk.char_start : chunk.char_end] == chunk.text


def test_chunk_text_never_splits_mid_paragraph():
    paragraphs = [f"Paragraph number {i} with some words in it." for i in range(20)]
    text = "\n\n".join(paragraphs)
    chunks = chunk_text(text, target_words=15, overlap_words=5)
    assert len(chunks) > 1
    for chunk in chunks:
        # every chunk's text must be composed of whole paragraphs from the source
        for para in chunk.text.split("\n\n"):
            assert para.strip() in paragraphs


def test_chunk_text_produces_overlap_between_consecutive_chunks():
    paragraphs = [f"Paragraph {i}." for i in range(10)]
    text = "\n\n".join(paragraphs)
    chunks = chunk_text(text, target_words=5, overlap_words=3)
    assert len(chunks) > 1
    # consecutive chunks should share at least one paragraph given a nonzero overlap
    first_paras = set(chunks[0].text.split("\n\n"))
    second_paras = set(chunks[1].text.split("\n\n"))
    assert first_paras & second_paras
