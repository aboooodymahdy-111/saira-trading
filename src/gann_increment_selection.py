"""
gann_increment_selection.py — Determines an appropriate price increment (for
Square of Nine cell_price) or price-per-degree scale (for planetary lines),
based on the stock's OWN price level and actual volatility — not a fixed
arbitrary number, per Abdo's explicit point (2026-07): the same 90-degree or
180-degree "step" means something completely different for a stock moving
$100/day vs one moving in cents.

PROVENANCE: Mikula's Square of Nine guide, Chapter 6, "Selecting the Increment"
(page 103) gives documented price-TIER guidelines:
    Low price stocks:    start with 0.01, 0.05, 0.10
    Medium price stocks: start with 0.10, 0.25, 0.50
    High price stocks:   start with 0.25, 0.50, 1.00
    Stock indexes:       start with 1, 5, 10, 25
This module uses those documented tiers as a baseline, but REFINES them using
the stock's own Average True Range (ATR) — its actual typical daily price
movement — since two stocks at the same absolute price level can have very
different volatility (a $50 stock moving $0.20/day vs one moving $5/day should
NOT use the same increment, even though the book's price-only tiers would
treat them identically).
"""

from __future__ import annotations

import pandas as pd


def compute_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> float:
    """Standard Average True Range over the given period (most recent value)."""
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()
    return float(atr.iloc[-1])


def book_price_tier_candidates(price_level: float) -> list[float]:
    """Mikula Chapter 6's documented starting candidates, by price tier."""
    if price_level < 10:
        return [0.01, 0.05, 0.10]
    if price_level < 100:
        return [0.10, 0.25, 0.50]
    if price_level < 1000:
        return [0.25, 0.50, 1.00]
    return [1, 5, 10, 25]  # index-like / very high price level


def recommended_price_increment(high: pd.Series, low: pd.Series, close: pd.Series) -> dict:
    """
    Combines the book's documented price-tier candidates with a volatility-based
    refinement: the increment should be a reasonable FRACTION of the stock's own
    ATR (its typical daily range) — too small and the Square of Nine cells are
    finer than the market ever actually moves in a day (noise, not signal); too
    large and every cell spans multiple days' worth of movement (too coarse to
    be useful). A commonly sensible starting point is roughly ATR/4 to ATR/2,
    which this function uses to pick the book-tier candidate closest to that
    volatility-implied scale, rather than leaving the choice arbitrary.

    Returns a dict with both the book-tier candidates (for transparency) and the
    final volatility-informed recommendation, so Abdo can see the reasoning, not
    just a bare number (Pillar 4: readable, not a black box).
    """
    price_level = float(close.iloc[-1])
    atr = compute_atr(high, low, close)
    candidates = book_price_tier_candidates(price_level)

    volatility_target = atr / 3  # a cell should represent roughly a third of a typical day's range
    closest = min(candidates, key=lambda c: abs(c - volatility_target))

    return {
        "price_level": round(price_level, 2),
        "atr_14": round(atr, 4),
        "book_tier_candidates": candidates,
        "volatility_implied_target": round(volatility_target, 4),
        "recommended_increment": closest,
    }


def recommended_price_per_degree(high: pd.Series, low: pd.Series, close: pd.Series,
                                  planet_typical_daily_degrees: float = 1.0) -> dict:
    """
    Analogous recommendation for planetary-line price_per_degree scale
    (gann_planetary_lines.py): chosen so that the line's implied daily price
    movement (price_per_degree * planet's typical daily degree movement) is in
    the same ballpark as the stock's own actual typical daily movement (ATR) —
    otherwise the planetary line will drift completely off the visible price
    range within days (if too steep) or barely move at all (if too shallow),
    regardless of the astronomical calculation's own correctness.

    planet_typical_daily_degrees is planet-specific (e.g. Mercury moves roughly
    ~1-1.5 degrees/day on average when direct, much slower for outer planets)
    — pass the right approximate value for the planet being used; this function
    does not hardcode per-planet rates since they vary too much to guess safely
    (Mercury's own geocentric rate varies from about -1.5 to +2.2 degrees/day
    depending on retrograde state, per standard astronomical references).
    """
    atr = compute_atr(high, low, close)
    recommended_scale = atr / planet_typical_daily_degrees if planet_typical_daily_degrees else None
    return {
        "atr_14": round(atr, 4),
        "planet_typical_daily_degrees": planet_typical_daily_degrees,
        "recommended_price_per_degree": round(recommended_scale, 4) if recommended_scale else None,
    }


# ---------------------------------------------------------------------------
# ABDO'S ALTERNATIVE METHOD (2026-07): volatility DIVIDED BY the angle span,
# giving a precise, continuous increment derived directly from the stock's own
# movement — distinct from the book's method above, which picks the nearest
# ROUND NUMBER from a fixed candidate list. Both are implemented separately so
# they can be empirically compared (see compare_increment_methods below),
# rather than assuming either is correct without testing.
# ---------------------------------------------------------------------------

def volatility_reference_increment(high: pd.Series, low: pd.Series, close: pd.Series,
                                    reference_degrees: float = 90.0, atr_period: int = 14) -> dict:
    """
    Abdo's method: increment = ATR / reference_degrees. This gives an EXACT
    value derived directly from the stock's actual volatility, rather than
    snapping to the nearest round number from Mikula's book-tier candidates.
    reference_degrees is typically 90 or 180 (a quarter or half rotation) —
    the "angle span" the volatility is being distributed across.
    """
    atr = compute_atr(high, low, close, atr_period)
    increment = atr / reference_degrees
    return {
        "atr": round(atr, 4),
        "reference_degrees": reference_degrees,
        "increment": round(increment, 5),
    }


def compare_increment_methods(high: pd.Series, low: pd.Series, close: pd.Series,
                               price_increment_touch_test_fn) -> pd.DataFrame:
    """
    Empirically compares the book's round-number method against Abdo's direct
    volatility/degrees method, using a caller-supplied touch-test function
    (e.g. a wrapper around gann_decision_system.calibrate_square9_angle) that
    takes (high, low, close, increment) and returns a hit-rate-like score. This
    keeps this module independent of gann_decision_system (avoiding a circular
    import) while still enabling a real, data-driven comparison rather than a
    guess about which method is "better".
    """
    book_rec = recommended_price_increment(high, low, close)
    book_increment = book_rec["recommended_increment"]

    rows = []
    book_score = price_increment_touch_test_fn(high, low, close, book_increment)
    rows.append({"method": "book_round_number", "increment": book_increment, "score": book_score})

    for degrees in (45, 90, 180, 360):
        vol_rec = volatility_reference_increment(high, low, close, reference_degrees=degrees)
        vol_increment = vol_rec["increment"]
        score = price_increment_touch_test_fn(high, low, close, vol_increment)
        rows.append({"method": f"volatility/{degrees}deg", "increment": vol_increment, "score": score})

    return pd.DataFrame(rows).sort_values("score", ascending=False).reset_index(drop=True)
