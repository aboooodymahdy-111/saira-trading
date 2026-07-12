# Saira-Trading

نظام تداول شبه-آلي (swing trading) لأسهم أمريكية، مبني على تحليل فني/كمّي/فلكي
مستقل بايثون (بدون أي اعتماد على Timing Solution)، ضمن فلاتر أخلاقية صارمة.
القرار النهائي دايمًا مراجعة يدوية — لا يوجد تنفيذ آلي لأي أمر شراء/بيع حقيقي.

## قواعد ثابتة (لا تتغير بدون نقاش صريح)

- **Timing Solution (TS) اتشال من المشروع بالكامل (قرار 2026-07).** كان
  المشروع أصلاً مبني على دمج إشارات TS الدورية/الفلكية مع تحليل فني مستقل، لكن
  بعد قياس دقة TS التاريخية (verify_signals.py) وطلوعها ~19.7% فقط — ضعيفة جدًا
  ومكلفة (شبكة + وقت) من غير عائد حقيقي — تقرر شيلها نهائيًا. الملفات
  `extract_signals.py` / `verify_signals.py` / `confirm_signals.py` /
  `independent_signals.py` اتنقلت لمجلد `deprecated_ts/` (مش محذوفة، للمرجعية
  بس — ما تستوردش منها في كود جديد). `committee_signals.py` بقى مكتبة تصويت
  مشتركة فقط (بدون main() خاص بيه)، و`full_universe_analysis.py` هو الـ
  pipeline الوحيد الشغّال دلوقتي — بيغطي كامل NASDAQ+NYSE مع الفلتر الأخلاقي
  مطبّق، بدون أي اعتماد على TS من الأساس.
- **دقة TS التاريخية (~19.7%، كانت في verify_signals.py) ما تتستخدمش أبدًا في
  تحجيم الصفقات أو أي قرار risk management** — نفس السبب اللي خلّى TS تتشال
  خالص. لو أي كود جديد بيستورد من `deprecated_ts/` داخل سياق تحجيم المخاطر أو
  اختيار المرشحين، ده خطأ ولازم يتراجع.
- **الفلتر الأخلاقي (`ethical_screen.py`) إلزامي على أي تحليل لسهم جديد**:
  استبعاد بنوك، دفاع/أسلحة، وقائمة BDS المحددة يدويًا (`BDS_EXCLUDED_TICKERS`).
  مبني على sector/industry من yfinance + قائمة تيكرات ثابتة، مش سكان تلقائي.
- **سقف صلب على قيمة أي صفقة مقترحة**: `MAX_ORDER_VALUE_USD` في
  `suggest_execution.py`. أي كود تحجيم جديد (زي `risk_management.py`) لازم
  يستورد الثابت ده مش يكرره برقم مختلف، ودايمًا يحجّم لأسفل منه فقط.
- كل سكريبت بينتج مخرجات بيحتفظ بنسخة أرشيفية (`runs/archive/`) بالإضافة
  للنسخة الأحدث — القرار ده متعمد (بيانات تدريب مستقبلية محتملة)، متشيلوش.
- **أي backtesting (`backtest.py` وأي سكريبت مقارنة زيه) لازم يقرأ بيانات
  الأسعار من الداتا المحلية على الجهاز، مش من yfinance مطلقًا**:
  `D:\EGX.Daily.2000-2023\data\daily\data\daily\us`
  (= `full_universe_analysis.LOCAL_MARKET_DATA_DIR`، عبر
  `build_local_ticker_index()`/`load_local_history()`). ده شغّال على جهاز
  Abdo بس (زي `refresh_ticker_universe.py` بالظبط) ومش جزء من الأتمتة السحابية
  — بيشيل مشكلة الشبكة/rate-limit اللي كانت بتخلي backtest على مئات الأسهم
  ياخد وقت طويل جدًا، فالـ backtest دلوقتي المفروض يتعمل على 400 سهم على
  الأقل، ويفضّل لغاية 1000 سهم لو الوقت يسمح (`TICKER_SAMPLE_SIZE` في
  backtest.py). **تنبيه:** فيه نسخة قديمة (stale) من نفس الداتا على
  `D:\EGX.Daily.2000-2023\data\daily\us` (من غير تكرار `data\daily`) بتوقف
  عند 2026-04-02 بدل التحديث الفعلي — لازم يتتأكد إن آخر تاريخ في الداتا
  المستخدمة قريب من تاريخ النهاردة قبل أي backtest جديد.
