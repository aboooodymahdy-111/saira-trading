"""جسر خط أنابيب Saira الحالي.

يستدعي full_universe_analysis.analyze_ticker() الحقيقي — نفس الدالة التي
يستخدمها full_universe_analysis.main() لكل رمز في الفحص اليومي الكامل (لجنة
فني/كمي/فلكي/فني متقدم + مستويات دخول/خروج). لا يوجد "run_committee" ولا أي
اسم بديل داخل committee_signals.py نفسه — هذا الملف تحوّل إلى مكتبة أصوات
بحتة بعد إزالة Timing Solution من المشروع (2026-07)، والدالة التي تجمّع
الأصوات الأربعة لرمز واحد فعليًا هي full_universe_analysis.evaluate_ticker_snapshot،
المُغلّفة بالجلب والفحص الأخلاقي عبر analyze_ticker().

تحذير: هذا يستدعي yfinance فعليًا (سنتين تاريخ + تصنيف القطاع + إجماع
المحللين) — طلب /committee ليس محليًا بالكامل، ويتأخر إذا كان الاتصال بطيئًا
أو خاضعًا لتقييد Yahoo. الكاش المستخدم هنا (dict فارغ) مؤقت في الذاكرة فقط —
لا يكتب إلى runs/ticker_eligibility_cache.json الحقيقي ولا يتأثر به.
"""
from __future__ import annotations

import importlib
import sys

from .config import PROJECT_ROOT

sys.path.insert(0, str(PROJECT_ROOT))


def run_committee(symbol: str) -> dict:
    symbol = symbol.upper()
    try:
        mod = importlib.import_module("full_universe_analysis")
    except Exception as exc:
        return {"available": False, "message": f"full_universe_analysis غير قابل للاستيراد: {exc}"}
    try:
        result = mod.analyze_ticker(symbol, {})
    except Exception as exc:
        return {"available": False, "message": f"خطأ أثناء التشغيل: {exc}"}
    if result is None:
        return {"available": False,
                "message": f"{symbol}: مستبعد أخلاقيًا أو تاريخ غير كافٍ أو فشل الجلب — راجع سجل الخادم"}
    return {"available": True, "symbol": symbol, "result": result}
