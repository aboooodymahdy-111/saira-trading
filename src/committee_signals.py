"""
committee_signals.py — Shared committee-voting library (Technical / Quantitative /
Astrological / Advanced Technical groups) used by full_universe_analysis.py.

PURPOSE:
    Each group asks "as of TODAY, is this stock showing a Buy signal?" using methods
    that are GENUINELY INDEPENDENT of Timing Solution (TS) — no TS dates, no TS
    context, no TS gate of any kind.

    HISTORY (2026-07): this file used to also have its own standalone CLI runner
    (main()/evaluate_ticker()) that built its ticker universe from TS's extracted
    signals (runs/signals_extracted.csv) and showed a TS-proximity column
    (ts_context) as supporting context. TS WAS REMOVED FROM THE PROJECT ENTIRELY
    (2026-07 decision — historical TS signal accuracy measured ~19.7%, judged not
    worth the network/time cost; see deprecated_ts/ for the removed TS pipeline
    scripts). That standalone runner is gone along with it — it evaluated a smaller,
    TS-derived universe AND never applied ethical_screen.py, making it strictly
    inferior to full_universe_analysis.py, which now covers the full NASDAQ+NYSE
    universe with the ethical filter applied. This file is now purely a shared
    library: full_universe_analysis.py imports evaluate_technical_group,
    evaluate_quantitative_group, get_astrological_votes, and
    select_diversified_candidates from here. Run full_universe_analysis.py directly,
    not this file.

GROUP STRUCTURE (see select_diversified_candidates() for how they combine):
    - TECHNICAL group (4 members, each casts buy/sell/neutral):
        MACD crossover, Golden/Death Cross, Bollinger Bands, ADX-gated trend direction
    - QUANTITATIVE group (2 members):
        Analyst consensus, unusual volume
    - ASTROLOGICAL group (1 member, ACTIVATED 2026-07):
        Gann Square of Nine vote, calibrated per-ticker against that ticker's own
        historical pivots (gann_decision_system.gann_committee_vote — Mikula's
        documented overlay/calibration method), NOT the earlier fixed-offset
        approximation. Carries proportionally less weight than the other groups
        (1 vote vs 4/2) since it's currently the only astrological method
        implemented. Gann angles (1x1/2x1/etc.) and planetary lines remain
        unimplemented — no agreed objective rule yet, per project conversation
        2026-07.
    - ADVANCED TECHNICAL group (up to 4 sub-votes, ACTIVATED 2026-07):
        advanced_technical_tools.evaluate_advanced_technical_group() — TA-Lib's
        indicator set (RSI/MACD/BBANDS/ADX/Aroon/Stochastic/MFI/SAR combined
        into one sub-vote), Ichimoku Cloud, Pivot Points, and Volume Profile.
        Requires TA-Lib to be installed (`pip install ta-lib`) for its first
        sub-vote; the other three (Ichimoku, Pivot Points, Volume Profile) work
        without it. Reported as its own group (not merged into the existing
        TECHNICAL group above) so its contribution stays visible/auditable
        separately, same reasoning as keeping ASTROLOGICAL separate.

DIVERSIFICATION: candidates are capped at MAX_CANDIDATES_PER_SECTOR per GICS-like
    sector (fetched from yfinance ticker.info) so the final shortlist isn't
    accidentally concentrated in one industry.

OUTPUT: runs/committee_candidates.csv — written by full_universe_analysis.py's
    diversified-shortlist step, using select_diversified_candidates() below.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

from advanced_technical_tools import evaluate_advanced_technical_group
from swing_horizon_filter import evaluate_horizon_fit
from yf_retry import call_with_retry

# Per project decision (2026-07): keep every run, not just the latest — every
# script in this project that writes a "latest" output also archives a
# timestamped copy alongside it, so past runs stay available as potential
# future training/comparison data.
ARCHIVE_DIR = Path("runs/archive")

BOLLINGER_WINDOW = 20
BOLLINGER_STD = 2
ADX_WINDOW = 14
ADX_TREND_THRESHOLD = 25  # ADX below this = "no real trend", vote is discarded regardless of direction

TOP_N_CANDIDATES = 3
MAX_CANDIDATES_PER_SECTOR = 1  # enforce diversification across sectors, per project goal


@dataclass
class GroupResult:
    """One group's combined vote for one ticker."""
    votes_buy: int = 0
    votes_sell: int = 0
    votes_neutral: int = 0
    votes_unavailable: int = 0
    details: dict = field(default_factory=dict)

    @property
    def net_vote(self) -> str:
        if self.votes_buy > self.votes_sell and self.votes_buy > 0:
            return "buy"
        if self.votes_sell > self.votes_buy and self.votes_sell > 0:
            return "sell"
        return "neutral"


