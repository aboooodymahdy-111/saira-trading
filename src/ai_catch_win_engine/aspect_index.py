"""
ai_catch_win_engine/aspect_index.py — مؤشر اتصالات يومي على طراز ZET9's AspGraphic
(راجع CLAUDE.md/ZET_AspGraphic_Methodology.md للمنهجية الأصلية المُشتقة عبر
تحليل عكسي لمخرجات ZET9 الفعلية).

**الفكرة (توجيه عبده 2026-07-18)**: كل الاختبارات السابقة في هذه الحزمة
(planet_isolation.py, same_ascendant_batch.py) قاست العلاقة بين **مستوى**
السعر وزاوية θ مستمرة عبر انحدار توافقي (fit_harmonic: wave ≈ A·cos(θ)+
B·sin(θ)) — لكن ملاحظة عبده الجوهرية: "حركة الكواكب فقط تصنع أضعف تأثير...
تخيل موجة ثابتة ومستقرة هل يتغير السعر كثيرًا؟" — بمعنى: الزاوية المستمرة بين
كوكب متحرك وكوكب/نقطة ثابتة ليست "حدثًا"، بل **لحظات تشكّل مناظرة كاملة
(aspect exact) هي الأحداث الفعلية**، أشبه بموجتين تتقاطعان بحدة، لا انحرافًا
تدريجيًا ناعمًا. لذلك التصميم هنا مختلف جوهريًا:
  - نقيس **تزامن التغيّر** (|Δprice| اليومي، لا مستوى السعر) مع **مؤشر عدد
    الاتصالات النشطة يوميًا** (aspect count، معدود مرجَّح متناغم/متوتر)،
    بنفس منطق ZET9's AspGraphic (عدّ on/off لكل مناظرة نشطة، لا دالة قوة
    متدرجة حسب دقة الأورب — راجع القسم 3.2-3.3 من الوثيقة المرجعية).

**نطاق هذه الخطوة الأولى (مبسّط عمدًا بتوجيه عبده)**: كوكب متحرك واحد فقط
(transit) في كل مرة — يبدأ بحاكم برج الطالع المُختبَر (زحل/أورانوس لحاكمي
الدلو)، لا كل السبعة الكلاسيكية دفعة واحدة كما في ZET9 الكامل. اتصالاته
تُحسب مع باقي الكواكب الست الكلاسيكية (زحل، مشتري، الزهرة، الشمس، عطارد،
القمر — بالترتيب من الأبطأ للأسرع، استبعاد الكوكب المتحرك نفسه من قائمة
الأهداف) **بصيغة transit-to-natal تحديدًا** (طلب عبده الصريح): موقع الكوكب
المتحرك اليوم مقابل موقع كل من الكواكب الأخرى **الثابت في خريطة ميلاد
السهم** (لا موقعها المتحرك اليوم أيضًا — ذلك transit-to-transit، مؤجَّل).

**تصنيف متناغم/متوتر (Ebertin/ZET9 التقليدي)**: تسديس (60°) وتثليث (120°) =
متناغم؛ تربيع (90°) وتقابل (180°) = متوتر. **الاقتران (0°) متروك متعمدًا بلا
تصنيف** (طلب عبده الصريح: "البعض يعتبر الاقتران مدمرًا في حالة اقتران كوكبين
سعيد ونحس... لا تفترض بخصوص هذا الاتصال") — يُعَدّ في مؤشر منفصل
(`n_conjunction`) بدل إقحامه في أي عمود، والمُستخدم في المؤشر الصافي هنا هو
فقط (متناغم − متوتر)، لا الاقتران.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, ".")

from full_universe_analysis import build_local_ticker_index, load_local_history
from gann_astrology import get_planet_longitude

from ai_catch_win_engine.birth_chart import compute_ascendant
from ai_catch_win_engine.natal_dates import NatalDateUnavailable, get_natal_date

ASPECT_ORB_DEGREES = 3.0  # أورب أوسع قليلاً من ASPECT_ORB_DEGREES في gann_astrology.py (2.0)
                          # لأن المؤشر هنا يعتمد على "on/off" يومي واحد، لا تدرّج دقيق

HARMONIOUS_ASPECT_DEGREES = (60.0, 120.0)  # تسديس، تثليث
TENSE_ASPECT_DEGREES = (90.0, 180.0)       # تربيع، تقابل
CONJUNCTION_DEGREES = 0.0                  # مجهول التصنيف عمدًا — راجع docstring الملف

CLASSICAL_SEVEN = ["saturn", "jupiter", "mars", "venus", "sun", "mercury", "moon"]


def _classify_separation(separation: float, orb: float = ASPECT_ORB_DEGREES) -> str | None:
    """يرجّع 'harmonious' / 'tense' / 'conjunction' / None (لا مناظرة نشطة)."""
    sep = separation % 360
    sep = min(sep, 360 - sep)  # 0-180، لأن أي مناظرة تتكرر على الجانبين

    if sep <= orb:
        return "conjunction"
    for deg in HARMONIOUS_ASPECT_DEGREES:
        if abs(sep - deg) <= orb:
            return "harmonious"
    for deg in TENSE_ASPECT_DEGREES:
        if abs(sep - deg) <= orb:
            return "tense"
    return None


@dataclass(frozen=True)
class DailyAspectCounts:
    n_harmonious: int
    n_tense: int
    n_conjunction: int

    @property
    def net_score(self) -> int:
        """المؤشر الصافي المُستخدَم في الاختبار: متناغم ناقص متوتر (الاقتران مُستبعَد عمدًا)."""
        return self.n_harmonious - self.n_tense


def daily_aspect_counts(transit_planet: str, on_date: date, natal_longitudes: dict[str, float],
                         orb: float = ASPECT_ORB_DEGREES) -> DailyAspectCounts:
    """
    عدد الاتصالات النشطة بين `transit_planet` (موقعه الحالي في on_date) وكل
    كوكب آخر في `natal_longitudes` (مواقعها الثابتة وقت ميلاد السهم) —
    transit-to-natal تحديدًا، لا transit-to-transit.
    """
    transit_lon = get_planet_longitude(transit_planet, on_date)
    n_harm = n_tense = n_conj = 0
    for other_planet, natal_lon in natal_longitudes.items():
        if other_planet == transit_planet:
            continue
        separation = transit_lon - natal_lon
        classification = _classify_separation(separation, orb)
        if classification == "harmonious":
            n_harm += 1
        elif classification == "tense":
            n_tense += 1
        elif classification == "conjunction":
            n_conj += 1
    return DailyAspectCounts(n_harmonious=n_harm, n_tense=n_tense, n_conjunction=n_conj)


def natal_longitudes_for_ticker(ticker: str, natal_date: date,
                                 planets: list[str] = CLASSICAL_SEVEN) -> dict[str, float]:
    """مواقع السبعة الكلاسيكية (أو أي قائمة فرعية) في لحظة ميلاد السهم — تُحسب مرة واحدة."""
    return {p: get_planet_longitude(p, natal_date) for p in planets}


def _daily_net_score_series(transit_planet: str, dates: list[date],
                             natal_lons: dict[str, float]) -> tuple[np.ndarray, int, int, int]:
    net_scores, n_harm_total, n_tense_total, n_conj_total = [], 0, 0, 0
    for d in dates:
        counts = daily_aspect_counts(transit_planet, d, natal_lons)
        net_scores.append(counts.net_score)
        n_harm_total += counts.n_harmonious
        n_tense_total += counts.n_tense
        n_conj_total += counts.n_conjunction
    return np.array(net_scores, dtype=float), n_harm_total, n_tense_total, n_conj_total


N_SHIFTS_DEFAULT = 300


def _spearman_permutation_test(abs_delta_price: np.ndarray, net_scores: np.ndarray,
                                n_shifts: int = N_SHIFTS_DEFAULT,
                                rng_seed: int = 42) -> float:
    """
    اختبار تباديل بالإزاحة الدائرية لسلسلة net_scores (نفس منهجية
    effect_size.permutation_test_harmonic بالضبط: الإزاحة الدائرية تحافظ على
    الارتباط الذاتي الزمني في net_scores بينما تفكّ تزامنها الحقيقي مع
    abs_delta_price) — يرجّع p-value لـ|r| الحقيقي مقابل توزيع |r| المُزاح.
    """
    observed_r, _ = stats.spearmanr(abs_delta_price, net_scores)
    n = len(net_scores)
    rng = np.random.default_rng(rng_seed)
    shifts = rng.integers(1, n, size=n_shifts)

    more_extreme = 0
    for shift in shifts:
        shifted = np.roll(net_scores, shift)
        shifted_r, _ = stats.spearmanr(abs_delta_price, shifted)
        if abs(shifted_r) >= abs(observed_r):
            more_extreme += 1
    return (more_extreme + 1) / (n_shifts + 1)


def _spearman_random_control_test(abs_delta_price: np.ndarray, net_scores: np.ndarray,
                                   n_shifts: int = N_SHIFTS_DEFAULT,
                                   rng_seed: int = 42) -> float:
    """
    اختبار الضبط (راجع effect_size.random_control_test_harmonic): يستبدل
    net_scores الحقيقية بقيم عشوائية بالكامل من نفس المدى (uniform integer
    بين أدنى وأقصى قيمة ظهرت فعليًا) قبل إعادة نفس اختبار التباديل من الصفر —
    لو "نجح" حتى مع بيانات عشوائية، فالمنهجية نفسها (لا الكوكب) هي المصدر.
    """
    rng = np.random.default_rng(rng_seed)
    lo, hi = int(net_scores.min()), int(net_scores.max())
    if lo == hi:
        return 1.0  # لا تباين ممكن أصلاً — لا معنى للاختبار
    random_scores = rng.integers(lo, hi + 1, size=len(net_scores)).astype(float)
    return _spearman_permutation_test(abs_delta_price, random_scores, n_shifts, rng_seed)


@dataclass(frozen=True)
class AspectSyncResult:
    ticker: str
    transit_planet: str
    window_start: date
    window_end: date
    n_days: int
    spearman_r: float
    spearman_p_value: float
    permutation_p_value: float
    random_control_p_value: float
    passes_gates: bool
    n_harmonious_total: int
    n_tense_total: int
    n_conjunction_total: int


def measure_aspect_sync(ticker: str, transit_planet: str, window_start: date, window_end: date,
                         natal_date: date, alpha: float,
                         target_planets: list[str] | None = None,
                         rng_seed: int = 42) -> AspectSyncResult | None:
    """
    يقيس تزامن |Δprice| اليومي مع مؤشر net_score (متناغم-متوتر) اليومي عبر
    ارتباط Spearman (رتبي، لا يفترض علاقة خطية — مناسب هنا لأن net_score قيمة
    مُعدودة صغيرة المدى (عادة -3..+3)، لا مستمرة)، **ثم** يطبّق نفس بوابتي
    القبول المعتمدتين في كل تجربة سابقة بهذه الحزمة (permutation + control) —
    ضروري هنا تحديدًا لأن نوافذ طويلة (>1000 يوم) تجعل حتى r ضعيف جدًا
    (r=0.05) "دالًا إحصائيًا" بالـp الخام وحده (فحص مباشر: n=1832، r=0.05 →
    p=0.032) — نفس فخ significance-inflation المُوثَّق بالمشروع مرارًا.

    target_planets الافتراضي: كل السبعة الكلاسيكية عدا transit_planet نفسه.
    """
    idx = build_local_ticker_index()
    hist = load_local_history(ticker, idx)
    if hist is None:
        return None

    win = hist.loc[str(window_start):str(window_end)]
    if len(win) < 30:
        return None

    if target_planets is None:
        target_planets = [p for p in CLASSICAL_SEVEN if p != transit_planet]

    natal_lons = natal_longitudes_for_ticker(ticker, natal_date, target_planets)

    close = win["Close"].to_numpy()
    abs_delta_price = np.abs(np.diff(close))
    dates = [ts.date() for ts in win.index[1:]]  # يبدأ من اليوم الثاني (diff)

    net_scores, n_harm_total, n_tense_total, n_conj_total = _daily_net_score_series(
        transit_planet, dates, natal_lons)

    if len(set(net_scores.tolist())) < 2:  # لا تباين إطلاقًا — Spearman غير مُعرَّف
        return None

    rho, raw_p_value = stats.spearmanr(abs_delta_price, net_scores)
    perm_p = _spearman_permutation_test(abs_delta_price, net_scores, rng_seed=rng_seed)
    control_p = _spearman_random_control_test(abs_delta_price, net_scores, rng_seed=rng_seed)
    passes_gates = perm_p < alpha and control_p >= alpha

    return AspectSyncResult(
        ticker=ticker, transit_planet=transit_planet, window_start=window_start, window_end=window_end,
        n_days=len(dates), spearman_r=float(rho), spearman_p_value=float(raw_p_value),
        permutation_p_value=perm_p, random_control_p_value=control_p, passes_gates=passes_gates,
        n_harmonious_total=n_harm_total, n_tense_total=n_tense_total, n_conjunction_total=n_conj_total,
    )


if __name__ == "__main__":
    from datetime import date as _date
    ticker_arg = sys.argv[1] if len(sys.argv) > 1 else "MAR"
    planet_arg = sys.argv[2] if len(sys.argv) > 2 else "saturn"
    start_arg = _date.fromisoformat(sys.argv[3]) if len(sys.argv) > 3 else _date(2019, 3, 9)
    end_arg = _date.fromisoformat(sys.argv[4]) if len(sys.argv) > 4 else _date.today()

    from lab_stats import bonferroni_alpha
    from ai_catch_win_engine.planet_isolation import SLOW_PLANETS
    alpha = bonferroni_alpha(len(SLOW_PLANETS))

    try:
        natal = get_natal_date(ticker_arg)
    except NatalDateUnavailable as exc:
        print(f"{ticker_arg}: {exc}")
        sys.exit(1)

    result = measure_aspect_sync(ticker_arg, planet_arg, start_arg, end_arg, natal, alpha)
    if result is None:
        print("لا نتيجة (بيانات غير كافية أو لا تباين في المؤشر).")
    else:
        verdict = "✅ عبر" if result.passes_gates else "❌ لم يعبر"
        print(f"{result.ticker} × {result.transit_planet} transit "
              f"({result.window_start} → {result.window_end}, {result.n_days} يوم)")
        print(f"  Spearman r={result.spearman_r:.4f} (raw p={result.spearman_p_value:.5f})")
        print(f"  permutation p={result.permutation_p_value:.5f}, control p={result.random_control_p_value:.5f} — {verdict}")
        print(f"  اتصالات: متناغم={result.n_harmonious_total}, متوتر={result.n_tense_total}, "
              f"اقتران={result.n_conjunction_total}")
