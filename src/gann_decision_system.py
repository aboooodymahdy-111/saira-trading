"""
gann_decision_system.py — Layer 4: Decision-making system that calibrates Layers
1-3's tools PER STOCK, rather than assuming one angle/cycle fits every market.

WHY CALIBRATION, NOT A FIXED RULE:
    Mikula's book states this explicitly and repeatedly (e.g. Chapter 6, MRK
    example): "compare the prices on the diagonal cross and cardinal cross to
    the pivot prices over the recent past. The angle with the best correlation
    to the pivot prices over the recent past is usually the best forecaster of
    the near future." This is not a one-time observation — nearly every worked
    example in the book repeats this same instruction: test several angles
    against a market's own pivot history, and use whichever one actually
    correlates for THAT market, not a fixed favorite.

    This directly parallels this project's committee_signals.py philosophy
    ("test then trust", per the project's coding standards) — Layer 4 applies
    that same discipline specifically to Gann's price/time/astrology tools.

WHAT THIS MODULE DOES:
    1. calibrate_square9_angle(): given a stock's price history, tests each of
       the 8 cardinal/diagonal Square of Nine overlay angles against the
       stock's own recent pivots, and returns which angle(s) actually
       correlated — verified with synthetic data engineered to favor one
       specific angle (see test run in project history, 2026-07).
    2. calibrate_gann_trendline_angle(): same idea for the classic 1x1/2x1/etc
       trendline angles (gann_layer1_tools.STANDARD_GANN_ANGLES) — which slope
       has the price actually been respecting as support/resistance.
    3. gann_committee_vote(): combines the calibrated angle's current signal,
       upcoming Layer 2 time-cycle forecast dates, and upcoming Layer 3
       astrological events into one vote, in the same buy/sell/neutral format
       used by committee_signals.py's other groups — designed to be dropped
       into get_astrological_votes() there, replacing the single, uncalibrated
       square9_proximity vote it currently uses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import pandas as pd

from gann_square9_precise import cell_price, nearest_cell_to_price
from gann_layer1_tools import STANDARD_GANN_ANGLES, gann_angle_price
from gann_time_cycles import forecast_dates_at_angle
from gann_astrology import find_upcoming_events

PIVOT_LEFT_BARS = 3
PIVOT_RIGHT_BARS = 3
CALIBRATION_LOOKBACK_BARS = 120     # how much price history to use for calibration
PROXIMITY_TOLERANCE_PCT = 0.02       # price within 2% of a projected level counts as "touched" it
CANDIDATE_ANGLES = (0, 45, 90, 135, 180, 225, 270, 315)


@dataclass(frozen=True)
class AngleCalibrationResult:
    angle: float
    hits: int              # how many historical pivots landed near this angle's projected levels
    total_pivots_tested: int

    @property
    def hit_rate(self) -> float:
        return self.hits / self.total_pivots_tested if self.total_pivots_tested else 0.0


def _detect_pivots(high: pd.Series, low: pd.Series) -> list[tuple[int, float, str]]:
    """Reuses the same swing-high/low logic as gann_square9.py, kept local to
    avoid a heavier cross-module dependency for this one helper."""
    pivots = []
    n = len(high)
    for i in range(PIVOT_LEFT_BARS, n - PIVOT_RIGHT_BARS):
        window_high = high.iloc[i - PIVOT_LEFT_BARS: i + PIVOT_RIGHT_BARS + 1]
        window_low = low.iloc[i - PIVOT_LEFT_BARS: i + PIVOT_RIGHT_BARS + 1]
        h, l = high.iloc[i], low.iloc[i]
        if h == window_high.max() and (window_high == h).sum() == 1:
            pivots.append((i, float(h), "high"))
        if l == window_low.min() and (window_low == l).sum() == 1:
            pivots.append((i, float(l), "low"))
    return sorted(pivots, key=lambda p: p[0])


def calibrate_square9_angle(high: pd.Series, low: pd.Series, close: pd.Series,
                             price_increment: float) -> list[AngleCalibrationResult]:
    """
    For each candidate cardinal/diagonal angle, and for each historical pivot
    LOW in the lookback window, projects that angle's Square of Nine level
    (using the pivot as the overlay anchor, same cell-based method as
    gann_square9_precise) and checks whether a LATER pivot HIGH landed within
    PROXIMITY_TOLERANCE_PCT of that projected level. Returns one
    AngleCalibrationResult per angle, sorted by hit_rate descending — the
    top result is the angle Mikula's method says to trust for this stock.
    """
    recent_high = high.tail(CALIBRATION_LOOKBACK_BARS).reset_index(drop=True)
    recent_low = low.tail(CALIBRATION_LOOKBACK_BARS).reset_index(drop=True)
    pivots = _detect_pivots(recent_high, recent_low)

    pivot_lows = [p for p in pivots if p[2] == "low"]
    pivot_highs = [p for p in pivots if p[2] == "high"]

    results = []
    for angle in CANDIDATE_ANGLES:
        hits = 0
        tested = 0
        for idx, pivot_price, _ in pivot_lows:
            later_highs = [ph for pi, ph, _ in pivot_highs if pi > idx]
            if not later_highs:
                continue
            tested += 1
            pivot_cell = nearest_cell_to_price(pivot_price, price_increment, 0.0)
            # project the angle as a fraction of a rotation from the pivot cell
            from gann_square9_precise import move_around_square
            moved_cell = round(move_around_square(pivot_cell, angle / 360.0))
            if moved_cell < 1:
                continue
            projected_price = cell_price(moved_cell, price_increment, 0.0)

            if any(abs(h - projected_price) / projected_price <= PROXIMITY_TOLERANCE_PCT
                   for h in later_highs):
                hits += 1

        if tested > 0:
            results.append(AngleCalibrationResult(angle=angle, hits=hits, total_pivots_tested=tested))

    return sorted(results, key=lambda r: r.hit_rate, reverse=True)


@dataclass(frozen=True)
class TrendlineCalibrationResult:
    angle_name: str
    hits: int
    total_bars_tested: int

    @property
    def hit_rate(self) -> float:
        return self.hits / self.total_bars_tested if self.total_bars_tested else 0.0


def calibrate_gann_trendline_angle(close: pd.Series, anchor_index: int, anchor_price: float,
                                    direction: int = 1, touch_tolerance_pct: float = 0.01) -> list[TrendlineCalibrationResult]:
    """
    Tests each standard Gann angle (1x1, 2x1, 1x2, etc.) as a trendline drawn
    from (anchor_index, anchor_price). Scores each angle by counting genuine
    TOUCHES — bars where price comes within touch_tolerance_pct of the
    projected line — while disqualifying (hit_rate forced to 0) any angle the
    price decisively BREACHES (closes beyond it by more than
    PROXIMITY_TOLERANCE_PCT on the wrong side).

    BUG FOUND AND FIXED (2026-07): an earlier version scored "hits" as simply
    "price stayed on the correct side of the line", which is trivially 100% for
    any angle SLOWER than the market's actual trend (a slow-rising support line
    is nearly impossible to breach if price is climbing faster than it) — this
    made the calibration always favor the shallowest angles regardless of
    whether the market actually respected them. Confirmed via a synthetic test:
    a price series built to follow an exact 1x1 slope scored 1x8, 1x4, 1x3, 1x2
    ALL at a trivial 100% hit rate under the old logic, with 1x1 itself not even
    the top result — a clear sign the metric measured "how slow is this angle"
    rather than "does the market respect this angle". The touch-based criterion
    below was re-verified against the same synthetic 1x1 series and correctly
    ranks 1x1 first.
    """
    results = []
    for name, angle in STANDARD_GANN_ANGLES.items():
        touches = 0
        tested = 0
        breached = False
        for t in range(anchor_index + 1, len(close)):
            projected = angle.price_at(anchor_price, anchor_index, t, direction)
            actual = close.iloc[t]
            tested += 1

            if direction == 1 and actual < projected * (1 - PROXIMITY_TOLERANCE_PCT):
                breached = True
            elif direction == -1 and actual > projected * (1 + PROXIMITY_TOLERANCE_PCT):
                breached = True

            if projected != 0 and abs(actual - projected) / projected <= touch_tolerance_pct:
                touches += 1

        if tested > 0:
            effective_hits = 0 if breached else touches
            results.append(TrendlineCalibrationResult(angle_name=name, hits=effective_hits, total_bars_tested=tested))
    return sorted(results, key=lambda r: r.hit_rate, reverse=True)


@dataclass
class GannCommitteeVote:
    vote: str  # "buy" / "sell" / "neutral" / "unavailable"
    best_square9_angle: float | None
    best_square9_hit_rate: float | None
    upcoming_time_cycle_dates: list[date] = field(default_factory=list)
    upcoming_astro_events: list[str] = field(default_factory=list)
    notes: str = ""
    # Price the calibrated angle currently projects from the latest pivot low —
    # same level the vote itself is judged against (see PROXIMITY_TOLERANCE_PCT
    # check below). Exposed so callers (e.g. entry/exit pricing) can reuse the
    # calibrated Square of Nine level without recomputing it. None if there was
    # no pivot low to project from.
    projected_price_level: float | None = None


def gann_committee_vote(ticker_high: pd.Series, ticker_low: pd.Series, ticker_close: pd.Series,
                         price_increment: float, as_of_date: date,
                         planets: tuple[str, ...] = ("mercury", "venus", "mars")) -> GannCommitteeVote:
    """
    Combines calibrated Layer 1 (Square of Nine angle), Layer 2 (time cycle
    forecast dates), and Layer 3 (upcoming astrological events) into a single
    vote, in the committee_signals.py format. This is meant to be substituted
    into that file's get_astrological_votes() in place of the single
    uncalibrated square9_proximity check it currently performs.

    Minimum-data guard: needs at least CALIBRATION_LOOKBACK_BARS + pivot window
    of price history, or returns "unavailable" rather than a low-confidence guess.
    """
    if len(ticker_close) < CALIBRATION_LOOKBACK_BARS:
        return GannCommitteeVote("unavailable", None, None, notes="insufficient price history for calibration")

    calibration = calibrate_square9_angle(ticker_high, ticker_low, ticker_close, price_increment)
    if not calibration or calibration[0].hit_rate == 0:
        return GannCommitteeVote("neutral", None, None, notes="no angle showed historical correlation")

    best = calibration[0]
    current_price = float(ticker_close.iloc[-1])
    pivot_lows = [p for p in _detect_pivots(ticker_high.tail(CALIBRATION_LOOKBACK_BARS).reset_index(drop=True),
                                             ticker_low.tail(CALIBRATION_LOOKBACK_BARS).reset_index(drop=True))
                  if p[2] == "low"]

    vote = "neutral"
    projected_level = None
    if pivot_lows:
        from gann_square9_precise import move_around_square
        last_pivot_price = pivot_lows[-1][1]
        pivot_cell = nearest_cell_to_price(last_pivot_price, price_increment, 0.0)
        moved_cell = round(move_around_square(pivot_cell, best.angle / 360.0))
        projected_level = cell_price(moved_cell, price_increment, 0.0) if moved_cell >= 1 else None
        if projected_level and abs(current_price - projected_level) / projected_level <= PROXIMITY_TOLERANCE_PCT:
            vote = "buy" if current_price >= last_pivot_price else "sell"

    time_forecasts = forecast_dates_at_angle(as_of_date, best.angle, max_cell=200)
    upcoming_dates = [f.calendar_date for f in time_forecasts if as_of_date <= f.calendar_date <= as_of_date + timedelta(days=30)]

    astro_events = find_upcoming_events(list(planets), as_of_date, as_of_date + timedelta(days=14))
    astro_summaries = [f"{e.planet} {e.event_type} on {e.event_date}" for e in astro_events]

    return GannCommitteeVote(
        vote=vote,
        best_square9_angle=best.angle,
        best_square9_hit_rate=round(best.hit_rate, 2),
        upcoming_time_cycle_dates=upcoming_dates,
        upcoming_astro_events=astro_summaries,
        notes=f"calibrated on {best.total_pivots_tested} historical pivots",
        projected_price_level=round(projected_level, 2) if projected_level else None,
    )
