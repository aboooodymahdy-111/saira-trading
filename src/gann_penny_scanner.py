# -*- coding: utf-8 -*-
"""
==================================================================
نظام تحليل وتصويت متكامل - كل عنصر له صوت مستقل:
  1. صوت لكل كوكب على حدة (انعكاس/تلامس عند خط الكوكب)
  2. صوت مربع التسعة (انعكاس عند زاوية أو كسرها والاستمرار)
  3. صوت فيبوناتشي
  4. صوت الفوليوم
  5. صوت الأخبار
  6. صوت إضافي (Bonus) لو الفوليوم + الأخبار حصلوا مع بعض
سكانر بيني ستوكس يشتغل كل 5 دقايق (عن طريق GitHub Actions)
مع إرسال تنبيهات مباشرة على تيليجرام
==================================================================

المتطلبات:
    pip install yfinance pandas numpy requests --break-system-packages

متغيرات البيئة المطلوبة (Environment Variables / GitHub Secrets):
    TELEGRAM_BOT_TOKEN   -> توكن البوت من BotFather
    TELEGRAM_CHAT_ID     -> رقم الشات بتاعك
"""

import os
import sys
import math
import time
from dataclasses import dataclass, field
from typing import List, Dict, Optional
import numpy as np
import pandas as pd
import requests

try:
    import yfinance as yf
except ImportError:
    raise SystemExit("محتاج تثبت المكتبة الأول: pip install yfinance --break-system-packages")

_SAIRA_API_APP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "saira-api")
if _SAIRA_API_APP_DIR not in sys.path:
    sys.path.insert(0, _SAIRA_API_APP_DIR)

from app.analysis.astro import geo_longitude  # درجات الكواكب الحقيقية عبر pyswisseph


# ==========================================
# 0. إعدادات عامة
# ==========================================
CONFIG = {
    "tolerance_pct": 0.015,        # هامش خطأ التوافق بين المستويات (1.5%)
    "volume_spike_ratio": 3.0,     # الفوليوم لازم يبقى 3 أضعاف المتوسط
    "volume_avg_period": 20,       # عدد الأيام لحساب متوسط الفوليوم
    "min_price": 0.10,             # أقل سعر مقبول - أي سهم بالنطاق ده وارد يتفحص
    "max_price": 20.0,             # أعلى سعر مقبول - أي سهم بالنطاق ده وارد يتفحص
    "min_breakout_pct": 15.0,      # أقل نسبة تغيّر % خلال آخر جلسة تداول عشان تتحسب طفرة
    "breakout_lookback_days": 5,   # المدى الزمني (بالأيام) لحساب مستويات مربع9/فيبوناتشي فقط
    "sq9_break_confirm_pct": 0.5,  # % فوق زاوية مربع9 عشان تتأكد إنها "كسرت واستمرت"
    "min_total_votes_for_alert": 5,  # الحد الأدنى الإجمالي لعدد الأصوات عشان يتبعت تنبيه
}

# أسماء الكواكب المتابَعة - درجاتها الحقيقية بتتحسب لحظة كل سكان عبر
# get_current_planet_longitudes() تحت (pyswisseph، نفس مصدر astro.py في الـ API)
TRACKED_PLANETS = ["sun", "moon", "mercury", "venus", "mars", "jupiter", "saturn"]

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


def get_current_planet_longitudes(planets: List[str] = None) -> Dict[str, float]:
    """درجات الطول الجيوسنتري الحقيقية لحظة الاستدعاء، عبر pyswisseph."""
    planets = planets or TRACKED_PLANETS
    now_epoch = time.time()
    return {p: geo_longitude(p, now_epoch) for p in planets}


# ==========================================
# 1. مربع التسعة (Square of Nine)
# ==========================================
def calculate_square_of_nine_targets(price: float, angles=(45, 90, 135, 180, 225, 270, 315, 360)) -> (Dict, Dict):
    """حساب مستويات المقاومة والدعم بمعادلة الجذر التربيعي لمربع التسعة."""
    sqrt_p = math.sqrt(price)
    targets_up, targets_down = {}, {}
    for angle in angles:
        factor = angle / 180.0
        targets_up[f"Sq9_{angle}deg"] = round((sqrt_p + factor) ** 2, 4)
        if sqrt_p - factor > 0:
            targets_down[f"Sq9_{angle}deg"] = round((sqrt_p - factor) ** 2, 4)
    return targets_up, targets_down


