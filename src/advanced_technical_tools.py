"""
advanced_technical_tools.py — Extra technical-analysis layer: TA-Lib-backed
oscillators/indicators, plus Ichimoku Cloud, ZigZag, Volume Profile, and Pivot
Points built in-house.

WHY THIS MODULE (project conversation, 2026-07):
    Abdo asked which additional well-known technical tools (Ichimoku, Volume
    Profile, Harmonic Patterns, ZigZag, etc.) are worth adding beyond what
    committee_signals.py already covers (MACD, Golden/Death Cross, Bollinger
    Bands, ADX). This module adds that next layer.

LIBRARY DECISIONS (researched 2026-07 — web search, not assumed):
    - TA-Lib: used for the standard oscillator/indicator set below (RSI, MACD,
      Bollinger Bands, ADX/+DI/-DI, Aroon, Stochastic, MFI, OBV, Parabolic SAR).
      It's the de facto reference implementation and is actively maintained;
      as of v0.6.5 it ships prebuilt binary wheels for most platforms, so
      `pip install ta-lib` normally needs no compiler. On Windows, if that
      still fails (older Python or no wheel yet for a brand-new Python
      release), use the community wheel builds at
      https://github.com/cgohlke/talib-build instead.
    - pandas-ta: REJECTED as a dependency — the original project is
      unmaintained (no real release since 2021). A community fork,
      `pandas-ta-classic`, exists and is active, but it's very young (started
      2026) and not yet trusted for this project.
    - tradingview-indicators: REJECTED — thin, largely unverified, and its
      Ichimoku implementation specifically looked unreliable on inspection.
    - FinFeatures: REJECTED — too new (v0.2.0, ~2 releases) to trust.
    - gannpy: does not actually exist on PyPI under that name (confirmed via
      web search) — not usable regardless of preference.
    - Ichimoku Cloud, ZigZag, Volume Profile, and Pivot Points are built
      IN-HOUSE below instead of importing a small/unverified package for each.
      All four are well-documented, standard formulas (cited per function)
      that are simple enough to implement directly and verify against known
      behavior — the same "test then trust" standard already applied to
      MACD/Bollinger/ADX in committee_signals.py, which are hand-implemented
      there too rather than imported.

NOT EXECUTED AGAINST REAL MARKET DATA IN THE ASSISTANT'S SANDBOX: the sandbox
    has no network access (same limitation noted throughout this project — see
    verify_signals.py / independent_signals.py / committee_signals.py) and does
    not have TA-Lib installed (installing it also needs network access this
    sandbox doesn't have). The TA-Lib wrapper functions below were written
    against TA-Lib's documented function signatures (talib.RSI, talib.MACD,
    talib.BBANDS, talib.ADX, talib.PLUS_DI/MINUS_DI, talib.AROON, talib.STOCH,
    talib.MFI, talib.OBV, talib.SAR — verified via TA-Lib's own documentation,
    2026-07), not executed here. The four in-house tools (Ichimoku, ZigZag,
    Volume Profile, Pivot Points) use only numpy/pandas and WERE smoke-tested
    in this sandbox against synthetic OHLCV data (see the `if __name__ ==
    "__main__"` block) to confirm they run end-to-end and produce sane,
    internally-consistent output — that is not the same as validating against
    a known worked example the way e.g. gann_square9_precise.py's formulas
    were verified against the book's own numbers, so treat the exact values
    with the same "verify before trusting heavily" caution as any new tool
    here, and run the smoke test yourself as a first sanity check:
        python src/advanced_technical_tools.py

INTEGRATION NOTE: evaluate_advanced_technical_group() returns a GroupResult
    with the same shape (votes_buy/votes_sell/votes_neutral/votes_unavailable/
    details, net_vote property) as committee_signals.GroupResult, by design —
    so it can be dropped into committee_signals.py's evaluate_ticker() as an
    additional group (e.g. alongside technical/quantitative/astrological) the
    same way gann_committee_vote() was wired in for the astrological group.
    That wiring is NOT done in this file to avoid a circular import between
    the two modules and because it's a project decision Abdo should confirm
    (how much weight this new group should carry) rather than one this module
    should make unilaterally.

Run (smoke test only — no live data fetch in this file):
    python src/advanced_technical_tools.py
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

try:
    import talib
    TALIB_AVAILABLE = True
except ImportError:
    TALIB_AVAILABLE = False


def _require_talib() -> None:
    if not TALIB_AVAILABLE:
        raise ImportError(
            "TA-Lib is not installed. Install it with `pip install ta-lib` "
            "(prebuilt wheels available since v0.6.5 for most platforms). On "
            "Windows, if that fails, use the wheel from "
            "https://github.com/cgohlke/talib-build instead. This function "
            "needs the real library and does not fall back to an "
            "approximation silently (Pillar 3: fail loud)."
        )


@dataclass
class GroupResult:
    """
    Mirrors committee_signals.GroupResult's shape exactly (kept as a separate,
    duplicate definition rather than imported, to avoid a circular import
    between this module and committee_signals.py — same reasoning as
    gann_increment_selection.compare_increment_methods taking a callback
    instead of importing gann_decision_system directly).
    """
    votes_buy: int = 0
    votes_sell: int = 0
    votes_neutral: int = 0
    votes_unavailable: int = 0
    details: dict = field(default_factory=dict)

    @property
    def net_vote(self) -> str:
        if self.votes_buy > self.votes_sell and self.votes_buy > 0:
            return "buy"
        if self.votes_sell > self.votes_buy and self.votes_sell > 0:
            return "sell"
        return "neutral"


# ---------------------------------------------------------------------------
# TA-LIB WRAPPER
# ---------------------------------------------------------------------------

RSI_PERIOD = 14
MACD_FAST, MACD_SLOW, MACD_SIGNAL = 12, 26, 9
BBANDS_PERIOD, BBANDS_STDDEV = 20, 2
ADX_PERIOD = 14
ADX_TREND_THRESHOLD = 25  # same threshold/rationale as committee_signals.ADX_TREND_THRESHOLD
AROON_PERIOD = 14
STOCH_FASTK, STOCH_SLOWK, STOCH_SLOWD = 14, 3, 3
MFI_PERIOD = 14
SAR_ACCELERATION, SAR_MAXIMUM = 0.02, 0.2
RSI_OVERSOLD, RSI_OVERBOUGHT = 30, 70
MFI_OVERSOLD, MFI_OVERBOUGHT = 20, 80
STOCH_OVERSOLD, STOCH_OVERBOUGHT = 20, 80

TALIB_MIN_BARS = 60  # rough floor so every indicator above has warmed up (ADX/MACD need the most)


@dataclass
class TALibSnapshot:
    """Most recent value of each TA-Lib indicator. NaN where TA-Lib itself
    returned NaN (usually just insufficient warm-up history)."""
    rsi_14: float
    macd: float
    macd_signal: float
    macd_hist: float
    bb_upper: float
    bb_middle: float
    bb_lower: float
    adx_14: float
    plus_di_14: float
    minus_di_14: float
    aroon_up: float
    aroon_down: float
    stoch_k: float
    stoch_d: float
    mfi_14: float
    obv: float
    sar: float


def compute_talib_snapshot(high: pd.Series, low: pd.Series, close: pd.Series,
                            volume: pd.Series) -> TALibSnapshot:
    """
    Computes the full TA-Lib indicator set and returns only the LATEST value of
    each (a snapshot for "as of today" voting, same pattern as
    committee_signals.py's vote functions) — not the full historical series.
    Raises ImportError via _require_talib() if TA-Lib isn't installed, rather
    than silently skipping indicators.
    """
    _require_talib()

    h = high.astype(float).values
    l = low.astype(float).values
    c = close.astype(float).values
    v = volume.astype(float).values

    macd, macd_signal, macd_hist = talib.MACD(
        c, fastperiod=MACD_FAST, slowperiod=MACD_SLOW, signalperiod=MACD_SIGNAL
    )
    bb_upper, bb_middle, bb_lower = talib.BBANDS(
        c, timeperiod=BBANDS_PERIOD, nbdevup=BBANDS_STDDEV, nbdevdn=BBANDS_STDDEV
    )
    # TA-Lib's own documented return order for AROON is (aroondown, aroonup).
    aroon_down, aroon_up = talib.AROON(h, l, timeperiod=AROON_PERIOD)
    stoch_k, stoch_d = talib.STOCH(
        h, l, c,
        fastk_period=STOCH_FASTK, slowk_period=STOCH_SLOWK, slowk_matype=0,
        slowd_period=STOCH_SLOWD, slowd_matype=0,
    )

    def last(arr: np.ndarray) -> float:
        val = arr[-1]
        return float(val) if not np.isnan(val) else float("nan")

    return TALibSnapshot(
        rsi_14=last(talib.RSI(c, timeperiod=RSI_PERIOD)),
        macd=last(macd), macd_signal=last(macd_signal), macd_hist=last(macd_hist),
        bb_upper=last(bb_upper), bb_middle=last(bb_middle), bb_lower=last(bb_lower),
        adx_14=last(talib.ADX(h, l, c, timeperiod=ADX_PERIOD)),
        plus_di_14=last(talib.PLUS_DI(h, l, c, timeperiod=ADX_PERIOD)),
        minus_di_14=last(talib.MINUS_DI(h, l, c, timeperiod=ADX_PERIOD)),
        aroon_up=last(aroon_up), aroon_down=last(aroon_down),
        stoch_k=last(stoch_k), stoch_d=last(stoch_d),
        mfi_14=last(talib.MFI(h, l, c, v, timeperiod=MFI_PERIOD)),
        obv=last(talib.OBV(c, v)),
        sar=last(talib.SAR(h, l, acceleration=SAR_ACCELERATION, maximum=SAR_MAXIMUM)),
    )


def talib_vote(snapshot: TALibSnapshot, current_price: float) -> tuple[str, dict]:
    """
    Combines several TA-Lib indicators into one net vote using simple,
    individually-documented rules (not a proprietary blend) — same
    "one indicator, one interpretable vote" style as
    committee_signals.evaluate_technical_group():
      - RSI: < 30 oversold (buy lean), > 70 overbought (sell lean)
      - MACD: histogram > 0 bullish, < 0 bearish
      - ADX-gated +DI/-DI: direction only trusted when ADX >= 25 (real trend
        underway), same gating rationale as committee_signals.compute_adx_vote
      - Stochastic %K: < 20 oversold, > 80 overbought
      - MFI: same oversold/overbought reading as RSI (volume-weighted version)
      - Aroon: Aroon-Up > Aroon-Down => bullish, else bearish
      - Parabolic SAR: price above SAR => bullish, below => bearish
    Each sub-vote counts once towards the net tally; ties => neutral.
    """
    votes: dict[str, str] = {}
    buy = sell = 0

    if not np.isnan(snapshot.rsi_14):
        if snapshot.rsi_14 < RSI_OVERSOLD:
            votes["rsi"] = "buy"; buy += 1
        elif snapshot.rsi_14 > RSI_OVERBOUGHT:
            votes["rsi"] = "sell"; sell += 1
        else:
            votes["rsi"] = "neutral"
    else:
        votes["rsi"] = "unavailable"

    if not np.isnan(snapshot.macd_hist):
        if snapshot.macd_hist > 0:
            votes["macd"] = "buy"; buy += 1
        elif snapshot.macd_hist < 0:
            votes["macd"] = "sell"; sell += 1
        else:
            votes["macd"] = "neutral"
    else:
        votes["macd"] = "unavailable"

    if not np.isnan(snapshot.adx_14):
        if snapshot.adx_14 < ADX_TREND_THRESHOLD:
            votes["adx_di"] = "neutral_no_trend"
        elif snapshot.plus_di_14 > snapshot.minus_di_14:
            votes["adx_di"] = "buy"; buy += 1
        else:
            votes["adx_di"] = "sell"; sell += 1
    else:
        votes["adx_di"] = "unavailable"

    if not np.isnan(snapshot.stoch_k):
        if snapshot.stoch_k < STOCH_OVERSOLD:
            votes["stochastic"] = "buy"; buy += 1
        elif snapshot.stoch_k > STOCH_OVERBOUGHT:
            votes["stochastic"] = "sell"; sell += 1
        else:
            votes["stochastic"] = "neutral"
    else:
        votes["stochastic"] = "unavailable"

    if not np.isnan(snapshot.mfi_14):
        if snapshot.mfi_14 < MFI_OVERSOLD:
            votes["mfi"] = "buy"; buy += 1
        elif snapshot.mfi_14 > MFI_OVERBOUGHT:
            votes["mfi"] = "sell"; sell += 1
        else:
            votes["mfi"] = "neutral"
    else:
        votes["mfi"] = "unavailable"

    if not np.isnan(snapshot.aroon_up) and not np.isnan(snapshot.aroon_down):
        if snapshot.aroon_up > snapshot.aroon_down:
            votes["aroon"] = "buy"; buy += 1
        elif snapshot.aroon_down > snapshot.aroon_up:
            votes["aroon"] = "sell"; sell += 1
        else:
            votes["aroon"] = "neutral"
    else:
        votes["aroon"] = "unavailable"

    if not np.isnan(snapshot.sar):
        if current_price > snapshot.sar:
            votes["sar"] = "buy"; buy += 1
        else:
            votes["sar"] = "sell"; sell += 1
    else:
        votes["sar"] = "unavailable"

    net = "buy" if buy > sell else ("sell" if sell > buy else "neutral")
    return net, votes


# ---------------------------------------------------------------------------
# ICHIMOKU CLOUD (built in-house)
# ---------------------------------------------------------------------------
# PROVENANCE: standard published Ichimoku Kinko Hyo construction (Goichi
# Hosoda), using the conventional default periods (9/26/52, 26-period
# displacement) — the same defaults confirmed via web search 2026-07 and used
# by every mainstream charting platform. No project-specific tuning applied.

ICHIMOKU_TENKAN_PERIOD = 9
ICHIMOKU_KIJUN_PERIOD = 26
ICHIMOKU_SENKOU_B_PERIOD = 52
ICHIMOKU_DISPLACEMENT = 26


def compute_ichimoku(high: pd.Series, low: pd.Series, close: pd.Series,
                      tenkan_period: int = ICHIMOKU_TENKAN_PERIOD,
                      kijun_period: int = ICHIMOKU_KIJUN_PERIOD,
                      senkou_b_period: int = ICHIMOKU_SENKOU_B_PERIOD,
                      displacement: int = ICHIMOKU_DISPLACEMENT) -> pd.DataFrame:
    """
    Returns a DataFrame (same index as the input) with the five standard
    Ichimoku lines:
        tenkan_sen      = (highest high + lowest low) / 2 over tenkan_period
        kijun_sen       = (highest high + lowest low) / 2 over kijun_period
        senkou_span_a   = (tenkan_sen + kijun_sen) / 2, projected `displacement`
                          periods FORWARD (a leading cloud boundary)
        senkou_span_b   = (highest high + lowest low) / 2 over senkou_b_period,
                          projected `displacement` periods FORWARD
        chikou_span     = close, shifted `displacement` periods BACKWARD

    Note on the forward shift: senkou_span_a/b represent the cloud as plotted
    `displacement` periods AHEAD of the current bar. The LAST `displacement`
    rows of the returned senkou columns are therefore NaN at the point they'd
    need current tenkan/kijun data that doesn't exist yet for future bars —
    callers reading "today's" cloud position should use current price against
    the cloud values that were projected TO today from `displacement` periods
    ago, i.e. ichimoku_df["senkou_span_a"/"senkou_span_b"].iloc[-1] as computed
    below (shift(displacement) already handles this correctly: it aligns each
    row with the cloud value that was projected to land there).
    """
    tenkan_sen = (high.rolling(tenkan_period).max() + low.rolling(tenkan_period).min()) / 2
    kijun_sen = (high.rolling(kijun_period).max() + low.rolling(kijun_period).min()) / 2
    senkou_span_a = ((tenkan_sen + kijun_sen) / 2).shift(displacement)
    senkou_span_b = (
        (high.rolling(senkou_b_period).max() + low.rolling(senkou_b_period).min()) / 2
    ).shift(displacement)
    chikou_span = close.shift(-displacement)

    return pd.DataFrame({
        "tenkan_sen": tenkan_sen,
        "kijun_sen": kijun_sen,
        "senkou_span_a": senkou_span_a,
        "senkou_span_b": senkou_span_b,
        "chikou_span": chikou_span,
    })


def ichimoku_vote(ichimoku_df: pd.DataFrame, close: pd.Series) -> tuple[str, dict]:
    """
    Standard, widely-documented Ichimoku trading rule:
      - price above the cloud (both senkou spans)  => bullish bias
      - price below the cloud                       => bearish bias
      - price inside the cloud                       => no clear bias (neutral)
    Refined by the Tenkan/Kijun ("TK") cross as a confirmation/veto: a fresh
    bearish TK cross vetoes an otherwise-bullish cloud-position vote, and vice
    versa, rather than blindly following whichever signal fired most recently.
    """
    if len(ichimoku_df) < 2:
        return "unavailable", {}

    last = ichimoku_df.iloc[-1]
    prev = ichimoku_df.iloc[-2]
    price = float(close.iloc[-1])

    if pd.isna(last["senkou_span_a"]) or pd.isna(last["senkou_span_b"]):
        return "unavailable", {"reason": "insufficient_history_for_cloud"}

    cloud_top = float(max(last["senkou_span_a"], last["senkou_span_b"]))
    cloud_bottom = float(min(last["senkou_span_a"], last["senkou_span_b"]))

    tk_cross = None
    if not pd.isna(prev["tenkan_sen"]) and not pd.isna(prev["kijun_sen"]) and \
       not pd.isna(last["tenkan_sen"]) and not pd.isna(last["kijun_sen"]):
        if prev["tenkan_sen"] <= prev["kijun_sen"] < last["tenkan_sen"]:
            tk_cross = "bullish"
        elif prev["tenkan_sen"] >= prev["kijun_sen"] > last["tenkan_sen"]:
            tk_cross = "bearish"

    if price > cloud_top:
        price_vs_cloud = "above"
    elif price < cloud_bottom:
        price_vs_cloud = "below"
    else:
        price_vs_cloud = "inside"

    vote = "neutral"
    if price_vs_cloud == "above" and tk_cross != "bearish":
        vote = "buy"
    elif price_vs_cloud == "below" and tk_cross != "bullish":
        vote = "sell"

    details = {
        "price_vs_cloud": price_vs_cloud,
        "tk_cross": tk_cross,
        "cloud_top": round(cloud_top, 2),
        "cloud_bottom": round(cloud_bottom, 2),
    }
    return vote, details


# ---------------------------------------------------------------------------
# ZIGZAG (built in-house)
# ---------------------------------------------------------------------------
# PROVENANCE: standard percentage-reversal ZigZag definition (the same
# algorithm underlying every mainstream ZigZag indicator) — DISTINCT from the
# fixed left/right-bar swing-pivot detection already used elsewhere in this
# project (gann_square9.detect_pivots / gann_decision_system._detect_pivots),
# which flags a pivot the instant N bars confirm it regardless of how large
# the move was. ZigZag instead only confirms a pivot once price has reversed
# by at least `reversal_pct` from the prior extreme — this filters out small
# moves the fixed-bar method would still flag, at the cost of some lag before
# the most recent swing is confirmed (by construction, the very last extreme
# in a still-developing trend is intentionally left OUT of the returned list,
# since it hasn't reversed by reversal_pct yet and could still extend further).

ZIGZAG_DEFAULT_REVERSAL_PCT = 5.0


@dataclass(frozen=True)
class ZigZagPoint:
    index: int          # positional index into the input series
    price: float
    kind: str            # "high" or "low"


def compute_zigzag(high: pd.Series, low: pd.Series,
                    reversal_pct: float = ZIGZAG_DEFAULT_REVERSAL_PCT) -> list[ZigZagPoint]:
    """
    Walks the price series bar by bar, tracking the current trend's running
    extreme (highest high while trending up, lowest low while trending down).
    A pivot is CONFIRMED and recorded only once price has retraced at least
    `reversal_pct` percent from that running extreme — not on every local
    wiggle. The final, still-developing swing (if any) is deliberately
    excluded, since it hasn't met the reversal threshold and may not be a
    real pivot at all yet.
    """
    h, l = high.reset_index(drop=True), low.reset_index(drop=True)
    n = len(h)
    if n < 2:
        return []

    pivots: list[ZigZagPoint] = []
    trend: str | None = None  # "up" or "down", None until an initial move is confirmed
    extreme_idx = 0
    extreme_price = float(h.iloc[0])  # provisional reference point before any trend is established
    reference_price = float(h.iloc[0])

    for i in range(1, n):
        bar_high, bar_low = float(h.iloc[i]), float(l.iloc[i])

        if trend is None:
            move_up_pct = (bar_high - reference_price) / reference_price * 100
            move_down_pct = (reference_price - bar_low) / reference_price * 100
            if move_up_pct >= reversal_pct:
                trend = "up"
                extreme_idx, extreme_price = i, bar_high
            elif move_down_pct >= reversal_pct:
                trend = "down"
                extreme_idx, extreme_price = i, bar_low
            continue

        if trend == "up":
            if bar_high > extreme_price:
                extreme_idx, extreme_price = i, bar_high
                continue
            retrace_pct = (extreme_price - bar_low) / extreme_price * 100
            if retrace_pct >= reversal_pct:
                pivots.append(ZigZagPoint(index=extreme_idx, price=round(extreme_price, 2), kind="high"))
                trend = "down"
                extreme_idx, extreme_price = i, bar_low
        else:  # trend == "down"
            if bar_low < extreme_price:
                extreme_idx, extreme_price = i, bar_low
                continue
            retrace_pct = (bar_high - extreme_price) / extreme_price * 100
            if retrace_pct >= reversal_pct:
                pivots.append(ZigZagPoint(index=extreme_idx, price=round(extreme_price, 2), kind="low"))
                trend = "up"
                extreme_idx, extreme_price = i, bar_high

    return pivots


# ---------------------------------------------------------------------------
# FIBONACCI RETRACEMENT (built in-house)
# ---------------------------------------------------------------------------
# PROVENANCE: standard Fibonacci retracement ratios (23.6/38.2/50/61.8/78.6%)
# applied to the most recent confirmed ZigZag swing (compute_zigzag, above) —
# reuses the swing detection this project already has rather than adding a
# second pivot-finding method. ADDED 2026-07 per Abdo's explicit request to
# have Fibonacci available as an alternative support/resistance source to
# Square of Nine, with the winner picked empirically via backtest (see
# full_universe_analysis.SUPPORT_RESISTANCE_METHOD).

FIBONACCI_RATIOS = (0.236, 0.382, 0.5, 0.618, 0.786)


@dataclass(frozen=True)
class FibonacciLevels:
    swing_high: float
    swing_low: float
    levels: dict          # ratio -> retraced price, between swing_low and swing_high


def compute_fibonacci_levels(high: pd.Series, low: pd.Series) -> "FibonacciLevels | None":
    """
    Anchors on the most recent confirmed ZigZag swing (its last high pivot and
    last low pivot, whichever order they occurred in) and retraces
    FIBONACCI_RATIOS between them. Returns None if fewer than one high and one
    low pivot are available yet (same "not enough data" contract as the other
    per-ticker tools here).
    """
    pivots = compute_zigzag(high, low)
    highs = [p.price for p in pivots if p.kind == "high"]
    lows = [p.price for p in pivots if p.kind == "low"]
    if not highs or not lows:
        return None

    swing_high, swing_low = highs[-1], lows[-1]
    if swing_high <= swing_low:
        return None

    span = swing_high - swing_low
    levels = {ratio: round(swing_high - span * ratio, 2) for ratio in FIBONACCI_RATIOS}
    return FibonacciLevels(swing_high=round(swing_high, 2), swing_low=round(swing_low, 2), levels=levels)


# ---------------------------------------------------------------------------
# VOLUME PROFILE / MARKET PROFILE (built in-house)
# ---------------------------------------------------------------------------
# PROVENANCE: standard Volume Profile construction — split the traded price
# range into equal-width bins, distribute each bar's volume across the bins
# its [low, high] range overlaps (proportional to the overlap), then report
# the Point of Control (POC = the bin with the most volume) and the Value
# Area (the tightest price band containing value_area_pct of total volume,
# built by expanding outward from the POC bin). This proportional-overlap
# distribution is a standard, defensible simplification — the true
# tick-by-tick volume-at-price isn't available from daily OHLCV bars, so
# spreading a bar's volume across its full range (rather than dumping it all
# on the close, a cruder alternative) is the better-justified choice given
# the data actually available here.

VOLUME_PROFILE_LOOKBACK_BARS = 60
VOLUME_PROFILE_NUM_BINS = 20
VOLUME_PROFILE_VALUE_AREA_PCT = 0.70  # standard convention (~1 std dev equivalent)


@dataclass
class VolumeProfileResult:
    poc_price: float               # Point of Control: price level with the most traded volume
    value_area_high: float
    value_area_low: float
    bins: pd.DataFrame              # bin_low, bin_high, volume — for charting/inspection


def compute_volume_profile(high: pd.Series, low: pd.Series, volume: pd.Series,
                            num_bins: int = VOLUME_PROFILE_NUM_BINS,
                            value_area_pct: float = VOLUME_PROFILE_VALUE_AREA_PCT) -> VolumeProfileResult:
    price_min = float(low.min())
    price_max = float(high.max())
    if price_max <= price_min:
        raise ValueError("compute_volume_profile: price range is zero or negative — check input data.")

    bin_edges = np.linspace(price_min, price_max, num_bins + 1)
    bin_volume = np.zeros(num_bins)

    for bar_high, bar_low, bar_volume in zip(high.values, low.values, volume.values):
        bar_range = bar_high - bar_low
        if bar_range <= 0:
            idx = min(int((bar_high - price_min) / (bin_edges[1] - bin_edges[0])), num_bins - 1)
            bin_volume[idx] += bar_volume
            continue
        for b in range(num_bins):
            b_lo, b_hi = bin_edges[b], bin_edges[b + 1]
            overlap = min(bar_high, b_hi) - max(bar_low, b_lo)
            if overlap > 0:
                bin_volume[b] += bar_volume * (overlap / bar_range)

    poc_idx = int(np.argmax(bin_volume))
    poc_price = (bin_edges[poc_idx] + bin_edges[poc_idx + 1]) / 2

    total_volume = bin_volume.sum()
    target_volume = value_area_pct * total_volume
    included = {poc_idx}
    covered = bin_volume[poc_idx]
    left, right = poc_idx - 1, poc_idx + 1
    while covered < target_volume and (left >= 0 or right < num_bins):
        left_vol = bin_volume[left] if left >= 0 else -1.0
        right_vol = bin_volume[right] if right < num_bins else -1.0
        if right_vol >= left_vol:
            covered += right_vol
            included.add(right)
            right += 1
        else:
            covered += left_vol
            included.add(left)
            left -= 1

    value_area_low = bin_edges[min(included)]
    value_area_high = bin_edges[max(included) + 1]

    bins_df = pd.DataFrame({
        "bin_low": bin_edges[:-1], "bin_high": bin_edges[1:], "volume": bin_volume,
    })

    return VolumeProfileResult(
        poc_price=round(float(poc_price), 2),
        value_area_high=round(float(value_area_high), 2),
        value_area_low=round(float(value_area_low), 2),
        bins=bins_df,
    )


def volume_profile_vote(current_price: float, profile: VolumeProfileResult) -> str:
    """
    Simple positional read, same style as confirm_signals.py's above/below-MA
    checks: price above the POC (where most volume traded) => buy lean, below
    => sell lean. Not a claim that this is the only valid way to read a
    volume profile (value-area breakouts are another common approach) — this
    is one reasonable, transparent interpretation.
    """
    if current_price > profile.poc_price:
        return "buy"
    if current_price < profile.poc_price:
        return "sell"
    return "neutral"


# ---------------------------------------------------------------------------
# PIVOT POINTS (built in-house)
# ---------------------------------------------------------------------------
# PROVENANCE: standard floor-trader Pivot Points formula (confirmed via web
# search 2026-07 as the conventional/documented version — this is a
# well-established, unambiguous formula, not something requiring a specific
# book citation):
#     PP = (High + Low + Close) / 3
#     R1 = 2*PP - Low        S1 = 2*PP - High
#     R2 = PP + (High - Low)  S2 = PP - (High - Low)
#     R3 = High + 2*(PP - Low)  S3 = Low - 2*(High - PP)
# Computed from the PRIOR completed bar (yesterday's H/L/C), which is the
# standard convention — pivots for "today" are always derived from
# yesterday's range.

@dataclass(frozen=True)
class PivotPointLevels:
    pp: float
    r1: float
    r2: float
    r3: float
    s1: float
    s2: float
    s3: float


def compute_pivot_points(prior_high: float, prior_low: float, prior_close: float) -> PivotPointLevels:
    pp = (prior_high + prior_low + prior_close) / 3
    r1 = 2 * pp - prior_low
    s1 = 2 * pp - prior_high
    r2 = pp + (prior_high - prior_low)
    s2 = pp - (prior_high - prior_low)
    r3 = prior_high + 2 * (pp - prior_low)
    s3 = prior_low - 2 * (prior_high - pp)
    return PivotPointLevels(
        pp=round(pp, 2), r1=round(r1, 2), r2=round(r2, 2), r3=round(r3, 2),
        s1=round(s1, 2), s2=round(s2, 2), s3=round(s3, 2),
    )


def pivot_points_vote(current_price: float, levels: PivotPointLevels) -> str:
    """Price above the central Pivot Point (PP) => buy lean, below => sell lean —
    the standard, most basic pivot-points read; R1-R3/S1-S3 are exposed in
    `levels` for anyone who wants a finer-grained reading than this vote uses."""
    if current_price > levels.pp:
        return "buy"
    if current_price < levels.pp:
        return "sell"
    return "neutral"


# ---------------------------------------------------------------------------
# COMBINED GROUP EVALUATION (see INTEGRATION NOTE in the module docstring)
# ---------------------------------------------------------------------------

def evaluate_advanced_technical_group(hist: pd.DataFrame) -> GroupResult:
    """
    Runs everything in this module against one ticker's OHLCV history and
    combines the votes into a single GroupResult, in the same shape
    committee_signals.py's other groups already use. ZigZag is reported for
    context (recent confirmed swing points) but does NOT cast a vote itself —
    it's a descriptive/annotation tool, not a directional signal, same
    treatment as gann_decision_system's upcoming time-cycle dates.
    """
    result = GroupResult()
    current_price = float(hist["Close"].iloc[-1])

    if not TALIB_AVAILABLE:
        result.details["talib"] = "unavailable_not_installed"
        result.votes_unavailable += 1
    elif len(hist) < TALIB_MIN_BARS:
        result.details["talib"] = "insufficient_history"
        result.votes_unavailable += 1
    else:
        snapshot = compute_talib_snapshot(hist["High"], hist["Low"], hist["Close"], hist["Volume"])
        talib_net, talib_details = talib_vote(snapshot, current_price)
        result.details["talib"] = talib_details
        result.details["talib_net_vote"] = talib_net
        if talib_net == "buy":
            result.votes_buy += 1
        elif talib_net == "sell":
            result.votes_sell += 1
        else:
            result.votes_neutral += 1

    if len(hist) < ICHIMOKU_SENKOU_B_PERIOD + ICHIMOKU_DISPLACEMENT:
        result.details["ichimoku"] = "insufficient_history"
        result.votes_unavailable += 1
    else:
        ichimoku_df = compute_ichimoku(hist["High"], hist["Low"], hist["Close"])
        ich_vote, ich_details = ichimoku_vote(ichimoku_df, hist["Close"])
        result.details["ichimoku"] = ich_details
        result.details["ichimoku_vote"] = ich_vote
        if ich_vote == "buy":
            result.votes_buy += 1
        elif ich_vote == "sell":
            result.votes_sell += 1
        elif ich_vote == "neutral":
            result.votes_neutral += 1
        else:
            result.votes_unavailable += 1

    if len(hist) < 2:
        result.details["pivot_points"] = "insufficient_history"
        result.votes_unavailable += 1
    else:
        prior = hist.iloc[-2]
        levels = compute_pivot_points(float(prior["High"]), float(prior["Low"]), float(prior["Close"]))
        pp_vote = pivot_points_vote(current_price, levels)
        result.details["pivot_points"] = levels.__dict__
        result.details["pivot_points_vote"] = pp_vote
        if pp_vote == "buy":
            result.votes_buy += 1
        elif pp_vote == "sell":
            result.votes_sell += 1
        else:
            result.votes_neutral += 1

    # Fibonacci retracement — exposed as a detail only (no vote of its own,
    # same treatment as ZigZag): it exists so entry/exit pricing can be
    # computed from it as an alternative to Pivot Points, see
    # full_universe_analysis.SUPPORT_RESISTANCE_METHOD.
    fib = compute_fibonacci_levels(hist["High"], hist["Low"])
    result.details["fibonacci_levels"] = fib.__dict__ if fib else "insufficient_history"

    if len(hist) < 20:
        result.details["volume_profile"] = "insufficient_history"
        result.votes_unavailable += 1
    else:
        window = hist.tail(VOLUME_PROFILE_LOOKBACK_BARS)
        profile = compute_volume_profile(window["High"], window["Low"], window["Volume"])
        vp_vote = volume_profile_vote(current_price, profile)
        result.details["volume_profile"] = {
            "poc": profile.poc_price,
            "value_area_high": profile.value_area_high,
            "value_area_low": profile.value_area_low,
        }
        result.details["volume_profile_vote"] = vp_vote
        if vp_vote == "buy":
            result.votes_buy += 1
        elif vp_vote == "sell":
            result.votes_sell += 1
        else:
            result.votes_neutral += 1

    if len(hist) >= 30:
        zigzag_points = compute_zigzag(hist["High"], hist["Low"])
        result.details["zigzag_recent_pivots"] = [
            {"kind": p.kind, "price": p.price} for p in zigzag_points[-5:]
        ]
    else:
        result.details["zigzag_recent_pivots"] = "insufficient_history"

    return result


# ---------------------------------------------------------------------------
# SMOKE TEST (synthetic data — no network needed; run this first to sanity-check)
# ---------------------------------------------------------------------------

def _make_synthetic_ohlcv(n: int = 300, seed: int = 7) -> pd.DataFrame:
    """Simple synthetic random-walk OHLCV series, used only to confirm every
    function in this module runs end-to-end without crashing and returns
    internally-consistent output — NOT a substitute for testing against real
    price data or a known worked example."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    returns = rng.normal(loc=0.0003, scale=0.02, size=n)
    close = 100 * np.cumprod(1 + returns)
    high = close * (1 + np.abs(rng.normal(0, 0.01, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.01, n)))
    open_ = close * (1 + rng.normal(0, 0.005, n))
    volume = rng.integers(1_000_000, 5_000_000, n).astype(float)
    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume}, index=dates
    )


