"""SEC EDGAR + XBRL companyfacts client.

Rate-limited, disk-cached, and requires a compliant User-Agent per SEC's fair-access policy:
https://www.sec.gov/os/webmaster-faq#developers
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path
from typing import Any

import requests

from crosscheck.config import settings
from crosscheck.io_utils import atomic_write_bytes, atomic_write_text

SEC_MIN_INTERVAL_SECONDS = 0.11  # SEC's documented limit is 10 req/sec; stay comfortably under it
_last_request_at = 0.0
_throttle_lock = threading.Lock()


class EdgarResponseError(RuntimeError):
    """Raised when SEC returns a 200 that isn't the JSON payload we asked for."""


def _throttle() -> None:
    global _last_request_at
    with _throttle_lock:
        elapsed = time.monotonic() - _last_request_at
        if elapsed < SEC_MIN_INTERVAL_SECONDS:
            time.sleep(SEC_MIN_INTERVAL_SECONDS - elapsed)
        _last_request_at = time.monotonic()


def _cache_path(url: str) -> Path:
    cache_dir = settings.raw_dir / "edgar_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(url.encode()).hexdigest()
    return cache_dir / f"{digest}.json"


def _get_json(url: str) -> dict[str, Any]:
    cache_file = _cache_path(url)
    if cache_file.exists():
        try:
            return json.loads(cache_file.read_text())
        except json.JSONDecodeError:
            # A prior run cached a corrupt/partial payload (e.g. process killed mid-write, or a
            # non-JSON error page that slipped past validation in an older version of this
            # client). Treat it as a cache miss rather than trusting it forever.
            cache_file.unlink(missing_ok=True)

    _throttle()
    resp = requests.get(url, headers={"User-Agent": settings.sec_user_agent}, timeout=30)
    resp.raise_for_status()

    content_type = resp.headers.get("Content-Type", "")
    if "json" not in content_type.lower():
        raise EdgarResponseError(
            f"expected JSON from {url}, got Content-Type={content_type!r} "
            f"(SEC may have returned an HTML error page despite HTTP {resp.status_code})"
        )
    try:
        data: dict[str, Any] = resp.json()
    except json.JSONDecodeError as exc:
        raise EdgarResponseError(f"non-JSON body from {url}: {exc}") from exc

    atomic_write_text(cache_file, json.dumps(data))
    return data


def fetch_company_facts(cik: str) -> dict[str, Any]:
    """Fetch the full XBRL companyfacts document for a zero-padded 10-digit CIK."""
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
    return _get_json(url)


def fetch_submissions(cik: str) -> dict[str, Any]:
    """Fetch the filing index (10-Q/10-K list, dates, accession numbers) for a CIK."""
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    return _get_json(url)


def content_hash(raw_bytes: bytes) -> str:
    return hashlib.sha256(raw_bytes).hexdigest()


def fetch_filing_document(
    cik: str, accession_number: str, primary_document: str
) -> tuple[Path, str]:
    """Download a filing's primary document (e.g. the 10-Q .htm) from SEC's Archives.

    Returns (local_path, content_hash). Idempotent via content hash, like the other acquisition
    functions in this package.
    """
    accn_nodash = accession_number.replace("-", "")
    cik_nolead = str(int(cik))
    url = f"https://www.sec.gov/Archives/edgar/data/{cik_nolead}/{accn_nodash}/{primary_document}"

    filings_dir = settings.raw_dir / "filings"
    filings_dir.mkdir(parents=True, exist_ok=True)

    _throttle()
    resp = requests.get(url, headers={"User-Agent": settings.sec_user_agent}, timeout=30)
    resp.raise_for_status()

    content_type = resp.headers.get("Content-Type", "")
    if "html" not in content_type.lower() and "text" not in content_type.lower():
        raise EdgarResponseError(
            f"expected an HTML/text filing document from {url}, got Content-Type={content_type!r}"
        )

    raw_bytes = resp.content
    digest = content_hash(raw_bytes)
    local_path = filings_dir / f"{cik}_{accn_nodash}_{digest[:12]}_{primary_document}"
    if not local_path.exists():
        atomic_write_bytes(local_path, raw_bytes)
    return local_path, digest
