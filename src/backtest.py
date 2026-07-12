"""
backtest.py — One-time/on-demand historical simulation of the full committee
system, per Abdo's request (2026-07): "would this system actually have made
money over the past 3-6 months?" Simulates what the committee would have
recommended at points in the past, then scores those simulated calls against
what ACTUALLY happened afterward (which we now know).

NOT part of the daily automation (.github/workflows/daily-scan.yml) — this is
compute-heavy (hundreds of tickers x tens of historical dates, each running
the full indicator/calibration stack) and meant to be run by hand:

    python src/backtest.py

LOOKAHEAD SAFETY (see preflight-checklist.md section A — "no feature uses
data that wouldn't have been known at prediction time"):
    - Every group evaluator (technical/quantitative/astrological/advanced
      technical) is called via full_universe_analysis.evaluate_ticker_snapshot
      with `hist` TRUNCATED to `.loc[:as_of_date]` — nothing after that date
      is ever visible to the decision logic.
    - `include_analyst_consensus=False`: yfinance's analyst consensus is a
      CURRENT-only snapshot with no historical point-in-time equivalent, so
      it's dropped for backtest scoring only (see
      committee_signals.evaluate_quantitative_group). The live daily system
      is unaffected.
    - Verified (2026-07, see project plan notes): evaluate_horizon_fit, Pivot
      Points, Ichimoku, and the Gann Square9/ZigZag pivot detection are all
      safe on truncated input by construction — no code changes were needed
      for those, this is documentation of that check, not a fix.
    - CAVEAT (not a lookahead bug, but affects dollar-level precision):
      yfinance's history() returns split/dividend-ADJUSTED prices as of
      TODAY'S fetch, not as literally traded on the historical date — this
      affects signal magnitude/price levels slightly, not signal direction.

FETCH_PERIOD margin: the binding lookback constraint is compute_ma_cross_vote
needing MA200 (200 trading days) and Ichimoku needing 78 — NOT the Gann
calibration's smaller CALIBRATION_LOOKBACK_BARS. "3y" leaves ~620 trading
days of history behind even the EARLIEST as-of date in a 6-month backtest
window, comfortably clearing the 200-bar requirement.

BASE-RATE COMPARISON: every analyzed (ticker, date) snapshot gets an
entry/exit level from compute_entry_exit_levels regardless of the committee's
vote — so besides scoring net-buy calls, this also scores EVERY analyzed
snapshot the same way, as the naive baseline the committee's own selectivity
should beat.
"""

from __future__ import annotations

import json
import random
import subprocess
from datetime import datetime
from pathlib import Path

import pandas as pd
import yfinance as yf

from full_universe_analysis import (
    TARGET_GAIN_PCT,
    TARGET_HOLDING_DAYS,
    _load_eligibility_cache,
    evaluate_ticker_snapshot,
)
from swing_horizon_filter import evaluate_forward_outcome
from yf_retry import call_with_retry

BACKTEST_LOOKBACK_MONTHS = 6
SAMPLE_FREQUENCY_DAYS = 7   # weekly
TICKER_SAMPLE_SIZE: int | None = 400   # None = full eligible universe (expensive — pilot with 400 first)
SAMPLE_SEED = 42            # logged in params.json — reproducible ticker sample
FETCH_PERIOD = "3y"         # see module docstring for why 3y, not less
OUTCOME_BUFFER_DAYS = 14    # calendar-day buffer so the latest as-of date still has
                            # TARGET_HOLDING_DAYS trading days of forward data to score

OUTPUT_ROOT = Path("runs/backtest")


def _sample_tickers() -> list[str]:
    cache = _load_eligibility_cache()
    eligible = sorted(t for t, entry in cache.items() if entry.get("status") == "eligible")
    if not eligible:
        raise RuntimeError(
            "No eligible tickers in runs/ticker_eligibility_cache.json — run "
            "full_universe_analysis.py to completion at least once first."
        )
    if TICKER_SAMPLE_SIZE is None or TICKER_SAMPLE_SIZE >= len(eligible):
        return eligible
    return sorted(random.Random(SAMPLE_SEED).sample(eligible, TICKER_SAMPLE_SIZE))


