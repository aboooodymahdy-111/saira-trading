"""
ai_catch_win_engine/etf_screen.py — Mechanical ETF exclusion filter for the
AI Catch & Win universe (project decision, 2026-07: Abdo wants stock-only
signals, no ETFs/ETNs in the analysis or results).

WHY THIS EXISTS: data/ai_catch_win_universe.csv is built by volatility_screen.py
from Abdo's local Stooq dump, which only walks the "nasdaq stocks"/"nyse
stocks" subfolders (see full_universe_analysis.py's EXCHANGE_SUBFOLDERS
comment) — but that folder split turned out to be unreliable for a handful of
recently-listed leveraged/inverse crypto ETFs (e.g. ETHT/ETHU/ETHD, BTCL/BTCZ,
XXRP), which showed up filed as "stocks" anyway and made it into the frozen
universe CSV. There is no asset-type column anywhere in the local pipeline to
filter on mechanically, so this mirrors ethical_screen.py's two-tier approach:
    1. NAMED-TICKER FALLBACK (KNOWN_ETF_TICKERS): the specific leveraged
       crypto ETFs already found in the universe — checked first, free, no
       network call, and still catches them even if the mechanical lookup
       below is unavailable/rate-limited.
    2. MECHANICAL CHECK (meta.instrumentType == "ETF" via Yahoo's chart API
       directly, NOT the yfinance library): generalizes to any ticker never
       seen before, so a future volatility_screen.py refresh that picks up a
       new ETF doesn't require a manual list update to catch it. Uses
       yahoo_fetch.fetch_instrument_type — the same direct v8/finance/chart
       call yahoo_fetch.py already relies on elsewhere (2026-07: switched away
       from the yfinance library here per Abdo's request, since yfinance's
       own cookie/crumb dance is exactly what made it unreliable enough
       locally to justify yahoo_fetch.py existing in the first place — see
       that module's docstring).

Fails OPEN (keeps the ticker) if the lookup itself errors out — an ETF
slipping through occasionally is a much smaller cost than dropping a
legitimate stock because of a transient network/rate-limit hiccup; anything
that has no tradable data at all gets filtered out downstream anyway (e.g.
fetch_ohlc in build_trade_plan).
"""

from __future__ import annotations

from yahoo_fetch import fetch_instrument_type
from yf_retry import call_with_retry

KNOWN_ETF_TICKERS: set[str] = {
    "ETHT",  # T-Rex 2X Long Ether Daily Target ETF
    "ETHU",  # Volatility Shares 2x Ether ETF
    "ETHD",  # T-Rex 2X Inverse Ether Daily Target ETF
    "BTCL",  # T-Rex 2X Long Bitcoin Daily Target ETF
    "BTCZ",  # T-Rex 2X Inverse Bitcoin Daily Target ETF
    "XXRP",  # Teucrium 2x Long Daily XRP ETF
}


def is_etf(ticker: str) -> bool:
    ticker = ticker.upper()
    if ticker in KNOWN_ETF_TICKERS:
        return True

    try:
        instrument_type = call_with_retry(lambda: fetch_instrument_type(ticker))
    except Exception as exc:  # noqa: BLE001 - fail open, see module docstring
        print(f"WARNING: instrumentType lookup failed for {ticker}, keeping it ({exc})")
        return False

    return instrument_type == "ETF"


def filter_out_etfs(tickers: list[str]) -> list[str]:
    return [t for t in tickers if not is_etf(t)]
