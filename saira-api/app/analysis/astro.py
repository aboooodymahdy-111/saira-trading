"""فلك جان — كل الكواكب عبر ephem (VSOP87، يعمل دون اتصال).

يعيد خطوط الطول البروجية geocentric أو heliocentric لأي كوكب عبر
مدى زمني، مع كشف فترات التراجع (Retrograde) — الأساس الذي ستُبنى
عليه الخطوط الكوكبية والماسح الكوكبي (Planetary Scanner) لاحقًا.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

import ephem

_PLANETS = {
    "sun": ephem.Sun, "moon": ephem.Moon, "mercury": ephem.Mercury,
    "venus": ephem.Venus, "mars": ephem.Mars, "jupiter": ephem.Jupiter,
    "saturn": ephem.Saturn, "uranus": ephem.Uranus,
    "neptune": ephem.Neptune, "pluto": ephem.Pluto,
}

PLANET_NAMES_AR = {
    "sun": "الشمس", "moon": "القمر", "mercury": "عطارد", "venus": "الزهرة",
    "mars": "المريخ", "jupiter": "المشتري", "saturn": "زحل",
    "uranus": "أورانوس", "neptune": "نبتون", "pluto": "بلوتو",
}


def _dt(t_epoch: float) -> datetime:
    return datetime.fromtimestamp(t_epoch, tz=timezone.utc)


def geo_longitude(planet: str, t_epoch: float) -> float:
    """خط الطول البروجي الجيوسنتري بالدرجات."""
    body = _PLANETS[planet]()
    body.compute(_dt(t_epoch))
    return math.degrees(ephem.Ecliptic(body).lon) % 360


def helio_longitude(planet: str, t_epoch: float) -> float:
    """خط الطول الهيليوسنتري بالدرجات (لا يُعرَّف للشمس/القمر)."""
    if planet in ("sun", "moon"):
        raise ValueError("الهيليوسنتري غير معرّف للشمس أو القمر")
    body = _PLANETS[planet]()
    body.compute(_dt(t_epoch))
    return math.degrees(body.hlon) % 360


def longitudes(planet: str, t_start: float, t_end: float,
               step_days: float = 1.0, helio: bool = False) -> list[dict]:
    """سلسلة خطوط طول عبر مدى زمني + علم التراجع لكل نقطة."""
    planet = planet.lower()
    if planet not in _PLANETS:
        raise ValueError(f"كوكب غير معروف: {planet}")
    fn = helio_longitude if helio else geo_longitude
    out: list[dict] = []
    step = max(step_days, 1 / 24) * 86400
    t, prev = t_start, None
    while t <= t_end + 1:
        lon = fn(planet, t)
        retro = False
        if prev is not None and not helio:      # لا تراجع هيليوسنتري
            delta = (lon - prev + 540) % 360 - 180
            retro = delta < 0
        out.append({"t": int(t), "lon": round(lon, 4), "retro": retro})
        prev, t = lon, t + step
    return out


def snapshot(t_epoch: float) -> dict:
    """لقطة كاملة: خطوط طول كل الكواكب لحظة معينة (لجداول الزوايا لاحقًا)."""
    result = {}
    for name in _PLANETS:
        entry = {"geo": round(geo_longitude(name, t_epoch), 4)}
        if name not in ("sun", "moon"):
            entry["helio"] = round(helio_longitude(name, t_epoch), 4)
        result[name] = entry
    return result
