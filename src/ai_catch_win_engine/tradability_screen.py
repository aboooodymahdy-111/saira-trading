"""
ai_catch_win_engine/tradability_screen.py — Mechanical tradability filter for
the AI Catch & Win universe (project decision, 2026-07: Abdo flagged IOTR as
an example of a "result" that isn't actually executable — 5.7% bid/ask spread
and a bid size of just 1 share, broker showing "Trade Notice" instead of a
normal buy button. Studying a stock you can't realistically enter/exit at the
analyzed price is pointless, so this excludes names with an unreasonably wide
spread before they ever reach a trade plan).

WHY SPREAD, NOT A BROKER RESTRICTION LIST: "Trade Notice"-style halts are
broker-specific (compliance/hard-to-borrow/reverse-split-pending flags) with
no public API this project can query. A wide bid/ask spread is the closest
MECHANICAL, universally-available proxy for "the market itself doesn't have
enough real liquidity to fill an order near the quoted price" — the two tend
to co-occur (both are symptoms of a thin/illiquid order book) even though
neither implies the other.

MAX_SPREAD_PCT = 2.0% is a starting default (IOTR's 5.7% fails it easily;
Abdo can tighten/loosen it here directly once he's seen it run against real
results).

Uses yahoo_fetch.fetch_bid_ask — the direct v7/finance/quote call, NOT the
yfinance library (2026-07: same "try Yahoo API not YF" reasoning as
etf_screen.py). This endpoint is separate from the v8/finance/chart one
fetch_ohlc/fetch_instrument_type rely on, so it carries its own risk of
needing Yahoo auth (crumb/cookie) that chart doesn't — hence failing OPEN
(keeps the ticker) on any lookup error or missing bid/ask, same rationale as
etf_screen.py: a bad spread slipping through occasionally costs less than
dropping a legitimate stock over a transient/endpoint issue.
"""

from __future__ import annotations

from yahoo_fetch import fetch_bid_ask
from yf_retry import call_with_retry

MAX_SPREAD_PCT = 2.0


def passes_tradability(ticker: str) -> bool:
    try:
        quote = call_with_retry(lambda: fetch_bid_ask(ticker))
    except Exception as exc:  # noqa: BLE001 - fail open, see module docstring
        print(f"WARNING: bid/ask lookup failed for {ticker}, keeping it ({exc})")
        return True

    bid, ask = quote.get("bid"), quote.get("ask")
    if not bid or not ask or bid <= 0:
        return True  # no usable quote to judge — don't punish for missing data

    spread_pct = (ask - bid) / bid * 100
    return spread_pct <= MAX_SPREAD_PCT


def filter_by_tradability(tickers: list[str]) -> list[str]:
    return [t for t in tickers if passes_tradability(t)]
