"""
ai_catch_win_engine/hourly_data.py — قارئ بيانات ساعية موحّد (طلب عبده 2026-07-18:
اختبار فريم الساعة بدل اليومي فقط، بدمج البيانات المحلية القديمة مع yfinance
الحديث لتغطية أطول مدى ممكن).

**مصدران، بفجوة زمنية معروفة بينهما**:
  1. محلي: `D:\\Library\\stock market\\Data\\USA\\hourly\\{nasdaq,nyse}
     stocks\\*\\{ticker}.us.txt` — يغطي 2022-11 حتى 2023-09-14 تقريبًا (يختلف
     قليلاً حسب السهم). التوقيت **UTC بالفعل** (تحقق مباشر: أوقات الشموع
     15:00-22:00 تطابق تمامًا افتتاح/إغلاق NYSE 14:30-21:00 UTC بعد تقريب
     الشمعة الساعية، لا فرق توقيت أمريكي محلي).
  2. yfinance (`interval="1h"`): يغطي آخر ~2 سنة فقط فقط (قيد ياهو نفسه، لا
     قيد بالكود — تحقق مباشر 2026-07-18: من 2024-07-18 حتى اليوم). التوقيت
     America/New_York (مع معلومة المنطقة الزمنية)، يُحوَّل هنا لـUTC قبل
     الدمج مع المصدر المحلي.

**فجوة غير مغطاة**: تقريبًا 2023-09-15 إلى 2024-07-17 (~10 أشهر) — لا بيانات
ساعية من أي من المصدرين لهذه الفترة. تظهر كفجوة طبيعية في السلسلة الزمنية
(لا بيانات مصطنعة/مُقحَمة لسدّها) — أي كود لاحق يستخدم هذه البيانات يجب أن
يتعامل معها كفجوة حقيقية، لا خطأ.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, ".")

LOCAL_HOURLY_ROOT = Path(r"D:\Library\stock market\Data\USA\hourly")
LOCAL_HOURLY_SUBFOLDERS = ("nasdaq stocks", "nyse stocks", "nasdaq etfs", "nyse etfs",
                            "nysemkt stocks", "nysemkt etfs")


def _find_local_hourly_file(ticker: str) -> Path | None:
    filename = f"{ticker.lower()}.us.txt"
    for sub in LOCAL_HOURLY_SUBFOLDERS:
        base = LOCAL_HOURLY_ROOT / sub
        if not base.exists():
            continue
        for match in base.rglob(filename):
            return match
    return None


def _load_local_hourly(ticker: str) -> pd.DataFrame | None:
    path = _find_local_hourly_file(ticker)
    if path is None:
        return None
    df = pd.read_csv(path)
    if df.empty:
        return None

    df.columns = [c.strip("<>").lower() for c in df.columns]
    # date=20221118, time=160000 -> "2022-11-18 16:00:00"، بالفعل UTC (راجع docstring الملف)
    dt_str = df["date"].astype(str) + df["time"].astype(str).str.zfill(6)
    df["datetime_utc"] = pd.to_datetime(dt_str, format="%Y%m%d%H%M%S", utc=True)
    df = df.set_index("datetime_utc")[["open", "high", "low", "close", "vol"]]
    df.columns = ["Open", "High", "Low", "Close", "Volume"]
    return df.sort_index()


def _load_yahoo_hourly(ticker: str) -> pd.DataFrame | None:
    try:
        import yfinance as yf
    except ImportError:
        return None
    from yf_retry import call_with_retry

    try:
        df = call_with_retry(lambda: yf.Ticker(ticker).history(period="max", interval="1h"))
    except Exception:
        return None
    if df is None or df.empty:
        return None

    df.index = df.index.tz_convert("UTC")
    df.index.name = "datetime_utc"
    return df[["Open", "High", "Low", "Close", "Volume"]]


def load_hourly_history(ticker: str) -> pd.DataFrame | None:
    """
    يدمج المصدر المحلي (أقدم، حتى ~2023-09) مع yfinance (أحدث، من ~2024-07)
    — فجوة ~10 أشهر بينهما تبقى كما هي (لا تعبئة مصطنعة). يرجّع None لو
    تعذّر كلا المصدرين.
    """
    local_df = _load_local_hourly(ticker)
    yahoo_df = _load_yahoo_hourly(ticker)

    parts = [df for df in (local_df, yahoo_df) if df is not None and not df.empty]
    if not parts:
        return None

    combined = pd.concat(parts)
    combined = combined[~combined.index.duplicated(keep="last")]  # yahoo يفوز عند أي تداخل
    return combined.sort_index()


if __name__ == "__main__":
    ticker_arg = sys.argv[1] if len(sys.argv) > 1 else "WMT"
    df = load_hourly_history(ticker_arg)
    if df is None:
        print(f"{ticker_arg}: لا بيانات ساعية من أي مصدر")
    else:
        print(f"{ticker_arg}: {len(df)} صف، {df.index[0]} -> {df.index[-1]}")
        gaps = df.index.to_series().diff()
        big_gaps = gaps[gaps > pd.Timedelta(days=5)]
        if not big_gaps.empty:
            print(f"فجوات > 5 أيام: {len(big_gaps)}")
            for ts, gap in big_gaps.items():
                print(f"  فجوة {gap} تنتهي عند {ts}")
