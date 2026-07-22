"""
ai_catch_win_engine/cloud_build_feature_tables.py — نسخة سحابية من feature_table.py
لـai_catch_win.py's GitHub Actions workflow: تبني نفس جدول الميزات بالضبط
(بلا فلك — راجع feature_table.py's docstring، القسم 9.18) لكن من yfinance
مباشرة (`yahoo_fetch.fetch_ohlc`) بدل الأرشيف المحلي (`build_local_ticker_
index`/`load_local_history`، متاح على جهاز عبده فقط) — الأرشيف المحلي مش
موجود على GitHub Actions runner، فهذا الملف يعيد استخدام **نفس منطق حساب
الميزات بالضبط** من feature_table.py، فقط بمصدر بيانات مختلف لصف OHLCV.

**لماذا ملف منفصل بدل تعديل feature_table.py نفسه**: feature_table.py's
build_feature_table() مربوطة صراحة بـ`full_universe_analysis.load_local_
history` (مصدر الحقيقة الوحيد لأي backtesting محلي، قرار ثابت في CLAUDE.md) —
تغييرها لدعم مصدرين يعقّد الدالة الأساسية بلا داعٍ. هذا الملف نسخة مطابقة
منطقيًا، مُستخدَمة فقط في مسار AI Catch & Win السحابي.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

# مسار مطلق (src/) بدل "." النسبي — "." اعتمد على أن CWD وقت التشغيل يبقى
# src/ بالظبط، وده اتأكد إنه مش موثوق دايمًا (فشل فعليًا على GitHub Actions
# Linux runner بـModuleNotFoundError لـyahoo_fetch رغم نجاحه محليًا على
# Windows بنفس الاستدعاء بالظبط — راجع الفحص الفعلي 2026-07-18).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai_catch_win_engine.feature_table import OUTPUT_ROOT, PREDICTION_HORIZONS_DAYS
from yahoo_fetch import fetch_ohlc

MIN_ROWS_REQUIRED = 120


def build_feature_table_from_yahoo(ticker: str, rng: str = "2y") -> pd.DataFrame | None:
    """نفس منطق feature_table.build_feature_table بالضبط، لكن من yfinance
    مباشرة. يرجّع None (لا يرفع استثناء) لو تعذّر الجلب أو قلّت البيانات —
    نفس عقد "تخطّي، لا توقّف التشغيلة كلها" المستخدَم في كل هذه الحزمة."""
    try:
        hist = fetch_ohlc(ticker, rng=rng, interval="1d")
    except Exception as exc:
        print(f"{ticker}: فشل الجلب ({exc})")
        return None
    if hist is None or len(hist) < MIN_ROWS_REQUIRED:
        return None

    close = hist["Close"]
    df = pd.DataFrame({
        "date": [d.date().isoformat() for d in hist.index],
        "close": close.to_numpy(dtype=float),
        "open": hist["Open"].to_numpy(dtype=float),
        "high": hist["High"].to_numpy(dtype=float),
        "low": hist["Low"].to_numpy(dtype=float),
        "volume": hist["Volume"].to_numpy(dtype=float),
    })
    df["delta_price"] = df["close"].diff()
    df["abs_delta_price"] = df["delta_price"].abs()

    pct_change_1 = df["close"].pct_change(1) * 100
    for lag_days in (1, 5, 10, 20):
        df[f"pct_change_lag{lag_days}"] = df["close"].pct_change(lag_days) * 100
    df["rolling_volatility_10d"] = pct_change_1.rolling(10).std()

    try:
        import talib
        close_arr = df["close"].to_numpy()
        high_arr = df["high"].to_numpy()
        low_arr = df["low"].to_numpy()

        df["rsi_14"] = talib.RSI(close_arr, timeperiod=14)
        _, _, macd_hist = talib.MACD(close_arr, fastperiod=12, slowperiod=26, signalperiod=9)
        df["macd_hist"] = macd_hist
        bb_upper, bb_middle, bb_lower = talib.BBANDS(close_arr, timeperiod=20)
        bb_range = bb_upper - bb_lower
        df["bollinger_pct_b"] = np.where(bb_range > 0, (close_arr - bb_lower) / bb_range, 0.5)
        df["atr_14"] = talib.ATR(high_arr, low_arr, close_arr, timeperiod=14)
        df["atr_pct_of_price"] = df["atr_14"] / df["close"] * 100
    except ImportError:
        pass  # TA-Lib غير مثبَّت — يستمر بلا هذه الميزات

    df["gap_pct"] = (df["open"] / df["close"].shift(1) - 1) * 100
    volatility_5d = pct_change_1.rolling(5).std()
    volatility_20d = pct_change_1.rolling(20).std()
    df["volatility_acceleration"] = volatility_5d / volatility_20d.replace(0, np.nan)
    volume_ma20 = df["volume"].rolling(20).mean()
    df["volume_ratio"] = df["volume"] / volume_ma20.replace(0, np.nan)
    df["range_pct_of_price"] = (df["high"] - df["low"]) / df["close"] * 100

    for horizon in PREDICTION_HORIZONS_DAYS:
        df[f"target_high_h{horizon}"] = (df["high"].shift(-horizon) / df["close"] - 1) * 100
        df[f"target_low_h{horizon}"] = (df["low"].shift(-horizon) / df["close"] - 1) * 100
        df[f"target_close_h{horizon}"] = (df["close"].shift(-horizon) / df["close"] - 1) * 100

    return df


def build_all_from_universe(universe_csv: str = "../data/ai_catch_win_universe.csv") -> tuple[int, int]:
    tickers = pd.read_csv(universe_csv)["ticker"].tolist()
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    ok = failed = 0
    for i, ticker in enumerate(tickers):
        df = build_feature_table_from_yahoo(ticker)
        if df is None:
            failed += 1
            continue
        df.to_csv(OUTPUT_ROOT / f"{ticker}.csv", index=False)
        ok += 1
        if (i + 1) % 20 == 0:
            print(f"  {i+1}/{len(tickers)}... ({ok} ok, {failed} failed)")
    print(f"انتهى: {ok} جدول ميزات مبني، {failed} فشل/تُخطّي.")
    return ok, failed


if __name__ == "__main__":
    csv_arg = sys.argv[1] if len(sys.argv) > 1 else "../data/ai_catch_win_universe.csv"
    build_all_from_universe(csv_arg)
