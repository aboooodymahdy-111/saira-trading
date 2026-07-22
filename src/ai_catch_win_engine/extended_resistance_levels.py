"""
ai_catch_win_engine/extended_resistance_levels.py — مستويات دعم/مقاومة حقيقية
إضافية لأهداف AI Catch & Win الكبيرة (طلب عبده 2026-07-18: "قد تكون الزاوية
720 أو أكثر في مربع جان والمثل في فيبوناتشي" — لو AI بتوقع مكسب أكبر من أبعد
مقاومة موجودة حاليًا في full_universe_analysis.compute_entry_exit_levels).

**لماذا ملف منفصل بدل تعديل compute_fibonacci_levels/gann_committee_vote
مباشرة**: الدالتان الأصليتان مُستخدَمتان في الفحص اليومي الكامل (full_universe_
analysis.py) — تمديدهما هناك يغيّر سلوك pipeline موجود ومُختبَر بلا داعٍ. هذا
الملف يبني **مستويات إضافية فقط** (لا يعدّل أي كود قائم)، تُستخدَم فقط في
مسار AI Catch & Win لو هدف AI تخطّى كل المستويات العادية.

**مربع التسعة، دورات متعددة**: نفس `gann_square9_precise.move_around_square`
المستخدَمة بالفعل في `gann_decision_system.calibrate_square9_angle`، لكن
بـ`rotations` أكبر من 1.0 (2.0 = "720 درجة" حرفيًا كما ذكر عبده، 3.0 = 1080،
...) — نفس الصيغة المرجعية من الكتاب (Chapter 1)، فقط بعدد لفّات أكبر.

**فيبوناتشي، امتدادات (extensions) لا فقط ارتدادات (retracements)**:
FIBONACCI_RATIOS الأصلية (0.236-0.786) كلها **داخل** مدى التأرجح (swing_low
إلى swing_high). الامتدادات القياسية (1.272, 1.618, 2.618) بتمتد **خارج**
swing_high — نفس معادلة compute_fibonacci_levels بالضبط لكن بنسب > 1.0.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, ".")

from advanced_technical_tools import compute_zigzag
from gann_square9_precise import cell_price, move_around_square, nearest_cell_to_price

FIBONACCI_EXTENSION_RATIOS = (1.272, 1.618, 2.618, 4.236)
SQUARE9_EXTRA_ROTATIONS = (2.0, 3.0, 4.0)  # 720°, 1080°, 1440°


def fibonacci_extension_levels(high: pd.Series, low: pd.Series) -> list[float]:
    """
    نفس ارتكاز compute_fibonacci_levels بالضبط (آخر swing عالي/منخفض مؤكَّد من
    ZigZag)، لكن يرجّع مستويات **خارج** swing_high (امتدادات، لا ارتدادات) —
    قائمة فارغة لو لا swing كافٍ (نفس عقد "بيانات غير كافية" لبقية الأدوات).
    """
    pivots = compute_zigzag(high, low)
    highs = [p.price for p in pivots if p.kind == "high"]
    lows = [p.price for p in pivots if p.kind == "low"]
    if not highs or not lows:
        return []

    swing_high, swing_low = highs[-1], lows[-1]
    if swing_high <= swing_low:
        return []

    span = swing_high - swing_low
    return [round(swing_high + span * (ratio - 1.0), 2) for ratio in FIBONACCI_EXTENSION_RATIOS]


def square9_extended_levels(pivot_price: float, price_increment: float) -> list[float]:
    """
    مستويات مربع9 على دورات إضافية (2-4 لفّات كاملة = 720°-1440°) حوالين
    pivot_price — نفس صيغة move_around_square المرجعية بالضبط، بعدد لفّات أكبر.
    """
    if price_increment <= 0:
        return []
    pivot_cell = nearest_cell_to_price(pivot_price, price_increment, 0.0)
    levels = []
    for rotations in SQUARE9_EXTRA_ROTATIONS:
        try:
            moved_cell = round(move_around_square(pivot_cell, rotations))
        except ValueError:
            continue
        if moved_cell >= 1:
            levels.append(cell_price(moved_cell, price_increment, 0.0))
    return sorted(set(levels))


def extended_resistances_above(current_price: float, high: pd.Series, low: pd.Series,
                                price_increment: float | None) -> list[float]:
    """
    يجمع كل المستويات الممتدة (فيبوناتشي + مربع9) اللي فوق current_price فقط
    — دالة الاستخدام الرئيسية من ai_catch_win.py، تُستدعى فقط لو هدف AI تخطّى
    كل مستويات compute_entry_exit_levels العادية (راجع docstring الملف).
    """
    levels = list(fibonacci_extension_levels(high, low))
    if price_increment is not None:
        # آخر قمة معروفة كنقطة ارتكاز لمربع9 (نفس منطق calibrate_square9_angle:
        # الإسقاط يبدأ من pivot حقيقي، لا من current_price مباشرة)
        pivots = compute_zigzag(high, low)
        recent_highs = [p.price for p in pivots if p.kind == "high"]
        if recent_highs:
            levels.extend(square9_extended_levels(recent_highs[-1], price_increment))
    return sorted(set(level for level in levels if level > current_price))