def check_sq9_signal(current_price: float, prev_price: float,
                      last_high: float, last_low: float,
                      tolerance_pct: float) -> (bool, str):
    """
    صوت مربع التسعة - حالتين مختلفتين تعتبرا صوت:
      أ) انعكاس عند زاوية مربع9 (السعر لمس الزاوية وارتد)
      ب) كسر الزاوية والاستمرار (بريك اوت) - بيتقاس من آخر قمة أو قاع
    """
    reasons = []

    # نحسب أهداف مربع9 من آخر قمة وآخر قاع (مش بس السعر الحالي)
    up_from_high, down_from_high = calculate_square_of_nine_targets(last_high)
    up_from_low, down_from_low = calculate_square_of_nine_targets(last_low)
    all_levels = {**up_from_high, **down_from_high, **up_from_low, **down_from_low}

    # حالة أ: انعكاس (تلامس) - السعر قريب من زاوية والحركة عكست اتجاهها
    touched_level = None
    for name, level in all_levels.items():
        if level > 0 and abs(current_price - level) / current_price <= tolerance_pct:
            touched_level = (name, level)
            break

    if touched_level:
        moved_away = abs(current_price - prev_price) / prev_price > 0.005
        if moved_away:
            reasons.append(f"انعكاس عند زاوية مربع9: {touched_level[0]} ({touched_level[1]})")

    # حالة ب: كسر الزاوية والاستمرار (بريك اوت) - قايس من آخر قمة
    # الشرط: السعر كان تحت الزاوية (prev_price) وبقى فوقها بهامش تأكيد
    # sq9_break_confirm_pct فوق الزاوية نفسها (مش مجرد ملامسة عابرة)
    breakout_confirm = CONFIG["sq9_break_confirm_pct"] / 100
    for name, level in up_from_high.items():
        if prev_price < level and current_price >= level * (1 + breakout_confirm):
            reasons.append(f"كسر زاوية مربع9 والاستمرار: {name} ({level}) - قيس من آخر قمة {last_high}")

    return (len(reasons) > 0), " | ".join(reasons)


# ==========================================
# 2. خطوط الكواكب - صوت مستقل لكل كوكب
# ==========================================
def calculate_planetary_price_line(planet_longitude: float, current_price: float,
                                    scale_factor: float = 1.0) -> float:
    """تحويل درجة الكوكب لأقرب خط سعري ممكن يكون عنده انعكاس/تلامس."""
    base = (planet_longitude % 360) * scale_factor
    cycles = round((current_price - base) / (360 * scale_factor))
    return round(base + cycles * 360 * scale_factor, 4)


def check_planetary_votes(current_price: float, prev_price: float,
                           planets: Dict[str, float],
                           tolerance_pct: float) -> (int, List[str]):
    """
    صوت مستقل لكل كوكب على حدة.
    لو فيه كلاستر (أكتر من كوكب في نفس المنطقة السعرية) كل كوكب بياخد صوته لوحده.
    بيرجع (عدد الأصوات, تفاصيل كل كوكب اتفعل)
    """
    votes = 0
    details = []
    for planet_name, longitude in planets.items():
        line = calculate_planetary_price_line(longitude, current_price)
        if line <= 0:
            continue
        if abs(current_price - line) / current_price <= tolerance_pct:
            votes += 1
            details.append(f"🪐 {planet_name}: انعكاس/تلامس عند خط {line}")
    return votes, details


# ==========================================
# 3. فيبوناتشي - صوت مستقل
# ==========================================
def calculate_fibonacci_levels(high_price: float, low_price: float) -> Dict:
    diff = high_price - low_price
    return {
        "Fib_38.2%": round(low_price + diff * 0.382, 4),
        "Fib_50.0%": round(low_price + diff * 0.500, 4),
        "Fib_61.8%": round(low_price + diff * 0.618, 4),
        "Fib_100.0%": round(high_price, 4),
        "Fib_161.8%": round(low_price + diff * 1.618, 4),
    }


