"""
gann_planetary_lines.py — Layer 3 extension: genuine PLANETARY LINES drawn across
the price/time chart (matching the concept in Abdo's own gann-astro-lines.html
tool), tested for touch/bounce behavior — distinct from the static price/longitude
"aspect" snapshot check already in gann_astrology.py.

CONCEPT (per Abdo's direct question, 2026-07): does price touch a planetary line
and respect it (bounce off it) as support/resistance? This is a genuinely
different technique from find_price_aspect() (a one-day snapshot comparison) —
here the line is drawn continuously across many days, following the planet's
REAL (non-linear, retrograde-affected) motion converted to a price scale, the
same way a Gann 1x1 angle is a continuous line but anchored to a planet's actual
movement instead of a fixed price/time ratio.

METHOD:
    1. Pick an anchor date/price (a significant pivot).
    2. For every subsequent date, the line's price =
           anchor_price + (planet_longitude(date) - planet_longitude(anchor_date)) * price_per_degree
       price_per_degree is a scale factor the user chooses (analogous to
       selecting a price increment on the Square of Nine, per Mikula Chapter 6's
       "Selecting the Increment" — no single correct value, must be chosen per
       market and calibrated).
    3. Score the line the same TOUCH-based way as the (bug-fixed) Gann trendline
       calibration in gann_decision_system.py: count genuine touches (price
       coming within tolerance of the line) while disqualifying lines that get
       decisively breached.

This directly reuses the touch/breach logic validated in gann_decision_system.py
(same fix: "stayed on the correct side" alone is not a valid touch/respect test).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

from gann_astrology import get_planet_longitude

TOUCH_TOLERANCE_PCT = 0.01
BREACH_TOLERANCE_PCT = 0.02


def build_planetary_line(planet: str, anchor_date: date, anchor_price: float,
                          trading_dates: list[date], price_per_degree: float) -> pd.Series:
    """
    Computes the planetary line's projected price for every date in
    trading_dates, following the planet's REAL geocentric longitude movement
    (not a fixed slope) from the anchor date/price.
    """
    anchor_longitude = get_planet_longitude(planet, anchor_date)
    projected_prices = []
    for d in trading_dates:
        current_longitude = get_planet_longitude(planet, d)
        # handle wraparound (longitude can cross 0/360 during the tracked period,
        # e.g. retrograde loops) by taking the signed shortest-path difference
        diff = current_longitude - anchor_longitude
        if diff > 180:
            diff -= 360
        elif diff < -180:
            diff += 360
        projected_prices.append(anchor_price + diff * price_per_degree)
    return pd.Series(projected_prices, index=trading_dates)


@dataclass
class PlanetaryLineTouchResult:
    planet: str
    price_per_degree: float
    touches: int
    breached: bool
    total_days_tested: int

    @property
    def touch_rate(self) -> float:
        return self.touches / self.total_days_tested if self.total_days_tested else 0.0

    @property
    def is_respected(self) -> bool:
        """A line is 'respected' if it was touched at least once and never decisively breached."""
        return self.touches > 0 and not self.breached


def test_planetary_line_touch(planet: str, anchor_date: date, anchor_price: float,
                               close_series: pd.Series, price_per_degree: float,
                               direction: int = 1) -> PlanetaryLineTouchResult:
    """
    Tests whether real price action touches and respects a planetary line drawn
    from (anchor_date, anchor_price), for the given planet.

    direction=1: line expected to act as SUPPORT (price should stay at/above it,
                 with genuine touches counted when price approaches from above).
    direction=-1: line expected to act as RESISTANCE (price stays at/below it).
    """
    trading_dates = [d.date() if hasattr(d, "date") else d for d in close_series.index]
    line = build_planetary_line(planet, anchor_date, anchor_price, trading_dates, price_per_degree)

    touches = 0
    breached = False
    tested = 0
    for d, actual in zip(trading_dates, close_series.values):
        projected = line.loc[d]
        if projected == 0:
            continue
        tested += 1

        if direction == 1 and actual < projected * (1 - BREACH_TOLERANCE_PCT):
            breached = True
        elif direction == -1 and actual > projected * (1 + BREACH_TOLERANCE_PCT):
            breached = True

        if abs(actual - projected) / abs(projected) <= TOUCH_TOLERANCE_PCT:
            touches += 1

    return PlanetaryLineTouchResult(
        planet=planet, price_per_degree=price_per_degree,
        touches=0 if breached else touches, breached=breached, total_days_tested=tested,
    )


def calibrate_price_per_degree(planet: str, anchor_date: date, anchor_price: float,
                                close_series: pd.Series,
                                candidate_scales: tuple[float, ...] = (0.05, 0.1, 0.25, 0.5, 1.0, 2.0),
                                direction: int = 1) -> list[PlanetaryLineTouchResult]:
    """
    Since there's no single 'correct' price-per-degree scale (Mikula's own
    "Selecting the Increment" section says this must be chosen/calibrated per
    market), this tests a range of candidate scales and returns them ranked by
    touch_rate among those NOT breached — same "test then trust" discipline used
    throughout this project rather than picking one scale arbitrarily.
    """
    results = [
        test_planetary_line_touch(planet, anchor_date, anchor_price, close_series, scale, direction)
        for scale in candidate_scales
    ]
    return sorted(results, key=lambda r: r.touch_rate, reverse=True)
