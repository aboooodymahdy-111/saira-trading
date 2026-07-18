"""
astro_engine_1/feature_table.py — بناء جدول ميزات يومي (feature table) لسهم
واحد، جاهز كمُدخل مباشر لنموذج تعلّم آلي/عميق.

**تحديث 2026-07-18 (إزالة الفلك بالكامل، القسم 9.18 من
Astro_Wave_Decomposition_Methodology.md)**: بعد اختبار وجود/غياب المجموعة
الفلكية (26 عمود: زوايا 7 كواكب + اتصالات) عبر كل الـ12 تركيبة (4 آفاق ×
high/low/close) على عيّنة 20 سهمًا، تبيّن أن **إزالة الفلك حسّنت (لم تُضعف)
الدقة في 12 من 12 حالة** (فرق 1-2.5 نقطة، لكن الاتجاه ثابت بلا استثناء) —
الميزات الفنية/الزخم وحدها كافية وأفضل قليلاً. القرار: **إسقاط الفلك
بالكامل من هذا الملف** (كان natal_date/ascendant/planet_longitude/aspects،
راجع تاريخ git لو احتجت مراجعتها). يبقى اسم الحزمة `astro_engine_1` للمرجعية
التاريخية فقط، رغم أن الملف الحالي بلا فلك.

**الأعمدة المُنتَجة لكل يوم**: `close`/`delta_price`/`abs_delta_price` (السعر
والهدف المحتمل)، ميزات lag/momentum/volatility (`pct_change_lag*`,
`rolling_volatility_10d`)، مؤشرات فنية عبر TA-Lib (RSI/MACD/Bollinger/ATR)،
وميزات "عنف الحركة" (`gap_pct`, `volatility_acceleration`, `volume_ratio`,
`range_pct_of_price`) — راجع القسم 9.16 من الوثيقة لسبب إضافتها (نموذج
مخصص للأسهم شديدة التقلب).

يُصدَّر كـCSV واحد (`runs/astro_engine_1/feature_tables/{ticker}.csv`) —
تنسيق عادي يقرأه أي إطار عمل تعلّم آلي (pandas/XGBoost/PyTorch) مباشرة.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # مطلق، لا "." هش — راجع cloud_build_feature_tables.py

from full_universe_analysis import build_local_ticker_index, load_local_history

OUTPUT_ROOT = Path("../runs/astro_engine_1/feature_tables")

# آفاق التنبؤ المُختبَرة (بالأيام التداولية) — طلب عبده: تجربة فريمات
# متنوعة لمعرفة أفضلها، بدل الاقتصار على "الغد" (h=1) فقط.
PREDICTION_HORIZONS_DAYS = [1, 5, 10, 20]


def build_feature_table(ticker: str) -> pd.DataFrame:
    """
    يبني جدول ميزات يومي كامل لـ`ticker` عبر كل تاريخه المحلي المتاح — بلا
    أي اعتماد على تاريخ ميلاد/فلك (راجع القسم 9.18: إزالة الفلك بالكامل بعد
    إثبات أنها لا تحسّن الأداء). يرفع ValueError لو لا بيانات سعرية محلية.
    """
    idx = build_local_ticker_index()
    hist = load_local_history(ticker, idx)
    if hist is None:
        raise ValueError(f"{ticker}: لا بيانات سعرية محلية")

    close = hist["Close"]
    dates = [ts.date() for ts in close.index]

    df = pd.DataFrame({
        "date": [d.isoformat() for d in dates],
        "close": close.to_numpy(dtype=float),
        "open": hist["Open"].to_numpy(dtype=float),
        "high": hist["High"].to_numpy(dtype=float),
        "low": hist["Low"].to_numpy(dtype=float),
        "volume": hist["Volume"].to_numpy(dtype=float),
    })
    df["delta_price"] = df["close"].diff()
    df["abs_delta_price"] = df["delta_price"].abs()

    # ميزات lag (تطوير 2026-07-18، طلب عبده: تطوير الدقة فوق 90%) — % تغيّر
    # السعر خلال آخر 1/5/10/20 يوم، وتقلّب السعر (rolling std لآخر 10 أيام).
    # هذه ميزات "زخم/تقلّب" عادية (لا فلكية)، لكن دمجها مع الزوايا الفلكية
    # يعطي النموذج سياقًا عن الاتجاه الأخير — بدونها، النموذج يرى فقط مواقع
    # الكواكب بلا أي معرفة بحالة السعر الحديثة، ما يحدّ قدرته على التنبؤ.
    pct_change_1 = df["close"].pct_change(1) * 100
    for lag_days in (1, 5, 10, 20):
        df[f"pct_change_lag{lag_days}"] = df["close"].pct_change(lag_days) * 100
    df["rolling_volatility_10d"] = pct_change_1.rolling(10).std()

    # مؤشرات فنية حقيقية (تطوير 2026-07-18، طلب عبده: دقة > 96%) — عبر
    # TA-Lib (نفس المكتبة المستخدَمة في advanced_technical_tools.py) بدل lag
    # بسيط فقط: RSI (زخم/تشبّع)، MACD (اتجاه)، Bollinger %B (موقع السعر
    # نسبة لنطاق تقلبه)، ATR (مدى التقلب الحقيقي) — أقوى بكثير من lag/
    # volatility وحدهما لأنها تلخّص أنماطًا معروفة تجريبيًا في التحليل الفني.
    try:
        import talib
        close_arr = df["close"].to_numpy()
        high_arr = df["high"].to_numpy()
        low_arr = df["low"].to_numpy()

        df["rsi_14"] = talib.RSI(close_arr, timeperiod=14)
        macd, macd_signal, macd_hist = talib.MACD(close_arr, fastperiod=12, slowperiod=26, signalperiod=9)
        df["macd_hist"] = macd_hist
        bb_upper, bb_middle, bb_lower = talib.BBANDS(close_arr, timeperiod=20)
        bb_range = bb_upper - bb_lower
        df["bollinger_pct_b"] = np.where(bb_range > 0, (close_arr - bb_lower) / bb_range, 0.5)
        df["atr_14"] = talib.ATR(high_arr, low_arr, close_arr, timeperiod=14)
        df["atr_pct_of_price"] = df["atr_14"] / df["close"] * 100
    except ImportError:
        pass  # TA-Lib غير مثبَّت — يستمر بلا هذه الميزات (lag/volatility تبقى كافية للعمل الأساسي)

    # ميزات "عنف الحركة" (تطوير 2026-07-18، طلب عبده: نموذج مخصص للأسهم
    # شديدة التقلب — AAL/QCOM/ADBE/EBAY/ROST/LUV/AVGO/CSCO، أعلى 8 من 20
    # سهمًا حسب متوسط |تغيّر يومي|). الميزات السابقة (lag/RSI/MACD) تلتقط
    # الاتجاه والزخم لكن ليس "حدّة" الحركة نفسها — هذه الميزات الجديدة تفعل:
    #   - gap_pct: فجوة الافتتاح عن إغلاق أمس (حركة خارج ساعات التداول،
    #     شائعة في الأسهم العنيفة بعد أخبار/أرباح).
    #   - volatility_acceleration: هل التقلب الحالي (5 أيام) أعلى من المعتاد
    #     (20 يومًا)؟ — يلتقط "تسارع" العنف، لا فقط مستواه الثابت.
    #   - volume_ratio: نسبة حجم التداول اليوم لمتوسط 20 يومًا — ارتفاع حاد
    #     في الحجم غالبًا يرافق/يسبق حركات سعرية عنيفة.
    #   - range_pct_of_price: (High-Low)/Close اليوم — مدى الحركة اليومي
    #     الفعلي، مباشرة بلا اعتماد على ATR المُنعَّم عبر 14 يومًا.
    df["gap_pct"] = (df["open"] / df["close"].shift(1) - 1) * 100
    volatility_5d = pct_change_1.rolling(5).std()
    volatility_20d = pct_change_1.rolling(20).std()
    df["volatility_acceleration"] = volatility_5d / volatility_20d.replace(0, np.nan)
    volume_ma20 = df["volume"].rolling(20).mean()
    df["volume_ratio"] = df["volume"] / volume_ma20.replace(0, np.nan)
    df["range_pct_of_price"] = (df["high"] - df["low"]) / df["close"] * 100

    # أهداف التنبؤ (target): نسبة تغيّر مئوية بعد N يوم (High/Low/Close)،
    # لا السعر المطلق. MAJOR REVISION (2026-07-18): السعر المطلق كهدف فشل
    # فشلاً ذريعًا (overfit_ratio 40-300، 480/480 تشغيلة) — السبب الأرجح
    # أن WMT (وباقي الأسهم) تحرّك سعرها من سنتات لمئات الدولارات عبر عقود
    # (انقسامات أسهم/نمو طبيعي)، فالميزات الفلكية (زوايا 0-360°، لا علاقة
    # لها بمستوى السعر بالدولار) لا يمكنها التعميم على مستوى سعري لم يُرَ في
    # التدريب. % التغيّر عن سعر اليوم مستقل عن المستوى المطلق، فيعالج هذه
    # المشكلة مباشرة. shift(-N) يجلب قيمة الصف بعد N يوم تداول.
    for horizon in PREDICTION_HORIZONS_DAYS:
        df[f"target_high_h{horizon}"] = (df["high"].shift(-horizon) / df["close"] - 1) * 100
        df[f"target_low_h{horizon}"] = (df["low"].shift(-horizon) / df["close"] - 1) * 100
        df[f"target_close_h{horizon}"] = (df["close"].shift(-horizon) / df["close"] - 1) * 100

    return df


def main(ticker: str) -> None:
    try:
        df = build_feature_table(ticker)
    except ValueError as exc:
        print(f"{ticker}: {exc}")
        sys.exit(1)

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_ROOT / f"{ticker}.csv"
    df.to_csv(out_path, index=False)
    print(f"{ticker}: {len(df)} صف × {len(df.columns)} عمود -> {out_path.resolve()}")
    print(f"الأعمدة: {list(df.columns)}")


def build_all(tickers: list[str]) -> None:
    """يبني جدول ميزات لكل تيكر في `tickers` دفعة واحدة، متجاوزًا فشل سهم واحد."""
    for t in tickers:
        try:
            main(t)
        except SystemExit:
            print(f"  {t}: تخطّي (لا بيانات سعرية محلية)")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--all":
        # طلب عبده 2026-07-18: التركيز على الأسهم شديدة التقلب (راجع
        # volatility_screen.py) — لا سجل الأزواج الفلكية المُثبَتة القديم
        # (كان في correlation_weights.py، غير ذي صلة بعد إزالة الفلك).
        from astro_engine_1.volatility_screen import top_volatile_tickers
        all_tickers = top_volatile_tickers(200)
        build_all(all_tickers)
    else:
        ticker_arg = sys.argv[1] if len(sys.argv) > 1 else "WMT"
        main(ticker_arg)
