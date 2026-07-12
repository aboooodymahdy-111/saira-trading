"""
gann_astrology.py — Layer 3 (Astrology): planetary aspects and price/longitude
conversion, built from Scientific Methods Unveiled Vol. 1, Chapters 2, 4, and 8.

MAJOR UPDATE (2026-07): this module now computes REAL planetary positions using
the `ephem` (PyEphem) library, which has its own built-in analytical algorithms
(VSOP87-based, same underlying method as Abdo's own gann-astro-lines.html) and
needs NO external data file downloads — confirmed working fully offline in the
assistant's network-restricted sandbox (only `pip install ephem` itself needed
PyPI access; every actual position calculation below runs with zero network calls).

FORECASTING CONFIRMED (2026-07): all functions here work identically for FUTURE
dates, not just historical ones — tested through 2030 with physically sane
results (e.g. Saturn's computed motion rate matched its known ~29.5-year orbital
period to within ~5%). This means this module can be used for genuine forward-
looking signals (upcoming retrogrades, ingresses, planetary returns), not only
backtesting/verification.

PRECISION BOUNDS (per PyEphem's own documentation, web-verified 2026-07):
    - PyEphem uses VSOP87 for the major planets. Documented precision over the
      YEAR RANGE 1900-2100 is between 0.001 and 0.1 arcseconds depending on the
      planet — many thousands of times finer than the 2-degree aspect orb used
      in this module, so effectively exact for our purposes within this range.
    - This project's use case (current + several years forward, e.g. 2026-2032)
      sits comfortably inside the well-documented 1900-2100 range.
    - Outside 1900-2100, PyEphem does not throw an error (tested through 1800 and
      2100 without exceptions), but published precision figures don't cover that
      range — treat results outside 1900-2100 with more caution if ever needed.
    - PyEphem's own maintainers now recommend the newer `skyfield` library for
      new projects, but PyEphem remains accurate within its documented bounds and
      has the practical advantage (for this project) of needing no downloaded
      data files.

VERIFICATION — Gann's own "natural date" example (Scientific Methods Unveiled
Vol. 1, Chapter 8, quoting "How To Make Profits Trading in Commodities" p.210-211):
    Cotton price 97.50 was in OPPOSITION to Saturn on October 11, 1930.
    Computed here: Saturn's ecliptic longitude on 1930-10-11 = 277.01°.
    Opposition longitude (277.01 + 180) mod 360 = 97.01°.
    Cotton price as longitude: 97.50°.
    Difference: 0.49° — a near-exact match to a real historical Gann example,
    computed independently via ephem, not copied from the book.

PROVENANCE for the non-ephemeris parts (ASPECT_TABLE, price_to_longitude): same
as before, Scientific Methods Unveiled Vol. 1, Chapters 4 and 8.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta

import ephem


@dataclass(frozen=True)
class Aspect:
    name: str
    degrees: float
    classification: str  # "major" or "minor"


# Scientific Methods Unveiled Vol. 1, Chapter 4 — degrees apart, both directions
# around the zodiac (e.g. trine is both 120 and 240 degrees away).
ASPECT_TABLE: list[Aspect] = [
    Aspect("conjunction", 0, "major"),
    Aspect("semisextile", 30, "minor"),
    Aspect("semisquare", 45, "minor"),
    Aspect("sextile", 60, "major"),
    Aspect("square", 90, "major"),
    Aspect("trine", 120, "major"),
    Aspect("sesquare", 135, "minor"),
    Aspect("quincunx", 150, "minor"),
    Aspect("opposition", 180, "major"),
    Aspect("quincunx", 210, "minor"),
    Aspect("sesquare", 225, "minor"),
    Aspect("trine", 240, "major"),
    Aspect("square", 270, "major"),
    Aspect("sextile", 300, "major"),
    Aspect("semisquare", 315, "minor"),
    Aspect("semisextile", 330, "minor"),
    Aspect("conjunction", 360, "major"),
]

ASPECT_ORB_DEGREES = 2.0  # tolerance for treating two longitudes as "in aspect" rather than exact-only

PLANET_CLASSES: dict[str, type] = {
    "mercury": ephem.Mercury, "venus": ephem.Venus, "mars": ephem.Mars,
    "jupiter": ephem.Jupiter, "saturn": ephem.Saturn, "uranus": ephem.Uranus,
    "neptune": ephem.Neptune, "pluto": ephem.Pluto, "moon": ephem.Moon, "sun": ephem.Sun,
}

ZODIAC_SIGNS = [
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces",
]


def get_planet_longitude(planet: str, on_date: date) -> float:
    """
    Real geocentric ecliptic longitude (0-360 degrees) of a planet on a given
    date, computed via ephem's built-in algorithms — no network access needed.
    Verified against Gann's cotton/Saturn 1930-10-11 example (see module docstring).
    """
    planet_name = planet.lower()
    if planet_name not in PLANET_CLASSES:
        raise ValueError(f"Unknown planet '{planet}'. Valid options: {sorted(PLANET_CLASSES)}")
    body = PLANET_CLASSES[planet_name]()
    body.compute(on_date.strftime("%Y/%m/%d"))
    ecliptic = ephem.Ecliptic(body)
    return math.degrees(float(ecliptic.lon)) % 360


def get_planet_declination(planet: str, on_date: date) -> float:
    """
    Declination in degrees (positive = north of celestial equator, negative =
    south), per the book's "n"/"s" convention in Chapter 2. Uses the same ephem
    computation as get_planet_longitude().
    """
    planet_name = planet.lower()
    if planet_name not in PLANET_CLASSES:
        raise ValueError(f"Unknown planet '{planet}'. Valid options: {sorted(PLANET_CLASSES)}")
    body = PLANET_CLASSES[planet_name]()
    body.compute(on_date.strftime("%Y/%m/%d"))
    return math.degrees(float(body.dec))


def get_zodiac_sign(longitude: float) -> str:
    """Which of the 12 zodiac signs a given longitude (0-360) falls in."""
    index = int(longitude // 30) % 12
    return ZODIAC_SIGNS[index]


def is_retrograde(planet: str, on_date: date) -> bool:
    """
    Chapter 2 definition: "Retrograde motion... the planet's longitude will move
    backwards." Determined here by comparing longitude one day before and one day
    after on_date — if longitude decreased (accounting for 360-degree wraparound),
    the planet is retrograde on this date.
    """
    before = get_planet_longitude(planet, on_date - timedelta(days=1))
    after = get_planet_longitude(planet, on_date + timedelta(days=1))
    # handle wraparound (e.g. 359 -> 1 is forward motion, not retrograde)
    diff = after - before
    if diff > 180:
        diff -= 360
    elif diff < -180:
        diff += 360
    return diff < 0


def find_ingress_dates(planet: str, start_date: date, end_date: date) -> list[tuple[date, str]]:
    """
    Chapter 2 definition: "Planetary ingress... the date on which a planet enters
    a new zodiac sign." Scans day by day between start_date and end_date (inclusive)
    and reports each date the zodiac sign changes from the previous day.
    """
    results = []
    current = start_date
    prev_sign = get_zodiac_sign(get_planet_longitude(planet, current))
    current += timedelta(days=1)
    while current <= end_date:
        sign = get_zodiac_sign(get_planet_longitude(planet, current))
        if sign != prev_sign:
            results.append((current, sign))
        prev_sign = sign
        current += timedelta(days=1)
    return results


def angular_separation(longitude_a: float, longitude_b: float) -> float:
    """Shortest-path-agnostic separation between two zodiac longitudes, 0-360."""
    diff = abs(longitude_a - longitude_b) % 360
    return diff


def find_aspect(longitude_a: float, longitude_b: float, orb: float = ASPECT_ORB_DEGREES) -> Aspect | None:
    """
    Determines which named aspect (if any) two longitudes form, within the given
    orb (tolerance). Returns None if no aspect matches within tolerance — a real,
    meaningful "no relationship" result (Pillar 3: explicit, not silently guessed).
    """
    separation = angular_separation(longitude_a, longitude_b)
    closest = min(ASPECT_TABLE, key=lambda a: abs(a.degrees - separation))
    if abs(closest.degrees - separation) <= orb:
        return closest
    return None


def price_to_longitude(price: float) -> float:
    """
    "Linear zodiac" price-to-degree conversion (Chapter 8): every 360 price units
    (cents/points/dollars, chosen per market) maps to one full zodiac wheel.
    """
    return price % 360


def find_price_aspect(price: float, planet_longitude: float, orb: float = ASPECT_ORB_DEGREES) -> Aspect | None:
    """
    Checks whether a price (converted to a "linear zodiac" longitude) forms a
    named aspect with a given planet's longitude. See module docstring for the
    verified cotton/Saturn 1930 example.
    """
    price_longitude = price_to_longitude(price)
    return find_aspect(price_longitude, planet_longitude, orb)


def find_price_aspect_on_date(price: float, planet: str, on_date: date, orb: float = ASPECT_ORB_DEGREES) -> Aspect | None:
    """Convenience: compute a planet's real longitude on a date, then check the price aspect against it."""
    planet_longitude = get_planet_longitude(planet, on_date)
    return find_price_aspect(price, planet_longitude, orb)


