"""
gann_time_cycles.py — Layer 2 (Time): forecasting pivot DATES using the Square of
Nine's cell/angle structure, instead of cell/PRICE (which gann_square9_precise.py
handles).

PROVENANCE: Mikula's "The Definitive Guide to Forecasting Using W.D. Gann's Square
of Nine", Chapter 4 "Forecasting Dates: Using Cell Numbers".

METHOD (documented, and verified below against the book's own worked example):
    Instead of Cell Number * Price Increment = Cell Price, here:
        Start Date + Cell Number (calendar or trading days) = Cell Date
    Cells landing on a chosen angle (e.g. the 45-degree angle, using the SAME
    cell_angle() table already built and verified in gann_square9_precise.py) become
    candidate forecast pivot dates.

VERIFICATION — Chapter 4 Example 2, Altera (ALTR):
    Starting pivot date: Tuesday, October 8, 2002 (a low pivot).
    45-degree-angle cells: 17, 37, 65, 101, 145.
    Book's stated CALENDAR-day dates for these cells: 10/25/02, 11/14/02, 12/12/02,
    01/17/03, 03/02/03 — all 5 reproduced EXACTLY by cell_to_calendar_date() below
    (verified in this module's test run, see project history 2026-07).
    Book's stated TRADING-day date for cell 17: 10/31/02 — also reproduced exactly
    by cell_to_trading_date() (17 business days after Oct 8, 2002, landing on
    Thursday Oct 31, 2002 — confirmed by manual business-day count).

    This is the strongest possible validation available: exact reproduction of the
    book's own five-date worked example, not a guess or an approximation.

LIMITATION: cell_to_trading_date() counts only weekends as non-trading days (no
    market holiday calendar). The book's own example matches this simplified
    counting exactly for the cases checked, but a full production version should
    use an actual NYSE holiday calendar (e.g. via the `pandas_market_calendars`
    package) for dates spanning a holiday, which this simplified version would
    get wrong by a day or two.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta

from gann_square9_precise import cell_angle, MAX_TABLED_CELL


def cell_to_calendar_date(start_date: date, cell_number: int) -> date:
    """
    Chapter 4 method, calendar-day count. Verified: start_date=2002-10-08,
    cell_number=17 -> 2002-10-25 (exact match to the book's ALTR example).
    """
    return start_date + timedelta(days=cell_number)


def cell_to_trading_date(start_date: date, cell_number: int) -> date:
    """
    Chapter 4 method, trading-day count (business days, weekends excluded, no
    holiday calendar — see module docstring limitation note). Verified: cell 17
    from start_date=2002-10-08 -> 2002-10-31 (exact match to the book's ALTR
    trading-day example).
    """
    current = start_date
    days_counted = 0
    while days_counted < cell_number:
        current += timedelta(days=1)
        if current.weekday() < 5:  # Monday=0 ... Friday=4
            days_counted += 1
    return current


@dataclass(frozen=True)
class DateForecast:
    cell_number: int
    angle: float
    calendar_date: date
    trading_date: date


def forecast_dates_at_angle(start_date: date, angle: float, max_cell: int = MAX_TABLED_CELL) -> list[DateForecast]:
    """
    Finds every cell (up to max_cell) whose angle matches the requested one, and
    returns both the calendar-day and trading-day forecast dates for each — this
    matches the book's own method of running BOTH counts in parallel and watching
    for whichever one correlates with real market pivots (Chapter 4, ALTR example:
    "the calendar days correlate with all tops... the trading day count to
    correlate with the opposite").
    """
    results = []
    for cell in range(2, max_cell + 1):
        if abs(cell_angle(cell) - angle) < 0.01:
            results.append(DateForecast(
                cell_number=cell,
                angle=angle,
                calendar_date=cell_to_calendar_date(start_date, cell),
                trading_date=cell_to_trading_date(start_date, cell),
            ))
    return results


def days_between(first_pivot_date: date, second_pivot_date: date, count_type: str = "calendar") -> int:
    """
    Chapter 5 "Forecasting Dates Using Overlays and Two Historical Pivot Dates":
    determines which cell number the SECOND pivot date falls into, counting from
    the FIRST pivot date as the Square of Nine's starting date. This cell number
    is then used to align the overlay's 0-degree angle (see two_pivot_overlay_dates()).

    VERIFIED against the book's Soybean example: first_pivot=2001-04-24,
    second_pivot=2001-07-17 -> 60 trading days (book states cell 60) and
    84 calendar days (book states cell 84). Both confirmed exact.
    """
    if count_type == "calendar":
        return (second_pivot_date - first_pivot_date).days
    if count_type == "trading":
        d = first_pivot_date
        count = 0
        while d < second_pivot_date:
            d += timedelta(days=1)
            if d.weekday() < 5:
                count += 1
        return count
    raise ValueError(f"count_type must be 'calendar' or 'trading', got '{count_type}'")


def two_pivot_overlay_dates(first_pivot_date: date, second_pivot_date: date,
                             count_type: str = "calendar", target_angles: tuple[float, ...] = (45.0, 90.0, 120.0, 135.0, 180.0),
                             max_cell: int = MAX_TABLED_CELL) -> list[DateForecast]:
    """
    Full Chapter 5 method: the overlay's 0-degree angle is aligned on whichever
    cell the second pivot date falls into (relative to the first pivot date as the
    day-count starting point). Cells at target_angles AWAY from that alignment
    cell (using move_around_square-style rotation, same as
    gann_square9_precise.find_overlay_levels) become forecast dates.

    Default target_angles includes 120 degrees because the book's Soybean example
    specifically calls out both the 45-degree AND 120-degree angles as the ones
    that correlated with real pivots in that market.
    """
    from gann_square9_precise import move_around_square

    alignment_cell = days_between(first_pivot_date, second_pivot_date, count_type)
    results = []
    for target_angle in target_angles:
        # angle relative to alignment_cell's own angle (the overlay's 0-degree reference)
        rotation_fraction = target_angle / 360.0
        for direction in (1, -1):
            moved = move_around_square(alignment_cell, rotation_fraction * direction)
            cell = round(moved)
            if cell < 2 or cell > max_cell:
                continue
            if count_type == "calendar":
                forecast_date = cell_to_calendar_date(first_pivot_date, cell)
            else:
                forecast_date = cell_to_trading_date(first_pivot_date, cell)
            results.append(DateForecast(
                cell_number=cell, angle=target_angle,
                calendar_date=forecast_date if count_type == "calendar" else None,
                trading_date=forecast_date if count_type == "trading" else None,
            ))
    return results


def anniversary_dates(pivot_date: date, years_ahead: int = 5) -> list[date]:
    """
    Anniversary Dates: a simpler, well-established Gann concept distinct from the
    Square of Nine cell/angle math above.

    SOURCE CONFIRMED (2026-07, web search): W.D. Gann's own words, "45 Years in
    Wall Street" (1949), p.92: "In my research work I have discovered that stocks
    make an important change in trend in the MONTHS when they reach extreme high
    and low. These are what I call anniversary dates." This confirms the concept
    is EARTH'S calendar year (same calendar date, N years later) — NOT a planetary
    orbital period. (A related but DISTINCT technique, "planetary return" — when a
    planet returns to the same zodiacal degree it held at a pivot — is a real
    astrological method, but belongs in Layer 3, not here.)
    """
    results = []
    for n in range(1, years_ahead + 1):
        try:
            results.append(pivot_date.replace(year=pivot_date.year + n))
        except ValueError:
            # Feb 29 on a pivot date with no matching leap day N years later
            results.append(pivot_date.replace(year=pivot_date.year + n, day=28))
    return results


def price_time_square_check(price: float, days_elapsed: int, tolerance_pct: float = 0.02) -> dict:
    """
    "Square Out of Time" / "Squaring Price and Time": a move is considered "squared
    out" when sqrt(days_elapsed) is close to the price level (or equivalently,
    price^2 is close to days_elapsed). This is Gann's stated "most important
    discovery" per multiple secondary sources (2026-07 web research; not from the
    project's uploaded books, which don't name this technique explicitly).

    VERIFIED against a real documented example (Alcoa, bottomed 2009-03-06 at
    $4.97, peaked 2010-01-11 at $17.60, 311 calendar days later):
    price_time_square_check(17.60, 311) -> sqrt(311)=17.635, within $0.035 of the
    actual peak price (well under a 1% tolerance).

    Returns a dict with the comparison so the caller can judge closeness themselves
    rather than get a bare True/False that hides how close/far the match was.
    """
    sqrt_days = math.sqrt(days_elapsed)
    diff = abs(sqrt_days - price)
    diff_pct = diff / price if price != 0 else float("inf")
    return {
        "price": price,
        "days_elapsed": days_elapsed,
        "sqrt_days_elapsed": round(sqrt_days, 3),
        "difference": round(diff, 3),
        "difference_pct": round(diff_pct * 100, 2),
        "is_squared": diff_pct <= tolerance_pct,
    }
