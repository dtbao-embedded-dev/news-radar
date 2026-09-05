"""The transport: one request, done politely, with the failures the wire hits.

Layer 1. Standard library only - it imports nothing from the package, so it can
be exercised against a local http.server with no config and no feed parser in
sight.

`urllib.request` rather than `requests`: this is one request with a header, a
timeout and a retry. A dependency would earn nothing here.

Two callers, one code path. `get()` reads a feed, `post_json()` talks to a
notification channel, and both go through `_request()` so the User-Agent, the
timeout, the retry policy and the per-host gap are decided in one place.

Contract: docs/memory-ai/data/news-sources.md (politeness and limits)
"""

from __future__ import annotations

import gzip
import json
import logging
import socket
import time
import urllib.error
import urllib.request
import zlib
from urllib.parse import urlsplit

__all__ = ["Fetcher", "HttpError", "RETRY_AFTER_MAX"]

log = logging.getLogger("news_radar.fetch.http")

# Statuses worth trying again. Everything else in 4xx is a decision about the
# request itself - Reddit's 403 answers the same way however many times it is
# asked, and retrying it only triples the delay before the run moves on.
RETRY_STATUSES = frozenset((408, 425, 429, 500, 502, 503, 504))

# The longest `Retry-After` worth honouring. A server asking for fifteen minutes
# would stall a thirty-minute cycle past its own interval; recording the failure
# and moving on loses one message, waiting loses the whole run.
RETRY_AFTER_MAX = 60.0


class HttpError(Exception):
    """A request failed. Carries the status, the body and the asked-for delay.

    `body` matters on the notification side: a Telegram 400 says *why* in it
    (`chat not found`, `can't parse entities`), and that sentence is the whole
    difference between a fixable config and a mystery.
    """

    def __init__(self, message, status=None, url=None, body=b"",
                 retry_after=None):
        super().__init__(message)
        self.status = status
        self.url = url
        self.body = body
        self.retry_after = retry_after


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
        return self._request(url)

    def post_json(self, url, payload):
        """POST a JSON body. Returns the response body, or raises HttpError.

        Retried on the same statuses a GET is, which means a 5xx can deliver
        the same message twice. That is the trade the notification contract
        already takes: a duplicate is the acceptable failure, a silently
        dropped story is not.
        """
        return self._request(url, data=json.dumps(payload).encode("utf-8"),
                             content_type="application/json")

    def _request(self, url, data=None, content_type=None):
        """One attempt loop for both verbs. `data` is what makes it a POST."""
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise HttpError("not an http(s) url: {!r}".format(url), url=url)

        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/rss+xml, application/atom+xml, "
                      "application/xml, application/json;q=0.9, */*;q=0.8",
            # Google News and Reddit both send gzip whether or not it is asked
            # for; asking makes the saving deliberate and the decoding ours.
            "Accept-Encoding": "gzip, deflate",
        }
        if content_type:
            headers["Content-Type"] = content_type
        request = urllib.request.Request(url, data=data, headers=headers)

        last_error = None
        for attempt in range(self.max_retries + 1):
            if attempt:
                # The server's own number wins over our guess. A 429 is the one
                # answer that says *how long*, and both notification channels
                # send it; sleeping an exponential guess instead is how a bot
                # gets itself banned rather than throttled.
                delay = self.backoff_s * (2 ** (attempt - 1))
                if last_error is not None and last_error.retry_after is not None:
                    delay = last_error.retry_after
                log.debug("retry %d/%d for %s in %.2fs",
                          attempt, self.max_retries, url, delay)
                time.sleep(delay)

            self._throttle(parts.hostname)
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_s) as resp:
                    return _decode(resp.read(), resp.headers.get("Content-Encoding"))
            except urllib.error.HTTPError as exc:
                body = _error_body(exc)
                last_error = HttpError("HTTP {} {}".format(exc.code, exc.reason),
                                       status=exc.code, url=url, body=body,
                                       retry_after=_retry_after(exc.headers, body))
                if exc.code not in RETRY_STATUSES:
                    raise last_error from exc
            except (urllib.error.URLError, socket.timeout, TimeoutError,
                    ConnectionError, OSError) as exc:
                last_error = HttpError("{}: {}".format(type(exc).__name__, exc),
                                       url=url)

        raise last_error


def _error_body(exc):
    """The error response's body, or empty. Reading it must never raise."""
    try:
        return _decode(exc.read(), exc.headers.get("Content-Encoding"))
    except (OSError, AttributeError):
        return b""


def _seconds(raw):
    """A delay as a non-negative float, or None for anything unparseable.

    `Retry-After` is also allowed to be an HTTP-date. Nobody this project talks
    to sends one, so an unparseable value falls back to the exponential delay
    rather than earning a date parser.
    """
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return None


def _retry_after(headers, body):
    """How long the server asked us to wait, in seconds, capped, or None.

    The header first, then the JSON body, because the two channels disagree:
    Telegram nests it under `parameters.retry_after` and Discord puts it at the
    top level as a float, and neither guarantees the header alongside it.
    """
    value = _seconds(headers.get("Retry-After") if headers else None)

    if value is None:
        try:
            payload = json.loads(body.decode("utf-8", "replace"))
        except (ValueError, AttributeError):
            payload = None
        if isinstance(payload, dict):
            value = _seconds(payload.get("retry_after"))
            if value is None and isinstance(payload.get("parameters"), dict):
                value = _seconds(payload["parameters"].get("retry_after"))

    return None if value is None else min(value, RETRY_AFTER_MAX)


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
