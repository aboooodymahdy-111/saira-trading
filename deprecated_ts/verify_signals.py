"""
verify_signals.py — Phase 2: Verify Buy/Sell signal direction using real historical prices.

PURPOSE:
    For every (Buy date -> next Sell date) pair extracted in Phase 1, fetch the actual
    historical closing price on both dates via yfinance, and check whether the price
    actually moved in the direction TS claims:
        - Buy signal should be followed by a HIGHER price at the paired Sell date.
        - Sell signal should be followed by a LOWER price at the paired Buy date.
    This automates the manual review Abdo was doing by hand (the "≈opz" notes in the
    source Excel) — instead of eyeballing charts, we check the real numbers.

IMPORTANT CAVEATS (read before trusting the output):
    - yfinance is an unofficial, community-maintained wrapper around Yahoo Finance.
      It can break silently if Yahoo changes their site. If this script suddenly
      returns all failures, check https://github.com/ranaroussi/yfinance for known issues
      before assuming your signals are wrong.
    - Only PAST dates can be verified this way (there's no price history for the future).
      Future-dated signals are marked as "pending" — nothing to check yet.
    - This script was written but could NOT be executed in the assistant's sandbox
      (Yahoo Finance's hosts are not reachable from that network). Abdo: please run
      this yourself and report back what happens on the first run — especially any
      error messages — before relying on its output.

Run:
    python src/verify_signals.py
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import yfinance as yf

INPUT_CSV = Path("runs/signals_extracted.csv")
OUTPUT_CSV = Path("runs/signals_verified.csv")
PRICE_CACHE_DIR = Path("data/raw/price_cache")

# Per project decision (2026-07): keep every run, not just the latest — see
# extract_signals.py's ARCHIVE_DIR comment for the full rationale.
ARCHIVE_DIR = Path("runs/archive")

REQUEST_DELAY_SECONDS = 0.5  # be polite to the free API; avoid rate-limit / block risk


@dataclass
class VerificationResult:
    ticker: str
    target_label: str
    column_index: int
    buy_date: pd.Timestamp
    sell_date: pd.Timestamp
    buy_price: float | None
    sell_price: float | None
    price_moved_up: bool | None   # True/False if both prices found, None if unknown
    matches_ts_direction: bool | None
    status: str   # "verified", "pending_future", "price_unavailable"


def load_signals() -> pd.DataFrame:
    if not INPUT_CSV.exists():
        raise FileNotFoundError(
            f"{INPUT_CSV} not found — run extract_signals.py first (Phase 1)."
        )
    df = pd.read_csv(INPUT_CSV, parse_dates=["signal_date"])
    return df


def build_buy_sell_pairs(signals_df: pd.DataFrame) -> pd.DataFrame:
    """
    For each (ticker, column_index) group, pair each Buy with the very next Sell
    in sequence_position order. Assumes signals already alternate Buy/Sell as
    confirmed during Phase 1 inspection — any group that doesn't strictly alternate
    is flagged rather than silently mis-paired.
    """
    pairs = []
    for (ticker, col), group in signals_df.groupby(["ticker", "column_index"]):
        group = group.sort_values("sequence_position").reset_index(drop=True)
        target_label = group["target_label"].iloc[0]

        i = 0
        while i < len(group) - 1:
            cur = group.iloc[i]
            nxt = group.iloc[i + 1]
            if cur["signal_type"] == "Buy" and nxt["signal_type"] == "Sell":
                pairs.append({
                    "ticker": ticker,
                    "target_label": target_label,
                    "column_index": col,
                    "buy_date": cur["signal_date"],
                    "sell_date": nxt["signal_date"],
                })
                i += 2
            elif cur["signal_type"] == "Sell" and nxt["signal_type"] == "Buy":
                # Sequence starts on a Sell (already-reversed column) — pair Sell->Buy instead
                pairs.append({
                    "ticker": ticker,
                    "target_label": target_label,
                    "column_index": col,
                    "buy_date": nxt["signal_date"],   # kept in buy_date/sell_date slots
                    "sell_date": cur["signal_date"],  # for consistent downstream logic
                })
                i += 2
            else:
                # Two Buys or two Sells in a row - unexpected, skip this one signal
                # rather than guess, and move forward by 1 to resync.
                i += 1

    return pd.DataFrame(pairs)


def fetch_price_on_or_after(ticker: str, date: pd.Timestamp, price_cache: dict) -> float | None:
    """
    Fetch the closing price on the given date, or the next available trading day
    if the market was closed (weekend/holiday). Uses a small in-memory cache so
    each ticker's price history is only downloaded once per script run, not once
    per signal.
    """
    if ticker not in price_cache:
        try:
            hist = yf.Ticker(ticker).history(
                start=(date - pd.Timedelta(days=400)).strftime("%Y-%m-%d"),
                end=pd.Timestamp.today().strftime("%Y-%m-%d"),
            )
            price_cache[ticker] = hist
            time.sleep(REQUEST_DELAY_SECONDS)
        except Exception as exc:  # noqa: BLE001 - deliberately broad: any fetch failure -> None, logged
            print(f"WARNING: failed to fetch price history for {ticker}: {exc}")
            price_cache[ticker] = None

    hist = price_cache[ticker]
    if hist is None or hist.empty:
        return None

    hist_dates = hist.index.tz_localize(None) if hist.index.tz is not None else hist.index
    matches = hist[hist_dates >= date]
    if matches.empty:
        return None
    return float(matches.iloc[0]["Close"])


def verify_pairs(pairs_df: pd.DataFrame) -> list[VerificationResult]:
    results: list[VerificationResult] = []
    price_cache: dict = {}
    today = pd.Timestamp.today()

    total = len(pairs_df)
    for idx, row in pairs_df.iterrows():
        if idx % 200 == 0:
            print(f"Verifying pair {idx}/{total}...")

        if row["buy_date"] > today or row["sell_date"] > today:
            results.append(VerificationResult(
                ticker=row["ticker"], target_label=row["target_label"],
                column_index=row["column_index"], buy_date=row["buy_date"],
                sell_date=row["sell_date"], buy_price=None, sell_price=None,
                price_moved_up=None, matches_ts_direction=None,
                status="pending_future",
            ))
            continue

        buy_price = fetch_price_on_or_after(row["ticker"], row["buy_date"], price_cache)
        sell_price = fetch_price_on_or_after(row["ticker"], row["sell_date"], price_cache)

        if buy_price is None or sell_price is None:
            results.append(VerificationResult(
                ticker=row["ticker"], target_label=row["target_label"],
                column_index=row["column_index"], buy_date=row["buy_date"],
                sell_date=row["sell_date"], buy_price=buy_price, sell_price=sell_price,
                price_moved_up=None, matches_ts_direction=None,
                status="price_unavailable",
            ))
            continue

        price_moved_up = sell_price > buy_price
        results.append(VerificationResult(
            ticker=row["ticker"], target_label=row["target_label"],
            column_index=row["column_index"], buy_date=row["buy_date"],
            sell_date=row["sell_date"], buy_price=buy_price, sell_price=sell_price,
            price_moved_up=price_moved_up, matches_ts_direction=price_moved_up,
            status="verified",
        ))

    return results


def main() -> None:
    signals_df = load_signals()
    pairs_df = build_buy_sell_pairs(signals_df)
    print(f"Built {len(pairs_df)} Buy->Sell pairs from {signals_df['ticker'].nunique()} tickers.")

    results = verify_pairs(pairs_df)
    results_df = pd.DataFrame([r.__dict__ for r in results])

    run_timestamp = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
    results_df.insert(0, "run_timestamp", run_timestamp)

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    results_df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")

    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    archive_path = ARCHIVE_DIR / f"signals_verified_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.csv"
    results_df.to_csv(archive_path, index=False, encoding="utf-8-sig")
    print(f"Archived this run to: {archive_path.resolve()}")

    verified = results_df[results_df["status"] == "verified"]
    print()
    print(f"Status breakdown:\n{results_df['status'].value_counts().to_string()}")
    if not verified.empty:
        accuracy = verified["matches_ts_direction"].mean()
        print(f"\nOf {len(verified)} verifiable past signals: "
              f"{accuracy:.1%} matched TS's claimed direction.")

        # Per-column summary — this is what tells you which columns are actually reversed
        summary = (
            verified.groupby(["ticker", "target_label"])["matches_ts_direction"]
            .agg(["mean", "count"])
            .rename(columns={"mean": "accuracy", "count": "n_verified"})
            .sort_values("accuracy")
        )
        print("\nColumns with LOWEST direction-match accuracy (candidates for reversal):")
        print(summary.head(15).to_string())

    print(f"\nSaved full results to: {OUTPUT_CSV.resolve()}")


if __name__ == "__main__":
    main()
