"""Saira Trading API — خادم المرحلة 0.

تشغيل:  uvicorn app.main:app --port 8787 --reload
التوثيق التفاعلي: http://127.0.0.1:8787/docs
"""
from __future__ import annotations

import importlib
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from . import pipeline_bridge
from .analysis import gann, indicators
from .config import DATA_DIR, load_allowlist, load_eligible_tickers
from .data import store

app = FastAPI(
    title="Saira Trading API",
    version="0.1.0",
    description="خلفية منصة Saira Terminal — شموع، مؤشرات، أدوات جان، لجنة الإشارات",
)

# CORS مفتوح للجميع عمدًا: لا كوكيز ولا مصادقة هنا، فلا خطر تسريب جلسة —
# فقط بيانات سوق عامة القراءة، وواجهة الويب (Cloudflare Pages) وتطبيقا
# Tauri/Capacitor يتصلون من أصول مختلفة تمامًا فلا توجد قائمة أصل واحدة تكفي.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


def _need_symbol(symbol: str, tf: str, limit: int):
    bars = store.candles(symbol, tf, limit)
    if not bars:
        raise HTTPException(404, f"لا بيانات للرمز {symbol} — استورد أولًا عبر /import/stooq")
    return bars


# ---------------------------------------------------------------- عام
@app.get("/health")
def health():
    return {"ok": True, "service": "saira-api", "phase": 0}


@app.get("/symbols")
def symbols(q: str | None = None):
    """الرموز المخزنة مع حالة القائمة الأخلاقية لكل رمز.

    q: فلترة اختيارية بجزء من اسم الرمز (بحث سريع في الواجهة)."""
    eligible = load_eligible_tickers()
    allow = load_allowlist()
    rows = store.symbols()
    for row in rows:
        base = row["symbol"].split(".")[0]
        if eligible is not None:
            row["allowed"] = base in eligible or row["symbol"] in eligible
        else:
            row["allowed"] = (not allow) or base in allow or row["symbol"] in allow
    if q:
        q_upper = q.strip().upper()
        rows = [r for r in rows if q_upper in r["symbol"]]
    return {"count": len(rows), "allowlist_size": len(allow),
            "eligibility_cache_size": len(eligible) if eligible is not None else None,
            "symbols": rows}


@app.get("/screen/{symbol}")
def screen(symbol: str):
    """فحص أخلاقي حي لرمز واحد عبر yfinance (بنوك/دفاع/قائمة BDS) — يُستخدم
    من بحث الواجهة عن رمز غير مخزَّن مسبقًا، حيث لا يوجد كاش جاهز لمعرفة
    حالته الأخلاقية مقدمًا كما في /symbols."""
    try:
        mod = importlib.import_module("ethical_screen")
    except Exception as exc:
        raise HTTPException(501, f"ethical_screen غير قابل للاستيراد: {exc}")
    result = mod.screen_ticker(symbol.upper())
    return {"symbol": symbol.upper(), "allowed": not result.excluded,
            "reason": result.reason, "sector": result.sector, "industry": result.industry}


# ---------------------------------------------------------------- استيراد وتحديث
@app.post("/import/stooq")
def import_stooq(directory: str | None = None, symbols: str | None = None,
                 all_symbols: bool = False):
    """يستورد ملفات Stooq النصية من المجلد (الافتراضي: SAIRA_DATA، الأرشيف الحقيقي).

    افتراضيًا يستورد فقط الرموز التي اجتازت الفلتر الأخلاقي الحقيقي فعليًا
    (كاش full_universe_analysis.py — status=="eligible"، فحص قطاع حقيقي +
    استبعاد بنوك/دفاع/BDS) — **مُصحَّح 2026-07**: كان الاستيراد الافتراضي
    يجلب كل كون التغطية (data/ticker_universe.csv، 6000+ رمز NASDAQ/NYSE
    بلا فلترة) رغم وجود فحص أخلاقي حقيقي محسوب مسبقًا وجاهز للاستخدام. لو
    كاش الأهلية غير موجود بعد (لم يُشغَّل full_universe_analysis.py على هذا
    الجهاز)، يرجع صراحة لقائمة التغطية الخام مع تحذير — لا فلترة صامتة.
    مرّر symbols=AAL,GOOG لاستيراد رموز محددة، أو all_symbols=true لاستيراد
    كل ما في المجلد بلا حدود (بطيء، ويشمل رموزًا مستبعدة أخلاقيًا).
    """
    path = Path(directory) if directory else DATA_DIR
    if not path.exists():
        raise HTTPException(400, f"المجلد غير موجود: {path}")
    warning = None
    if all_symbols:
        wanted = None
    elif symbols:
        wanted = {s.strip().upper() for s in symbols.split(",") if s.strip()}
    else:
        eligible = load_eligible_tickers()
        if eligible is not None:
            wanted = eligible
        else:
            wanted = load_allowlist() or None
            warning = ("كاش الفلترة الأخلاقية (runs/ticker_eligibility_cache.json) غير موجود — "
                      "تم الاستيراد من كون التغطية الخام بلا فلترة أخلاقية فعلية. "
                      "شغّل full_universe_analysis.py مرة واحدة على الأقل لبناء الكاش.")
    report = store.import_stooq_dir(path, symbols=wanted)
    if not report:
        raise HTTPException(400, "لا ملفات Stooq صالحة في المجلد (أو لا رمز من القائمة موجود فيه)")
    result = {"imported": report}
    if warning:
        result["warning"] = warning
    return result


