"""
ai_catch_win_engine/effect_size.py — المرحلتان 4-5 من المنهجية (قياس β + التحقق من
الاستقرار). هنا قلب طلب عبده الأصلي: "كم نقطة سعرية يقابل 1 درجة من حركة هذا
الكوكب"، بإشارة موقّعة (يرفع/يخفض) وفاصل ثقة حقيقي — وليس فقط "هل الطور
متركّز" كما تفعل lab_planet_selection.py.

MAJOR REVISION (2026-07، بعد دفعة 100 سهم أولى): التصميم الأصلي (fit_beta على
delta_wave~delta_longitude اليومي) فشل بنيويًا — R² متوسط 0.016 عبر 104 IMF
مُختبَر، وهذا متوقَّع رياضيًا وليس فشل الفرضية نفسها: IMF موجة دورية (شبه
جيبية)، بينما delta_longitude شبه ثابت السرعة (خصوصًا للكواكب البطيئة) أو دوري
بفترة مختلفة (للقمر). فرق يومي خطي بين إشارتين لهما شكل دوري مختلف عن بعضهما
لا يلتقط علاقة دورية حقيقية حتى لو كانت موجودة فعلاً — مشكلة كان لازم تُكتشف
بالتجربة الفعلية، مش بالتفكير النظري فقط.

الحل: **انحدار توافقي (harmonic regression)** — بدل ربط التغيّر اليومي في
الموجة بالتغيّر اليومي في الزاوية، نربط *مستوى* الموجة نفسه بجيب/تجيب زاوية
الكوكب مباشرة:
    wave(t) ≈ A·cos(θ(t)) + B·sin(θ(t)) + C
حيث θ(t) = زاوية الكوكب/الزوج المُطابَق بالراديان. هذا يلتقط أي علاقة دورية
بغض النظر عن فرق الطور بين الموجتين (المشكلة الأساسية في fit_beta). السعة
R = √(A²+B²) تمثّل "أقصى انحراف في الموجة يمكن تفسيره بهذه الدورة الفلكية"،
وbeta_points_per_degree المُشتقة منها = R / (نصف مدى الدورة بالدرجات) —
"كم نقطة سعرية يقابل كل درجة" بمعنى السعة القصوى للتذبذب، وليس ميل خطي محلي.

fit_beta/permutation_test_beta الأصليتان (على delta) اتسابتا موجودتين تحت
كمرجع تاريخي موثّق (ليه فشلوا) ولاستخدامات تشخيصية مستقبلية محتملة، لكن
harmonic_fit/permutation_test_harmonic هما المسار المُعتمَد الآن فعليًا في
harness.py.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

N_SHIFTS_DEFAULT = 500


def wrap_delta_degrees(longitude: pd.Series) -> np.ndarray:
    """
    فرق يومي في خط الطول (0-360) مع فك التفاف صحيح عند عبور 360/0 — بدون هذا،
    قفزة من 359° إلى 1° (حركة حقيقية +2°) تُقرأ خطأ كـ -358°.
    """
    raw_diff = longitude.diff().to_numpy()
    wrapped = np.where(raw_diff > 180, raw_diff - 360, raw_diff)
    wrapped = np.where(wrapped < -180, wrapped + 360, wrapped)
    return wrapped


@dataclass(frozen=True)
class BetaFit:
    beta_points_per_degree: float
    intercept: float
    r_squared: float
    n_observations: int


def fit_beta(delta_wave: np.ndarray, delta_longitude_deg: np.ndarray) -> BetaFit:
    """
    OLS بسيط: delta_wave ≈ beta * delta_longitude_deg + intercept. الـ intercept
    مقصود هنا (مش صفر بالإجبار) — بيلتقط أي انجراف يومي ثابت في الموجة مش
    مرتبط بحركة الكوكب أصلاً (زي بقايا اتجاه لم يُزل بالكامل)، فـ beta يعكس
    فعليًا الحساسية للحركة الكوكبية فقط، مش يمتص انجرافًا غير متعلق بيها.
    """
    valid = ~(np.isnan(delta_wave) | np.isnan(delta_longitude_deg))
    x = delta_longitude_deg[valid]
    y = delta_wave[valid]
    n = len(x)
    if n < 30:
        raise ValueError(f"observations قليلة قوي بعد التنقية ({n}) — يحتاج 30 على الأقل.")

    design = np.column_stack([x, np.ones(n)])
    coeffs, residuals_sum, _, _ = np.linalg.lstsq(design, y, rcond=None)
    beta, intercept = float(coeffs[0]), float(coeffs[1])

    y_pred = design @ coeffs
    ss_res = float(np.sum((y - y_pred) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0

    return BetaFit(beta_points_per_degree=beta, intercept=intercept, r_squared=r_squared, n_observations=n)


@dataclass(frozen=True)
class BetaPermutationResult:
    observed_beta: float
    p_value: float
    n_shifts_used: int


def permutation_test_beta(delta_wave: np.ndarray, delta_longitude_deg: np.ndarray,
                           n_shifts: int = N_SHIFTS_DEFAULT,
                           rng_seed: int | None = None) -> BetaPermutationResult:
    """
    اختبار تباديل بالإزاحة الدائرية لمعامل beta نفسه (مش لنسبة تصنيف ثنائية
    زي lab_stats.permutation_significance) — لهذا اتكتبت دالة منفصلة بدل إعادة
    استخدام تلك الدالة مباشرة: هنا الكمية المُختبَرة معامل انحدار مستمر، مش
    فرق بين معدلين لمجموعتين مصنّفتين. السبب في اختيار الإزاحة الدائرية نفسه
    (بدل shuffle عادي) مطابق تمامًا لتبرير lab_stats.py: الاستقلالية الذاتية
    الطويلة في كل من السعر وحركة الكواكب تخلي أي اختبار "مستقل" عادي يبالغ في
    تقدير الدلالة — الإزاحة الدائرية تحافظ على بنية الارتباط الذاتي في
    delta_longitude_deg بينما تفكّ ارتباطها الزمني الحقيقي بـ delta_wave.
    """
    valid = ~(np.isnan(delta_wave) | np.isnan(delta_longitude_deg))
    y = delta_wave[valid]
    x = delta_longitude_deg[valid]
    n = len(x)
    if n < 30:
        raise ValueError(f"observations قليلة قوي بعد التنقية ({n}) — يحتاج 30 على الأقل.")

    observed_fit = fit_beta(y, x)
    observed_beta = observed_fit.beta_points_per_degree

    rng = np.random.default_rng(rng_seed)
    shifts = rng.integers(1, n, size=n_shifts)

    more_extreme = 0
    valid_shifts = 0
    for shift in shifts:
        shifted_x = np.roll(x, shift)
        try:
            shifted_fit = fit_beta(y, shifted_x)
        except ValueError:
            continue
        valid_shifts += 1
        if abs(shifted_fit.beta_points_per_degree) >= abs(observed_beta):
            more_extreme += 1

    p_value = (more_extreme + 1) / (valid_shifts + 1) if valid_shifts else 1.0
    return BetaPermutationResult(observed_beta=observed_beta, p_value=p_value, n_shifts_used=valid_shifts)


@dataclass(frozen=True)
class StabilitySplitResult:
    beta_first_half: float
    beta_second_half: float
    same_sign: bool
    n_first_half: int
    n_second_half: int


def check_stability_split_half(delta_wave: np.ndarray, delta_longitude_deg: np.ndarray) -> StabilitySplitResult:
    """
    قسم 5.7/القسم 4 من المنهجية: تقسيم العيّنة لنصفين زمنيين والتأكد إن beta
    نفس الإشارة في الاثنين. beta موجب بالمتوسط الكلي لكن سالب في النصف الثاني
    = مرفوض (نفس مصير موديل "Adv Seasonal" الموثّق في Understanding Timing
    Solution.md قسم 5.7)، حتى لو المتوسط الكلي بيبدو "مقبول بالكاد".
    """
    valid = ~(np.isnan(delta_wave) | np.isnan(delta_longitude_deg))
    y = delta_wave[valid]
    x = delta_longitude_deg[valid]
    n = len(x)
    mid = n // 2
    if mid < 30 or (n - mid) < 30:
        raise ValueError(f"مش كفاية observations لتقسيم نصفين ({n} إجمالي) — يحتاج 60 على الأقل.")

    first = fit_beta(y[:mid], x[:mid])
    second = fit_beta(y[mid:], x[mid:])
    same_sign = (first.beta_points_per_degree > 0) == (second.beta_points_per_degree > 0)

    return StabilitySplitResult(
        beta_first_half=first.beta_points_per_degree,
        beta_second_half=second.beta_points_per_degree,
        same_sign=same_sign,
        n_first_half=first.n_observations,
        n_second_half=second.n_observations,
    )


def random_control_test(delta_wave: np.ndarray, n_points: int,
                         n_shifts: int = N_SHIFTS_DEFAULT, rng_seed: int | None = None) -> BetaPermutationResult:
    """
    اختبار الضبط الموثّق رسميًا في Understanding Timing Solution.md (قسم
    10.19، "أمواج القمر"): استبدال حركة الكوكب الحقيقية بقيم عشوائية بالكامل
    (uniform 0-360، فرق يومي عشوائي) وإعادة نفس اختبار beta — لو النتيجة
    "المعنوية" لسه بتظهر مع بيانات عشوائية تمامًا، فالمشكلة في المنهجية نفسها
    (artifact)، مش في الكوكب. هذا اختبار إضافي فوق permutation_test_beta،
    مش بديل عنه — الاثنان مطلوبان معًا لقسم 4 من المنهجية.
    """
    rng = np.random.default_rng(rng_seed)
    random_longitude = rng.uniform(0, 360, size=n_points)
    random_delta = wrap_delta_degrees(pd.Series(random_longitude))
    return permutation_test_beta(delta_wave, random_delta, n_shifts=n_shifts, rng_seed=rng_seed)


# ---------------------------------------------------------------------------
# الانحدار التوافقي (harmonic regression) — المسار المُعتمَد فعليًا بعد فشل
# fit_beta على الفروق اليومية (راجع docstring الملف). كل الدوال تحت تاخد
# theta_rad (زاوية الكوكب/الزوج المُطابَق بالراديان، أي longitude بعد التحويل
# لـ2π/period_days*360 مش بالضرورة longitude الخام لو الدورة المُطابَقة synodic)
# مباشرة، مش delta.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class HarmonicFit:
    amplitude: float          # R = sqrt(A^2 + B^2) — أقصى انحراف بوحدة الموجة نفسها
    phase_rad: float          # الطور اللي بيحصل عنده أقصى قيمة موجبة
    beta_points_per_degree: float  # R / (360/2) — "نقطة/درجة" بمعنى السعة القصوى
    r_squared: float
    n_observations: int


def fit_harmonic(wave_level: np.ndarray, theta_rad: np.ndarray) -> HarmonicFit:
    """
    wave_level(t) ≈ A*cos(theta) + B*sin(theta) + C — انحدار خطي عادي على
    مُدخلات مُحوَّلة (cos/sin)، فبيفضل OLS بسيط رياضيًا رغم إنه بيلتقط علاقة
    دورية. R=sqrt(A^2+B^2) هو سعة أفضل موجة جيبية واحدة تفسّر wave_level بدلالة
    theta — تفسير مباشر: "أقصى فرق بين ذروة وقاع الموجة يمكن تفسيره حصريًا
    بموضع هذا الكوكب/الزوج ضمن دورته". beta_points_per_degree = R / 180 —
    السعة مقسومة على نصف مدى الدورة الكاملة (0-360°)، أي "نقطة سعرية تقريبية
    لكل درجة حركة" على فرض توزيع خطي للسعة عبر نصف الدورة (تقريب مقصود ومبسّط،
    مش قياس ميل لحظي دقيق زي fit_beta كانت تحاول — لكنه أكثر واقعية لأنه مبني
    فعلاً على علاقة موجودة بدل ميل شبه صفري نتيجة تصميم خاطئ).
    """
    valid = ~(np.isnan(wave_level) | np.isnan(theta_rad))
    y = wave_level[valid]
    theta = theta_rad[valid]
    n = len(y)
    if n < 30:
        raise ValueError(f"observations قليلة قوي بعد التنقية ({n}) — يحتاج 30 على الأقل.")

    design = np.column_stack([np.cos(theta), np.sin(theta), np.ones(n)])
    coeffs, _, _, _ = np.linalg.lstsq(design, y, rcond=None)
    a, b, c = (float(v) for v in coeffs)

    amplitude = float(np.hypot(a, b))
    phase = float(np.arctan2(b, a))
    beta = amplitude / 180.0

    y_pred = design @ coeffs
    ss_res = float(np.sum((y - y_pred) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0

    return HarmonicFit(amplitude=amplitude, phase_rad=phase, beta_points_per_degree=beta,
                        r_squared=r_squared, n_observations=n)


@dataclass(frozen=True)
class HarmonicPermutationResult:
    observed_amplitude: float
    p_value: float
    n_shifts_used: int


def permutation_test_harmonic(wave_level: np.ndarray, theta_rad: np.ndarray,
                               n_shifts: int = N_SHIFTS_DEFAULT,
                               rng_seed: int | None = None) -> HarmonicPermutationResult:
    """
    اختبار تباديل بالإزاحة الدائرية لسعة الانحدار التوافقي (amplitude=R، مش
    beta الخطي) — نفس مبرر permutation_test_beta بالضبط (الإزاحة الدائرية
    تحافظ على الارتباط الذاتي الطويل في theta_rad بينما تفكّ ارتباطه الزمني
    الحقيقي بـwave_level)، لكن الكمية المُختبَرة هنا R، لأنها الإحصائية
    الأساسية للانحدار التوافقي.
    """
    valid = ~(np.isnan(wave_level) | np.isnan(theta_rad))
    y = wave_level[valid]
    theta = theta_rad[valid]
    n = len(y)
    if n < 30:
        raise ValueError(f"observations قليلة قوي بعد التنقية ({n}) — يحتاج 30 على الأقل.")

    observed_fit = fit_harmonic(y, theta)
    observed_amplitude = observed_fit.amplitude

    rng = np.random.default_rng(rng_seed)
    shifts = rng.integers(1, n, size=n_shifts)

    more_extreme = 0
    valid_shifts = 0
    for shift in shifts:
        shifted_theta = np.roll(theta, shift)
        try:
            shifted_fit = fit_harmonic(y, shifted_theta)
        except ValueError:
            continue
        valid_shifts += 1
        if shifted_fit.amplitude >= observed_amplitude:  # amplitude >= 0 دايمًا، مفيش حاجة لـ abs()
            more_extreme += 1

    p_value = (more_extreme + 1) / (valid_shifts + 1) if valid_shifts else 1.0
    return HarmonicPermutationResult(observed_amplitude=observed_amplitude, p_value=p_value,
                                      n_shifts_used=valid_shifts)


@dataclass(frozen=True)
class HarmonicStabilitySplitResult:
    phase_first_half_deg: float
    phase_second_half_deg: float
    phase_diff_deg: float  # أصغر فرق زاوي بين الطورين (0-180) — الأقرب لصفر = أكثر استقرارًا
    amplitude_first_half: float
    amplitude_second_half: float
    n_first_half: int
    n_second_half: int


def check_harmonic_stability_split_half(wave_level: np.ndarray, theta_rad: np.ndarray,
                                         max_phase_diff_deg: float = 45.0) -> HarmonicStabilitySplitResult:
    """
    مكافئ check_stability_split_half لكن للانحدار التوافقي: بدل مقارنة إشارة
    beta (موجب/سالب)، نقارن *طور* أفضل موجة جيبية (phase_rad) بين النصفين —
    لو الطور اتقلب بشكل كبير (أكتر من max_phase_diff_deg)، فالعلاقة "الدورية"
    المُكتشفة غير مستقرة زمنيًا (نفس مبدأ قسم 5.7 من Understanding Timing
    Solution.md: علاقة تنعكس بين نصفين = غير موثوقة، حتى لو متوسطها الكلي جيد).
    """
    valid = ~(np.isnan(wave_level) | np.isnan(theta_rad))
    y = wave_level[valid]
    theta = theta_rad[valid]
    n = len(y)
    mid = n // 2
    if mid < 30 or (n - mid) < 30:
        raise ValueError(f"مش كفاية observations لتقسيم نصفين ({n} إجمالي) — يحتاج 60 على الأقل.")

    first = fit_harmonic(y[:mid], theta[:mid])
    second = fit_harmonic(y[mid:], theta[mid:])

    phase_diff_rad = abs(first.phase_rad - second.phase_rad) % (2 * np.pi)
    phase_diff_rad = min(phase_diff_rad, 2 * np.pi - phase_diff_rad)
    phase_diff_deg = float(np.degrees(phase_diff_rad))

    return HarmonicStabilitySplitResult(
        phase_first_half_deg=float(np.degrees(first.phase_rad)),
        phase_second_half_deg=float(np.degrees(second.phase_rad)),
        phase_diff_deg=phase_diff_deg,
        amplitude_first_half=first.amplitude,
        amplitude_second_half=second.amplitude,
        n_first_half=first.n_observations,
        n_second_half=second.n_observations,
    )


def random_control_test_harmonic(wave_level: np.ndarray, n_points: int,
                                  n_shifts: int = N_SHIFTS_DEFAULT,
                                  rng_seed: int | None = None) -> HarmonicPermutationResult:
    """مكافئ random_control_test للانحدار التوافقي — راجع docstring تلك الدالة."""
    rng = np.random.default_rng(rng_seed)
    random_theta = rng.uniform(0, 2 * np.pi, size=n_points)
    return permutation_test_harmonic(wave_level, random_theta, n_shifts=n_shifts, rng_seed=rng_seed)
