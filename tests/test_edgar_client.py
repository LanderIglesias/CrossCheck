import json

import pytest

from crosscheck import config
from crosscheck.sources import edgar
from crosscheck.sources.edgar import content_hash


def test_content_hash_is_deterministic() -> None:
    a = content_hash(b"hello world")
    b = content_hash(b"hello world")
    assert a == b
    assert len(a) == 64  # sha256 hex digest


def test_content_hash_differs_for_different_input() -> None:
    assert content_hash(b"foo") != content_hash(b"bar")


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config.settings, "data_dir", tmp_path)
    monkeypatch.setattr(edgar, "_last_request_at", 0.0)


def test_get_json_rejects_html_error_page(monkeypatch):
    class _Resp:
        headers = {"Content-Type": "text/html; charset=utf-8"}
        status_code = 200

        def raise_for_status(self):
            pass

    monkeypatch.setattr(edgar.requests, "get", lambda *a, **k: _Resp())

    with pytest.raises(edgar.EdgarResponseError):
        edgar._get_json("https://data.sec.gov/fake")


def test_get_json_self_heals_from_corrupt_cache(monkeypatch):
    cache_file = edgar._cache_path("https://data.sec.gov/fake")
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text("{not valid json")

    class _Resp:
        headers = {"Content-Type": "application/json"}
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"ok": True}

    monkeypatch.setattr(edgar.requests, "get", lambda *a, **k: _Resp())

    result = edgar._get_json("https://data.sec.gov/fake")
    assert result == {"ok": True}
    assert json.loads(cache_file.read_text()) == {"ok": True}