@app.post("/refresh/{symbol}")
def refresh(symbol: str, period: str = "3mo"):
    """تحديث الشموع اليومية من ياهو فايننس."""
    try:
        n = store.refresh_from_yfinance(symbol, period)
    except ImportError:
        raise HTTPException(501, "ثبّت yfinance أولًا: pip install yfinance")
    except Exception as exc:
        raise HTTPException(502, f"فشل الجلب: {exc}")
    return {"symbol": symbol.upper(), "rows": n}


# ---------------------------------------------------------------- شموع ومؤشرات
@app.get("/candles/{symbol}")
def candles(symbol: str, tf: str = "D", limit: int = Query(5000, le=50000)):
    """tf: 30 / 60 / 300 / 900 / 3600 / 14400 / D / W / M"""
    return {"symbol": symbol.upper(), "tf": tf,
            "bars": _need_symbol(symbol, tf, limit)}


@app.get("/indicators/{symbol}")
def get_indicators(symbol: str, tf: str = "D",
                   names: str = "rsi,macd,sma20,sma50,bb,adx",
                   limit: int = 2000):
    bars = _need_symbol(symbol, tf, limit)
    import pandas as pd
    df = pd.DataFrame(bars)
    out = indicators.compute(df, names.split(","))
    return {
        "symbol": symbol.upper(), "tf": tf,
        "data": out.astype(object).where(out.notna(), None).to_dict(orient="records"),
    }


# ---------------------------------------------------------------- أدوات جان
@app.get("/gann/sq9")
def sq9(price: float, lo: float | None = None, hi: float | None = None):
    """مستويات مربع التسعة من سعر ارتكاز."""
    if price <= 0:
        raise HTTPException(400, "سعر الارتكاز يجب أن يكون موجبًا")
    return {"pivot": price, "levels": gann.sq9_levels(price, lo, hi)}


@app.get("/gann/sq9/{symbol}")
def sq9_auto(symbol: str, tf: str = "D", side: str = "low", limit: int = 2000):
    """مربع 9 تلقائيًا من أدنى قاع أو أعلى قمة للرمز، مقصوصًا على مداه."""
    import pandas as pd
    df = pd.DataFrame(_need_symbol(symbol, tf, limit))
    lo, hi = float(df["l"].min()), float(df["h"].max())
    pivot = lo if side == "low" else hi
    pad = (hi - lo) * 0.1
    return {"symbol": symbol.upper(), "pivot": pivot, "side": side,
            "levels": gann.sq9_levels(pivot, lo - pad, hi + pad)}


