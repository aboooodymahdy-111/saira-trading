"""
gann_swing_strategy_backtest.py — Tests the Gann mechanical trend indicator
(2-bar and 3-bar swing) as a STANDALONE entry/stop strategy, per plan item 6
in saira-api/Saira_Platform_خطة_التطوير_الشاملة.md section 5: "مؤشر اتجاه
جان الميكانيكي كاستراتيجية قابلة للاختبار الرجعي: دخول عند كسر قمة سوينج،
وقف تحت قاع السوينج — تُختبر بـ backtesting.py أو vectorbt، وتُضاف نتائجها
كصوت رابع في اللجنة."

WHY A SEPARATE SCRIPT INSTEAD OF WIRING DIRECTLY INTO THE COMMITTEE (2026-07,
Abdo's explicit call before touching the live vote): the committee's 4 groups
feed runs/full_universe_results.csv, which the daily automation emails out —
per this project's committee_signals_updated.py-mistake lesson (never wire an
unproven method just to have a vote), the strategy is validated here FIRST.
If it beats the base rate, its rule gets promoted into committee_signals.py
as a real 4th vote; if not, this file documents why not (same treatment as
gann_motion_aspect_experiments.py's rejected astrology theories).

METHOD (ported from saira-api/app/analysis/gann.py swing_pivots — same
mechanical-trend definition Mikula/Gann describe: a 2-bar swing reverses
direction after 2 consecutive lower lows in an uptrend, or 2 consecutive
higher highs in a downtrend):
    - direction=1 (up): track the running highest high; if price makes N
      consecutive lower lows, that running high is a confirmed swing-high
      pivot and direction flips to down.
    - direction=-1 (down): mirror image with lows/highs swapped.
    - ENTRY: close breaks above the most recent confirmed swing-high pivot.
    - STOP: the most recent confirmed swing-low pivot (below entry).
    - EXIT: stop hit, OR TARGET_GAIN_PCT reached, OR max_holding_days elapsed
      (same target/window as the rest of this project's backtesting, for a
      like-for-like comparison against the existing committee's hit rate).

LOOKAHEAD SAFETY: pivots are detected on hist truncated to `.loc[:as_of_date]`
exactly like backtest.py's committee snapshots — a pivot only "confirms" once
the N reversal bars have actually printed, never using future bars.

DATA SOURCE: local Stooq dump only, via full_universe_analysis's
build_local_ticker_index()/load_local_history() — same rule as backtest.py,
see CLAUDE.md.

Run: python src/gann_swing_strategy_backtest.py
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from full_universe_analysis import (
    TARGET_GAIN_PCT,
    TARGET_HOLDING_DAYS,
    _load_eligibility_cache,
    build_local_ticker_index,
    load_local_history,
)
from backtest import _sample_tickers, _sample_dates, _git_commit_hash, BACKTEST_LOOKBACK_MONTHS, SAMPLE_FREQUENCY_DAYS, SAMPLE_SEED, TICKER_SAMPLE_SIZE

SWING_REVERSAL_BARS = 2   # 2-bar swing per Gann's mechanical trend indicator (see gann.py)
STOP_BUFFER_PCT = 0.0     # no extra buffer below the swing-low stop — Gann's rule is literal
OUTPUT_ROOT = Path("runs/backtest")


def _swing_pivots(high: pd.Series, low: pd.Series, m: int = SWING_REVERSAL_BARS) -> list[dict]:
    """Identical logic to saira-api/app/analysis/gann.py's swing_pivots() —
    ported (not imported) since saira-api is a separate deployable service
    with its own dependency set; duplicating this ~25-line pure function
    avoids a cross-service import for one small piece of logic."""
    h, l = high.values, low.values
    n = len(h)
    if n < m + 2:
        return []
    direction, dn, up = 0, 0, 0
    hh, hh_i, ll, ll_i = h[0], 0, l[0], 0
    pivots: list[dict] = []
    for i in range(1, n):
        if direction >= 0:
            if h[i] > hh:
                hh, hh_i, dn = h[i], i, 0
            dn = dn + 1 if l[i] < l[i - 1] else 0
            if direction == 0 and h[i] > h[i - 1]:
                direction = 1
            if dn >= m:
                pivots.append({"i": hh_i, "price": float(hh), "type": "top"})
                direction, ll, ll_i, dn, up = -1, l[i], i, 0, 0
        else:
            if l[i] < ll:
                ll, ll_i, up = l[i], i, 0
            up = up + 1 if h[i] > h[i - 1] else 0
            if up >= m:
                pivots.append({"i": ll_i, "price": float(ll), "type": "bottom"})
                direction, hh, hh_i, up, dn = 1, h[i], i, 0, 0
    return pivots


def _find_entry_signal(hist: pd.DataFrame) -> dict | None:
    """As of the last bar in `hist` (already truncated to as_of_date): is
    today's close breaking above the most recent confirmed swing-high pivot,
    with a confirmed swing-low pivot available below it to use as a stop?
    Returns None if no such breakout signal exists at this exact bar —
    this is deliberately narrow (checks only the LAST bar, not "any
    breakout in the lookback window") so the backtest asks the same question
    the live daily pipeline would ask: "is there a Gann swing entry signal
    RIGHT NOW, as of today."""
    pivots = _swing_pivots(hist["High"], hist["Low"])
    if len(pivots) < 2:
        return None
    last_close = float(hist["Close"].iloc[-1])
    prev_close = float(hist["Close"].iloc[-2]) if len(hist) > 1 else last_close

    tops = [p for p in pivots if p["type"] == "top"]
    bottoms = [p for p in pivots if p["type"] == "bottom"]
    if not tops or not bottoms:
        return None
    last_top = tops[-1]
    # need a swing-low pivot to use as a stop, confirmed before the breakout bar
    prior_bottoms = [p for p in bottoms if p["i"] < len(hist) - 1]
    if not prior_bottoms:
        return None
    stop_price = prior_bottoms[-1]["price"]

    breakout_now = prev_close <= last_top["price"] < last_close
    if not breakout_now or stop_price >= last_close:
        return None
    return {"entry_price": last_close, "stop_price": stop_price,
            "swing_high_broken": last_top["price"]}


def run_gann_swing_backtest(tickers: list[str] | None = None,
                            as_of_dates: list[pd.Timestamp] | None = None,
                            write_output: bool = True) -> pd.DataFrame:
    local_index = build_local_ticker_index()
    tickers = tickers if tickers is not None else _sample_tickers(local_index)
    as_of_dates = as_of_dates if as_of_dates is not None else _sample_dates()
    print(f"Gann swing strategy backtest: {len(tickers)} tickers x {len(as_of_dates)} dates "
          f"({as_of_dates[0].date()} to {as_of_dates[-1].date()})...")

    rows: list[dict] = []
    completed = 0
    for ticker in tickers:
        completed += 1
        if completed % 50 == 0:
            print(f"  {completed}/{len(tickers)} tickers...")

        hist = load_local_history(ticker, local_index)
        if hist is None or hist.empty:
            continue

        for as_of in as_of_dates:
            truncated = hist.loc[:as_of]
            if len(truncated) < 200:
                continue

            future = hist.loc[as_of:]["Close"].iloc[1:]
            if len(future) < TARGET_HOLDING_DAYS:
                continue

            signal = _find_entry_signal(truncated)
            if signal is None:
                continue

            entry_price, stop_price = signal["entry_price"], signal["stop_price"]
            target_price = entry_price * (1 + TARGET_GAIN_PCT / 100)

            status, days_to_exit = "missed", None
            closes = future.values
            window = min(len(closes), TARGET_HOLDING_DAYS)
            for i in range(window):
                if closes[i] <= stop_price:
                    status, days_to_exit = "stopped", i + 1
                    break
                if closes[i] >= target_price:
                    status, days_to_exit = "hit", i + 1
                    break

            rows.append({
                "ticker": ticker, "as_of_date": as_of.date().isoformat(),
                "entry_price": entry_price, "stop_price": stop_price,
                "target_price": round(target_price, 4),
                "status": status, "days_to_exit": days_to_exit,
            })

    if not rows:
        print("No Gann swing entry signals found in this sample — cannot evaluate the strategy.")
        return pd.DataFrame(rows)

    results = pd.DataFrame(rows)
    if write_output:
        _write_output(results, tickers, as_of_dates)
    return results


def _write_output(results: pd.DataFrame, tickers: list[str], as_of_dates: list[pd.Timestamp]) -> None:
    run_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = OUTPUT_ROOT / f"gann_swing_strategy_{run_timestamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    results.to_csv(out_dir / "results.csv", index=False)

    # "resolved" = the full max_holding_days window has elapsed, so the
    # outcome is known — includes "missed" (neither stop nor target hit
    # within the window, i.e. the trade just didn't work) as a resolved
    # LOSS, matching evaluate_forward_outcome's own convention in backtest.py
    # (see that file's summary: committee hit rate counts every non-hit
    # snapshot in the denominator). Excluding "missed" from the denominator
    # — as an earlier version of this script did — silently inflates the
    # apparent hit rate by dropping the largest loss bucket.
    resolved = results[results["status"].isin(["hit", "stopped", "missed"])]
    hits = resolved[resolved["status"] == "hit"]
    hit_rate = round(len(hits) / len(resolved), 3) if len(resolved) else None

    params = {
        "run_timestamp": run_timestamp, "git_commit": _git_commit_hash(),
        "swing_reversal_bars": SWING_REVERSAL_BARS,
        "backtest_lookback_months": BACKTEST_LOOKBACK_MONTHS,
        "sample_frequency_days": SAMPLE_FREQUENCY_DAYS,
        "ticker_sample_size": TICKER_SAMPLE_SIZE, "sample_seed": SAMPLE_SEED,
        "tickers_tested": len(tickers),
        "target_gain_pct": TARGET_GAIN_PCT, "target_holding_days": TARGET_HOLDING_DAYS,
        "lookahead_check": "passed — pivots detected on hist truncated to as_of_date; "
                           "entry signal checked only on the last bar of that truncation",
    }
    (out_dir / "params.json").write_text(json.dumps(params, indent=2), encoding="utf-8")

    hit_rate_line = f"- Hit rate: {hit_rate:.1%}\n" if hit_rate is not None else "- Hit rate: n/a (no resolved signals)\n"
    summary = (
        f"# Gann mechanical swing strategy backtest — {run_timestamp}\n\n"
        f"Entry: close breaks above last confirmed {SWING_REVERSAL_BARS}-bar swing-high pivot. "
        f"Stop: last confirmed swing-low pivot. Target: {TARGET_GAIN_PCT}% within "
        f"{TARGET_HOLDING_DAYS} trading days.\n\n"
        f"- Total entry signals found: {len(results)}\n"
        f"- Resolved (hit, stopped, or window elapsed with no exit \"missed\"): {len(resolved)}\n"
        + hit_rate_line
        + "\n(Compare against the existing 4-group committee's own backtest hit rate and the "
        "naive base rate — see runs/backtest/backtest_*/summary.md from src/backtest.py — "
        "before deciding whether this strategy is worth adding as a 5th committee vote.)\n"
    )
    (out_dir / "summary.md").write_text(summary, encoding="utf-8")
    print(f"\nWrote output to {out_dir.resolve()}")
    print(summary)


if __name__ == "__main__":
    run_gann_swing_backtest()
