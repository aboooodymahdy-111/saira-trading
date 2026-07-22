"""
ai_catch_win_engine/is_trading_day.py — فحص "هل النهاردة يوم تداول NYSE فعلي؟"
(طلب عبده 2026-07-18: "خلي التحليل والتقرير يتموا أيام التداول فقط") —
يستبعد عطلات نهاية الأسبوع **وإجازات NYSE الرسمية** (Thanksgiving, Christmas,
إلخ)، لا مجرد فحص السبت/الأحد.

يُستخدَم كخطوة أولى في .github/workflows/ai-catch-win.yml (وأي ورك-فلو
تداولي آخر لاحقًا) — يخرج بكود 1 (فشل، يوقف الخطوات التالية) لو مش يوم
تداول، بلا حاجة لمكتبة NYSE calendar داخل كل سكريبت على حدة.
"""
from __future__ import annotations

import sys
from datetime import date

import pandas_market_calendars as mcal


def is_nyse_trading_day(check_date: date | None = None) -> bool:
    check_date = check_date or date.today()
    nyse = mcal.get_calendar("NYSE")
    schedule = nyse.schedule(start_date=check_date.isoformat(), end_date=check_date.isoformat())
    return not schedule.empty


if __name__ == "__main__":
    import os

    today_is_trading_day = is_nyse_trading_day()
    print(f"{date.today().isoformat()}: {'trading day' if today_is_trading_day else 'NOT a trading day'}")

    # يكتب النتيجة كـstep output (GITHUB_OUTPUT) بدل الاعتماد على exit code —
    # كده باقي خطوات الورك-فلو بتتخطّى (skip) نظيفة عبر `if:` بدل ما التشغيلة
    # كلها تظهر "فشل" أحمر على GitHub مع إن التخطّي ده متعمد ومقصود تمامًا،
    # مش عطل حقيقي (راجع .github/workflows/ai-catch-win.yml).
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as f:
            f.write(f"is_trading_day={'true' if today_is_trading_day else 'false'}\n")

    sys.exit(0)  # النجاح هنا يعني "الفحص اتنفّذ صح"، لا "النهاردة يوم تداول"
