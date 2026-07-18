"""
astro_engine_1/isolation_batch_runner.py — يكرر planet_isolation.
run_planet_isolation_experiment عبر عيّنة أسهم فعلية، لكوكب واحد محدد. بما أن
النوافذ "الأنقى" (find_lowest_density_windows) مُحدَّدة بالكامل من مواقع
الكواكب (مستقلة عن أي سهم)، تُحسب مرة واحدة فقط هنا وتُعاد استخدامها لكل
الأسهم — توفير حسابي كبير (بدل إعادة حسابها لكل تيكر كما في
run_planet_isolation_experiment الفردية).

اختيار العيّنة (2026-07-18، بتوجيه عبده): عيّنة عشوائية بحتة من كل الفهرس
المحلي لا تضمن تنويعًا قطاعيًا أو عمريًا — والهدف هنا تحديدًا فصل "تأثير
فلكي حقيقي خاص بكل خريطة سهم" عن "ظرف سوقي عام" (مثال: فقاعة الدوت-كوم
أثّرت على AAPL/MSFT معًا في نفس نافذة 1999-2004، راجع القسم 9.5 من
Astro_Wave_Decomposition_Methodology.md)، فاستُبدلت بقائمة يدوية ثابتة
(DIVERSIFIED_SAMPLE_TICKERS) مختارة يدويًا لتغطية: (أ) قطاعات متعددة لا
علاقة لها مباشرة بفقاعة الدوت-كوم (طاقة، سلع استهلاكية، صناعي، رعاية صحية،
مرافق، معادن، نقل) بجانب تقنية/تجزئة، و(ب) مدى عمري واسع (IBM منذ 1962 حتى
APTV/DOW/LIN المؤسَّسة بعد 2000 بكثير) — بدل نداء yfinance بطيء/rate-limited
لكل تيكر في كامل الفهرس (8000+ سهم) فقط لاختيار عيّنة. عمود `sector` في
المخرجات (نداء get_sector_and_industry واحد فقط لكل سهم في العيّنة، لا أكثر)
موجود ليُظهر أي نمط "قطاع يرنّ مع كوكب معيّن" بوضوح — توضيح عبده أن القطاعات
قد تتزامن تأثرًا لأن كل بيت في الخريطة يمثّل مجال حياة/صناعة معينة، فهذا ليس
بالضرورة ضوضاء بل قد يكون جزءًا من الفرضية نفسها. القائمة مفلترة يدويًا مقابل
`ethical_screen.BDS_EXCLUDED_TICKERS` (نفس فلتر المشروع الإلزامي) حتى في هذه
بيئة الاختبار البحتة.
"""
from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, ".")

from ethical_screen import get_sector_and_industry
from full_universe_analysis import build_local_ticker_index, load_local_history
from lab_stats import bonferroni_alpha

from astro_engine_1.planet_isolation import (
    SLOW_PLANETS,
    find_lowest_density_windows,
    measure_window_effect,
    recommended_window_days,
)

# عيّنة يدوية متنوعة قطاعيًا وعمريًا — راجع شرح الاختيار في docstring الملف.
# مرتّبة حسب القطاع التقريبي فقط للقراءة، بلا أي دلالة أخرى.
DIVERSIFIED_SAMPLE_TICKERS = [
    # تقنية/تجزئة إلكترونية (الأكثر تأثرًا بفقاعة الدوت-كوم)
    "AAPL", "IBM", "ORCL", "XRX", "APTV",
    # طاقة
    "XOM", "COP", "FCX", "AA", "NUE",
    # سلع استهلاكية أساسية
    "PG", "CL", "KMB", "MO", "PM", "ADM", "HSY", "GIS", "CAG",
    # تجزئة/مطاعم
    "WMT", "COST", "TGT", "HD", "LOW", "NKE", "SBUX", "CMG",
    # صناعي/كيماويات
    "CAT", "MMM", "DD", "DOW", "LIN", "ECL",
    # نقل
    "UNP", "CSX", "UPS", "FDX", "NSC", "GM", "F",
    # اتصالات ومرافق
    "T", "VZ", "SO", "DUK", "AEP", "D", "EXC",
    # معادن/تعدين
    "NEM", "APD",
    # رعاية صحية
    "JNJ", "PFE", "GILD", "ABT", "MRK", "LLY", "BMY",
]

DEFAULT_SAMPLE_SIZE = len(DIVERSIFIED_SAMPLE_TICKERS)
OUTPUT_ROOT = Path("../runs/astro_engine_1")


def _diversified_tickers(local_index: dict, sample_size: int) -> list[str]:
    available = [t for t in DIVERSIFIED_SAMPLE_TICKERS if t in local_index]
    return available[:sample_size] if sample_size < len(available) else available


