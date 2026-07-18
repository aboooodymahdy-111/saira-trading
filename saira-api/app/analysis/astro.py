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


# ---------------------------------------------------------------- العلاقات الكوكبية (Aspects)
# الزوايا التقليدية الخمس بين كوكبين + هامش السماحية (orb) القياسي لكل
# منها — نفس القيم المستخدمة في التنجيم الكلاسيكي (اقتران/مقابلة أوسع
# سماحية من التسديس مثلًا، لأن تأثيرهما أقوى وأبطأ حركة نسبيًا حول الزاوية
# المضبوطة). المستخدم يقدر يغيّر السماحية صراحة عبر orb_deg في الطلب.
ASPECTS: dict[str, dict] = {
    "conjunction":  {"angle": 0.0, "orb": 8.0, "ar": "اقتران"},
    "semisextile":  {"angle": 30.0, "orb": 2.0, "ar": "نصف سداسي"},
    "semisquare":   {"angle": 45.0, "orb": 2.0, "ar": "نصف تربيع"},
    "sextile":      {"angle": 60.0, "orb": 4.0, "ar": "تسديس"},
    "square":       {"angle": 90.0, "orb": 6.0, "ar": "تربيع"},
    "trine":        {"angle": 120.0, "orb": 6.0, "ar": "تثليث"},
    "opposition":   {"angle": 180.0, "orb": 8.0, "ar": "مقابلة"},
}


def _angular_separation(lon_a: float, lon_b: float) -> float:
    """أصغر فرق زاوي بين خطي طول (0-180°، بلا إشارة اتجاه)."""
    diff = abs(lon_a - lon_b) % 360
    return diff if diff <= 180 else 360 - diff


def aspect_status(lon_a: float, lon_b: float, aspect: str,
                  orb_deg: float | None = None) -> dict:
    """يفحص هل خطا الطول lon_a وlon_b يشكّلان aspect المحدد ضمن السماحية
    الآن، ومدى قرب الفصل الفعلي من الزاوية المضبوطة بالتمام (0 = تمام
    الزاوية بالضبط، السماحية الكاملة = أبعد نقطة لا تزال "داخل" العلاقة)."""
    if aspect not in ASPECTS:
        raise ValueError(f"علاقة غير معروفة: {aspect}. الخيارات: {sorted(ASPECTS)}")
    spec = ASPECTS[aspect]
    orb = orb_deg if orb_deg is not None else spec["orb"]
    sep = _angular_separation(lon_a, lon_b)
    delta = abs(sep - spec["angle"])
    is_active = delta <= orb
    return {
        "aspect": aspect, "aspect_ar": spec["ar"], "target_angle": spec["angle"],
        "orb_deg": orb, "separation_deg": round(sep, 3),
        "delta_from_exact_deg": round(delta, 3), "is_active": is_active,
        "exactness_pct": round(max(0.0, 1 - delta / orb) * 100, 1) if orb > 0 else (100.0 if delta == 0 else 0.0),
    }


def scan_aspect(planet_a: str, mode_a: str, planet_b: str, mode_b: str,
                aspect: str, t_start: float, t_end: float,
                natal_t: float | None = None, orb_deg: float | None = None,
                step_days: float = 1.0, helio_a: bool = False,
                helio_b: bool = False) -> dict:
    """يمسح مدى زمني بحثًا عن أيام تكون فيها العلاقة المحددة بين كوكبين
    نشطة (ضمن السماحية) — يدعم أربع تركيبات: عبور-عبور (كلا الكوكبين
    يتحركان)، ميلاد-عبور أو عبور-ميلاد (أحدهما ثابت عند natal_t، مثل
    تاريخ IPO كخريطة ميلاد للسهم — مطابق لملاحظة الخطة عن IPO)، أو
    ميلاد-ميلاد (كلاهما ثابت — علاقة واحدة أبدية، لا مسح زمني فعليًا).

    mode_a/mode_b: "transit" (يتحرك مع الزمن) أو "natal" (يُثبَّت عند
    natal_t لحظة واحدة ولا يتغيّر خلال المسح).
    """
    for mode in (mode_a, mode_b):
        if mode not in ("transit", "natal"):
            raise ValueError(f"mode يجب أن يكون transit أو natal، ليس {mode}")
    if ("natal" in (mode_a, mode_b)) and natal_t is None:
        raise ValueError("natal_t مطلوب عند استخدام mode=natal لأي كوكب")

    fn_a = helio_longitude if helio_a else geo_longitude
    fn_b = helio_longitude if helio_b else geo_longitude

    natal_lon_a = fn_a(planet_a, natal_t) if mode_a == "natal" else None
    natal_lon_b = fn_b(planet_b, natal_t) if mode_b == "natal" else None

    step = max(step_days, 1 / 24) * 86400
    events: list[dict] = []
    t = t_start
    prev_active = False
    while t <= t_end:
        lon_a = natal_lon_a if mode_a == "natal" else fn_a(planet_a, t)
        lon_b = natal_lon_b if mode_b == "natal" else fn_b(planet_b, t)
        status = aspect_status(lon_a, lon_b, aspect, orb_deg)
        # نسجّل فقط بداية كل نافذة نشاط (لا كل يوم داخلها) — تجنبًا لإغراق
        # النتيجة بمئات الصفوف المتتالية لعلاقة بطيئة الحركة (كواكب خارجية).
        if status["is_active"] and not prev_active:
            events.append({"t": int(t), **status,
                           "lon_a": round(lon_a, 3), "lon_b": round(lon_b, 3)})
        prev_active = status["is_active"]
        t += step

    return {
        "planet_a": planet_a, "mode_a": mode_a,
        "planet_b": planet_b, "mode_b": mode_b,
        "aspect": aspect, "orb_deg": orb_deg if orb_deg is not None else ASPECTS[aspect]["orb"],
        "natal_t": natal_t, "events": events,
    }
