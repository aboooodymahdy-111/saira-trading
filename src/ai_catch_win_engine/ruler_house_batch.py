"""
ai_catch_win_engine/ruler_house_batch.py — اختبار "الحاكم قوي البيت" (توجيه عبده
2026-07-18): بدل تثبيت برج الطالع (same_ascendant_batch.py)، هنا معيار
الاختيار مستقل عن البرج تمامًا — أي سهم يكون **الكوكب الحاكم لبرج طالعه
واقعًا فعليًا في البيت الأول أو العاشر** من خريطته (Equal House، راجع
birth_chart.house_of_longitude) — البيتان الأقوى تأثيرًا تقليديًا (الذات/
الهوية، والمهنة/المكانة العامة).

**عكس اتجاه القياس (طلب عبده الصريح، بخلاف aspect_index.py)**: هناك
الحاكم كان *متحركًا* (transit) وبقية الكواكب *ثابتة* (natal). هنا: **الحاكم
نفسه ثابت (natal، عند لحظة الميلاد)**، وبقية الستة الكواكب الكلاسيكية
*متحركة* (transit) تشكّل اتصالات معه بمرور الوقت — الأقرب لكيفية استخدام
الاتصالات (transits) في التنجيم التقليدي عمومًا (الكوكب المتحرك "يزور"
نقطة ثابتة في الخريطة).

**تحدٍّ منهجي**: كل سهم في هذه المجموعة له حاكم مختلف (زحل/الشمس/عطارد/
الزهرة/القمر/المشتري) بسرعات حركة مختلفة جذريًا — لا يمكن نافذة واحدة
"طبيعية" للجميع بنفس الطريقة المستخدمة سابقًا (same_ascendant_batch، حيث
كل الأسهم اختُبرت ضد **نفس** الكوكب). عبده طلب اختبار **كلا الطريقتين**:
  1. `run_fixed_window()`: نافذة زمنية واحدة موحّدة لكل الأسهم (نفس تاريخ
     البداية/النهاية للجميع، بغض النظر عن حاكم كل سهم) — الأقرب لمنطق
     "لحظة سوقية واحدة تُختبر عبر عدة خرائط مختلفة".
  2. `run_custom_window()`: لكل سهم نافذة بطول مخصص (N دورة لحاكمه هو
     تحديدًا) — يحترم اختلاف سرعة كل حاكم، لكن يعني كل سهم يُختبر عبر فترة
     تاريخية مختلفة عن الآخر.
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, ".")

from ethical_screen import get_sector_and_industry
from full_universe_analysis import build_local_ticker_index, load_local_history
from lab_stats import bonferroni_alpha

from ai_catch_win_engine.aspect_index import CLASSICAL_SEVEN, natal_longitudes_for_ticker
from ai_catch_win_engine.birth_chart import compute_ascendant, house_of_longitude
from ai_catch_win_engine.natal_dates import filter_suspicious_natal_dates
from ai_catch_win_engine.planet_isolation import SLOW_PLANETS, recommended_window_days
from ai_catch_win_engine.same_ascendant_batch import CANDIDATE_POOL, MANUALLY_EXCLUDED
from ai_catch_win_engine.effect_size import fit_harmonic, permutation_test_harmonic, random_control_test_harmonic
from gann_astrology import get_planet_longitude
import numpy as np

OUTPUT_ROOT = Path("../runs/ai_catch_win_engine")

# دورة الكواكب السبعة الكلاسيكية (أيام سيدرالية) — لحساب طول نافذة مخصصة
# لكل حاكم (run_custom_window)، ولحساب alpha الموحّد (تصحيح Bonferroni عبر
# 7 كواكب كلاسيكية ممكنة كحاكم، لا 6 SLOW_PLANETS فقط — كل الكواكب السبعة
# قابلة لتكون حاكمًا هنا، بخلاف planet_isolation.py حيث فقط البطيئة تُختبر).
from ai_catch_win_engine.known_cycles import SIDEREAL_PERIOD_DAYS

CLASSICAL_PERIOD_DAYS = {
    "saturn": SIDEREAL_PERIOD_DAYS["saturn"], "jupiter": SIDEREAL_PERIOD_DAYS["jupiter"],
    "mars": SIDEREAL_PERIOD_DAYS["mars"], "venus": SIDEREAL_PERIOD_DAYS["venus"],
    "sun": 365.25, "mercury": SIDEREAL_PERIOD_DAYS["mercury"], "moon": 27.32,
}


def find_ruler_powerful_tickers(min_group_size: int = 6) -> dict[str, dict]:
    """
    يفحص كل مرشّح صالح أخلاقيًا وبتاريخ ميلاد موثوق: هل حاكم برج طالعه واقع
    فعليًا في البيت الأول أو العاشر (Equal House)؟ يرجّع {ticker: {natal_date,
    ascendant_sign, ruler, ruler_house}} لكل من حقق الشرط.
    """
    from ethical_screen import BDS_EXCLUDED_TICKERS

    idx = build_local_ticker_index()
    candidates = [t for t in CANDIDATE_POOL
                  if t not in MANUALLY_EXCLUDED and t not in BDS_EXCLUDED_TICKERS and t in idx]
    clean, excluded = filter_suspicious_natal_dates(candidates)
    print(f"تواريخ ميلاد موثوقة: {len(clean)}/{len(candidates)}")

    result = {}
    for t, natal_date in clean.items():
        asc = compute_ascendant(natal_date)
        ruler_lon = get_planet_longitude(asc.ruling_planet, natal_date)
        ruler_house = house_of_longitude(ruler_lon, asc.ascendant_longitude)
        if ruler_house in (1, 10):
            result[t] = {
                "natal_date": natal_date, "ascendant_sign": asc.ascendant_sign,
                "ruling_planet": asc.ruling_planet, "ruler_house": ruler_house,
                "ascendant_longitude": asc.ascendant_longitude,
            }

    print(f"{len(result)} سهم لديهم الحاكم نفسه في البيت 1 أو 10")
    return result


def _measure_one(ticker: str, ruler: str, natal_date: date, ascendant_longitude: float,
                  window_start: date, window_end: date, alpha: float, rng_seed: int = 42) -> dict | None:
    """
    ينحدر توافقيًا مستوى السعر (منزوع الاتجاه) على موقع الحاكم transit
    النسبي لطالع السهم — نفس منهجية planet_isolation.measure_window_effect
    بالضبط، لكن الحاكم هنا مختلف لكل سهم (مش كوكب واحد ثابت للجميع).
    """
    idx = build_local_ticker_index()
    hist = load_local_history(ticker, idx)
    if hist is None:
        return None
    win = hist.loc[str(window_start):str(window_end)]
    if len(win) < 30:
        return None

    close = win["Close"]
    trend = np.polyval(np.polyfit(np.arange(len(close)), close.to_numpy(), deg=1), np.arange(len(close)))
    detrended = close.to_numpy() - trend

    dates = [ts.date() for ts in close.index]
    longitude = np.array([get_planet_longitude(ruler, d) for d in dates])
    transit_position = (longitude - ascendant_longitude) % 360
    theta_rad = np.radians(transit_position)

    try:
        fit = fit_harmonic(detrended, theta_rad)
        perm_result = permutation_test_harmonic(detrended, theta_rad, n_shifts=300, rng_seed=rng_seed)
        control_result = random_control_test_harmonic(detrended, n_points=len(detrended),
                                                        n_shifts=300, rng_seed=rng_seed)
    except ValueError:
        return None

    passes_gates = perm_result.p_value < alpha and control_result.p_value >= alpha
    return {
        "ticker": ticker, "ruling_planet": ruler, "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(), "n_days": len(dates),
        "r_squared": round(fit.r_squared, 4),
        "permutation_p_value": round(perm_result.p_value, 5),
        "random_control_p_value": round(control_result.p_value, 5),
        "passes_gates": passes_gates,
    }


def run_fixed_window(members: dict[str, dict], window_days: int = 561) -> pd.DataFrame:
    """طريقة 1: نافذة موحّدة (أحدث window_days يوم، بغض النظر عن حاكم كل سهم)."""
    alpha = bonferroni_alpha(len(CLASSICAL_PERIOD_DAYS))
    window_end = date.today()
    window_start = window_end - timedelta(days=window_days - 1)
    print(f"\n=== نافذة موحّدة: {window_start} إلى {window_end} ({window_days} يوم) ===")

    rows = []
    for t, info in members.items():
        hist_start = load_local_history(t, build_local_ticker_index())
        if hist_start is None or hist_start.index[0].date() > window_start:
            print(f"  {t}: مستبعد (تاريخه المحلي أحدث من بداية النافذة)")
            continue
        result = _measure_one(t, info["ruling_planet"], info["natal_date"], info["ascendant_longitude"],
                               window_start, window_end, alpha)
        if result is None:
            continue
        try:
            sector, _ = get_sector_and_industry(t)
        except Exception:
            sector = "unknown"
        result["sector"] = sector
        result["ascendant_sign"] = info["ascendant_sign"]
        result["ruler_house"] = info["ruler_house"]
        verdict = "PASS" if result["passes_gates"] else "fail"
        print(f"  {t} ({info['ascendant_sign']}, ruler={info['ruling_planet']}@house{info['ruler_house']}): "
              f"R²={result['r_squared']:.3f}, perm p={result['permutation_p_value']:.4f}, "
              f"control p={result['random_control_p_value']:.4f} — {verdict}")
        rows.append(result)
    return pd.DataFrame(rows)


def run_custom_window(members: dict[str, dict], n_cycles: float = 2.5) -> pd.DataFrame:
    """طريقة 2: نافذة مخصصة لكل سهم (N دورة لحاكمه هو تحديدًا)، تنتهي بأحدث تاريخ."""
    alpha = bonferroni_alpha(len(CLASSICAL_PERIOD_DAYS))
    print(f"\n=== نوافذ مخصصة لكل حاكم ({n_cycles} دورة) ===")

    rows = []
    idx = build_local_ticker_index()
    for t, info in members.items():
        ruler = info["ruling_planet"]
        window_days = int(CLASSICAL_PERIOD_DAYS[ruler] * n_cycles)
        window_end = date.today()
        window_start = window_end - timedelta(days=window_days - 1)

        hist = load_local_history(t, idx)
        if hist is None or hist.index[0].date() > window_start:
            window_start = hist.index[0].date() if hist is not None else window_start
            print(f"  {t}: نافذة {window_days} يوم أطول من التاريخ المتاح — استُخدم كامل التاريخ المتاح بدلاً")

        result = _measure_one(t, ruler, info["natal_date"], info["ascendant_longitude"],
                               window_start, window_end, alpha)
        if result is None:
            continue
        try:
            sector, _ = get_sector_and_industry(t)
        except Exception:
            sector = "unknown"
        result["sector"] = sector
        result["ascendant_sign"] = info["ascendant_sign"]
        result["ruler_house"] = info["ruler_house"]
        verdict = "PASS" if result["passes_gates"] else "fail"
        print(f"  {t} ({info['ascendant_sign']}, ruler={ruler}@house{info['ruler_house']}, "
              f"window={window_days}d): R²={result['r_squared']:.3f}, "
              f"perm p={result['permutation_p_value']:.4f}, control p={result['random_control_p_value']:.4f} — {verdict}")
        rows.append(result)
    return pd.DataFrame(rows)


def _summarize(results: pd.DataFrame, label: str) -> str:
    if results.empty:
        return f"{label}: مفيش نتائج."
    n = len(results)
    n_passed = int(results["passes_gates"].sum())
    from scipy import stats as scipy_stats
    alpha = bonferroni_alpha(len(CLASSICAL_PERIOD_DAYS))
    chance_p = alpha * (1 - alpha)
    binom_p = scipy_stats.binomtest(n_passed, n, chance_p, alternative="greater").pvalue
    return (f"{label}\nإجمالي: {n}, عبروا: {n_passed} ({100*n_passed/n:.1f}%)\n"
            f"binomial test (نسبة العبور مقابل الصدفة): p={binom_p:.4f}\n"
            f"R² متوسط: {results['r_squared'].mean():.4f}\n\n" + results.to_string(index=False))


def main() -> None:
    members = find_ruler_powerful_tickers()

    fixed_results = run_fixed_window(members)
    custom_results = run_custom_window(members)

    run_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = OUTPUT_ROOT / f"ruler_house_{run_timestamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    fixed_summary = _summarize(fixed_results, "=== نافذة موحّدة ===")
    custom_summary = _summarize(custom_results, "=== نوافذ مخصصة ===")

    if not fixed_results.empty:
        fixed_results.to_csv(out_dir / "fixed_window_results.csv", index=False)
    if not custom_results.empty:
        custom_results.to_csv(out_dir / "custom_window_results.csv", index=False)
    (out_dir / "summary.md").write_text(fixed_summary + "\n\n" + custom_summary, encoding="utf-8")

    print("\n" + fixed_summary)
    print("\n" + custom_summary)
    print(f"\nWrote output to {out_dir.resolve()}")


if __name__ == "__main__":
    main()