@app.get("/gann/auto_calibrate/{symbol}")
def gann_auto_calibrate(symbol: str, tf: str = "D", limit: int = 5000,
                        swing_m: int = 2, anchor_t: int | None = None):
    """معايرة تلقائية حقيقية لكل أدوات المعايرة (زر "تلقائي" في الواجهة):

    - increment: الزيادة السعرية الموصى بها من ATR/مستوى السعر (لمربع
      9/144/النجمة) — Mikula ch.6 + تنقيح التقلب، لا تقريب مدى/شموع.
    - square9: أفضل زاوية مربع 9 مُختبَرة فعليًا ضد ارتكازات السهم.
    - fan: أفضل زاوية مروحة جان — من نقطة الارتكاز التي حددها المستخدم
      بالنقر (anchor_t) إن مُرر، وإلا من آخر ارتكاز سوينج كافتراضي.
      **مُصحَّح 2026-07**: كانت تُحسب دومًا من آخر ارتكاز سوينج بصرف النظر
      عن الارتكاز الذي اختاره المستخدم فعليًا على الشارت — يعطي انطباعًا
      خاطئًا بأن "التلقائي" مرتبط بالسعر الحالي دومًا، بينما الحقيقة أنه
      كان يتجاهل اختيار المستخدم تمامًا.

    يستبدل التقريب القديم (المدى ÷ عدد الشموع) في كل الأزرار "تلقائي"."""
    import pandas as pd
    df = pd.DataFrame(_need_symbol(symbol, tf, limit))
    high, low, close = df["h"], df["l"], df["c"]

    incr_result = gann.auto_price_increment(high, low, close)
    increment = incr_result["recommended_increment"]
    sq9_result = gann.auto_square9_angle(high, low, close, increment)

    sw = gann.swing_pivots(df, swing_m)
    fan_result = None
    chosen_pivot = None
    if anchor_t is not None:
        matches = [p for p in sw["pivots"] if p["t"] == anchor_t]
        if matches:
            chosen_pivot = matches[0]
        else:
            # الارتكاز المُختار بالنقر مش بالضرورة "ارتكاز سوينج" رسمي
            # (m=2 قد لا يكتشفه) — نبني نقطة ارتكاز مباشرة من السعر عند
            # ذلك الطابع الزمني بدل تجاهل اختيار المستخدم كليًا.
            idx_matches = df.index[df["t"] == anchor_t]
            if len(idx_matches):
                i = int(idx_matches[0])
                is_low = float(low.iloc[i]) == float(low.iloc[max(0, i - 2):i + 3].min())
                chosen_pivot = {"t": anchor_t,
                               "price": float(low.iloc[i]) if is_low else float(high.iloc[i]),
                               "type": "bottom" if is_low else "top"}
    elif sw["pivots"]:
        chosen_pivot = sw["pivots"][-1]

    if chosen_pivot:
        idx_matches = df.index[df["t"] == chosen_pivot["t"]]
        if len(idx_matches):
            anchor_i = int(idx_matches[0])
            direction = 1 if chosen_pivot["type"] == "bottom" else -1
            fan_result = gann.auto_fan_angle(close, anchor_i, chosen_pivot["price"], direction)
            fan_result["anchor_t"] = chosen_pivot["t"]
            fan_result["anchor_price"] = chosen_pivot["price"]
            fan_result["direction"] = direction

    return {"symbol": symbol.upper(), "tf": tf,
            "increment": incr_result, "square9": sq9_result, "fan": fan_result}


@app.get("/gann/swing/{symbol}")
def swing(symbol: str, tf: str = "D", bars: int = Query(2, ge=2, le=5),
          limit: int = 5000):
    import pandas as pd
    df = pd.DataFrame(_need_symbol(symbol, tf, limit))
    result = gann.swing_pivots(df, bars)
    return {"symbol": symbol.upper(), "tf": tf, "reversal_bars": bars, **result}


@app.get("/gann/cycles/{symbol}")
def cycles(symbol: str, tf: str = "D", top: int = 5, limit: int = 2000):
    import pandas as pd
    df = pd.DataFrame(_need_symbol(symbol, tf, limit))
    return {"symbol": symbol.upper(), "tf": tf,
            "cycles": gann.dominant_cycles(df, top)}


@app.get("/gann/sun")
def sun(t: int):
    """خط طول الشمس الجيوسنتري عند طابع زمني (ثوانٍ)."""
    return {"t": t, "longitude": round(gann.sun_longitude(t), 4)}


# ---------------------------------------------------------------- اللجنة
@app.get("/committee/{symbol}")
def committee(symbol: str):
    """يشغّل committee_signals.py الموجود في جذر مشروعك إن وُجد."""
    return pipeline_bridge.run_committee(symbol.upper())


# ---------------------------------------------------------------- المرحلة 2: فلك + أشكال جان
from .analysis import astro as astro_mod  # noqa: E402


@app.get("/astro/planets")
def planets():
    """قائمة الكواكب المدعومة بأسمائها العربية."""
    return {"planets": astro_mod.PLANET_NAMES_AR}


