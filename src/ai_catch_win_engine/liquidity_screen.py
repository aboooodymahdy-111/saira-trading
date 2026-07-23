"""
ai_catch_win_engine/liquidity_screen.py — Mechanical price-cap + liquidity
filter for the AI Catch & Win universe (project decision, 2026-07: Abdo
raised the (previously nonexistent) price ceiling request to $50 max, and
turned the volume warning that already existed in ai_catch_win_email.py
(LOW_LIQUIDITY_VOLUME_THRESHOLD — "فيه أسهم الـVolume فيها أقل من 100 ألف")
into an actual exclusion instead of a manual-review flag).

WHY A BACKSTOP HERE, NOT JUST IN volatility_screen.py: that script only
shapes the NEXT frozen data/ai_catch_win_universe.csv Abdo regenerates on his
own machine every ~3 days — it can't retroactively fix the CSV already
committed. This runs on every load_universe() call (daily GitHub Actions job,
live network available there) so the price/volume rule is enforced
immediately regardless of when the frozen list itself gets refreshed —
same reasoning as etf_screen.py's mechanical check.

Fails OPEN (keeps the ticker) on a fetch error, same rationale as
etf_screen.py: a stale/rate-limited lookup shouldn't silently drop a
legitimate stock, and anything with no real data gets skipped later anyway
(e.g. fetch_ohlc inside build_trade_plan).
"""

from __future__ import annotations

from yahoo_fetch import fetch_ohlc

MAX_PRICE = 50.0
MIN_AVG_VOLUME_20D = 100_000  # same threshold ai_catch_win_email.py's LOW_LIQUIDITY_VOLUME_THRESHOLD warns on


def passes_price_and_liquidity(ticker: str) -> bool:
    try:
        hist = fetch_ohlc(ticker, rng="2mo", interval="1d")
    except Exception as exc:  # noqa: BLE001 - fail open, see module docstring
        print(f"WARNING: price/volume lookup failed for {ticker}, keeping it ({exc})")
        return True
    if hist is None or hist.empty:
        return True

    last_close = float(hist["Close"].iloc[-1])
    if last_close > MAX_PRICE:
        return False

    avg_volume_20d = float(hist["Volume"].tail(20).mean())
    if avg_volume_20d < MIN_AVG_VOLUME_20D:
        return False

    return True


def filter_by_price_and_liquidity(tickers: list[str]) -> list[str]:
    return [t for t in tickers if passes_price_and_liquidity(t)]
