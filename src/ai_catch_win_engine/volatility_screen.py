"""
ai_catch_win_engine/volatility_screen.py — فلترة كمية للأسهم "شديدة التقلب" من
الأرشيف المحلي (طلب عبده 2026-07-18: "أنا أستهدف الاسهم التي تتقلب بعنف").

**لماذا فلترة كمية لا يدوية**: الـ8 أسهم اللي اتدرّب عليها النموذج قبل شوية
(AAL/QCOM/ADBE/EBAY/ROST/LUV/AVGO/CSCO) متقلبة *نسبيًا* بس مقارنة بباقي
large-caps — مش عنيفة زي AXTI (اللي تحرّكت $2 -> $140 -> $70 خلال شهور،
راجع project_axti_jul16_prediction). الأرشيف المحلي فيه ~8300 سهم، فحص عيّنة
عشوائية منه كشف مئات الأسهم (غالبًا micro-caps/warrants) بمتوسط |تغيّر يومي|
5-14% — رتبة حجم أعلى بكثير من الـ8 الحاليين (~1.5-3%). هذا الملف يبني ترتيب
موضوعي بدل اختيار عيّن بالعين.

**فلترة تحصينية ضد data artifacts (لا تقلب حقيقي)**: فحص العيّنة العشوائية
كشف تيكرز زي XTIA (سعر من $1.04 إلى ~$60 تريليون) وSBFM (حتى $2.24 مليار) —
انقسامات عكسية (reverse splits) متكررة تُنتج قفزات سعرية ضخمة في البيانات
الخام لا علاقة لها بتقلب تداولي حقيقي يوميًا. `min_price`/`max_price_ratio`
تحت يستبعدان هذه الحالات (سعر دنيا معقول + سقف على نسبة max/min عبر كامل
التاريخ) قبل الترتيب حسب التقلب.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, ".")

from full_universe_analysis import build_local_ticker_index, load_local_history

OUTPUT_PATH = Path("../runs/ai_catch_win_engine/volatility_screen.csv")

MIN_ROWS = 250          # على الأقل سنة تداول تقريبًا من التاريخ
MIN_PRICE = 1.0         # يستبعد penny stocks تحت الدولار (سبريد/سيولة رديئة تضخّم %التغيّر مصطنعًا)
MAX_PRICE = 50.0        # طلب عبده (2026-07): سقف سعر جديد، بلا داعي لأسهم أغلى من كده لحسابه
MAX_PRICE_RATIO = 50.0  # يستبعد أسهم بها انقسام عكسي ضخم يُظهر "تقلب" كاذب (راجع docstring الملف)
MIN_AVG_VOLUME_20D = 100_000  # طلب عبده (2026-07): نفس عتبة السيولة اللي كانت تحذير بصري بس في
                              # الإيميل (LOW_LIQUIDITY_VOLUME_THRESHOLD)، بقت استبعاد فعلي هنا


def screen_universe(sample_size: int | None = None, seed: int = 42) -> pd.DataFrame:
    """
    يفحص الأرشيف المحلي كله (أو عيّنة عشوائية منه لو `sample_size` محدَّد،
    للتشغيل السريع/الاختباري) ويرجّع DataFrame مرتّبًا تنازليًا حسب
    `mean_abs_daily_pct` — أعمدة كافية لمراجعة يدوية سريعة قبل اعتماد أي عيّنة
    نهائية للتدريب.
    """
    index = build_local_ticker_index()
    tickers = sorted(index)
    if sample_size is not None and sample_size < len(tickers):
        import random
        tickers = sorted(random.Random(seed).sample(tickers, sample_size))

    rows = []
    for ticker in tickers:
        try:
            hist = load_local_history(ticker, index)
        except Exception:
            continue
        if hist is None or len(hist) < MIN_ROWS:
            continue

        close = hist["Close"]
        min_price, max_price = float(close.min()), float(close.max())
        if min_price < MIN_PRICE:
            continue
        if min_price > 0 and (max_price / min_price) > MAX_PRICE_RATIO:
            continue
        last_close = float(close.iloc[-1])
        if last_close > MAX_PRICE:
            continue
        avg_volume_20d = float(hist["Volume"].tail(20).mean())
        if avg_volume_20d < MIN_AVG_VOLUME_20D:
            continue

        pct = close.pct_change().abs() * 100
        rows.append({
            "ticker": ticker,
            "n_rows": len(hist),
            "mean_abs_daily_pct": round(float(pct.mean()), 3),
            "std_daily_pct": round(float(pct.std()), 3),
            "min_close": round(min_price, 2),
            "max_close": round(max_price, 2),
            "last_close": round(float(close.iloc[-1]), 2),
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.sort_values("mean_abs_daily_pct", ascending=False).reset_index(drop=True)


def top_volatile_tickers(n: int, sample_size: int | None = None, seed: int = 42) -> list[str]:
    df = screen_universe(sample_size=sample_size, seed=seed)
    return df["ticker"].head(n).tolist()


def main() -> None:
    sample_size = int(sys.argv[1]) if len(sys.argv) > 1 else None
    df = screen_universe(sample_size=sample_size)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_PATH, index=False)
    print(f"{len(df)} سهم اجتاز الفلترة (من أصل عيّنة {sample_size or 'كاملة'}) -> {OUTPUT_PATH.resolve()}")
    print(df.head(40).to_string(index=False))


if __name__ == "__main__":
    main()
