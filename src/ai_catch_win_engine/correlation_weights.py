"""
ai_catch_win_engine/correlation_weights.py — تعلّم من الارتباط (توجيه عبده
2026-07-18: "لو لم تنجح طريقة استخدم ما تم اثباته. اكمل بطريقة تعلم من
الارتباط"). بدل معيار رفض/قبول ثنائي صارم (permutation+control+Bonferroni،
المستخدَم في كل ملفات ai_catch_win_engine الأخرى)، هذا الملف يحسب **وزن استمراري**
لكل كوكب مع كل سهم من السجل المُثبَت فعليًا (القسم 9.11 من
Astro_Wave_Decomposition_Methodology.md)، ثم يدمج كل الكواكب معًا في تنبؤ
مرجّح واحد — خطوة انتقالية بين الإثبات الإحصائي الصارم (ai_catch_win_engine
الحالية) والنموذج الكامل (feature_table.py + ML مستقبلي).

**الفكرة**: بدل "هل β معنوي إحصائيًا؟" (نعم/لا)، نسأل "كم وزن هذا الكوكب في
تفسير حركة هذا السهم تحديدًا؟" (β نفسه بوحدة نقطة/درجة، مأخوذ مباشرة من
fit_harmonic — لا حاجة لإعادة اختباره إحصائيًا لأنه مُثبَت مسبقًا في السجل).
التنبؤ المركّب = Σ (β_i × Δθ_i المتوقعة) لكل كوكب i أُثبت له تأثير على هذا
السهم بالذات — نفس فلسفة القسم 6 من الوثيقة المرجعية (الدمج المرجّح
الموقّع)، لكن بأوزان مُشتقة من التجارب الفعلية المحفوظة، لا نظرية.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

sys.path.insert(0, ".")

from full_universe_analysis import build_local_ticker_index, load_local_history
from gann_astrology import get_planet_longitude

from ai_catch_win_engine.birth_chart import compute_ascendant
from ai_catch_win_engine.effect_size import fit_harmonic
from ai_catch_win_engine.natal_dates import get_natal_date

# السجل المُثبَت (القسم 9.11 من الوثيقة المرجعية) — كل صف هو (سهم, كوكب)
# عبر البوابات الإحصائية بنجاح فعلي موثّق، بأوزان β محسوبة سابقًا. يُستخدم
# هنا كنقطة انطلاق مباشرة بدل إعادة تشغيل كل الاختبارات الإحصائية من الصفر.
PROVEN_PLANET_TICKER_PAIRS: list[dict] = [
    {"ticker": "AAPL", "planet": "mars", "beta": None, "r_squared": 0.4984,
     "window_start": "1999-08-12", "window_end": "2004-04-23"},
    {"ticker": "WMT", "planet": "mars", "beta": None, "r_squared": 0.3536,
     "window_start": "1999-08-12", "window_end": "2004-04-23"},
    {"ticker": "COST", "planet": "mars", "beta": None, "r_squared": 0.3757,
     "window_start": "1999-08-12", "window_end": "2004-04-23"},
    {"ticker": "APTV", "planet": "mars", "beta": None, "r_squared": 0.5103,
     "window_start": "2024-09-01", "window_end": "2026-07-18"},
    {"ticker": "ORCL", "planet": "mars", "beta": None, "r_squared": 0.3114,
     "window_start": "2021-11-05", "window_end": "2026-07-18"},
    {"ticker": "MAR", "planet": "saturn", "beta": None, "r_squared": 0.4324,
     "window_start": "2019-03-09", "window_end": "2026-07-18"},
    {"ticker": "BAX", "planet": "venus", "beta": None, "r_squared": 0.3343,
     "window_start": "2025-01-04", "window_end": "2026-07-18"},
    {"ticker": "GM", "planet": "venus", "beta": None, "r_squared": 0.6010,
     "window_start": "2025-01-04", "window_end": "2026-07-18"},
    {"ticker": "WMT", "planet": "sun", "beta": None, "r_squared": 0.3848,
     "window_start": "2025-01-04", "window_end": "2026-07-18"},
    {"ticker": "LIN", "planet": "mercury", "beta": None, "r_squared": 0.5821,
     "window_start": "2025-01-04", "window_end": "2026-07-18"},
    {"ticker": "ALL", "planet": "mercury", "beta": None, "r_squared": 0.1298,
     "window_start": "2025-01-04", "window_end": "2026-07-18"},
]


@dataclass(frozen=True)
class PlanetWeight:
    ticker: str
    planet: str
    beta_points_per_degree: float
    phase_rad: float
    r_squared: float
    window_start: date
    window_end: date


def recompute_weight(ticker: str, planet: str, window_start: date, window_end: date) -> PlanetWeight | None:
    """
    يعيد حساب β وphase الفعليين (fit_harmonic) لزوج (سهم، كوكب) من السجل
    المُثبَت — لا اختبار تباديل/ضبط هنا (مُثبَت مسبقًا)، فقط استخراج المعامل
    نفسه لاستخدامه كوزن في التنبؤ المركّب.
    """
    idx = build_local_ticker_index()
    hist = load_local_history(ticker, idx)
    if hist is None:
        return None
    win = hist.loc[str(window_start):str(window_end)]
    if len(win) < 30:
        return None

    natal_date = get_natal_date(ticker)
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
    except ValueError:
        return None

    return PlanetWeight(
        ticker=ticker, planet=planet, beta_points_per_degree=fit.beta_points_per_degree,
        phase_rad=fit.phase_rad, r_squared=fit.r_squared,
        window_start=window_start, window_end=window_end,
    )


def build_weight_table() -> pd.DataFrame:
    """يعيد حساب كل الأوزان في PROVEN_PLANET_TICKER_PAIRS دفعة واحدة."""
    rows = []
    for entry in PROVEN_PLANET_TICKER_PAIRS:
        w = recompute_weight(entry["ticker"], entry["planet"],
                              date.fromisoformat(entry["window_start"]),
                              date.fromisoformat(entry["window_end"]))
        if w is None:
            continue
        rows.append({
            "ticker": w.ticker, "planet": w.planet,
            "beta_points_per_degree": round(w.beta_points_per_degree, 5),
            "phase_deg": round(np.degrees(w.phase_rad), 2),
            "r_squared": round(w.r_squared, 4),
            "window_start": w.window_start.isoformat(), "window_end": w.window_end.isoformat(),
        })
    return pd.DataFrame(rows)


def predict_composite_change(ticker: str, planets_for_ticker: pd.DataFrame,
                              from_date: date, to_date: date) -> float:
    """
    التنبؤ المركّب (القسم 6 من الوثيقة المرجعية): صافي التغيّر المتوقع =
    Σ β_i × [longitude_i(to_date) - longitude_i(from_date)] لكل كوكب i له
    وزن مُثبَت لهذا السهم تحديدًا. مبنية على أوزان القسم 9.11 فقط (لا يُعاد
    اختبارها إحصائيًا هنا) — أداة استكشافية/تنبؤية، لا اختبار فرضية.
    """
    rows = planets_for_ticker[planets_for_ticker["ticker"] == ticker]
    if rows.empty:
        raise ValueError(f"لا وزن مُثبَت لـ{ticker} في الجدول")

    natal_date = get_natal_date(ticker)
    natal_ascendant = compute_ascendant(natal_date).ascendant_longitude

    net_change = 0.0
    for _, row in rows.iterrows():
        planet = row["planet"]
        beta = row["beta_points_per_degree"]
        lon_from = (get_planet_longitude(planet, from_date) - natal_ascendant) % 360
        lon_to = (get_planet_longitude(planet, to_date) - natal_ascendant) % 360
        delta_theta = lon_to - lon_from
        if delta_theta > 180:
            delta_theta -= 360
        elif delta_theta < -180:
            delta_theta += 360
        net_change += beta * delta_theta

    return net_change


if __name__ == "__main__":
    weights = build_weight_table()
    print(weights.to_string(index=False))

    out_path = "../runs/ai_catch_win_engine/proven_weights_20260718.csv"
    weights.to_csv(out_path, index=False)
    print(f"\nWrote weight table to {out_path}")

    print("\n--- مثال تنبؤ مركّب (WMT، من اليوم حتى +30 يوم) ---")
    today = date.today()
    future = today + timedelta(days=30)
    try:
        wmt_planets = weights[weights["ticker"] == "WMT"]["planet"].tolist()
        change = predict_composite_change("WMT", weights, today, future)
        print(f"WMT: صافي التغيّر المتوقع خلال 30 يوم = {change:+.2f} نقطة "
              f"(دمج كل الكواكب المُثبَتة لهذا السهم: {wmt_planets})")
    except ValueError as exc:
        print(exc)
