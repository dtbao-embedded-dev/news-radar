"""The transport: one GET, done politely, with the failures a feed reader hits.

Layer 1. Standard library only - it imports nothing from the package, so it can
be exercised against a local http.server with no config and no feed parser in
sight.

`urllib.request` rather than `requests`: this is one GET with a header, a
timeout and a retry. A dependency would earn nothing here.

Contract: docs/memory-ai/data/news-sources.md (politeness and limits)
"""

from __future__ import annotations

import gzip
import logging
import socket
import time
import urllib.error
import urllib.request
import zlib
from urllib.parse import urlsplit

__all__ = ["Fetcher", "HttpError"]

log = logging.getLogger("news_radar.fetch.http")

# Statuses worth trying again. Everything else in 4xx is a decision about the
# request itself - Reddit's 403 answers the same way however many times it is
# asked, and retrying it only triples the delay before the run moves on.
RETRY_STATUSES = frozenset((408, 425, 429, 500, 502, 503, 504))


class HttpError(Exception):
    """A source could not be read. Carries the status when there was one."""

    def __init__(self, message, status=None, url=None):
        super().__init__(message)
        self.status = status
        self.url = url


class Fetcher:
    """A GET with a User-Agent, a timeout, retries, and a per-hostname gap.

    One instance per run: the throttle state lives on it, so every source in
    the run shares the same idea of how recently a host was asked.
    """

    def __init__(self, user_agent, timeout_s=15, max_retries=2, interval_ms=2000,
                 backoff_s=1.0):
        if not (user_agent or "").strip():
            # The 403 on both Reddit sources is caused by the default Python
            # User-Agent. An empty one is that same bug with an extra step, so
            # it is refused where it can still be fixed.
            raise ValueError(
                "user_agent must not be empty - Reddit answers 403 without one")
        self.user_agent = user_agent.strip()
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.interval_s = max(0.0, interval_ms / 1000.0)
        self.backoff_s = backoff_s
        self._last_request = {}  # hostname -> time.monotonic() of the last GET

    def _throttle(self, host):
        """Wait out the remainder of this host's interval, if any.

        Keyed by hostname, not by source id: `hn` and `hn_algolia` are
        different hosts and must not queue behind each other, while the fixed
        Reddit feed and the Reddit search are the same host and must.
        """
        last = self._last_request.get(host)
        if last is not None:
            wait = self.interval_s - (time.monotonic() - last)
            if wait > 0:
                log.debug("throttle: waiting %.2fs for %s", wait, host)
                time.sleep(wait)
        self._last_request[host] = time.monotonic()

    def get(self, url):
        """Fetch one URL. Returns the body as bytes, or raises HttpError."""
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise HttpError("not an http(s) url: {!r}".format(url), url=url)

        request = urllib.request.Request(url, headers={
            "User-Agent": self.user_agent,
            "Accept": "application/rss+xml, application/atom+xml, "
                      "application/xml, application/json;q=0.9, */*;q=0.8",
            # Google News and Reddit both send gzip whether or not it is asked
            # for; asking makes the saving deliberate and the decoding ours.
            "Accept-Encoding": "gzip, deflate",
        })

        last_error = None
        for attempt in range(self.max_retries + 1):
            if attempt:
                delay = self.backoff_s * (2 ** (attempt - 1))
                log.debug("retry %d/%d for %s in %.2fs",
                          attempt, self.max_retries, url, delay)
                time.sleep(delay)

            self._throttle(parts.hostname)
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_s) as resp:
                    return _decode(resp.read(), resp.headers.get("Content-Encoding"))
            except urllib.error.HTTPError as exc:
                last_error = HttpError("HTTP {} {}".format(exc.code, exc.reason),
                                       status=exc.code, url=url)
                if exc.code not in RETRY_STATUSES:
                    raise last_error from exc
            except (urllib.error.URLError, socket.timeout, TimeoutError,
                    ConnectionError, OSError) as exc:
                last_error = HttpError("{}: {}".format(type(exc).__name__, exc),
                                       url=url)

        raise last_error


def _decode(body, content_encoding):
    """Undo the transfer encoding the server actually used.

    A server may ignore Accept-Encoding and send plain bytes, or send gzip
    without being asked. The header is what decides, and a body that claims an
    encoding it does not have is returned as-is rather than losing the run.
    """
    encoding = (content_encoding or "").lower().strip()
    try:
        if encoding == "gzip":
            return gzip.decompress(body)
        if encoding == "deflate":
            return zlib.decompress(body, -zlib.MAX_WBITS)
    except (OSError, zlib.error) as exc:
        log.warning("body claimed %s but did not decompress (%s), using it raw",
                    encoding, exc)
    return body
