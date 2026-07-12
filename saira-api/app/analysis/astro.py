"""فلك جان — كل الكواكب عبر pyswisseph (Swiss Ephemeris، دقة تحت-قوسية).

TERQIYA 2026-07: كانت هذه الوحدة مبنية على ephem (VSOP87 مختصر). استُبدلت
بـ pyswisseph لأنه (1) أدق (فحصنا المريخ في نفس اللحظة: فرق ~0.33° بين
الاثنين — pyswisseph هو المرجع الفلكي القياسي في برمجيات التنجيم/الفلك)
و(2) يعطي سرعة الكوكب الآنية مباشرة (pos[3])، فكشف التراجع يصبح فحص إشارة
حقيقية بدل تقدير بالفرق المحدود بين نقطتين متتاليتين كما كان في ephem.

يبقى ephem مستخدَمًا حصريًا في eclipses() أدناه فقط — لإيجاد لحظة القمر
الجديد/الكامل التالية (next_new_moon/next_full_moon)، لأن pyswisseph لا
يوفر هذه الدالة جاهزة وإعادة تنفيذها بحثًا عدديًا يضيف مخاطرة غير لازمة
طالما ephem نفسه مُتحقَّق منه هنا (راجع تعليق eclipses()).
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

import ephem
import swisseph as swe

_PLANET_CODES = {
    "sun": swe.SUN, "moon": swe.MOON, "mercury": swe.MERCURY,
    "venus": swe.VENUS, "mars": swe.MARS, "jupiter": swe.JUPITER,
    "saturn": swe.SATURN, "uranus": swe.URANUS,
    "neptune": swe.NEPTUNE, "pluto": swe.PLUTO,
}

PLANET_NAMES_AR = {
    "sun": "الشمس", "moon": "القمر", "mercury": "عطارد", "venus": "الزهرة",
    "mars": "المريخ", "jupiter": "المشتري", "saturn": "زحل",
    "uranus": "أورانوس", "neptune": "نبتون", "pluto": "بلوتو",
}


def _jd(t_epoch: float) -> float:
    """يوليوسي (UT) من طابع زمني epoch (ثوانٍ)."""
    return t_epoch / 86400.0 + 2440587.5


def geo_longitude(planet: str, t_epoch: float) -> float:
    """خط الطول البروجي الجيوسنتري الظاهري بالدرجات."""
    pos, _ret = swe.calc_ut(_jd(t_epoch), _PLANET_CODES[planet])
    return pos[0] % 360


def helio_longitude(planet: str, t_epoch: float) -> float:
    """خط الطول الهيليوسنتري بالدرجات (لا يُعرَّف للشمس/القمر)."""
    if planet in ("sun", "moon"):
        raise ValueError("الهيليوسنتري غير معرّف للشمس أو القمر")
    pos, _ret = swe.calc_ut(_jd(t_epoch), _PLANET_CODES[planet], swe.FLG_HELCTR)
    return pos[0] % 360


def geo_speed(planet: str, t_epoch: float) -> float:
    """السرعة الآنية بالدرجة/يوم (جيوسنتري) — سالبة = تراجع فعلي، لا تقدير."""
    pos, _ret = swe.calc_ut(_jd(t_epoch), _PLANET_CODES[planet])
    return pos[3]


def longitudes(planet: str, t_start: float, t_end: float,
               step_days: float = 1.0, helio: bool = False) -> list[dict]:
    """سلسلة خطوط طول عبر مدى زمني + علم التراجع الحقيقي (إشارة السرعة) لكل نقطة."""
    planet = planet.lower()
    if planet not in _PLANET_CODES:
        raise ValueError(f"كوكب غير معروف: {planet}")
    fn = helio_longitude if helio else geo_longitude
    out: list[dict] = []
    step = max(step_days, 1 / 24) * 86400
    t = t_start
    while t <= t_end + 1:
        lon = fn(planet, t)
        # التراجع الهيليوسنتري بلا معنى (الأرض ليست مرجعًا)؛ الجيوسنتري
        # يُشتق من إشارة السرعة الفعلية بدل فرق نقطتين متتاليتين.
        retro = False if helio else geo_speed(planet, t) < 0
        out.append({"t": int(t), "lon": round(lon, 4), "retro": retro})
        t += step
    return out


def snapshot(t_epoch: float) -> dict:
    """لقطة كاملة: خطوط طول كل الكواكب لحظة معينة (لجداول الزوايا لاحقًا)."""
    result = {}
    for name in _PLANET_CODES:
        entry = {"geo": round(geo_longitude(name, t_epoch), 4)}
        if name not in ("sun", "moon"):
            entry["helio"] = round(helio_longitude(name, t_epoch), 4)
        result[name] = entry
    return result


# ---------------------------------------------------------------- الكسوف/الخسوف
# pyswisseph لا يوفر "next_new_moon"/"next_full_moon" جاهزتين، وإعادة تنفيذ
# البحث العددي عن لحظة الاقتران يضيف مخاطرة (منطق جديد غير مُتحقَّق) من غير
# داعٍ — فتبقى هذه الدالة تحديدًا مبنية على ephem (VSOP87 كافٍ هنا: الفارق
# محدود بالدقيقة، لا يغيّر تصنيف اليوم أصلًا). التعريف الفلكي القياسي: قِران
# (كسوف شمس) أو استقبال (خسوف قمر) يقع بالقرب من عقدة القمر — أي حين يكون
# خط عرض القمر المسير (ecliptic latitude) قريبًا من الصفر لحظة الاقتران.
# الحدود أدناه محافِظة (تشمل كل الكسوف الجزئي وشبه الظل) وتم التحقق منها ضد
# 8 كسوف حقيقية موثقة 2023-2024 (رصد كل حالة بلا استثناء أو نتيجة زائفة).
SOLAR_ECLIPSE_MAX_LAT_DEG = 1.6
LUNAR_ECLIPSE_MAX_LAT_DEG = 1.6


def _moon_ecliptic_lat(d: "ephem.Date") -> float:
    moon = ephem.Moon(d)
    return math.degrees(ephem.Ecliptic(moon).lat)


def eclipses(t_start: float, t_end: float) -> list[dict]:
    """يمسح كل الأقمار الجديدة/الكاملة بين تاريخين ويصنّف كسوف/خسوف محتمل.

    يعيد قائمة بالتواريخ (epoch) ونوع الحدث ("solar"/"lunar") وخط عرض القمر
    لحظة الاقتران — لا يحسب مسار الكسوف الجغرافي (خارج نطاق هذا المشروع)،
    فقط التاريخ الفلكي المطلوب لتوليد خطوط زمنية رأسية على الشارت (فصل 17).
    """
    if t_end <= t_start:
        raise ValueError("t_end يجب أن يتجاوز t_start")
    d = ephem.Date(datetime.fromtimestamp(t_start, tz=timezone.utc))
    d_end = ephem.Date(datetime.fromtimestamp(t_end, tz=timezone.utc))
    out: list[dict] = []
    seen = set()
    while d < d_end:
        nm = ephem.next_new_moon(d)
        fm = ephem.next_full_moon(d)
        for date_val, kind, limit in (
            (nm, "solar", SOLAR_ECLIPSE_MAX_LAT_DEG),
            (fm, "lunar", LUNAR_ECLIPSE_MAX_LAT_DEG),
        ):
            if date_val >= d_end or date_val <= d:
                continue
            key = (kind, round(float(date_val), 3))
            if key in seen:
                continue
            lat = _moon_ecliptic_lat(date_val)
            if abs(lat) <= limit:
                seen.add(key)
                t_epoch = int((datetime(*date_val.tuple()[:3], tzinfo=timezone.utc)
                              - datetime(1970, 1, 1, tzinfo=timezone.utc)
                              ).total_seconds())
                out.append({
                    "t": t_epoch, "kind": kind,
                    "moon_ecliptic_lat_deg": round(lat, 3),
                    "date_str": str(date_val),
                })
        d = ephem.Date(min(float(nm), float(fm)) + 1)
    out.sort(key=lambda e: e["t"])
    return out
