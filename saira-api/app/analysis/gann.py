"""أدوات جان الأساسية للمرحلة 0: مربع التسعة، سوينج، الدورات، الشمس.

مربع التسعة يحاول أولًا استخدام gann_square9.py الموجود في جذر المشروع
(نفس منطق committee_signals) ثم يعود للتنفيذ الداخلي المطابق للنموذج.
"""
from __future__ import annotations

import math
import sys

import numpy as np
import pandas as pd

from ..config import PROJECT_ROOT

# ---------------------------------------------------------------- مربع التسعة
try:  # جسر لأداتك الحالية إن وُجدت
    sys.path.insert(0, str(PROJECT_ROOT))
    import gann_square9 as _user_sq9  # type: ignore
except Exception:
    _user_sq9 = None


def sq9_levels(pivot: float, lo: float | None = None,
               hi: float | None = None) -> list[dict]:
    """مستويات مربع 9 بزيادات 45° (دورة كاملة = +2 على الجذر)."""
    if _user_sq9 is not None and hasattr(_user_sq9, "levels"):
        try:
            return _user_sq9.levels(pivot, lo, hi)  # واجهة أداتك إن توفرت
        except Exception:
            pass

    mul = 1.0
    while pivot * mul < 50:
        mul *= 10
        if mul > 1e7:
            break
    root = math.sqrt(pivot * mul)
    out: list[dict] = []
    n = 0.25
    while n <= 2.0001:
        for sign in (1, -1):
            r = root + sign * n
            if r <= 0:
                continue
            level = (r * r) / mul
            if lo is not None and level < lo:
                continue
            if hi is not None and level > hi:
                continue
            deg = int(round(n * 180)) * sign
            out.append({"deg": deg, "price": round(level, 4),
                        "cardinal": abs(deg) % 90 == 0})
        n += 0.25
    out.sort(key=lambda x: -x["price"])
    return out


# ---------------------------------------------------------------- سوينج جان
def swing_pivots(df: pd.DataFrame, m: int = 2) -> dict:
    """ارتكازات مؤشر الاتجاه الميكانيكي (انعكاس بعد m شموع متتالية)."""
    h, l, t = df["h"].values, df["l"].values, df["t"].values
    if len(df) < m + 2:
        return {"pivots": [], "direction": 0}
    direction, dn, up = 0, 0, 0
    hh, hh_i, ll, ll_i = h[0], 0, l[0], 0
    pivots: list[dict] = []
    for i in range(1, len(df)):
        if direction >= 0:
            if h[i] > hh:
                hh, hh_i, dn = h[i], i, 0
            dn = dn + 1 if l[i] < l[i - 1] else 0
            if direction == 0 and h[i] > h[i - 1]:
                direction = 1
            if dn >= m:
                pivots.append({"t": int(t[hh_i]), "price": float(hh),
                               "type": "top"})
                direction, ll, ll_i, dn, up = -1, l[i], i, 0, 0
        else:
            if l[i] < ll:
                ll, ll_i, up = l[i], i, 0
            up = up + 1 if h[i] > h[i - 1] else 0
            if up >= m:
                pivots.append({"t": int(t[ll_i]), "price": float(ll),
                               "type": "bottom"})
                direction, hh, hh_i, up, dn = 1, h[i], i, 0, 0
    return {"pivots": pivots, "direction": int(direction)}


# ---------------------------------------------------------------- المعايرة التلقائية الحقيقية
# كل أزرار "تلقائي" في الواجهة (مروحة جان، مربع 9، مربع 144، نجمة جان) كانت
# تحسب فقط (المدى الكلي ÷ عدد الشموع) — تقريب لا علاقة له بأنماط السهم
# الفعلية. المحاولة الأولى (قياس نسبة سعر/شمعة الأكثر ثباتًا عبر الارتكازات،
# بنفس منطق الماسح الكوكبي) فشلت تجريبيًا: الأسهم — على عكس الكواكب — ليس
# لها "معدل حركة يومي ثابت" طبيعي (تشتت > 0.7 على AAPL/AA، أي لا علاقة
# مستقرة إطلاقًا). البديل الصحيح: المشروع الرئيسي (src/) عنده بالفعل نظام
# معايرة حقيقي مُختبر ومُستخدم فعليًا في اللجنة الحية —
# gann_increment_selection.recommended_price_increment (زيادة سعرية من
# ATR/مستوى السعر) + gann_decision_system.calibrate_square9_angle/
# calibrate_gann_trendline_angle (يختبران كل زاوية مرشحة ضد ارتكازات السهم
# التاريخية فعليًا ويختاران الأعلى هيت-ريت، لا تقريبًا). هذه الدوال تُعيد
# استخدام تلك الوحدات مباشرة بدل اختراع منطق مواز.
def _import_src_modules():
    import sys
    from ..config import PROJECT_ROOT
    sys.path.insert(0, str(PROJECT_ROOT))
    import gann_increment_selection as _incr
    import gann_decision_system as _decision
    return _incr, _decision


