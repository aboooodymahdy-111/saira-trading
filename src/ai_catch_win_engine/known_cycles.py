"""
ai_catch_win_engine/known_cycles.py — جدول ثابت لفترات الدورات الفلكية المعروفة
مسبقًا (لا اكتشاف، فلك كلاسيكي بحت)، يُستخدم في المرحلة 3 (الإسناد) لمطابقة
فترة IMF المستخرجة بأقرب دورة كوكبية.

الفترات المدارية (sidereal، بالأيام) من ephem/VSOP87 (نفس المكتبة المستخدمة في
gann_astrology.py) — قيم فلكية معيارية معروفة، وليست مُقاسة من بيانات السعر.
دورات التقارن (synodic) بين كوكبين محسوبة من الصيغة الكلاسيكية:
    1/T_synodic = |1/T_a - 1/T_b|
(الأرض تُعتبر ضمنيًا كوكب المرجع الجيوسنتري لكل الأزواج التي تشمل كوكبًا
داخليًا أسرع من الأرض؛ الصيغة أعلاه صحيحة عمومًا لأي زوجين حول نفس المركز).
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

# فترات مدارية (sidereal) بالأيام — قيم فلكية معيارية معروفة (VSOP87/JPL)
SIDEREAL_PERIOD_DAYS: dict[str, float] = {
    "moon": 27.32,
    "mercury": 87.97,
    "venus": 224.70,
    "earth": 365.25,
    "mars": 686.98,
    "jupiter": 4332.59,
    "saturn": 10759.22,
    "uranus": 30688.5,
    "neptune": 60182.0,
    "pluto": 90560.0,
}

# الشمس (من منظور جيوسنتري) لها نفس فترة الأرض المدارية (365.25 يوم) —
# مُدرجة صراحة لتفادي أي التباس أنها "غير معروفة".
SIDEREAL_PERIOD_DAYS["sun"] = SIDEREAL_PERIOD_DAYS["earth"]


@dataclass(frozen=True)
class KnownCycle:
    label: str            # مثال: "mercury" أو "mars-jupiter synodic"
    period_days: float
    kind: str              # "sidereal" (كوكب مفرد) أو "synodic" (زوج كواكب)


def _synodic_period_days(period_a: float, period_b: float) -> float:
    """1/T_syn = |1/Ta - 1/Tb| — الصيغة الكلاسيكية لدورة التقارن بين جرمين."""
    diff = abs(1.0 / period_a - 1.0 / period_b)
    if diff == 0:
        raise ValueError("planets share the exact same period — synodic period undefined (infinite)")
    return 1.0 / diff


def build_known_cycles_table(include_synodic_pairs: bool = True) -> list[KnownCycle]:
    """
    يبني قائمة كل الدورات المعروفة القابلة للمطابقة: كل كوكب مفرد (sidereal)،
    وإذا include_synodic_pairs=True، كل زوج كواكب (synodic) — الشمس مستبعدة من
    الأزواج (فترتها الجيوسنترية = فترة الأرض، ما يجعل "تقارن الأرض-الشمس" غير
    معرَّف/بلا معنى من هذا المنظور).
    """
    planets = [p for p in SIDEREAL_PERIOD_DAYS if p not in ("earth", "sun")]
    cycles = [
        KnownCycle(label=planet, period_days=SIDEREAL_PERIOD_DAYS[planet], kind="sidereal")
        for planet in SIDEREAL_PERIOD_DAYS
        if planet != "earth"  # الأرض نفسها مش جسم يُرصد جيوسنتريًا
    ]
    if include_synodic_pairs:
        for a, b in combinations(planets, 2):
            period = _synodic_period_days(SIDEREAL_PERIOD_DAYS[a], SIDEREAL_PERIOD_DAYS[b])
            cycles.append(KnownCycle(label=f"{a}-{b} synodic", period_days=period, kind="synodic"))
    return cycles


@dataclass(frozen=True)
class CycleMatch:
    cycle: KnownCycle
    imf_period_days: float
    error_pct: float  # |imf_period - cycle.period| / cycle.period


def match_period_to_known_cycles(imf_period_days: float, max_error_pct: float = 10.0,
                                  include_synodic_pairs: bool = True) -> list[CycleMatch]:
    """
    يبحث عن كل الدورات المعروفة اللي فترتها قريبة من فترة IMF المُكتشفة (ضمن
    max_error_pct% نسبة خطأ) — قد يرجّع أكثر من مطابقة (مثلاً كوكب مفرد وزوج
    تقارن بنفس الفترة تقريبًا)؛ المرحلة التالية (التحقق بالطور) هي اللي تفصل
    بينها لاحقًا، مش هذه الدالة. مرتبة تصاعديًا بنسبة الخطأ (الأقرب أولاً).
    """
    if imf_period_days <= 0:
        raise ValueError(f"imf_period_days must be positive, got {imf_period_days}")

    matches = []
    for cycle in build_known_cycles_table(include_synodic_pairs=include_synodic_pairs):
        error_pct = abs(imf_period_days - cycle.period_days) / cycle.period_days * 100
        if error_pct <= max_error_pct:
            matches.append(CycleMatch(cycle=cycle, imf_period_days=imf_period_days, error_pct=error_pct))
    return sorted(matches, key=lambda m: m.error_pct)
