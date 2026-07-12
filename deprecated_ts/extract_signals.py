"""
extract_signals.py — Phase 1: Extract TS-generated Buy/Sell signals from trading_timeline.xlsx

INPUT ASSUMPTIONS (verified against trading_timeline1.xlsx, "Clean" sheet, 2026-07-10):
  - Sheet contains one block of 6 columns per stock: 4 data columns + 2 blank separator columns.
  - Row 0 (0-indexed): stock ticker, e.g. "AXTI". May contain trailing manual notes,
    e.g. "FCX More accu LPC", "TSM 100%" — these are split into (ticker, note).
  - Row 1: target-profit label per column, normally a float like 0.1/0.2/0.3/0.4 (=10/20/30/40%).
    Sometimes replaced with a manual text note, e.g. "10% ≈opz" — this signals Abdo has
    manually identified this column's Buy/Sell direction as REVERSED after review.
  - Rows 2+: alternating "Buy DD.MM.YYYY" / "Sell DD.MM.YYYY" strings, one signal per cell,
    continuing down the column until it runs out (padded with NaN below that).
  - There is an UNRELATED reference table starting a few rows below the last real signal
    row (a two-column ticker/flag list). This script auto-detects the real data boundary
    by ticker validation rather than a hardcoded row number, and logs what it finds.

OUTPUT: a tidy DataFrame with one row per individual signal:
    ticker | target_label | reversed_flag | signal_type | signal_date | sequence_position

Run:
    python src/extract_signals.py
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

# ---- Constants (no magic numbers buried in logic below) --------------------
INPUT_XLSX = Path("data/raw/trading_timeline_2026-07-10.xlsx")
SHEET_NAME = "Clean"
OUTPUT_CSV = Path("runs/signals_extracted.csv")

BLOCK_WIDTH = 6          # 4 data columns + 2 blank separator columns per stock
DATA_COLS_PER_BLOCK = 4  # the 4 target-profit scenario columns
HEADER_ROW = 0           # ticker row
LABEL_ROW = 1            # target % / manual note row
FIRST_SIGNAL_ROW = 2     # signals start here

# Per project decision (2026-07): keep every run, not just the latest, since
# past runs are needed as a historical record (e.g. future AI training data).
# OUTPUT_CSV always holds the latest run (for normal day-to-day use); ARCHIVE_DIR
# accumulates a separate timestamped copy of every run that is never overwritten.
ARCHIVE_DIR = Path("runs/archive")

SIGNAL_PATTERN = re.compile(r"^(Buy|Sell)\s+(\d{2}\.\d{2}\.\d{4})$")
REVERSED_MARKER = "opz"  # substring Abdo uses in row 1 to flag a manually-confirmed reversed column


@dataclass
class Signal:
    """One Buy or Sell signal for one stock/target-scenario column."""
    ticker: str
    ticker_note: str | None
    target_label: str
    reversed_flag: bool
    column_index: int
    sequence_position: int
    signal_type: str   # "Buy" or "Sell"
    signal_date: datetime


def split_ticker_and_note(raw: str) -> tuple[str, str | None]:
    """
    Row-0 header cells sometimes carry a manual note appended after the ticker,
    e.g. "FCX More accu LPC" -> ("FCX", "More accu LPC"), "TSM 100%" -> ("TSM", "100%").
    Assumes the ticker is always the first whitespace-separated token.
    """
    raw = raw.strip()
    parts = raw.split(maxsplit=1)
    ticker = parts[0]
    note = parts[1] if len(parts) > 1 else None
    return ticker, note


def parse_target_label(cell) -> tuple[str, bool]:
    """
    Row-1 cells are normally a float (0.1, 0.2, 0.3, 0.4). Abdo sometimes replaces
    the value with a manual text note after reviewing the column's actual price
    direction, e.g. "10% ≈opz", meaning: he found this column's Buy/Sell signals
    are REVERSED relative to what TS labeled them (see conversation history —
    this is a manual finding, not something derivable from the data itself).

    Returns (label_as_string, reversed_flag).
    """
    if isinstance(cell, str):
        is_reversed = REVERSED_MARKER in cell.lower()
        return cell.strip(), is_reversed
    if pd.isna(cell):
        return "unknown", False
    # numeric label like 0.1 -> "10%"
    return f"{float(cell) * 100:.0f}%", False


def find_stock_blocks(raw_df: pd.DataFrame) -> list[int]:
    """Return the starting column index of every stock block (row 0 has a ticker there)."""
    return [c for c in raw_df.columns if pd.notna(raw_df.iloc[HEADER_ROW, c])]


def find_last_signal_row(raw_df: pd.DataFrame, stock_start_cols: list[int]) -> int:
    """
    Auto-detect where real signal data ends and any unrelated trailing table begins,
    instead of hardcoding a row number that could silently go stale if the sheet changes.
    Returns the last row index (inclusive) that contains valid Buy/Sell signal text
    anywhere across all stock data columns.
    """
    last_valid_row = FIRST_SIGNAL_ROW - 1
    data_cols = [
        c + offset
        for c in stock_start_cols
        for offset in range(DATA_COLS_PER_BLOCK)
    ]
    for row_idx in range(FIRST_SIGNAL_ROW, raw_df.shape[0]):
        row_has_valid_signal = any(
            isinstance(raw_df.iloc[row_idx, c], str) and SIGNAL_PATTERN.match(raw_df.iloc[row_idx, c].strip())
            for c in data_cols
            if c < raw_df.shape[1]
        )
        if row_has_valid_signal:
            last_valid_row = row_idx
    return last_valid_row


def extract_signals(raw_df: pd.DataFrame) -> list[Signal]:
    stock_start_cols = find_stock_blocks(raw_df)
    last_row = find_last_signal_row(raw_df, stock_start_cols)

    print(f"Found {len(stock_start_cols)} stock blocks.")
    print(f"Signal data spans rows {FIRST_SIGNAL_ROW} to {last_row} "
          f"(anything below row {last_row} is ignored as unrelated trailing content).")

    signals: list[Signal] = []
    skipped_malformed = 0

    for start_col in stock_start_cols:
        ticker_raw = str(raw_df.iloc[HEADER_ROW, start_col])
        ticker, ticker_note = split_ticker_and_note(ticker_raw)

        for offset in range(DATA_COLS_PER_BLOCK):
            col = start_col + offset
            if col >= raw_df.shape[1]:
                continue

            target_label, reversed_flag = parse_target_label(raw_df.iloc[LABEL_ROW, col])

            seq_pos = 0
            for row_idx in range(FIRST_SIGNAL_ROW, last_row + 1):
                cell = raw_df.iloc[row_idx, col]
                if pd.isna(cell):
                    continue
                if not isinstance(cell, str):
                    skipped_malformed += 1
                    continue
                match = SIGNAL_PATTERN.match(cell.strip())
                if not match:
                    skipped_malformed += 1
                    continue

                signal_type, date_str = match.groups()
                signal_date = datetime.strptime(date_str, "%d.%m.%Y")
                seq_pos += 1

                signals.append(Signal(
                    ticker=ticker,
                    ticker_note=ticker_note,
                    target_label=target_label,
                    reversed_flag=reversed_flag,
                    column_index=col,
                    sequence_position=seq_pos,
                    signal_type=signal_type,
                    signal_date=signal_date,
                ))

    if skipped_malformed:
        print(f"WARNING: skipped {skipped_malformed} cells that did not match the expected "
              f"'Buy/Sell DD.MM.YYYY' pattern. Review the source file if this number looks large.")

    return signals


def to_dataframe(signals: list[Signal]) -> pd.DataFrame:
    df = pd.DataFrame([s.__dict__ for s in signals])
    df = df.sort_values(["ticker", "column_index", "sequence_position"]).reset_index(drop=True)
    return df


def main() -> None:
    if not INPUT_XLSX.exists():
        raise FileNotFoundError(
            f"Expected input file at {INPUT_XLSX.resolve()} — copy trading_timeline1.xlsx "
            f"there first (see data/raw/ naming convention: keep the original snapshot untouched)."
        )

    raw_df = pd.read_excel(INPUT_XLSX, sheet_name=SHEET_NAME, header=None)
    signals = extract_signals(raw_df)

    if not signals:
        raise ValueError("No signals extracted — check that the sheet structure matches assumptions "
                          "documented at the top of this file.")

    result_df = to_dataframe(signals)

    # Stamp every row with when this run happened, so a future dataset built by
    # concatenating archive files doesn't have to rely on filenames alone to
    # know which run a row came from.
    run_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    result_df.insert(0, "run_timestamp", run_timestamp)

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    result_df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")

    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    archive_path = ARCHIVE_DIR / f"signals_extracted_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    result_df.to_csv(archive_path, index=False, encoding="utf-8-sig")

    print()
    print(f"Extracted {len(result_df)} signals across {result_df['ticker'].nunique()} tickers.")
    print(f"Saved to: {OUTPUT_CSV.resolve()}")
    print(f"Archived this run to: {archive_path.resolve()}")
    print()
    print("Preview:")
    print(result_df.head(10).to_string())

    reversed_cols = result_df[result_df["reversed_flag"]][["ticker", "target_label"]].drop_duplicates()
    if not reversed_cols.empty:
        print()
        print("Columns manually flagged as REVERSED by Abdo (Buy/Sell direction swapped):")
        print(reversed_cols.to_string(index=False))


if __name__ == "__main__":
    main()