def main() -> None:
    hist = _make_synthetic_ohlcv()
    print(f"Synthetic smoke test: {len(hist)} bars, price range "
          f"{hist['Low'].min():.2f}-{hist['High'].max():.2f}.\n")

    print(f"TA-Lib installed: {TALIB_AVAILABLE}")
    if TALIB_AVAILABLE:
        snapshot = compute_talib_snapshot(hist["High"], hist["Low"], hist["Close"], hist["Volume"])
        net, votes = talib_vote(snapshot, float(hist["Close"].iloc[-1]))
        print(f"  TA-Lib net vote: {net} — {votes}")
    else:
        print("  Skipped TA-Lib functions (not installed in this environment).")

    ichimoku_df = compute_ichimoku(hist["High"], hist["Low"], hist["Close"])
    ich_vote, ich_details = ichimoku_vote(ichimoku_df, hist["Close"])
    print(f"\nIchimoku vote: {ich_vote} — {ich_details}")

    zigzag_points = compute_zigzag(hist["High"], hist["Low"])
    print(f"\nZigZag: {len(zigzag_points)} confirmed pivots, last 5: "
          f"{[(p.kind, p.price) for p in zigzag_points[-5:]]}")

    profile = compute_volume_profile(hist["High"].tail(60), hist["Low"].tail(60), hist["Volume"].tail(60))
    print(f"\nVolume Profile (last 60 bars): POC={profile.poc_price}, "
          f"value area=[{profile.value_area_low}, {profile.value_area_high}]")

    prior = hist.iloc[-2]
    levels = compute_pivot_points(float(prior["High"]), float(prior["Low"]), float(prior["Close"]))
    pp_vote = pivot_points_vote(float(hist["Close"].iloc[-1]), levels)
    print(f"\nPivot Points: {levels} -> vote={pp_vote}")

    print("\nCombined group evaluation:")
    result = evaluate_advanced_technical_group(hist)
    print(f"  net_vote={result.net_vote}  buy={result.votes_buy} sell={result.votes_sell} "
          f"neutral={result.votes_neutral} unavailable={result.votes_unavailable}")
    print(f"  details keys: {list(result.details.keys())}")
    print("\nSmoke test completed without errors.")


if __name__ == "__main__":
    main()