- **مؤشر اتجاه جان الميكانيكي (2-bar swing-high breakout / swing-low stop)
  اتختبر ورفض (2026-07-13، `src/gann_swing_strategy_backtest.py`)**: على
  400 سهم × 6 شهور، معدل الإصابة الحقيقي (بعد احتساب "missed" كخسارة —
  نفس معيار `evaluate_forward_outcome`) كان 13.1%، أقل من اللجنة الحالية
  (42.8%) وأقل من المعدل الأساسي البسيط (25.3%). **لا يُستخدم كصوت خامس في
  اللجنة بشكله الحالي.** السبب: قاعدة الدخول وحدها (بلا حجم هدف/وقف مبني
  على دعم/مقاومة حقيقي) بتسيب 79% من الإشارات تتوه جانبيًا بلا خروج خلال
  نافذة الاختبار. الكود والـ harness موجودين لإعادة اختبار نسخة محسّنة
  لاحقًا (فلتر ADX، حجم هدف مختلف) من غير إعادة بناء من الصفر.

## Pipeline (الترتيب مهم)

```
full_universe_analysis.py -> runs/full_universe_results.csv (السكان الرئيسي: كامل NASDAQ+NYSE، فلتر أخلاقي، تصويت 4 مجموعات، دخول/خروج)
                           -> runs/committee_candidates.csv (نفس الخطوة: شورت ليست متنوعة قطاعيًا، top 3)
build_report.py           -> runs/report.html             (داشبورد HTML تفاعلي من full_universe_results.csv)
format_report.py          -> runs/committee_report.md      (تقرير Markdown من committee_candidates.csv، لمشاركته مع Claude)
suggest_execution.py      -> runs/execution_suggestions.csv (اقتراح حجم صفقة من full_universe_results.csv، مراجعة يدوية فقط)
```

(الملفات القديمة `extract_signals.py`/`verify_signals.py`/`confirm_signals.py`/
`independent_signals.py` كانت phases 1-4 من TS pipeline قديم — اتشالت بالكامل،
موجودة في `deprecated_ts/` للمرجعية بس، مش جزء من الـ pipeline الحالي.)

كل سكريبت من دول عنده docstring مفصّل في أوله بيشرح المدخلات/المخرجات
والافتراضات — اقرأه قبل التعديل بدل تخمين البنية.

## بنية committee_signals.py (أهم ملف في المشروع)

4 مجموعات تصويت مستقلة، كل واحدة بترجع GroupResult (buy/sell/neutral/unavailable):
- **Technical**: MACD, Golden/Death Cross, Bollinger Bands, ADX-gated trend
- **Quantitative**: Analyst consensus, unusual volume
- **Astrological**: Gann Square of Nine (معايرة لكل سهم عبر
  `gann_decision_system.gann_committee_vote` — مش `gann_square9.py` القديم
  التقريبي)
- **Advanced Technical**: TA-Lib snapshot + Ichimoku + Pivot Points + Volume Profile
  (`advanced_technical_tools.py`)

الترشيح النهائي (`select_diversified_candidates`): `total_buy_votes >
total_sell_votes`، مفيش حد أدنى للأصوات، مع تنويع القطاعات
(`MAX_CANDIDATES_PER_SECTOR`).

## أدوات Gann (Layers 1-4)

