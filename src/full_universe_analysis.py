"""
full_universe_analysis.py — Runs the FULL analysis stack (increment method
comparison, Gann angle calibration, technical committee, swing-horizon fit)
across EVERY NASDAQ/NYSE-listed ticker (per project decision 2026-07 — widened
from the earlier 217-stock static allow-list), fetching real price data from
Yahoo Finance via yfinance.

TICKER UNIVERSE SOURCE (widened 2026-07, moved to the cloud 2026-07): ticker
SYMBOLS (names only, not price data) are read from the repo-committed
TICKER_UNIVERSE_CSV — see load_ticker_universe(). That CSV is itself generated
from Abdo's local offline Stooq-format dump by refresh_ticker_universe.py, a
separate manual/occasional script (only runnable on Abdo's own machine, which
is the only place that can see the dump). This script never touches the local
dump directly, so it runs identically on GitHub Actions or any other machine.
The dump's own price data is stale and is NOT used for analysis; every ticker
still gets a fresh yfinance fetch. The dump also contains long-delisted
tickers (its history goes back to 2000) — these simply fail/get skipped by
analyze_ticker's existing "insufficient history" check when yfinance has no
current data for them, same as any other unfetchable ticker.

ETHICAL FILTER (project decision 2026-07): every ticker is screened via
ethical_screen.screen_ticker() BEFORE any price history is fetched, excluding
weapons/defense and banks (mechanical, via yfinance sector/industry) and
tickers on Abdo's BDS Movement boycott-list mapping (see ethical_screen.py's
module docstring for exactly what's covered and why). This replaced the old
217-stock static HTML allow-list, which had no discoverable filtering logic
in this repo to extend to a larger universe.

RUNS IN THE CLOUD (2026-07): scheduled via .github/workflows/daily-scan.yml on
GitHub Actions — no local machine needs to be on. See that workflow file for
the exact steps (dependency install, this script, build_report.py, archiving,
committing results back, and publishing to GitHub Pages).

WHAT IT COMPUTES PER TICKER:
    1. Recommended price increment: book method vs. volatility/degrees method
       (gann_increment_selection.py), compared empirically via touch-rate.
    2. Best-fit Square of Nine angle for that ticker, using whichever increment
       method scored higher (gann_decision_system.calibrate_square9_angle).
    3. Technical committee vote (MACD, Golden/Death Cross, Bollinger, ADX)
       (committee_signals.evaluate_technical_group).
    4. Quantitative committee vote (analyst consensus, volume spike)
       (committee_signals.evaluate_quantitative_group, MERGED 2026-07 from
       committee_signals.py so this script carries the same full vote set).
    5. Astrological committee vote: calibrated Square of Nine vote
       (committee_signals.get_astrological_votes, MERGED 2026-07 — same
       function committee_signals.py itself uses, not duplicated).
    6. Advanced technical committee vote (TA-Lib's RSI/MACD/BBANDS/ADX/Aroon/
       Stochastic/MFI/SAR + Ichimoku Cloud + Pivot Points + Volume Profile)
       (advanced_technical_tools.evaluate_advanced_technical_group, ACTIVATED
       2026-07) — reported alongside the existing technical vote as its own
       column, not blended into it, so its contribution stays auditable
       separately. TA-Lib's own sub-vote needs `pip install ta-lib`; the other
       three (Ichimoku/Pivots/Volume Profile) work regardless.
    7. Swing-horizon fit for Abdo's own trading profile: hit rate of reaching
       the target gain within the target holding period
       (swing_horizon_filter.evaluate_horizon_fit) — defaults set to 30%/5
       trading days per his stated profile (2026-07, revised 2026-07-23), but
       configurable via the constants below.
    8. Entry/exit/stop-loss/T2 price levels (compute_entry_exit_levels, ADDED
       2026-07, CORRECTED 2026-07): combines the Astrological group's
       calibrated Square of Nine projected level with ONE of two candidate
       support/resistance sources, selected by SUPPORT_RESISTANCE_METHOD —
       Pivot Points (S1/S2/S3/R1/R2/R3) or Fibonacci retracement off the
       latest ZigZag swing — both already computed above, not a new invented
       formula. Which of the two wins is decided empirically, globally,
       from a full historical backtest comparison (see backtest.py
       --compare-support-method), not per-ticker. Entry is ALWAYS the
       nearest support (a real pullback level, not "buy now"), exit ALWAYS
       the nearest resistance, regardless of the committee's vote — see
       compute_entry_exit_levels's docstring for the exact rule and why.

RANKING (per project decision 2026-07, conditions before gain to favor lower
    risk): total_buy_votes (sum across Technical + Quantitative + Astrological
    + Advanced Technical) descending first, then gain_speed_score (hit_rate /
    median_days_to_hit for the target swing-trading profile) as the tiebreaker.
    A DIVERSIFIED SHORTLIST (same selection logic as
    committee_signals.select_diversified_candidates: net-buy lean, capped at
    1 candidate per sector) is also printed at the end, on top of the full
    ranked CSV — the bigger the universe, the more sector concentration is a
    real risk worth capping.

ESTIMATED RUNTIME: with concurrency (MAX_WORKERS threads, see below) across a
universe of several thousand tickers and 2-3 yfinance calls each (ethical
screen, price history, analyst recommendations), a full run is expected to
take on the order of tens of minutes rather than the multi-hour runtime a
purely sequential loop would need. Run every ~3 months (per Abdo's stated
cadence, 2026-07); refine/re-check the resulting shortlist monthly in
between rather than re-running this full scan.

Run:
    python src/full_universe_analysis.py
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import pandas as pd
import yfinance as yf

from gann_increment_selection import compare_increment_methods
from gann_decision_system import calibrate_square9_angle
from committee_signals import (
    evaluate_technical_group,
    evaluate_quantitative_group,
    get_astrological_votes,
    select_diversified_candidates,
)
from advanced_technical_tools import evaluate_advanced_technical_group
from swing_horizon_filter import evaluate_horizon_fit
from ethical_screen import screen_ticker
from yf_retry import call_with_retry

# Ticker universe (2026-07, moved to the cloud): SYMBOLS only, checked into
# the repo at TICKER_UNIVERSE_CSV so this script runs unchanged on GitHub
# Actions (or any machine), not just Abdo's, which is the only place that can
# see LOCAL_MARKET_DATA_DIR. Regenerate the CSV from that local dump with
# refresh_ticker_universe.py whenever Abdo wants to widen/refresh the universe
# — a manual, occasional step, not part of the daily run.
TICKER_UNIVERSE_CSV = Path("data/ticker_universe.csv")

# Abdo's local offline Stooq-format historical data dump. Used by
# refresh_ticker_universe.py to enumerate ticker SYMBOLS (filenames), and
# (2026-07, per Abdo's explicit instruction — see CLAUDE.md) by backtest.py
# for actual PRICE DATA too, now that build_local_ticker_index()/
# load_local_history() exist. "etfs" and "nysemkt" (NYSE American) sibling
# folders in the same dump are deliberately excluded — Abdo asked
# specifically for NASDAQ + NYSE common stocks.
#
# PATH CORRECTED 2026-07: the dump actually lives one level deeper than this
# constant used to point to — `...\data\daily\us` (no nested `data\daily`)
# silently resolves to a STALE duplicate copy of the dump (confirmed: AAL's
# last bar there is 2026-04-02), while `...\data\daily\data\daily\us` is the
# live, current one (AAL's last bar there is 2026-06-24). Both paths exist on
# disk, so this was silently returning stale data with no error — verify
# LOCAL_MARKET_DATA_DIR's last-bar date against today whenever this dump is
# touched again.
LOCAL_MARKET_DATA_DIR = Path(r"D:\EGX.Daily.2000-2023\data\daily\data\daily\us")
EXCHANGE_SUBFOLDERS = ("nasdaq stocks", "nyse stocks")

OUTPUT_CSV = Path("runs/full_universe_results.csv")
# The diversified shortlist (below) is also saved here, in committee_signals.py's
# original output shape, so format_report.py keeps working unchanged post-TS-removal.
COMMITTEE_CANDIDATES_CSV = Path("runs/committee_candidates.csv")

# Per project decision (2026-07): keep every run, not just the latest — every
# script in this project that writes a "latest" output also archives a
# timestamped copy alongside it, so past runs stay available as potential
# future training/comparison data.
ARCHIVE_DIR = Path("runs/archive")

# Abdo's stated swing-trading profile (2026-07, revised again 2026-07-23 to
# 30%/5 trading days): adjust here to test other holding-period/target-gain
# combinations without touching the logic below.
TARGET_HOLDING_DAYS = 5
TARGET_GAIN_PCT = 30.0

# Eligibility cache (2026-07): with the daily schedule (run_daily.ps1 via
# register_scheduled_task.ps1), re-running the ethical screen (1 yfinance
# .info call/ticker) and the history-existence check across all ~8,199
# tickers EVERY DAY was pure waste — a ticker excluded for being a bank, or
# without enough price history, doesn't change status overnight. This caches
# each ticker's last-known status (eligible / excluded / insufficient_history)
# to disk and skips straight past anything checked within CACHE_TTL_DAYS,
# without ever touching yfinance for it. Price/indicator data for ELIGIBLE
# tickers is still fetched fresh every run — only the classification step is
# cached, never the trading signal itself. Fetch failures (network/rate-limit)
# are deliberately never cached, so a transient miss always gets retried next
# run rather than silently sticking forever.
ELIGIBILITY_CACHE_PATH = Path("runs/ticker_eligibility_cache.json")
CACHE_TTL_DAYS = 30


def _load_eligibility_cache() -> dict:
    if not ELIGIBILITY_CACHE_PATH.exists():
        return {}
    try:
        return json.loads(ELIGIBILITY_CACHE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_eligibility_cache(cache: dict) -> None:
    ELIGIBILITY_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    ELIGIBILITY_CACHE_PATH.write_text(json.dumps(cache, indent=2, sort_keys=True), encoding="utf-8")


def _cache_is_fresh(entry: dict) -> bool:
    try:
        checked = datetime.fromisoformat(entry["last_checked"])
    except (KeyError, ValueError):
        return False
    return (datetime.now() - checked).days < CACHE_TTL_DAYS


REQUEST_DELAY_SECONDS = 1.0  # small per-ticker pacing, applied per worker thread — see analyze_ticker
# Lowered from an initial MAX_WORKERS=8 (2026-07): that combination triggered Yahoo's
# rate limiter after only ~500 tickers, after which nearly everything failed for the
# rest of the run (Yahoo's block does not clear itself quickly). 3 workers + retry
# backoff (yf_retry.call_with_retry, used at every yfinance call site) is slower but
# actually completes instead of silently losing most of the universe.
MAX_WORKERS = 3


def load_ticker_universe() -> list[str]:
    """
    Reads the ticker universe (symbols only) from TICKER_UNIVERSE_CSV, checked
    into the repo so this runs the same on GitHub Actions as on Abdo's own
    machine. Run refresh_ticker_universe.py locally (the only place with
    access to LOCAL_MARKET_DATA_DIR) to regenerate this file when the universe
    needs updating.
    """
    if not TICKER_UNIVERSE_CSV.exists():
        raise FileNotFoundError(
            f"{TICKER_UNIVERSE_CSV} not found — run `python src/refresh_ticker_universe.py` "
            f"first (needs LOCAL_MARKET_DATA_DIR, so only works on Abdo's own machine)."
        )
    # keep_default_na=False: pandas' default NA-marker list includes "NA" and
    # "NULL" — both real NASDAQ/NYSE ticker symbols — which would otherwise
    # silently turn into a missing value here (confirmed 2026-07: ticker "NA"
    # was dropped this way, tripping a float-vs-str sort error).
    df = pd.read_csv(TICKER_UNIVERSE_CSV, keep_default_na=False)
    return sorted(df["ticker"].astype(str).str.upper().unique())


def build_local_ticker_index() -> dict:
    """
    Maps TICKER -> file path across LOCAL_MARKET_DATA_DIR's exchange
    subfolders (built once and reused — rglob-ing per ticker for a
    400-1000-ticker backtest would be needlessly slow). Local-machine-only,
    same as LOCAL_MARKET_DATA_DIR itself.
    """
    index: dict = {}
    for sub in EXCHANGE_SUBFOLDERS:
        base = LOCAL_MARKET_DATA_DIR / sub
        if not base.exists():
            continue
        for txt_file in base.rglob("*.us.txt"):
            index[txt_file.stem.split(".")[0].upper()] = txt_file
    return index


def load_local_history(ticker: str, index: dict) -> pd.DataFrame | None:
    """
    Loads one ticker's full daily OHLCV history from Abdo's local Stooq-format
    dump (LOCAL_MARKET_DATA_DIR), reshaped to the same column names/shape
    yfinance's .history() returns (Open/High/Low/Close/Volume, DatetimeIndex)
    so evaluate_ticker_snapshot works unchanged regardless of the source.

    ADDED 2026-07 per Abdo's explicit instruction: ALL backtesting must run
    against this local dump, not yfinance — it removes both the network
    dependency and Yahoo's rate-limiting (see MAX_WORKERS/REQUEST_DELAY_SECONDS
    above), which is what made a 400+/1000-ticker backtest impractical before.
    Returns None (not an exception) if the ticker isn't in the local dump —
    same "skip, don't crash the whole run" contract backtest.py already uses
    for fetch failures.
    """
    path = index.get(ticker.upper())
    if path is None:
        return None
    df = pd.read_csv(path)
    df.columns = [c.strip("<>") for c in df.columns]
    if df.empty or "DATE" not in df.columns:
        return None
    df["DATE"] = pd.to_datetime(df["DATE"], format="%Y%m%d")
    df = df.set_index("DATE").sort_index()
    df = df.rename(columns={"OPEN": "Open", "HIGH": "High", "LOW": "Low", "CLOSE": "Close", "VOL": "Volume"})
    return df[["Open", "High", "Low", "Close", "Volume"]]


def touch_test(high: pd.Series, low: pd.Series, close: pd.Series, increment: float) -> float:
    if increment <= 0:
        return 0.0
    calib = calibrate_square9_angle(high, low, close, increment)
    return max((r.hit_rate for r in calib), default=0.0)


# Which per-ticker price levels feed entry/exit alongside the calibrated
# Square of Nine level: "pivot" (Pivot Points S1-S3/R1-R3) or "fibonacci"
# (retracement levels off the latest confirmed ZigZag swing). Per Abdo's
# request (2026-07), the choice is decided empirically — whichever scores a
# higher hit_rate across the FULL historical backtest (src/backtest.py
# --compare-support-method) wins and gets set here, not a per-ticker or
# per-vote pick. See backtest.py's module docstring for the comparison run
# that produced the current value.
SUPPORT_RESISTANCE_METHOD = "fibonacci"  # "pivot" | "fibonacci" — set by backtest comparison
# DECIDED 2026-07-12, CONFIRMED at full scale same day: backtest.py
# --compare-support-method against the local dump (see CLAUDE.md's
# backtesting rule) first ran at 30 tickers/3 months (fibonacci
# hit_rate=0.111 vs pivot 0.095, 126/126 resolved calls each — see
# runs/backtest/support_method_comparison_20260712_203613/summary.md), then
# at the full 400-ticker/6-month default (fibonacci hit_rate=0.098 vs pivot
# 0.073, 4078/4078 resolved calls each — see
# runs/backtest/support_method_comparison_20260712_214850/summary.md).
# Fibonacci won both times, with a wider margin at the larger sample. Re-run
# the comparison and update this constant if a future run shifts the result.


def compute_entry_exit_levels(
    current_price: float,
    pivot_points: dict | None,
    square9_projected_level: float | None,
    target_gain_pct: float,
    median_days_to_hit: float | None,
    fibonacci_levels: dict | None = None,
    support_resistance_method: str = SUPPORT_RESISTANCE_METHOD,
) -> dict:
    """
    Combines one of two candidate support/resistance sources — Pivot Points
    (advanced_technical_tools.compute_pivot_points) or Fibonacci retracement
    (advanced_technical_tools.compute_fibonacci_levels), selected by
    support_resistance_method — with the calibrated Square of Nine level
    (gann_decision_system.gann_committee_vote's projected_price_level).
    These are the per-ticker price levels this project already computes and
    tests, rather than inventing a new untested formula.

    CORRECTED 2026-07 (per Abdo's explicit correction — entry/exit were
    previously just "current price" and "current price + target_gain_pct%",
    which isn't a real technical entry/exit at all): entry_price is ALWAYS
    the nearest support below current price (pivot/Fibonacci level or the
    Square9 level, whichever is closest) — a real pullback level, regardless
    of the committee's vote. stop_loss_price is the next support down (a
    second line of defense). exit_price is ALWAYS the nearest resistance
    above current price, and target2_price the next resistance up (T2),
    again regardless of vote. target_gain_pct is used ONLY as a last-resort
    reference floor for exit_price when literally no resistance level was
    found at all — a criterion, not a hard rule, per Abdo's own wording.

    exit_days_estimate: this ticker's own historical median days-to-hit for
    the swing-trading profile (swing_horizon_filter.evaluate_horizon_fit),
    reused rather than guessed — None if the target was never hit historically.
    """
    supports, resistances = [], []
    if support_resistance_method == "fibonacci":
        if fibonacci_levels and isinstance(fibonacci_levels, dict):
            for level in (fibonacci_levels.get("levels") or {}).values():
                if level is None:
                    continue
                if level < current_price:
                    supports.append(level)
                elif level > current_price:
                    resistances.append(level)
    else:
        if pivot_points and isinstance(pivot_points, dict):
            for key in ("s1", "s2", "s3"):
                level = pivot_points.get(key)
                if level is not None and level < current_price:
                    supports.append(level)
            for key in ("r1", "r2", "r3"):
                level = pivot_points.get(key)
                if level is not None and level > current_price:
                    resistances.append(level)
    if square9_projected_level is not None:
        if square9_projected_level < current_price:
            supports.append(square9_projected_level)
        elif square9_projected_level > current_price:
            resistances.append(square9_projected_level)

    supports = sorted(set(supports), reverse=True)  # nearest-to-price first
    resistances = sorted(set(resistances))  # nearest-to-price first
    source_label = "Fibonacci/Square9" if support_resistance_method == "fibonacci" else "pivot/Square9"

    if supports:
        entry_price = round(supports[0], 2)
        entry_basis = f"nearest {source_label} support below current price"
    else:
        entry_price = round(current_price, 2)
        entry_basis = "no support level identified below current price — current price used"

    if len(supports) >= 2:
        stop_loss_price = round(supports[1], 2)
        stop_loss_basis = "second-nearest support below current price"
    else:
        stop_loss_price = None
        stop_loss_basis = "no second support level identified"

    if resistances:
        exit_price = round(resistances[0], 2)
        exit_basis = f"nearest {source_label} resistance above current price"
    else:
        exit_price = round(current_price * (1 + target_gain_pct / 100), 2)
        exit_basis = f"no resistance level identified — {target_gain_pct:.0f}% swing target used as a reference floor"

    if len(resistances) >= 2:
        target2_price = round(resistances[1], 2)
        target2_basis = "second-nearest resistance above current price (T2)"
    else:
        target2_price = None
        target2_basis = "no second resistance level identified"

    exit_days_estimate = round(median_days_to_hit) if median_days_to_hit else None

    return {
        "entry_price": entry_price,
        "entry_basis": entry_basis,
        "stop_loss_price": stop_loss_price,
        "stop_loss_basis": stop_loss_basis,
        "exit_price": exit_price,
        "exit_basis": exit_basis,
        "target2_price": target2_price,
        "target2_basis": target2_basis,
        "exit_days_estimate": exit_days_estimate,
    }


def evaluate_ticker_snapshot(
    ticker: str,
    hist: pd.DataFrame,
    sector: str | None,
    industry: str | None,
    target_gain_pct: float = TARGET_GAIN_PCT,
    target_holding_days: int = TARGET_HOLDING_DAYS,
    include_analyst_consensus: bool = True,
    support_resistance_method: str = SUPPORT_RESISTANCE_METHOD,
) -> dict:
    """
    The actual decision-making core, shared by the live daily path
    (analyze_ticker, below) and src/backtest.py (2026-07, ADDED to let both
    reuse identical logic instead of the backtest silently drifting from
    live behavior over time). Takes `hist` as given — the caller decides
    whether it's a live 2-year fetch or a truncated as-of-some-past-date
    slice; this function has no opinion on that and does no fetching itself.

    include_analyst_consensus=False (backtest only): yfinance's analyst
    consensus is a CURRENT-only snapshot with no historical point-in-time
    equivalent, so it's not reconstructable for a past as-of date — dropping
    it is the one deliberate difference between backtest and live scoring
    (see committee_signals.evaluate_quantitative_group).

    NOTE for backtest scoring: best_square9_angle/best_square9_hit_rate below
    (from compare_increment_methods+touch_test) are a SEPARATE calibration
    from the one get_astrological_votes actually votes on internally (via
    gann_increment_selection.recommended_price_increment) — cosmetic/
    reporting columns, not "the angle the committee traded on". Don't score
    backtest outcomes against best_square9_angle expecting it to explain
    astrological_net_vote.

    Raises on any analysis failure — same "one ticker's failure shouldn't
    stop the whole run" contract as before, just left to the caller (which
    differs between the live per-ticker thread and a backtest per-ticker/date
    loop) instead of swallowed here.
    """
    increment_comparison = compare_increment_methods(hist["High"], hist["Low"], hist["Close"], touch_test)
    best_method_row = increment_comparison.iloc[0]

    calib = calibrate_square9_angle(hist["High"], hist["Low"], hist["Close"], best_method_row["increment"])
    best_angle = calib[0] if calib else None

    tech = evaluate_technical_group(hist)
    quant = evaluate_quantitative_group(ticker, hist, include_analyst_consensus=include_analyst_consensus)
    astro = get_astrological_votes(ticker, hist)  # calibrated Square of Nine vote (see committee_signals.py)
    advanced_tech = evaluate_advanced_technical_group(hist)  # ACTIVATED 2026-07

    total_buy_votes = tech.votes_buy + quant.votes_buy + advanced_tech.votes_buy
    total_sell_votes = tech.votes_sell + quant.votes_sell + advanced_tech.votes_sell
    if astro is not None:
        total_buy_votes += astro.votes_buy
        total_sell_votes += astro.votes_sell

    horizon = evaluate_horizon_fit(hist["Close"], target_gain_pct, target_holding_days)

    current_price = float(hist["Close"].iloc[-1])
    pivot_points = advanced_tech.details.get("pivot_points")
    if not isinstance(pivot_points, dict):
        pivot_points = None
    fibonacci_levels = advanced_tech.details.get("fibonacci_levels")
    if not isinstance(fibonacci_levels, dict):
        fibonacci_levels = None
    square9_projected_level = astro.details.get("square9_projected_price_level") if astro else None
    entry_exit = compute_entry_exit_levels(
        current_price, pivot_points, square9_projected_level,
        target_gain_pct, horizon.median_days_to_hit,
        fibonacci_levels=fibonacci_levels,
        support_resistance_method=support_resistance_method,
    )

    # "Highest likely gain in the shortest time" isn't hit_rate alone (that's
    # just success probability) — it's gain achieved PER DAY when it does hit.
    # A stock hitting +20% in a 5-day median beats one hitting +20% in a
    # 14-day median even if both have similar hit rates. Weighted by hit_rate
    # so a fast-but-rare hit doesn't outrank a reliable one on a technicality
    # (Pillar 4: the ranking metric should mean what the user actually asked
    # for, not just be the first plausible-looking number).
    if horizon.median_days_to_hit and horizon.median_days_to_hit > 0:
        gain_speed_score = round(
            (target_gain_pct / horizon.median_days_to_hit) * horizon.hit_rate, 4
        )
    else:
        gain_speed_score = None  # never hit the target in this window — no meaningful rate

    # Per-signal breakdown (which member of each group voted buy/sell) —
    # serialized as JSON so build_report.py can render it as a per-row,
    # per-group "why" tooltip without a schema change every time a new
    # sub-signal is added to any group. json.dumps(default=str) covers the
    # astrological group's date objects (upcoming_time_cycle_dates).
    signal_breakdown = json.dumps(
        {
            "technical": tech.details,
            "quantitative": quant.details,
            "astrological": astro.details if astro else None,
            "advanced_technical": advanced_tech.details,
        },
        default=str,
    )

    return {
        "ticker": ticker,
        "sector": sector,
        "industry": industry,
        "current_price": current_price,
        "best_increment_method": best_method_row["method"],
        "best_increment_value": best_method_row["increment"],
        "best_square9_angle": best_angle.angle if best_angle else None,
        "best_square9_hit_rate": round(best_angle.hit_rate, 2) if best_angle else None,
        "technical_net_vote": tech.net_vote,
        "technical_buy_votes": tech.votes_buy,
        "quantitative_net_vote": quant.net_vote,
        "quantitative_buy_votes": quant.votes_buy,
        "astrological_status": "unavailable_insufficient_history" if astro is None else "implemented",
        "astrological_net_vote": astro.net_vote if astro else None,
        "advanced_technical_net_vote": advanced_tech.net_vote,
        "advanced_technical_buy_votes": advanced_tech.votes_buy,
        "total_buy_votes": total_buy_votes,
        "total_sell_votes": total_sell_votes,
        f"horizon_fit_{target_gain_pct}pct_{target_holding_days}d": horizon.hit_rate,
        "horizon_median_days_when_hit": horizon.median_days_to_hit,
        "gain_speed_score": gain_speed_score,
        "entry_price": entry_exit["entry_price"],
        "entry_basis": entry_exit["entry_basis"],
        "stop_loss_price": entry_exit["stop_loss_price"],
        "stop_loss_basis": entry_exit["stop_loss_basis"],
        "exit_price": entry_exit["exit_price"],
        "exit_basis": entry_exit["exit_basis"],
        "target2_price": entry_exit["target2_price"],
        "target2_basis": entry_exit["target2_basis"],
        "exit_days_estimate": entry_exit["exit_days_estimate"],
        "signal_breakdown": signal_breakdown,
    }


def analyze_ticker(ticker: str, cache: dict) -> dict | None:
    cached = cache.get(ticker)

    if cached and cached["status"] == "excluded" and _cache_is_fresh(cached):
        print(f"SKIPPED {ticker}: excluded by ethical filter (cached) — {cached['reason']}")
        return None
    if cached and cached["status"] == "insufficient_history" and _cache_is_fresh(cached):
        print(f"SKIPPED {ticker}: insufficient history (cached, last checked {cached['last_checked'][:10]}).")
        return None

    now = datetime.now().isoformat()
    trust_cached_screen = cached and cached["status"] == "eligible" and _cache_is_fresh(cached)

    if trust_cached_screen:
        sector, industry = cached["sector"], cached["industry"]
    else:
        time.sleep(REQUEST_DELAY_SECONDS)  # small per-thread pacing to stay polite to Yahoo under concurrency
        screen = screen_ticker(ticker)
        sector, industry = screen.sector, screen.industry
        if screen.excluded:
            cache[ticker] = {
                "status": "excluded", "reason": screen.reason,
                "sector": sector, "industry": industry, "last_checked": now,
            }
            print(f"SKIPPED {ticker}: excluded by ethical filter — {screen.reason}")
            return None

    time.sleep(REQUEST_DELAY_SECONDS)  # small per-thread pacing to stay polite to Yahoo under concurrency
    try:
        hist = call_with_retry(lambda: yf.Ticker(ticker).history(period="2y"))
    except Exception as exc:  # noqa: BLE001 - transient (network/rate-limit): never cached, always retried next run
        print(f"WARNING: fetch failed for {ticker}: {exc}")
        return None

    if hist.empty or len(hist) < 120:
        cache[ticker] = {
            "status": "insufficient_history", "reason": None,
            "sector": sector, "industry": industry, "last_checked": now,
        }
        print(f"SKIPPED {ticker}: insufficient history ({len(hist)} bars).")
        return None

    try:
        result = evaluate_ticker_snapshot(ticker, hist, sector, industry)
        cache[ticker] = {
            "status": "eligible", "reason": None,
            "sector": sector, "industry": industry, "last_checked": now,
        }
        return result
    except Exception as exc:  # noqa: BLE001 - one ticker's analysis failure shouldn't stop the whole run
        print(f"WARNING: analysis failed for {ticker}: {exc}")
        return None


def main() -> None:
    tickers = load_ticker_universe()
    print(f"Loaded {len(tickers)} tickers from NASDAQ + NYSE (local universe file, ethical filter applied per-ticker).")
    print(f"Swing-trading profile: {TARGET_GAIN_PCT}% target within {TARGET_HOLDING_DAYS} trading days.")

    cache = _load_eligibility_cache()
    if cache:
        fresh = sum(1 for e in cache.values() if _cache_is_fresh(e))
        print(f"Loaded eligibility cache: {len(cache)} tickers known, {fresh} still fresh "
              f"(< {CACHE_TTL_DAYS} days old) — those skip the ethical/history re-check entirely.")
    print(f"Scanning with {MAX_WORKERS} concurrent workers — progress printed every 50 tickers.\n")

    results = []
    completed = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(analyze_ticker, ticker, cache): ticker for ticker in tickers}
        for future in as_completed(futures):
            completed += 1
            if completed % 50 == 0:
                print(f"  {completed}/{len(tickers)}...")
            result = future.result()
            if result is not None:
                results.append(result)

    _save_eligibility_cache(cache)
    print(f"Saved eligibility cache ({len(cache)} tickers known) to {ELIGIBILITY_CACHE_PATH.resolve()}")

    if not results:
        print("No results produced — check network access to Yahoo Finance and retry.")
        return

    df = pd.DataFrame(results)
    df.insert(0, "run_timestamp", pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"))

    # Two-tier sort, conditions before gain (per project decision 2026-07, same
    # philosophy as committee_signals.select_diversified_candidates): rank by
    # total_buy_votes first (agreement across independent methods, treated as
    # lower-risk), then by gain_speed_score as the tiebreaker ("highest likely
    # gain in the shortest time"). Rows with no score (target never hit in this
    # window) sort to the bottom rather than being silently dropped, so they're
    # still visible in the full saved file.
    df = df.sort_values(
        ["total_buy_votes", "gain_speed_score"], ascending=[False, False], na_position="last"
    )

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")

    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    archive_path = ARCHIVE_DIR / f"full_universe_results_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.csv"
    df.to_csv(archive_path, index=False, encoding="utf-8-sig")

    horizon_col = f"horizon_fit_{TARGET_GAIN_PCT}pct_{TARGET_HOLDING_DAYS}d"
    print(f"\nAnalyzed {len(df)}/{len(tickers)} tickers successfully.")
    print(f"\nTop 15 (ranked by total_buy_votes, then gain-per-day as tiebreaker — "
          f"{TARGET_GAIN_PCT}% target, {TARGET_HOLDING_DAYS}-day window):")
    top = df.head(15)  # already sorted above
    print(top[["ticker", "sector", "current_price", "entry_price", "exit_price",
               "total_buy_votes", "total_sell_votes",
               "gain_speed_score", horizon_col, "horizon_median_days_when_hit",
               "technical_net_vote", "quantitative_net_vote", "astrological_net_vote",
               "advanced_technical_net_vote", "best_square9_angle",
               "best_square9_hit_rate"]].to_string(index=False))

    print(f"\nSaved full results to: {OUTPUT_CSV.resolve()} "
          f"(sorted by total_buy_votes, then gain_speed_score, highest first)")
    print(f"Archived this run to: {archive_path.resolve()}")

    # Diversified shortlist (same logic as committee_signals.py): net-buy lean,
    # capped per sector, top TOP_N_CANDIDATES — useful now that the universe is
    # much bigger than the old 217-stock list, where sector concentration is a
    # real risk.
    diversified = select_diversified_candidates(results)
    if not diversified.empty:
        print(f"\n=== DIVERSIFIED SHORTLIST ({len(diversified)} candidates, "
              f"1 per sector, for manual review only) ===")
        print(diversified[["ticker", "sector", "current_price", "total_buy_votes", "total_sell_votes",
                            "gain_speed_score", "technical_net_vote", "quantitative_net_vote",
                            "astrological_net_vote", "advanced_technical_net_vote"]].to_string(index=False))
        print("\nREMINDER: this is a candidate SHORTLIST for your own research, not an order. "
              "Review preflight-checklist.md before acting on any of these.")

        committee_df = diversified.copy()
        committee_df.insert(0, "run_timestamp", df["run_timestamp"].iloc[0])
        committee_df.to_csv(COMMITTEE_CANDIDATES_CSV, index=False, encoding="utf-8-sig")
        committee_archive_path = ARCHIVE_DIR / f"committee_candidates_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.csv"
        committee_df.to_csv(committee_archive_path, index=False, encoding="utf-8-sig")
        print(f"\nSaved diversified shortlist to: {COMMITTEE_CANDIDATES_CSV.resolve()} (feeds format_report.py)")
        print(f"Archived this run to: {committee_archive_path.resolve()}")


if __name__ == "__main__":
    main()
