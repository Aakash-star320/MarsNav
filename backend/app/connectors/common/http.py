"""Small HTTP helpers with timeouts, bounded retries and content checks (used for catalog queries and labels)."""
from __future__ import annotations

import time
from typing import Any

import httpx

DEFAULT_TIMEOUT = httpx.Timeout(45.0, connect=15.0)


class HttpFetchError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _get(url: str, retries: int, client: httpx.Client | None) -> httpx.Response:
    owns = client is None
    c = client or httpx.Client(follow_redirects=True, timeout=DEFAULT_TIMEOUT)
    last: Exception | None = None
    try:
        for attempt in range(retries + 1):
            try:
                r = c.get(url)
                if r.status_code == 200:
                    return r
                if r.status_code < 500:
                    raise HttpFetchError("bad_status", f"{url} answered {r.status_code}")
                last = HttpFetchError("server_error", f"{url} answered {r.status_code}")
            except httpx.TransportError as exc:
                last = exc
            if attempt < retries:
                time.sleep(0.5 * 2 ** attempt)
        raise HttpFetchError("unreachable", f"could not fetch {url} after {retries + 1} attempts: {last}")
    finally:
        if owns:
            c.close()


def get_text(url: str, retries: int = 2, client: httpx.Client | None = None) -> str:
    r = _get(url, retries, client)
    if "text/html" in r.headers.get("content-type", "") and not r.text.lstrip().startswith("ENVI"):
        raise HttpFetchError("bad_content", f"{url} returned an HTML page instead of the expected file")
    return r.text


def get_json(url: str, retries: int = 2, client: httpx.Client | None = None) -> dict[str, Any]:
    r = _get(url, retries, client)
    try:
        body = r.json() if "json" in r.headers.get("content-type", "") else __import__("json").loads(r.content.decode("utf-8-sig"))
    except ValueError as exc:
        raise HttpFetchError("bad_content", f"{url} did not return JSON") from exc
    if not isinstance(body, dict):
        raise HttpFetchError("bad_content", f"{url} returned unexpected JSON")
    return body
