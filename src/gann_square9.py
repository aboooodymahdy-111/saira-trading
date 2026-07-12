"""
gann_square9.py — Objective, deterministic Gann Square of Nine analysis.

PROVENANCE:
    - square_of_nine(): taken directly from GannAnalyzer_v1.0/modules/gann_core.py
      (Abdo's own prior work, uploaded 2026-07-11). Unmodified logic.
    - Pivot detection: reconstructed from Abdo's ChatGPT session "منهج جان والتحليل"
      (Commit 2.2.1 — Pivot Detection Engine), which described a standard swing-high/
      swing-low algorithm. Rewritten here in idiomatic pandas rather than the original
      dataclass-based version, and unit-tested (see tests at the bottom of this file's
      companion test run in project history).

WHY THIS IS THE "ASTROLOGICAL" GROUP, NOT MYSTICISM:
    Square of Nine is a genuinely deterministic price transformation (square root,
    offset, re-square) — given the same anchor price, it always produces the same
    levels. That's what makes it usable as an automated vote, unlike Gann fans or
    price=time visual analysis, which still require human interpretation and are
    NOT implemented here (see committee_signals.py's reserved-slot docstring for why).

VOTING RULE (new, decided here — not from the original chat, which never actually
    wired square_of_nine() into a scoring decision):
    1. Find the most recent significant pivot LOW and pivot HIGH in the last
       PIVOT_LOOKBACK_BARS bars.
    2. Compute Square of Nine levels anchored to each.
    3. If the CURRENT price is within PROXIMITY_PCT of a level computed from the
       pivot LOW -> that's a potential support level holding -> "buy" vote.
       If within PROXIMITY_PCT of a level from the pivot HIGH -> potential
       resistance -> "sell" vote.
    4. If price isn't near any computed level -> "neutral".
    This is ONE reasonable interpretation of how to use Square of Nine as a
    directional signal, not a claim that it's the historically "correct" one —
    Abdo should sanity-check this rule against his own Gann study before trusting
    it heavily.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

import pandas as pd

PIVOT_LEFT_BARS = 3     # bars on each side that must be lower/higher for a pivot to count
PIVOT_RIGHT_BARS = 3
PIVOT_LOOKBACK_BARS = 60  # how far back to look for the most recent significant pivot
PROXIMITY_PCT = 0.015     # price within 1.5% of a Square-of-9 level counts as "at" that level


class PivotType(Enum):
    HIGH = 1
    LOW = -1


@dataclass(frozen=True)
class Pivot:
    index: int
    price: float
    kind: PivotType


def square_of_nine(price: float) -> list[float]:
    """
    Unmodified from GannAnalyzer_v1.0/modules/gann_core.py (Abdo's prior work).
    Takes sqrt(price), applies a set of offsets, re-squares -> a small set of
    Gann-derived support/resistance price levels around the anchor price.
    """
    r = math.sqrt(price)
    return [round((r + x) ** 2, 2) for x in [-1, -.5, -.25, .25, .5, .75, 1]]


def detect_pivots(high: pd.Series, low: pd.Series,
                   left: int = PIVOT_LEFT_BARS, right: int = PIVOT_RIGHT_BARS) -> list[Pivot]:
    """
    Standard swing-high/swing-low detection: a bar is a pivot high if its high is
    strictly greater than every bar's high in the [left, right] window around it
    (and symmetrically for pivot lows). Reconstructed from the algorithm described
    in Abdo's ChatGPT session (Commit 2.2.1), rewritten for pandas Series input.
    """
    pivots: list[Pivot] = []
    n = len(high)
    for i in range(left, n - right):
        window_high = high.iloc[i - left: i + right + 1]
        window_low = low.iloc[i - left: i + right + 1]
        h, l = high.iloc[i], low.iloc[i]

        if h == window_high.max() and (window_high == h).sum() == 1:
            pivots.append(Pivot(index=i, price=float(h), kind=PivotType.HIGH))
        if l == window_low.min() and (window_low == l).sum() == 1:
            pivots.append(Pivot(index=i, price=float(l), kind=PivotType.LOW))

    return sorted(pivots, key=lambda p: p.index)


def most_recent_pivot(pivots: list[Pivot], kind: PivotType, before_index: int, lookback: int) -> Pivot | None:
    candidates = [
        p for p in pivots
        if p.kind == kind and before_index - lookback <= p.index < before_index
    ]
    return candidates[-1] if candidates else None


def compute_square9_vote(high: pd.Series, low: pd.Series, close: pd.Series) -> tuple[str, dict]:
    """
    Returns (vote, details) where vote is 'buy' / 'sell' / 'neutral' / 'unavailable'.
    details includes which pivot/level triggered the vote, for transparency in reports
    (Pillar 4 of the coding standards: readable output, not a black box).
    """
    if len(high) < PIVOT_LOOKBACK_BARS + PIVOT_LEFT_BARS + PIVOT_RIGHT_BARS:
        return "unavailable", {"reason": "insufficient_history"}

    pivots = detect_pivots(high, low)
    last_index = len(close) - 1
    current_price = float(close.iloc[-1])

    recent_low = most_recent_pivot(pivots, PivotType.LOW, last_index, PIVOT_LOOKBACK_BARS)
    recent_high = most_recent_pivot(pivots, PivotType.HIGH, last_index, PIVOT_LOOKBACK_BARS)

    if recent_low is None and recent_high is None:
        return "neutral", {"reason": "no_recent_pivot_found"}

    def nearest_level(levels: list[float], price: float) -> tuple[float, float] | None:
        closest = min(levels, key=lambda lvl: abs(lvl - price))
        distance_pct = abs(closest - price) / price
        return (closest, distance_pct) if distance_pct <= PROXIMITY_PCT else None

    support_hit = None
    if recent_low is not None:
        support_levels = square_of_nine(recent_low.price)
        support_hit = nearest_level(support_levels, current_price)

    resistance_hit = None
    if recent_high is not None:
        resistance_levels = square_of_nine(recent_high.price)
        resistance_hit = nearest_level(resistance_levels, current_price)

    details = {
        "recent_pivot_low": recent_low.price if recent_low else None,
        "recent_pivot_high": recent_high.price if recent_high else None,
        "current_price": current_price,
    }

    # If price is near BOTH a support and resistance level simultaneously (can happen
    # with a tight recent range), prefer the closer one rather than guessing.
    if support_hit and resistance_hit:
        if support_hit[1] <= resistance_hit[1]:
            details.update({"matched_level": support_hit[0], "distance_pct": support_hit[1]})
            return "buy", details
        details.update({"matched_level": resistance_hit[0], "distance_pct": resistance_hit[1]})
        return "sell", details

    if support_hit:
        details.update({"matched_level": support_hit[0], "distance_pct": support_hit[1]})
        return "buy", details
    if resistance_hit:
        details.update({"matched_level": resistance_hit[0], "distance_pct": resistance_hit[1]})
        return "sell", details

    return "neutral", details
