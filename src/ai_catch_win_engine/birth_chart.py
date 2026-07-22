"""
ai_catch_win_engine/birth_chart.py — خريطة ميلاد السهم (natal chart): حساب الطالع
(Ascendant/البيت الأول) من تاريخ+وقت أول تداول (IPO)، وجدول الكواكب الحاكمة
للأبراج (rulership)، لتحديد "الكوكب الحاكم" لكل سهم — نقطة انطلاق التحليل بدل
البحث العشوائي عبر كل الكواكب العشرة.

خطوة تأسيسية طلبها عبده صراحة قبل تحليل الحركة الكوكبية المفردة: بدل اختبار
كل كوكب بلا أولوية، نبدأ بالكوكب الحاكم لبرج الطالع (البيت الأول) في خريطة
ميلاد السهم — نفس منطق التنجيم الكلاسيكي (الكوكب الحاكم لبرج الطالع هو
"صاحب" الخريطة، وأقوى تأثيراته المتوقعة على الكيان نفسه).

قرار منهجي (بدل تسجيل عدم اليقين): البورصة (NYSE/NASDAQ) ليست شخصًا له مكان
ميلاد جغرافي ذو معنى فلكي تقليدي، لكن لحظة "أول تداول" فعلية ومسجّلة — نستخدم
موقع NYSE (نيويورك، ~40.7128°N 74.0060°W) وساعة افتتاح التداول الرسمية
(9:30 صباحًا بتوقيت شرق أمريكا) كإحداثيات "الميلاد"، بنفس منطق كل منصات
التنجيم المالي المعروفة (Optuma/GannTrader تستخدم "IPO كخريطة ميلاد" كمفهوم
موثّق فعلاً في تعليقات الكود الحالي — راجع astro.py:199، main.py:319،
gann.py:325 — لكن بلا تفعيل فعلي؛ هذا أول تفعيل حقيقي لتلك الفكرة).

FORMULA PROVENANCE: صيغة الطالع (Ascendant) الفلكية الكلاسيكية:
    tan(Ascendant) = cos(RAMC) / (-sin(RAMC)·cos(ε) - tan(lat)·sin(ε))
حيث RAMC = الزمن النجمي المحلي (Local Sidereal Time) محوّلاً لدرجات (× 15)،
ε = ميل مسير الشمس (obliquity of the ecliptic، ~23.4367° للعصر J2000)،
lat = خط عرض المكان. هذه صيغة فلك رياضية كلاسيكية عامة (موجودة في أي كتاب
تنجيم رياضي أو مرجع فلك كروي قياسي)، وليست خاصة بأي برنامج تجاري.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, time

import ephem

from gann_astrology import ZODIAC_SIGNS, get_zodiac_sign

# NYSE/NASDAQ (تعاملان فعليًا من نفس منطقة نيويورك) — إحداثيات تقريبية
# لمركز مانهاتن المالي، كافية لدقة الطالع (فرق دقائق قليلة من الموقع الدقيق
# للمبنى لا يغيّر البرج الطالع في أغلب الحالات).
EXCHANGE_LATITUDE = 40.7128
EXCHANGE_LONGITUDE = -74.0060
MARKET_OPEN_TIME = time(9, 30)  # 9:30 صباحًا بتوقيت شرق أمريكا (EST/EDT)
OBLIQUITY_J2000_DEG = 23.4367  # ميل مسير الشمس، عصر J2000 — قيمة فلكية معيارية

# جدول الحكم الكلاسيكي (traditional/classical rulership، قبل اكتشاف
# أورانوس/نبتون/بلوتو) — كل برج له كوكب حاكم واحد فقط، متماثل حول الشمس/القمر
# (اللذان يحكمان برجًا واحدًا فقط، الأسد والسرطان على التوالي). هذا الجدول
# الكلاسيكي مُفضَّل هنا على الحكم الحديث (uranus/الدلو، neptune/الحوت،
# pluto/العقرب) لأنه أبسط وأقدم توافقًا عبر المصادر المرجعية المستخدمة في
# هذا المشروع (Mikula، Gann نفسه) — الحكم الحديث ملاحظة بديلة موثّقة في
# MODERN_RULERSHIP تحت لمن أراد المقارنة لاحقًا.
CLASSICAL_RULERSHIP: dict[str, str] = {
    "Aries": "mars", "Taurus": "venus", "Gemini": "mercury", "Cancer": "moon",
    "Leo": "sun", "Virgo": "mercury", "Libra": "venus", "Scorpio": "mars",
    "Sagittarius": "jupiter", "Capricorn": "saturn", "Aquarius": "saturn", "Pisces": "jupiter",
}

MODERN_RULERSHIP: dict[str, str] = {
    **CLASSICAL_RULERSHIP,
    "Scorpio": "pluto", "Aquarius": "uranus", "Pisces": "neptune",
}


def _local_sidereal_time_deg(on_date: date, on_time: time, longitude_deg: float) -> float:
    """الزمن النجمي المحلي (LST) بالدرجات، عبر ephem.Observer.sidereal_time()."""
    observer = ephem.Observer()
    observer.lat = "0"  # خط العرض هنا غير مستخدم لحساب LST نفسه (فقط lon يؤثر)
    observer.lon = str(longitude_deg)
    observer.date = f"{on_date.strftime('%Y/%m/%d')} {on_time.strftime('%H:%M:%S')}"
    lst_rad = float(observer.sidereal_time())
    return math.degrees(lst_rad) % 360


@dataclass(frozen=True)
class NatalAscendant:
    ascendant_longitude: float  # 0-360
    ascendant_sign: str
    ruling_planet: str  # الكوكب الحاكم لبرج الطالع (نظام كلاسيكي)


def compute_ascendant(on_date: date, on_time: time = MARKET_OPEN_TIME,
                       latitude_deg: float = EXCHANGE_LATITUDE,
                       longitude_deg: float = EXCHANGE_LONGITUDE) -> NatalAscendant:
    """
    يحسب خط طول الطالع (Ascendant) عبر الصيغة الفلكية الكلاسيكية (راجع
    docstring الملف للصيغة والمصدر). القيم الافتراضية (on_time/lat/lon) هي
    فرضية "ميلاد السهم" المُتَّفَق عليها: لحظة افتتاح تداول NYSE/NASDAQ.

    ملاحظة دقة صريحة: هذا تقريب زمني (يوم أول تداول التقويمي + افتراض 9:30
    صباحًا)، مش لحظة أول صفقة فعلية بالثانية — الطالع حساس جدًا للوقت (يتحرك
    ~1° كل 4 دقائق تقريبًا)، فبرج الطالع الناتج هنا "الأرجح إحصائيًا" وليس
    مؤكدًا 100% لو التداول الفعلي بدأ قبل/بعد 9:30 بدقائق معدودة عند فتح
    السوق أو بسبب halts/circuit breakers في أول يوم تداول.
    """
    ramc_deg = _local_sidereal_time_deg(on_date, on_time, longitude_deg)
    ramc_rad = math.radians(ramc_deg)
    epsilon_rad = math.radians(OBLIQUITY_J2000_DEG)
    lat_rad = math.radians(latitude_deg)

    numerator = math.cos(ramc_rad)
    denominator = -math.sin(ramc_rad) * math.cos(epsilon_rad) - math.tan(lat_rad) * math.sin(epsilon_rad)
    ascendant_rad = math.atan2(numerator, denominator)
    ascendant_deg = math.degrees(ascendant_rad) % 360

    sign = get_zodiac_sign(ascendant_deg)
    ruler = CLASSICAL_RULERSHIP[sign]

    return NatalAscendant(ascendant_longitude=ascendant_deg, ascendant_sign=sign, ruling_planet=ruler)


def house_cusps_equal(ascendant_longitude: float) -> list[float]:
    """
    حدود البيوت الاثني عشر بنظام Equal House (بيوت متساوية، طلب عبده 2026-07-18
    — الأبسط حسابيًا مقابل Placidus الأدق فلكيًا لكن الأكثر تعقيدًا رياضيًا):
    كل بيت يغطي 30° بالضبط بدءًا من الطالع (البيت الأول = [Asc, Asc+30)،
    البيت الثاني = [Asc+30, Asc+60)، ...، البيت العاشر = [Asc+270, Asc+300)).
    يرجّع قائمة من 12 قيمة (بداية كل بيت، بالترتيب 1-12).

    ملاحظة: هذا **ليس** نفس تعريف "البيت العاشر = Midheaven/MC" المستخدَم في
    أنظمة البيوت الفلكية الدقيقة (Placidus/Koch)، حيث MC يُحسب مستقلاً عن
    الطالع عبر RAMC مباشرة وقد لا يقع عند Asc+270° بالضبط. نظام Equal House
    يُبسِّط هذا عمدًا (Asc+270 دائمًا) — قرار عبده الصريح لتفادي التعقيد
    الرياضي الإضافي في هذه المرحلة التجريبية.
    """
    return [(ascendant_longitude + 30 * i) % 360 for i in range(12)]


def house_of_longitude(longitude: float, ascendant_longitude: float) -> int:
    """
    رقم البيت (1-12) الذي يقع فيه `longitude` بنظام Equal House، بالنسبة
    لـ`ascendant_longitude` — البيت الأول يبدأ عند الطالع نفسه بالضبط.
    """
    offset = (longitude - ascendant_longitude) % 360
    return int(offset // 30) + 1


def ruling_planet_for_ticker(ipo_date: date) -> NatalAscendant:
    """واجهة مختصرة: من تاريخ IPO فقط (بافتراض فرضية موقع/وقت البورصة أعلاه)."""
    return compute_ascendant(ipo_date)


if __name__ == "__main__":
    import sys

    # مثال تحقق سريع: تاريخ اختباري عشوائي، للتأكد من أن الصيغة تنتج بروجًا
    # متنوعة (مش قيمة ثابتة دايمًا) عبر تواريخ مختلفة — فحص سلامة ميكانيكي.
    test_dates = [date(2020, 1, 1), date(2020, 4, 1), date(2020, 7, 1), date(2020, 10, 1)]
    for d in test_dates:
        result = compute_ascendant(d)
        print(f"{d}: Ascendant={result.ascendant_longitude:.2f}° "
              f"({result.ascendant_sign}), ruler={result.ruling_planet}")