@app.get("/astro/longitudes/{planet}")
def astro_longitudes(planet: str, t_start: int, t_end: int,
                     step_days: float = 1.0, helio: bool = False):
    """سلسلة خطوط الطول لكوكب عبر مدى زمني (مع علم التراجع)."""
    if t_end <= t_start:
        raise HTTPException(400, "t_end يجب أن يتجاوز t_start")
    if (t_end - t_start) / 86400 / max(step_days, 1/24) > 40000:
        raise HTTPException(400, "المدى كبير جدًا — كبّر step_days")
    try:
        return {"planet": planet.lower(), "helio": helio,
                "series": astro_mod.longitudes(planet, t_start, t_end,
                                               step_days, helio)}
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.get("/astro/snapshot")
def astro_snapshot(t: int):
    """خطوط طول كل الكواكب لحظة معينة."""
    return {"t": t, "positions": astro_mod.snapshot(t)}


@app.get("/astro/eclipses")
def astro_eclipses(t_start: int, t_end: int):
    """جدول الكسوف/الخسوف بين تاريخين (فصل 17)."""
    if t_end <= t_start:
        raise HTTPException(400, "t_end يجب أن يتجاوز t_start")
    if (t_end - t_start) / 86400 > 366 * 30:
        raise HTTPException(400, "المدى كبير جدًا — قسّمه على دفعات أصغر من 30 سنة")
    return {"t_start": t_start, "t_end": t_end,
            "eclipses": astro_mod.eclipses(t_start, t_end)}


