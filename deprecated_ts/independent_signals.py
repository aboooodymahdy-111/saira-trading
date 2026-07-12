"""
independent_signals.py — Independent cross-check: classical technical signals + analyst consensus.

PURPOSE:
    Unlike verify_signals.py (which checks whether TS's OWN claimed direction matched
    what price actually did — an internal consistency check), this script produces a
    genuinely INDEPENDENT opinion on each stock/date, built from methods that have
    nothing to do with TS or astrology:

    1. MACD crossover: bullish (MACD line crosses above signal line) or bearish
       (crosses below) near the TS buy_date.
    2. Golden/Death Cross: 50-day MA crossing above (golden) or below (death) the
       200-day MA near the TS buy_date — a slower, longer-horizon trend signal.
    3. Analyst consensus: current analyst recommendation trend from yfinance
       (buy/hold/sell mix), as a fundamentally different (human, fundamentals-based)
       opinion rather than a technical one.

    The output tells you, for each TS signal, whether these independent methods AGREE
    or DISAGREE with TS's claimed direction — giving you a real second opinion, not
    just an internal consistency check.

IMPORTANT CAVEATS:
    - "Near the buy_date" for crossovers means: did a crossover happen within
      CROSSOVER_LOOKBACK_DAYS before the buy_date? A crossover happening 60 days
      earlier is much weaker evidence than one happening 3 days earlier — this
      script reports the number of days back, not just yes/no, so you can judge
      strength yourself rather than have it hidden behind a boolean.
    - Analyst consensus is CURRENT (as of when you run this script), not historical —
      yfinance does not provide historical analyst-recommendation snapshots for free.
      This means it's only meaningful for signals with a buy_date close to today,
      not for old past signals or far-future ones.
    - This script was NOT executed against live Yahoo Finance data in the assistant's
      sandbox (no network access there — see verify_signals.py docstring for why).
      The MACD/Golden Cross MATH was unit-tested offline against synthetic data;
      run this yourself and report the first output before trusting it.

INPUT: runs/signals_extracted.csv (Phase 1 output)
OUTPUT: runs/independent_signals.csv

Run:
    python src/independent_signals.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

INPUT_CSV = Path("runs/signals_extracted.csv")
OUTPUT_CSV = Path("runs/independent_signals.csv")

# Per project decision (2026-07): keep every run, not just the latest — see
# extract_signals.py's ARCHIVE_DIR comment for the full rationale.
ARCHIVE_DIR = Path("runs/archive")

MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
CROSSOVER_LOOKBACK_DAYS = 10  # how far back a crossover can be and still "count" as near the signal


def compute_macd(close: pd.Series) -> pd.DataFrame:
    """
    Standard MACD: fast EMA - slow EMA, plus a signal line (EMA of that).
    Returns a DataFrame with columns: macd, signal, histogram.
    """
    ema_fast = close.ewm(span=MACD_FAST, adjust=False).mean()
    ema_slow = close.ewm(span=MACD_SLOW, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=MACD_SIGNAL, adjust=False).mean()
    histogram = macd_line - signal_line
    return pd.DataFrame({"macd": macd_line, "signal": signal_line, "histogram": histogram})


def find_last_crossover(histogram: pd.Series, as_of_date: pd.Timestamp) -> tuple[str | None, int | None]:
    """
    Look backward from as_of_date through `histogram` (macd - signal, or MA50 - MA200)
    for the most recent sign change. A sign change from negative to positive = bullish
    crossover; positive to negative = bearish crossover.

    Excludes the first WARMUP_BARS of the series: EMAs/rolling means start equal (or
    very close) to each other before they've had enough data to diverge properly, which
    produces a spurious "crossover" right at the start of the series that has nothing
    to do with a real trend change. Confirmed via unit test (2026-07): a pure-uptrend
    series with no real reversal was falsely flagged as "bearish" on day 2 without this
    guard.

    Returns (direction, days_before_as_of_date) or (None, None) if no genuine crossover
    is found within CROSSOVER_LOOKBACK_DAYS, or if there isn't enough history yet.
    """
    WARMUP_BARS = 5  # skip the first few bars where the indicator is still initializing

    hist_dates = histogram.index.tz_localize(None) if histogram.index.tz is not None else histogram.index
    window_start = as_of_date - pd.Timedelta(days=CROSSOVER_LOOKBACK_DAYS + 5)  # buffer for weekends/holidays
    mask = (hist_dates >= window_start) & (hist_dates <= as_of_date)
    windowed = histogram[mask]

    if len(windowed) < 2:
        return None, None

    # Determine this window's position within the full series so we can exclude
    # crossovers that fall inside the warm-up region of the ORIGINAL series, not
    # just the windowed slice (a windowed slice always "starts" somewhere, but that
    # start is only a real warm-up if it coincides with the true start of `histogram`).
    warmup_cutoff = histogram.index[min(WARMUP_BARS, len(histogram) - 1)]

    signs = np.sign(windowed.values)
    for i in range(len(signs) - 1, 0, -1):
        if signs[i] != signs[i - 1] and signs[i] != 0:
            crossover_date = windowed.index[i]
            if crossover_date <= warmup_cutoff:
                continue  # spurious crossover from indicator initialization, not a real signal
            crossover_date_naive = crossover_date.tz_localize(None) if crossover_date.tz else crossover_date
            days_back = (as_of_date - crossover_date_naive).days
            if days_back > CROSSOVER_LOOKBACK_DAYS:
                return None, None
            direction = "bullish" if signs[i] > 0 else "bearish"
            return direction, days_back

    return None, None


def find_ma_cross(close: pd.Series, as_of_date: pd.Timestamp) -> tuple[str | None, int | None]:
    """Same crossover-detection logic, applied to (MA50 - MA200) instead of MACD histogram."""
    ma50 = close.rolling(50).mean()
    ma200 = close.rolling(200).mean()
    diff = ma50 - ma200
    return find_last_crossover(diff, as_of_date)


def fetch_analyst_consensus(ticker: str) -> str | None:
    """
    Current analyst recommendation trend from yfinance. Returns a simple label
    ('buy_lean', 'hold_lean', 'sell_lean') based on the most recent period's
    recommendation counts, or None if unavailable (delisted stock, no coverage, etc.)
    """
    try:
        rec = yf.Ticker(ticker).recommendations
        if rec is None or rec.empty:
            return None
        latest = rec.iloc[0]
        buy_count = latest.get("strongBuy", 0) + latest.get("buy", 0)
        sell_count = latest.get("strongSell", 0) + latest.get("sell", 0)
        hold_count = latest.get("hold", 0)

        total = buy_count + sell_count + hold_count
        if total == 0:
            return None
        if buy_count / total > 0.5:
            return "buy_lean"
        if sell_count / total > 0.5:
            return "sell_lean"
        return "hold_lean"
    except Exception as exc:  # noqa: BLE001 - one ticker's failure shouldn't stop the whole run
        print(f"WARNING: could not fetch analyst consensus for {ticker}: {exc}")
        return None


def evaluate_ticker_signals(ticker: str, buy_dates: list[pd.Timestamp], price_cache: dict) -> list[dict]:
    if ticker not in price_cache:
        try:
            hist = yf.Ticker(ticker).history(period="2y")
            if hist.empty:
                price_cache[ticker] = None
            else:
                macd_df = compute_macd(hist["Close"])
                price_cache[ticker] = {"close": hist["Close"], "macd_hist": macd_df["histogram"]}
        except Exception as exc:  # noqa: BLE001
            print(f"WARNING: could not fetch price history for {ticker}: {exc}")
            price_cache[ticker] = None

    data = price_cache[ticker]
    consensus = fetch_analyst_consensus(ticker)

    results = []
    for buy_date in buy_dates:
        if data is None:
            results.append({
                "ticker": ticker, "buy_date": buy_date,
                "macd_crossover": None, "macd_days_before": None,
                "ma_crossover": None, "ma_days_before": None,
                "analyst_consensus": consensus,
            })
            continue

        macd_dir, macd_days = find_last_crossover(data["macd_hist"], buy_date)
        ma_dir, ma_days = find_ma_cross(data["close"], buy_date)

        results.append({
            "ticker": ticker, "buy_date": buy_date,
            "macd_crossover": macd_dir, "macd_days_before": macd_days,
            "ma_crossover": ma_dir, "ma_days_before": ma_days,
            "analyst_consensus": consensus,
        })

    return results


def main() -> None:
    if not INPUT_CSV.exists():
        raise FileNotFoundError(f"{INPUT_CSV} not found — run extract_signals.py first (Phase 1).")

    signals_df = pd.read_csv(INPUT_CSV, parse_dates=["signal_date"])
    buy_signals = signals_df[signals_df["signal_type"] == "Buy"]

    print(f"Evaluating independent signals for {buy_signals['ticker'].nunique()} tickers, "
          f"{len(buy_signals)} Buy signals total. This will take a few minutes.")

    price_cache: dict = {}
    all_results = []
    for ticker, group in buy_signals.groupby("ticker"):
        print(f"Processing {ticker}...")
        buy_dates = group["signal_date"].tolist()
        all_results.extend(evaluate_ticker_signals(ticker, buy_dates, price_cache))

    result_df = pd.DataFrame(all_results)

    run_timestamp = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
    result_df.insert(0, "run_timestamp", run_timestamp)

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    result_df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")

    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    archive_path = ARCHIVE_DIR / f"independent_signals_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.csv"
    result_df.to_csv(archive_path, index=False, encoding="utf-8-sig")
    print(f"Archived this run to: {archive_path.resolve()}")

    print()
    print("MACD crossover direction breakdown (near each TS buy_date):")
    print(result_df["macd_crossover"].value_counts(dropna=False).to_string())
    print()
    print("MA (Golden/Death) crossover direction breakdown:")
    print(result_df["ma_crossover"].value_counts(dropna=False).to_string())
    print()
    print("Analyst consensus breakdown:")
    print(result_df["analyst_consensus"].value_counts(dropna=False).to_string())
    print(f"\nSaved to: {OUTPUT_CSV.resolve()}")


if __name__ == "__main__":
    main()
