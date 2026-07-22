"""
ai_catch_win_engine/test_ipo_seasonality.py — اختبار مخصص (توجيه عبده 2026-07-18):
"هل وجود IPO يحدث فارق؟" — بمعنى: هل موسم/توقيت تاريخ الإدراج نفسه (لا أي
حساب فلكي مشتق منه) يحمل إشارة تنبؤية، بمعزل عن الفلك تمامًا؟

**لماذا هذا ملف منفصل، لا امتداد لـtrain_model.py**: كل تجارب ai_catch_win_engine
الأخرى تدرّب نموذجًا **منفصلاً لكل سهم** — وهذا يجعل أي ميزة IPO ثابتة
(مثل شهر الإدراج) عديمة الفائدة تمامًا (قيمة واحدة لا تتغيّر ضمن بيانات
سهم واحد = صفر معلومة لأي نموذج). لاختبار "هل موسم IPO يفرّق فعليًا بين
الأسهم" يجب نموذج **واحد مشترك** يرى بيانات كل الأسهم معًا، بحيث تتفاوت
قيمة `ipo_month`/`ipo_quarter` فعليًا بين الصفوف.

**اكتشاف تمهيدي مهم (فحص أولي قبل بناء هذا الملف)**: `days_since_ipo`
(عمر السهم بالأيام، كمتغيّر رقمي متزايد) أعطى دقة عالية مضلِّلة (87.9%
داخل نموذج منفصل لكل سهم) — لكن فحص نطاقات train/test أظهر عدم تداخل
تام (كل قيم test أعلى من كل قيم train، لأنه متغيّر رتيب بلا استثناء). هذا
**تسريب زمني مقنَّع (leakage)**: النموذج يحفظ "أين نحن في الخط الزمني"
كبديل غير مباشر عن الاتجاه العام، لا نمطًا عمريًا حقيقيًا. **لذلك هذا
الملف يستبعد days_since_ipo عمدًا** ويستخدم فقط سمات IPO الثابتة (شهر/
فصل/يوم أسبوع الإدراج) التي لا ترتبط بالتقدّم الزمني داخل حياة السهم.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import mean_squared_error

sys.path.insert(0, ".")

from ai_catch_win_engine.natal_dates import get_natal_date
from ai_catch_win_engine.train_model import FRAME_CONFIGS, NON_FEATURE_COLUMNS

TICKERS = ["AAL", "ADBE", "ALL", "AVB", "AVGO", "COST", "CSCO", "EBAY", "EQR",
           "ISRG", "LIN", "LUV", "MA", "NSC", "QCOM", "ROST", "SYY", "UNP", "VTR", "WMT"]
TARGET = "target_high_h1"
FEATURE_TABLES_DIR = Path("../runs/ai_catch_win_engine/feature_tables")


def _load_pooled_data() -> pd.DataFrame:
    """
    يجمع بيانات كل الأسهم في جدول واحد، مضيفًا سمات IPO الثابتة (لا
    days_since_ipo — راجع تحذير docstring الملف) وعمود ticker (لضبط تأثير
    السهم نفسه بمعزل عن IPO، عبر ترميزه كفئة).
    """
    frames = []
    for ticker in TICKERS:
        path = FEATURE_TABLES_DIR / f"{ticker}.csv"
        if not path.exists():
            continue
        df = pd.read_csv(path)
        natal_date = pd.to_datetime(get_natal_date(ticker))

        df["ticker"] = ticker
        df["ipo_month"] = natal_date.month
        df["ipo_quarter"] = (natal_date.month - 1) // 3 + 1
        df["ipo_day_of_week"] = natal_date.dayofweek
        df["ipo_year"] = natal_date.year
        frames.append(df)

    pooled = pd.concat(frames, ignore_index=True)
    pooled["date"] = pd.to_datetime(pooled["date"])
    return pooled.sort_values("date").reset_index(drop=True)


def _time_split_pooled(df: pd.DataFrame, train_fraction: float = 0.8) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    تقسيم زمني على المجمّع بأكمله (لا لكل سهم على حدة) — تاريخ القطع نفسه
    لكل الأسهم، فلا يرى train أي يوم بعد تاريخ القطع من أي سهم، ولا يرى test
    أي يوم قبله. يحافظ هذا على منع أي تسريب عبر الأسهم (مثلاً معرفة اتجاه
    السوق العام في فترة معينة من سهم آخر).
    """
    cutoff_date = df["date"].quantile(train_fraction, interpolation="nearest")
    return df[df["date"] <= cutoff_date], df[df["date"] > cutoff_date]


