"""
ai_catch_win_engine/predict.py — أداة الاستخدام النهائية (طلب عبده 2026-07-18):
"عند استخدامه سأطلب منه ترتيب النتائج من الأعلى ربحية متوقعة مع عرض نسبة
الدقة... نفس الأمر مع h5, h10, h20... عمود للربح وآخر للدقة التاريخية".

لكل سهم، يبني صفًا واحدًا يحمل تنبؤ %التغيّر المتوقَّع + الدقة التاريخية
**لكل أفق من الأربعة** (h1/h5/h10/h20) في أعمدة منفصلة — لا صف منفصل لكل
أفق، حتى تُقارَن كل الآفاق لنفس السهم في نظرة واحدة.

**تصحيح جوهري 2026-07-18 (طلب عبده: "نموذج يوصل لنتائج صادقة... توقع
لنسبة الربح")**: اكتُشف أن %التغيّر الخام اللي بيتوقعه النموذج **مضغوط**
دائمًا — انحراف معياري التوقعات أقل بكثير من انحراف معياري الفعلي (تحقّق
مباشر على ATCX: توقعات std=5.6% مقابل فعلي std=10.6%، أي النموذج يلتقط
نص التذبذب الحقيقي فقط). استخدام الرقم الخام كـ"حجم ربح متوقَّع" كان
سيقلّل هدف الربح الحقيقي بشكل منهجي. **الحل**: `magnitude_calibration_factor`
(من train_model.py) — نسبة متوسط |الفعلي| ÷ متوسط |المتوقَّع| على test set،
محسوبة فقط من الصفوف اللي كان النموذج فيها **محقًا اتجاهيًا** (نثق بحجم
تنبؤ اتجاهه صح فقط). الترتيب والعرض الافتراضي الآن حسب **الربح المعايَر**
(`h{N}_calibrated_pct_change` = الخام × المعامل)، لا الخام مباشرة — والعمود
الخام يبقى معروضًا بجانبه للشفافية، لا يُخفى.

**بوابة الثقة**: لو `direction_accuracy` قريبة من الصدفة (<55%)، المعايرة نفسها
غير موثوقة (حجم موثوق لاتجاه عشوائي بلا قيمة) — المعامل ما يُطبَّقش وقتها،
ويظهر تحذير صريح بدل رقم مضلِّل.

**المعايرة الحية (2026-07-19، إكمال طلب عبده "أداة تتعلم من تحقق الأهداف
مع الوقت")**: `prediction_tracker.recompute_live_calibration()` تحسب معامل
معايرة بديل من التوقعات المُقيَّمة الفعلية المتراكمة (لا test split وقت
التدريب فقط) — أدق مع الوقت لأنه مبني على أداء حقيقي حي. لو متاح لتركيبة
(سهم × هدف × أفق) معينة وعيّنته كافية (نفس MIN_LIVE_SAMPLES_FOR_RECALIBRATION
بتاع prediction_tracker.py)، يُفضَّل على معامل التدريب الثابت؛ غير كده،
معامل التدريب يبقى fallback كما كان.

**تنبيه صريح غير قابل للحذف (طلب المشروع الثابت: preflight-checklist قبل
أي تنفيذ حقيقي)**: هذا الملف **لا ينفّذ أي أمر شراء/بيع** — فقط يرتّب
تنبؤات رقمية للمراجعة اليدوية، بنفس فلسفة full_universe_analysis.py و
suggest_execution.py في بقية المشروع.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # مطلق، لا "." هش — راجع cloud_build_feature_tables.py

from ai_catch_win_engine.feature_table import OUTPUT_ROOT, PREDICTION_HORIZONS_DAYS, build_feature_table
from ai_catch_win_engine.prediction_tracker import MIN_LIVE_SAMPLES_FOR_RECALIBRATION, log_predictions
from ai_catch_win_engine.train_model import NON_FEATURE_COLUMNS

TRAINING_RESULTS_PATH = Path("../runs/ai_catch_win_engine/model_training_results_daily.csv")
LIVE_CALIBRATION_PATH = Path("../runs/ai_catch_win_engine/live_calibration.csv")

RANK_BY_HORIZON = 1  # الأفق المُستخدَم للترتيب النهائي (h1 — الأثبت أداءً في كل التجارب)
DIRECTION_TRUST_THRESHOLD = 55.0  # تحت ده، دقة الاتجاه قريبة جدًا من الصدفة (50%) — لا تُطبَّق المعايرة

# نفس شبكة hyperparameters المُختبَرة في train_model.py — طلب عبده: كل
# تركيبة (سهم × هدف) تختار أفضلها بنفسها (لا قيمة ثابتة واحدة للجميع).
PARAM_GRID = [
    {"n_estimators": 400, "max_depth": 3, "learning_rate": 0.03},
    {"n_estimators": 400, "max_depth": 4, "learning_rate": 0.03},
    {"n_estimators": 600, "max_depth": 3, "learning_rate": 0.02},
    {"n_estimators": 300, "max_depth": 2, "learning_rate": 0.05},
]


def _load_historical_accuracy() -> pd.DataFrame:
    """أفضل دقة تاريخية (across كل نوافذ التدريب) لكل (ticker, target) — من آخر تشغيلة train_model.py.

    يعرض هامشين معًا (طلب عبده 2026-07-18): ±2% للأسهم الهادئة نسبيًا،
    و±5% للأسهم شديدة التقلب — تحقق فعلي أظهر أن ±2% غير عادل لهذه الفئة
    (تقلبها الطبيعي اليومي يتجاوز الهامش بلا علاقة بجودة التنبؤ)، بينما ±5%
    يعطيها دقة أعلى بثبات. **direction_accuracy (القسم 9.18) يُعرَض دائمًا
    بجانبهما** — دقة قيمة عالية بلا دقة اتجاه مقابلة (قريبة من 50%) تعني أن
    النموذج "يخمّن" الإشارة +/- عشوائيًا رغم شكل دقيق ظاهريًا."""
    if not TRAINING_RESULTS_PATH.exists():
        return pd.DataFrame(columns=["ticker", "target", "accuracy_within_2pct", "accuracy_within_5pct",
                                      "direction_accuracy", "magnitude_calibration_factor", "overfit_ratio"])
    df = pd.read_csv(TRAINING_RESULTS_PATH)
    df = df[(df["skipped"] == False) & (df["overfit_ratio"] <= 3)]
    return df.loc[df.groupby(["ticker", "target"])["accuracy_within_2pct"].idxmax()]


def _load_live_calibration() -> pd.DataFrame:
    """معامل المعايرة الحي (راجع docstring الملف) لكل (ticker, target_kind,
    horizon_days) بعيّنة كافية — فارغ لو الملف غير موجود بعد أو لا صفوف
    عدّت عتبة العيّنة الدنيا (prediction_tracker.py لسه ما جمّعش تقييمات
    كافية، طبيعي لميزة جديدة)."""
    if not LIVE_CALIBRATION_PATH.exists():
        return pd.DataFrame(columns=["ticker", "target_kind", "horizon_days",
                                      "live_direction_accuracy", "live_magnitude_calibration_factor"])
    try:
        df = pd.read_csv(LIVE_CALIBRATION_PATH)
    except pd.errors.EmptyDataError:
        return pd.DataFrame(columns=["ticker", "target_kind", "horizon_days",
                                      "live_direction_accuracy", "live_magnitude_calibration_factor"])
    return df[df["n_correct_direction_live"] >= MIN_LIVE_SAMPLES_FOR_RECALIBRATION] if not df.empty else df


def _fit_best_model(X: pd.DataFrame, y: pd.Series) -> xgb.XGBRegressor:
    """يختار أفضل تركيبة hyperparameters عبر eval_set فرعي، ثم يعيد التدريب على كل X."""
    eval_split = max(int(len(X) * 0.9), len(X) - 200)
    X_fit, X_eval = X.iloc[:eval_split], X.iloc[eval_split:]
    y_fit, y_eval = y.iloc[:eval_split], y.iloc[eval_split:]

    best_model, best_rmse = None, float("inf")
    for params in PARAM_GRID:
        candidate = xgb.XGBRegressor(
            subsample=0.8, colsample_bytree=0.8, random_state=42,
            early_stopping_rounds=20, eval_metric="rmse", **params,
        )
        if len(X_eval) >= 20:
            candidate.fit(X_fit, y_fit, eval_set=[(X_eval, y_eval)], verbose=False)
            rmse = float(np.sqrt(np.mean((candidate.predict(X_eval) - y_eval) ** 2)))
        else:
            candidate.set_params(early_stopping_rounds=None)
            candidate.fit(X, y)
            rmse = 0.0
        if rmse < best_rmse:
            best_model, best_rmse = candidate, rmse

    if len(X_eval) >= 20 and best_model.best_iteration is not None:
        final_params = best_model.get_params()
        final_params["n_estimators"] = best_model.best_iteration + 1
        final_params.pop("early_stopping_rounds", None)
        final_model = xgb.XGBRegressor(**final_params)
        final_model.fit(X, y)
        return final_model
    return best_model


def _load_feature_table(ticker: str) -> pd.DataFrame | None:
    """
    يفضّل جدول ميزات مبني مسبقًا (runs/ai_catch_win_engine/feature_tables/{ticker}.csv
    — سواء بناه feature_table.py محليًا من الأرشيف المحلي، أو
    cloud_build_feature_tables.py سحابيًا من yfinance مباشرة، راجع ذلك الملف)
    بدل إعادة البناء الحي هنا. **لماذا**: build_feature_table الأصلية تعتمد
    على build_local_ticker_index/load_local_history (الأرشيف المحلي بتاع عبده
    فقط) — على GitHub Actions (لا أرشيف محلي)، كل استدعاء لها كان يفشل بصمت
    بـValueError لكل الـ200 سهم (اكتُشف فعليًا 2026-07-18، أول تشغيلة سحابية
    كاملة: كل الأسهم "تخطّي" رغم نجاح خطوة بناء الجداول السحابية قبلها مباشرة
    في نفس الورك-فلو). يرجع None لو لا الجدول الجاهز ولا إعادة البناء الحي
    (المسار المحلي فقط) نجحا.
    """
    cached_path = OUTPUT_ROOT / f"{ticker}.csv"
    if cached_path.exists() and cached_path.stat().st_size > 0:
        try:
            df = pd.read_csv(cached_path)
            if not df.empty:
                return df
        except pd.errors.EmptyDataError:
            pass  # ملف تالف/فارغ (مثلاً fetch فشل نص طريقه) — كمّل لإعادة البناء الحي تحت
    try:
        return build_feature_table(ticker)
    except ValueError:
        return None


def predict_ticker_all_horizons(ticker: str, accuracy_table: pd.DataFrame,
                                 target_kind: str = "high",
                                 live_calibration: pd.DataFrame | None = None) -> dict | None:
    """
    يبني جدول ميزات كامل لـ`ticker` مرة واحدة، ثم يدرّب نموذجًا منفصلاً لكل
    أفق (h1/h5/h10/h20) على نفس target_kind (high/low/close)، ويرجّع صفًا
    واحدًا يحمل %التغيّر + الدقة التاريخية لكل أفق في أعمدة منفصلة.
    """
    df = _load_feature_table(ticker)
    if df is None:
        return None

    excluded = NON_FEATURE_COLUMNS | {f"target_{kind}_h{h}" for h in PREDICTION_HORIZONS_DAYS
                                       for kind in ("high", "low", "close")}
    # XGBoost (نسخة حديثة) بيرفض أعمدة نصية بدون enable_categorical=True —
    # استبعاد أي عمود object/string من الميزات (مش تعديل feature_table.py
    # نفسها، فقط مدخل predict.py) بدل تحديد اسمين بعينهما.
    non_numeric_cols = set(df.select_dtypes(exclude="number").columns)
    feature_cols = [c for c in df.columns if c not in excluded and c not in non_numeric_cols]
    latest_row = df.iloc[[-1]]
    current_price = float(latest_row["close"].iloc[0])

    # سيولة التداول (طلب عبده 2026-07-22: "فيه أسهم الـVolume فيها أقل من
    # 100 ألف وأحيانًا أقل من 10 آلاف — طب لو اشتريته هضمن إزاي خروج في
    # الميعاد؟") — متوسط حجم التداول لآخر 20 يوم (avg_volume_20d) هو مؤشر
    # السيولة الحقيقي (حجم يوم واحد لوحده مضلِّل: قفزة/هبوط حاد ليوم واحد
    # مش دليل سيولة مستمرة) — بيوضّح هل السهم أصلاً بيتداول بكمية كافية
    # للدخول/الخروج بسعر قريب من المستويات المحسوبة بلا انزلاق سعري كبير،
    # قبل ما يوصل لخطة الصفقة خالص. today_volume معروض جنبه للمرجعية فقط.
    volume_ma20 = df["volume"].rolling(20).mean()
    avg_volume_20d = float(volume_ma20.iloc[-1]) if pd.notna(volume_ma20.iloc[-1]) else None
    today_volume = float(latest_row["volume"].iloc[0]) if pd.notna(latest_row["volume"].iloc[0]) else None

    result = {
        "ticker": ticker, "as_of_date": latest_row["date"].iloc[0],
        "current_price": round(current_price, 2),
        "today_volume": int(today_volume) if today_volume is not None else None,
        "avg_volume_20d": int(avg_volume_20d) if avg_volume_20d is not None else None,
    }

    for horizon in PREDICTION_HORIZONS_DAYS:
        target_col = f"target_{target_kind}_h{horizon}"
        known = df.dropna(subset=[target_col])
        if len(known) < 100:
            result[f"h{horizon}_pct_change"] = None
            result[f"h{horizon}_accuracy_within_2pct"] = None
            continue

        model = _fit_best_model(known[feature_cols], known[target_col])
        predicted_pct = float(model.predict(latest_row[feature_cols])[0])
        result[f"h{horizon}_pct_change"] = round(predicted_pct, 3)

        match = accuracy_table[(accuracy_table["ticker"] == ticker) & (accuracy_table["target"] == target_col)]
        result[f"h{horizon}_accuracy_within_2pct"] = (
            round(float(match["accuracy_within_2pct"].iloc[0]), 2) if not match.empty else None
        )
        result[f"h{horizon}_accuracy_within_5pct"] = (
            round(float(match["accuracy_within_5pct"].iloc[0]), 2) if not match.empty else None
        )
        dir_acc = (
            float(match["direction_accuracy"].iloc[0])
            if not match.empty and pd.notna(match["direction_accuracy"].iloc[0]) else None
        )
        result[f"h{horizon}_direction_accuracy"] = round(dir_acc, 2) if dir_acc is not None else None

        # الربح المعايَر (راجع docstring الملف) — يُطبَّق فقط لو الاتجاه موثوق
        # به (فوق DIRECTION_TRUST_THRESHOLD)؛ غير كده، معايرة حجم على اتجاه
        # شبه عشوائي رقم مضلِّل، فيُترَك calibrated_pct_change = None صراحة
        # (لا تقريب صامت لقيمة غير موثوقة).
        # المعامل الحي (لو متاح بعيّنة كافية لنفس التركيبة) يُفضَّل على معامل
        # التدريب الثابت — أدق لأنه مبني على أداء فعلي متراكم، لا test split
        # وقت التدريب فقط. غير كده، معامل التدريب fallback كالمعتاد.
        calib_factor = None
        calib_source = None
        if live_calibration is not None and not live_calibration.empty:
            live_match = live_calibration[
                (live_calibration["ticker"] == ticker)
                & (live_calibration["target_kind"] == target_kind)
                & (live_calibration["horizon_days"] == horizon)
            ]
            if not live_match.empty and pd.notna(live_match["live_magnitude_calibration_factor"].iloc[0]):
                calib_factor = float(live_match["live_magnitude_calibration_factor"].iloc[0])
                calib_source = "live"
        if calib_factor is None and not match.empty and pd.notna(match["magnitude_calibration_factor"].iloc[0]):
            calib_factor = float(match["magnitude_calibration_factor"].iloc[0])
            calib_source = "trained"

        if calib_factor is not None and dir_acc is not None and dir_acc >= DIRECTION_TRUST_THRESHOLD:
            result[f"h{horizon}_calibrated_pct_change"] = round(predicted_pct * calib_factor, 3)
            result[f"h{horizon}_calibration_source"] = calib_source
        else:
            result[f"h{horizon}_calibrated_pct_change"] = None
            result[f"h{horizon}_calibration_source"] = None

    return result


def rank_predictions(tickers: list[str], target_kind: str = "high") -> pd.DataFrame:
    """
    الوظيفة الرئيسية المطلوبة: صف واحد لكل سهم يحمل تنبؤ %التغيّر (خام
    ومعايَر) + الدقة التاريخية لكل أفق (h1/h5/h10/h20)، مرتّب تنازليًا حسب
    **الربح المعايَر** لأفق h1 (RANK_BY_HORIZON) — أسهم بلا معايرة موثوقة
    (اتجاه قريب من الصدفة) تُرتَّب في الآخر، لا تُستبعَد، حتى تبقى مرئية
    للمراجعة اليدوية مع تحذيرها الصريح.
    """
    accuracy_table = _load_historical_accuracy()
    live_calibration = _load_live_calibration()

    rows = []
    for ticker in tickers:
        result = predict_ticker_all_horizons(ticker, accuracy_table, target_kind, live_calibration)
        if result is None:
            print(f"{ticker}: تخطّي (بيانات غير كافية)")
            continue
        rows.append(result)

        parts = []
        for h in PREDICTION_HORIZONS_DAYS:
            pct = result[f"h{h}_pct_change"]
            calib_pct = result[f"h{h}_calibrated_pct_change"]
            acc2, acc5 = result[f"h{h}_accuracy_within_2pct"], result[f"h{h}_accuracy_within_5pct"]
            dir_acc = result[f"h{h}_direction_accuracy"]
            if pct is None:
                parts.append(f"h{h}=—")
            elif calib_pct is None:
                parts.append(f"h{h}: خام={pct:+.2f}% [تحذير: اتجاه~صدفة {dir_acc}%]، لا معايرة موثوقة")
            else:
                src = result[f"h{h}_calibration_source"]
                src_tag = "حي" if src == "live" else "تدريب"
                parts.append(f"h{h}: معايَر({src_tag})={calib_pct:+.2f}% (خام={pct:+.2f}%، ±2%={acc2}% / "
                              f"±5%={acc5}% / اتجاه={dir_acc}%)")
        print(f"{ticker}: " + " | ".join(parts))

    if not rows:
        return pd.DataFrame()

    # تسجيل تلقائي (طلب عبده: "أداة تتعلم من تحقق الأهداف مع الوقت") — كل
    # تشغيلة predict.py تسجّل توقعاتها في prediction_log.csv تلقائيًا، بلا
    # خطوة يدوية إضافية. راجع prediction_tracker.py لدورة score/recalibrate/
    # check_retrain الكاملة اللي بتُشغَّل لاحقًا (يدويًا، على فترات).
    log_predictions(rows, target_kind)

    out = pd.DataFrame(rows)
    rank_col = f"h{RANK_BY_HORIZON}_calibrated_pct_change"
    # الأسهم بلا معايرة موثوقة (None) تُرتَّب آخر القائمة، لا تُستبعَد
    return out.sort_values(rank_col, ascending=False, na_position="last").reset_index(drop=True)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        tickers_arg = sys.argv[1:]
    else:
        # هدف عبده 2026-07-18: التركيز على الأسهم شديدة التقلب (راجع
        # volatility_screen.py) بدل عيّنة الـ10 أسهم الهادئة القديمة.
        from ai_catch_win_engine.volatility_screen import top_volatile_tickers
        tickers_arg = top_volatile_tickers(20)
    ranked = rank_predictions(tickers_arg)
    print("\n=== الترتيب النهائي (من الأعلى ربحية معايَرة، أفق h1) ===")
    print(ranked.to_string(index=False))

    out_path = Path("../runs/ai_catch_win_engine/latest_predictions.csv")
    ranked.to_csv(out_path, index=False)
    print(f"\nWrote ranked predictions to {out_path.resolve()}")
