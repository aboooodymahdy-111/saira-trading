"""
confirm_signals.py — Phase 3: Add technical confirmation layers on top of verified signals.

PURPOSE:
    Phase 2 told us whether TS's claimed Buy->Sell direction actually matched what the
    price did historically. That's a PAST-looking check. This phase adds FORWARD-looking
    confirmation for signals that are still pending (future buy dates) or already verified,
    using independent technical indicators that don't depend on TS or astrology at all:

    1. Volume confirmation: is trading volume around the buy date meaningfully above
       that stock's recent average? Higher volume = more conviction behind a move,
       a widely used confirmation heuristic (see coding-standards discussion).
    2. Trend confirmation: is the stock trading above or below its 50-day and 200-day
       moving averages at the buy date? Buying into an established uptrend is generally
       considered lower-risk than buying against the trend.
    3. RSI confirmation: is the stock already overbought (RSI > 70) right before a Buy
       signal? That's a mild warning sign the move may be exhausted already.

    None of these layers "prove" a signal is good. They are independent cross-checks
    that reduce (not eliminate) the chance of acting on a false positive — same logic
    used by the multi-factor screening approach discussed earlier in this project.

INPUT: runs/signals_verified.csv (produced by verify_signals.py on Abdo's machine —
    this script was NOT executed in the assistant's sandbox; see that file's docstring
    for why, and confirm Phase 2 ran successfully before trusting this phase's output).

OUTPUT: runs/signals_confirmed.csv — same rows as input, plus columns:
    volume_ratio, above_50dma, above_200dma, rsi_14, confirmation_score (0-4)

Run:
    python src/confirm_signals.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

INPUT_CSV = Path("runs/signals_verified.csv")
OUTPUT_CSV = Path("runs/signals_confirmed.csv")

# Per project decision (2026-07): keep every run, not just the latest — see
# extract_signals.py's ARCHIVE_DIR comment for the full rationale.
ARCHIVE_DIR = Path("runs/archive")

VOLUME_LOOKBACK_DAYS = 20      # "recent average volume" window
VOLUME_SPIKE_THRESHOLD = 1.3   # buy-date volume must be >= 1.3x the 20-day average to count as confirmed
RSI_PERIOD = 14
RSI_OVERBOUGHT = 70


def compute_rsi(close: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
    """
    Standard Wilder RSI. Returns NaN for the first `period` rows, where there isn't
    enough history yet — callers must handle NaN explicitly rather than treating it
    as 0 or "not overbought" (Pillar 3: fail loud, don't let NaN silently mean something).
    """
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    # avg_loss == 0 is ambiguous: could mean a pure uptrend (RSI should be 100) or
    # completely flat prices with zero gains too (RSI is undefined -> conventionally 50).
    # Distinguish the two cases explicitly rather than assuming one.
    pure_uptrend = (avg_loss == 0) & (avg_gain > 0)
    flat_price = (avg_loss == 0) & (avg_gain == 0)
    rsi = rsi.where(~pure_uptrend, 100.0)
    rsi = rsi.where(~flat_price, 50.0)
    return rsi


def fetch_price_history(ticker: str, price_cache: dict) -> pd.DataFrame | None:
    if ticker not in price_cache:
        try:
            hist = yf.Ticker(ticker).history(period="2y")
            if hist.empty:
                price_cache[ticker] = None
            else:
                hist = hist.copy()
                hist["MA50"] = hist["Close"].rolling(50).mean()
                hist["MA200"] = hist["Close"].rolling(200).mean()
                hist["VolAvg20"] = hist["Volume"].rolling(VOLUME_LOOKBACK_DAYS).mean()
                hist["RSI14"] = compute_rsi(hist["Close"])
                price_cache[ticker] = hist
        except Exception as exc:  # noqa: BLE001 - broad on purpose: log and continue, don't crash the whole run
            print(f"WARNING: failed to fetch extended history for {ticker}: {exc}")
            price_cache[ticker] = None
    return price_cache[ticker]


def row_on_or_after(hist: pd.DataFrame, date: pd.Timestamp) -> pd.Series | None:
    hist_dates = hist.index.tz_localize(None) if hist.index.tz is not None else hist.index
    matches = hist[hist_dates >= date]
    if matches.empty:
        return None
    return matches.iloc[0]


def confirm_row(ticker: str, buy_date: pd.Timestamp, price_cache: dict) -> dict:
    hist = fetch_price_history(ticker, price_cache)
    if hist is None:
        return {
            "volume_ratio": np.nan, "above_50dma": None, "above_200dma": None,
            "rsi_14": np.nan, "confirmation_score": np.nan,
            "confirmation_note": "price_history_unavailable",
        }

    day = row_on_or_after(hist, buy_date)
    if day is None:
        return {
            "volume_ratio": np.nan, "above_50dma": None, "above_200dma": None,
            "rsi_14": np.nan, "confirmation_score": np.nan,
            "confirmation_note": "date_out_of_range",
        }

    volume_ratio = (
        float(day["Volume"] / day["VolAvg20"])
        if pd.notna(day["VolAvg20"]) and day["VolAvg20"] > 0
        else np.nan
    )
    above_50dma = bool(day["Close"] > day["MA50"]) if pd.notna(day["MA50"]) else None
    above_200dma = bool(day["Close"] > day["MA200"]) if pd.notna(day["MA200"]) else None
    rsi = float(day["RSI14"]) if pd.notna(day["RSI14"]) else np.nan

    score = 0
    notes = []
    if not np.isnan(volume_ratio):
        if volume_ratio >= VOLUME_SPIKE_THRESHOLD:
            score += 1
        else:
            notes.append("low_volume")
    if above_50dma:
        score += 1
    elif above_50dma is False:
        notes.append("below_50dma")
    if above_200dma:
        score += 1
    elif above_200dma is False:
        notes.append("below_200dma")
    if not np.isnan(rsi):
        if rsi < RSI_OVERBOUGHT:
            score += 1
        else:
            notes.append("overbought_rsi")

    return {
        "volume_ratio": volume_ratio, "above_50dma": above_50dma, "above_200dma": above_200dma,
        "rsi_14": rsi, "confirmation_score": score,
        "confirmation_note": ",".join(notes) if notes else "clean",
    }


def main() -> None:
    if not INPUT_CSV.exists():
        raise FileNotFoundError(
            f"{INPUT_CSV} not found — run verify_signals.py first (Phase 2) on a machine "
            f"with internet access to Yahoo Finance."
        )

    df = pd.read_csv(INPUT_CSV, parse_dates=["buy_date", "sell_date"])
    print(f"Loaded {len(df)} verified signal pairs. Adding technical confirmation layers...")

    price_cache: dict = {}
    confirmations = []
    for idx, row in df.iterrows():
        if idx % 200 == 0:
            print(f"Confirming pair {idx}/{len(df)}...")
        confirmations.append(confirm_row(row["ticker"], row["buy_date"], price_cache))

    confirm_df = pd.DataFrame(confirmations)
    result_df = pd.concat([df.reset_index(drop=True), confirm_df], axis=1)

    run_timestamp = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
    result_df.insert(0, "run_timestamp", run_timestamp)

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    result_df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")

    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    archive_path = ARCHIVE_DIR / f"signals_confirmed_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.csv"
    result_df.to_csv(archive_path, index=False, encoding="utf-8-sig")
    print(f"Archived this run to: {archive_path.resolve()}")

    scored = result_df.dropna(subset=["confirmation_score"])
    print()
    print(f"Confirmation score distribution (0=no confirmation, 4=fully confirmed):")
    print(scored["confirmation_score"].value_counts().sort_index().to_string())
    print(f"\nSaved to: {OUTPUT_CSV.resolve()}")


if __name__ == "__main__":
    main()
