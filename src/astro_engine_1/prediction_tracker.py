"""
astro_engine_1/prediction_tracker.py — الأداة اللي بتخلّي predict.py يتعلّم من
النتائج الفعلية بمرور الوقت (طلب عبده 2026-07-18: "ابني أداة تتعلم من تحقق
الأهداف مع الوقت في المستقبل وتحسن التوقعات").

**3 طبقات، كل واحدة بتكلفتها وتكرارها المناسب (قرار مبني على نقاش مباشر مع
عبده — إعادة تدريب XGBoost بالكامل كل مرة مكلفة جدًا (~25 دقيقة لـ200 سهم)
لعائد صغير، بينما تحديث معامل المعايرة رخيص وفوري)**:

1. **log_predictions()** — تسجّل كل توقع صادر من predict.py (سهم/تاريخ/أفق/
   خام/معايَر) في سجل دائم، بمفتاح فريد (ticker, as_of_date, horizon,
   target_kind) — إعادة تشغيل predict.py لنفس اليوم ما بتكرّرش الصف.
2. **score_due_predictions()** — لأي توقع عدّى تاريخ استحقاقه (as_of_date +
   أيام الأفق)، تجيب السعر الفعلي (yahoo_fetch، نفس المصدر المستخدم في
   lab_forecast_tracker.py لأن yfinance المكتبة معطوبة محليًا)، تحسب: هل
   الاتجاه صح؟ نسبة الخطأ؟ وتضيفها لسجل التقييم.
3. **recompute_live_calibration()** — تعيد حساب magnitude_calibration_factor
   من **التوقعات المُقيَّمة الفعلية المتراكمة** (لا فقط test split وقت
   التدريب) — تحديث رخيص وسريع، بديل أول عن إعادة التدريب.
4. **check_retrain_warning()** — تقارن دقة الاتجاه **الحية** (من التوقعات
   المُقيَّمة) بدقة الاتجاه **وقت التدريب** (من model_training_results_daily.csv)
   لكل (ticker, target) — لو انحراف كبير (تدهور حقيقي)، تُصدر تحذير صريح
   "أعِد التدريب" بدل تشغيله أعمى على جدول زمني. هذا خط الدفاع الثاني الأغلى،
   يتفعّل فقط عند إشارة حقيقية.

اللوجات: runs/astro_engine_1/prediction_log.csv (توقعات) +
runs/astro_engine_1/prediction_scores.csv (مقيّمة، بعد score_due_predictions).
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, ".")

from astro_engine_1.feature_table import PREDICTION_HORIZONS_DAYS
from yahoo_fetch import fetch_ohlc

LOG_ROOT = Path("../runs/astro_engine_1")
PREDICTION_LOG_CSV = LOG_ROOT / "prediction_log.csv"
PREDICTION_SCORES_CSV = LOG_ROOT / "prediction_scores.csv"
TRAINING_RESULTS_PATH = LOG_ROOT / "model_training_results_daily.csv"

MIN_LIVE_SAMPLES_FOR_RECALIBRATION = 20  # نفس عتبة train_model.py — لا نثق بمتوسط عيّنة صغيرة
MAX_CALIBRATION_FACTOR = 20.0            # نفس سقف train_model.py — حماية من قسمة متفجرة
DIRECTION_DRIFT_WARNING_POINTS = 15.0    # فرق نقاط مئوية بين الدقة الحية والتدريبية يستدعي تحذير


def log_predictions(rows: list[dict], target_kind: str) -> None:
    """
    يسجّل صفوف predict.py الخام (نتيجة predict_ticker_all_horizons لكل سهم)
    كتوقعات فردية لكل (ticker × أفق) — صف واحد لكل أفق فعلي (لا الشكل العريض
    المُستخدَم في العرض)، لتسهيل المطابقة لاحقًا بصف واحد فعلي واحد.
    """
    log_rows = []
    for r in rows:
        for h in PREDICTION_HORIZONS_DAYS:
            pct = r.get(f"h{h}_pct_change")
            if pct is None:
                continue
            log_rows.append({
                "ticker": r["ticker"], "as_of_date": r["as_of_date"], "horizon_days": h,
                "target_kind": target_kind, "current_price": r["current_price"],
                "raw_pct_change": pct, "calibrated_pct_change": r.get(f"h{h}_calibrated_pct_change"),
                "direction_accuracy_at_prediction": r.get(f"h{h}_direction_accuracy"),
                "logged_at": pd.Timestamp.now().isoformat(timespec="seconds"),
            })

    if not log_rows:
        return
    new = pd.DataFrame(log_rows)
    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    if PREDICTION_LOG_CSV.exists():
        old = pd.read_csv(PREDICTION_LOG_CSV)
        combined = pd.concat([old, new], ignore_index=True)
        combined = combined.drop_duplicates(
            subset=["ticker", "as_of_date", "horizon_days", "target_kind"], keep="last")
    else:
        combined = new
    combined.to_csv(PREDICTION_LOG_CSV, index=False)


def _target_date(as_of_date: str, horizon_days: int) -> date:
    """أيام تداول تقريبية — نفس تقريب lab_forecast_tracker (تقويمية مباشرة،
    كافٍ هنا لأن score_due_predictions أصلاً بتنتظر توفر السعر الفعلي، لا
    تفترض دقة تاريخ التداول الحرفي)."""
    return date.fromisoformat(as_of_date) + timedelta(days=horizon_days)


def score_due_predictions() -> pd.DataFrame:
    """
    لكل توقع مسجَّل عدّى تاريخ استحقاقه (as_of_date + horizon_days أيام)،
    تجيب السعر الفعلي وتحسب: هل الاتجاه صح؟ (sign(المتوقع) == sign(الفعلي
    نسبةً لـcurrent_price وقت التوقع)، ونسبة الخطأ للخام والمعايَر معًا.
    توقعات لسه ماجاش وقتها بتتخطّى (لا تُقيَّم قبل الأوان).
    """
    if not PREDICTION_LOG_CSV.exists():
        raise FileNotFoundError("لا يوجد سجل توقعات بعد — شغّل predict.py أولاً (بيسجّل تلقائيًا).")

    log = pd.read_csv(PREDICTION_LOG_CSV)
    already_scored = set()
    if PREDICTION_SCORES_CSV.exists():
        prior = pd.read_csv(PREDICTION_SCORES_CSV)
        already_scored = set(zip(prior["ticker"], prior["as_of_date"], prior["horizon_days"], prior["target_kind"]))

    today = date.today()
    actuals_cache: dict[str, pd.DataFrame] = {}
    new_scores = []

    for _, p in log.iterrows():
        key = (p["ticker"], p["as_of_date"], int(p["horizon_days"]), p["target_kind"])
        if key in already_scored:
            continue
        due = _target_date(p["as_of_date"], int(p["horizon_days"]))
        if due > today:
            continue  # لسه ماجاش وقته

        if p["ticker"] not in actuals_cache:
            try:
                actuals_cache[p["ticker"]] = fetch_ohlc(p["ticker"], rng="3mo", interval="1d")
            except Exception as exc:
                print(f"{p['ticker']}: تعذّر جلب السعر الفعلي ({exc}) — تخطّي هذا التقييم للآن")
                actuals_cache[p["ticker"]] = None
                continue
        actual_df = actuals_cache[p["ticker"]]
        if actual_df is None or actual_df.empty:
            continue

        # أقرب يوم تداول فعلي متاح عند/بعد تاريخ الاستحقاق مباشرة (لا قبل)
        available = actual_df[actual_df.index.date >= due]
        if available.empty:
            continue  # لسه الداتا الفعلية ما وصلتش لهذا التاريخ

        col = {"high": "High", "low": "Low", "close": "Close"}[p["target_kind"]]
        actual_price = float(available[col].iloc[0])
        actual_pct_change = (actual_price / p["current_price"] - 1) * 100

        raw_pred = p["raw_pct_change"]
        calib_pred = p["calibrated_pct_change"]
        direction_hit = bool(np.sign(raw_pred) == np.sign(actual_pct_change)) if actual_pct_change != 0 else None

        new_scores.append({
            "ticker": p["ticker"], "as_of_date": p["as_of_date"], "horizon_days": int(p["horizon_days"]),
            "target_kind": p["target_kind"], "current_price": p["current_price"],
            "raw_pct_change": raw_pred, "calibrated_pct_change": calib_pred,
            "actual_pct_change": round(actual_pct_change, 4), "direction_hit": direction_hit,
            "raw_abs_error_pct": round(abs(raw_pred - actual_pct_change), 4),
            "calibrated_abs_error_pct": (
                round(abs(calib_pred - actual_pct_change), 4) if pd.notna(calib_pred) else None
            ),
            "scored_at": pd.Timestamp.now().isoformat(timespec="seconds"),
        })

    if not new_scores:
        print("لا توجد توقعات مستحقة جديدة للتقييم الآن.")
        return pd.read_csv(PREDICTION_SCORES_CSV) if PREDICTION_SCORES_CSV.exists() else pd.DataFrame()

    new_df = pd.DataFrame(new_scores)
    if PREDICTION_SCORES_CSV.exists():
        combined = pd.concat([pd.read_csv(PREDICTION_SCORES_CSV), new_df], ignore_index=True)
    else:
        combined = new_df
    combined.to_csv(PREDICTION_SCORES_CSV, index=False)
    print(f"تم تقييم {len(new_df)} توقّع جديد مستحق. الإجمالي المُقيَّم: {len(combined)}")
    return combined


def recompute_live_calibration(min_samples: int = MIN_LIVE_SAMPLES_FOR_RECALIBRATION) -> pd.DataFrame:
    """
    الطبقة الثانية (رخيصة وسريعة): تعيد حساب معامل المعايرة من التوقعات
    **المُقيَّمة فعليًا** (لا test split وقت التدريب فقط) لكل (ticker,
    target_kind, horizon_days) — نفس منطق train_model.py بالضبط (متوسط
    |الفعلي| ÷ متوسط |المتوقَّع|، على الصفوف اللي كان الاتجاه فيها صح فقط،
    بنفس حراسة العيّنة الصغيرة والسقف الأقصى).
    """
    if not PREDICTION_SCORES_CSV.exists():
        raise FileNotFoundError("لا يوجد سجل تقييم بعد — شغّل score_due_predictions أولاً.")

    scored = pd.read_csv(PREDICTION_SCORES_CSV)
    scored = scored[scored["direction_hit"].notna()]

    rows = []
    for (ticker, target_kind, horizon), g in scored.groupby(["ticker", "target_kind", "horizon_days"]):
        correct = g[g["direction_hit"] == True]
        if len(correct) < min_samples:
            continue
        actual_abs = correct["actual_pct_change"].abs().mean()
        predicted_abs = correct["raw_pct_change"].abs().mean()
        if predicted_abs <= 0:
            continue
        factor = actual_abs / predicted_abs
        if factor > MAX_CALIBRATION_FACTOR:
            continue  # نفس حراسة train_model.py — رقم متفجّر رياضيًا، لا يُوثَق به

        rows.append({
            "ticker": ticker, "target_kind": target_kind, "horizon_days": horizon,
            "n_correct_direction_live": len(correct), "n_total_live": len(g),
            "live_direction_accuracy": round((g["direction_hit"] == True).mean() * 100, 2),
            "live_magnitude_calibration_factor": round(factor, 4),
            "recomputed_at": pd.Timestamp.now().isoformat(timespec="seconds"),
        })

    live_calib = pd.DataFrame(rows)
    out_path = LOG_ROOT / "live_calibration.csv"
    live_calib.to_csv(out_path, index=False)
    print(f"أُعيد حساب معامل المعايرة الحي لـ{len(live_calib)} تركيبة (سهم×هدف×أفق) -> {out_path.resolve()}")
    return live_calib


def check_retrain_warning(drift_threshold: float = DIRECTION_DRIFT_WARNING_POINTS) -> pd.DataFrame:
    """
    الطبقة الثالثة (الأغلى، الأندر تفعيلاً): تقارن دقة الاتجاه **الحية**
    (من التوقعات المُقيَّمة فعليًا) بدقة الاتجاه **وقت التدريب** (من
    model_training_results_daily.csv) — انحراف كبير (drift_threshold نقطة
    مئوية أو أكتر، تدهورًا لا تحسّنًا) يعني الموديل على الأرجح عفا عليه الزمن
    لهذا السهم/الهدف تحديدًا، ويستحق إعادة تدريب فعلية — لا مجرد تحديث معايرة.

    **لا تُشغَّل إعادة التدريب تلقائيًا هنا** (قرار متعمد — إعادة التدريب
    مكلفة، والقرار يستحق مراجعة بشرية قبل تنفيذه، بنفس فلسفة preflight
    الثابتة بالمشروع لأي عملية مكلفة/لها أثر).
    """
    if not PREDICTION_SCORES_CSV.exists():
        raise FileNotFoundError("لا يوجد سجل تقييم بعد — شغّل score_due_predictions أولاً.")
    if not TRAINING_RESULTS_PATH.exists():
        raise FileNotFoundError("لا يوجد سجل تدريب (model_training_results_daily.csv) للمقارنة.")

    scored = pd.read_csv(PREDICTION_SCORES_CSV)
    scored = scored[scored["direction_hit"].notna()]
    training = pd.read_csv(TRAINING_RESULTS_PATH)
    training = training[training["skipped"] == False]

    warnings = []
    for (ticker, target_kind, horizon), g in scored.groupby(["ticker", "target_kind", "horizon_days"]):
        if len(g) < MIN_LIVE_SAMPLES_FOR_RECALIBRATION:
            continue  # عيّنة حية صغيرة جدًا — لا حكم موثوق بعد
        live_acc = (g["direction_hit"] == True).mean() * 100

        target_col = f"target_{target_kind}_h{horizon}"
        train_match = training[(training["ticker"] == ticker) & (training["target"] == target_col)]
        if train_match.empty:
            continue
        trained_acc = train_match["direction_accuracy"].max()  # أفضل نافذة تدريب لنفس التركيبة
        if pd.isna(trained_acc):
            continue

        drift = trained_acc - live_acc
        if drift >= drift_threshold:
            warnings.append({
                "ticker": ticker, "target_kind": target_kind, "horizon_days": horizon,
                "trained_direction_accuracy": round(float(trained_acc), 2),
                "live_direction_accuracy": round(float(live_acc), 2),
                "drift_points": round(float(drift), 2), "n_live_samples": len(g),
            })

    warn_df = pd.DataFrame(warnings)
    if warn_df.empty:
        print("لا توجد تركيبة (سهم×هدف×أفق) بانحراف دقة اتجاه كبير — لا حاجة لإعادة تدريب حاليًا.")
    else:
        print(f"تحذير: {len(warn_df)} تركيبة أداؤها الحي أضعف من التدريب بـ{drift_threshold}+ نقطة مئوية "
              f"— مرشّحة لإعادة تدريب (مراجعة يدوية، لا تنفيذ تلقائي):")
        print(warn_df.sort_values("drift_points", ascending=False).to_string(index=False))
    return warn_df


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "score"
    if cmd == "score":
        score_due_predictions()
    elif cmd == "recalibrate":
        recompute_live_calibration()
    elif cmd == "check_retrain":
        check_retrain_warning()
    elif cmd == "full_cycle":
        score_due_predictions()
        recompute_live_calibration()
        check_retrain_warning()
    else:
        raise SystemExit("الأوامر: score | recalibrate | check_retrain | full_cycle")