def planetary_return_date(planet: str, target_longitude: float, search_start: date,
                           max_days_ahead: int = 900) -> date | None:
    """
    Abdo's "Planetary Return" idea (project conversation, 2026-07): finds the
    next date on/after search_start when the given planet's longitude returns to
    (within 0.5 degrees of) target_longitude. Scans day by day up to
    max_days_ahead — simple and slow but transparent and correct, given the
    irregular (non-fixed-period) geocentric orbits described in Chapter 2. Unlike
    the earlier "approximate period" placeholder, this now computes the REAL
    return date via ephem rather than guessing a rough period.
    """
    current = search_start
    end = search_start + timedelta(days=max_days_ahead)
    while current <= end:
        longitude = get_planet_longitude(planet, current)
        diff = abs(longitude - target_longitude) % 360
        diff = min(diff, 360 - diff)
        if diff <= 0.5:
            return current
        current += timedelta(days=1)
    return None


@dataclass(frozen=True)
class UpcomingEvent:
    event_date: date
    planet: str
    event_type: str  # "retrograde_start", "retrograde_end", "ingress"
    detail: str


def find_upcoming_events(planets: list[str], start_date: date, end_date: date) -> list[UpcomingEvent]:
    """
    Forward-looking scan (per the 2026-07 forecasting confirmation — see module
    docstring) across multiple planets at once: finds every retrograde
    start/end and every zodiac ingress within [start_date, end_date]. Intended
    for Layer 4 to answer "what astrological events affect this stock's upcoming
    signal window" without each caller re-implementing the day-by-day scan.

    This is a straightforward, transparent day-by-day scan (not optimized) —
    for a wide date range across many planets this can take a few seconds; that
    tradeoff is deliberate, favoring a simple, auditable implementation over a
    faster but harder-to-verify one, consistent with this project's coding
    standards (Pillar 4: readable over clever).
    """
    events: list[UpcomingEvent] = []
    for planet in planets:
        current = start_date
        prev_lon = get_planet_longitude(planet, current)
        prev_sign = get_zodiac_sign(prev_lon)
        prev_retrograde = is_retrograde(planet, current)
        current += timedelta(days=1)

        while current <= end_date:
            lon = get_planet_longitude(planet, current)
            sign = get_zodiac_sign(lon)
            retrograde = is_retrograde(planet, current)

            if sign != prev_sign:
                events.append(UpcomingEvent(current, planet, "ingress", f"enters {sign}"))
            if retrograde and not prev_retrograde:
                events.append(UpcomingEvent(current, planet, "retrograde_start", "begins retrograde motion"))
            elif not retrograde and prev_retrograde:
                events.append(UpcomingEvent(current, planet, "retrograde_end", "resumes direct motion"))

            prev_sign, prev_retrograde = sign, retrograde
            current += timedelta(days=1)

    return sorted(events, key=lambda e: e.event_date)
