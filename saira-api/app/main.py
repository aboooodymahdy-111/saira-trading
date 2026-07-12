"""Saira Trading API — خادم المرحلة 0.

تشغيل:  uvicorn app.main:app --port 8787 --reload
التوثيق التفاعلي: http://127.0.0.1:8787/docs
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from . import pipeline_bridge
from .analysis import gann, indicators
from .config import DATA_DIR, load_allowlist
from .data import store

app = FastAPI(
    title="Saira Trading API",
    version="0.1.0",
    description="خلفية منصة Saira Terminal — شموع، مؤشرات، أدوات جان، لجنة الإشارات",
)

# CORS مفتوح محليًا كي يتصل به النموذج saira-terminal-prototype.html مباشرة
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
def symbols():
    """الرموز المخزنة مع حالة القائمة الأخلاقية لكل رمز."""
    allow = load_allowlist()
    rows = store.symbols()
    for row in rows:
        base = row["symbol"].split(".")[0]
        row["allowed"] = (not allow) or base in allow or row["symbol"] in allow
    return {"count": len(rows), "allowlist_size": len(allow), "symbols": rows}


# ---------------------------------------------------------------- استيراد وتحديث
@app.post("/import/stooq")
def import_stooq(directory: str | None = None, symbols: str | None = None,
                 all_symbols: bool = False):
    """يستورد ملفات Stooq النصية من المجلد (الافتراضي: SAIRA_DATA، الأرشيف الحقيقي).

    افتراضيًا يستورد رموز كون التغطية (data/ticker_universe.csv) فقط — تجنبًا
    لاستيراد آلاف الملفات كل مرة. مرّر symbols=AAL,GOOG لاستيراد رموز محددة،
    أو all_symbols=true لاستيراد كل ما في المجلد بلا حدود (بطيء).
    """
    path = Path(directory) if directory else DATA_DIR
    if not path.exists():
        raise HTTPException(400, f"المجلد غير موجود: {path}")
    if all_symbols:
        wanted = None
    elif symbols:
        wanted = {s.strip().upper() for s in symbols.split(",") if s.strip()}
    else:
        wanted = load_allowlist() or None
    report = store.import_stooq_dir(path, symbols=wanted)
    if not report:
        raise HTTPException(400, "لا ملفات Stooq صالحة في المجلد (أو لا رمز من القائمة موجود فيه)")
    return {"imported": report}


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
    """شبكة مربع 144 من آخر ارتكاز سوينج للرمز."""
    import pandas as pd
    df = pd.DataFrame(_need_symbol(symbol, tf, limit))
    sw = gann.swing_pivots(df, swing_m)
    if not sw["pivots"]:
        raise HTTPException(422, "لا ارتكازات سوينج كافية")
    pivot = sw["pivots"][-1]
    unit = price_unit or round(float(df["h"].max() - df["l"].min())
                               / len(df), 6)
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
