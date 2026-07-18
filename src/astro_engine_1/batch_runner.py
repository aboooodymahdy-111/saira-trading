"""
astro_engine_1/batch_runner.py — يكرر harness.run_mini_experiment عبر عيّنة
أسهم فعلية من الداتا المحلية (بدل سهم واحد)، ويجمّع كل النتائج (الناجحة
والفاشلة معًا — لا نتيجة سلبية تُخفى) في CSV واحد + ملخص.

نفس منهجية lab.py: عيّنة عشوائية بـ seed ثابت (قابلة لإعادة الإنتاج بالضبط)،
مخرجات مؤرشفة بالتوقيت الزمني تحت runs/astro_engine_1/.

تشغيل: `python -m astro_engine_1.batch_runner [n_tickers]` من مجلد src/.
"""
from __future__ import annotations

import json
import random
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, ".")

from full_universe_analysis import build_local_ticker_index

from astro_engine_1.harness import _default_alpha, run_mini_experiment

SAMPLE_SEED = 42
DEFAULT_SAMPLE_SIZE = 50
OUTPUT_ROOT = Path("../runs/astro_engine_1")


def _sample_tickers(local_index: dict, sample_size: int, seed: int) -> list[str]:
    """
    عيّنة عشوائية بسيطة من كل التيكرز المتاحة محليًا — بخلاف lab.py، هنا
    لا حاجة لفلتر الأهلية الأخلاقية (ethical_screen) لأن هذه تجربة قياس إحصائي
    بحت (β)، مش توصية تداول فعلية؛ الفلتر الأخلاقي بيتطبّق عند التوصية الفعلية
    لاحقًا (full_universe_analysis.py)، مش عند اختبار فرضية بحثية.
    """
    all_tickers = sorted(local_index)
    if sample_size >= len(all_tickers):
        return all_tickers
    return sorted(random.Random(seed).sample(all_tickers, sample_size))


def run_batch(n_tickers: int = DEFAULT_SAMPLE_SIZE) -> pd.DataFrame:
    local_index = build_local_ticker_index()
    tickers = _sample_tickers(local_index, n_tickers, SAMPLE_SEED)
    alpha = _default_alpha()

    print(f"astro_engine_1 batch: {len(tickers)} تيكر (seed={SAMPLE_SEED}), "
          f"alpha مُصحَّح بـ Bonferroni = {alpha:.6f}")

    rows: list[dict] = []
    for i, ticker in enumerate(tickers, start=1):
        print(f"[{i}/{len(tickers)}] {ticker}...")
        try:
            outcomes = run_mini_experiment(ticker, alpha=alpha)
        except Exception as exc:  # noqa: BLE001 - فشل سهم واحد مايوقفش الدفعة كلها
            print(f"  WARNING: {ticker} فشل: {exc}")
            continue

        for r in outcomes:
            rows.append({
                "ticker": r.ticker,
                "imf_index": r.imf_index,
                "imf_period_days": round(r.imf_period_days, 2),
                "matched_cycle": r.matched_cycle_label,
                "period_error_pct": round(r.matched_cycle_error_pct, 2),
                "beta_points_per_degree": round(r.beta_points_per_degree, 5),
                "beta_r_squared": round(r.beta_r_squared, 4),
                "permutation_p_value": round(r.permutation_p_value, 5),
                "random_control_p_value": round(r.random_control_p_value, 5),
                "stable_across_halves": r.stable_across_halves,
                "phase_diff_deg": round(r.phase_diff_deg, 2),
                "n_observations": r.n_observations,
                "passes_all_gates": r.passes_all_gates,
            })

    return pd.DataFrame(rows)


def summarize(results: pd.DataFrame, alpha: float) -> str:
    if results.empty:
        return "مفيش أي IMF عبر كل العيّنة عنده مطابقة فلكية قابلة للاختبار."

    lines = []
    total_imfs_tested = len(results)
    n_passed = int(results["passes_all_gates"].sum())
    lines.append(f"إجمالي IMFs مُختبَرة (لها مطابقة فلكية ضمن الهامش): {total_imfs_tested}")
    lines.append(f"عدد اجتاز كل البوابات (permutation p<{alpha:.5f} + "
                 f"random-control غير دال + استقرار نصفين): {n_passed}")

    lines.append("\nتوزيع المطابقات الفلكية المكتشفة (الأكثر تكرارًا):")
    lines.append(results["matched_cycle"].value_counts().head(10).to_string())

    if n_passed > 0:
        lines.append("\n--- الإشارات التي اجتازت كل البوابات ---")
        passed = results[results["passes_all_gates"]].sort_values("permutation_p_value")
        lines.append(passed.to_string(index=False))

        lines.append("\n--- ثبات كل دورة عبر كل الأسهم (هل نفس الكوكب يفوز بأكثر من سهم؟) ---")
        cycle_summary = (
            passed.groupby("matched_cycle")
            .agg(n_tickers=("ticker", "nunique"),
                 mean_beta=("beta_points_per_degree", "mean"),
                 mean_r_squared=("beta_r_squared", "mean"))
            .sort_values("n_tickers", ascending=False)
        )
        lines.append(cycle_summary.to_string())
    else:
        lines.append("\nمفيش أي إشارة اجتازت كل البوابات في هذه العيّنة.")

    return "\n".join(lines)


def main(n_tickers: int) -> None:
    results = run_batch(n_tickers)
    alpha = _default_alpha()

    run_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = OUTPUT_ROOT / f"batch_{run_timestamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    if not results.empty:
        results.to_csv(out_dir / "all_imf_results.csv", index=False)

    summary_text = summarize(results, alpha)
    params = {
        "run_timestamp": run_timestamp,
        "n_tickers_requested": n_tickers,
        "sample_seed": SAMPLE_SEED,
        "bonferroni_alpha": alpha,
    }
    (out_dir / "params.json").write_text(json.dumps(params, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "summary.md").write_text(summary_text, encoding="utf-8")

    print(f"\nWrote batch output to {out_dir.resolve()}")
    print("\n" + summary_text)


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SAMPLE_SIZE
    main(n)
