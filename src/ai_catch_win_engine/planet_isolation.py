"""
ai_catch_win_engine/planet_isolation.py — يطبّق منهجية عبده الجديدة (2026-07):
لكل كوكب على حدة، بدل تفكيك EMD عشوائي، نبني نافذة تغطي 2-3 دورات كاملة لهذا
الكوكب تحديدًا، ثم نبحث عن النوافذ ذات **أقل عدد اتصالات (أسبكتات) نشطة** مع
باقي الكواكب — في هذه النوافذ تحديدًا، تأثير حركة الكوكب المفرد على السعر
أوضح لأن تداخل قوى الكواكب الأخرى في حدّه الأدنى (تقليل ضوضاء عبر اختيار
العيّنة، لا عبر التصفية الإحصائية بعد الحساب).

MAJOR REVISION (2026-07، بعد فحص فعلي): التصميم الأول افترض "عزل مطلق" (صفر
أسبكتات مع أي جرم، ثنائي isolated/not) — فحص فعلي على المريخ عبر 1718 يوم
(2.5 دورة) أظهر 173 يوم معزول فرديًا (~10%) لكن أطول متتالية متصلة 8 أيام فقط
(محتاجين 30+ للانحدار). هذا متوقَّع تركيبيًا: مع 9 أجرام أخرى كل واحد "يحجب"
~11% من الوقت بأسبكت ضمن orb ضيق، احتمال عدم وجود أي أسبكت مع أي جرم لعشرين
يوم متتالٍ ضعيف جدًا رياضيًا — وليس خطأ في الكود. طلب عبده الفعلي (بالنص) كان
"أقل عدد اتصالات" (تقليل نسبي)، مش "صفر اتصالات" (عزل مطلق) — تفسير أول كان
أكثر تشددًا من المطلوب. التصحيح: نقيس **كثافة الأسبكتات** (aspect density،
عدد الأسبكتات النشطة يوميًا مع كل الأجرام الأخرى)، ونختار نوافذ متحركة (مش
أيام منفردة) ذات أدنى متوسط كثافة، بدل اشتراط صفر مطلق.

الخطوات:
    1. لكل كوكب (SLOW_PLANETS بالأساس — مريخ/مشتري/زحل/أورانوس/نبتون/بلوتو،
       لأن الكواكب السريعة (قمر/شمس/عطارد/زهرة) نادرًا ما "قليلة الاتصالات"
       لفترة طويلة كفاية، وهي بالضبط الكواكب اللي هيمنت على النتائج الفاشلة
       في harness.py/rolling_harness.py — نفس التوصية الموثّقة في
       Understanding Timing Solution.md قسم 10.2).
    2. لكل يوم في نافذة التاريخ، حساب aspect_density(day) = عدد الأسبكتات
       النشطة بين الكوكب وكل الأجرام الأخرى (ضمن ISOLATION_ORB_DEGREES) —
       هذه ظاهرة فلكية مطلقة (زاوية الفصل بين جرمين حقيقيين)، لا علاقة لها
       بخريطة ميلاد أي سهم بعينه، فتُحسب مرة واحدة وتُعاد استخدامها لكل الأسهم.
    3. نافذة متحركة (rolling) بمتوسط aspect_density أدنى = "أنقى" نافذة.
    4. لأنقى N نافذة، قياس العلاقة بين **موقع الكوكب النسبي لطالع خريطة ميلاد
       هذا السهم تحديدًا** (transit position = خط_الطول - طالع_السهم، مش
       خط الطول الخام ولا موقعه البرجي النظري المطلق — تذكير عبده الصريح:
       "التحرك يقاس بناءً على خريطة الميلاد وليس على البروج النظرية") والسعر
       الخام منزوع اتجاه خطي بسيط، عبر انحدار توافقي (fit_harmonic).
       راجع القسم 9.2 من الوثيقة المرجعية لتحقق رياضي أن هذا التصحيح يغيّر
       الطور (متى يرتفع/ينخفض) لا قوة العلاقة (R²) — كلاهما مطلوب: القوة
       تأتي من اختيار النافذة نفسها (خطوة 2-3)، والطور من موقع النسبة للطالع.

الإطار المفاهيمي الكامل (توضيح عبده، 2026-07): تخيّل 9 مصادر موجات بترددات
مختلفة تمامًا — ككرة حديدية 50 كجم (كوكب بطيء كزحل: تأثير كبير الحجم لكنه
بطيء التغيّر) مقابل كرة 50 جرام (كوكب سريع كعطارد: تأثير صغير لكنه سريع
التغيّر). الاستراتيجية الصحيحة هي بناء الموجة الكلية **من الأكبر للأصغر**:
هذا الملف يقيس الطبقة الأولى (الكواكب البطيئة، بإطار زمني يومي، متجاهلاً
تذبذب القمر/عطارد السريع كـ"ضوضاء" بالنسبة لهذا المقياس الزمني) — الموجة
"الكبيرة" الأساسية. الطبقة التالية (لم تُبنَ بعد) تضيف الكواكب الأسرع
كتصحيحات أدق، تُقاس بأطر زمنية أقصر (ساعات/دقائق، حسب سرعة الكوكب —
عطارد/القمر تأثيرهما يظهر على فريم 5-15 دقيقة حسب توضيح عبده، لا الأيام).
الدمج النهائي لكل الطبقات (من الأبطأ للأسرع) هو "الموجة المُركَّبة" المتوقَّع
أن توافق تقلبات السعر الحية — هذا الملف يبني الطبقة الأولى فقط من هذا البرج.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

sys.path.insert(0, ".")

from full_universe_analysis import build_local_ticker_index, load_local_history
from gann_astrology import ASPECT_TABLE, PLANET_CLASSES, get_planet_longitude

from ai_catch_win_engine.birth_chart import compute_ascendant
from ai_catch_win_engine.effect_size import fit_harmonic, permutation_test_harmonic, random_control_test_harmonic
from ai_catch_win_engine.known_cycles import SIDEREAL_PERIOD_DAYS

ISOLATION_ORB_DEGREES = 2.5  # "نقي" بالمعنى الصارم — راجع نقاش القرار مع عبده (orb ضيق ±2-3°)

# الكواكب البطيئة فقط (نفس توصية TS قسم 10.2) — سريعة الاستبعاد: قمر/شمس/
# عطارد/زهرة، لأنها نادرًا ما تكون "معزولة" لفترة طويلة (تتحرك بسرعة فتشكّل
# أسبكتات جديدة باستمرار)، وهي أصلاً مصدر الهيمنة/الـartifact الموثّق سابقًا.
SLOW_PLANETS = ["mars", "jupiter", "saturn", "uranus", "neptune", "pluto"]

# طلب عبده الصريح (2026-07): تجاهل اتصالات القمر وعطارد عند حساب كثافة
# الأسبكتات — أسرع جرمين، فوجودهما في الحساب يضمن كثافة عالية شبه دائمًا
# (القمر وحده يمر بأسبكت جديد كل يوم-يومين تقريبًا)، ما يطمس أي فرق حقيقي في
# الكثافة الناتج عن باقي الكواكب. الشمس تُستبعد أيضًا لنفس السبب (حركة سريعة
# نسبيًا، ~1°/يوم) رغم عدم ذكرها صراحة، اتساقًا مع قائمة "الكواكب السريعة"
# الموثّقة في TS قسم 10.2 (قمر/شمس/عطارد/زهرة) — الزهرة أُبقيت لأنها أبطأ
# نسبيًا من عطارد/القمر وعبده لم يذكرها صراحة بالاستبعاد.
DENSITY_EXCLUDED_BODIES = {"moon", "mercury"}
ALL_OTHER_BODIES = [b for b in PLANET_CLASSES if b not in DENSITY_EXCLUDED_BODIES]


def _aspect_count_on_date(planet: str, on_date: date, orb: float = ISOLATION_ORB_DEGREES) -> int:
    """
    عدد الأسبكتات النشطة بين `planet` وكل الأجرام الأخرى (عدا القمر/عطارد،
    راجع DENSITY_EXCLUDED_BODIES) في on_date — 0 يعني معزول تمامًا عن باقي
    الكواكب البطيئة/المتوسطة.
    """
    planet_lon = get_planet_longitude(planet, on_date)
    count = 0
    for other in ALL_OTHER_BODIES:
        if other == planet:
            continue
        other_lon = get_planet_longitude(other, on_date)
        separation = abs(planet_lon - other_lon) % 360
        for aspect in ASPECT_TABLE:
            if abs(aspect.degrees - separation) <= orb:
                count += 1
                break  # أسبكت واحد يكفي لعدّ هذا الجرم كـ"متصل" — مش أكتر من نوع أسبكت لنفس الزوج
    return count


def aspect_density_series(planet: str, start_date: date, end_date: date,
                           orb: float = ISOLATION_ORB_DEGREES) -> pd.Series:
    """سلسلة يومية بعدد الأسبكتات النشطة لـ`planet` — الأساس لاختيار أنقى النوافذ."""
    dates = []
    counts = []
    current = start_date
    while current <= end_date:
        dates.append(current)
        counts.append(_aspect_count_on_date(planet, current, orb))
        current += timedelta(days=1)
    return pd.Series(counts, index=pd.DatetimeIndex(dates), name="aspect_count")


@dataclass(frozen=True)
class LowDensityWindow:
    start_date: date
    end_date: date
    n_days: int
    mean_aspect_count: float


def find_lowest_density_windows(planet: str, start_date: date, end_date: date,
                                 window_days: int, n_windows: int = 5,
                                 orb: float = ISOLATION_ORB_DEGREES) -> list[LowDensityWindow]:
    """
    يبني سلسلة كثافة الأسبكتات اليومية، ثم متوسط متحرك (rolling mean) بطول
    window_days، ويرجّع أدنى n_windows نافذة غير متداخلة (كل نافذة تبدأ بعد
    نهاية السابقة، تفاديًا لإرجاع نوافذ شبه متطابقة تتزحلق يومًا واحدًا فقط).
    """
    density = aspect_density_series(planet, start_date, end_date, orb)
    rolling_mean = density.rolling(window=window_days).mean()

    candidates = rolling_mean.dropna().sort_values()
    selected: list[LowDensityWindow] = []
    used_ranges: list[tuple[pd.Timestamp, pd.Timestamp]] = []

    for window_end_ts, mean_density in candidates.items():
        window_start_ts = window_end_ts - pd.Timedelta(days=window_days - 1)
        overlaps = any(window_start_ts <= used_end and window_end_ts >= used_start
                       for used_start, used_end in used_ranges)
        if overlaps:
            continue
        selected.append(LowDensityWindow(
            start_date=window_start_ts.date(), end_date=window_end_ts.date(),
            n_days=window_days, mean_aspect_count=float(mean_density),
        ))
        used_ranges.append((window_start_ts, window_end_ts))
        if len(selected) >= n_windows:
            break

    return selected


@dataclass(frozen=True)
class IsolationEffectResult:
    ticker: str
    planet: str
    window_start: date
    window_end: date
    n_days: int
    mean_aspect_count: float
    beta_points_per_degree: float
    r_squared: float
    permutation_p_value: float
    random_control_p_value: float
    passes_gates: bool


def _natal_ascendant_for_ticker(ticker: str) -> float:
    """
    خريطة ميلاد السهم: تاريخ الميلاد الحقيقي (أول تداول فعلي عبر
    natal_dates.get_natal_date، لا أول صف في ملف البيانات المحلي).

    MAJOR REVISION (2026-07-18، بتوجيه عبده الصريح): كانت هذه الدالة تأخذ
    `hist.index[0].date()` — أول تاريخ متوفر في الأرشيف المحلي — كتقريب
    لتاريخ IPO. فحص فعلي كشف أن هذا **قيد بيانات لا معنى فلكي له**: عشرات
    الشركات المختلفة تمامًا تشارك نفس "أول تاريخ محلي" (حدود أرشيف تقنية،
    راجع docstring natal_dates.py بالتفصيل الكامل والأرقام). أي طالع محسوب
    من هذا التقريب لا يقيس خريطة ميلاد السهم الحقيقية، فأُلغي فورًا لصالح
    natal_dates.get_natal_date (يرفع NatalDateUnavailable صراحة لو تعذّر
    الحصول على تاريخ حقيقي — لا رجوع صامت لتقريب الأرشيف بعد الآن).
    """
    from ai_catch_win_engine.natal_dates import get_natal_date
    ipo_date = get_natal_date(ticker)
    return compute_ascendant(ipo_date).ascendant_longitude


def measure_window_effect(ticker: str, planet: str, window: LowDensityWindow,
                           alpha: float, rng_seed: int = 42) -> IsolationEffectResult | None:
    """
    يقيس العلاقة بين موقع `planet` **النسبي لطالع خريطة ميلاد هذا السهم**
    (transit position، مش خط الطول الجيوسنتري الخام) والسعر الخام (منزوع
    اتجاه خطي بسيط) خلال نافذة منخفضة كثافة الأسبكتات — انحدار توافقي
    (fit_harmonic)، بلا EMD.

    لماذا الموقع النسبي للطالع لا الخام (تصحيح جوهري 2026-07 بناءً على توضيح
    عبده): خط الطول الجيوسنتري الخام لكوكب معيّن **نفسه بالضبط** لكل الأسهم في
    نفس اللحظة (المريخ في نفس النقطة بالسماء الليلة بغض النظر عن أي سهم)،
    فاستخدامه مباشرة كـθ يجعل كل الأسهم "تتفق" على نفس النافذة الفائزة —
    وهذا فعليًا ما لوحظ (AAPL وMSFT فازتا بنفس نافذة 1999-2004 حرفيًا) رغم
    عدم وجود علاقة سببية منطقية تُلزم كل الأسهم بالتزامن معًا. حسب التنجيم
    التقليدي، تأثير الكوكب يُقرأ عبر **خريطة transit** (دمج الموقع الحالي مع
    خريطة الميلاد) — نفس درجة المريخ تقع في بيت مختلف تمامًا حسب طالع كل
    خريطة (مثال عبده: المريخ في الحمل = بيت أول لو الحمل طالعك، بيت ثانٍ لو
    الحوت طالعك). لذلك θ الصحيحة هنا = (خط_طول_الكوكب - خط_طول_طالع_السهم)،
    فتختلف فعليًا بين الأسهم حتى لو كانت حركة الكوكب المطلقة متطابقة.
    """
    local_index = build_local_ticker_index()
    hist = load_local_history(ticker, local_index)
    if hist is None:
        return None

    win = hist.loc[str(window.start_date):str(window.end_date)]
    if len(win) < 30:
        return None

    from ai_catch_win_engine.natal_dates import NatalDateUnavailable
    try:
        natal_ascendant = _natal_ascendant_for_ticker(ticker)
    except NatalDateUnavailable:
        return None

    close = win["Close"]
    trend = np.polyval(np.polyfit(np.arange(len(close)), close.to_numpy(), deg=1), np.arange(len(close)))
    detrended = close.to_numpy() - trend

    dates = [ts.date() for ts in close.index]
    longitude = np.array([get_planet_longitude(planet, d) for d in dates])
    transit_position = (longitude - natal_ascendant) % 360  # موقع الكوكب النسبي لبيت هذا السهم الأول
    theta_rad = np.radians(transit_position)

    try:
        fit = fit_harmonic(detrended, theta_rad)
        perm_result = permutation_test_harmonic(detrended, theta_rad, n_shifts=300, rng_seed=rng_seed)
        control_result = random_control_test_harmonic(detrended, n_points=len(detrended),
                                                        n_shifts=300, rng_seed=rng_seed)
    except ValueError:
        return None

    passes_gates = perm_result.p_value < alpha and control_result.p_value >= alpha

    return IsolationEffectResult(
        ticker=ticker, planet=planet, window_start=window.start_date, window_end=window.end_date,
        n_days=window.n_days, mean_aspect_count=window.mean_aspect_count,
        beta_points_per_degree=fit.beta_points_per_degree, r_squared=fit.r_squared,
        permutation_p_value=perm_result.p_value, random_control_p_value=control_result.p_value,
        passes_gates=passes_gates,
    )


def recommended_window_days(planet: str, n_cycles: float = 2.5) -> int:
    """
    نافذة موصى بها (بالأيام) تغطي n_cycles دورة كاملة لهذا الكوكب — طلب عبده
    الصريح: "نافذة تغطي دورتين كاملتين على الأقل وربما 3". n_cycles=2.5
    كنقطة بداية معقولة بين الحدين (2 و3) المذكورين.
    """
    if planet not in SIDEREAL_PERIOD_DAYS:
        raise ValueError(f"Unknown planet '{planet}'. Valid: {sorted(SIDEREAL_PERIOD_DAYS)}")
    return int(SIDEREAL_PERIOD_DAYS[planet] * n_cycles)


def run_planet_isolation_experiment(ticker: str, planet: str, n_windows: int = 5,
                                     rng_seed: int = 42) -> list[IsolationEffectResult]:
    """
    الدالة الرئيسية: يبحث عن أنقى n_windows نافذة (أقل متوسط كثافة أسبكتات)
    ضمن كل التاريخ المحلي المتاح للسهم، ويقيس تأثير `planet` في كل واحدة.
    """
    from lab_stats import bonferroni_alpha

    local_index = build_local_ticker_index()
    hist = load_local_history(ticker, local_index)
    if hist is None:
        print(f"ai_catch_win_engine: مفيش بيانات محلية لـ {ticker}.")
        return []

    window_days = recommended_window_days(planet)
    history_start = hist.index[0].date()
    history_end = hist.index[-1].date()
    if (history_end - history_start).days < window_days:
        print(f"ai_catch_win_engine: تاريخ {ticker} أقصر من نافذة {planet} الموصى بها ({window_days} يوم).")
        return []

    print(f"ai_catch_win_engine: {ticker} × {planet} — نافذة {window_days} يوم (~2.5 دورة)، "
          f"بحث عبر {history_start} إلى {history_end}")

    windows = find_lowest_density_windows(planet, history_start, history_end, window_days, n_windows)
    if not windows:
        print("  مفيش نوافذ كافية الطول لهذا النطاق التاريخي.")
        return []

    alpha = bonferroni_alpha(len(SLOW_PLANETS))  # تصحيح Bonferroni عبر الكواكب البطيئة فقط هنا
    results = []
    for w in windows:
        result = measure_window_effect(ticker, planet, w, alpha, rng_seed)
        if result is not None:
            results.append(result)
    return results


def _print_isolation_result(result: IsolationEffectResult) -> None:
    verdict = "✅ اجتاز" if result.passes_gates else "❌ لم يجتز"
    print(f"\n  نافذة: {result.window_start} إلى {result.window_end} ({result.n_days} يوم)، "
          f"متوسط كثافة أسبكتات={result.mean_aspect_count:.2f}")
    print(f"    beta={result.beta_points_per_degree:.4f} نقطة/درجة (R²={result.r_squared:.3f})")
    print(f"    permutation p={result.permutation_p_value:.4f}, "
          f"control p={result.random_control_p_value:.4f} — {verdict}")


if __name__ == "__main__":
    ticker_arg = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    planet_arg = sys.argv[2] if len(sys.argv) > 2 else "mars"

    outcomes = run_planet_isolation_experiment(ticker_arg, planet_arg)
    if not outcomes:
        print(f"\nai_catch_win_engine: مفيش نتائج لـ {ticker_arg} × {planet_arg}.")
    for outcome in outcomes:
        _print_isolation_result(outcome)
