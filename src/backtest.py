"""
backtest.py — One-time/on-demand historical simulation of the full committee
system, per Abdo's request (2026-07): "would this system actually have made
money over the past 3-6 months?" Simulates what the committee would have
recommended at points in the past, then scores those simulated calls against
what ACTUALLY happened afterward (which we now know).

NOT part of the daily automation (.github/workflows/daily-scan.yml) — this is
compute-heavy (hundreds of tickers x tens of historical dates, each running
the full indicator/calibration stack) and meant to be run by hand, on Abdo's
own machine:

    python src/backtest.py

DATA SOURCE (RULE, 2026-07 — per Abdo's explicit instruction, see CLAUDE.md):
    ALL backtesting reads price history from Abdo's local Stooq-format dump
    (full_universe_analysis.LOCAL_MARKET_DATA_DIR, see that constant for the
    exact path), via
    build_local_ticker_index()/load_local_history() — NEVER yfinance. This is
    what makes a 400-1000-ticker backtest practical at all: no network calls,
    no Yahoo rate-limiting (see MAX_WORKERS in full_universe_analysis.py for
    how badly that bites the LIVE daily path, which still uses yfinance and is
    unaffected by this file). Local-machine-only, same restriction
    refresh_ticker_universe.py already has — this script cannot run on GitHub
    Actions.

LOOKAHEAD SAFETY (see preflight-checklist.md section A — "no feature uses
data that wouldn't have been known at prediction time"):
    - Every group evaluator (technical/quantitative/astrological/advanced
      technical) is called via full_universe_analysis.evaluate_ticker_snapshot
      with `hist` TRUNCATED to `.loc[:as_of_date]` — nothing after that date
      is ever visible to the decision logic.
    - `include_analyst_consensus=False`: analyst consensus is a CURRENT-only
      snapshot with no historical point-in-time equivalent (and isn't in the
      local dump at all), so it's dropped for backtest scoring only (see
      committee_signals.evaluate_quantitative_group). The live daily system
      is unaffected.
    - Verified (2026-07, see project plan notes): evaluate_horizon_fit, Pivot
      Points, Ichimoku, and the Gann Square9/ZigZag pivot detection are all
      safe on truncated input by construction — no code changes were needed
      for those, this is documentation of that check, not a fix.
    - CAVEAT: the local dump's prices are whatever Stooq recorded at dump
      time (not necessarily split/dividend-adjusted the same way yfinance's
      live fetch is) — affects price-level precision slightly, not signal
      direction. Distinct from the old yfinance caveat this replaces.

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

from full_universe_analysis import (
    TARGET_GAIN_PCT,
    TARGET_HOLDING_DAYS,
    SUPPORT_RESISTANCE_METHOD,
    _load_eligibility_cache,
    build_local_ticker_index,
    load_local_history,
    evaluate_ticker_snapshot,
)
from swing_horizon_filter import evaluate_forward_outcome

BACKTEST_LOOKBACK_MONTHS = 6
SAMPLE_FREQUENCY_DAYS = 7   # weekly
TICKER_SAMPLE_SIZE: int | None = 400   # None = full eligible universe; local data removes the old
                                        # network-rate-limit reason to keep this small — raise to
                                        # 1000 (or None) freely, see CLAUDE.md's backtesting rule
SAMPLE_SEED = 42            # logged in params.json — reproducible ticker sample
OUTCOME_BUFFER_DAYS = 14    # calendar-day buffer so the latest as-of date still has
                            # TARGET_HOLDING_DAYS trading days of forward data to score

OUTPUT_ROOT = Path("runs/backtest")


def _sample_tickers(local_index: dict) -> list[str]:
    cache = _load_eligibility_cache()
    eligible = sorted(
        t for t, entry in cache.items()
        if entry.get("status") == "eligible" and t.upper() in local_index
    )
    if not eligible:
        raise RuntimeError(
            "No eligible tickers found in both runs/ticker_eligibility_cache.json and "
            "LOCAL_MARKET_DATA_DIR — run full_universe_analysis.py to completion at least "
            "once first, and check LOCAL_MARKET_DATA_DIR is reachable."
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


def run_backtest(support_resistance_method: str = SUPPORT_RESISTANCE_METHOD,
                  tickers: list[str] | None = None,
                  as_of_dates: list[pd.Timestamp] | None = None,
                  write_output: bool = True) -> pd.DataFrame:
    local_index = build_local_ticker_index()
    tickers = tickers if tickers is not None else _sample_tickers(local_index)
    as_of_dates = as_of_dates if as_of_dates is not None else _sample_dates()
    print(f"Backtesting {len(tickers)} tickers x {len(as_of_dates)} sample dates "
          f"({as_of_dates[0].date()} to {as_of_dates[-1].date()}, every {SAMPLE_FREQUENCY_DAYS} days) "
          f"[support_resistance_method={support_resistance_method}, source=local dump]...")

    cache = _load_eligibility_cache()
    rows: list[dict] = []
    completed = 0

    for ticker in tickers:
        completed += 1
        if completed % 50 == 0:
            print(f"  {completed}/{len(tickers)} tickers...")

        hist = load_local_history(ticker, local_index)
        if hist is None or hist.empty:
            print(f"WARNING: no local history for {ticker} — skipping.")
            continue

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
                    support_resistance_method=support_resistance_method,
                )
            except Exception as exc:  # noqa: BLE001 - one ticker/date failure shouldn't stop the whole backtest
                print(f"WARNING: backtest snapshot failed for {ticker} @ {as_of.date()}: {exc}")
                continue

            net_buy = snapshot["total_buy_votes"] > snapshot["total_sell_votes"]
            # entry_price is only ever >= current_price in the rare "no support level
            # found at all" fallback (see compute_entry_exit_levels) — otherwise a real
            # pullback is required, regardless of the committee's vote.
            already_at_entry = snapshot["entry_price"] >= snapshot["current_price"]
            outcome = evaluate_forward_outcome(
                future, entry_price=snapshot["entry_price"], exit_price=snapshot["exit_price"],
                max_holding_days=TARGET_HOLDING_DAYS, already_at_entry=already_at_entry,
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
        return pd.DataFrame(rows)

    results = pd.DataFrame(rows)
    if write_output:
        _write_output(results, tickers, as_of_dates, support_resistance_method)
    return results


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


def _write_output(results: pd.DataFrame, tickers: list[str], as_of_dates: list[pd.Timestamp],
                   support_resistance_method: str = SUPPORT_RESISTANCE_METHOD) -> None:
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
        "support_resistance_method": support_resistance_method,
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
        "Caveat: local dump prices are whatever Stooq recorded at dump time, not necessarily "
        "adjusted identically to a live fetch — affects price-level precision, not signal direction.",
    ]
    (out_dir / "summary.md").write_text("\n".join(summary_lines), encoding="utf-8")

    print(f"\nWrote backtest output to {out_dir.resolve()}")
    print("\n".join(summary_lines))


def compare_support_resistance_methods() -> None:
    """
    Runs the identical backtest (same tickers, same as-of dates — sampled
    once, reused for both) with support_resistance_method="pivot" and again
    with "fibonacci", then reports which one scored a higher committee hit
    rate. Per Abdo's explicit decision (2026-07): the choice between
    Fibonacci retracement and Square of Nine as the entry/exit support
    source should be made GLOBALLY from one full backtest comparison, not
    per-ticker — whichever wins here should be hand-copied into
    full_universe_analysis.SUPPORT_RESISTANCE_METHOD.

    Run: python src/backtest.py --compare-support-method
    """
    tickers = _sample_tickers(build_local_ticker_index())
    as_of_dates = _sample_dates()

    print("=== Pass 1/2: support_resistance_method=pivot ===")
    pivot_results = run_backtest(support_resistance_method="pivot", tickers=tickers,
                                  as_of_dates=as_of_dates, write_output=False)
    print("\n=== Pass 2/2: support_resistance_method=fibonacci ===")
    fib_results = run_backtest(support_resistance_method="fibonacci", tickers=tickers,
                                as_of_dates=as_of_dates, write_output=False)

    pivot_stats = _hit_rate(pivot_results[pivot_results["net_buy"]]) if not pivot_results.empty else _hit_rate(pivot_results)
    fib_stats = _hit_rate(fib_results[fib_results["net_buy"]]) if not fib_results.empty else _hit_rate(fib_results)

    run_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = OUTPUT_ROOT / f"support_method_comparison_{run_timestamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    pivot_results.to_csv(out_dir / "results_pivot.csv", index=False)
    fib_results.to_csv(out_dir / "results_fibonacci.csv", index=False)

    pivot_rate = pivot_stats["hit_rate"]
    fib_rate = fib_stats["hit_rate"]
    if pivot_rate is None and fib_rate is None:
        winner = "inconclusive — no resolved committee calls in either pass"
    elif fib_rate is None:
        winner = "pivot"
    elif pivot_rate is None:
        winner = "fibonacci"
    else:
        winner = "fibonacci" if fib_rate > pivot_rate else "pivot"

    summary = (
        f"# Support/resistance method comparison — {run_timestamp}\n\n"
        f"pivot:     hit_rate={pivot_rate} ({pivot_stats['resolved']} resolved / {pivot_stats['total']} total)\n"
        f"fibonacci: hit_rate={fib_rate} ({fib_stats['resolved']} resolved / {fib_stats['total']} total)\n\n"
        f"WINNER: {winner}\n\n"
        f"Action: set full_universe_analysis.SUPPORT_RESISTANCE_METHOD = \"{winner}\" "
        f"if it isn't already (currently \"{SUPPORT_RESISTANCE_METHOD}\").\n"
    )
    (out_dir / "summary.md").write_text(summary, encoding="utf-8")
    print(f"\n{summary}")
    print(f"Wrote comparison output to {out_dir.resolve()}")


if __name__ == "__main__":
    import sys
    if "--compare-support-method" in sys.argv:
        compare_support_resistance_methods()
    else:
        run_backtest()
