"""
yahoo_fetch.py — جالب بيانات مباشر من Yahoo Finance chart API (بديل لمكتبة
yfinance اللي بتفشل محليًا: النسخة 1.5.1 بترجع "possibly delisted" لكل الرموز
رغم إن الشبكة شغالة و Yahoo عنده الداتا — تأكد 2026-07-16 بأن الاستعلام المباشر
لنفس الـ endpoint بيرجع الداتا تمام).

للاستخدام البحثي في الـ lab: بيجيب OHLCV يومي أو intraday، وبيدمج الفجوة بين
الداتا المحلية (اللي بتنتهي عند تاريخ الـ dump) وآخر جلسة. مش بديل لمسار الإنتاج
اليومي (اللي بيشتغل على GitHub Actions حيث yfinance متاح) — ده لسد فجوة الجهاز
المحلي فقط.
"""
from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone

import pandas as pd

_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range={rng}&interval={interval}"
_HEADERS = {"User-Agent": "Mozilla/5.0"}


def fetch_ohlc(symbol: str, rng: str = "1y", interval: str = "1d", timeout: int = 25) -> pd.DataFrame:
    """
    يرجّع DataFrame بأعمدة Open/High/Low/Close/Volume وفهرس تاريخ/وقت (UTC-naive،
    نفس شكل full_universe_analysis.load_local_history). يرمي استثناء عند الفشل بدل
    إرجاع فاضي صامت.

    rng: '1d','5d','1mo','3mo','6mo','1y','2y','5y','max' حسب Yahoo.
    interval: '1d' (يومي) أو '5m','15m','60m' (intraday — متاح لآخر ~60 يوم فقط).
    """
    url = _CHART_URL.format(symbol=symbol, rng=rng, interval=interval)
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read())

    result = payload.get("chart", {}).get("result")
    if not result:
        err = payload.get("chart", {}).get("error")
        raise ValueError(f"Yahoo returned no data for {symbol}: {err}")
    res = result[0]
    timestamps = res.get("timestamp")
    if not timestamps:
        raise ValueError(f"Yahoo returned no timestamps for {symbol} (range={rng}, interval={interval})")
    q = res["indicators"]["quote"][0]

    rows = []
    intraday = interval.endswith(("m", "h"))
    for i, t in enumerate(timestamps):
        c = q["close"][i]
        if c is None:
            continue
        ts = datetime.fromtimestamp(t, tz=timezone.utc).replace(tzinfo=None)
        idx = ts if intraday else ts.normalize() if hasattr(ts, "normalize") else pd.Timestamp(ts).normalize()
        rows.append({
            "idx": pd.Timestamp(idx),
            "Open": q["open"][i], "High": q["high"][i], "Low": q["low"][i],
            "Close": c, "Volume": q["volume"][i],
        })
    df = pd.DataFrame(rows).set_index("idx")
    df.index.name = "DATE"
    return df


def fetch_instrument_type(symbol: str, timeout: int = 25) -> str | None:
    """
    يرجّع نوع الأداة المالية ("EQUITY"، "ETF"، "MUTUALFUND"، إلخ) من نفس
    v8/finance/chart endpoint المستخدَم في fetch_ohlc أعلاه (حقل
    meta.instrumentType) — بلا استدعاء endpoint إضافي أو مخاطرة crumb/cookie
    زيادة، لأنه نفس الاستدعاء المؤكَّد شغّال بالفعل (راجع docstring الملف).
    يرجّع None (لا يرمي استثناء) لو الحقل غير موجود — الاستثناءات الحقيقية
    (فشل الشبكة/رمز غير موجود) لسه بتتفرقع زي fetch_ohlc بالظبط.
    """
    url = _CHART_URL.format(symbol=symbol, rng="5d", interval="1d")
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read())

    result = payload.get("chart", {}).get("result")
    if not result:
        err = payload.get("chart", {}).get("error")
        raise ValueError(f"Yahoo returned no data for {symbol}: {err}")
    return result[0].get("meta", {}).get("instrumentType")


def merged_daily_history(symbol: str, local_hist: pd.DataFrame | None, rng: str = "6mo") -> pd.DataFrame:
    """
    يدمج الداتا المحلية (لو متاحة) مع آخر جلسات Yahoo لسد الفجوة حتى اليوم. صفوف
    Yahoo بتغلب عند التداخل (أحدث/مُعدَّلة)، والنتيجة مرتّبة بلا تكرار تواريخ.
    """
    yahoo = fetch_ohlc(symbol, rng=rng, interval="1d")
    if local_hist is None or local_hist.empty:
        return yahoo
    combined = pd.concat([local_hist[["Open", "High", "Low", "Close", "Volume"]], yahoo])
    combined = combined[~combined.index.duplicated(keep="last")].sort_index()
    return combined


if __name__ == "__main__":
    import sys
    symbol = sys.argv[1].upper() if len(sys.argv) > 1 else "AXTI"
    rng = sys.argv[2] if len(sys.argv) > 2 else "3mo"
    interval = sys.argv[3] if len(sys.argv) > 3 else "1d"
    df = fetch_ohlc(symbol, rng=rng, interval=interval)
    print(f"{symbol} {interval} {rng}: {len(df)} rows | {df.index.min()} -> {df.index.max()}")
    print(df.tail(12).to_string())
