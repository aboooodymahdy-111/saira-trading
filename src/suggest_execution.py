"""
suggest_execution.py — Turn full_universe_analysis.py's net-buy candidates into a
human-reviewable execution suggestion.

PURPOSE:
    This is deliberately NOT an auto-trading script. It reads
    runs/full_universe_results.csv and produces a report of candidate trades for
    Abdo to review and act on manually. No order is ever placed automatically by
    this script — see coding-standards.md, Pillar 3, on why live execution always
    needs a human sanity check.

HISTORY (2026-07): this script used to read runs/signals_confirmed.csv (the TS
    pipeline's Phase 3 output) and require confirmation_score >= SUGGESTION_MIN_SCORE.
    TS WAS REMOVED FROM THE PROJECT ENTIRELY (2026-07 decision — see
    deprecated_ts/ and CLAUDE.md). Sizing now uses total_buy_votes (committee
    agreement across the Technical/Quantitative/Astrological/Advanced Technical
    groups, already computed by full_universe_analysis.py) as the confirmation
    signal instead, and the suggested execution price is entry_price (ALWAYS the
    nearest pivot/Square9 support level below current price — CORRECTED 2026-07,
    see full_universe_analysis.compute_entry_exit_levels) rather than a bare
    current price fetch. stop_loss_price (next support down) and target2_price
    (next resistance up, "T2") are carried through below for the same reason —
    a real trade needs a stop, not just an entry and one target.

SELECTION LOGIC (a starting point — tune SUGGESTION_MIN_VOTES / other constants
    below to match your own risk tolerance; nothing here is a "correct" threshold,
    it's a reasonable default):
    - Require total_buy_votes > total_sell_votes (net-buy lean) AND
      total_buy_votes >= SUGGESTION_MIN_VOTES (default: 5 of 11 possible votes) —
      i.e. a clear majority of independent methods agree.
    - Apply a hard position-size ceiling (Pillar 3 of the coding standards) — this
      script computes a SUGGESTED share count capped at MAX_ORDER_VALUE_USD, it does
      not know your actual account size or existing positions, and does not adjust
      for that. Treat the suggested quantity as a ceiling reference, not a final answer.

INPUT: runs/full_universe_results.csv (full_universe_analysis.py output)
OUTPUT: runs/execution_suggestions.csv + a printed summary of top candidates

Run:
    python src/suggest_execution.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

INPUT_CSV = Path("runs/full_universe_results.csv")
OUTPUT_CSV = Path("runs/execution_suggestions.csv")

# Per project decision (2026-07): keep every run, not just the latest — every
# script in this project that writes a "latest" output also archives a
# timestamped copy alongside it, so past runs stay available as potential
# future training/comparison data.
ARCHIVE_DIR = Path("runs/archive")

SUGGESTION_MIN_VOTES = 5          # out of 11 possible committee votes (4 Technical + 2 Quant + 1 Astro + 4 Adv. Tech)
MAX_ORDER_VALUE_USD = 5_000       # hard ceiling — see coding-standards.md Pillar 3. Change deliberately.
MAX_SUGGESTIONS_PER_TICKER = 1    # avoid flooding the report with every cycle for the same stock


def load_universe_results() -> pd.DataFrame:
    if not INPUT_CSV.exists():
        raise FileNotFoundError(f"{INPUT_CSV} not found — run full_universe_analysis.py first.")
    return pd.read_csv(INPUT_CSV)


def build_suggestions(df: pd.DataFrame) -> pd.DataFrame:
    eligible = df[
        (df["total_buy_votes"] > df["total_sell_votes"])
        & (df["total_buy_votes"] >= SUGGESTION_MIN_VOTES)
    ].copy()

    if eligible.empty:
        print("No candidates currently meet the suggestion criteria "
              f"(net-buy lean + total_buy_votes >= {SUGGESTION_MIN_VOTES}).")
        return eligible

    # Highest vote agreement first, then gain_speed_score as the tiebreaker — same
    # ranking philosophy as full_universe_analysis.py/committee_signals.py.
    eligible = eligible.sort_values(
        ["total_buy_votes", "gain_speed_score"], ascending=[False, False], na_position="last"
    )
    eligible = eligible.groupby("ticker").head(MAX_SUGGESTIONS_PER_TICKER).reset_index(drop=True)

    suggested_shares = []
    order_values = []
    ceiling_hit = []

    for _, row in eligible.iterrows():
        price = row["entry_price"]

        if price is None or pd.isna(price) or price <= 0:
            suggested_shares.append(None)
            order_values.append(None)
            ceiling_hit.append(None)
            continue

        max_shares_by_ceiling = int(MAX_ORDER_VALUE_USD // price)
        shares = max(max_shares_by_ceiling, 0)
        order_value = shares * price

        suggested_shares.append(shares)
        order_values.append(round(order_value, 2))
        ceiling_hit.append(shares == 0)  # price alone exceeds the ceiling for even 1 share

    eligible["suggested_shares"] = suggested_shares
    eligible["suggested_order_value_usd"] = order_values
    eligible["price_exceeds_ceiling"] = ceiling_hit

    return eligible


def main() -> None:
    df = load_universe_results()
    print(f"Loaded {len(df)} analyzed tickers from {INPUT_CSV}.")

    suggestions = build_suggestions(df)
    if suggestions.empty:
        return

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    columns_order = [
        "ticker", "sector", "total_buy_votes", "total_sell_votes",
        "current_price", "entry_price", "entry_basis", "exit_price", "exit_basis",
        "exit_days_estimate", "suggested_shares", "suggested_order_value_usd",
        "price_exceeds_ceiling",
    ]
    columns_order = [c for c in columns_order if c in suggestions.columns]
    output_df = suggestions[columns_order].copy()
    output_df.insert(0, "run_timestamp", pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"))
    output_df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")

    archive_path = ARCHIVE_DIR / f"execution_suggestions_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.csv"
    output_df.to_csv(archive_path, index=False, encoding="utf-8-sig")

    print()
    print(f"=== {len(suggestions)} EXECUTION SUGGESTIONS (for manual review only) ===")
    print(f"Hard order-value ceiling: ${MAX_ORDER_VALUE_USD:,} per suggestion")
    print(f"Minimum committee agreement required: {SUGGESTION_MIN_VOTES}/11 votes, net-buy lean")
    print()
    print(suggestions[columns_order].to_string(index=False))

    flagged = suggestions[suggestions["price_exceeds_ceiling"] == True]  # noqa: E712
    if not flagged.empty:
        print()
        print(f"NOTE: {len(flagged)} suggestion(s) have an entry price above the "
              f"${MAX_ORDER_VALUE_USD:,} ceiling for even a single share — "
              f"suggested_shares=0. Review MAX_ORDER_VALUE_USD if this is unintentional.")

    print()
    print("REMINDER: this is a SUGGESTION report, not an order. Review "
          "preflight-checklist.md section B before placing any real trade.")
    print(f"\nSaved to: {OUTPUT_CSV.resolve()}")
    print(f"Archived this run to: {archive_path.resolve()}")


if __name__ == "__main__":
    main()
