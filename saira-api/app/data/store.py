"""مخزن الشموع التاريخية — DuckDB.

المخطط: candles(symbol, t[epoch ثانية], o, h, l, c, v)
يستوعب أي دقة زمنية (30 ثانية حتى يومي) في جدول واحد،
وإعادة التجميع لأي فريم أكبر تتم عند الاستعلام.
"""
from __future__ import annotations

import re
from pathlib import Path

import duckdb
import pandas as pd

from ..config import DATA_SUBFOLDERS, DB_PATH

_SCHEMA = """
CREATE TABLE IF NOT EXISTS candles(
    symbol VARCHAR NOT NULL,
    t      BIGINT  NOT NULL,
    o DOUBLE, h DOUBLE, l DOUBLE, c DOUBLE,
    v BIGINT,
    PRIMARY KEY (symbol, t)
);
"""


def _conn() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(str(DB_PATH))
    con.execute(_SCHEMA)
    return con


# ---------------------------------------------------------------- استيراد Stooq
_STOOQ_HEADER = "<TICKER>"


def parse_stooq(path: Path) -> tuple[str, pd.DataFrame]:
    """يقرأ ملف Stooq النصي ويعيد (الرمز، إطار بيانات t,o,h,l,c,v)."""
    df = pd.read_csv(path)
    df.columns = [re.sub(r"[<>]", "", str(col)).strip().upper() for col in df.columns]
    required = {"TICKER", "DATE", "OPEN", "HIGH", "LOW", "CLOSE"}
    if not required.issubset(df.columns):
        raise ValueError(f"ليست صيغة Stooq: {path.name}")

    symbol = str(df["TICKER"].iloc[0]).upper()
    date = df["DATE"].astype(str).str.zfill(8)
    time = (
        df["TIME"].astype(str).str.zfill(6) if "TIME" in df.columns
        else pd.Series(["000000"] * len(df))
    )
    ts = pd.to_datetime(date + time, format="%Y%m%d%H%M%S", utc=True)

    out = pd.DataFrame({
        "t": ((ts - pd.Timestamp("1970-01-01", tz="UTC")) // pd.Timedelta("1s")).astype("int64"),
        "o": df["OPEN"].astype(float),
        "h": df["HIGH"].astype(float),
        "l": df["LOW"].astype(float),
        "c": df["CLOSE"].astype(float),
        "v": df.get("VOL", pd.Series([0] * len(df))).fillna(0).astype("int64"),
    }).sort_values("t")
    return symbol, out


def upsert(symbol: str, df: pd.DataFrame) -> int:
    """إدراج/تحديث شموع رمز — يعيد عدد الصفوف المدرجة."""
    if df.empty:
        return 0
    df = df.copy()
    df.insert(0, "symbol", symbol.upper())
    con = _conn()
    try:
        con.register("incoming", df)
        con.execute("""
            INSERT INTO candles
            SELECT symbol, t, o, h, l, c, v FROM incoming
            ON CONFLICT (symbol, t) DO UPDATE SET
                o=excluded.o, h=excluded.h, l=excluded.l,
                c=excluded.c, v=excluded.v
        """)
        return len(df)
    finally:
        con.close()


def import_stooq_dir(directory: Path, symbols: set[str] | None = None) -> dict[str, int]:
    """يستورد ملفات .txt بصيغة Stooq — يبحث تكراريًا (rglob) لأن الأرشيف الحقيقي
    (LOCAL_MARKET_DATA_DIR في full_universe_analysis.py) مبعثر داخل مجلدات فرعية
    بالبورصة (nasdaq stocks/<حرف>/AAPL.US.txt) وليس ملفات مسطّحة في مجلد واحد
    كما افترض النموذج الأولي. إن مُرر symbols يستورد هذه الرموز فقط — تجنبًا
    لاستيراد آلاف الملفات غير المطلوبة دفعة واحدة كل مرة."""
    from ..config import DATA_SUBFOLDERS

    report: dict[str, int] = {}
    roots = [directory / sub for sub in DATA_SUBFOLDERS if (directory / sub).exists()]
    roots = roots or [directory]
    for root in roots:
        for path in sorted(root.rglob("*.txt")):
            stem_symbol = path.stem.split(".")[0].upper()
            if symbols is not None and stem_symbol not in symbols:
                continue
            try:
                first = path.open(encoding="utf-8").readline()
                if not first.startswith(_STOOQ_HEADER):
                    continue
                symbol, df = parse_stooq(path)
                report[symbol] = upsert(symbol, df)
            except Exception as exc:  # ملف تالف لا يوقف الدفعة
                report[path.name] = f"خطأ: {exc}"  # type: ignore[assignment]
    return report


# ---------------------------------------------------------------- الاستعلام
def symbols() -> list[dict]:
    con = _conn()
    try:
        rows = con.execute("""
            SELECT symbol, COUNT(*) AS bars,
                   MIN(t) AS first_t, MAX(t) AS last_t
            FROM candles GROUP BY symbol ORDER BY symbol
        """).fetchall()
    finally:
        con.close()
    return [
        {"symbol": s, "bars": b, "first": ft, "last": lt}
        for s, b, ft, lt in rows
    ]


_TF_SECONDS = {"30": 30, "60": 60, "300": 300, "900": 900,
               "3600": 3600, "14400": 14400, "D": 86400}


def candles(symbol: str, tf: str = "D", limit: int = 5000) -> list[dict]:
    """شموع رمز بفريم معين. tf: ثوانٍ كنص أو D/W/M."""
    symbol = symbol.upper()
    con = _conn()
    try:
        if tf in _TF_SECONDS:
            sec = _TF_SECONDS[tf]
            bucket = f"(t // {sec}) * {sec}"
        elif tf == "W":
            # إثنين بداية الأسبوع
            bucket = ("epoch(date_trunc('week', "
                      "to_timestamp(t)))::BIGINT")
        elif tf == "M":
            bucket = ("epoch(date_trunc('month', "
                      "to_timestamp(t)))::BIGINT")
        else:
            raise ValueError(f"فريم غير معروف: {tf}")

        rows = con.execute(f"""
            SELECT {bucket} AS bt,
                   arg_min(o, t) AS o, MAX(h) AS h, MIN(l) AS l,
                   arg_max(c, t) AS c, SUM(v) AS v
            FROM candles WHERE symbol = ?
            GROUP BY bt ORDER BY bt DESC LIMIT ?
        """, [symbol, limit]).fetchall()
    finally:
        con.close()
    rows.reverse()
    return [
        {"t": int(t), "o": o, "h": h, "l": l, "c": c, "v": int(v or 0)}
        for t, o, h, l, c, v in rows
    ]


def candles_df(symbol: str, tf: str = "D", limit: int = 5000) -> pd.DataFrame:
    return pd.DataFrame(candles(symbol, tf, limit))


# ---------------------------------------------------------------- تحديث yfinance
def refresh_from_yfinance(symbol: str, period: str = "3mo") -> int:
    """جلب أحدث الشموع اليومية من ياهو ودمجها (استيراد كسول للمكتبة)."""
    import yfinance as yf  # كسول: الخادم يعمل بدونها إن لم تُثبَّت

    ticker = symbol.split(".")[0]  # AAL.US -> AAL
    hist = yf.Ticker(ticker).history(period=period, auto_adjust=False)
    if hist.empty:
        return 0
    idx = pd.to_datetime(hist.index, utc=True)
    df = pd.DataFrame({
        "t": ((idx - pd.Timestamp("1970-01-01", tz="UTC")) // pd.Timedelta("1s")).astype("int64"),
        "o": hist["Open"].values, "h": hist["High"].values,
        "l": hist["Low"].values, "c": hist["Close"].values,
        "v": hist["Volume"].fillna(0).astype("int64").values,
    })
    return upsert(symbol, df)
