"""Download one company's `companyfacts` JSON from the SEC. This is the only file in calcfinc
that can touch the network, and nothing else calls it: loading and parsing take JSON you
already have.

SEC fair-access rules (https://www.sec.gov/os/accessing-edgar-data):
- Send a User-Agent that identifies you with a real contact, e.g. "Jane Doe jane@example.com".
  Requests without one are refused. There is deliberately no default here.
- Stay under 10 requests per second. This helper spaces calls at least MIN_INTERVAL apart
  (5 per second), and does not retry on its own.
- Download once and keep the file; the data changes only when a company files.
"""
from __future__ import annotations

import gzip
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping

COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
MIN_INTERVAL = 0.2                      # seconds between requests: half the SEC's published limit

Opener = Callable[[urllib.request.Request], tuple[int, Mapping[str, str], bytes]]


class SecFetchError(Exception):
    pass


def _urlopen(request: urllib.request.Request) -> tuple[int, Mapping[str, str], bytes]:
    try:
        with urllib.request.urlopen(request, timeout=30) as response:      # noqa: S310 (https URL built here)
            return int(response.status), dict(response.headers), bytes(response.read())
    except urllib.error.HTTPError as e:
        return int(e.code), dict(e.headers), bytes(e.read())


_last_request = [float("-inf")]
_spacing = threading.Lock()


def fetch_companyfacts(cik: int | str, user_agent: str, *, opener: Opener = _urlopen,
                       sleep: Callable[[float], None] = time.sleep,
                       clock: Callable[[], float] = time.monotonic) -> bytes:
    """The raw JSON bytes for one CIK. Pass them to `read_companyfacts`."""
    if not isinstance(user_agent, str) or "@" not in user_agent:
        raise ValueError("user_agent must identify you with a contact address, for example "
                         "'Jane Doe jane@example.com'; the SEC refuses anonymous requests")
    try:
        number = int(str(cik).strip())
    except ValueError:
        raise ValueError(f"cik must be a number, got {cik!r}") from None
    if not 0 < number < 10**10:
        raise ValueError(f"cik must be between 1 and 9999999999, got {cik!r}")
    with _spacing:                       # callers on several threads queue here, MIN_INTERVAL apart
        wait = MIN_INTERVAL - (clock() - _last_request[0])
        if wait > 0:
            sleep(wait)
        _last_request[0] = clock()
    request = urllib.request.Request(COMPANYFACTS_URL.format(cik=number),
                                     headers={"User-Agent": user_agent, "Accept-Encoding": "gzip"})
    status, headers, body = opener(request)
    if status == 200:
        gzipped = {k.lower(): v for k, v in headers.items()}.get("content-encoding", "").lower() == "gzip"
        return gzip.decompress(body) if gzipped else body
    if status == 404:
        raise SecFetchError(f"the SEC has no companyfacts for CIK {number:010d} "
                            "(wrong CIK, or the company files no XBRL)")
    if status in (403, 429):
        raise SecFetchError(f"the SEC refused the request (HTTP {status}). Check that the User-Agent carries a "
                            "real contact and that you stay under 10 requests per second, then wait before retrying")
    raise SecFetchError(f"unexpected response from the SEC: HTTP {status}")
