"""
track_outcomes.py — Keeps a running ledger of every net-buy candidate ever
recommended (runs/outcome_tracking.csv) and checks back on what actually
happened to each one, per Abdo's request (2026-07): the daily scan produces
candidates but never told anyone whether the committee's calls were actually
any good. This is the feedback loop that answers that.

Run daily, AFTER full_universe_analysis.py (needs today's fresh
runs/full_universe_results.csv) and BEFORE build_report.py (which reads
runs/outcome_summary.json, written here, to show a "Track record" stat tile)
— see run_daily.ps1 and .github/workflows/daily-scan.yml.

LEDGER FILE: runs/outcome_tracking.csv is a CUMULATIVE ledger (appended to and
updated in place), not a daily snapshot — deliberately NOT given the
runs/archive/ timestamped-copy treatment full_universe_results.csv gets.
That convention exists to preserve a snapshot that would otherwise be
overwritten; this file is never overwritten, only grown, and every day's
state is already recoverable from daily-scan.yml's own daily git commit.

Every tracked row is a net-buy candidate, but entry_price is now ALWAYS a
real support level (CORRECTED 2026-07 — see
full_universe_analysis.compute_entry_exit_levels), not just that day's
close, so a genuine pullback is required before "hit" can register —
already_at_entry (passed to evaluate_forward_outcome) is computed per row
by comparing entry_price to current_price_at_recommendation, and will
almost always be False.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf

from full_universe_analysis import TARGET_HOLDING_DAYS
from swing_horizon_filter import evaluate_forward_outcome
from yf_retry import call_with_retry

RESULTS_CSV = Path("runs/full_universe_results.csv")
LEDGER_CSV = Path("runs/outcome_tracking.csv")
SUMMARY_JSON = Path("runs/outcome_summary.json")

TRAILING_WINDOW_DAYS = 90  # summary stat window — see summarize()

LEDGER_COLUMNS = [
    "ticker", "recommendation_date", "current_price_at_recommendation",
    "entry_price", "entry_basis", "stop_loss_price",
    "exit_price", "exit_basis", "target2_price", "expected_holding_days",
    "status", "days_to_exit", "checked_date",
]


def _load_ledger() -> pd.DataFrame:
    if not LEDGER_CSV.exists():
        return pd.DataFrame(columns=LEDGER_COLUMNS)
    return pd.read_csv(LEDGER_CSV, keep_default_na=False, na_values=[""])


def _append_new_recommendations(ledger: pd.DataFrame) -> pd.DataFrame:
    if not RESULTS_CSV.exists():
        print(f"WARNING: {RESULTS_CSV} not found — skipping today's new recommendations.")
        return ledger

    df = pd.read_csv(RESULTS_CSV)
    net_buy = df[df["total_buy_votes"] > df["total_sell_votes"]].copy()
    net_buy["recommendation_date"] = pd.to_datetime(net_buy["run_timestamp"]).dt.strftime("%Y-%m-%d")

    existing_keys = set(zip(ledger["ticker"], ledger["recommendation_date"])) if not ledger.empty else set()
    new_rows = []
    for _, row in net_buy.iterrows():
        key = (row["ticker"], row["recommendation_date"])
        if key in existing_keys:
            continue  # already tracked (e.g. a manual re-run the same day) — don't duplicate
        new_rows.append({
            "ticker": row["ticker"],
            "recommendation_date": row["recommendation_date"],
            "current_price_at_recommendation": row["current_price"],
            "entry_price": row["entry_price"],
            "entry_basis": row["entry_basis"],
            "stop_loss_price": row.get("stop_loss_price"),
            "exit_price": row["exit_price"],
            "exit_basis": row["exit_basis"],
            "target2_price": row.get("target2_price"),
            "expected_holding_days": row["exit_days_estimate"] if pd.notna(row["exit_days_estimate"]) else TARGET_HOLDING_DAYS,
            "status": "still_pending",
            "days_to_exit": None,
            "checked_date": date.today().isoformat(),
        })

    if not new_rows:
        return ledger
    print(f"Adding {len(new_rows)} new recommendation(s) to the outcome ledger.")
    return pd.concat([ledger, pd.DataFrame(new_rows)], ignore_index=True)


def _recheck_pending(ledger: pd.DataFrame) -> pd.DataFrame:
    pending_idx = ledger.index[ledger["status"] == "still_pending"]
    if len(pending_idx) == 0:
        return ledger

    print(f"Rechecking {len(pending_idx)} still-pending recommendation(s)...")
    for idx in pending_idx:
        row = ledger.loc[idx]
        ticker = row["ticker"]
        rec_date = row["recommendation_date"]
        try:
            hist = call_with_retry(lambda t=ticker, d=rec_date: yf.Ticker(t).history(start=d))
        except Exception as exc:  # noqa: BLE001 - one ticker's fetch failure shouldn't stop the whole recheck
            print(f"WARNING: outcome recheck fetch failed for {ticker}: {exc}")
            continue

        if hist.empty or len(hist) < 2:
            continue  # recommendation day itself may not have closed/settled in the feed yet

        future_close = hist["Close"].iloc[1:]  # exclude the recommendation day itself
        # See module docstring: entry_price is only ever >= the recommendation-time
        # price in the rare "no support level found at all" fallback.
        already_at_entry = row["entry_price"] >= row["current_price_at_recommendation"]
        outcome = evaluate_forward_outcome(
            future_close, entry_price=row["entry_price"], exit_price=row["exit_price"],
            max_holding_days=int(row["expected_holding_days"]), already_at_entry=already_at_entry,
        )
        ledger.loc[idx, "status"] = outcome.status
        ledger.loc[idx, "days_to_exit"] = outcome.days_to_exit
        ledger.loc[idx, "checked_date"] = date.today().isoformat()

    return ledger


def summarize(ledger: pd.DataFrame) -> dict:
    """Trailing-TRAILING_WINDOW_DAYS-day win rate — resolved calls only (pending excluded from the rate)."""
    cutoff = (datetime.now() - timedelta(days=TRAILING_WINDOW_DAYS)).strftime("%Y-%m-%d")
    recent = ledger[ledger["recommendation_date"] >= cutoff]
    resolved = recent[recent["status"].isin(["hit", "missed"])]
    hits = resolved[resolved["status"] == "hit"]

    return {
        "window_days": TRAILING_WINDOW_DAYS,
        "total_tracked": len(recent),
        "resolved": len(resolved),
        "still_pending": len(recent) - len(resolved),
        "hits": len(hits),
        "misses": len(resolved) - len(hits),
        "hit_rate": round(len(hits) / len(resolved), 3) if len(resolved) else None,
        "avg_days_to_exit": round(hits["days_to_exit"].mean(), 1) if len(hits) else None,
    }


def track() -> None:
    ledger = _load_ledger()
    ledger = _append_new_recommendations(ledger)
    ledger = _recheck_pending(ledger)

    LEDGER_CSV.parent.mkdir(parents=True, exist_ok=True)
    ledger.to_csv(LEDGER_CSV, index=False)

    summary = summarize(ledger)
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"Outcome ledger: {len(ledger)} total recommendations tracked.")
    print(f"Trailing {TRAILING_WINDOW_DAYS}-day track record: {summary['hits']}/{summary['resolved']} hit "
          f"({summary['hit_rate']:.1%} hit rate)" if summary["hit_rate"] is not None
          else f"Trailing {TRAILING_WINDOW_DAYS}-day track record: no resolved calls yet.")


if __name__ == "__main__":
    track()
