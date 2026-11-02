import hashlib

import pytest

from crosscheck import config
from crosscheck.sources import decks


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config.settings, "data_dir", tmp_path)


def test_download_deck_is_idempotent(monkeypatch):
    raw = b"%PDF-1.4 fake deck bytes"

    class _Resp:
        content = raw
        headers = {"Content-Type": "application/pdf"}

        def raise_for_status(self):
            pass

    monkeypatch.setattr(decks.requests, "get", lambda *a, **k: _Resp())

    path1, hash1 = decks.download_deck("ACME", 2025, "Q2", "https://example.com/deck.pdf")
    path2, hash2 = decks.download_deck("ACME", 2025, "Q2", "https://example.com/deck.pdf")

    assert path1 == path2
    assert hash1 == hash2 == hashlib.sha256(raw).hexdigest()
    assert path1.exists()


def test_download_deck_reuses_local_copy_without_network(monkeypatch):
    raw = b"%PDF-1.4 already acquired"
    decks_dir = config.settings.raw_dir / "decks"
    decks_dir.mkdir(parents=True)
    digest = hashlib.sha256(raw).hexdigest()
    local = decks_dir / f"ACME_2025Q2_{digest[:12]}.pdf"
    local.write_bytes(raw)

    def _no_network(*a, **k):
        raise AssertionError("must not hit the network when the deck is on disk")

    monkeypatch.setattr(decks.requests, "get", _no_network)

    assert decks.download_deck("ACME", 2025, "Q2", "https://example.com/deck.pdf") == (
        local,
        digest,
    )


def test_download_deck_rejects_non_pdf_response(monkeypatch):
    class _Resp:
        content = b"<html>404 not found</html>"
        headers = {"Content-Type": "text/html"}

        def raise_for_status(self):
            pass

    monkeypatch.setattr(decks.requests, "get", lambda *a, **k: _Resp())

    with pytest.raises(decks.DeckResponseError):
        decks.download_deck("ACME", 2025, "Q2", "https://example.com/deck.pdf")
