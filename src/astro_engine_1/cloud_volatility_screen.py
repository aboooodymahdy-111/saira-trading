"""
astro_engine_1/cloud_volatility_screen.py — نفس فكرة volatility_screen.py لكن
بيانات yfinance بدل الأرشيف المحلي (`LOCAL_MARKET_DATA_DIR` بتاع Abdo)،
عشان يشتغل على GitHub Actions حيث الأرشيف المحلي مش متاح — طلب عبده صراحة:
"متحدثهاش من جهازي خالص. ضيف خطوة الفلترة والجلب قبل التحليل على GH".

**تصميم "الثلث الدوّار" (طلب عبده)**: فحص كل الـ~6059 سهم (`TICKER_UNIVERSE_CSV`
من full_universe_analysis.py) دفعة واحدة يوميًا بطيء جدًا (rate limit فعلي مع
Yahoo — راجع full_universe_analysis.MAX_WORKERS/REQUEST_DELAY_SECONDS). بدلاً
من كده: كل تشغيلة تفحص **ثلث** القائمة فقط (يتغيّر يوميًا حسب رقم اليوم في
السنة mod 3)، فتُغطّى القائمة الكاملة كل 3 أيام. نتيجة كل تشغيلة تُدمَج في
سجل تراكمي (`cloud_volatility_rolling.csv`) بدل الكتابة فوقه بالكامل — كل
سهم يحمل `last_checked_date`، فالقائمة النهائية دائمًا "أحدث بيانات معروفة
لكل سهم" حتى لو آخر فحص فعلي له كان قبل يوم-يومين.

نفس فلاتر جودة البيانات المستخدمة محليًا (min_price / max_price_ratio) —
راجع volatility_screen.py's docstring لسبب وجودها (استبعاد reverse-split
artifacts زي XTIA).
"""
from __future__ import annotations

import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, ".")

from full_universe_analysis import load_ticker_universe
from yahoo_fetch import fetch_ohlc

OUTPUT_PATH = Path("../runs/astro_engine_1/cloud_volatility_rolling.csv")

MIN_ROWS = 100           # yfinance rng="1y" ~250 صف لو توفّر كامل، هامش أقل تشددًا من النسخة المحلية
MIN_PRICE = 1.0
MAX_PRICE_RATIO = 50.0
REQUEST_DELAY_SECONDS = 1.0  # نفس وتيرة full_universe_analysis — احترام Yahoo rate limit
STALE_AFTER_DAYS = 10        # سهم لم يُفحص منذ أكتر من كده يُستبعد من القائمة النهائية (بيانات قديمة جدًا)


def _screen_one(ticker: str) -> dict | None:
    try:
        hist = fetch_ohlc(ticker, rng="1y", interval="1d")
    except Exception:
        return None
    if hist is None or len(hist) < MIN_ROWS:
        return None

    close = hist["Close"].dropna()
    if close.empty:
        return None
    min_price, max_price = float(close.min()), float(close.max())
    if min_price < MIN_PRICE:
        return None
    if min_price > 0 and (max_price / min_price) > MAX_PRICE_RATIO:
        return None

    pct = close.pct_change().abs() * 100
    return {
        "ticker": ticker, "n_rows": len(hist),
        "mean_abs_daily_pct": round(float(pct.mean()), 3),
        "std_daily_pct": round(float(pct.std()), 3),
        "min_close": round(min_price, 2), "max_close": round(max_price, 2),
        "last_close": round(float(close.iloc[-1]), 2),
        "last_checked_date": date.today().isoformat(),
    }


def todays_third(all_tickers: list[str], n_parts: int = 3) -> list[str]:
    """يقسّم القائمة الكاملة (مُرتَّبة أبجديًا لثبات التقسيم) لـn_parts أجزاء
    متساوية تقريبًا، ويرجّع الجزء المطلوب فحصه اليوم حسب day-of-year mod
    n_parts — دورة كاملة كل n_parts يوم، بلا حاجة لتخزين حالة "أين توقفنا"."""
    part_index = date.today().timetuple().tm_yday % n_parts
    sorted_tickers = sorted(all_tickers)
    return [t for i, t in enumerate(sorted_tickers) if i % n_parts == part_index]


def scan_todays_third() -> pd.DataFrame:
    all_tickers = load_ticker_universe()
    todays_batch = todays_third(all_tickers)
    print(f"فحص اليوم: جزء {date.today().timetuple().tm_yday % 3 + 1}/3 "
          f"({len(todays_batch)} سهم من أصل {len(all_tickers)})")

    rows = []
    for i, t in enumerate(todays_batch):
        result = _screen_one(t)
        if result is not None:
            rows.append(result)
        if (i + 1) % 100 == 0:
            print(f"  {i+1}/{len(todays_batch)} سهم اتفحص... ({len(rows)} عدّى الفلترة لحد الآن)")
        time.sleep(REQUEST_DELAY_SECONDS)

    new_df = pd.DataFrame(rows)
    print(f"انتهى فحص اليوم: {len(new_df)}/{len(todays_batch)} سهم عدّى الفلترة.")
    return new_df


def merge_and_save(new_df: pd.DataFrame) -> pd.DataFrame:
    """يدمج نتيجة فحص اليوم مع السجل التراكمي — سهم فُحص اليوم يستبدل صفه
    القديم، أسهم لم تُفحص اليوم (الثلثان الآخران) تبقى بصفها القديم (لو
    موجود). أسهم لم تُفحص منذ أكتر من STALE_AFTER_DAYS تُستبعد من الناتج
    النهائي — بيانات قديمة جدًا لا تُستخدم في التنبؤ."""
    if OUTPUT_PATH.exists():
        old = pd.read_csv(OUTPUT_PATH)
        combined = pd.concat([old, new_df], ignore_index=True) if not new_df.empty else old
        combined = combined.drop_duplicates(subset=["ticker"], keep="last")
    else:
        combined = new_df

    if combined.empty:
        return combined

    cutoff = (date.today() - timedelta(days=STALE_AFTER_DAYS)).isoformat()
    fresh = combined[combined["last_checked_date"] >= cutoff].copy()
    fresh = fresh.sort_values("mean_abs_daily_pct", ascending=False).reset_index(drop=True)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    fresh.to_csv(OUTPUT_PATH, index=False)
    print(f"السجل التراكمي: {len(fresh)} سهم صالح (بيانات لآخر {STALE_AFTER_DAYS} يوم) -> {OUTPUT_PATH.resolve()}")
    return fresh


def top_volatile_tickers(n: int) -> list[str]:
    if not OUTPUT_PATH.exists():
        raise FileNotFoundError(f"{OUTPUT_PATH} غير موجود — شغّل scan_todays_third()/main() أولاً.")
    df = pd.read_csv(OUTPUT_PATH)
    return df["ticker"].head(n).tolist()


def main() -> None:
    new_df = scan_todays_third()
    merge_and_save(new_df)


if __name__ == "__main__":
    main()
