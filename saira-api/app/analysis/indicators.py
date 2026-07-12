"""مؤشرات فنية مكتفية ذاتيًا (pandas/numpy فقط).

مبنية بنفس ضمانات الحواف التي اكتُشفت في اختبارات خط الأنابيب:
- RSI على سعر ثابت لا يقسم على صفر (يعيد 50 حيادية).
- MACD لا يعطي تقاطعًا زائفًا خلال فترة الإحماء (NaN حتى الاكتمال).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def sma(close: pd.Series, n: int) -> pd.Series:
    return close.rolling(n).mean()


def ema(close: pd.Series, n: int) -> pd.Series:
    return close.ewm(span=n, adjust=False, min_periods=n).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    out = pd.Series(np.nan, index=close.index)
    both_zero = (gain == 0) & (loss == 0)          # سعر ثابت
    loss_zero = (loss == 0) & ~both_zero            # صعود صافٍ
    normal = ~both_zero & ~loss_zero
    out[both_zero] = 50.0
    out[loss_zero] = 100.0
    rs = gain[normal] / loss[normal]
    out[normal] = 100 - 100 / (1 + rs)
    out[gain.isna() | loss.isna()] = np.nan          # فترة الإحماء
    return out


def macd(close: pd.Series, fast: int = 12, slow: int = 26,
         signal: int = 9) -> pd.DataFrame:
    line = ema(close, fast) - ema(close, slow)
    sig = line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return pd.DataFrame({"macd": line, "signal": sig, "hist": line - sig})


def bollinger(close: pd.Series, n: int = 20, k: float = 2.0) -> pd.DataFrame:
    mid = sma(close, n)
    sd = close.rolling(n).std(ddof=0)
    return pd.DataFrame({"bb_mid": mid, "bb_up": mid + k * sd,
                         "bb_dn": mid - k * sd})


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    """df يحوي h, l, c."""
    prev_c = df["c"].shift()
    tr = pd.concat([
        df["h"] - df["l"],
        (df["h"] - prev_c).abs(),
        (df["l"] - prev_c).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def adx(df: pd.DataFrame, n: int = 14) -> pd.DataFrame:
    up = df["h"].diff()
    dn = -df["l"].diff()
    plus_dm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=df.index)
    _atr = atr(df, n).replace(0, np.nan)
    plus_di = 100 * plus_dm.ewm(alpha=1 / n, adjust=False,
                                min_periods=n).mean() / _atr
    minus_di = 100 * minus_dm.ewm(alpha=1 / n, adjust=False,
                                  min_periods=n).mean() / _atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return pd.DataFrame({
        "plus_di": plus_di, "minus_di": minus_di,
        "adx": dx.ewm(alpha=1 / n, adjust=False, min_periods=n).mean(),
    })


def compute(df: pd.DataFrame, names: list[str]) -> pd.DataFrame:
    """يحسب مجموعة مؤشرات على إطار شموع t,o,h,l,c,v ويعيدها بأعمدة مسماة."""
    out = pd.DataFrame({"t": df["t"]})
    close = df["c"]
    for name in names:
        name = name.strip().lower()
        if name.startswith("sma"):
            n = int(name[3:] or 20)
            out[f"sma{n}"] = sma(close, n)
        elif name.startswith("ema"):
            n = int(name[3:] or 20)
            out[f"ema{n}"] = ema(close, n)
        elif name == "rsi":
            out["rsi"] = rsi(close)
        elif name == "macd":
            out = out.join(macd(close))
        elif name in ("bb", "bollinger"):
            out = out.join(bollinger(close))
        elif name == "adx":
            out = out.join(adx(df))
        elif name == "atr":
            out["atr"] = atr(df)
    return out
