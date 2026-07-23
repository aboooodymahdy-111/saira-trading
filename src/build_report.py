"""
build_report.py — Generates a self-contained HTML dashboard from
runs/full_universe_results.csv (the output of full_universe_analysis.py).

WHY THIS EXISTS: raw CSV / terminal output isn't something Abdo can quickly
scan for candidates worth researching. This bakes one run's results into a
single static HTML file (embedded data, no external calls) with a filterable/
sortable table, a featured shortlist, and two summary charts — a report
that's actually usable to explore, not just a print of numbers.

This is a SNAPSHOT of the CSV at generation time, not a live view — matches
the project's existing "timestamped, archived, reproducible" philosophy
(see full_universe_analysis.py's ARCHIVE_DIR comment).

Run:
    python src/build_report.py
"""

from __future__ import annotations

import json
import math
import os
from datetime import datetime
from pathlib import Path

import pandas as pd


def _clean_nan(records: list[dict]) -> list[dict]:
    """
    JSON has no NaN literal. pandas' float64 columns silently coerce a
    .where(..., None) replacement back to NaN (can't hold Python None in a
    float64 array) — confirmed 2026-07 when an embedded NaN broke
    JSON.parse() and silently blanked the entire report (one exception in
    the page's top-level script kills every render call after it, with no
    visible error). Cleaning post-to_dict(), on plain Python floats, sidesteps
    the dtype coercion entirely.
    """
    for row in records:
        for key, value in row.items():
            if isinstance(value, float) and math.isnan(value):
                row[key] = None
    return records

RESULTS_CSV = Path("runs/full_universe_results.csv")
OUTPUT_HTML = Path("runs/report.html")
# run_daily.ps1 copies OUTPUT_HTML here after each run (see its own comment) —
# read back here so the report page can offer a picker over past runs.
ARCHIVE_REPORTS_DIR = Path("runs/archive/reports")
# Written by track_outcomes.py (2026-07) — absent until that's run at least
# once (e.g. a fresh clone before the first daily-scan.yml run completes).
OUTCOME_SUMMARY_JSON = Path("runs/outcome_summary.json")