def run_test() -> None:
    pooled = _load_pooled_data()
    print(f"إجمالي الصفوف المجمّعة: {len(pooled)} عبر {pooled['ticker'].nunique()} سهمًا")

    known = pooled.dropna(subset=[TARGET])
    train_df, test_df = _time_split_pooled(known)
    print(f"train: {len(train_df)} صف، test: {len(test_df)} صف "
          f"(تاريخ القطع: {train_df['date'].max().date()})")

    excluded = NON_FEATURE_COLUMNS | {f"target_{k}_h{h}" for h in FRAME_CONFIGS["daily"]["horizons"]
                                       for k in ("high", "low", "close")}
    astro_features = [c for c in pooled.columns if c not in excluded
                       and any(p in c for p in ("saturn", "jupiter", "mars", "venus", "sun_", "mercury",
                                                  "moon", "n_harmonious", "n_tense", "n_conjunction",
                                                  "net_aspect", "ruler_transit"))]
    tech_features = [c for c in pooled.columns if c not in excluded and c not in astro_features
                      and c not in ("ticker", "ipo_month", "ipo_quarter", "ipo_day_of_week", "ipo_year")]
    ipo_features_raw = ["ipo_month", "ipo_quarter", "ipo_day_of_week", "ipo_year"]
    ticker_dummies = pd.get_dummies(pooled["ticker"], prefix="ticker")
    pooled_with_dummies = pd.concat([pooled, ticker_dummies], axis=1)
    train_df = pooled_with_dummies.loc[train_df.index]
    test_df = pooled_with_dummies.loc[test_df.index]
    ticker_features = list(ticker_dummies.columns)

    configs = {
        "tech only (no ticker ID, no IPO)": tech_features,
        "astro only (no ticker ID, no IPO)": astro_features,
        "IPO features only (month/quarter/dow/year, no ticker ID)": ipo_features_raw,
        "ticker identity only (which stock is it, no IPO/astro/tech)": ticker_features,
        "tech + IPO features": tech_features + ipo_features_raw,
        "tech + ticker identity": tech_features + ticker_features,
        "everything (tech+astro+IPO+ticker identity)": tech_features + astro_features + ipo_features_raw + ticker_features,
    }

    results = []
    for name, cols in configs.items():
        model = xgb.XGBRegressor(n_estimators=400, max_depth=4, learning_rate=0.03,
                                  subsample=0.8, colsample_bytree=0.8, random_state=42)
        model.fit(train_df[cols], train_df[TARGET])
        pred = model.predict(test_df[cols])
        rmse = float(np.sqrt(mean_squared_error(test_df[TARGET], pred)))

        actual_price = test_df["close"] * (1 + test_df[TARGET] / 100)
        pred_price = test_df["close"] * (1 + pred / 100)
        pct_error = np.abs(pred_price - actual_price) / actual_price
        acc2 = float((pct_error <= 0.02).mean() * 100)
        acc5 = float((pct_error <= 0.05).mean() * 100)

        results.append({"config": name, "n_features": len(cols), "test_rmse": round(rmse, 4),
                         "accuracy_within_2pct": round(acc2, 2), "accuracy_within_5pct": round(acc5, 2)})
        print(f"{name} (n={len(cols)}): RMSE={rmse:.4f}, acc±2%={acc2:.2f}%, acc±5%={acc5:.2f}%")

    out = pd.DataFrame(results)
    out_path = Path("../runs/ai_catch_win_engine/ipo_seasonality_test.csv")
    out.to_csv(out_path, index=False)
    print(f"\nWrote results to {out_path.resolve()}")


if __name__ == "__main__":
    run_test()