def _sample_dates() -> list[pd.Timestamp]:
    end = pd.Timestamp.today().normalize() - pd.Timedelta(days=OUTCOME_BUFFER_DAYS)
    start = end - pd.DateOffset(months=BACKTEST_LOOKBACK_MONTHS)
    return list(pd.date_range(start, end, freq=f"{SAMPLE_FREQUENCY_DAYS}D"))


def _git_commit_hash() -> str | None:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True)
        return out.stdout.strip()
    except Exception:  # noqa: BLE001 - purely informational, never fatal
        return None


def run_backtest() -> None:
    tickers = _sample_tickers()
    as_of_dates = _sample_dates()
    print(f"Backtesting {len(tickers)} tickers x {len(as_of_dates)} sample dates "
          f"({as_of_dates[0].date()} to {as_of_dates[-1].date()}, every {SAMPLE_FREQUENCY_DAYS} days)...")

    cache = _load_eligibility_cache()
    rows: list[dict] = []
    completed = 0

    for ticker in tickers:
        completed += 1
        if completed % 50 == 0:
            print(f"  {completed}/{len(tickers)} tickers...")

        try:
            hist = call_with_retry(lambda t=ticker: yf.Ticker(t).history(period=FETCH_PERIOD))
        except Exception as exc:  # noqa: BLE001 - one ticker's fetch failure shouldn't stop the whole backtest
            print(f"WARNING: backtest fetch failed for {ticker}: {exc}")
            continue
        if hist.empty:
            continue
        # yfinance normally returns a tz-aware (exchange-local) index; strip it so
        # .loc slicing against the tz-naive as_of_dates below doesn't raise. Guarded
        # since tz_localize(None) itself errors if the index is already tz-naive.
        if hist.index.tz is not None:
            hist.index = hist.index.tz_localize(None)

        entry = cache.get(ticker, {})
        sector, industry = entry.get("sector"), entry.get("industry")

        for as_of in as_of_dates:
            truncated = hist.loc[:as_of]
            if len(truncated) < 200:
                continue  # not enough lookback yet for this ticker at this date (recent IPO, etc.)

            future = hist.loc[as_of:]["Close"].iloc[1:]
            if len(future) < TARGET_HOLDING_DAYS:
                continue  # shouldn't happen given OUTCOME_BUFFER_DAYS, but skip rather than mis-score

            try:
                snapshot = evaluate_ticker_snapshot(
                    ticker, truncated, sector, industry,
                    target_gain_pct=TARGET_GAIN_PCT, target_holding_days=TARGET_HOLDING_DAYS,
                    include_analyst_consensus=False,
                )
            except Exception as exc:  # noqa: BLE001 - one ticker/date failure shouldn't stop the whole backtest
                print(f"WARNING: backtest snapshot failed for {ticker} @ {as_of.date()}: {exc}")
                continue

            net_buy = snapshot["total_buy_votes"] > snapshot["total_sell_votes"]
            outcome = evaluate_forward_outcome(
                future, entry_price=snapshot["entry_price"], exit_price=snapshot["exit_price"],
                max_holding_days=TARGET_HOLDING_DAYS, net_buy=net_buy,
            )

            rows.append({
                "ticker": ticker,
                "as_of_date": as_of.date().isoformat(),
                "net_buy": net_buy,
                "total_buy_votes": snapshot["total_buy_votes"],
                "total_sell_votes": snapshot["total_sell_votes"],
                "entry_price": snapshot["entry_price"],
                "exit_price": snapshot["exit_price"],
                "status": outcome.status,
                "days_to_exit": outcome.days_to_exit,
                "entry_touched": outcome.entry_touched,
            })

    if not rows:
        print("No backtest rows produced — check eligibility cache / network access.")
        return

    results = pd.DataFrame(rows)
    _write_output(results, tickers, as_of_dates)


def _hit_rate(df: pd.DataFrame) -> dict:
    resolved = df[df["status"].isin(["hit", "missed"])]
    hits = resolved[resolved["status"] == "hit"]
    return {
        "total": len(df),
        "resolved": len(resolved),
        "hits": len(hits),
        "hit_rate": round(len(hits) / len(resolved), 3) if len(resolved) else None,
        "avg_days_to_exit": round(hits["days_to_exit"].mean(), 1) if len(hits) else None,
    }


