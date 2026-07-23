"""
ai_catch_win_engine/ai_catch_win.py — "AI Catch & Win": الأداة النهائية الموحّدة
(طلب عبده 2026-07-18) اللي بتجمع كل حاجة اتعملت في هذه الجلسة في مكان واحد:

  1. قائمة الأسهم شديدة التقلب (data/ai_catch_win_universe.csv — نسخة مجمّدة
     من volatility_screen.py، تتحدّث يدويًا من جهاز عبده كل 3 أيام تقريبًا،
     راجع تعليق عبده الصريح: "يمكنك استخدام الليست المتقلبة الموجودة بالفعل
     هذه المرة ويمكنك رفعها كمرجع قابل للتحديث دوريًا").
  2. بناء جداول ميزات + تدريب XGBoost (feature_table.py + train_model.py) —
     بلا فلك (القسم 9.18)، مع دقة الاتجاه ومعامل المعايرة (train_model.py).
  3. تنبؤ %الربح المعايَر لكل سهم (predict.py) — الاتجاه + الثقة + الحجم.
  4. **الجديد هنا**: تحويل التنبؤ لخطة صفقة فعلية (دخول/وقف/أهداف) عبر
     full_universe_analysis.compute_entry_exit_levels بمستوياته الحقيقية
     (Pivot/Fibonacci/Square9)، موجَّهة بـ ai_target_pct (راجع docstring تلك
     الدالة) — لا AI بيخترع سعر، الأسعار كلها حقيقية من دعم/مقاومة فعلي.
     لو هدف AI تخطّى حتى أبعد مستوى حقيقي عادي (T3)، يُستخدَم
     extended_resistance_levels.py (امتدادات فيبوناتشي + دورات مربع9 إضافية،
     طلب عبده الصريح: "قد تكون الزاوية 720 أو أكثر") كـ"T3+" — مُعلَّم صراحة
     كمستوى ممتد، لا مساوٍ في الثقة لـT1/T2/T3 العادية.
  5. تتبّع النتائج بمرور الوقت (prediction_tracker.py).
  6. إرسال تنبيه تليجرام + إتاحة النتيجة كـJSON لصفحة saira-api.

تنبيه ثابت (نفس preflight الموجود بكل أدوات المشروع): لا ينفّذ أي أمر شراء/
بيع حقيقي — فقط يرتّب خطط صفقات مقترحة للمراجعة اليدوية.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from datetime import date
from pathlib import Path

import pandas as pd

# مسار مطلق (src/) بدل "." النسبي — "." اعتمد على أن CWD وقت التشغيل يبقى
# src/ بالظبط، وده اتأكد إنه مش موثوق دايمًا على كل بيئة (فشل فعليًا على
# GitHub Actions Linux runner بـModuleNotFoundError رغم نجاحه محليًا على
# Windows بنفس الاستدعاء بالظبط — راجع cloud_build_feature_tables.py).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from advanced_technical_tools import compute_fibonacci_levels, compute_pivot_points
from full_universe_analysis import compute_entry_exit_levels
from gann_increment_selection import recommended_price_increment
from yahoo_fetch import fetch_ohlc

from ai_catch_win_engine.etf_screen import filter_out_etfs
from ai_catch_win_engine.extended_resistance_levels import extended_resistances_above
from ai_catch_win_engine.liquidity_screen import filter_by_price_and_liquidity
from ai_catch_win_engine.predict import rank_predictions
from ai_catch_win_engine.prediction_tracker import (check_retrain_warning,
                                                 recompute_live_calibration,
                                                 score_due_predictions)

UNIVERSE_CSV = Path("../data/ai_catch_win_universe.csv")
OUTPUT_JSON = Path("../runs/ai_catch_win_engine/ai_catch_win_latest.json")
OUTPUT_CSV = Path("../runs/ai_catch_win_engine/ai_catch_win_latest.csv")

DIRECTION_TRUST_THRESHOLD = 55.0  # نفس عتبة predict.py — دقة اتجاه تحت كده = ثقة صدفة تقريبًا


def load_universe(n: int | None = None) -> list[str]:
    if not UNIVERSE_CSV.exists():
        raise FileNotFoundError(
            f"{UNIVERSE_CSV} غير موجود — رجاء تحديثه من جهاز عبده عبر "
            f"`python ai_catch_win_engine/volatility_screen.py` ثم نسخ الناتج لـ{UNIVERSE_CSV}."
        )
    df = pd.read_csv(UNIVERSE_CSV)
    tickers = df["ticker"].tolist()
    # Abdo wants stock-only signals, no ETFs — see etf_screen.py docstring for
    # why this can't just be baked into the frozen CSV once and forgotten.
    tickers = filter_out_etfs(tickers)
    # Price cap ($50 max) + liquidity floor (100k avg 20-day volume) — same
    # backstop reasoning as the ETF filter above, see liquidity_screen.py.
    tickers = filter_by_price_and_liquidity(tickers)
    return tickers[:n] if n is not None else tickers


def _reorder_targets_by_ai_goal(entry_exit: dict, current_price: float,
                                 ai_pct_change: float | None) -> dict:
    """
    يفرز المستويات الثلاثة (الناتجة من full_universe_analysis.compute_entry_
    exit_levels — دائمًا "أقرب مقاومة حقيقية للسعر الحالي" افتراضيًا) لمستوى
    واحد مميَّز (`ai_t_price`) هو الأقرب فعليًا لهدف AI (current_price × (1 +
    ai_pct_change/100))، والاتنين الباقيين (`t1_price`/`t2_price`) بترتيبهم
    السعري الطبيعي التصاعدي بينهم (t1 < t2 دايمًا) — بلا اختراع أي مستوى
    جديد، فقط إعادة تسمية/تجميع نفس الثلاثة المستويات الحقيقية اللي رجّعتها
    الدالة المشتركة أصلاً.

    **تسمية الأعمدة (طلب عبده 2026-07-22، بعد نقاش)**: `ai_t_price` (المستوى
    المميَّز حسب قرب هدف AI، لا حسب السعر) + `t1_price`/`t2_price` (الباقيان،
    ترتيبهم سعري تصاعدي عادي فيما بينهم). هذا يفادي مشكلة الاسم القديم
    (`exit_price`/`target2_price`/`target3_price` بترتيب T1/T2/T3 يوحي
    بتسلسل سعري ثابت، لكن كان بيتغيّر فعليًا حسب قرب هدف AI — راجع اكتشاف
    عبده: RGTU طلعت T1=11.64 أعلى من T2=10.71، مربك لقارئ خارجي). الاسم
    الجديد يفصل بوضوح: مستوى واحد "بالأولوية" (ai_t)، ومستويان "بالترتيب
    السعري العادي" (t1/t2) — لا تناقض محتمل بين الاسم والقيمة.

    **لماذا هنا لا داخل compute_entry_exit_levels نفسها**: تلك الدالة مشتركة
    مع الفحص اليومي الكامل (full_universe_analysis.py) وفيها تعديلات أخرى غير
    مدفوعة لسه من جلسات سابقة — إضافة معامل جديد لها مباشرة خطر (احتمال
    التعارض مع ذلك الشغل). هذا الملف مستقل تمامًا، فآمن تمامًا.
    """
    if ai_pct_change is None:
        return entry_exit

    targets = [entry_exit.get("exit_price"), entry_exit.get("target2_price"), entry_exit.get("target3_price")]
    real_levels = [t for t in targets if t is not None]
    if not real_levels:
        return entry_exit

    ai_target_price = current_price * (1 + ai_pct_change / 100)
    ai_t = min(real_levels, key=lambda level: abs(level - ai_target_price))
    remaining = sorted(level for level in real_levels if level != ai_t)

    result = dict(entry_exit)
    result.pop("exit_price", None)
    result.pop("target2_price", None)
    result.pop("target3_price", None)
    result.pop("exit_basis", None)
    result.pop("target2_basis", None)
    result.pop("target3_basis", None)

    result["ai_t_price"] = ai_t
    result["ai_t_basis"] = f"nearest real resistance to AI target ({ai_pct_change:+.1f}%)"
    result["t1_price"] = remaining[0] if len(remaining) >= 1 else None
    result["t1_basis"] = "nearest remaining real resistance level" if len(remaining) >= 1 else None
    result["t2_price"] = remaining[1] if len(remaining) >= 2 else None
    result["t2_basis"] = "second remaining real resistance level" if len(remaining) >= 2 else None
    return result


def build_trade_plan(ticker: str, ai_pct_change: float | None) -> dict | None:
    """
    يبني خطة صفقة حقيقية (دخول/وقف/T1/T2/T3[+]) لسهم واحد، موجَّهة بـ
    ai_pct_change (تنبؤ AI Catch & Win، بعد المعايرة) لو متاح — راجع docstring
    الملف. يرجّع None لو تعذّر جلب بيانات كافية لهذا السهم.
    """
    try:
        hist = fetch_ohlc(ticker, rng="1y", interval="1d")
    except Exception as exc:
        print(f"{ticker}: تعذّر جلب البيانات لبناء خطة الصفقة ({exc})")
        return None
    if hist is None or len(hist) < 60:
        return None

    current_price = float(hist["Close"].iloc[-1])
    high, low, close = hist["High"], hist["Low"], hist["Close"]

    pivot = compute_pivot_points(
        float(high.iloc[-2]), float(low.iloc[-2]), float(close.iloc[-2]),
    ).__dict__ if len(hist) >= 2 else None

    fib = compute_fibonacci_levels(high, low)
    fib_dict = {"levels": fib.levels} if fib else None

    entry_exit = compute_entry_exit_levels(
        current_price, pivot, None, target_gain_pct=10.0, median_days_to_hit=None,
        fibonacci_levels=fib_dict, support_resistance_method="pivot",
    )
    entry_exit = _reorder_targets_by_ai_goal(entry_exit, current_price, ai_pct_change)

    # لو هدف AI تخطّى حتى أبعد مستوى عادي (أو مفيش مستويات أصلاً)، نجرّب مستوى
    # ممتد (فيبوناتشي extension / مربع9 دورات إضافية) كمستوى إضافي — معلَّم
    # صراحة، لا يُعرَض كأنه بنفس ثقة ai_t/t1/t2 العادية.
    target3_plus_price, target3_plus_basis = None, None
    if ai_pct_change is not None:
        ai_target_price = current_price * (1 + ai_pct_change / 100)
        normal_targets = [t for t in (entry_exit["ai_t_price"], entry_exit["t1_price"],
                                       entry_exit["t2_price"]) if t is not None]
        farthest_normal = max(normal_targets) if normal_targets else current_price
        if ai_target_price > farthest_normal:
            try:
                increment = recommended_price_increment(high, low, close)["recommended_increment"]
            except Exception:
                increment = None
            extended = extended_resistances_above(current_price, high, low, increment)
            if extended:
                target3_plus_price = min(extended, key=lambda level: abs(level - ai_target_price))
                target3_plus_basis = (
                    f"extended level (Fibonacci extension / multi-rotation Square9) beyond normal "
                    f"T1-T3 — needed because AI target ({ai_pct_change:+.1f}%) exceeds all standard "
                    f"resistance levels for this ticker"
                )

    return {
        "ticker": ticker, "current_price": round(current_price, 2),
        "ai_target_pct": round(ai_pct_change, 3) if ai_pct_change is not None else None,
        **entry_exit,
        "target3_plus_price": target3_plus_price, "target3_plus_basis": target3_plus_basis,
    }


def send_telegram_alert(message: str) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("WARNING: TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID not set — skipping Telegram alert.")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({
        "chat_id": chat_id, "text": message, "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            ok = resp.status == 200
            if not ok:
                print(f"WARNING: Telegram send failed with status {resp.status}")
            return ok
    except Exception as exc:
        print(f"WARNING: Telegram send error: {exc}")
        return False


def format_telegram_message(ranked: pd.DataFrame, trade_plans: dict[str, dict], top_n: int = 10) -> str:
    lines = [f"<b>AI Catch & Win — {date.today().isoformat()}</b>", ""]
    shown = 0
    for _, row in ranked.iterrows():
        if shown >= top_n:
            break
        ticker = row["ticker"]
        calib = row.get("h1_calibrated_pct_change")
        dir_acc = row.get("h1_direction_accuracy")
        if pd.isna(calib):
            continue  # لا معايرة موثوقة — لا تظهر في التنبيه المختصر
        plan = trade_plans.get(ticker)
        lines.append(f"<b>{ticker}</b> — AI: {calib:+.1f}% (ثقة اتجاه {dir_acc:.0f}%)")
        if plan:
            lines.append(f"  دخول: ${plan['entry_price']} | وقف: ${plan['stop_loss_price']}")
            # ai_t هو الأقرب فعليًا لهدف AI بالبناء (راجع _reorder_targets_by_ai_goal)
            targets = [f"AI T=${plan['ai_t_price']}"]
            if plan.get("t1_price") is not None:
                targets.append(f"T1=${plan['t1_price']}")
            if plan.get("t2_price") is not None:
                targets.append(f"T2=${plan['t2_price']}")
            if plan.get("target3_plus_price") is not None:
                targets.append(f"Extended=${plan['target3_plus_price']}")
            lines.append("  " + " | ".join(targets))
        lines.append("")
        shown += 1
    if shown == 0:
        lines.append("لا توجد إشارات بثقة كافية اليوم.")
    lines.append("⚠️ للمراجعة اليدوية فقط — لا تنفيذ آلي لأي صفقة.")
    return "\n".join(lines)


def main(n_tickers: int | None = None, target_kind: str = "high", send_alert: bool = True) -> pd.DataFrame:
    tickers = load_universe(n_tickers)
    print(f"AI Catch & Win: {len(tickers)} سهم من القائمة المجمّدة.")

    ranked = rank_predictions(tickers, target_kind=target_kind)
    if ranked.empty:
        print("لا توجد تنبؤات صالحة اليوم.")
        return ranked

    trade_plans: dict[str, dict] = {}
    for _, row in ranked.iterrows():
        ticker = row["ticker"]
        ai_pct = row.get("h1_calibrated_pct_change")
        ai_pct = float(ai_pct) if pd.notna(ai_pct) else None
        plan = build_trade_plan(ticker, ai_pct)
        if plan is not None:
            trade_plans[ticker] = plan

    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    # current_price يتكرر في الاتنين (ranked من جدول ميزات predict.py، وممكن
    # يبقى أقدم من fetch_ohlc اللحظي في build_trade_plan) — نسخة خطة الصفقة
    # هي الأحدث (جلب حي وقت بناء الخطة)، فتفوز بلا لاحقة _plan مربكة.
    ranked_no_price = ranked.drop(columns=["current_price"])
    merged = ranked_no_price.merge(pd.DataFrame(trade_plans.values()), on="ticker", how="left")
    merged.to_csv(OUTPUT_CSV, index=False)
    OUTPUT_JSON.write_text(merged.to_json(orient="records", indent=2, force_ascii=False), encoding="utf-8")
    print(f"النتيجة الكاملة (تنبؤات + خطط صفقات) -> {OUTPUT_CSV.resolve()} و {OUTPUT_JSON.resolve()}")

    if send_alert:
        message = format_telegram_message(ranked, trade_plans)
        send_telegram_alert(message)

    # دورة التتبّع الكاملة (طلب عبده: أداة تتعلم من تحقق الأهداف مع الوقت) —
    # راجع prediction_tracker.py. لا تفشل التشغيلة كلها لو فشلت هذه الخطوة
    # (شبكة/بيانات ناقصة) — التنبؤ الأساسي أهم من التتبّع.
    try:
        score_due_predictions()
        recompute_live_calibration()
        check_retrain_warning()
    except FileNotFoundError as exc:
        print(f"تتبّع التوقعات: {exc}")

    return merged


if __name__ == "__main__":
    n_arg = int(sys.argv[1]) if len(sys.argv) > 1 else None
    main(n_tickers=n_arg)
