"""الماسح الكوكبي (Planetary Scanner) — نسخة عبده.

فكرتان مستقلتان تحلان مشكلة تحيز الكواكب البطيئة:

1. الاحترام بالانعكاس (Reversal Test)
   لكل زوج ارتكازات متتالي: نسبة |Δسعر| / |Δخط طول|.
   إذا كان الكوكب متحكمًا، تتقارب النسبة عبر الأزواج.
   المقياس = 1 - MAD/الوسيط (تشتت متين).
   ميزتها الكبرى: تحدد الوحدة السعرية تلقائيًا (الوسيط)، بلا مسح.

2. الاحترام بالمحاذاة (Alignment Test)
   لكل حركة قاع→قمة أو العكس، نأخذ نقطتين بفارق 6° على خط طول الكوكب
   ونقارن اتجاه السعر باتجاه الكوكب. الحركات > 2×ATR = رئيسية بوزن 2،
   الباقي بوزن 1.

المخرَج: لكل كوكب ثقة مدمجة مرتّبة تنازليًا.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import astro, gann
from .indicators import atr as _atr

_PLANETS = ("mercury", "venus", "mars", "jupiter", "saturn",
            "uranus", "neptune", "pluto")
_CENTERS = ("geo", "helio")
_STEP_DEG = 6.0


@dataclass
class ScanConfig:
    min_pivots: int = 8
    top_planets: int = 5
    reversal_weight: float = 0.6
    alignment_weight: float = 0.4


def _lon_series(planet: str, center: str,
                times: list[int]) -> np.ndarray | None:
    if center == "helio" and planet in ("sun", "moon"):
        return None
    fn = astro.helio_longitude if center == "helio" else astro.geo_longitude
    return np.array([fn(planet, t) for t in times], dtype=float)


def _wrap_delta(a: float, b: float) -> float:
    return (a - b + 540) % 360 - 180


def _reversal_test(pivots: list[dict], lons: np.ndarray,
                   min_lon_move_deg: float = 3.0) -> dict | None:
    """يقيس ثبات نسبة |Δسعر|/|Δخط طول| عبر أزواج الارتكازات المتتالية.

    شروط رفض الأزواج (لمنع تحيز الكواكب البطيئة):
    - حركة الكوكب < min_lon_move_deg (يحوّل حركة 0.5° إلى ضجيج مكبَّر)
    - حركة > 179.5° (غموض اتجاه)
    - حركة السعر تافهة (< 1e-6)
    - بعد التصفية، إذا بقيت < 5 أزواج، الكوكب غير قابل للحكم عليه.
    """
    prices = np.array([p["price"] for p in pivots], dtype=float)
    ratios = []
    for i in range(1, len(pivots)):
        dprice = abs(prices[i] - prices[i-1])
        dlon = abs(_wrap_delta(lons[i], lons[i-1]))
        if dlon < min_lon_move_deg or dlon > 179.5 or dprice < 1e-6:
            continue
        ratios.append(dprice / dlon)
    if len(ratios) < 5:
        return None
    ratios = np.array(ratios)
    median = float(np.median(ratios))
    if median <= 0:
        return None
    mad = float(np.median(np.abs(ratios - median)))
    dispersion = mad / median
    confidence = max(0.0, min(1.0, 1 - dispersion / 0.5))
    return {
        "unit_price_median": round(median, 4),
        "unit_price_mad": round(mad, 4),
        "dispersion": round(dispersion, 3),
        "pairs_used": len(ratios),
        "pairs_total": len(pivots) - 1,
        "confidence": round(confidence, 3),
    }


def _alignment_test(df: pd.DataFrame, pivots: list[dict],
                    planet: str, center: str) -> dict | None:
    if center == "helio" and planet in ("sun", "moon"):
        return None
    fn = astro.helio_longitude if center == "helio" else astro.geo_longitude
    if len(pivots) < 3:
        return None

    t_arr = df["t"].values
    piv_idx = [min(int(np.searchsorted(t_arr, p["t"])), len(df) - 1)
               for p in pivots]
    atr_series = _atr(df)

    scores, weights = [], []
    for i in range(1, len(pivots)):
        i_start, i_end = piv_idx[i-1], piv_idx[i]
        if i_end - i_start < 3:
            continue
        seg_idx = list(range(i_start, i_end + 1))
        seg_lons = np.array([fn(planet, int(t_arr[j])) for j in seg_idx])
        base_lon = seg_lons[0]
        deltas = np.array([abs(_wrap_delta(sl, base_lon)) for sl in seg_lons])
        reach = np.where(deltas >= _STEP_DEG)[0]
        if len(reach) == 0:
            continue
        k = int(reach[0])
        planet_dir = np.sign(_wrap_delta(seg_lons[k], seg_lons[0]))
        p0 = df["c"].iloc[seg_idx[0]]
        p1 = df["c"].iloc[seg_idx[k]]
        price_dir = np.sign(p1 - p0)
        atr_val = atr_series.iloc[i_end]
        if not math.isfinite(atr_val) or atr_val <= 0:
            atr_val = 1.0
        move_size = abs(pivots[i]["price"] - pivots[i-1]["price"])
        weight = 2.0 if move_size >= 2 * atr_val else 1.0
        scores.append(float(planet_dir * price_dir))
        weights.append(weight)

    if len(scores) < 3:
        return None
    scores_arr = np.array(scores)
    weights_arr = np.array(weights)
    agreement = float(np.average(scores_arr, weights=weights_arr))
    return {
        "moves_tested": len(scores),
        "agreement": round(agreement, 3),
        "aligned_moves": int(np.sum(scores_arr > 0)),
        "opposed_moves": int(np.sum(scores_arr < 0)),
        "confidence": round((agreement + 1) / 2, 3),
    }


def scan_symbol(df: pd.DataFrame, cfg: ScanConfig | None = None) -> dict:
    cfg = cfg or ScanConfig()
    sw = gann.swing_pivots(df, m=2)
    pivots = sw["pivots"]
    if len(pivots) < cfg.min_pivots:
        return {"error": f"ارتكازات غير كافية ({len(pivots)}/{cfg.min_pivots})",
                "planets": []}

    times = [p["t"] for p in pivots]
    results = []
    for planet in _PLANETS:
        for center in _CENTERS:
            lons = _lon_series(planet, center, times)
            if lons is None:
                continue
            reversal = _reversal_test(pivots, lons)
            alignment = _alignment_test(df, pivots, planet, center)
            if reversal is None and alignment is None:
                continue
            r_conf = reversal["confidence"] if reversal else 0
            a_conf = alignment["confidence"] if alignment else 0
            if reversal is None:
                combined = a_conf * 0.7
            elif alignment is None:
                combined = r_conf * 0.7
            else:
                combined = (r_conf * cfg.reversal_weight
                            + a_conf * cfg.alignment_weight)
            results.append({
                "planet": planet, "center": center,
                "combined_confidence": round(combined, 3),
                "reversal": reversal, "alignment": alignment,
            })

    results.sort(key=lambda r: -r["combined_confidence"])
    return {
        "pivots_analyzed": len(pivots),
        "method": "reversal + alignment (اقتراح عبده)",
        "planets": results[:cfg.top_planets],
    }


def planetary_grid(df: pd.DataFrame, planet: str, center: str,
                   unit_price: float, n_lines_per_side: int = 4) -> dict:
    """يبني خطوط الكوكب بالوحدة المكتشفة من اختبار الانعكاس."""
    if unit_price <= 0:
        raise ValueError("unit_price يجب أن تكون موجبة")
    fn = astro.helio_longitude if center == "helio" else astro.geo_longitude

    sw = gann.swing_pivots(df, m=2)
    if not sw["pivots"]:
        raise ValueError("لا ارتكاز سوينج متاح")
    anchor = sw["pivots"][-1]
    anchor_lon = fn(planet, anchor["t"])
    anchor_price = anchor["price"]

    lo, hi = float(df["l"].min()), float(df["h"].max())
    pad = (hi - lo) * 0.1
    lo_p, hi_p = lo - pad, hi + pad
    period = 360.0 * unit_price

    step = max(1, len(df) // 400)
    sample = df.iloc[::step]
    times = sample["t"].astype(int).tolist()
    lons = [fn(planet, t) for t in times]

    mid_price = (lo + hi) / 2
    k_center = int(round((mid_price - anchor_price) / period))

    series = []
    for k in range(k_center - n_lines_per_side, k_center + n_lines_per_side + 1):
        segments, cur, prev_price = [], [], None
        for t, lon in zip(times, lons):
            lon_delta = _wrap_delta(lon, anchor_lon)
            price = anchor_price + lon_delta * unit_price + k * period
            if not (lo_p <= price <= hi_p):
                if len(cur) > 1:
                    segments.append(cur)
                cur, prev_price = [], None
                continue
            if prev_price is not None and abs(price - prev_price) > period * 0.4:
                if len(cur) > 1:
                    segments.append(cur)
                cur = []
            cur.append({"t": t, "price": round(price, 4)})
            prev_price = price
        if len(cur) > 1:
            segments.append(cur)
        if segments:
            series.append({"k": k, "segments": segments})

    return {
        "planet": planet, "center": center, "unit_price": unit_price,
        "anchor": {"t": anchor["t"], "price": anchor_price,
                   "lon": round(anchor_lon, 2)},
        "series": series,
    }


# ---------------------------------------------------------------- شبكة الخطوط المترابطة
# مجلد 1، ملاحظة 1: إذا أثّر خط تربيع كوكبٍ ما على السهم، تُرسم تلقائيًا
# بقية خطوطه (تثليث/مقابلة). الزوايا الكلاسيكية الخمس (سداسي مستثنى من
# القائمة الأساسية في الملاحظة الأصلية، لكنه مضاف هنا لأن star_levels()
# نفسه يدعم 60° أصلًا في هذا المشروع — التناسق مع باقي الأدوات أولى من
# الالتزام الحرفي بقائمة لم تستثنِه لسبب معلوم) + نصف السداسي 30° ونصف
# التربيع 45° (زوايا ثانوية شائعة في التنجيم المالي لجان، أضعف تأثيرًا من
# الخمسة الأساسية لكنها مفيدة لرصد نقاط توتر مبكرة).
ASPECT_ANGLES_DEG: tuple[float, ...] = (0.0, 30.0, 45.0, 60.0, 90.0, 120.0, 180.0)


def connected_lines(df: pd.DataFrame, planet: str, center: str,
                    unit_price: float, n_lines_per_side: int = 2) -> dict:
    """يبني شبكة الخطوط المترابطة (قِران/سداسي/تربيع/تثليث/مقابلة) لكوكبٍ
    واحد فائز في الماسح — بدل خط واحد فقط، طبقًا لملاحظة 1 (مجلد 1):
    "إذا أثّر خط تربيع كوكبٍ ما، تُرسم تلقائيًا بقية خطوطه".

    كل زاوية تُبنى بنفس منطق planetary_grid لكن بإزاحة الارتكاز بمقدار
    الزاوية (بوحدة السعر) قبل تكرار الدورة الكاملة — نفس الارتكاز والوحدة
    المكتشفة، فقط "زوايا الميلاد" المختلفة لشبكة الخط الواحد.
    """
    if unit_price <= 0:
        raise ValueError("unit_price يجب أن تكون موجبة")
    fn = astro.helio_longitude if center == "helio" else astro.geo_longitude

    sw = gann.swing_pivots(df, m=2)
    if not sw["pivots"]:
        raise ValueError("لا ارتكاز سوينج متاح")
    anchor = sw["pivots"][-1]
    anchor_lon = fn(planet, anchor["t"])
    anchor_price = anchor["price"]

    lo, hi = float(df["l"].min()), float(df["h"].max())
    pad = (hi - lo) * 0.1
    lo_p, hi_p = lo - pad, hi + pad
    period = 360.0 * unit_price

    step = max(1, len(df) // 400)
    sample = df.iloc[::step]
    times = sample["t"].astype(int).tolist()
    lons = [fn(planet, t) for t in times]

    aspects = []
    for deg in ASPECT_ANGLES_DEG:
        aspect_price = anchor_price + deg * unit_price
        mid_price = (lo + hi) / 2
        k_center = int(round((mid_price - aspect_price) / period))

        series = []
        for k in range(k_center - n_lines_per_side, k_center + n_lines_per_side + 1):
            segments, cur, prev_price = [], [], None
            for t, lon in zip(times, lons):
                lon_delta = _wrap_delta(lon, anchor_lon)
                price = aspect_price + lon_delta * unit_price + k * period
                if not (lo_p <= price <= hi_p):
                    if len(cur) > 1:
                        segments.append(cur)
                    cur, prev_price = [], None
                    continue
                if prev_price is not None and abs(price - prev_price) > period * 0.4:
                    if len(cur) > 1:
                        segments.append(cur)
                    cur = []
                cur.append({"t": t, "price": round(price, 4)})
                prev_price = price
            if len(cur) > 1:
                segments.append(cur)
            if segments:
                series.append({"k": k, "segments": segments})
        if series:
            aspects.append({"deg": deg, "series": series})

    return {
        "planet": planet, "center": center, "unit_price": unit_price,
        "anchor": {"t": anchor["t"], "price": anchor_price,
                   "lon": round(anchor_lon, 2)},
        "aspects": aspects,
    }


# ---------------------------------------------------------------- أكثر علاقات الكواكب تأثيرًا
# اختبار مستقل عن scan_symbol (اللي يختبر كوكبًا واحدًا بمفرده): هنا نختبر
# أزواج الكواكب معًا — لكل زوج ولكل زاوية في ASPECT_ANGLES_DEG، نحسب عدد
# ارتكازات السوينج (قمم/قيعان) التي وقعت ضمن سماحية قريبة من لحظة تحقق تلك
# الزاوية بين الكوكبين، مقابل ما هو متوقع بالصدفة على مدى عشوائي — فيعطي
# ترتيبًا لأكثر العلاقات (زوج كوكبين + زاوية) ترافقًا مع انعكاسات فعلية.
_ORB_INFLUENCE_DEG = 3.0


def _pair_aspect_hits(times_all: list[int], lon_a: np.ndarray, lon_b: np.ndarray,
                      deg: float, pivot_times: set[int], orb: float) -> tuple[int, int]:
    """يعيد (عدد التطابقات مع ارتكاز فعلي، إجمالي مرات تحقق الزاوية)."""
    sep = np.abs(np.vectorize(_wrap_delta)(lon_a - lon_b, 0.0))
    # المسافة الزاوية بين الكوكبين (0-180) مقارنة بالزاوية المستهدفة، بمراعاة
    # أن deg قد يكون أكبر من 180 (لن يحدث هنا لأن كل قيم ASPECT_ANGLES_DEG <= 180)
    hit_mask = np.abs(sep - deg) <= orb
    hit_idx = np.where(hit_mask)[0]
    if len(hit_idx) == 0:
        return 0, 0
    total = len(hit_idx)
    matched = 0
    for i in hit_idx:
        t = times_all[i]
        # أقرب ارتكاز فعلي ضمن نافذة ±5 أيام من لحظة تحقق الزاوية
        if any(abs(t - pt) <= 5 * 86400 for pt in pivot_times):
            matched += 1
    return matched, total


def aspect_influence_scan(df: pd.DataFrame, top: int = 10) -> dict:
    """يمسح كل أزواج الكواكب × كل الزوايا في ASPECT_ANGLES_DEG، ويرتبها
    حسب نسبة تطابق تحقق الزاوية مع ارتكازات سوينج فعلية على السهم — إجابة
    مباشرة على "أي علاقة كوكبية الأكثر تأثيرًا على هذا السهم تحديدًا"،
    بعكس scan_symbol الذي يقيّم كل كوكب بمفرده بلا اعتبار لعلاقته بكوكب آخر.
    """
    sw = gann.swing_pivots(df, m=2)
    pivots = sw["pivots"]
    if len(pivots) < 5:
        return {"error": f"ارتكازات غير كافية ({len(pivots)}/5)", "pairs": []}
    pivot_times = {int(p["t"]) for p in pivots}

    t_arr = df["t"].astype(int).to_numpy()
    step = max(1, len(df) // 800)
    times_all = t_arr[::step].tolist()

    lon_cache: dict[tuple[str, str], np.ndarray] = {}

    def lons_for(planet: str, center: str) -> np.ndarray | None:
        key = (planet, center)
        if key in lon_cache:
            return lon_cache[key]
        arr = _lon_series(planet, center, times_all)
        lon_cache[key] = arr
        return arr

    all_planets = ("sun", "moon") + _PLANETS
    results = []
    for i, pa in enumerate(all_planets):
        for pb in all_planets[i + 1:]:
            for center in _CENTERS:
                lon_a = lons_for(pa, center)
                lon_b = lons_for(pb, center)
                if lon_a is None or lon_b is None:
                    continue
                for deg in ASPECT_ANGLES_DEG:
                    matched, total = _pair_aspect_hits(
                        times_all, lon_a, lon_b, deg, pivot_times, _ORB_INFLUENCE_DEG)
                    if total < 2:
                        continue
                    hit_rate = matched / total
                    results.append({
                        "planet_a": pa, "planet_b": pb, "center": center,
                        "aspect_deg": deg, "occurrences": total,
                        "matched_pivots": matched,
                        "hit_rate": round(hit_rate, 3),
                    })

    results.sort(key=lambda r: (-r["hit_rate"], -r["occurrences"]))
    return {
        "pivots_analyzed": len(pivots),
        "pairs": results[:top],
    }
