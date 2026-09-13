"""Plaintext -> overlapping word-count chunks, tracked by character offset.

Paragraph-boundary aware: chunks are built by greedily packing whole paragraphs (never splitting
mid-sentence) up to a target word count, then starting the next chunk with an overlap of whole
trailing paragraphs from the previous one. Financial filings are paragraph/table-row dense enough
that this avoids the mid-sentence-split failure mode of naive fixed-width character chunking.
"""

from __future__ import annotations

from dataclasses import dataclass

TARGET_WORDS = 250
OVERLAP_WORDS = 50


@dataclass(frozen=True)
class Chunk:
    chunk_index: int
    char_start: int
    char_end: int
    text: str


def _split_paragraphs(text: str) -> list[tuple[int, int, str]]:
    """Return (char_start, char_end, paragraph_text) for each non-empty paragraph in `text`."""
    paragraphs = []
    pos = 0
    for para in text.split("\n\n"):
        start = text.index(para, pos) if para else pos
        end = start + len(para)
        stripped = para.strip()
        if stripped:
            paragraphs.append((start, end, stripped))
        pos = end
    return paragraphs


def chunk_text(
    text: str, target_words: int = TARGET_WORDS, overlap_words: int = OVERLAP_WORDS
) -> list[Chunk]:
    """Chunk `text` into overlapping, paragraph-boundary-respecting windows."""
    paragraphs = _split_paragraphs(text)
    if not paragraphs:
        return []

    chunks: list[Chunk] = []
    i = 0
    chunk_index = 0
    while i < len(paragraphs):
        window: list[tuple[int, int, str]] = []
        word_count = 0
        j = i
        while j < len(paragraphs) and (word_count < target_words or not window):
            window.append(paragraphs[j])
            word_count += len(paragraphs[j][2].split())
            j += 1

        char_start = window[0][0]
        char_end = window[-1][1]
        chunk_text_value = text[char_start:char_end]
        chunks.append(Chunk(chunk_index, char_start, char_end, chunk_text_value))
        chunk_index += 1

        if j >= len(paragraphs):
            break

        # Step forward, but back up over trailing paragraphs worth ~overlap_words for the next
        # window's start, so consecutive chunks share context instead of hard-cutting.
        overlap_word_count = 0
        k = j - 1
        while k > i and overlap_word_count < overlap_words:
            overlap_word_count += len(paragraphs[k][2].split())
            k -= 1
        i = max(k + 1, i + 1)

    return chunks