def check_fibonacci_vote(current_price: float, high_price: float, low_price: float,
                          tolerance_pct: float) -> (bool, str):
    fib_levels = calculate_fibonacci_levels(high_price, low_price)
    for name, level in fib_levels.items():
        if abs(current_price - level) / current_price <= tolerance_pct:
            return True, f"🌀 السعر عند مستوى فيبوناتشي {name} ({level})"
    return False, ""


# ==========================================
# 4. صوت الفوليوم (مستقل) - لازم يكون فوليوم شراء (Bullish) مش بيع
# ==========================================
def check_volume_vote(hist: pd.DataFrame, avg_period: int, spike_ratio: float) -> (bool, float, bool):
    """
    فحص صوت الفوليوم - بيتحقق من شرطين:
      1) الفوليوم أعلى من المتوسط بالنسبة المطلوبة (spike)
      2) الشمعة اللي حصل فيها السبايك شمعة صاعدة (شراء) مش هابطة (بيع)
    فوليوم ضخم مع هبوط سعري (بيع/تصريف) ميتحسبش صوت خالص حتى لو كان ضخم جداً.
    بيرجع (هل_الصوت_متحقق, نسبة_الفوليوم, هل_الشمعة_صاعدة)
    """
    if len(hist) < avg_period + 1:
        return False, 0.0, False

    recent_volume = hist["Volume"].iloc[-1]
    avg_volume = hist["Volume"].iloc[-(avg_period + 1):-1].mean()

    if avg_volume <= 0:
        return False, 0.0, False

    ratio = recent_volume / avg_volume
    has_spike = ratio >= spike_ratio

    # فحص اتجاه الشمعة: صاعدة لو الإغلاق أعلى من الافتتاح، وأعلى من إغلاق اليوم اللي قبله
    last_close = hist["Close"].iloc[-1]
    last_open = hist["Open"].iloc[-1]
    prev_close = hist["Close"].iloc[-2]

    is_bullish_candle = (last_close > last_open) and (last_close > prev_close)

    # الصوت النهائي: سبايك + شمعة صاعدة مع بعض
    vote = has_spike and is_bullish_candle
    return vote, round(ratio, 2), is_bullish_candle


# ==========================================
# 5. صوت الأخبار (مستقل)
# ==========================================
def check_news_vote(ticker_obj: "yf.Ticker", max_items: int = 5) -> (bool, int, List[str]):
    try:
        news = ticker_obj.news or []
    except Exception:
        news = []
    headlines = []
    for item in news[:max_items]:
        title = item.get("title") or item.get("content", {}).get("title")
        if title:
            headlines.append(title)
    return (len(headlines) > 0), len(headlines), headlines


# ==========================================
# 6. محرك التصويت الكامل - كل عنصر صوت مستقل
# ==========================================
@dataclass
class ConfluenceResult:
    ticker: str
    votes: int
    max_votes: int
    alert_level: str
    vote_breakdown: List[str]
    news_headlines: List[str]
    has_volume_anchor: bool = False   # الشرط الإجباري 1: فوليوم غير طبيعي
    has_planet_anchor: bool = False   # الشرط الإجباري 2: ارتداد عند كوكب واحد على الأقل
    planet_anchor_count: int = 0      # عدد الكواكب اللي حصل عندها ارتداد (كلاستر = أقوى)
    passes_threshold: bool = False    # النتيجة النهائية: يستحق تنبيه أم لا