- Layer 1 (رياضي/هندسي): `gann_square9_precise.py` (الطريقة الدقيقة، overlay
  method) + `gann_layer1_tools.py` (Gann Angles, Hexagon, Circle Chart).
  **لا تستخدم `gann_square9.py` القديم** (تقريب sqrt+offset) في أي كود جديد —
  موجود للمرجعية بس.
- Layer 2 (زمني): `gann_time_cycles.py` — تنبؤ تواريخ عبر cell/angle، تحقق ضد
  مثال ALTR في الكتاب.
- Layer 3 (فلكي): `gann_astrology.py` (مواقع كواكب حقيقية via ephem، مش تقريب)
  + `gann_planetary_lines.py` (خطوط سعرية مستمرة تتابع حركة كوكب حقيقية).
- Layer 4 (قرار): `gann_decision_system.py` — يعاير الزاوية/الخط الأنسب لكل
  سهم بدل افتراض زاوية ثابتة (فلسفة "test then trust").
- `gann_increment_selection.py`: يحدد الزيادة السعرية المناسبة (increment)
  حسب ATR الفعلي للسهم، مش رقم ثابت.

## أدوات مساعدة

- `yf_retry.call_with_retry()`: أي نداء yfinance جديد لازم يمر من هنا —
  Yahoo بيعمل rate-limit بسرعة تحت التزامن (خبرة موثقة، 8 workers فشلت،
  3 workers + retry نجحت).
- الفلتر الأخلاقي عبر `ethical_screen.screen_ticker()` قبل أي تحليل سعري.

## أوامر شائعة

```bash
python src/full_universe_analysis.py     # بطيء — كامل NASDAQ+NYSE، تلاجي عشرات الدقايق
python src/build_report.py
python src/format_report.py
python src/suggest_execution.py
pip install pandas numpy yfinance openpyxl --user   # لا يوجد requirements.txt موحّد بعد
```

أو `run_daily.ps1` (يشغّل full_universe_analysis.py ثم build_report.py بالترتيب
ويؤرشف نسخة) — `register_scheduled_task.ps1` يجدولها يوميًا عبر Windows Task
Scheduler.

بيئة العمل: Windows، Python 3.14.6، المشروع في `C:\Users\Mahdy\Saira-Trading\`.

## أسلوب الكود المتوقع (من الكود الموجود)

- كل دالة رئيسية بترجع dataclass واضح (`GroupResult`, `VerificationResult`,
  إلخ) مش dict خام — القيم القابلة للقراءة في التقرير أهم من الاختصار.
- لا تخمين صامت: بيانات ناقصة = `None`/`"unavailable"` صريح، مش قيمة افتراضية
  مموّهة (مبدأ متكرر في كل الملفات: "fail loud, don't let NaN silently mean
  something").
- أي threshold/ثابت رقمي (VOLUME_SPIKE_THRESHOLD، ADX_TREND_THRESHOLD، إلخ)
  بيتكتب كـ constant معلّق في أول الملف مع تعليق يوضح إنه "نقطة بداية معقولة"
  مش قيمة نهائية مثبتة.
- توثيق provenance: أي معادلة Gann لازم تتحقق ضد مثال حقيقي من الكتب
  المرجعية (موجودة في project knowledge) قبل ما تتوثق كـ "صحيحة".

## ما لا يجب فعله

- ما تحطش أي كود تنفيذ آلي حقيقي لأمر شراء/بيع — المشروع كله "اقتراح للمراجعة
  اليدوية" فقط (preflight-checklist.md لازم تتراجع قبل أي تنفيذ حقيقي).
- ما ترجّعش TS أو تستورد من `deprecated_ts/` في كود جديد (اتفق عليه صراحةً —
  راجع أعلى) — لو محتاج سياق تاريخي عن ليه اتشال، الملفات نفسها لسه موجودة هناك.
- ما ترفعش MAX_ORDER_VALUE_USD أو أي سقف أمان من غير تغيير صريح ومرئي في
  `suggest_execution.py` نفسه.
