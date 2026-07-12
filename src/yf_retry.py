"""
yf_retry.py — Shared retry-with-backoff helper for yfinance calls.

WHY THIS MODULE: Yahoo's unofficial API rate-limits fairly aggressively once
concurrent request volume goes up — confirmed empirically (2026-07) scanning
the full NASDAQ/NYSE universe (~8,200 tickers): requests started failing with
"Too Many Requests. Rate limited." past a few hundred tickers under 8
concurrent workers, and every subsequent ticker failed too (Yahoo's block
doesn't clear itself instantly). A permanent failure on the first rate-limit
hit would silently drop most of a large-universe scan, so this retries
transient rate-limit errors with exponential backoff instead of giving up
immediately.

Non-rate-limit errors (e.g. a genuinely delisted ticker with no data,
"possibly delisted; no price data found") are NOT retried — retrying those
just wastes time waiting for an outcome that will never change.
"""

from __future__ import annotations

import time
from typing import Callable, TypeVar

T = TypeVar("T")

RATE_LIMIT_MARKERS = ("too many requests", "rate limit")


def is_rate_limit_error(exc: Exception) -> bool:
    return any(marker in str(exc).lower() for marker in RATE_LIMIT_MARKERS)


def call_with_retry(func: Callable[[], T], max_retries: int = 4, base_delay: float = 8.0) -> T:
    """
    Calls func() and retries with exponential backoff (base_delay, 2x, 4x,
    8x, ...) ONLY when the failure looks like a Yahoo rate limit. Any other
    exception propagates immediately — no point retrying a truly missing
    ticker.
    """
    for attempt in range(max_retries + 1):
        try:
            return func()
        except Exception as exc:  # noqa: BLE001 - message is inspected to decide retry vs propagate
            if not is_rate_limit_error(exc) or attempt == max_retries:
                raise
            time.sleep(base_delay * (2 ** attempt))
    raise RuntimeError("unreachable")  # pragma: no cover