def analyze_stock_confluence(ticker_symbol: str,
                              current_price: float,
                              prev_price: float,
                              high_price: float,
                              low_price: float,
                              hist: pd.DataFrame,
                              ticker_obj: "yf.Ticker",
                              planets: Dict[str, float] = None,
                              tolerance_pct: float = None) -> ConfluenceResult:
    """
    نظام التصويت الكامل - كل عنصر يحسب صوت مستقل بذاته:
      - كل كوكب صوت منفرد (ممكن ياخد أكتر من صوت لو كلاستر كواكب)
      - مربع9 صوت واحد (انعكاس أو كسر واستمرار)
      - فيبوناتشي صوت واحد
      - الفوليوم صوت واحد
      - الأخبار صوت واحد
      - بونص: لو الفوليوم + الأخبار مع بعض = صوت سادس إضافي
    """
    tolerance_pct = tolerance_pct or CONFIG["tolerance_pct"]
    planets = planets or get_current_planet_longitudes()

    vote_breakdown = []
    total_votes = 0

    # 1) أصوات الكواكب (كل كوكب لوحده)
    planet_votes, planet_details = check_planetary_votes(
        current_price, prev_price, planets, tolerance_pct
    )
    total_votes += planet_votes
    vote_breakdown.extend(planet_details)

    # 2) صوت مربع التسعة
    sq9_vote, sq9_detail = check_sq9_signal(
        current_price, prev_price, high_price, low_price, tolerance_pct
    )
    if sq9_vote:
        total_votes += 1
        vote_breakdown.append(f"🔢 مربع التسعة: {sq9_detail}")

    # 3) صوت فيبوناتشي
    fib_vote, fib_detail = check_fibonacci_vote(current_price, high_price, low_price, tolerance_pct)
    if fib_vote:
        total_votes += 1
        vote_breakdown.append(fib_detail)

    # 4) صوت الفوليوم (لازم يكون فوليوم شراء - شمعة صاعدة)
    vol_vote, vol_ratio, is_bullish = check_volume_vote(
        hist, CONFIG["volume_avg_period"], CONFIG["volume_spike_ratio"]
    )
    if vol_vote:
        total_votes += 1
        vote_breakdown.append(f"📈 فوليوم شراء غير طبيعي (x{vol_ratio} من المتوسط، شمعة صاعدة)")

    # 5) صوت الأخبار
    news_vote, news_count, headlines = check_news_vote(ticker_obj)
    if news_vote:
        total_votes += 1
        vote_breakdown.append(f"📰 أخبار حديثة ({news_count} خبر)")

    # 6) بونص: الفوليوم + الأخبار مع بعض = صوت إضافي سادس
    if vol_vote and news_vote:
        total_votes += 1
        vote_breakdown.append("⭐ بونص: الفوليوم والأخبار حصلوا مع بعض في نفس الوقت")

    # أقصى عدد أصوات ممكن = عدد الكواكب + مربع9 + فيبو + فوليوم + أخبار + بونص
    max_votes = len(planets) + 1 + 1 + 1 + 1 + 1

    if total_votes >= 5:
        alert = "🔴🔴🔴 [تنبيه أقصى قوة]"
    elif total_votes >= 3:
        alert = "🔴 [تنبيه قوي جداً]"
    elif total_votes == 2:
        alert = "🟠 [تنبيه قوي]"
    elif total_votes == 1:
        alert = "🟡 [تنبيه متوسط]"
    else:
        alert = "⚪ [لا يوجد توافق]"

    # ==========================================
    # الـ Threshold النهائي (5 شروط):
    #   إجباري: الفوليوم لازم يكون موجود
    #   إجباري: كوكب واحد على الأقل عليه ارتداد (كلاستر كواكب = صوت أقوى تلقائياً)
    #   + إجمالي الأصوات لازم يوصل لـ 5 على الأقل (شامل الفوليوم والكوكب أنفسهم)
    # لو الفوليوم أو الكوكب مفقودين -> مفيش تنبيه خالص مهما زاد عدد باقي الأصوات
    # ==========================================
    has_volume_anchor = vol_vote
    has_planet_anchor = planet_votes >= 1
    passes_threshold = (
        has_volume_anchor
        and has_planet_anchor
        and total_votes >= CONFIG["min_total_votes_for_alert"]
    )

    return ConfluenceResult(
        ticker=ticker_symbol,
        votes=total_votes,
        max_votes=max_votes,
        alert_level=alert,
        vote_breakdown=vote_breakdown,
        news_headlines=headlines,
        has_volume_anchor=has_volume_anchor,
        has_planet_anchor=has_planet_anchor,
        planet_anchor_count=planet_votes,
        passes_threshold=passes_threshold,
    )


# ==========================================
# 7. سكانر بيني ستوكس
# ==========================================
@dataclass
class BreakoutCandidate:
    ticker: str
    current_price: float
    breakout_pct: float
    confluence: ConfluenceResult


