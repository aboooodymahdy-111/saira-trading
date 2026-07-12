# Saira Trading API — المرحلة 0

خلفية FastAPI لمنصة Saira Terminal: شموع بأي فريم، مؤشرات فنية، أدوات جان، وجسر للجنة الإشارات الحالية.

## التثبيت والتشغيل (ويندوز)

1. انسخ مجلد `saira-api` بأكمله إلى داخل `C:\Users\Mahdy\Saira-Trading\`
   (هذا مهم — الجسر يبحث عن `committee_signals.py` و`gann_square9.py` في المجلد الأب تلقائيًا).
2. ضع ملفات Stooq النصية (`aal_us.txt` وأخواتها) في `Saira-Trading\market_data\`
   أو غيّر المسار بمتغير البيئة `SAIRA_DATA`.
3. شغّل `run.bat` (يثبّت المتطلبات ثم يقلع الخادم على المنفذ 8787).
4. افتح التوثيق التفاعلي: **http://127.0.0.1:8787/docs** — كل نقطة نهاية قابلة للتجربة من المتصفح.
5. أول مرة فقط: نفّذ `POST /import/stooq` من صفحة docs لاستيراد كل الملفات دفعة واحدة إلى DuckDB.

## نقاط النهاية

| النقطة | الوظيفة |
|---|---|
| `GET /health` | فحص الحالة |
| `GET /symbols` | الرموز المخزنة + حالة القائمة الأخلاقية لكل رمز |
| `POST /import/stooq` | استيراد دفعة ملفات Stooq من مجلد البيانات |
| `POST /refresh/{symbol}` | تحديث الشموع اليومية من ياهو فايننس |
| `GET /candles/{symbol}?tf=D` | شموع بفريم: `30/60/300/900/3600/14400/D/W/M` |
| `GET /indicators/{symbol}?names=rsi,macd,sma20,bb,adx` | مؤشرات فنية (فترة الإحماء تعود `null` — لا تقاطعات زائفة) |
| `GET /gann/sq9?price=X` | مستويات مربع التسعة من سعر ارتكاز |
| `GET /gann/sq9/{symbol}?side=low` | مربع 9 تلقائيًا من قاع/قمة الرمز مقصوصًا على مداه |
| `GET /gann/swing/{symbol}?bars=2` | ارتكازات سوينج جان (2 أو 3 بار) + الاتجاه الحالي |
| `GET /gann/cycles/{symbol}` | أقوى الدورات الزمنية (تحليل طيفي) |
| `GET /gann/sun?t=EPOCH` | خط طول الشمس الجيوسنتري |
| `GET /committee/{symbol}` | تشغيل لجنة الإشارات الحالية عبر الجسر |

## ربط لجنة الإشارات

`app/pipeline_bridge.py` يستورد `committee_signals` من جذر المشروع ويجرّب الدوال:
`run_committee` ثم `committee_for_symbol` ثم `main` ثم `run`.
إن كانت دالتك باسم آخر، أضف اسمها إلى `_CANDIDATES` في أول الملف — سطر واحد فقط.

## الطبقة الأخلاقية

`tickers_allowlist.txt`: ضع الـ 219 رمزًا المعتمدة (رمز في كل سطر). نقطة `/symbols`
تعلّم كل رمز بـ `allowed: true/false`، والماسح في المراحل القادمة لن يتجاوزها.

## البنية

```
saira-api/
├─ run.bat                  ← التشغيل بنقرة
├─ requirements.txt
├─ tickers_allowlist.txt    ← القائمة الأخلاقية
└─ app/
   ├─ main.py               ← نقاط النهاية
   ├─ config.py             ← المسارات (متغيرات بيئة)
   ├─ pipeline_bridge.py    ← جسر committee_signals
   ├─ data/store.py         ← DuckDB: استيراد Stooq + استعلام أي فريم
   └─ analysis/
      ├─ indicators.py      ← RSI/MACD/SMA/EMA/BB/ADX/ATR بضمانات الحواف
      └─ gann.py            ← مربع 9 (بجسر لأداتك) + سوينج + دورات + الشمس
```

## ملاحظات تقنية

- الطوابع الزمنية بالثواني (epoch) في جدول واحد — نفس المخطط سيستقبل شموع
  الـ 30 ثانية من مُجمِّع Alpaca في المرحلة 4 دون أي تعديل.
- إعادة التجميع تتم في DuckDB عند الاستعلام (`arg_min/arg_max`) لا في بايثون — سريعة لأي حجم.
- متوافق مع pandas 2 و3 (معالجة صريحة لدقة التواريخ).
- CORS مفتوح محليًا كي يتصل النموذج `saira-terminal-prototype.html` بالخادم مباشرة في المرحلة 1.
