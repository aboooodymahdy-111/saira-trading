"""
ai_catch_win_engine/train_model.py — تدريب نموذج XGBoost على جداول الميزات
(feature_table.py، بلا فلك بعد القسم 9.18 — راجع docstring ذلك الملف)،
بهدف عبده الصريح: تنبؤ رقمي مباشر بسعر الغد (High/Low/Close)، لا تصنيف
صعود/هبوط فقط — لكن **دقة الاتجاه تُقاس وتُعرَض دائمًا كمقياس مستقل**
(راجع `direction_accuracy` تحت).

**قرار "ابدأ بسيط" (Roadmap)**: XGBoost regressor، لا شبكة عصبية عميقة.

**تقسيم زمني صارم (لا عشوائي)**: بما أن البيانات سلسلة زمنية، الخلط
العشوائي (train_test_split العادي) يسرّب معلومات من المستقبل للماضي
(leakage) ويعطي أداءً مضللاً على test. بدلاً من ذلك: كل سهم يُقسَّم زمنيًا
(أول 80% تدريب، آخر 20% اختبار خارج العيّنة) — نفس فلسفة "backtest على بيانات
لم يرها النموذج" المتبعة في باقي المشروع (`backtest.py`).

**رصد overfitting (طلب عبده الصريح: "أو لحد قبل ال overfitting لو بيحصل
هنا")**: يُطبع RMSE على كل من train وtest معًا — فجوة كبيرة بينهما
(train منخفض جدًا، test مرتفع) = overfitting واضح، يستدعي التوقف عن زيادة
تعقيد النموذج (n_estimators/max_depth) بدل الاستمرار الأعمى.

**دقة الاتجاه (direction_accuracy، أُضيفت 2026-07-18 — القسم 9.18)**:
اكتشاف حاسم في التجربة السابقة على عيّنة 20 سهمًا: الهدف الموقَّع (%change)
يتضمن الاتجاه أصلاً، لكن `accuracy_within_Npct` وحدها **تُضلِّل جزئيًا** —
close عند أي أفق أعطى دقة قيمة ظاهرية معقولة (75%+) بينما دقة الاتجاه
(sign(توقّع) == sign(فعلي)) كانت ~50%، أي بمستوى رمي العملة تمامًا (لأن
close يتحرك غالبًا بمدى ضيق حول الصفر، فتوقّع قريب من 0% يمر بسهولة عبر
هامش ±2/5% حتى لو كانت إشارة +/- عشوائية). **لذلك: أي تحسين مستقبلي للنموذج
يجب أن يُقاس بكلا المقياسين معًا** (قيمة + اتجاه)، لا قيمة فقط — تحسّن ظاهري
في accuracy_within_Npct بلا تحسّن مقابل في direction_accuracy مؤشر تحذير،
لا نجاح حقيقي.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import mean_absolute_error, mean_squared_error

# نمطان: يومي (feature_table.py) وساعي (feature_table_hourly.py) — طلب
# عبده "حاول العمل على فريمات متنوعة" شمل فريم الشموع نفسه (يوم/ساعة)، لا
# فقط أفق التنبؤ أو نافذة التدريب. كل نمط له مجلد جداول وآفاق تنبؤ وخيارات
# نافذة تدريب مختلفة (بالأيام للنمط اليومي، بالساعات للساعي).
FRAME_CONFIGS = {
    "daily": {
        "dir": Path("../runs/ai_catch_win_engine/feature_tables"),
        "date_col": "date",
        "horizons": [1, 5, 10, 20],
        "train_windows": {"full_history": None, "last_10y": 2520, "last_5y": 1260, "last_2y": 504},
    },
    "hourly": {
        "dir": Path("../runs/ai_catch_win_engine/feature_tables_hourly"),
        "date_col": "datetime_utc",
        "horizons": [1, 4, 8],
        # بيانات ساعية أقصر بكثير (~4900 صف إجمالي لـWMT) من اليومية —
        # نوافذ تدريب أصغر بكثير من daily (بالساعات لا الأيام): آخر ~6
        # أشهر/3 أشهر/شهر تداول تقريبًا (يوم تداول ساعي ≈ 6.5 ساعة).
        "train_windows": {"full_history": None, "last_6m": 780, "last_3m": 390, "last_1m": 130},
    },
}

NON_FEATURE_COLUMNS = {
    "date", "datetime_utc", "close", "open", "high", "low", "delta_price", "abs_delta_price",
}


def load_ticker_table(frame: str, ticker: str, target_col: str) -> pd.DataFrame:
    config = FRAME_CONFIGS[frame]
    path = config["dir"] / f"{ticker}.csv"
    if not path.exists():
        raise FileNotFoundError(f"جدول ميزات ({frame}) غير موجود لـ{ticker}")
    df = pd.read_csv(path)
    return df.dropna(subset=[target_col])  # آخر صفوف بلا هدف (shift(-horizon) عند نهاية التاريخ)


def train_test_split_by_time(df: pd.DataFrame, train_fraction: float = 0.8) -> tuple[pd.DataFrame, pd.DataFrame]:
    """تقسيم زمني: أول train_fraction تدريب، الباقي اختبار (لا خلط عشوائي)."""
    split_idx = int(len(df) * train_fraction)
    return df.iloc[:split_idx], df.iloc[split_idx:]


def train_and_evaluate(frame: str, ticker: str, target_col: str, train_window_name: str,
                        train_window_days: int | None) -> dict:
    df = load_ticker_table(frame, ticker, target_col)
    excluded = NON_FEATURE_COLUMNS | {f"target_{kind}_h{h}" for h in FRAME_CONFIGS[frame]["horizons"]
                                       for kind in ("high", "low", "close")}
    feature_cols = [c for c in df.columns if c not in excluded]

    train_df, test_df = train_test_split_by_time(df)
    # فريم التدريب (طلب عبده: تجربة أحجام مدخلات مختلفة) — يُقتطَع من آخر
    # train_df (الأحدث ضمن قسم التدريب)، لا من كل df، فيبقى test_df بلا
    # تغيير عبر كل فريمات التدريب لنفس (ticker, target) — مقارنة عادلة.
    if train_window_days is not None and len(train_df) > train_window_days:
        train_df = train_df.iloc[-train_window_days:]

    if len(train_df) < 100 or len(test_df) < 20:
        return {"ticker": ticker, "target": target_col, "train_window": train_window_name, "skipped": True,
                "reason": f"عيّنة صغيرة جدًا (train={len(train_df)}, test={len(test_df)})"}

    X_train, y_train = train_df[feature_cols], train_df[target_col]
    X_test, y_test = test_df[feature_cols], test_df[target_col]

    # تطوير 2026-07-18 (طلب عبده: دقة > 96%) — grid search صغير على
    # hyperparameters بدل قيم ثابتة واحدة لكل الأسهم: تجربة فعلية (سكريبت
    # منفصل) أظهرت أن أفضل تركيبة تختلف باختلاف السهم (مثلاً LIN يفضّل
    # max_depth=4، بينما WMT/ORCL/MAR يفضّلون max_depth=3 مع أشجار أكثر
    # وlearning_rate أبطأ) — لا تركيبة واحدة مثلى للجميع. يُختار الأفضل عبر
    # eval_set فرعي من train (لا test، لتفادي أي تسريب)، مع early stopping
    # لتفادي overfitting عند كل تركيبة.
    eval_split = max(int(len(X_train) * 0.9), len(X_train) - 200)
    X_fit, X_eval = X_train.iloc[:eval_split], X_train.iloc[eval_split:]
    y_fit, y_eval = y_train.iloc[:eval_split], y_train.iloc[eval_split:]

    param_grid = [
        {"n_estimators": 400, "max_depth": 3, "learning_rate": 0.03},
        {"n_estimators": 400, "max_depth": 4, "learning_rate": 0.03},
        {"n_estimators": 600, "max_depth": 3, "learning_rate": 0.02},
        {"n_estimators": 300, "max_depth": 2, "learning_rate": 0.05},
    ]

    best_model, best_eval_rmse = None, float("inf")
    for params in param_grid:
        candidate = xgb.XGBRegressor(
            subsample=0.8, colsample_bytree=0.8, random_state=42,
            early_stopping_rounds=20, eval_metric="rmse", **params,
        )
        if len(X_eval) >= 20:
            candidate.fit(X_fit, y_fit, eval_set=[(X_eval, y_eval)], verbose=False)
            eval_pred = candidate.predict(X_eval)
            eval_rmse = float(np.sqrt(mean_squared_error(y_eval, eval_pred)))
        else:
            candidate.set_params(early_stopping_rounds=None)
            candidate.fit(X_train, y_train)
            eval_rmse = 0.0  # لا eval_set كافٍ — أول تركيبة تُقبل مباشرة
        if eval_rmse < best_eval_rmse:
            best_model, best_eval_rmse = candidate, eval_rmse

    model = best_model
    # إعادة تدريب أفضل تركيبة على كامل X_train (بلا اقتطاع eval) بعدد
    # الأشجار الفعلي الذي توقف عنده early stopping — يستفيد من كل بيانات
    # التدريب المتاحة بدل تضييع آخر 10%/200 صف على eval فقط.
    if len(X_eval) >= 20 and model.best_iteration is not None:
        final_params = model.get_params()
        final_params["n_estimators"] = model.best_iteration + 1
        final_params.pop("early_stopping_rounds", None)
        model = xgb.XGBRegressor(**final_params)
        model.fit(X_train, y_train)

    train_pred = model.predict(X_train)
    test_pred = model.predict(X_test)

    train_rmse = float(np.sqrt(mean_squared_error(y_train, train_pred)))
    test_rmse = float(np.sqrt(mean_squared_error(y_test, test_pred)))
    train_mae = float(mean_absolute_error(y_train, train_pred))
    test_mae = float(mean_absolute_error(y_test, test_pred))

    # مقياس overfitting بسيط: نسبة test_rmse / train_rmse — كلما زادت عن 1
    # بشكل كبير، كلما كان النموذج يحفظ التدريب بدل التعميم.
    overfit_ratio = test_rmse / train_rmse if train_rmse > 0 else float("inf")

    # baseline بسيط للمقارنة: توقّع "0% تغيّر" (naive persistence، بما أن
    # الهدف الآن % تغيّر عن سعر اليوم لا سعرًا مطلقًا — راجع تصحيح
    # feature_table.py) — يعادل مباشرة RMSE حول الصفر لقيم y_test نفسها.
    naive_test_rmse = float(np.sqrt(mean_squared_error(y_test, np.zeros(len(y_test)))))

    # عرض إضافي بالسنت (طلب عبده: "اعرضها أيضًا بالسنت في المخرجات") — يُشتق
    # من % التغيّر المتوقَّع × سعر آخر يوم اختبار فعليًا (تحويل عكسي)، لا
    # يُستخدم في التدريب نفسه (الهدف يبقى % لحل مشكلة overfitting الأصلية،
    # راجع نقاش عبده 2026-07-18: الوحدة وحدها — دولار أو سنت — لا تحل
    # overfitting الناتج عن تغيّر مستوى السعر عبر عقود بسبب انقسامات الأسهم).
    last_test_close_cents = float(test_df["close"].iloc[-1]) * 100
    last_test_pred_pct = float(test_pred[-1])
    predicted_price_cents = last_test_close_cents * (1 + last_test_pred_pct / 100)

    # "دقة" (طلب عبده: "الوصول لنسبة دقة أكبر من 90%") = نسبة التنبؤات التي
    # يقع فيها السعر الفعلي ضمن هامش خطأ معقول من السعر المتوقَّع — نُعيد
    # بناء السعر الفعلي/المتوقَّع بالدولار من % التغيّر (بالنسبة لسعر ذلك
    # اليوم تحديدًا لكل صف اختبار، لا صف واحد فقط) لحساب هذا على كل test_df.
    actual_price = test_df["close"] * (1 + y_test / 100)
    predicted_price = test_df["close"] * (1 + test_pred / 100)
    pct_error = np.abs(predicted_price - actual_price) / actual_price
    accuracy_within_1pct = float((pct_error <= 0.01).mean() * 100)
    accuracy_within_2pct = float((pct_error <= 0.02).mean() * 100)
    accuracy_within_5pct = float((pct_error <= 0.05).mean() * 100)

    # دقة الاتجاه (القسم 9.18 — مقياس مستقل إلزامي، لا بديل عن accuracy_within_Npct
    # بل رفيق له): هل إشارة التوقع (+/-) تطابق إشارة الفعلي؟ صفوف y_test=0
    # بالضبط (نادرة) تُستبعد من المقام — لا معنى لـ"اتجاه" لتغيّر صفري فعلي.
    # (يُحوَّل كل شيء لـnumpy صراحة هنا لتفادي أي التباس فهرسة pandas/numpy.)
    y_test_arr = y_test.to_numpy()
    nonzero_mask = y_test_arr != 0
    y_nonzero, pred_nonzero = y_test_arr[nonzero_mask], test_pred[nonzero_mask]

    if nonzero_mask.any():
        correct_direction = np.sign(pred_nonzero) == np.sign(y_nonzero)
        direction_accuracy = float(correct_direction.mean() * 100)
    else:
        correct_direction = np.array([], dtype=bool)
        direction_accuracy = None

    # معامل معايرة الحجم (طلب عبده 2026-07-18: "توقّع لنسبة الربح" صادق —
    # لاحظ عبده أن %التغيّر المتوقَّع مضغوط دائمًا (std التوقعات أقل بكثير من
    # std الفعلي، خصوصًا على الأسهم العنيفة الجديدة ذات البيانات القليلة)،
    # فاستخدام رقم النموذج الخام كـ"حجم ربح متوقَّع" يقلّل الهدف الحقيقي.
    # الحل اللي اختاره عبده: معامل معايرة = متوسط |الفعلي| ÷ متوسط |المتوقَّع|،
    # محسوب فقط على الصفوف اللي كان فيها النموذج **محقًا اتجاهيًا** (لا نثق
    # بحجم توقع كان اتجاهه غلط أصلاً) — يُضرب لاحقًا في توقع predict.py الحي
    # ليعطي حجم ربح متوقَّع أقرب للواقع التاريخي، لا الرقم المضغوط الخام.
    #
    # حراسة إضافية (اكتُشفت فعليًا بفحص أول تشغيلة كاملة، معاملات وصلت 628x):
    # (أ) عيّنة صغيرة جدًا (<MIN_CALIBRATION_SAMPLES صفًا محقًا اتجاهيًا) تعطي
    # نسبة غير مستقرة إحصائيًا — تُرفَض بدل الوثوق بها. (ب) توقعات قريبة جدًا
    # من الصفر (predicted_abs_when_right شبه معدوم) تُنتج قسمة متفجرة رياضيًا
    # بلا معنى عملي — أي معامل خارج MAX_CALIBRATION_FACTOR معقول يُرفَض صراحة
    # (None)، لا يُقصّ (clip) بصمت لقيمة عشوائية.
    MIN_CALIBRATION_SAMPLES = 20
    MAX_CALIBRATION_FACTOR = 20.0
    if correct_direction.sum() >= MIN_CALIBRATION_SAMPLES:
        actual_abs_when_right = float(np.abs(y_nonzero[correct_direction]).mean())
        predicted_abs_when_right = float(np.abs(pred_nonzero[correct_direction]).mean())
        raw_factor = (
            actual_abs_when_right / predicted_abs_when_right if predicted_abs_when_right > 0 else None
        )
        magnitude_calibration_factor = (
            raw_factor if raw_factor is not None and raw_factor <= MAX_CALIBRATION_FACTOR else None
        )
    else:
        magnitude_calibration_factor = None

    return {
        "frame": frame, "ticker": ticker, "target": target_col, "train_window": train_window_name, "skipped": False,
        "n_train": len(train_df), "n_test": len(test_df),
        "train_rmse": round(train_rmse, 4), "test_rmse": round(test_rmse, 4),
        "train_mae": round(train_mae, 4), "test_mae": round(test_mae, 4),
        "overfit_ratio": round(overfit_ratio, 2),
        "naive_baseline_test_rmse": round(naive_test_rmse, 4),
        "beats_naive_baseline": test_rmse < naive_test_rmse,
        "accuracy_within_1pct": round(accuracy_within_1pct, 2),
        "accuracy_within_2pct": round(accuracy_within_2pct, 2),
        "accuracy_within_5pct": round(accuracy_within_5pct, 2),
        "direction_accuracy": round(direction_accuracy, 2) if direction_accuracy is not None else None,
        "magnitude_calibration_factor": (
            round(magnitude_calibration_factor, 4) if magnitude_calibration_factor is not None else None
        ),
        "last_test_close_cents": round(last_test_close_cents, 2),
        "last_test_predicted_pct": round(last_test_pred_pct, 4),
        "last_test_predicted_price_cents": round(predicted_price_cents, 2),
    }


def main(frame: str, tickers: list[str]) -> None:
    config = FRAME_CONFIGS[frame]
    target_columns = [f"target_{kind}_h{h}" for h in config["horizons"] for kind in ("high", "low", "close")]

    rows = []
    for ticker in tickers:
        for target in target_columns:
            for window_name, window_days in config["train_windows"].items():
                try:
                    result = train_and_evaluate(frame, ticker, target, window_name, window_days)
                except FileNotFoundError as exc:
                    print(f"{ticker}: {exc}")
                    continue
                rows.append(result)
                if result.get("skipped"):
                    continue
                overfit_flag = " *** OVERFITTING محتمل (overfit_ratio > 3) ***" if result["overfit_ratio"] > 3 else ""
                beats = "أفضل من baseline" if result["beats_naive_baseline"] else "أسوأ من/يعادل baseline"
                dir_acc = result["direction_accuracy"]
                dir_flag = " *** اتجاه بمستوى الصدفة (~50%) ***" if dir_acc is not None and dir_acc < 55 else ""
                print(f"[{frame}] {ticker} / {target} / {window_name}: train RMSE={result['train_rmse']}, "
                      f"test RMSE={result['test_rmse']} (overfit_ratio={result['overfit_ratio']})"
                      f"{overfit_flag} — {beats} (naive={result['naive_baseline_test_rmse']}) — "
                      f"دقة الاتجاه={dir_acc}%{dir_flag}")

    out_df = pd.DataFrame(rows)
    out_path = Path(f"../runs/ai_catch_win_engine/model_training_results_{frame}.csv")
    out_df.to_csv(out_path, index=False)
    print(f"\nWrote training results to {out_path.resolve()}")

    valid = out_df[out_df["skipped"] == False]
    if not valid.empty:
        n_beats = int(valid["beats_naive_baseline"].sum())
        n_overfit = int((valid["overfit_ratio"] > 3).sum())
        mean_dir_acc = valid["direction_accuracy"].mean()
        n_coinflip_direction = int((valid["direction_accuracy"] < 55).sum())
        print(f"\nملخص [{frame}]: {len(valid)} تشغيلة صالحة — {n_beats} تفوقت على baseline "
              f"({100*n_beats/len(valid):.1f}%), {n_overfit} أظهرت overfitting واضح "
              f"(overfit_ratio>3, {100*n_overfit/len(valid):.1f}%), متوسط دقة الاتجاه="
              f"{mean_dir_acc:.1f}%، {n_coinflip_direction} تشغيلة ({100*n_coinflip_direction/len(valid):.1f}%) "
              f"دقة اتجاهها قريبة من الصدفة (<55%)")


if __name__ == "__main__":
    frame_arg = sys.argv[1] if len(sys.argv) > 1 else "daily"
    tickers_arg = sys.argv[2:] if len(sys.argv) > 2 else \
        ["AAPL", "ALL", "APTV", "BAX", "COST", "GM", "LIN", "MAR", "ORCL", "WMT"]
    main(frame_arg, tickers_arg)