def auto_price_increment(high: pd.Series, low: pd.Series, close: pd.Series) -> dict:
    """الزيادة السعرية الموصى بها (لمربع 9/144/النجمة) — من ATR ومستوى
    السعر الفعليين للسهم (Mikula ch.6 + تنقيح عبده بالتقلب)، لا تقريب."""
    incr, _ = _import_src_modules()
    return incr.recommended_price_increment(high, low, close)


def auto_square9_angle(high: pd.Series, low: pd.Series, close: pd.Series,
                       price_increment: float) -> dict:
    """أفضل زاوية مربع 9 لهذا السهم تحديدًا — كل زاوية مرشحة (0°/45°/.../315°)
    تُختبر فعليًا ضد ارتكازات السهم التاريخية، والأعلى هيت-ريت هو الفائز
    (calibrate_square9_angle، مستخدَم فعليًا في اللجنة الحية)."""
    _, decision = _import_src_modules()
    results = decision.calibrate_square9_angle(high, low, close, price_increment)
    if not results or results[0].hit_rate == 0:
        return {"angle": None, "hit_rate": 0.0, "pivots_tested": 0,
                "note": "لا زاوية أظهرت علاقة تاريخية حقيقية"}
    best = results[0]
    return {"angle": best.angle, "hit_rate": round(best.hit_rate, 3),
            "pivots_tested": best.total_pivots_tested,
            "all_angles": [{"angle": r.angle, "hit_rate": round(r.hit_rate, 3)}
                          for r in results]}


def auto_fan_angle(close: pd.Series, anchor_index: int, anchor_price: float,
                   direction: int = 1) -> dict:
    """أفضل زاوية مروحة جان (1×8 حتى 8×1) من نقطة ارتكاز محددة — كل زاوية
    قياسية تُختبر باختبار "لمس بلا اختراق" الحقيقي ضد حركة السعر الفعلية
    بعد الارتكاز (calibrate_gann_trendline_angle، فيه تصحيح موثّق 2026-07
    لبق كان بيفضّل أي زاوية أبطأ من السوق بلا داعٍ)."""
    _, decision = _import_src_modules()
    results = decision.calibrate_gann_trendline_angle(close, anchor_index, anchor_price, direction)
    if not results or results[0].hit_rate == 0:
        return {"angle_name": "1x1", "hit_rate": 0.0, "bars_tested": 0,
                "note": "لا زاوية أظهرت احترامًا تاريخيًا حقيقيًا — 1×1 الافتراضية الذهبية"}
    best = results[0]
    return {"angle_name": best.angle_name, "hit_rate": round(best.hit_rate, 3),
            "bars_tested": best.total_bars_tested,
            "all_angles": [{"angle_name": r.angle_name, "hit_rate": round(r.hit_rate, 3)}
                          for r in results]}


