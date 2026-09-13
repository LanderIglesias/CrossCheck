"""HTML filing -> clean plaintext.

Replaces the ad-hoc regex-based extraction used during Phase 0's manual claim reading with a
proper HTML parser, so numbers embedded in nested table cells extract in reading order without
mangling (e.g. "$ 3,075,121" rather than "$3,075,121" losing its digit grouping across tags).
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup
from bs4.element import Tag

# SEC filings are almost always table-based layouts (financial statements are <table>/<tr>/<td>)
# with narrative text in <p>/<div>. Splitting on these as paragraph-equivalent units is what
# gives the chunker real paragraph boundaries to work with — a flat `get_text(separator=" ")`
# over the whole document collapses everything into one giant blob with no break points at all.
_BLOCK_TAGS = ("p", "div", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6")


def _is_leaf_block(tag: Tag) -> bool:
    """True if `tag` is a block tag with no nested block tag descendant.

    Using only leaf blocks avoids emitting the same text twice for nested <div><div>...</div></div>
    structures (SEC filings nest divs heavily for styling).
    """
    return tag.name in _BLOCK_TAGS and not tag.find(_BLOCK_TAGS)


def extract_text(html: str) -> str:
    """Convert a filing's raw HTML into clean plaintext with real paragraph boundaries.

    Each leaf block-level element (a <p>, a <div> with no nested block, a table <tr>, an <li>,
    a heading) becomes one paragraph, joined by blank lines — this is what lets the chunker
    actually find break points instead of treating the whole filing as one chunk.
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()

    paragraphs: list[str] = []
    for block in soup.find_all(_is_leaf_block):
        block_text = block.get_text(separator=" ", strip=True)
        block_text = block_text.replace("\xa0", " ")
        block_text = re.sub(r"[ \t]+", " ", block_text).strip()
        if block_text:
            paragraphs.append(block_text)

    return "\n\n".join(paragraphs)
