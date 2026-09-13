"""Investor deck PDF downloader.

Decks are not scraped — company IR sites vary too much to crawl reliably and safely. Instead a
hand-curated manifest maps (ticker, fiscal_year, fiscal_period) -> direct PDF URL, built during
the data-scouting step once the 5 companies are chosen. This module only downloads + dedups.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import requests

from crosscheck.config import settings
from crosscheck.io_utils import atomic_write_bytes

# Populated during data scouting (see db/data_scouting.md for the verification trail):
# {(ticker, fiscal_year, fiscal_period): pdf_url}
DECK_MANIFEST: dict[tuple[str, int, str], str] = {
    (
        "PPC",
        2020,
        "Q3",
    ): "https://ir.pilgrims.com/static-files/60bb1952-27cc-4256-8699-bd48d2ceefe2",
    ("DHR", 2020, "Q1"): (
        "https://filecache.investorroom.com/mr5ir_danaher/650/"
        "1Q2020%20Danaher%20Earnings%20Presentation.pdf"
    ),
    (
        "GE",
        2020,
        "Q1",
    ): "https://www.ge.com/sites/default/files/ge_webcast_presentation_04292020_0.pdf",
    ("TRV", 2020, "Q2"): (
        "https://s26.q4cdn.com/410417801/files/doc_financials/quarterly_results/2020/q2/"
        "ed012ea5-616a-7a4a-3a04-38a1ef782740.pdf"
    ),
    ("ADTN", 2020, "Q3"): (
        "https://s205.q4cdn.com/856112109/files/doc_financials/2020/"
        "Q3-2020-Earnings-Call-Supporting-Materials.pdf"
    ),
}

PDF_MAGIC = b"%PDF-"


class DeckResponseError(RuntimeError):
    """Raised when a deck URL doesn't actually return a PDF."""


def download_deck(ticker: str, fiscal_year: int, fiscal_period: str, url: str) -> tuple[Path, str]:
    """Download a deck PDF, returning (local_path, content_hash). Idempotent via content hash."""
    decks_dir = settings.raw_dir / "decks"
    decks_dir.mkdir(parents=True, exist_ok=True)

    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    raw_bytes = resp.content

    content_type = resp.headers.get("Content-Type", "")
    if "pdf" not in content_type.lower() and not raw_bytes.startswith(PDF_MAGIC):
        raise DeckResponseError(
            f"expected a PDF from {url}, got Content-Type={content_type!r} and body not "
            f"starting with {PDF_MAGIC!r} (likely an IR-site redirect or error page)"
        )

    digest = hashlib.sha256(raw_bytes).hexdigest()
    local_path = decks_dir / f"{ticker}_{fiscal_year}{fiscal_period}_{digest[:12]}.pdf"
    if not local_path.exists():
        atomic_write_bytes(local_path, raw_bytes)

    return local_path, digest