# ---------------------------------------------------------------------------
# TECHNICAL GROUP
# ---------------------------------------------------------------------------

def compute_bollinger_vote(close: pd.Series) -> str:
    """Price closing outside the bands signals strong momentum in that direction."""
    if len(close) < BOLLINGER_WINDOW:
        return "unavailable"
    ma = close.rolling(BOLLINGER_WINDOW).mean()
    std = close.rolling(BOLLINGER_WINDOW).std()
    upper = ma + BOLLINGER_STD * std
    lower = ma - BOLLINGER_STD * std

    last_close, last_upper, last_lower = close.iloc[-1], upper.iloc[-1], lower.iloc[-1]
    if pd.isna(last_upper) or pd.isna(last_lower):
        return "unavailable"
    if last_close > last_upper:
        return "buy"
    if last_close < last_lower:
        return "sell"
    return "neutral"


def compute_adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = ADX_WINDOW):
    """
    Standard Wilder ADX. Measures trend STRENGTH, not direction — used here as a
    gate: a directional signal from other indicators is only trusted if ADX confirms
    a real trend is underway (>= ADX_TREND_THRESHOLD), filtering out choppy/sideways
    markets where crossovers are more likely to be noise.
    """
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)

    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    atr = tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    plus_di = 100 * pd.Series(plus_dm, index=high.index).ewm(alpha=1 / period, min_periods=period, adjust=False).mean() / atr
    minus_di = 100 * pd.Series(minus_dm, index=high.index).ewm(alpha=1 / period, min_periods=period, adjust=False).mean() / atr

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    adx = dx.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    return adx, plus_di, minus_di


def compute_adx_vote(high: pd.Series, low: pd.Series, close: pd.Series) -> str:
    if len(close) < ADX_WINDOW * 2:
        return "unavailable"
    adx, plus_di, minus_di = compute_adx(high, low, close)
    last_adx, last_plus, last_minus = adx.iloc[-1], plus_di.iloc[-1], minus_di.iloc[-1]
    if pd.isna(last_adx):
        return "unavailable"
    if last_adx < ADX_TREND_THRESHOLD:
        return "neutral"  # trend too weak to trust direction
    return "buy" if last_plus > last_minus else "sell"


