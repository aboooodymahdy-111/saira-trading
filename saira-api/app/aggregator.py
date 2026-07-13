"""مُجمِّع Alpaca WebSocket — المرحلة 4 من خطة التطوير الشاملة.

يستمع لصفقات لحظية (trades) عبر Alpaca's Basic plan (تغذية IEX، مجانية،
لا تتطلب تمويل حساب) ويبنيها بنفسه إلى شموع 30 ثانية/1 دقيقة في نفس جدول
DuckDB الذي يستخدمه باقي المشروع (candles(symbol, t, o, h, l, c, v)) —
"من اليوم الأول تبدأ ببناء أرشيفك اللحظي الخاص بك مجانًا" (نص الخطة، قسم 3).

لماذا تجميع يدوي بدل الاعتماد على Alpaca's own bars stream: خطة Basic
المجانية توفر trades لحظية لكن الـ 1-minute bars الجاهزة عندهم تتأخر ~15
دقيقة على IEX feed (قيد موثق من Alpaca) — التجميع الذاتي من trades هو الحل
المجاني الوحيد لشموع 30 ثانية شبه-فورية فعليًا، وهو بالضبط ما تنص عليه
الخطة ("الحل المجاني الصحيح: تشغيل مُجمِّع").

لا يعمل هذا الملف بدون ALPACA_KEY_ID/ALPACA_SECRET_KEY حقيقيين (راجع
config.py) — يرفض البدء صراحة بدلًا من محاولة اتصال سيفشل بصمت.

التشغيل: python -m app.aggregator AAPL MSFT GOOG   # رموز مفصولة بمسافة
"""
from __future__ import annotations

import asyncio
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone

import websockets

from .config import ALPACA_KEY_ID, ALPACA_SECRET_KEY, ALPACA_STREAM_URL
from .data import store

BUCKET_SECONDS = 30  # حجم الشمعة الأساسي — أي فريم أكبر يُعاد تجميعه عند
                     # الاستعلام (candles()) من هذا الجدول، بلا تعديل هناك.
FLUSH_INTERVAL_SECONDS = 5  # كل كام ثانية نكتب الشموع المكتملة إلى DuckDB


def _bucket_start(t_epoch: float) -> int:
    return int(t_epoch // BUCKET_SECONDS) * BUCKET_SECONDS


class BarBuilder:
    """يبني شمعة OHLCV واحدة لكل (رمز، بداية الفترة) من صفقات فردية متتالية."""

    def __init__(self) -> None:
        # symbol -> {bucket_t: {o,h,l,c,v}}
        self._open: dict[str, dict[int, dict]] = defaultdict(dict)

    def add_trade(self, symbol: str, price: float, size: int, t_epoch: float) -> None:
        bucket = _bucket_start(t_epoch)
        bars = self._open[symbol]
        if bucket not in bars:
            bars[bucket] = {"o": price, "h": price, "l": price, "c": price, "v": 0}
        bar = bars[bucket]
        bar["h"] = max(bar["h"], price)
        bar["l"] = min(bar["l"], price)
        bar["c"] = price
        bar["v"] += size

    def pop_completed(self, now_epoch: float) -> dict[str, list[dict]]:
        """يُخرج (ويحذف من الذاكرة) كل الشموع التي انتهت فترتها بالفعل —
        يُبقي الشمعة الجارية فقط، لتفادي كتابة شمعة ناقصة البيانات."""
        current_bucket = _bucket_start(now_epoch)
        completed: dict[str, list[dict]] = defaultdict(list)
        for symbol, bars in self._open.items():
            done_keys = [t for t in bars if t < current_bucket]
            for t in sorted(done_keys):
                bar = bars.pop(t)
                completed[symbol].append({"t": t, **bar})
        return completed


async def _flush_loop(builder: BarBuilder, stop_event: asyncio.Event) -> None:
    import pandas as pd
    while not stop_event.is_set():
        await asyncio.sleep(FLUSH_INTERVAL_SECONDS)
        now = datetime.now(tz=timezone.utc).timestamp()
        for symbol, bars in builder.pop_completed(now).items():
            if not bars:
                continue
            df = pd.DataFrame(bars)
            n = store.upsert(symbol, df)
            print(f"[aggregator] {symbol}: wrote {n} 30s bar(s) up to "
                  f"{datetime.fromtimestamp(bars[-1]['t'], tz=timezone.utc)}")


async def run_aggregator(symbols: list[str]) -> None:
    if not ALPACA_KEY_ID or not ALPACA_SECRET_KEY:
        raise RuntimeError(
            "ALPACA_KEY_ID/ALPACA_SECRET_KEY غير مضبوطين — سجّل حساب Alpaca "
            "Basic (مجاني) على alpaca.markets واضبط متغيري البيئة هذين قبل "
            "تشغيل المُجمِّع. لا يوجد تشغيل بدونهما."
        )
    symbols = [s.upper() for s in symbols]
    builder = BarBuilder()
    stop_event = asyncio.Event()
    flush_task = asyncio.create_task(_flush_loop(builder, stop_event))

    try:
        async with websockets.connect(ALPACA_STREAM_URL) as ws:
            await ws.recv()  # رسالة الترحيب الأولى من Alpaca
            await ws.send(json.dumps({
                "action": "auth", "key": ALPACA_KEY_ID, "secret": ALPACA_SECRET_KEY,
            }))
            auth_reply = json.loads(await ws.recv())
            if not any(m.get("T") == "success" and m.get("msg") == "authenticated"
                       for m in auth_reply):
                raise RuntimeError(f"فشل التوثيق مع Alpaca: {auth_reply}")

            await ws.send(json.dumps({"action": "subscribe", "trades": symbols}))
            print(f"[aggregator] subscribed to trades for {symbols}")

            async for raw in ws:
                messages = json.loads(raw)
                for msg in messages:
                    if msg.get("T") != "t":  # "t" = trade؛ نتجاهل رسائل أخرى (quotes/bars/status)
                        continue
                    symbol = msg["S"]
                    price = float(msg["p"])
                    size = int(msg["s"])
                    # Alpaca ترسل "t" (الطابع الزمني) كـ RFC3339 نانوثانية
                    t_epoch = datetime.fromisoformat(
                        msg["t"].replace("Z", "+00:00")
                    ).timestamp()
                    builder.add_trade(symbol, price, size, t_epoch)
    finally:
        stop_event.set()
        await flush_task


if __name__ == "__main__":
    tickers = sys.argv[1:] or ["AAPL"]
    asyncio.run(run_aggregator(tickers))