def get_penny_stock_universe(min_price: float = None, max_price: float = None,
                              min_breakout_pct: float = None,
                              max_results: int = 250) -> List[str]:
    """
    بيجيب أي سهم أمريكي متداول دلوقتي ضمن نطاق السعر المطلوب (min_price-max_price)
    وحقق نسبة تغيّر (صعود) >= min_breakout_pct خلال آخر جلسة تداول - مباشرة من
    Yahoo Finance Screener، مفيش قايمة أسهم ثابتة متسجلة مسبقًا في الكود.
    """
    min_price = CONFIG["min_price"] if min_price is None else min_price
    max_price = CONFIG["max_price"] if max_price is None else max_price
    min_breakout_pct = CONFIG["min_breakout_pct"] if min_breakout_pct is None else min_breakout_pct

    query = yf.EquityQuery("and", [
        yf.EquityQuery("btwn", ["intradayprice", min_price, max_price]),
        yf.EquityQuery("gte", ["percentchange", min_breakout_pct]),
        yf.EquityQuery("eq", ["region", "us"]),
    ])

    tickers: List[str] = []
    offset = 0
    page_size = 250
    while len(tickers) < max_results:
        try:
            resp = yf.screen(query, offset=offset, size=page_size,
                              sortField="percentchange", sortAsc=False)
        except Exception as e:
            print(f"⚠️ فشل الاستعلام من Yahoo Screener: {e}")
            break

        quotes = (resp or {}).get("quotes", [])
        if not quotes:
            break

        tickers.extend(q["symbol"] for q in quotes if q.get("symbol"))

        if len(quotes) < page_size:
            break
        offset += page_size

    return tickers[:max_results]


def scan_penny_stock_breakouts(tickers: List[str],
                                planets: Dict[str, float] = None,
                                period: str = "3mo") -> List[BreakoutCandidate]:
    """يفحص قائمة الأسهم المُمررة ويرجع المرشحين اللي عندهم طفرة سعرية + تصويت."""
    candidates = []
    planets = planets or get_current_planet_longitudes()

    for symbol in tickers:
        try:
            t = yf.Ticker(symbol)
            hist = t.history(period=period)

            if hist.empty or len(hist) < 2:
                continue

            current_price = float(hist["Close"].iloc[-1])
            prev_price = float(hist["Close"].iloc[-2])

            if not (CONFIG["min_price"] <= current_price <= CONFIG["max_price"]):
                continue

            if prev_price <= 0:
                continue

            # الطفرة = نسبة تغيّر السعر خلال آخر جلسة تداول (مقارنة بإغلاق الجلسة
            # السابقة)، سواء حصلت الحركة في دقيقة أو ساعة أو طول الجلسة بالكامل
            breakout_pct = ((current_price - prev_price) / prev_price) * 100
            if breakout_pct < CONFIG["min_breakout_pct"]:
                continue

            lookback = CONFIG["breakout_lookback_days"]
            high_price = float(hist["High"].iloc[-lookback:].max())
            low_price = float(hist["Low"].iloc[-lookback:].min())

            confluence = analyze_stock_confluence(
                ticker_symbol=symbol,
                current_price=current_price,
                prev_price=prev_price,
                high_price=high_price,
                low_price=low_price,
                hist=hist,
                ticker_obj=t,
                planets=planets,
            )

            candidates.append(BreakoutCandidate(
                ticker=symbol,
                current_price=round(current_price, 4),
                breakout_pct=round(breakout_pct, 2),
                confluence=confluence,
            ))

        except Exception as e:
            print(f"⚠️ تعذر تحليل {symbol}: {e}")
            continue

        time.sleep(0.3)

    candidates.sort(key=lambda c: (c.confluence.votes, c.breakout_pct), reverse=True)
    return candidates