def compute_macd_vote(close: pd.Series) -> str:
    ema_fast = close.ewm(span=12, adjust=False).mean()
    ema_slow = close.ewm(span=26, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    histogram = macd_line - signal_line
    if len(histogram.dropna()) < 2:
        return "unavailable"
    prev, cur = histogram.iloc[-2], histogram.iloc[-1]
    if prev <= 0 < cur:
        return "buy"
    if prev >= 0 > cur:
        return "sell"
    return "neutral"


def compute_ma_cross_vote(close: pd.Series) -> str:
    if len(close) < 200:
        return "unavailable"
    ma50, ma200 = close.rolling(50).mean(), close.rolling(200).mean()
    diff = (ma50 - ma200).dropna()
    if len(diff) < 2:
        return "unavailable"
    prev, cur = diff.iloc[-2], diff.iloc[-1]
    if prev <= 0 < cur:
        return "buy"
    if prev >= 0 > cur:
        return "sell"
    return "neutral"


def evaluate_technical_group(hist: pd.DataFrame) -> GroupResult:
    result = GroupResult()
    votes = {
        "macd": compute_macd_vote(hist["Close"]),
        "golden_death_cross": compute_ma_cross_vote(hist["Close"]),
        "bollinger": compute_bollinger_vote(hist["Close"]),
        "adx_trend": compute_adx_vote(hist["High"], hist["Low"], hist["Close"]),
    }
    for name, vote in votes.items():
        result.details[name] = vote
        if vote == "buy":
            result.votes_buy += 1
        elif vote == "sell":
            result.votes_sell += 1
        elif vote == "neutral":
            result.votes_neutral += 1
        else:
            result.votes_unavailable += 1
    return result


# ---------------------------------------------------------------------------
# QUANTITATIVE GROUP
# ---------------------------------------------------------------------------

def compute_volume_vote(volume: pd.Series, lookback: int = 20, spike_threshold: float = 1.5) -> str:
    if len(volume) < lookback:
        return "unavailable"
    avg = volume.rolling(lookback).mean().iloc[-1]
    last = volume.iloc[-1]
    if pd.isna(avg) or avg == 0:
        return "unavailable"
    ratio = last / avg
    # Volume alone doesn't tell direction — only "something is happening".
    # We treat a spike as a (weak) buy-side vote per common retail-trading heuristic
    # that unusual volume more often accompanies upside breakouts than breakdowns in
    # this dataset's universe — an ASSUMPTION worth revisiting with real data later,
    # not an established fact.
    return "buy" if ratio >= spike_threshold else "neutral"


def compute_analyst_vote(ticker: str) -> str:
    try:
        rec = call_with_retry(lambda: yf.Ticker(ticker).recommendations)
        if rec is None or rec.empty:
            return "unavailable"
        latest = rec.iloc[0]
        buy = latest.get("strongBuy", 0) + latest.get("buy", 0)
        sell = latest.get("strongSell", 0) + latest.get("sell", 0)
        hold = latest.get("hold", 0)
        total = buy + sell + hold
        if total == 0:
            return "unavailable"
        if buy / total > 0.5:
            return "buy"
        if sell / total > 0.5:
            return "sell"
        return "neutral"
    except Exception as exc:  # noqa: BLE001
        print(f"WARNING: analyst consensus unavailable for {ticker}: {exc}")
        return "unavailable"


def evaluate_quantitative_group(ticker: str, hist: pd.DataFrame, include_analyst_consensus: bool = True) -> GroupResult:
    """
    include_analyst_consensus=False (2026-07, for src/backtest.py only): skips
    compute_analyst_vote entirely rather than counting it as "unavailable" —
    yfinance's analyst consensus is a CURRENT-only snapshot with no historical
    point-in-time equivalent, so it can't be reconstructed for a past as-of
    date and would otherwise silently look like a live-matching signal it
    isn't. Live callers never pass this, so default True keeps them unchanged.
    """
    result = GroupResult()
    votes = {}
    if include_analyst_consensus:
        votes["analyst_consensus"] = compute_analyst_vote(ticker)
    else:
        votes["analyst_consensus"] = "skipped_for_backtest"
    votes["volume_spike"] = compute_volume_vote(hist["Volume"])
    for name, vote in votes.items():
        result.details[name] = vote
        if vote == "buy":
            result.votes_buy += 1
        elif vote == "sell":
            result.votes_sell += 1
        elif vote == "neutral":
            result.votes_neutral += 1
        else:
            result.votes_unavailable += 1
    return result


# ---------------------------------------------------------------------------
# ASTROLOGICAL GROUP
# ---------------------------------------------------------------------------

def get_astrological_votes(ticker: str, hist: pd.DataFrame) -> GroupResult | None:
    """
    ACTIVATED 2026-07, CORRECTED 2026-07 (merged from committee_signals_updated.py):
    uses gann_decision_system.gann_committee_vote(), which CALIBRATES the Square
    of Nine angle per ticker against that ticker's own historical pivots (Mikula's
    documented method — see gann_decision_system.py module docstring), NOT
    gann_square9.compute_square9_vote(), which uses a fixed sqrt+offset
    approximation with no per-ticker calibration. An earlier version of this
    project (committee_signals_updated.py) wired up the approximate tool by
    mistake; this is the corrected version, using the precise/calibrated stack
    (gann_square9_precise.py + gann_decision_system.py) that the rest of the
    project's Layer 1/2/3/4 tools were built and verified against.

    Gann angles (1x1/2x1/etc.) and planetary lines remain unimplemented here —
    they either require a human-verified anchor point or lack an agreed
    objective rule, per project conversation 2026-07. This function returns a
    GroupResult with exactly one vote (not a full 3-4 member group like
    Technical/Quantitative), so it carries proportionally less weight in
    total_buy_votes/total_sell_votes until more astrological methods are added.

    Returns None (not a GroupResult) if there isn't enough price history to
    calibrate at all — same "insufficient data -> explicit unavailable, not a
    guessed vote" principle used elsewhere in this project.
    """
    from gann_decision_system import gann_committee_vote
    from gann_increment_selection import recommended_price_increment

    increment_info = recommended_price_increment(hist["High"], hist["Low"], hist["Close"])
    price_increment = increment_info["recommended_increment"]

    vote_result = gann_committee_vote(
        ticker_high=hist["High"], ticker_low=hist["Low"], ticker_close=hist["Close"],
        price_increment=price_increment, as_of_date=pd.Timestamp.today().date(),
    )

    if vote_result.vote == "unavailable":
        return None

    result = GroupResult()
    result.details["square9_calibrated_vote"] = vote_result.vote
    result.details["square9_angle"] = vote_result.best_square9_angle
    result.details["square9_hit_rate"] = vote_result.best_square9_hit_rate
    result.details["square9_projected_price_level"] = vote_result.projected_price_level
    result.details["price_increment_used"] = price_increment
    result.details["upcoming_time_cycle_dates"] = vote_result.upcoming_time_cycle_dates
    result.details["upcoming_astro_events"] = vote_result.upcoming_astro_events
    result.details["notes"] = vote_result.notes

    if vote_result.vote == "buy":
        result.votes_buy += 1
    elif vote_result.vote == "sell":
        result.votes_sell += 1
    elif vote_result.vote == "neutral":
        result.votes_neutral += 1
    else:
        result.votes_unavailable += 1
    return result


# ---------------------------------------------------------------------------
# COMMITTEE COMBINATION + CANDIDATE SELECTION
# ---------------------------------------------------------------------------

def select_diversified_candidates(evaluations: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(evaluations)
    if df.empty:
        return df

    # Candidacy requires a clear net BUY lean across all automated groups combined
    # (more buy votes than sell votes overall). Per project decision 2026-07, the
    # earlier minimum-vote-count floor (total_buy_votes >= 3) is removed entirely —
    # any net-buy ticker is eligible; ranking below is what surfaces the strongest.
    #
    # Ranking is two-tier, conditions before gain (per project decision 2026-07, to
    # favor lower risk over speed): (1) total_buy_votes descending — more independent
    # methods agreeing is treated as lower-risk than any single method's conviction;
    # (2) gain_speed_score descending as the tiebreaker — among equally-confirmed
    # candidates, prefer the one whose price history reached a strong gain fastest
    # (see evaluate_ticker's swing_horizon_filter wiring).
    candidates = df[df["total_buy_votes"] > df["total_sell_votes"]].copy()
    candidates = candidates.sort_values(
        ["total_buy_votes", "gain_speed_score"], ascending=[False, False]
    )

    diversified = []
    sector_counts: dict[str, int] = {}
    for _, row in candidates.iterrows():
        sector = row["sector"]
        if sector_counts.get(sector, 0) >= MAX_CANDIDATES_PER_SECTOR:
            continue
        diversified.append(row)
        sector_counts[sector] = sector_counts.get(sector, 0) + 1
        if len(diversified) >= TOP_N_CANDIDATES:
            break

    return pd.DataFrame(diversified)


if __name__ == "__main__":
    raise SystemExit(
        "committee_signals.py has no standalone runner anymore (removed 2026-07 along with "
        "TS) — it's now a shared library imported by full_universe_analysis.py, which covers "
        "the full NASDAQ+NYSE universe with the ethical filter applied. Run:\n"
        "    python src/full_universe_analysis.py"
    )