# ---------------------------------------------------------------- الدورات
def dominant_cycles(df: pd.DataFrame, top: int = 5,
                    max_n: int = 750) -> list[dict]:
    """أقوى الدورات بتحليل طيفي مباشر على الإغلاق بعد نزع الاتجاه الخطي."""
    y = df["c"].values[-max_n:].astype(float)
    n = len(y)
    if n < 40:
        return []
    x = np.arange(n)
    slope, icpt = np.polyfit(x, y, 1)
    yd = y - (icpt + slope * x)
    results = []
    for p in range(8, n // 2 + 1):
        w = 2 * np.pi * x / p
        a = float(np.dot(yd, np.cos(w))) * 2 / n
        b = float(np.dot(yd, np.sin(w))) * 2 / n
        results.append({"period": p, "amp": math.hypot(a, b),
                        "a": a, "b": b})
    results.sort(key=lambda r: -r["amp"])
    picked: list[dict] = []
    for r in results:
        if len(picked) >= top:
            break
        if any(abs(q["period"] - r["period"]) / r["period"] < 0.12
               for q in picked):
            continue
        picked.append({k: round(v, 5) if isinstance(v, float) else v
                       for k, v in r.items()})
    return picked


# ---------------------------------------------------------------- الشمس
def sun_longitude(t_epoch: int | float) -> float:
    """خط طول الشمس الجيوسنتري الظاهري بالدرجات (دقة ~0.01°)."""
    n = t_epoch / 86400 + 2440587.5 - 2451545.0
    big_l = (280.460 + 0.9856474 * n) % 360
    g = math.radians((357.528 + 0.9856003 * n) % 360)
    lam = (big_l + 1.915 * math.sin(g) + 0.020 * math.sin(2 * g)) % 360
    return lam + 360 if lam < 0 else lam


# ---------------------------------------------------------------- حاسبة مربع 144
def sq144_grid(pivot_price: float, pivot_t: int, price_unit: float,
               bar_seconds: int = 86400, direction: int = 1,
               divisions: tuple = (0.125, 0.25, 0.333, 0.375, 0.5,
                                   0.625, 0.667, 0.75, 0.875)) -> dict:
    """شبكة مربع 144: أثمان وأثلاث السعر والزمن + الزوايا القطرية.

    direction=1 يبني المربع فوق قاع، -1 تحت قمة.
    """
    size = 144.0
    price_span = size * price_unit * direction
    horizontals = [{"frac": 0.0, "price": round(pivot_price, 4), "corner": True}]
    for f in divisions:
        horizontals.append({"frac": f,
                            "price": round(pivot_price + price_span * f, 4),
                            "corner": False})
    horizontals.append({"frac": 1.0,
                        "price": round(pivot_price + price_span, 4),
                        "corner": True})

    verticals = [{"frac": f, "t": int(pivot_t + size * bar_seconds * f)}
                 for f in (0.0, 0.25, 0.333, 0.5, 0.667, 0.75, 1.0)]

    # الزوايا القطرية للمربع (1×1 صعودًا من الارتكاز وهبوطًا من الضلع المقابل)
    diagonals = [
        {"name": "1x1", "from": {"t": int(pivot_t), "price": pivot_price},
         "to": {"t": verticals[-1]["t"],
                "price": round(pivot_price + price_span, 4)}},
        {"name": "counter", "from": {"t": int(pivot_t),
                                     "price": round(pivot_price + price_span, 4)},
         "to": {"t": verticals[-1]["t"], "price": round(pivot_price, 4)}},
    ]
    return {"pivot": {"t": int(pivot_t), "price": pivot_price},
            "size": size, "price_unit": price_unit, "direction": direction,
            "horizontals": horizontals, "verticals": verticals,
            "diagonals": diagonals}


# ---------------------------------------------------------------- نجمة جان
def star_levels(pivot: float, kind: str = "hexagram",
                rotations: int = 2, lo: float | None = None,
                hi: float | None = None) -> list[dict]:
    """رؤوس نجمة جان على عجلة مربع 9.

    kind: pentagram (72°) أو hexagram (60° — نجمة داود).
    دورة كاملة 360° = +2 على الجذر، فكل درجة = 2/360 على الجذر.
    """
    step_deg = 72 if kind == "pentagram" else 60
    mul = 1.0
    while pivot * mul < 50:
        mul *= 10
        if mul > 1e7:
            break
    root = math.sqrt(pivot * mul)
    out: list[dict] = []
    max_deg = 360 * rotations
    deg = step_deg
    while deg <= max_deg:
        for sign in (1, -1):
            r = root + sign * deg * 2 / 360
            if r <= 0:
                continue
            level = (r * r) / mul
            if lo is not None and level < lo:
                continue
            if hi is not None and level > hi:
                continue
            out.append({"deg": deg * sign, "price": round(level, 4),
                        "point": (deg % 360) // step_deg or step_deg})
        deg += step_deg
    out.sort(key=lambda x: -x["price"])
    return out


# ---------------------------------------------------------------- موازنة السعر والزمن
def squaring_price_time(df: pd.DataFrame, swing_m: int = 2,
                        price_unit: float | None = None,
                        tolerance_bars: float = 1.5) -> dict:
    """جوهر منهج جان: تنبيه عندما "يتربّع" السعر مع الزمن — عدد الشموع منذ
    آخر ارتكاز سوينج يساوي مدى السعر منذ ذلك الارتكاز (بوحدة المعايرة).

    وحدة المعايرة الافتراضية = نفس autoUnit في الواجهة: مدى كامل البيانات
    مقسومًا على عدد الشموع — لكن تُفضَّل تمريرها من قيمة معايرة موثوقة
    (مثل sq144 price_unit أو نتيجة الماسح الكوكبي) عند توفرها.

    كل ارتكاز سوينج (ما عدا الأخير الجاري) يُفحص: "شموع منذ الارتكاز" مقابل
    "مدى السعر منذ الارتكاز ÷ الوحدة" — التطابق ضمن tolerance_bars يُعلَّم
    كـ "مربّع". لا يُنبئ باتجاه، فقط يعلّم النقطة التي رصدها جان كارتكاز
    محتمل قوي — التفسير (استمرار أو انعكاس) متروك للمؤشرات الأخرى (نفس مبدأ
    الخطة: "لا نتنبأ بالاتجاه منها بل نراقب سلوك السعر عندها").
    """
    sw = swing_pivots(df, swing_m)
    pivots = sw["pivots"]
    if len(pivots) < 2:
        return {"squares": [], "price_unit": price_unit}

    if price_unit is None:
        span = float(df["h"].max() - df["l"].min())
        price_unit = round(span / max(len(df), 1), 6) or 0.01

    t_arr = df["t"].values
    h_arr, l_arr = df["h"].values, df["l"].values
    n = len(df)

    squares: list[dict] = []
    for i, piv in enumerate(pivots[:-1]):
        i0 = int(np.searchsorted(t_arr, piv["t"]))
        if i0 >= n - 1:
            continue
        seg_hi = float(h_arr[i0:].max())
        seg_lo = float(l_arr[i0:].min())
        bars_elapsed = n - 1 - i0
        price_range_units = (seg_hi - seg_lo) / price_unit
        diff_bars = abs(bars_elapsed - price_range_units)
        if diff_bars <= tolerance_bars:
            squares.append({
                "pivot_t": int(piv["t"]), "pivot_price": piv["price"],
                "pivot_type": piv["type"],
                "bars_elapsed": bars_elapsed,
                "price_range_units": round(price_range_units, 2),
                "diff_bars": round(diff_bars, 2),
                "as_of_t": int(t_arr[-1]),
            })
    squares.sort(key=lambda s: s["diff_bars"])
    return {"squares": squares, "price_unit": price_unit,
            "tolerance_bars": tolerance_bars}


# ---------------------------------------------------------------- حاسبة الزمن الرئيسية
# Master Calculator for Time Periods (1955): مسطرة زمنية تُرسي من تاريخ
# القاع/القمة (أو IPO) وتُعلّم أيام الاستحقاق القياسية. لا تتنبأ بالاتجاه —
# فقط "مواعيد استحقاق" يُراقَب سلوك السعر عندها (نفس مبدأ squaring_price_time
# أعلاه: الملاحظة لا التنبؤ).
MASTER_TIME_PERIODS_DAYS: tuple[int, ...] = (
    30, 45, 60, 90, 120, 135, 180, 225, 270, 315, 360,
)


def master_time_periods(anchor_t: int, as_of_t: int,
                        periods_days: tuple = MASTER_TIME_PERIODS_DAYS) -> dict:
    """يبني تواريخ الاستحقاق (30/45/60/.../360 يومًا) من تاريخ ارتكاز واحد.

    كل موعد يُعلَّم بحالته: "past" (مضى) أو "upcoming" (قادم) نسبة لـ as_of_t
    (عادة آخر شمعة في البيانات) — التمييز يفيد الواجهة في رسم الماضي بخط
    رفيع والمستقبل بخط بارز، دون أي منطق تنبؤي إضافي هنا.
    """
    out = []
    for days in periods_days:
        t = anchor_t + days * 86400
        out.append({"days": days, "t": t, "upcoming": t >= as_of_t})
    return {"anchor_t": anchor_t, "as_of_t": as_of_t, "periods": out}


# ---------------------------------------------------------------- درجة الالتقاء
_W = {"sq9_cardinal": 2.0, "sq9": 1.0, "star": 1.5,
      "ret_50": 2.0, "ret": 1.0, "sq144_corner": 2.0, "sq144": 1.0}


def confluence(df: pd.DataFrame, swing_m: int = 2,
               star_kind: str = "hexagram", top: int = 8) -> dict:
    """محرك درجة الالتقاء: يجمع مستويات كل الأدوات ويعنقدها ويرتبها.

    الارتكاز = آخر ارتكاز سوينج (درس AXTI: لا القاع التاريخي المطلق)،
    وسماحة العنقدة = 0.4 × ATR(14).
    """
    lo, hi = float(df["l"].min()), float(df["h"].max())
    last_close = float(df["c"].iloc[-1])
    pad = (hi - lo) * 0.1

    sw = swing_pivots(df, swing_m)
    if sw["pivots"]:
        pivot = sw["pivots"][-1]
        pivot_price, pivot_t = pivot["price"], pivot["t"]
        pivot_kind = pivot["type"]
    else:
        pivot_price, pivot_t, pivot_kind = lo, int(df["t"].iloc[0]), "bottom"

    from .indicators import atr as _atr
    atr_val = float(_atr(df).iloc[-1]) or (hi - lo) / 100
    tol = 0.4 * atr_val

    levels: list[dict] = []
    for x in sq9_levels(pivot_price, lo - pad, hi + pad):
        levels.append({"price": x["price"],
                       "src": "sq9_cardinal" if x["cardinal"] else "sq9",
                       "tag": f"SQ9 {x['deg']:+d}°"})
    for x in star_levels(pivot_price, star_kind, 2, lo - pad, hi + pad):
        levels.append({"price": x["price"], "src": "star",
                       "tag": f"نجمة {x['deg']:+d}°"})
    span = hi - lo
    for k in range(0, 9):
        f = k / 8
        levels.append({"price": round(lo + span * f, 4),
                       "src": "ret_50" if k == 4 else "ret",
                       "tag": f"ثُمن {f*100:.1f}%"})
    unit = round(span / len(df), 6) or 0.01
    grid = sq144_grid(pivot_price, pivot_t, unit,
                      direction=1 if pivot_kind == "bottom" else -1)
    for x in grid["horizontals"]:
        if lo - pad <= x["price"] <= hi + pad:
            levels.append({"price": x["price"],
                           "src": "sq144_corner" if x["corner"] else "sq144",
                           "tag": f"م144 {x['frac']*100:.1f}%"})

    # عنقدة بسقف عرض: العنقود لا يتسع لأكثر من tol من أول عضو فيه
    # (يمنع التسلسل المتعدي الذي يبتلع نصف الشارت)
    levels.sort(key=lambda x: x["price"])
    clusters: list[dict] = []
    for lv in levels:
        if clusters and lv["price"] - clusters[-1]["members"][0]["price"] <= tol:
            clusters[-1]["members"].append(lv)
        else:
            clusters.append({"members": [lv]})

    _family = lambda src: src.split("_")[0]  # sq9_cardinal→sq9, ret_50→ret
    for cl in clusters:
        prices = [m["price"] for m in cl["members"]]
        cl["price"] = round(sum(prices) / len(prices), 4)
        # الالتقاء = اتفاق أدوات مختلفة: كل عائلة تصوّت مرة بأعلى وزن لها
        best_per_family: dict[str, float] = {}
        for m in cl["members"]:
            fam = _family(m["src"])
            best_per_family[fam] = max(best_per_family.get(fam, 0), _W[m["src"]])
        cl["score"] = round(sum(best_per_family.values()), 2)
        cl["families"] = len(best_per_family)
        cl["sources"] = [m["tag"] for m in cl["members"]]
        cl["distance_pct"] = round((cl["price"] / last_close - 1) * 100, 2)
        del cl["members"]
    # التقاء فعلي = عائلتان مختلفتان على الأقل
    clusters = [c for c in clusters if c["families"] >= 2]
    clusters.sort(key=lambda c: (-c["score"], abs(c["distance_pct"])))
    return {"pivot": {"price": pivot_price, "t": pivot_t, "type": pivot_kind,
                      "source": "آخر ارتكاز سوينج"},
            "atr": round(atr_val, 4), "tolerance": round(tol, 4),
            "last_close": last_close, "clusters": clusters[:top]}