def run_isolation_batch(planet: str, n_tickers: int = DEFAULT_SAMPLE_SIZE,
                         n_windows: int = 5, n_cycles: float = 2.5) -> pd.DataFrame:
    local_index = build_local_ticker_index()
    tickers = _diversified_tickers(local_index, n_tickers)
    alpha = bonferroni_alpha(len(SLOW_PLANETS))

    window_days = recommended_window_days(planet, n_cycles)
    # نطاق البحث عن النوافذ: أوسع تاريخ ممكن نظريًا (من أقدم سهم قد يظهر في
    # العيّنة حتى اليوم) — كل سهم بعدين بيقتصّ (measure_window_effect) على
    # الجزء المتوفر فعليًا من تاريخه، فمفيش مشكلة لو النافذة أقدم من تاريخ سهم معين.
    search_start = date(1962, 1, 1)  # أقدم بيانات NYSE محلية معروفة تقريبًا
    search_end = date.today()

    print(f"astro_engine_1 isolation batch: planet={planet}, {len(tickers)} تيكر "
          f"(عيّنة يدوية متنوعة قطاعيًا)، نافذة={window_days} يوم, alpha={alpha:.5f}")

    windows = find_lowest_density_windows(planet, search_start, search_end, window_days, n_windows)
    print(f"أنقى {len(windows)} نافذة (نفس النوافذ لكل الأسهم — مُحدَّدة من مواقع الكواكب فقط):")
    for w in windows:
        print(f"  {w.start_date} إلى {w.end_date} (متوسط كثافة={w.mean_aspect_count:.2f})")

    rows: list[dict] = []
    for i, ticker in enumerate(tickers, start=1):
        try:
            sector, _industry = get_sector_and_industry(ticker)
        except Exception as exc:  # noqa: BLE001 - فشل جلب القطاع مايوقفش الدفعة
            print(f"  WARNING: sector lookup failed for {ticker}: {exc}")
            sector = "unknown"
        print(f"[{i}/{len(tickers)}] {ticker} ({sector})...")
        for w in windows:
            try:
                result = measure_window_effect(ticker, planet, w, alpha)
            except Exception as exc:  # noqa: BLE001 - فشل سهم واحد مايوقفش الدفعة كلها
                print(f"  WARNING: {ticker} @ {w.start_date}: {exc}")
                continue
            if result is None:
                continue
            rows.append({
                "ticker": result.ticker,
                "sector": sector,
                "planet": result.planet,
                "window_start": result.window_start.isoformat(),
                "window_end": result.window_end.isoformat(),
                "mean_aspect_count": round(result.mean_aspect_count, 3),
                "beta_points_per_degree": round(result.beta_points_per_degree, 5),
                "r_squared": round(result.r_squared, 4),
                "permutation_p_value": round(result.permutation_p_value, 5),
                "random_control_p_value": round(result.random_control_p_value, 5),
                "passes_gates": result.passes_gates,
            })

    return pd.DataFrame(rows)


def summarize(results: pd.DataFrame) -> str:
    if results.empty:
        return "مفيش أي نتيجة عبر العيّنة."

    lines = []
    n_total = len(results)
    n_passed = int(results["passes_gates"].sum())
    lines.append(f"إجمالي (سهم × نافذة) مُختبَرة: {n_total}")
    lines.append(f"عدد اجتاز كل البوابات: {n_passed} ({100*n_passed/n_total:.1f}%)")
    lines.append(f"R² متوسط عبر كل العيّنة: {results['r_squared'].mean():.4f}")
    lines.append(f"R² متوسط لمن اجتاز البوابات فقط: "
                 f"{results[results['passes_gates']]['r_squared'].mean():.4f}" if n_passed else "—")

    lines.append("\n--- تلخيص حسب النافذة (هل نفس النافذة تنجح عبر عدة أسهم؟) ---")
    by_window = results.groupby(["window_start", "window_end"]).agg(
        n_tickers=("ticker", "nunique"),
        n_passed=("passes_gates", "sum"),
        mean_r_squared=("r_squared", "mean"),
    ).sort_values("n_passed", ascending=False)
    lines.append(by_window.to_string())

    if n_passed > 0:
        lines.append("\n--- الأسهم/النوافذ التي اجتازت كل البوابات ---")
        passed = results[results["passes_gates"]].sort_values("permutation_p_value")
        lines.append(passed.to_string(index=False))

    lines.append("\n--- تلخيص حسب القطاع (هل قطاع معيّن ينجح أكثر — يتماشى مع فكرة البيوت) ---")
    by_sector = results.groupby("sector").agg(
        n_tested=("ticker", "count"),
        n_passed=("passes_gates", "sum"),
        mean_r_squared=("r_squared", "mean"),
    ).sort_values("n_passed", ascending=False)
    lines.append(by_sector.to_string())

    return "\n".join(lines)


def main(planet: str, n_tickers: int, n_cycles: float = 2.5) -> None:
    results = run_isolation_batch(planet, n_tickers, n_cycles=n_cycles)

    run_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = OUTPUT_ROOT / f"isolation_{planet}_{run_timestamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    if not results.empty:
        results.to_csv(out_dir / "results.csv", index=False)

    summary_text = summarize(results)
    (out_dir / "summary.md").write_text(summary_text, encoding="utf-8")

    print(f"\nWrote batch output to {out_dir.resolve()}")
    print("\n" + summary_text)


if __name__ == "__main__":
    planet_arg = sys.argv[1] if len(sys.argv) > 1 else "mars"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_SAMPLE_SIZE
    main(planet_arg, n)
