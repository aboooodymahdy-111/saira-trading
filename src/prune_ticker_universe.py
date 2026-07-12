"""
prune_ticker_universe.py — Shrinks data/ticker_universe.csv down to only the
tickers already known to be "eligible" (passed the ethical screen AND had
enough yfinance price history), per Abdo's request (2026-07): most of the
~8,199-ticker universe is junk that will never pass — preferred-share
tickers, long-delisted symbols, small OTC-adjacent names with no yfinance
data — and every one of those gets re-hit by a 404 request on every run
until ELIGIBILITY_CACHE's TTL forces a recheck (see
full_universe_analysis.py's CACHE_TTL_DAYS comment). Removing them from the
universe file itself means they're never even attempted again, not just
skipped-with-a-cache-lookup.

TRADE-OFF (worth knowing before running this): any ticker excluded here
because it was ineligible LAST time it was checked, or simply hadn't been
reached yet in an interrupted run, drops out of future scans permanently
(barring a manual refresh_ticker_universe.py re-run from the full local
dump). Only run this after a full, COMPLETED universe scan — not a partial
or interrupted one — so "not eligible" actually means "not eligible", not
"never got checked".

Run (after a completed full_universe_analysis.py run):
    python src/prune_ticker_universe.py
"""

from __future__ import annotations

import csv

from full_universe_analysis import ELIGIBILITY_CACHE_PATH, TICKER_UNIVERSE_CSV, _load_eligibility_cache


def prune() -> None:
    cache = _load_eligibility_cache()
    if not cache:
        raise RuntimeError(
            f"{ELIGIBILITY_CACHE_PATH} is empty or missing — run a completed "
            f"full_universe_analysis.py scan first."
        )

    with TICKER_UNIVERSE_CSV.open(encoding="utf-8") as f:
        before = [row["ticker"] for row in csv.DictReader(f)]

    # A handful of tickers can legitimately have no cache entry even after a
    # FULLY completed run — analyze_ticker() deliberately never caches a
    # transient fetch/analysis failure (so it gets retried next run instead
    # of silently sticking), and every ticker is still submitted to the
    # thread pool regardless. Only a low coverage ratio actually indicates an
    # interrupted/partial run worth blocking on.
    checked = sum(1 for t in before if t in cache)
    coverage = checked / len(before) if before else 0.0
    if coverage < 0.90:
        raise RuntimeError(
            f"Only {checked}/{len(before)} tickers ({coverage:.0%}) in {TICKER_UNIVERSE_CSV} have a "
            f"cache entry — this looks like a partial/interrupted run, not a completed one. "
            f"Re-run full_universe_analysis.py to completion before pruning."
        )
    if checked < len(before):
        print(f"Note: {len(before) - checked} ticker(s) had no cache entry (transient fetch/analysis "
              f"failures never get cached) — dropping them along with the ineligible ones.")

    eligible = sorted(t for t in before if cache.get(t, {}).get("status") == "eligible")

    with TICKER_UNIVERSE_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["ticker"])
        for ticker in eligible:
            writer.writerow([ticker])

    print(f"Pruned {TICKER_UNIVERSE_CSV}: {len(before)} -> {len(eligible)} tickers "
          f"({len(before) - len(eligible)} ineligible/no-data tickers dropped).")
    print("Commit and push this file, and re-run refresh_ticker_universe.py + this "
          "script again in a few months to pick up newly-listed tickers.")


if __name__ == "__main__":
    prune()
