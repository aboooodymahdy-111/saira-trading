"""
ai_catch_win_engine/feature_table_hourly.py — نفس منهجية feature_table.py، لكن
على فريم **ساعي** بدل يومي (طلب عبده 2026-07-18: اختبار فريمات مختلفة).

**تحديث 2026-07-18 (إزالة الفلك بالكامل)**: راجع القسم 9.18 من
Astro_Wave_Decomposition_Methodology.md و docstring feature_table.py —
نفس القرار والسبب هنا (الفلك أُثبت أنه لا يحسّن الأداء، وأُسقط من الملفين
معًا للاتساق).

**مصدر البيانات**: ai_catch_win_engine.hourly_data.load_hourly_history (دمج
محلي+yfinance، راجع docstring ذلك الملف لتفاصيل الفجوة الزمنية المعروفة
بين المصدرين). **مدى محدود بطبيعة البيانات المتاحة** (~2022-11 حتى الآن،
بفجوة ~10 أشهر) — أقصر بكثير من الفريم اليومي (feature_table.py يغطي عقودًا).

آفاق التنبؤ هنا **بالساعات التداولية** لا الأيام (PREDICTION_HORIZONS_HOURS):
1 ساعة، 4 ساعات (~نصف يوم تداول)، 8 ساعات (~يوم تداول كامل تقريبًا).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, ".")

from ai_catch_win_engine.hourly_data import load_hourly_history

OUTPUT_ROOT = Path("../runs/ai_catch_win_engine/feature_tables_hourly")

PREDICTION_HORIZONS_HOURS = [1, 4, 8]


def build_hourly_feature_table(ticker: str) -> pd.DataFrame:
    """يبني جدول ميزات ساعي كامل لـ`ticker` عبر كل تاريخه الساعي المتاح."""
    hist = load_hourly_history(ticker)
    if hist is None:
        raise ValueError(f"{ticker}: لا بيانات ساعية من أي مصدر")

    close = hist["Close"]
    df = pd.DataFrame({
        "datetime_utc": [ts.isoformat() for ts in close.index],
        "close": close.to_numpy(dtype=float),
        "open": hist["Open"].to_numpy(dtype=float),
        "high": hist["High"].to_numpy(dtype=float),
        "low": hist["Low"].to_numpy(dtype=float),
    })
    df["delta_price"] = df["close"].diff()
    df["abs_delta_price"] = df["delta_price"].abs()

    # نسبة تغيّر مئوية، لا سعر مطلق — نفس تصحيح feature_table.py (المستوى
    # المطلق فشل overfitting شامل، راجع docstring هناك للتفاصيل).
    for horizon in PREDICTION_HORIZONS_HOURS:
        df[f"target_high_h{horizon}"] = (df["high"].shift(-horizon) / df["close"] - 1) * 100
        df[f"target_low_h{horizon}"] = (df["low"].shift(-horizon) / df["close"] - 1) * 100
        df[f"target_close_h{horizon}"] = (df["close"].shift(-horizon) / df["close"] - 1) * 100

    return df


def main(ticker: str) -> None:
    try:
        df = build_hourly_feature_table(ticker)
    except ValueError as exc:
        print(f"{ticker}: {exc}")
        sys.exit(1)

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_ROOT / f"{ticker}.csv"
    df.to_csv(out_path, index=False)
    print(f"{ticker}: {len(df)} صف × {len(df.columns)} عمود -> {out_path.resolve()}")


if __name__ == "__main__":
    ticker_arg = sys.argv[1] if len(sys.argv) > 1 else "WMT"
    main(ticker_arg)
