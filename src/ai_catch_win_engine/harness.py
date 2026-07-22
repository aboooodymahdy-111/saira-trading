"""
ai_catch_win_engine/harness.py — التجربة المصغّرة (قسم 7 من
CLAUDE.md/Astro_Wave_Decomposition_Methodology.md): سهم واحد، IMF واحد (الأسرع/
الأعلى طاقة)، اختبار الفرضية الجوهرية قبل بناء الـ pipeline الكامل بـ7 مراحل.

الخطوات (كل واحدة تعيد استخدام كود موجود فعلاً حيث أمكن):
    1. EMD على السعر (lab_spectral_features.emd_decompose، موجود بالفعل).
    2. فترة IMF الأول عبر FFT (lab_spectral_features.fft_cycle_features).
    3. مطابقة الفترة بأقرب دورة كوكبية معروفة (known_cycles.py، جديد).
    4. حركة الكوكب/الزوج المُطابَق يوميًا عبر gann_astrology (موجود بالفعل).
    5. قياس beta بانحدار توافقي + اختبار تباديل + اختبار ضبط عشوائي + استقرار
       طور عبر نصفين (effect_size.py، جديد).

KNOWN LIMITATION (بعد دفعة 100 سهم، راجع batch_20260717_223244): تصميم هذا
الملف يفترض أن فترة IMF **ثابتة عبر كامل نافذة الـ252 يوم** — فحص فعلي
(zero-crossing على AAPL IMF#1) أثبت العكس: الفترة الفعلية تتراوح 8-56 يومًا
عبر نفس النافذة رغم أن FFT يلخّصها برقم واحد (28 يوم). هذا نفس "نقطة الضعف
الموثّقة" في Understanding Timing Solution.md قسم 2.1 (الدورات الثابتة تفترض
طور/فترة ثابتين، لكن الواقع متغيّر — الحل الموثّق: Multiframe Spectrum/نوافذ
أقصر). النتيجة: R² شبه صفري حتى مع الانحدار التوافقي (fit_harmonic).

المسار المُعتمَد فعليًا الآن: rolling_harness.py (نوافذ متحركة قصيرة، فترة
محلية مستقلة لكل نافذة) — هذا الملف اتسيب EXPERIMENTAL/مرجعي (يوثّق ليه
النافذة الطويلة الواحدة فشلت)، ومازال يُستخدم لاختبارات تشخيصية سريعة.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

sys.path.insert(0, ".")  # نفس نمط lab_spectral_features.py __main__ — يسمح بالتشغيل المباشر من جذر المشروع

from full_universe_analysis import build_local_ticker_index, load_local_history
from gann_astrology import get_planet_longitude
from lab_spectral_features import emd_decompose, fft_cycle_features, wavelet_denoise

from lab_stats import bonferroni_alpha

from ai_catch_win_engine.effect_size import (
    check_harmonic_stability_split_half,
    permutation_test_harmonic,
    random_control_test_harmonic,
    fit_harmonic,
)
from ai_catch_win_engine.known_cycles import CycleMatch, build_known_cycles_table, match_period_to_known_cycles

DEFAULT_LOOKBACK = 252  # نفس lab_spectral_features.DEFAULT_LOOKBACK — سنة تداول تقريبًا


def _synodic_longitude_series(planet_a: str, planet_b: str, dates: list[date]) -> pd.Series:
    """
    خط طول "زاوية الفصل" بين كوكبين (0-360، بيلف حوالين نفسه بمعدل الدورة
    التقارنية) — الفرق بين خطي الطول الجيوسنتريين الحقيقيين، وليس تقريبًا.
    مستخدَم لما المطابقة تكون على دورة synodic (زوج) بدل sidereal (كوكب مفرد).
    """
    values = []
    for d in dates:
        lon_a = get_planet_longitude(planet_a, d)
        lon_b = get_planet_longitude(planet_b, d)
        values.append((lon_a - lon_b) % 360)
    return pd.Series(values, index=pd.DatetimeIndex(dates))


def _longitude_series_for_match(match: CycleMatch, dates: list[date]) -> pd.Series:
    """يبني سلسلة خط الطول اليومية المناسبة لنوع المطابقة (كوكب مفرد أو زوج)."""
    if match.cycle.kind == "sidereal":
        values = [get_planet_longitude(match.cycle.label, d) for d in dates]
        return pd.Series(values, index=pd.DatetimeIndex(dates))
    planet_a, _, rest = match.cycle.label.partition("-")
    planet_b = rest.replace(" synodic", "")
    return _synodic_longitude_series(planet_a, planet_b, dates)


@dataclass(frozen=True)
class MiniExperimentResult:
    ticker: str
    imf_index: int
    imf_period_days: float
    matched_cycle_label: str
    matched_cycle_error_pct: float
    beta_points_per_degree: float
    beta_r_squared: float
    permutation_p_value: float
    random_control_p_value: float
    stable_across_halves: bool
    phase_diff_deg: float
    n_observations: int
    passes_all_gates: bool


def _evaluate_one_imf(imf_series: pd.Series, imf_index: int, ticker: str,
                       max_period_error_pct: float, alpha: float,
                       max_phase_diff_deg: float,
                       rng_seed: int) -> MiniExperimentResult | None:
    """
    يقيّم IMF واحد بعينه: فترة → مطابقة فلكية → انحدار توافقي (harmonic) →
    كل بوابات القبول. راجع docstring effect_size.py لسبب استخدام الانحدار
    التوافقي بدل fit_beta الأصلية (فروق يومية) اللي فشلت في الدفعة الأولى
    (100 سهم، R² متوسط 0.016 فقط).
    """
    fft_on_imf = fft_cycle_features(imf_series)
    if fft_on_imf.dominant_period_days is None:
        return None

    matches = match_period_to_known_cycles(fft_on_imf.dominant_period_days,
                                            max_error_pct=max_period_error_pct)
    if not matches:
        return None

    best_match = matches[0]
    dates = [ts.date() for ts in imf_series.index]
    longitude = _longitude_series_for_match(best_match, dates)

    wave_level = imf_series.to_numpy()
    theta_rad = np.radians(longitude.to_numpy())

    try:
        fit = fit_harmonic(wave_level, theta_rad)
        perm_result = permutation_test_harmonic(wave_level, theta_rad, rng_seed=rng_seed)
        control_result = random_control_test_harmonic(wave_level, n_points=len(wave_level), rng_seed=rng_seed)
        stability = check_harmonic_stability_split_half(wave_level, theta_rad,
                                                          max_phase_diff_deg=max_phase_diff_deg)
    except ValueError:
        return None

    stable = stability.phase_diff_deg <= max_phase_diff_deg
    passes_all_gates = (
        perm_result.p_value < alpha
        and control_result.p_value >= alpha  # الضبط العشوائي المفروض ما يبقاش دالًا
        and stable
    )

    return MiniExperimentResult(
        ticker=ticker,
        imf_index=imf_index,
        imf_period_days=fft_on_imf.dominant_period_days,
        matched_cycle_label=best_match.cycle.label,
        matched_cycle_error_pct=best_match.error_pct,
        beta_points_per_degree=fit.beta_points_per_degree,
        beta_r_squared=fit.r_squared,
        permutation_p_value=perm_result.p_value,
        random_control_p_value=control_result.p_value,
        stable_across_halves=stable,
        phase_diff_deg=stability.phase_diff_deg,
        n_observations=fit.n_observations,
        passes_all_gates=passes_all_gates,
    )


def _default_alpha() -> float:
    """
    Bonferroni عبر عدد الدورات الفلكية المعروفة كلها (كل كوكب مفرد + كل زوج
    synodic) — نفس مبدأ lab_stats.bonferroni_alpha ونفس السبب: بمقارنة فترة
    IMF واحدة ضد عشرات الدورات المرشّحة دفعة واحدة (match_period_to_known_cycles
    بتفحصهم كلهم)، احتمال تطابق واحد منهم صدفة بحتة يكبر مع عددهم، فعتبة
    الدلالة الافتراضية (0.05) المستخدمة من غير تصحيح هتنتج إيجابيات كاذبة
    كتير جدًا عبر عيّنة أسهم كبيرة.
    """
    n_cycles = len(build_known_cycles_table(include_synodic_pairs=True))
    return bonferroni_alpha(n_cycles)


def run_mini_experiment(ticker: str, lookback: int = DEFAULT_LOOKBACK,
                         max_period_error_pct: float = 10.0,
                         alpha: float | None = None, max_phase_diff_deg: float = 45.0,
                         rng_seed: int = 42) -> list[MiniExperimentResult]:
    """
    ينفّذ التجربة المصغّرة كاملة على تيكر واحد، لكل الـ IMFs المستخرجة (مش
    الأول بس — الموجات الأبطأ (IMF الثاني/الثالث...) أقرب فعليًا لفترات
    الكواكب الحقيقية من IMF الأول اللي غالبًا ضوضاء عالية التردد). يرجّع قائمة
    فارغة (بدل استثناء) لو مفيش بيانات كفاية أو مفيش أي IMF عنده مطابقة كوكبية
    ضمن العتبة — نتيجة سلبية صريحة، مش قيمة مموّهة (نفس مبدأ المشروع الثابت
    في CLAUDE.md).

    alpha=None (الافتراضي) بيستخدم عتبة مُصحَّحة بـ Bonferroni عبر كل الدورات
    الفلكية المعروفة (_default_alpha) بدل 0.05 الخام — مرّر قيمة صراحة فقط لو
    قاصد تجاهل التصحيح لسبب محدد (مثلاً فحص تشخيصي سريع).
    """
    if alpha is None:
        alpha = _default_alpha()
    local_index = build_local_ticker_index()
    hist = load_local_history(ticker, local_index)
    if hist is None or len(hist) < lookback + 10:
        print(f"ai_catch_win_engine: مفيش بيانات محلية كفاية لـ {ticker} "
              f"(محتاج {lookback + 10} صف على الأقل).")
        return []

    close = hist["Close"].iloc[-lookback:]
    denoised = wavelet_denoise(close)

    emd_result = emd_decompose(denoised)
    if emd_result.n_imfs < 1:
        print(f"ai_catch_win_engine: EMD مرجّعش أي IMF لـ {ticker}.")
        return []

    results: list[MiniExperimentResult] = []
    # آخر IMF هو الـ residual/trend (أقل تردد جدًا، عمليًا اتجاه لا دورة) —
    # مُستبعد هنا لأنه مش موجة قابلة لقياس فترة/طور بمعنى دوري حقيقي.
    for i in range(emd_result.n_imfs - 1):
        imf_series = pd.Series(emd_result.imfs[i], index=close.index)
        result = _evaluate_one_imf(imf_series, i, ticker, max_period_error_pct, alpha,
                                    max_phase_diff_deg, rng_seed)
        if result is not None:
            results.append(result)
        else:
            print(f"ai_catch_win_engine: {ticker} IMF #{i} — لا مطابقة فلكية ضمن هامش "
                  f"{max_period_error_pct}% أو بيانات غير كافية.")

    return results


def _print_result(result: MiniExperimentResult) -> None:
    verdict = "✅ اجتاز كل البوابات" if result.passes_all_gates else "❌ لم يجتز"
    print(f"\n=== {result.ticker} — IMF #{result.imf_index} ===")
    print(f"  فترة IMF المكتشفة: {result.imf_period_days:.2f} يوم")
    print(f"  أقرب مطابقة فلكية: {result.matched_cycle_label} "
          f"(خطأ {result.matched_cycle_error_pct:.2f}%)")
    print(f"  beta = {result.beta_points_per_degree:.4f} نقطة/درجة "
          f"(R²={result.beta_r_squared:.3f}, n={result.n_observations})")
    print(f"  permutation p-value: {result.permutation_p_value:.4f}")
    print(f"  random-control p-value: {result.random_control_p_value:.4f} "
          f"(المفروض ≥ 0.05 — يعني مفيش إشارة زائفة من المنهجية نفسها)")
    print(f"  استقرار الطور عبر نصفين: {'نعم' if result.stable_across_halves else 'لا'} "
          f"(فرق الطور={result.phase_diff_deg:.1f}°)")
    print(f"  الحكم النهائي: {verdict}")


if __name__ == "__main__":
    ticker_arg = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    outcomes = run_mini_experiment(ticker_arg)
    if not outcomes:
        print(f"\nai_catch_win_engine: مفيش أي IMF لـ {ticker_arg} عنده مطابقة فلكية قابلة للاختبار.")
    for outcome in outcomes:
        _print_result(outcome)