def _load_outcome_summary() -> dict | None:
    if not OUTCOME_SUMMARY_JSON.exists():
        return None
    try:
        return json.loads(OUTCOME_SUMMARY_JSON.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _report_url_for(target: Path) -> str:
    """
    Locally (no REPORT_BASE_URL set), an absolute file:// URI works
    regardless of whether OUTPUT_HTML or an archived copy is the one
    currently open. On GitHub Pages (REPORT_BASE_URL set to the site's base
    URL by the daily-scan.yml workflow), a relative link would break for
    archived copies living at a different directory depth than OUTPUT_HTML,
    so an absolute site URL is used instead — safe from any page.
    """
    base = os.environ.get("REPORT_BASE_URL", "").rstrip("/")
    if base:
        rel = target.resolve().relative_to(OUTPUT_HTML.resolve().parent)
        return f"{base}/{str(rel).replace(chr(92), '/')}"
    return target.resolve().as_uri()


def _collect_report_history() -> list[dict]:
    """
    Scans ARCHIVE_REPORTS_DIR for past report_YYYYMMDD_HHMMSS.html copies
    (written by run_daily.ps1, one per completed run) and returns them newest
    first. Today's own report isn't in there yet — run_daily.ps1 archives the
    copy AFTER build_report.py finishes — so it won't show in its own list,
    only in tomorrow's.
    """
    if not ARCHIVE_REPORTS_DIR.exists():
        return []
    entries = []
    for f in ARCHIVE_REPORTS_DIR.glob("report_*.html"):
        ts_part = f.stem[len("report_"):]
        try:
            dt = datetime.strptime(ts_part, "%Y%m%d_%H%M%S")
        except ValueError:
            continue
        entries.append({
            "date": dt.strftime("%Y-%m-%d"),
            "time": dt.strftime("%H:%M"),
            "label": dt.strftime("%Y-%m-%d %H:%M"),
            "url": _report_url_for(f),
        })
    entries.sort(key=lambda e: e["label"], reverse=True)
    return entries

TABLE_COLS = [
    "ticker", "sector", "industry", "current_price",
    "entry_price", "entry_basis", "stop_loss_price", "stop_loss_basis",
    "exit_price", "exit_basis", "target2_price", "target2_basis",
    "exit_days_estimate", "total_buy_votes", "total_sell_votes",
    "technical_net_vote", "quantitative_net_vote", "astrological_net_vote",
    "advanced_technical_net_vote", "gain_speed_score", "best_square9_angle",
    "best_square9_hit_rate", "signal_breakdown",
]

# One-line "how is this computed" explanation per column, shown as a native
# hover tooltip on the table header — answers "لما أقف على اسم التاب أشوف
# طريقة حسابها" without needing a separate docs page.
COLUMN_TOOLTIPS = {
    "ticker": "Stock ticker symbol (NASDAQ/NYSE).",
    "sector": "yfinance sector classification.",
    "current_price": "Latest close price from the run's yfinance fetch.",
    "entry_price": "Nearest support level below current price (Pivot Point S1/S2/S3 or the calibrated "
                    "Square of Nine projected level, whichever is closest) — the suggested pullback-buy "
                    "level, ALWAYS a real support level regardless of the committee's vote. Falls back to "
                    "current price only if no support level was found at all. Hover the value for the "
                    "exact basis used on this row.",
    "stop_loss_price": "The next support level down from entry_price (a second line of defense) — hover "
                        "for the exact basis. Blank if no second support level was identified.",
    "exit_price": "Nearest resistance level above current price (Pivot Point R1/R2/R3 or the calibrated "
                   "Square of Nine projected level) — the first realistic take-profit target, ALWAYS a real "
                   "resistance level regardless of vote. Falls back to the standard 30%-swing target only as "
                   "a reference floor if no resistance level was found at all. Hover the value for the exact "
                   "basis used on this row.",
    "target2_price": "The next resistance level up from exit_price (\"T2\") — a second, further profit "
                      "target if the first is reached. Hover for the exact basis. Blank if no second "
                      "resistance level was identified.",
    "exit_days_estimate": "This ticker's own historical median trading days to reach the swing target "
                           "(30% within 5 trading days), from swing_horizon_filter.evaluate_horizon_fit. "
                           "Blank if the target was never historically hit in that window.",
    "total_buy_votes": "Sum of buy votes across the Technical (4), Quantitative (2), Astrological (1), "
                        "and Advanced Technical (up to 4) groups. Primary ranking key.",
    "total_sell_votes": "Same as Buy but counting sell votes across all four groups.",
    "technical_net_vote": "Net vote (buy/sell/neutral) from 4 members: MACD crossover, Golden/Death "
                           "Cross, Bollinger Bands breakout, ADX-gated trend direction. Click/hover the "
                           "chip on a row for which specific member(s) voted which way.",
    "quantitative_net_vote": "Net vote from 2 members: analyst consensus (yfinance recommendations) "
                              "and unusual volume spike. Hover the chip for the per-member breakdown.",
    "astrological_net_vote": "Single vote: calibrated Gann Square of Nine level (per-ticker, tested "
                              "against that ticker's own historical pivots — not a fixed angle). Hover "
                              "the chip for the calibrated angle and hit rate used.",
    "advanced_technical_net_vote": "Net vote from up to 4 members: TA-Lib composite (RSI/MACD/BBANDS/"
                                    "ADX/Aroon/Stochastic/MFI/SAR), Ichimoku Cloud, Pivot Points, Volume "
                                    "Profile. Hover the chip for the per-member breakdown.",
    "gain_speed_score": "(target_gain% / historical median days to hit) × hit_rate — rewards a fast, "
                         "reliable path to the swing target over a slow or unreliable one. Tiebreaker "
                         "after total_buy_votes.",
    "best_square9_angle": "The Square of Nine overlay angle (0/45/90/.../315°) that historically "
                           "correlated best with this ticker's own pivots.",
    "best_square9_hit_rate": "Historical hit rate of best_square9_angle against this ticker's own "
                              "pivots during calibration.",
}


def build() -> None:
    if not RESULTS_CSV.exists():
        raise FileNotFoundError(f"{RESULTS_CSV} not found — run full_universe_analysis.py first.")

    df = pd.read_csv(RESULTS_CSV)

    missing = [c for c in TABLE_COLS if c not in df.columns]
    if missing:
        raise ValueError(
            f"{RESULTS_CSV} is missing columns {missing} — this CSV was written by an older "
            f"version of full_universe_analysis.py (its own run_timestamp column says "
            f"'{df['run_timestamp'].iloc[0] if 'run_timestamp' in df.columns else '?'}'). "
            f"Re-run `python src/full_universe_analysis.py` to completion first (it can take "
            f"tens of minutes across the full universe), THEN run build_report.py."
        )

    run_timestamp = df["run_timestamp"].iloc[0]

    net_buy = df[df["total_buy_votes"] > df["total_sell_votes"]].copy()
    net_buy = net_buy[TABLE_COLS]
    for col in ("current_price", "gain_speed_score", "best_square9_hit_rate", "entry_price", "exit_price"):
        net_buy[col] = net_buy[col].round(4)
    net_buy = net_buy.sort_values(
        ["total_buy_votes", "gain_speed_score"], ascending=[False, False], na_position="last"
    )

    records = _clean_nan(net_buy.to_dict(orient="records"))

    sector_counts = (
        net_buy["sector"].fillna("unknown").value_counts().sort_values(ascending=False)
    )
    sector_chart = [{"label": k, "value": int(v)} for k, v in sector_counts.items()]

    vote_counts = net_buy["total_buy_votes"].value_counts().sort_index()
    vote_chart = [{"label": str(int(k)), "value": int(v)} for k, v in vote_counts.items()]

    # Diversified shortlist: same rule as committee_signals.select_diversified_candidates
    # (net-buy lean, already true here; cap 1 per sector; top 3), recomputed here purely
    # for display since we only kept a trimmed column set above.
    shortlist = []
    seen_sectors: set[str] = set()
    for row in records:
        sector = row["sector"] or "unknown"
        if sector in seen_sectors:
            continue
        shortlist.append(row)
        seen_sectors.add(sector)
        if len(shortlist) >= 3:
            break

    stats = {
        "universe_total": 8199,
        "analyzed": len(df),
        "ethically_excluded": 535,
        "ethically_excluded_banks": 372,
        "ethically_excluded_defense": 78,
        "ethically_excluded_bds": 23,
        "ethically_excluded_review": 62,
        "insufficient_history": 1381,
        "net_buy_candidates": len(net_buy),
        "shortlist_count": len(shortlist),
        "run_timestamp": run_timestamp,
        "track_record": _load_outcome_summary(),
    }

    history = _collect_report_history()
    current_report_url = _report_url_for(OUTPUT_HTML)

    html = HTML_TEMPLATE.replace("__DATA_JSON__", json.dumps(records, separators=(",", ":")))
    html = html.replace("__SECTOR_CHART_JSON__", json.dumps(sector_chart))
    html = html.replace("__VOTE_CHART_JSON__", json.dumps(vote_chart))
    html = html.replace("__SHORTLIST_JSON__", json.dumps(shortlist))
    html = html.replace("__STATS_JSON__", json.dumps(stats))
    html = html.replace("__TOOLTIPS_JSON__", json.dumps(COLUMN_TOOLTIPS))
    html = html.replace("__HISTORY_JSON__", json.dumps(history))
    html = html.replace("__CURRENT_REPORT_URL_JSON__", json.dumps(current_report_url))

    OUTPUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_HTML.write_text(html, encoding="utf-8")
    print(f"Wrote {OUTPUT_HTML.resolve()} ({len(html):,} bytes, {len(records):,} candidate rows)")


HTML_TEMPLATE = r"""<title>Gann Committee Scanner — NASDAQ + NYSE</title>
<style>
:root {
  --bg: #edf0f2;
  --surface: #ffffff;
  --surface-2: #e4e8eb;
  --border: #d3d9dd;
  --ink: #1b2024;
  --ink-2: #4b545c;
  --ink-3: #7c868d;
  --accent: #a6742f;
  --accent-ink: #6b4a1d;
  --accent-soft: #f0e2c8;
  --buy: #3f7d5c;
  --buy-soft: #e1efe8;
  --sell: #b5533c;
  --sell-soft: #f6e5e0;
  --neutral: #8a8f98;
  --neutral-soft: #eaeced;
  --radius: 10px;
  --shadow: 0 1px 2px rgba(20, 24, 28, 0.06), 0 4px 14px rgba(20, 24, 28, 0.05);
  --font-display: "Iowan Old Style", "Palatino Linotype", Palatino, Georgia, serif;
  --font-body: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  --font-mono: ui-monospace, "SF Mono", "Cascadia Code", Consolas, "Roboto Mono", monospace;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #14181d;
    --surface: #1b2127;
    --surface-2: #232a31;
    --border: #313a42;
    --ink: #e7eaec;
    --ink-2: #b0b8be;
    --ink-3: #838d94;
    --accent: #d4a24c;
    --accent-ink: #e9c27a;
    --accent-soft: #3a2f1c;
    --buy: #6fbe94;
    --buy-soft: #1f2f27;
    --sell: #e2836a;
    --sell-soft: #33241f;
    --neutral: #8a939b;
    --neutral-soft: #242a2f;
    --shadow: 0 1px 2px rgba(0, 0, 0, 0.3), 0 4px 18px rgba(0, 0, 0, 0.35);
  }
}
:root[data-theme="dark"] {
  --bg: #14181d; --surface: #1b2127; --surface-2: #232a31; --border: #313a42;
  --ink: #e7eaec; --ink-2: #b0b8be; --ink-3: #838d94;
  --accent: #d4a24c; --accent-ink: #e9c27a; --accent-soft: #3a2f1c;
  --buy: #6fbe94; --buy-soft: #1f2f27; --sell: #e2836a; --sell-soft: #33241f;
  --neutral: #8a939b; --neutral-soft: #242a2f;
  --shadow: 0 1px 2px rgba(0, 0, 0, 0.3), 0 4px 18px rgba(0, 0, 0, 0.35);
}
:root[data-theme="light"] {
  --bg: #edf0f2; --surface: #ffffff; --surface-2: #e4e8eb; --border: #d3d9dd;
  --ink: #1b2024; --ink-2: #4b545c; --ink-3: #7c868d;
  --accent: #a6742f; --accent-ink: #6b4a1d; --accent-soft: #f0e2c8;
  --buy: #3f7d5c; --buy-soft: #e1efe8; --sell: #b5533c; --sell-soft: #f6e5e0;
  --neutral: #8a8f98; --neutral-soft: #eaeced;
  --shadow: 0 1px 2px rgba(20, 24, 28, 0.06), 0 4px 14px rgba(20, 24, 28, 0.05);
}

* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--ink);
  font-family: var(--font-body);
  font-size: 14.5px;
  line-height: 1.5;
}
.page { max-width: 1280px; margin: 0 auto; padding: 28px 20px 64px; }

header.top { margin-bottom: 28px; }
header.top .eyebrow {
  font-family: var(--font-mono);
  font-size: 11.5px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--accent-ink);
  margin-bottom: 6px;
}
header.top h1 {
  font-family: var(--font-display);
  font-weight: 600;
  font-size: 30px;
  margin: 0 0 6px;
  text-wrap: balance;
  letter-spacing: 0.01em;
}
header.top p.meta {
  color: var(--ink-2);
  font-size: 13.5px;
  margin: 0;
}
header.top p.meta span.sep { margin: 0 8px; color: var(--ink-3); }

.stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 12px;
  margin-bottom: 28px;
}
.stat {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 14px 16px;
  box-shadow: var(--shadow);
}
.stat .n {
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  font-size: 22px;
  font-weight: 600;
  display: block;
}
.stat .l { font-size: 11.5px; color: var(--ink-2); margin-top: 2px; }
.stat.accent .n { color: var(--accent-ink); }
.stat.buy .n { color: var(--buy); }

section { margin-bottom: 32px; }
h2.section-title {
  font-family: var(--font-display);
  font-size: 17px;
  font-weight: 600;
  margin: 0 0 12px;
  display: flex;
  align-items: baseline;
  gap: 8px;
}
h2.section-title .count {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--ink-3);
  font-weight: 400;
}

.shortlist { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }
.pick {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 18px 18px 16px;
  box-shadow: var(--shadow);
  position: relative;
}
.pick .rank {
  position: absolute; top: 14px; right: 16px;
  font-family: var(--font-mono); font-size: 11px; color: var(--ink-3);
}
.pick .ticker {
  font-family: var(--font-display);
  font-size: 24px; font-weight: 600;
}
.pick .sector { font-size: 12.5px; color: var(--ink-2); margin-bottom: 10px; }
.pick .price {
  font-family: var(--font-mono); font-variant-numeric: tabular-nums;
  font-size: 13px; color: var(--ink-2); margin-bottom: 12px; line-height: 1.6;
}
.pick .price .current { font-size: 15px; display: block; }
.pick .chips { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 10px; }
.pick .votes-line {
  font-family: var(--font-mono); font-variant-numeric: tabular-nums;
  font-size: 12.5px; color: var(--ink-2);
}
.pick .votes-line b { color: var(--buy); }

.chip {
  display: inline-flex; align-items: center; gap: 4px;
  font-size: 11px; padding: 3px 8px; border-radius: 99px;
  font-weight: 600; letter-spacing: 0.01em;
}
.chip.buy { background: var(--buy-soft); color: var(--buy); }
.chip.sell { background: var(--sell-soft); color: var(--sell); }
.chip.neutral, .chip.unavailable, .chip.none { background: var(--neutral-soft); color: var(--neutral); }

.charts { display: grid; grid-template-columns: 1.1fr 1fr; gap: 14px; }
.chart-card {
  background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius);
  padding: 16px 18px; box-shadow: var(--shadow);
}
.chart-card h3 {
  font-size: 12.5px; text-transform: uppercase; letter-spacing: 0.05em;
  color: var(--ink-2); margin: 0 0 12px; font-weight: 600;
}
.hbar-row { display: grid; grid-template-columns: 130px 1fr 40px; align-items: center; gap: 8px; margin-bottom: 7px; }
.hbar-row .label { font-size: 12px; color: var(--ink-2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.hbar-track { background: var(--surface-2); border-radius: 4px; height: 14px; overflow: hidden; }
.hbar-fill { background: var(--accent); height: 100%; border-radius: 4px 0 0 4px; }
.hbar-row .val { font-family: var(--font-mono); font-variant-numeric: tabular-nums; font-size: 11.5px; color: var(--ink-3); text-align: right; }

.vhist { display: flex; align-items: flex-end; gap: 8px; height: 160px; padding-top: 8px; }
.vhist .col { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: flex-end; height: 100%; }
.vhist .bar { width: 100%; background: var(--accent); border-radius: 4px 4px 2px 2px; min-height: 2px; }
.vhist .val { font-family: var(--font-mono); font-size: 10.5px; color: var(--ink-3); margin-bottom: 3px; }
.vhist .label { font-family: var(--font-mono); font-size: 11px; color: var(--ink-2); margin-top: 6px; }

.controls {
  display: flex; flex-wrap: wrap; gap: 10px; align-items: center;
  margin-bottom: 12px;
}
.controls input[type="text"], .controls select {
  font-size: 12.5px; padding: 7px 10px;
  border: 1px solid var(--border); border-radius: 7px;
  background: var(--surface); color: var(--ink); outline: none;
  font-family: var(--font-body);
}
.controls input[type="text"] { width: 160px; }
.controls label.range-label {
  font-size: 12px; color: var(--ink-2); display: flex; align-items: center; gap: 6px;
}
.controls input[type="range"] { width: 120px; }
.controls .result-count { margin-left: auto; font-size: 12px; color: var(--ink-3); }

.table-wrap { overflow-x: auto; border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface); box-shadow: var(--shadow); }
table { width: 100%; border-collapse: collapse; font-size: 12.5px; min-width: 1420px; }
thead th {
  padding: 10px 12px; background: var(--surface-2); border-bottom: 1px solid var(--border);
  color: var(--ink-2); font-weight: 600; text-align: left; white-space: nowrap;
  cursor: pointer; user-select: none; font-size: 11.5px; letter-spacing: 0.02em; text-transform: uppercase;
}
thead th:hover { color: var(--ink); }
thead th[title], .chip[title], td[title] { cursor: help; }
thead th.sorted::after { content: " \2193"; color: var(--accent-ink); }
thead th.sorted.asc::after { content: " \2191"; }
tbody td { padding: 8px 12px; border-bottom: 1px solid var(--border); vertical-align: middle; white-space: nowrap; }
tbody tr:last-child td { border-bottom: none; }
tbody tr:hover td { background: var(--surface-2); }
td.num, th.num { font-family: var(--font-mono); font-variant-numeric: tabular-nums; text-align: right; }
td.ticker-cell { font-weight: 600; font-family: var(--font-mono); }

.pagination { display: flex; align-items: center; gap: 10px; margin-top: 12px; font-size: 12.5px; color: var(--ink-2); }
.pagination button {
  font-family: var(--font-body); font-size: 12.5px; padding: 6px 12px;
  border: 1px solid var(--border); border-radius: 7px; background: var(--surface); color: var(--ink);
  cursor: pointer;
}
.pagination button:disabled { opacity: 0.4; cursor: default; }
.pagination button:not(:disabled):hover { border-color: var(--accent); }

.history-toolbar { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; position: relative; }
.history-toolbar .cal-toggle-btn {
  font-size: 13px; padding: 7px 10px; line-height: 1;
  border: 1px solid var(--border); border-radius: 7px; background: var(--surface); color: var(--ink-2);
  cursor: pointer;
}
.history-toolbar .cal-toggle-btn:hover, .history-toolbar .cal-toggle-btn.active { border-color: var(--accent); color: var(--ink); }
.history-toolbar .current-link {
  margin-left: auto; font-size: 12px; color: var(--accent-ink); text-decoration: none; font-weight: 600;
}
.history-toolbar .current-link:hover { text-decoration: underline; }

.cal-popover {
  position: absolute; top: calc(100% + 6px); left: 0; z-index: 20;
  width: 216px; background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius);
  box-shadow: var(--shadow); padding: 10px;
}
.calendar-nav { display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px; }
.calendar-nav button {
  font-family: var(--font-body); font-size: 12px; padding: 2px 7px; line-height: 1.4;
  border: 1px solid var(--border); border-radius: 5px; background: var(--surface); color: var(--ink);
  cursor: pointer;
}
.calendar-nav button:disabled { opacity: 0.35; cursor: default; }
.calendar-nav .month-label { font-size: 12px; font-weight: 600; color: var(--ink); }
.calendar-grid { display: grid; grid-template-columns: repeat(7, 1fr); gap: 2px; }
.calendar-grid .dow { font-size: 9px; text-transform: uppercase; color: var(--ink-3); text-align: center; padding-bottom: 2px; }
.calendar-grid .day-cell {
  aspect-ratio: 1; border-radius: 4px; background: transparent;
  display: flex; align-items: center; justify-content: center;
  font-size: 10.5px; color: var(--ink-2); position: relative;
}
.calendar-grid .day-cell.has-report { cursor: pointer; background: var(--surface-2); color: var(--ink); font-weight: 600; }
.calendar-grid .day-cell.has-report:hover { background: var(--accent-soft); color: var(--accent-ink); }
.calendar-grid .day-cell.has-report::after {
  content: ""; position: absolute; bottom: 2px; width: 3px; height: 3px; border-radius: 50%; background: var(--accent);
}
.calendar-day-runs { margin-top: 8px; display: flex; flex-direction: column; gap: 4px; border-top: 1px solid var(--border); padding-top: 8px; }
.calendar-day-runs a {
  font-size: 11.5px; color: var(--ink); text-decoration: none; padding: 4px 6px; border-radius: 5px;
}
.calendar-day-runs a:hover { background: var(--surface-2); }

footer.notes {
  margin-top: 36px; padding-top: 18px; border-top: 1px solid var(--border);
  font-size: 12px; color: var(--ink-3); line-height: 1.7;
}
footer.notes strong { color: var(--ink-2); }

@media (max-width: 900px) {
  .stats { grid-template-columns: repeat(3, 1fr); }
  .shortlist { grid-template-columns: 1fr; }
  .charts { grid-template-columns: 1fr; }
}
</style>

<div class="page">
  <header class="top">
    <div class="eyebrow">Gann Committee Scanner — Full Universe Run</div>
    <h1>NASDAQ + NYSE Candidate Report</h1>
    <p class="meta" id="meta-line"></p>
  </header>

  <section id="history-section">
    <h2 class="section-title">Previous reports <span class="count" id="history-count"></span></h2>
    <div class="history-toolbar">
      <button id="cal-toggle" class="cal-toggle-btn" title="Browse by calendar">📅 Browse by date</button>
      <a class="current-link" id="history-current-link" href="#">Latest report ↗</a>
      <div id="cal-popover" class="cal-popover" hidden>
        <div class="calendar-nav">
          <button id="cal-prev">←</button>
          <div class="month-label" id="cal-month-label"></div>
          <button id="cal-next">→</button>
        </div>
        <div class="calendar-grid" id="cal-grid"></div>
        <div class="calendar-day-runs" id="cal-day-runs"></div>
      </div>
    </div>
  </section>

  <div class="stats" id="stats"></div>

  <section>
    <h2 class="section-title">Diversified shortlist <span class="count">1 per sector, ranked highest-conviction first</span></h2>
    <div class="shortlist" id="shortlist"></div>
  </section>

  <section>
    <div class="charts">
      <div class="chart-card">
        <h3>Net-buy candidates by sector</h3>
        <div id="sector-chart"></div>
      </div>
      <div class="chart-card">
        <h3>Candidates by vote count (out of 11 possible)</h3>
        <div class="vhist" id="vote-chart"></div>
      </div>
    </div>
  </section>

  <section>
    <h2 class="section-title">All net-buy candidates <span class="count" id="table-total-count"></span></h2>
    <div class="controls">
      <input type="text" id="search" placeholder="Search ticker…">
      <select id="sector-filter"><option value="">All sectors</option></select>
      <label class="range-label">Min votes <input type="range" id="min-votes" min="2" max="9" value="3"><span id="min-votes-val">3</span></label>
      <span class="result-count" id="result-count"></span>
    </div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr id="table-head-row"></tr>
        </thead>
        <tbody id="table-body"></tbody>
      </table>
    </div>
    <div class="pagination">
      <button id="prev-page">← Prev</button>
      <span id="page-indicator"></span>
      <button id="next-page">Next →</button>
    </div>
  </section>

  <footer class="notes">
    <strong>Ethical filter (applied before analysis, per-ticker):</strong> banks and weapons/defense
    excluded mechanically via sector/industry classification; named companies excluded per the
    BDS Movement boycott list (bdsmovement.net/get-involved/what-to-boycott, snapshot 2026-07 —
    re-check periodically, this list is not auto-updated). Tickers whose sector/industry lookup
    failed are excluded pending manual review rather than assumed clean.<br>
    <strong>Ranking:</strong> total_buy_votes (sum across Technical, Quantitative, Astrological,
    Advanced Technical groups) descending first, then gain_speed_score as the tiebreaker — conditions
    before gain, to favor lower risk.<br>
    <strong>This is a candidate shortlist for your own research, not an order.</strong> Review
    preflight-checklist.md before acting on any of these.
  </footer>
</div>

<script id="data" type="application/json">__DATA_JSON__</script>
<script id="sector-chart-data" type="application/json">__SECTOR_CHART_JSON__</script>
<script id="vote-chart-data" type="application/json">__VOTE_CHART_JSON__</script>
<script id="shortlist-data" type="application/json">__SHORTLIST_JSON__</script>
<script id="stats-data" type="application/json">__STATS_JSON__</script>
<script id="tooltips-data" type="application/json">__TOOLTIPS_JSON__</script>
<script id="history-data" type="application/json">__HISTORY_JSON__</script>
<script id="current-report-url-data" type="application/json">__CURRENT_REPORT_URL_JSON__</script>

<script>
(function () {
  const DATA = JSON.parse(document.getElementById('data').textContent);
  const SECTOR_CHART = JSON.parse(document.getElementById('sector-chart-data').textContent);
  const VOTE_CHART = JSON.parse(document.getElementById('vote-chart-data').textContent);
  const SHORTLIST = JSON.parse(document.getElementById('shortlist-data').textContent);
  const STATS = JSON.parse(document.getElementById('stats-data').textContent);
  const TOOLTIPS = JSON.parse(document.getElementById('tooltips-data').textContent);
  const HISTORY = JSON.parse(document.getElementById('history-data').textContent);
  const CURRENT_REPORT_URL = JSON.parse(document.getElementById('current-report-url-data').textContent);

  // Column definitions for the main table — driven from one list so the
  // header row and each body row stay in sync, and so every header can carry
  // its "how is this computed" tooltip from TOOLTIPS.
  const COLUMNS = [
    { key: 'ticker', label: 'Ticker' },
    { key: 'sector', label: 'Sector' },
    { key: 'industry', label: 'Industry' },
    { key: 'current_price', label: 'Price', num: true },
    { key: 'entry_price', label: 'Entry', num: true },
    { key: 'stop_loss_price', label: 'Stop Loss', num: true },
    { key: 'exit_price', label: 'Exit', num: true },
    { key: 'target2_price', label: 'T2', num: true },
    { key: 'exit_days_estimate', label: 'Exit (days)', num: true },
    { key: 'total_buy_votes', label: 'Buy', num: true },
    { key: 'total_sell_votes', label: 'Sell', num: true },
    { key: 'technical_net_vote', label: 'Technical' },
    { key: 'quantitative_net_vote', label: 'Quant' },
    { key: 'astrological_net_vote', label: 'Astro' },
    { key: 'advanced_technical_net_vote', label: 'Adv. Tech' },
    { key: 'gain_speed_score', label: 'Gain speed', num: true },
    { key: 'best_square9_angle', label: 'Sq9 angle', num: true },
    { key: 'best_square9_hit_rate', label: 'Sq9 hit rate', num: true },
  ];

  document.getElementById('table-head-row').innerHTML = COLUMNS.map(c => `
    <th data-key="${c.key}" ${c.num ? 'class="num"' : ''} title="${esc(TOOLTIPS[c.key] || '')}">${c.label}</th>
  `).join('');

  const fmtPrice = (v) => v == null ? '—' : '$' + Number(v).toFixed(2);
  const fmtNum = (v, d) => v == null ? '—' : Number(v).toFixed(d);
  function esc(s) {
    return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');
  }

  // ---- per-group signal breakdown (which member voted buy/sell) ----
  // signal_breakdown is a JSON string with one key per committee group
  // (technical/quantitative/astrological/advanced_technical), each holding
  // that group's raw vote details. Rendered into the chip's native title
  // tooltip so hovering "Adv. Tech" on any row answers "which sub-signal
  // said buy here" without extra clicks.
  function formatDetailValue(v) {
    if (v == null) return 'n/a';
    if (typeof v === 'object') {
      return Object.entries(v).map(([k, vv]) => `${k}=${formatDetailValue(vv)}`).join(', ');
    }
    return String(v);
  }
  function groupBreakdownText(breakdown, groupKey) {
    if (!breakdown) return 'no per-signal detail available';
    let details;
    try { details = JSON.parse(breakdown)[groupKey]; } catch (e) { return 'no per-signal detail available'; }
    if (!details) return 'unavailable for this ticker';
    return Object.entries(details).map(([k, v]) => `${k}: ${formatDetailValue(v)}`).join('\n');
  }
  const chip = (v, breakdown, groupKey) => {
    const cls = v == null ? 'neutral' : String(v).toLowerCase();
    const label = v == null ? 'n/a' : v;
    const title = groupKey ? esc(groupBreakdownText(breakdown, groupKey)) : '';
    return `<span class="chip ${cls}" title="${title}">${label}</span>`;
  };

  // ---- meta line + stat tiles ----
  document.getElementById('meta-line').textContent =
    `Run ${STATS.run_timestamp} · ${STATS.universe_total.toLocaleString()} NASDAQ+NYSE tickers scanned`;

  const statTiles = [
    ['Universe scanned', STATS.universe_total, ''],
    ['Analyzed', STATS.analyzed, ''],
    ['Ethically excluded', STATS.ethically_excluded,
      `${STATS.ethically_excluded_banks} banks · ${STATS.ethically_excluded_defense} defense · ${STATS.ethically_excluded_bds} BDS · ${STATS.ethically_excluded_review} needs review`],
    ['Delisted / no data', STATS.insufficient_history, ''],
    ['Net-buy candidates', STATS.net_buy_candidates, 'buy'],
    ['Diversified shortlist', STATS.shortlist_count, 'accent'],
  ];
  // Track record (2026-07, track_outcomes.py): absent until that script has
  // run at least once and resolved at least one recommendation.
  const tr = STATS.track_record;
  if (tr && tr.hit_rate !== null && tr.hit_rate !== undefined) {
    statTiles.push([
      `Track record (${tr.window_days}d)`,
      `${(tr.hit_rate * 100).toFixed(0)}%`,
      `${tr.hits}/${tr.resolved} hit · ${tr.still_pending} pending`,
    ]);
  }
  document.getElementById('stats').innerHTML = statTiles.map(([label, n, cls]) => `
    <div class="stat ${cls === 'buy' || cls === 'accent' ? cls : ''}">
      <span class="n">${n.toLocaleString ? n.toLocaleString() : n}</span>
      <span class="l">${label}${typeof cls === 'string' && cls && cls !== 'buy' && cls !== 'accent' ? ' · ' + cls : ''}</span>
    </div>`).join('');

  // ---- shortlist cards ----
  document.getElementById('shortlist').innerHTML = SHORTLIST.map((r, i) => `
    <div class="pick">
      <span class="rank">#${i + 1}</span>
      <div class="ticker">${r.ticker}</div>
      <div class="sector">${r.sector || 'Unknown sector'}${r.industry ? ' · ' + r.industry : ''}</div>
      <div class="price">
        <span class="current">${fmtPrice(r.current_price)}</span>
        <span title="${esc(r.entry_basis || '')}">entry ${fmtPrice(r.entry_price)}</span> ·
        <span title="${esc(r.exit_basis || '')}">exit ${fmtPrice(r.exit_price)}</span><br>
        <span title="${esc(r.stop_loss_basis || '')}">stop ${fmtPrice(r.stop_loss_price)}</span> ·
        <span title="${esc(r.target2_basis || '')}">T2 ${fmtPrice(r.target2_price)}</span>
      </div>
      <div class="chips">
        ${chip(r.technical_net_vote, r.signal_breakdown, 'technical')}
        ${chip(r.quantitative_net_vote, r.signal_breakdown, 'quantitative')}
        ${chip(r.astrological_net_vote, r.signal_breakdown, 'astrological')}
        ${chip(r.advanced_technical_net_vote, r.signal_breakdown, 'advanced_technical')}
      </div>
      <div class="votes-line"><b>${r.total_buy_votes}</b> buy / ${r.total_sell_votes} sell votes · gain speed ${fmtNum(r.gain_speed_score, 3)}</div>
    </div>`).join('');

  // ---- sector chart (horizontal bars) ----
  const sectorMax = Math.max(...SECTOR_CHART.map(d => d.value));
  document.getElementById('sector-chart').innerHTML = SECTOR_CHART.map(d => `
    <div class="hbar-row">
      <div class="label">${d.label}</div>
      <div class="hbar-track"><div class="hbar-fill" style="width:${(d.value / sectorMax * 100).toFixed(1)}%"></div></div>
      <div class="val">${d.value}</div>
    </div>`).join('');

  // ---- vote histogram (vertical bars) ----
  const voteMax = Math.max(...VOTE_CHART.map(d => d.value));
  document.getElementById('vote-chart').innerHTML = VOTE_CHART.map(d => `
    <div class="col">
      <div class="val">${d.value}</div>
      <div class="bar" style="height:${Math.max(2, d.value / voteMax * 110)}px"></div>
      <div class="label">${d.label}</div>
    </div>`).join('');

  // ---- table: filters, sort, pagination ----
  const sectorSet = Array.from(new Set(DATA.map(r => r.sector || 'unknown'))).sort();
  const sectorSelect = document.getElementById('sector-filter');
  sectorSet.forEach(s => {
    const opt = document.createElement('option');
    opt.value = s; opt.textContent = s;
    sectorSelect.appendChild(opt);
  });

  let sortKey = 'total_buy_votes';
  let sortDir = -1; // -1 desc, 1 asc
  let page = 0;
  const pageSize = 50;

  const searchEl = document.getElementById('search');
  const minVotesEl = document.getElementById('min-votes');
  const minVotesVal = document.getElementById('min-votes-val');

  function getFiltered() {
    const q = searchEl.value.trim().toUpperCase();
    const sector = sectorSelect.value;
    const minVotes = Number(minVotesEl.value);
    return DATA.filter(r => {
      if (q && !r.ticker.toUpperCase().includes(q)) return false;
      if (sector && (r.sector || 'unknown') !== sector) return false;
      if (r.total_buy_votes < minVotes) return false;
      return true;
    });
  }

  function render() {
    minVotesVal.textContent = minVotesEl.value;
    let rows = getFiltered();
    rows.sort((a, b) => {
      let av = a[sortKey], bv = b[sortKey];
      if (av == null) av = sortDir === 1 ? Infinity : -Infinity;
      if (bv == null) bv = sortDir === 1 ? Infinity : -Infinity;
      if (typeof av === 'string') return sortDir * av.localeCompare(bv);
      return sortDir * (av - bv);
    });

    document.getElementById('result-count').textContent = `${rows.length.toLocaleString()} matching`;
    document.getElementById('table-total-count').textContent = `(${DATA.length.toLocaleString()} total)`;

    const maxPage = Math.max(0, Math.ceil(rows.length / pageSize) - 1);
    if (page > maxPage) page = maxPage;
    const pageRows = rows.slice(page * pageSize, page * pageSize + pageSize);

    document.getElementById('table-body').innerHTML = pageRows.map(r => `
      <tr>
        <td class="ticker-cell">${r.ticker}</td>
        <td>${r.sector || 'Unknown'}</td>
        <td>${r.industry || 'Unknown'}</td>
        <td class="num">${fmtPrice(r.current_price)}</td>
        <td class="num" title="${esc(r.entry_basis || '')}">${fmtPrice(r.entry_price)}</td>
        <td class="num" title="${esc(r.stop_loss_basis || '')}">${fmtPrice(r.stop_loss_price)}</td>
        <td class="num" title="${esc(r.exit_basis || '')}">${fmtPrice(r.exit_price)}</td>
        <td class="num" title="${esc(r.target2_basis || '')}">${fmtPrice(r.target2_price)}</td>
        <td class="num">${r.exit_days_estimate == null ? '—' : r.exit_days_estimate}</td>
        <td class="num">${r.total_buy_votes}</td>
        <td class="num">${r.total_sell_votes}</td>
        <td>${chip(r.technical_net_vote, r.signal_breakdown, 'technical')}</td>
        <td>${chip(r.quantitative_net_vote, r.signal_breakdown, 'quantitative')}</td>
        <td>${chip(r.astrological_net_vote, r.signal_breakdown, 'astrological')}</td>
        <td>${chip(r.advanced_technical_net_vote, r.signal_breakdown, 'advanced_technical')}</td>
        <td class="num">${fmtNum(r.gain_speed_score, 3)}</td>
        <td class="num">${r.best_square9_angle == null ? '—' : r.best_square9_angle}</td>
        <td class="num">${fmtNum(r.best_square9_hit_rate, 2)}</td>
      </tr>`).join('');

    document.getElementById('page-indicator').textContent = `Page ${page + 1} of ${maxPage + 1}`;
    document.getElementById('prev-page').disabled = page <= 0;
    document.getElementById('next-page').disabled = page >= maxPage;

    document.querySelectorAll('thead th[data-key]').forEach(th => {
      th.classList.toggle('sorted', th.dataset.key === sortKey);
      th.classList.toggle('asc', th.dataset.key === sortKey && sortDir === 1);
    });
  }

  document.querySelectorAll('thead th[data-key]').forEach(th => {
    th.addEventListener('click', () => {
      const key = th.dataset.key;
      if (sortKey === key) sortDir *= -1; else { sortKey = key; sortDir = -1; }
      page = 0;
      render();
    });
  });
  searchEl.addEventListener('input', () => { page = 0; render(); });
  sectorSelect.addEventListener('change', () => { page = 0; render(); });
  minVotesEl.addEventListener('input', () => { page = 0; render(); });
  document.getElementById('prev-page').addEventListener('click', () => { page--; render(); });
  document.getElementById('next-page').addEventListener('click', () => { page++; render(); });

  render();

  // ---- previous-reports picker: calendar popover only ----
  document.getElementById('history-current-link').href = CURRENT_REPORT_URL;
  document.getElementById('history-count').textContent =
    HISTORY.length ? `(${HISTORY.length.toLocaleString()} archived)` : '';

  const calToggle = document.getElementById('cal-toggle');
  const calPopover = document.getElementById('cal-popover');

  {
    // Merge today's own report in alongside the archive: it's never in
    // ARCHIVE_REPORTS_DIR yet (that copy is only made AFTER this file is
    // built — see _collect_report_history's docstring), so without this
    // the calendar would show nothing at all on day one / after a gap.
    const byDateMap = new Map();
    HISTORY.forEach(r => {
      if (!byDateMap.has(r.date)) byDateMap.set(r.date, []);
      byDateMap.get(r.date).push(r);
    });
    const todayEntry = { date: STATS.run_timestamp.slice(0, 10), time: STATS.run_timestamp.slice(11, 16), url: CURRENT_REPORT_URL };
    if (!byDateMap.has(todayEntry.date)) byDateMap.set(todayEntry.date, []);
    byDateMap.get(todayEntry.date).unshift(todayEntry);

    const latestDate = [...byDateMap.keys()].sort().at(-1);
    let calYear = Number(latestDate.slice(0, 4));
    let calMonth = Number(latestDate.slice(5, 7)) - 1; // 0-indexed

    function renderCalendar() {
      const monthNames = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
      document.getElementById('cal-month-label').textContent = `${monthNames[calMonth]} ${calYear}`;

      const firstOfMonth = new Date(calYear, calMonth, 1);
      const startDow = firstOfMonth.getDay();
      const daysInMonth = new Date(calYear, calMonth + 1, 0).getDate();

      const cells = ['S','M','T','W','T','F','S'].map(d => `<div class="dow">${d}</div>`);
      for (let i = 0; i < startDow; i++) cells.push('<div class="day-cell"></div>');
      for (let day = 1; day <= daysInMonth; day++) {
        const dateStr = `${calYear}-${String(calMonth + 1).padStart(2,'0')}-${String(day).padStart(2,'0')}`;
        const hasReport = byDateMap.has(dateStr);
        cells.push(`<div class="day-cell ${hasReport ? 'has-report' : ''}" data-date="${dateStr}">${day}</div>`);
      }
      document.getElementById('cal-grid').innerHTML = cells.join('');
      document.getElementById('cal-day-runs').innerHTML = '';

      document.querySelectorAll('.day-cell.has-report').forEach(cell => {
        cell.addEventListener('click', () => {
          const runs = byDateMap.get(cell.dataset.date) || [];
          document.getElementById('cal-day-runs').innerHTML = runs.map(r => `
            <a href="${esc(r.url)}">${r.time}</a>`).join('');
        });
      });
    }

    document.getElementById('cal-prev').addEventListener('click', () => {
      calMonth--; if (calMonth < 0) { calMonth = 11; calYear--; }
      renderCalendar();
    });
    document.getElementById('cal-next').addEventListener('click', () => {
      calMonth++; if (calMonth > 11) { calMonth = 0; calYear++; }
      renderCalendar();
    });

    calToggle.addEventListener('click', (e) => {
      e.stopPropagation();
      const opening = calPopover.hidden;
      calPopover.hidden = !opening;
      calToggle.classList.toggle('active', opening);
      if (opening) renderCalendar();
    });
    document.addEventListener('click', (e) => {
      if (!calPopover.hidden && !calPopover.contains(e.target) && e.target !== calToggle) {
        calPopover.hidden = true;
        calToggle.classList.remove('active');
      }
    });
  }
})();
</script>
"""


if __name__ == "__main__":
    build()
