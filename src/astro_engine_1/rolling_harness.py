"""
astro_engine_1/rolling_harness.py — النسخة المُعتمَدة الثانية من التجربة
المصغّرة، تصحّح الخلل المكتشف فعليًا في harness.py: فترة IMF **ليست ثابتة**
عبر نافذة طويلة (252 يوم) — فحص zero-crossing حقيقي على AAPL IMF#1 أظهر فترة
فعلية متراوحة 8-56 يوم رغم أن FFT على النافذة الكاملة يلخّصها برقم واحد (28
يوم). هذا نفس "نقطة الضعف الموثّقة" في Understanding Timing Solution.md قسم
2.1 (Multiframe Spectrum كحل رسمي موصى به لعدم ثبات الفترة/الطور).

التصميم هنا: تقسيم تاريخ السهم لنوافذ متحركة متداخلة قصيرة (WINDOW_DAYS، خطوة
STEP_DAYS)، تشغيل EMD+FFT+harmonic بشكل مستقل على كل نافذة (فترة/طور محليان
خاصان بها، لا افتراض ثبات عبر كل التاريخ)، ثم تجميع النتائج عبر النوافذ:
هل نفس الدورة الفلكية (كوكب/زوج) تظهر كأفضل مطابقة بثبات عبر أغلب النوافذ
لنفس السهم؟ هذا أقرب لمنهجية "Cycles Activity Diagram" الموثّقة في TS (يبيّن
"عمر" الدورة عبر الزمن) من افتراض دورة واحدة صالحة للتاريخ كله.

القيود: WINDOW_DAYS أقصر يعني EMD أقل موثوقية إحصائيًا (بيانات أقل)، وMIN_
OBSERVATIONS في fit_harmonic (30) يضع حدًا أدنى صارمًا — هذا trade-off مقصود
(نفس المفاضلة الموثّقة في TS قسم 5.6 لـ Basic Interval: "كبير بما يكفي لالتقاط
الدورة، لكن ليس كبيرًا جدًا").
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

sys.path.insert(0, ".")

from full_universe_analysis import build_local_ticker_index, load_local_history
from lab_spectral_features import emd_decompose, fft_cycle_features, wavelet_denoise
from lab_stats import bonferroni_alpha

from astro_engine_1.effect_size import fit_harmonic, permutation_test_harmonic, random_control_test_harmonic
from astro_engine_1.harness import _longitude_series_for_match
from astro_engine_1.known_cycles import build_known_cycles_table, match_period_to_known_cycles

WINDOW_DAYS = 60      # قريب من "Basic Interval" الموصى به في TS لدورات قصيرة/متوسطة المدى
STEP_DAYS = 20         # تداخل 2/3 بين نافذة وأخرى — كثافة كافية لرصد استقرار/تلاشي الدورة
MIN_TOTAL_HISTORY = 252  # سنة تداول على الأقل عشان تدّي عدة نوافذ متتالية ذات معنى


def _default_alpha() -> float:
    n_cycles = len(build_known_cycles_table(include_synodic_pairs=True))
    return bonferroni_alpha(n_cycles)


@dataclass(frozen=True)
class WindowResult:
    ticker: str
    window_start: date
    window_end: date
    imf_index: int
    imf_period_days: float
    matched_cycle_label: str
    period_error_pct: float
    beta_points_per_degree: float
    r_squared: float
    permutation_p_value: float
    random_control_p_value: float
    passes_gates: bool  # permutation + control بس (بلا استقرار نصفين — النافذة نفسها قصيرة أصلاً)


def _evaluate_window(close_window: pd.Series, ticker: str, max_period_error_pct: float,
                      alpha: float, rng_seed: int) -> list[WindowResult]:
    """يشغّل EMD+FFT+harmonic على نافذة واحدة قصيرة، لكل IMF فيها (عدا الـresidual)."""
    try:
        denoised = wavelet_denoise(close_window)
        emd_result = emd_decompose(denoised, max_imfs=4)  # نافذة قصيرة -> IMFs أقل منطقيًا
    except ValueError:
        return []

    results: list[WindowResult] = []
    for i in range(max(emd_result.n_imfs - 1, 0)):
        imf_series = pd.Series(emd_result.imfs[i], index=close_window.index)
        fft_result = fft_cycle_features(imf_series, min_period_days=3)
        if fft_result.dominant_period_days is None:
            continue

        matches = match_period_to_known_cycles(fft_result.dominant_period_days,
                                                max_error_pct=max_period_error_pct)
        if not matches:
            continue

        best_match = matches[0]
        dates = [ts.date() for ts in imf_series.index]
        longitude = _longitude_series_for_match(best_match, dates)
        wave_level = imf_series.to_numpy()
        theta_rad = np.radians(longitude.to_numpy())

        try:
            fit = fit_harmonic(wave_level, theta_rad)
            perm_result = permutation_test_harmonic(wave_level, theta_rad, n_shifts=200, rng_seed=rng_seed)
            control_result = random_control_test_harmonic(wave_level, n_points=len(wave_level),
                                                            n_shifts=200, rng_seed=rng_seed)
        except ValueError:
            continue

        passes_gates = perm_result.p_value < alpha and control_result.p_value >= alpha

        results.append(WindowResult(
            ticker=ticker,
            window_start=close_window.index[0].date(),
            window_end=close_window.index[-1].date(),
            imf_index=i,
            imf_period_days=fft_result.dominant_period_days,
            matched_cycle_label=best_match.cycle.label,
            period_error_pct=best_match.error_pct,
            beta_points_per_degree=fit.beta_points_per_degree,
            r_squared=fit.r_squared,
            permutation_p_value=perm_result.p_value,
            random_control_p_value=control_result.p_value,
            passes_gates=passes_gates,
        ))
    return results


def run_rolling_experiment(ticker: str, window_days: int = WINDOW_DAYS, step_days: int = STEP_DAYS,
                            max_period_error_pct: float = 10.0, alpha: float | None = None,
                            rng_seed: int = 42) -> list[WindowResult]:
    """
    ينفّذ التجربة عبر كل النوافذ المتحركة لتيكر واحد. يرجّع قائمة مسطّحة لكل
    (نافذة, IMF) له مطابقة فلكية — التجميع/التلخيص (هل نفس الدورة تتكرر عبر
    نوافذ متعددة؟) بيصير في summarize_rolling_results تحت، مش هنا.
    """
    if alpha is None:
        alpha = _default_alpha()

    local_index = build_local_ticker_index()
    hist = load_local_history(ticker, local_index)
    if hist is None or len(hist) < MIN_TOTAL_HISTORY:
        print(f"astro_engine_1: مفيش بيانات محلية كفاية لـ {ticker} "
              f"(محتاج {MIN_TOTAL_HISTORY} صف على الأقل).")
        return []

    close = hist["Close"].iloc[-MIN_TOTAL_HISTORY:]
    n = len(close)

    all_results: list[WindowResult] = []
    start = 0
    while start + window_days <= n:
        window = close.iloc[start:start + window_days]
        all_results.extend(_evaluate_window(window, ticker, max_period_error_pct, alpha, rng_seed))
        start += step_days

    return all_results


@dataclass(frozen=True)
class CycleConsistency:
    ticker: str
    matched_cycle_label: str
    n_windows_matched: int
    n_windows_passed_gates: int
    mean_beta: float
    beta_sign_consistency: float  # نسبة النوافذ اللي إشارة beta فيها متفقة مع الإشارة الغالبة
    mean_r_squared: float


def summarize_rolling_results(results: list[WindowResult]) -> list[CycleConsistency]:
    """
    يجمّع نتائج كل النوافذ حسب الدورة الفلكية المُطابَقة: كم نافذة "شافت" نفس
    الدورة، كام منها اجتاز بوابتي permutation+control، وهل إشارة beta متسقة
    (نفس المنطق الجوهري لاستقرار النصفين في harness.py الأصلي، لكن هنا عبر N
    نوافذ مستقلة بدل نصفين فقط من نفس النافذة الطويلة).
    """
    if not results:
        return []

    df = pd.DataFrame([{
        "ticker": r.ticker, "matched_cycle_label": r.matched_cycle_label,
        "beta_points_per_degree": r.beta_points_per_degree, "r_squared": r.r_squared,
        "passes_gates": r.passes_gates,
    } for r in results])

    summaries = []
    for (ticker, cycle), group in df.groupby(["ticker", "matched_cycle_label"]):
        signs = np.sign(group["beta_points_per_degree"])
        dominant_sign = signs.mode().iloc[0] if not signs.mode().empty else 0
        sign_consistency = float((signs == dominant_sign).mean()) if dominant_sign != 0 else 0.0

        summaries.append(CycleConsistency(
            ticker=ticker,
            matched_cycle_label=cycle,
            n_windows_matched=len(group),
            n_windows_passed_gates=int(group["passes_gates"].sum()),
            mean_beta=float(group["beta_points_per_degree"].mean()),
            beta_sign_consistency=sign_consistency,
            mean_r_squared=float(group["r_squared"].mean()),
        ))

    return sorted(summaries, key=lambda c: (-c.n_windows_passed_gates, -c.n_windows_matched))


def _print_summary(ticker: str, summaries: list[CycleConsistency]) -> None:
    print(f"\n=== {ticker} — ملخص عبر النوافذ المتحركة ===")
    if not summaries:
        print("  مفيش أي دورة فلكية ظهرت في أي نافذة.")
        return
    for s in summaries[:10]:
        print(f"  {s.matched_cycle_label}: {s.n_windows_matched} نافذة شافتها، "
              f"{s.n_windows_passed_gates} اجتازت البوابات الإحصائية، "
              f"beta متوسط={s.mean_beta:.5f}, اتساق الإشارة={s.beta_sign_consistency:.0%}, "
              f"R² متوسط={s.mean_r_squared:.3f}")


if __name__ == "__main__":
    ticker_arg = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    window_results = run_rolling_experiment(ticker_arg)
    summary = summarize_rolling_results(window_results)
    _print_summary(ticker_arg, summary)