# ==========================================
# 8. إرسال تنبيهات تيليجرام
# ==========================================
def send_telegram_message(message: str):
    """إرسال رسالة على تيليجرام. لازم TELEGRAM_BOT_TOKEN و TELEGRAM_CHAT_ID متظبطين."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ لم يتم ضبط TELEGRAM_BOT_TOKEN أو TELEGRAM_CHAT_ID - تم تخطي الإرسال.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        resp = requests.post(url, data=payload, timeout=10)
        if resp.status_code != 200:
            print(f"⚠️ فشل إرسال تيليجرام: {resp.text}")
    except Exception as e:
        print(f"⚠️ خطأ في الاتصال بتيليجرام: {e}")


def format_candidate_message(c: BreakoutCandidate) -> str:
    conf = c.confluence
    lines = [
        f"{conf.alert_level}",
        f"<b>{c.ticker}</b>  السعر: ${c.current_price}",
        f"نسبة الطفرة: {c.breakout_pct}%",
        f"عدد الأصوات: {conf.votes}/{conf.max_votes}  (الحد الأدنى المطلوب: {CONFIG['min_total_votes_for_alert']})",
        f"✅ فوليوم شراء: {'نعم' if conf.has_volume_anchor else 'لا'}  |  "
        f"✅ ارتداد كوكب: {'نعم (' + str(conf.planet_anchor_count) + ' كوكب)' if conf.has_planet_anchor else 'لا'}",
        "",
        "<b>تفاصيل الأصوات:</b>",
    ]
    for v in conf.vote_breakdown:
        lines.append(f"• {v}")

    if conf.news_headlines:
        lines.append("")
        lines.append("<b>آخر عنوان خبري:</b>")
        lines.append(conf.news_headlines[0])

    return "\n".join(lines)


# ==========================================
# 9. تحديد أوقات التداول الأمريكية (بتوقيت UTC)
# ==========================================
def is_within_us_trading_window() -> bool:
    """
    فحص هل الوقت الحالي (UTC) ضمن نافذة ما قبل التداول + جلسة التداول الأمريكية.
    - Pre-market: 09:00 - 14:30 UTC  (4:00 AM - 9:30 AM ET)
    - Regular:    14:30 - 21:00 UTC  (9:30 AM - 4:00 PM ET)
    ملاحظة: التوقيت ده تقريبي وبيفترض EST (UTC-5). وقت التوقيت الصيفي (EDT / UTC-4)
    هيبقى فيه فرق ساعة، فلو عايز دقة كاملة استخدم مكتبة pytz + zoneinfo مع "America/New_York".
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)

    # الأسهم الأمريكية بتتداول من الاثنين للجمعة فقط
    if now.weekday() >= 5:
        return False

    minutes = now.hour * 60 + now.minute
    pre_market_start = 9 * 60       # 09:00 UTC
    market_close = 21 * 60          # 21:00 UTC

    return pre_market_start <= minutes <= market_close


# ==========================================
# 10. نقطة التشغيل الرئيسية (تُستدعى من GitHub Actions كل 5 دقايق)
# ==========================================
def run_scan_once(planets: Dict[str, float] = None):
    """
    تشغيل واحد للسكانر - ده اللي بيتنادى من GitHub Actions كل 5 دقايق.
    مفيش قايمة أسهم ثابتة: بيجيب ديناميكيًا أي سهم أمريكي سعره ضمن النطاق
    المطلوب وحقق طفرة (تغيّر) >= الحد الأدنى خلال آخر جلسة تداول، ثم يبعت
    تنبيه تيليجرام فقط للأسهم اللي عدّت الـ threshold الكامل:
      - فوليوم شراء (spike + شمعة صاعدة) إجباري
      - ارتداد عند كوكب واحد على الأقل إجباري
      - إجمالي 5 أصوات على الأقل (شامل الفوليوم والكوكب أنفسهم)
    أي سهم ناقصه شرط من الشرطين الإجباريين، مبيتبعتش عنه تنبيه مهما زاد
    عدد باقي الأصوات.
    """
    if not is_within_us_trading_window():
        print("⏸️ خارج أوقات التداول الأمريكية (بريما ركت + الجلسة الرسمية) - تم تخطي السكان.")
        return

    tickers = get_penny_stock_universe()
    if not tickers:
        print("لا يوجد أسهم ضمن نطاق السعر المطلوب حققت طفرة كافية خلال آخر جلسة تداول.")
        return

    print(f"🔎 بدء السكان على {len(tickers)} سهم (تم اكتشافهم ديناميكيًا حسب السعر والطفرة)...")
    candidates = scan_penny_stock_breakouts(tickers, planets=planets)

    alerted = [c for c in candidates if c.confluence.passes_threshold]

    if not alerted:
        print("لا يوجد مرشحين وصلوا للـ threshold الكامل (فوليوم شراء + كوكب + 5 أصوات) في هذا السكان.")
        return

    for c in alerted:
        msg = format_candidate_message(c)
        send_telegram_message(msg)
        print(f"✅ تم إرسال تنبيه لـ {c.ticker} ({c.confluence.votes} صوت)")


if __name__ == "__main__":
    run_scan_once(planets=get_current_planet_longitudes())
