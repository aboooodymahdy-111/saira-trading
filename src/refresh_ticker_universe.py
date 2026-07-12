"""
refresh_ticker_universe.py — Regenerates data/ticker_universe.csv from Abdo's
local offline Stooq-format dump (LOCAL_MARKET_DATA_DIR in
full_universe_analysis.py).

WHY THIS IS SEPARATE from full_universe_analysis.py (2026-07, moved to the
cloud): only Abdo's own machine can see that local dump — GitHub Actions
can't. full_universe_analysis.py now reads the committed CSV instead, so the
daily scan runs unchanged in the cloud; this script is the manual, occasional
step Abdo runs locally whenever he wants to widen or refresh the universe,
then commits+pushes the updated CSV.

Run (on Abdo's machine only):
    python src/refresh_ticker_universe.py
"""

from __future__ import annotations

import csv

from full_universe_analysis import (
    EXCHANGE_SUBFOLDERS,
    LOCAL_MARKET_DATA_DIR,
    TICKER_UNIVERSE_CSV,
)


def refresh() -> None:
    tickers: set[str] = set()
    for sub in EXCHANGE_SUBFOLDERS:
        base = LOCAL_MARKET_DATA_DIR / sub
        if not base.exists():
            raise FileNotFoundError(f"{base} not found — check LOCAL_MARKET_DATA_DIR.")
        for txt_file in base.rglob("*.us.txt"):
            tickers.add(txt_file.stem.split(".")[0].upper())

    TICKER_UNIVERSE_CSV.parent.mkdir(parents=True, exist_ok=True)
    with TICKER_UNIVERSE_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["ticker"])
        for ticker in sorted(tickers):
            writer.writerow([ticker])

    print(f"Wrote {len(tickers)} tickers to {TICKER_UNIVERSE_CSV.resolve()}")
    print("Commit and push this file so the next cloud run picks up the update.")


if __name__ == "__main__":
    refresh()