@app.get("/astro/aspects")
def astro_aspects(planet_a: str, mode_a: str, planet_b: str, mode_b: str,
                  aspect: str, t_start: int, t_end: int,
                  natal_t: int | None = None, orb_deg: float | None = None,
                  step_days: float = 1.0, helio_a: bool = False, helio_b: bool = False):
    """العلاقة الكوكبية (aspect) بين كوكبين — اقتران/تسديس/تربيع/تثليث/
    مقابلة — كلٌ منهما إما عابر (transit) أو ثابت عند تاريخ ميلاد
    (natal، مثل تاريخ IPO). راجع astro.ASPECTS للزوايا والسماحية الافتراضية."""
    if t_end <= t_start:
        raise HTTPException(400, "t_end يجب أن يتجاوز t_start")
    if (t_end - t_start) / 86400 / max(step_days, 1 / 24) > 40000:
        raise HTTPException(400, "المدى كبير جدًا — كبّر step_days")
    try:
        return astro_mod.scan_aspect(
            planet_a, mode_a, planet_b, mode_b, aspect, t_start, t_end,
            natal_t=natal_t, orb_deg=orb_deg, step_days=step_days,
            helio_a=helio_a, helio_b=helio_b,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.get("/astro/aspect_types")
def astro_aspect_types():
    """قائمة أنواع العلاقات الكوكبية المدعومة (زاوية وسماحية افتراضية)."""
    return {"aspects": astro_mod.ASPECTS}


@app.get("/gann/star")
def gann_star(price: float, kind: str = "hexagram", rotations: int = 2,
              lo: float | None = None, hi: float | None = None):
    """رؤوس نجمة جان (خماسية 72° أو سداسية 60°) من سعر ارتكاز."""
    if price <= 0:
        raise HTTPException(400, "سعر الارتكاز يجب أن يكون موجبًا")
    if kind not in ("pentagram", "hexagram"):
        raise HTTPException(400, "kind: pentagram أو hexagram")
    return {"pivot": price, "kind": kind,
            "levels": gann.star_levels(price, kind, rotations, lo, hi)}


@app.get("/gann/sq144/{symbol}")
def gann_sq144(symbol: str, tf: str = "D", limit: int = 5000,
               price_unit: float | None = None, swing_m: int = 2):
    """شبكة مربع 144 من آخر ارتكاز سوينج للرمز.

    وحدة السعر الافتراضية (بلا price_unit صريح) = الزيادة السعرية الموصى
    بها فعليًا من ATR/مستوى السعر (gann.auto_price_increment) — لا تقريب
    مدى/شموع كما كانت سابقًا."""
    import pandas as pd
    df = pd.DataFrame(_need_symbol(symbol, tf, limit))
    sw = gann.swing_pivots(df, swing_m)
    if not sw["pivots"]:
        raise HTTPException(422, "لا ارتكازات سوينج كافية")
    pivot = sw["pivots"][-1]
    if price_unit is not None:
        unit = price_unit
    else:
        unit = gann.auto_price_increment(df["h"], df["l"], df["c"])["recommended_increment"]
    bar_sec = int(df["t"].iloc[-1] - df["t"].iloc[-2]) if len(df) > 1 else 86400
    grid = gann.sq144_grid(pivot["price"], pivot["t"], unit, bar_sec,
                           1 if pivot["type"] == "bottom" else -1)
    return {"symbol": symbol.upper(), **grid}


@app.get("/gann/confluence/{symbol}")
def gann_confluence(symbol: str, tf: str = "D", limit: int = 5000,
                    swing_m: int = 2, star_kind: str = "hexagram",
                    top: int = 8):
    """درجة الالتقاء: عنقدة مستويات كل الأدوات وترتيبها بالوزن."""
    import pandas as pd
    df = pd.DataFrame(_need_symbol(symbol, tf, limit))
    return {"symbol": symbol.upper(), "tf": tf,
            **gann.confluence(df, swing_m, star_kind, top)}


@app.get("/gann/squaring/{symbol}")
def gann_squaring(symbol: str, tf: str = "D", limit: int = 5000,
                  swing_m: int = 2, price_unit: float | None = None,
                  tolerance_bars: float = 1.5):
    """موازنة السعر والزمن: ارتكازات سوينج "تربّعت" فيها الشموع مع المدى."""
    import pandas as pd
    df = pd.DataFrame(_need_symbol(symbol, tf, limit))
    return {"symbol": symbol.upper(), "tf": tf,
            **gann.squaring_price_time(df, swing_m, price_unit, tolerance_bars)}


@app.get("/gann/master_time/{symbol}")
def gann_master_time(symbol: str, tf: str = "D", limit: int = 5000,
                     swing_m: int = 2, anchor_t: int | None = None):
    """حاسبة الزمن الرئيسية: مواعيد استحقاق 30..360 يومًا من ارتكاز.

    anchor_t اختياري — بلا تمرير، يُستخدم آخر ارتكاز سوينج تلقائيًا."""
    import pandas as pd
    df = pd.DataFrame(_need_symbol(symbol, tf, limit))
    if anchor_t is None:
        sw = gann.swing_pivots(df, swing_m)
        if not sw["pivots"]:
            raise HTTPException(422, "لا ارتكاز سوينج كافٍ ولم يُمرَّر anchor_t")
        anchor_t = sw["pivots"][-1]["t"]
    as_of_t = int(df["t"].iloc[-1])
    return {"symbol": symbol.upper(), "tf": tf,
            **gann.master_time_periods(anchor_t, as_of_t)}


# ---------------------------------------------------------------- الماسح الكوكبي (Planetary Scanner)
from .analysis import scanner  # noqa: E402


@app.get("/scan/planets/{symbol}")
def scan_planets(symbol: str, tf: str = "D", limit: int = 5000, top: int = 5):
    """يمسح كل الكواكب على الرمز (اختبارا الانعكاس + المحاذاة)."""
    import pandas as pd
    df = pd.DataFrame(_need_symbol(symbol, tf, limit))
    cfg = scanner.ScanConfig(top_planets=top)
    return {"symbol": symbol.upper(), "tf": tf,
            **scanner.scan_symbol(df, cfg)}


@app.get("/scan/grid/{symbol}")
def scan_grid(symbol: str, planet: str, center: str, unit_price: float,
              tf: str = "D", limit: int = 5000, n_lines: int = 4):
    """يبني خطوط الكوكب باستخدام الوحدة السعرية المكتشفة من الماسح."""
    import pandas as pd
    df = pd.DataFrame(_need_symbol(symbol, tf, limit))
    try:
        return scanner.planetary_grid(df, planet, center, unit_price, n_lines)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.get("/scan/connected/{symbol}")
def scan_connected(symbol: str, planet: str, center: str, unit_price: float,
                   tf: str = "D", limit: int = 5000, n_lines: int = 2):
    """شبكة الخطوط المترابطة لكوكب فائز في الماسح: قِران/سداسي/تربيع/
    تثليث/مقابلة معًا (ملاحظة 1، مجلد 1) بدل خط واحد فقط."""
    import pandas as pd
    df = pd.DataFrame(_need_symbol(symbol, tf, limit))
    try:
        return scanner.connected_lines(df, planet, center, unit_price, n_lines)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.get("/scan/aspect_influence/{symbol}")
def scan_aspect_influence(symbol: str, tf: str = "D", limit: int = 5000, top: int = 10):
    """يختبر كل أزواج الكواكب × كل زوايا الاتصال (0/30/45/60/90/120/180)
    معًا — بعكس /scan/planets الذي يقيّم كل كوكب بمفرده — ويرتب أكثر
    العلاقات (زوج كوكبين + زاوية) ترافقًا مع ارتكازات سوينج فعلية."""
    import pandas as pd
    df = pd.DataFrame(_need_symbol(symbol, tf, limit))
    return {"symbol": symbol.upper(), "tf": tf,
            **scanner.aspect_influence_scan(df, top)}