def _write_output(results: pd.DataFrame, tickers: list[str], as_of_dates: list[pd.Timestamp]) -> None:
    run_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = OUTPUT_ROOT / f"backtest_{run_timestamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    results.to_csv(out_dir / "results.csv", index=False)

    committee_rows = results[results["net_buy"]]
    committee_stats = _hit_rate(committee_rows)
    base_stats = _hit_rate(results)

    by_month = (
        committee_rows.assign(month=pd.to_datetime(committee_rows["as_of_date"]).dt.strftime("%Y-%m"))
        .groupby("month")
        .apply(lambda g: _hit_rate(g)["hit_rate"])
        .to_dict()
    )

    params = {
        "run_timestamp": run_timestamp,
        "git_commit": _git_commit_hash(),
        "backtest_lookback_months": BACKTEST_LOOKBACK_MONTHS,
        "sample_frequency_days": SAMPLE_FREQUENCY_DAYS,
        "ticker_sample_size": TICKER_SAMPLE_SIZE,
        "sample_seed": SAMPLE_SEED,
        "tickers_tested": len(tickers),
        "sample_dates_tested": [d.date().isoformat() for d in as_of_dates],
        "target_gain_pct": TARGET_GAIN_PCT,
        "target_holding_days": TARGET_HOLDING_DAYS,
        "include_analyst_consensus": False,
        "fetch_period": FETCH_PERIOD,
        "lookahead_check": "passed — hist truncated to as_of_date for every group evaluator; "
                            "analyst_consensus dropped (no historical point-in-time equivalent); "
                            "see module docstring for full notes",
    }
    (out_dir / "params.json").write_text(json.dumps(params, indent=2), encoding="utf-8")

    summary_lines = [
        f"# Backtest summary — {run_timestamp}",
        "",
        f"Window: {as_of_dates[0].date()} to {as_of_dates[-1].date()} "
        f"({BACKTEST_LOOKBACK_MONTHS} months, every {SAMPLE_FREQUENCY_DAYS} days), "
        f"{len(tickers)} tickers sampled (seed={SAMPLE_SEED}).",
        f"Target: {TARGET_GAIN_PCT}% within {TARGET_HOLDING_DAYS} trading days. "
        f"Analyst consensus excluded (not reconstructable historically).",
        "",
        "## Committee (net-buy) calls",
        f"- Total calls: {committee_stats['total']} ({committee_stats['resolved']} resolved)",
        f"- Hit rate: {committee_stats['hit_rate']:.1%}" if committee_stats["hit_rate"] is not None
        else "- Hit rate: n/a (no resolved calls)",
        f"- Avg days to exit when hit: {committee_stats['avg_days_to_exit']}",
        "",
        "## Base rate (every analyzed snapshot, regardless of vote)",
        f"- Total: {base_stats['total']} ({base_stats['resolved']} resolved)",
        f"- Hit rate: {base_stats['hit_rate']:.1%}" if base_stats["hit_rate"] is not None
        else "- Hit rate: n/a (no resolved snapshots)",
        "",
        "## Committee hit rate by month",
    ]
    for month, rate in sorted(by_month.items()):
        summary_lines.append(f"- {month}: {rate:.1%}" if rate is not None else f"- {month}: n/a")

    edge = None
    if committee_stats["hit_rate"] is not None and base_stats["hit_rate"] is not None:
        edge = committee_stats["hit_rate"] - base_stats["hit_rate"]
    summary_lines += [
        "",
        "## Conclusion",
        f"Committee beat the base rate by {edge:+.1%}." if edge is not None
        else "Not enough resolved data to compare committee vs base rate yet.",
        "Caveat: yfinance prices are adjusted as of today's fetch, not as literally traded "
        "on the historical date — affects price-level precision, not signal direction.",
    ]
    (out_dir / "summary.md").write_text("\n".join(summary_lines), encoding="utf-8")

    print(f"\nWrote backtest output to {out_dir.resolve()}")
    print("\n".join(summary_lines))


if __name__ == "__main__":
    run_backtest()
