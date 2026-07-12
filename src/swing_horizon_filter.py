"""
swing_horizon_filter.py — Configurable swing-trading fit filter (holding period +
target gain both selectable), per Abdo's spec (2026-07): holding period in
TRADING days (1/3/5/10/15/20), target gain in percent (3/10/15/20/30+).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

HOLDING_PERIOD_CHOICES: tuple[int, ...] = (1, 3, 5, 10, 15, 20)
TARGET_GAIN_CHOICES: tuple[float, ...] = (3.0, 10.0, 15.0, 20.0, 30.0)  # "30% or more" -> 30.0 as floor


@dataclass
class HorizonFitResult:
    target_gain_pct: float
    max_holding_days: int
    total_entry_points_tested: int
    hit_within_window: int
    hit_rate: float
    median_days_to_hit: float | None
    days_to_hit_distribution: list[int]


def evaluate_horizon_fit(close: pd.Series, target_gain_pct: float = 20.0,
                          max_holding_days: int = 15) -> HorizonFitResult:
    """
    Scans the ENTIRE price history. For each possible entry day (a TRADING day
    index, since OHLCV data is naturally indexed by trading days only), checks
    whether/when the target gain was reached within max_holding_days TRADING
    days forward.
    """
    if target_gain_pct not in TARGET_GAIN_CHOICES:
        raise ValueError(f"target_gain_pct must be one of {TARGET_GAIN_CHOICES}, got {target_gain_pct}")
    if max_holding_days not in HOLDING_PERIOD_CHOICES:
        raise ValueError(f"max_holding_days must be one of {HOLDING_PERIOD_CHOICES}, got {max_holding_days}")

    closes = close.values
    n = len(closes)
    days_to_hit: list[int] = []
    tested = 0

    for i in range(n - 1):
        entry_price = closes[i]
        if entry_price <= 0:
            continue
        tested += 1
        window_end = min(i + max_holding_days, n - 1)
        target_price = entry_price * (1 + target_gain_pct / 100)

        hit_day = None
        for j in range(i + 1, window_end + 1):
            if closes[j] >= target_price:
                hit_day = j - i
                break
        if hit_day is not None:
            days_to_hit.append(hit_day)

    hit_rate = len(days_to_hit) / tested if tested > 0 else 0.0
    median_days = float(np.median(days_to_hit)) if days_to_hit else None

    return HorizonFitResult(
        target_gain_pct=target_gain_pct,
        max_holding_days=max_holding_days,
        total_entry_points_tested=tested,
        hit_within_window=len(days_to_hit),
        hit_rate=round(hit_rate, 3),
        median_days_to_hit=median_days,
        days_to_hit_distribution=days_to_hit,
    )


def evaluate_all_combinations(close: pd.Series,
                               target_gains: tuple[float, ...] = TARGET_GAIN_CHOICES,
                               holding_periods: tuple[int, ...] = HOLDING_PERIOD_CHOICES) -> pd.DataFrame:
    """
    Runs evaluate_horizon_fit() across every (target_gain, holding_period)
    combination and returns a summary grid — lets Abdo see at a glance which
    holding period is realistically needed for a given target on a given stock.
    """
    rows = []
    for gain in target_gains:
        for days in holding_periods:
            result = evaluate_horizon_fit(close, gain, days)
            rows.append({
                "target_gain_pct": gain,
                "max_holding_days": days,
                "hit_rate": result.hit_rate,
                "median_days_to_hit": result.median_days_to_hit,
                "hit_within_window": result.hit_within_window,
                "total_tested": result.total_entry_points_tested,
            })
    return pd.DataFrame(rows)


def summarize_fit_for_swing_trader(close: pd.Series, target_gain_pct: float = 20.0,
                                    max_holding_days: int = 15) -> str:
    result = evaluate_horizon_fit(close, target_gain_pct, max_holding_days)
    if result.hit_within_window == 0:
        return (f"Never reached +{target_gain_pct}% within {max_holding_days} trading days "
                f"in {result.total_entry_points_tested} historical entry points tested. "
                f"POOR FIT for this holding window.")
    return (f"Reached +{target_gain_pct}% within {max_holding_days} trading days "
            f"{result.hit_rate:.1%} of the time historically "
            f"(median {result.median_days_to_hit:.0f} days when it happened, "
            f"{result.hit_within_window}/{result.total_entry_points_tested} entry points).")


@dataclass
class ForwardOutcomeResult:
    status: str  # "hit" | "missed" | "still_pending"
    days_to_exit: int | None
    entry_touched: bool


def evaluate_forward_outcome(future_close: pd.Series, entry_price: float, exit_price: float,
                              max_holding_days: int, net_buy: bool) -> ForwardOutcomeResult:
    """
    The mirror-image question to evaluate_horizon_fit's "does this ticker
    tend to reach its target" — given what ACTUALLY happened after a
    recommendation date (future_close, the close-price series starting the
    bar AFTER the recommendation), did it? Shared by src/track_outcomes.py
    (live daily recommendations) and src/backtest.py (simulated historical
    ones) so both score outcomes identically (2026-07).

    net_buy=True means entry_price was just today's close at recommendation
    time (see compute_entry_exit_levels) — entry is trivially "touched" on
    day zero, so entry_touched isn't a meaningful signal in that case; only
    whether exit_price was reached within max_holding_days matters. For a
    net_buy=False row (needed a pullback to entry_price first), entry_touched
    tracks whether that pullback ever actually happened.

    "still_pending": fewer than max_holding_days bars are available yet in
    future_close — the window hasn't fully elapsed, so "missed" can't be
    concluded yet (this is the live-tracking case; a backtest run far enough
    in the past should never see this).
    """
    closes = future_close.values
    entry_touched = True if net_buy else False
    days_to_exit = None

    window = min(len(closes), max_holding_days)
    for i in range(window):
        if not net_buy and not entry_touched and closes[i] <= entry_price:
            entry_touched = True
        if (net_buy or entry_touched) and closes[i] >= exit_price:
            days_to_exit = i + 1
            break

    if days_to_exit is not None:
        return ForwardOutcomeResult("hit", days_to_exit, entry_touched)
    if len(closes) < max_holding_days:
        return ForwardOutcomeResult("still_pending", None, entry_touched)
    return ForwardOutcomeResult("missed", None, entry_touched)
