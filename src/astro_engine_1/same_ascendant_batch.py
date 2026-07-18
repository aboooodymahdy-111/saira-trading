"""
astro_engine_1/same_ascendant_batch.py — تصميم اختبار مختلف تمامًا عن
isolation_batch_runner.py، بتوجيه عبده الصريح (2026-07-18):

بدل عيّنة أسهم بأطالع مختلفة (كما في isolation_batch_runner، حيث الهدف فصل
"تأثير فلكي حقيقي خاص بكل خريطة" عن "ظرف سوقي عام")، هنا الهدف معاكس تمامًا:
تثبيت البرج الطالع نفسه عبر كل العيّنة (كل الأسهم لها نفس البيت الأول)، وقياس
تأثير كوكب واحد عبر **نافذة زمنية مشتركة واحدة** (لا 5 نوافذ مستقلة لكل سهم).
هذا يعزل سؤالًا مختلفًا: "هل أسهم تتشارك نفس الطالع تتفق أكثر في استجابتها
لنفس حركة الكوكب في نفس التوقيت الفعلي؟" — بدل "هل نفس السهم يستجيب لكوكبه
عبر نوافذ مختلفة؟" كما في isolation_batch_runner.

فرقان تصميميان صريحان عن isolation_batch_runner (كلاهما بطلب عبده المباشر):
  1. **لا شرط أقل كثافة أسبكتات هنا** — النافذة الزمنية تُختار فقط بحسب
     تغطية أكبر عدد أسهم (أحدث دورة/نصف/ربع ممكن)، بغض النظر عن كثافة
     الاتصالات الفلكية في تلك الفترة. isolation_batch_runner كان يبحث عمدًا
     عن أنقى نافذة (`find_lowest_density_windows`) — هنا هذا الشرط مُسقَط
     صراحةً، فالأولوية لتثبيت الطالع لا لتنقية الإشارة من تشويش كواكب أخرى.
  2. **نافذة واحدة مشتركة، لا نوافذ مستقلة لكل سهم** — كل الأسهم في المجموعة
     تُقاس عبر بالضبط نفس نطاق التاريخ (بخلاف isolation_batch_runner حيث كل
     نافذة "أنقى" مستقلة عن أي سهم بعينه لكنها لا تزال 5 نوافذ منفصلة تُختبر
     كل سهم عبرها كلها).

**اعتماد جوهري على natal_dates.py**: هذا الاختبار يعتمد بالكامل على تواريخ
ميلاد حقيقية موثوقة (لا تقريب من أرشيف محلي) — فحص فعلي (راجع
natal_dates.py) اكتشف أن العيّنة الأصلية المتنوعة قطاعيًا
(isolation_batch_runner.DIVERSIFIED_SAMPLE_TICKERS) بها عشرات الأسهم
لا يمكن الوثوق بتاريخ ميلادها (حدود أرشيف تقنية متعددة: 1962-01-02،
1972-06-01، 1980-03-17 — حتى في yfinance نفسه لا فقط البيانات المحلية).
لذلك حجم أي مجموعة "برج واحد" هنا محدود بعدد الأسهم ذات تاريخ ميلاد موثوق
فرديًا ضمن نفس البرج — قد يكون صغيرًا (8-10 أسهم)، وهذا قيد بيانات حقيقي
موثّق، لا اختيار تصميمي.
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, ".")

from ethical_screen import get_sector_and_industry
from full_universe_analysis import build_local_ticker_index, load_local_history
from gann_astrology import get_planet_longitude
from lab_stats import bonferroni_alpha

from astro_engine_1.birth_chart import compute_ascendant
from astro_engine_1.effect_size import (fit_harmonic, permutation_test_harmonic,
                                          random_control_test_harmonic)
from astro_engine_1.natal_dates import filter_suspicious_natal_dates
from astro_engine_1.planet_isolation import SLOW_PLANETS, recommended_window_days

OUTPUT_ROOT = Path("../runs/astro_engine_1")

# مرشحو العيّنة: القائمة المتنوعة قطاعيًا الأصلية + إضافات (شركات مُدرَجة بعد
# 1970 من قطاعات لم تكن ممثَّلة كفاية، لزيادة فرصة إيجاد مجموعة برج كبيرة
# بما يكفي بعد استبعاد كل تاريخ ميلاد مشبوه) — كلها مفلترة يدويًا مقابل
# ethical_screen.BDS_EXCLUDED_TICKERS ومستبعدة يدويًا لأي دفاع/بنوك معروفة.
CANDIDATE_POOL = [
    "IBM", "XRX", "XOM", "COP", "FCX", "AA", "NUE", "PG", "CL", "KMB", "MO",
    "PM", "ADM", "HSY", "GIS", "CAG", "WMT", "COST", "TGT", "HD", "LOW",
    "NKE", "SBUX", "CMG", "CAT", "MMM", "DD", "DOW", "LIN", "ECL", "UNP",
    "CSX", "UPS", "FDX", "NSC", "GM", "F", "T", "VZ", "SO", "DUK", "AEP",
    "D", "EXC", "NEM", "APD", "JNJ", "PFE", "GILD", "ABT", "MRK", "LLY",
    "BMY", "APTV", "ORCL",
    "AMD", "ADBE", "CSCO", "QCOM", "TXN", "AVGO", "MU", "EBAY", "NFLX",
    "V", "MA", "PYPL", "ADP", "FIS", "FISV",
    "MDT", "SYK", "BDX", "BAX", "ZBH", "ISRG", "DHR", "TMO", "A",
    "EMR", "ITW", "ROK", "PH", "DOV", "ETN", "HON",
    "MAR", "HLT", "CCL", "RCL", "LUV", "DAL", "UAL", "AAL", "ALK",
    "CVS", "KR", "SYY", "DLTR", "ROST", "TJX", "BBY",
    "ALL", "TRV", "PGR", "CB", "AFL", "MET", "PRU",
    "AVB", "EQR", "PSA", "O", "SPG", "WELL", "VTR",
    "NEE", "PCG", "ED", "PPL", "WEC", "CMS", "ES",
]
MANUALLY_EXCLUDED = {"MSFT", "INTC", "HPQ", "DELL", "AMZN", "LMT", "NOC", "RTX"}


def build_ascendant_groups(min_group_size: int = 6) -> dict[str, dict[str, date]]:
    """
    يحسب تاريخ الميلاد الحقيقي (natal_dates.get_natal_date) لكل مرشّح صالح
    أخلاقيًا، يستبعد أي تاريخ مشبوه (حد أرشيف)، ثم يجمّع الباقي حسب برج
    الطالع. يرجّع فقط الأبراج التي بلغت min_group_size أسهم فأكثر.
    """
    from ethical_screen import BDS_EXCLUDED_TICKERS

    idx = build_local_ticker_index()
    candidates = [t for t in CANDIDATE_POOL
                  if t not in MANUALLY_EXCLUDED and t not in BDS_EXCLUDED_TICKERS and t in idx]

    clean, excluded = filter_suspicious_natal_dates(candidates)
    print(f"تواريخ ميلاد موثوقة: {len(clean)}/{len(candidates)} "
          f"({len(excluded)} استُبعدوا — تاريخ مشبوه أو غير متوفر)")

    groups: dict[str, dict[str, date]] = {}
    for t, natal_date in clean.items():
        sign = compute_ascendant(natal_date).ascendant_sign
        groups.setdefault(sign, {})[t] = natal_date

    return {sign: members for sign, members in groups.items() if len(members) >= min_group_size}


def find_latest_common_window(tickers: list[str], window_days: int) -> tuple[date, date]:
    """
    "أحدث نافذة ممكنة تغطي أكبر عدد أسهم" (طلب عبده الصريح): يحسب أحدث تاريخ
    بداية بيانات مشترك بين كل الأسهم المُعطاة (= أقدم "أول تداول محلي" بينهم،
    لأن النافذة يجب أن تبدأ بعده لتشمل الجميع)، ثم يضع النافذة في آخر
    window_days يوم متاحة قبل اليوم — إن كان أي سهم يبدأ لاحقًا مما تسمح به
    النافذة، يُستبعد ذلك السهم (لا تُقصَّر النافذة، بل تُستبعد الأسهم الأضيق).
    """
    idx = build_local_ticker_index()
    latest_end = date.today()
    window_start = latest_end - timedelta(days=window_days - 1)

    included, excluded = [], []
    for t in tickers:
        hist = load_local_history(t, idx)
        if hist is None or hist.index[0].date() > window_start:
            excluded.append(t)
        else:
            included.append(t)

    if excluded:
        print(f"  مستبعدون من هذه النافذة (تاريخهم المحلي أحدث من بداية النافذة): {excluded}")
    return window_start, latest_end


def measure_common_window_effect(ticker: str, planet: str, window_start: date, window_end: date,
                                   natal_date: date, alpha: float,
                                   rng_seed: int = 42) -> dict | None:
    """
    مطابق لـ planet_isolation.measure_window_effect لكن بنافذة مُمرَّرة مباشرة
    (لا بحث عن أنقى نافذة) وبتاريخ ميلاد مُمرَّر مسبقًا (لا إعادة حساب لكل
    استدعاء) — الفرق الجوهري: بلا شرط كثافة أسبكتات إطلاقًا.
    """
    idx = build_local_ticker_index()
    hist = load_local_history(ticker, idx)
    if hist is None:
        return None

    win = hist.loc[str(window_start):str(window_end)]
    if len(win) < 30:
        return None

    natal_ascendant = compute_ascendant(natal_date).ascendant_longitude

    close = win["Close"]
    trend = np.polyval(np.polyfit(np.arange(len(close)), close.to_numpy(), deg=1), np.arange(len(close)))
    detrended = close.to_numpy() - trend

    dates = [ts.date() for ts in close.index]
    longitude = np.array([get_planet_longitude(planet, d) for d in dates])
    transit_position = (longitude - natal_ascendant) % 360
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
        "ticker": ticker, "natal_date": natal_date.isoformat(),
        "ascendant_sign": compute_ascendant(natal_date).ascendant_sign,
        "planet": planet, "window_start": window_start.isoformat(), "window_end": window_end.isoformat(),
        "beta_points_per_degree": round(fit.beta_points_per_degree, 5),
        "r_squared": round(fit.r_squared, 4),
        "permutation_p_value": round(perm_result.p_value, 5),
        "random_control_p_value": round(control_result.p_value, 5),
        "passes_gates": passes_gates,
    }


def run_same_ascendant_batch(planet: str, ascendant_sign: str, n_cycles: float = 1.0) -> pd.DataFrame:
    groups = build_ascendant_groups()
    if ascendant_sign not in groups:
        available = {s: len(m) for s, m in groups.items()}
        raise ValueError(f"برج '{ascendant_sign}' ليس له عدد كافٍ من الأسهم بتاريخ ميلاد موثوق. "
                          f"المتاح: {available}")

    members = groups[ascendant_sign]
    tickers = sorted(members)
    window_days = recommended_window_days(planet, n_cycles)
    alpha = bonferroni_alpha(len(SLOW_PLANETS))

    print(f"same_ascendant_batch: برج={ascendant_sign} ({len(tickers)} سهم)، planet={planet}, "
          f"نافذة={window_days} يوم ({n_cycles} دورة)، alpha={alpha:.5f}")

    window_start, window_end = find_latest_common_window(tickers, window_days)
    print(f"النافذة المشتركة: {window_start} إلى {window_end}")

    rows = []
    for t in tickers:
        try:
            sector, _industry = get_sector_and_industry(t)
        except Exception as exc:  # noqa: BLE001
            sector = "unknown"
        result = measure_common_window_effect(t, planet, window_start, window_end, members[t], alpha)
        if result is None:
            print(f"  {t}: لا بيانات كافية ضمن هذه النافذة")
            continue
        result["sector"] = sector
        print(f"  {t} ({sector}): R²={result['r_squared']:.3f}, perm p={result['permutation_p_value']:.4f}, "
              f"control p={result['random_control_p_value']:.4f} — "
              f"{'✅ عبر' if result['passes_gates'] else '❌ لم يعبر'}")
        rows.append(result)

    return pd.DataFrame(rows)


def main(planet: str, ascendant_sign: str, n_cycles: float) -> None:
    results = run_same_ascendant_batch(planet, ascendant_sign, n_cycles)

    run_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = OUTPUT_ROOT / f"same_ascendant_{ascendant_sign}_{planet}_{run_timestamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    if not results.empty:
        results.to_csv(out_dir / "results.csv", index=False)
        n_passed = int(results["passes_gates"].sum())
        summary = (f"برج={ascendant_sign}, planet={planet}\n"
                   f"عدد الأسهم المُختبَرة: {len(results)}\n"
                   f"عدد عبروا: {n_passed} ({100*n_passed/len(results):.1f}%)\n"
                   f"R² متوسط: {results['r_squared'].mean():.4f}\n\n"
                   + results.to_string(index=False))
        (out_dir / "summary.md").write_text(summary, encoding="utf-8")
        print(f"\n{summary}")

    print(f"\nWrote output to {out_dir.resolve()}")


if __name__ == "__main__":
    planet_arg = sys.argv[1] if len(sys.argv) > 1 else "mars"
    sign_arg = sys.argv[2] if len(sys.argv) > 2 else "Aquarius"
    cycles_arg = float(sys.argv[3]) if len(sys.argv) > 3 else 1.0
    main(planet_arg, sign_arg, cycles_arg)
