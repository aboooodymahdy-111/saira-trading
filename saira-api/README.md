# Saira Trading API — المراحل 0-3

خلفية FastAPI لمنصة Saira Terminal: شموع بأي فريم، مؤشرات فنية، أدوات جان الكاملة
(مربع 9، نجمة، مربع 144، موازنة سعر/زمن، حاسبة الزمن الرئيسية، ماسح كوكبي + شبكة
خطوط مترابطة، جدول كسوف/خسوف)، وجسر للجنة الإشارات الحالية. الواجهة (`saira-terminal.html`)
ثنائية اللغة (عربي/إنجليزي، زر EN/ع في الهيدر) وتعمل كصفحة ويب أو مغلّفة كتطبيق
سطح مكتب عبر Tauri (المرحلة 3، انظر أسفل).

## التثبيت والتشغيل — كصفحة ويب (ويندوز)

1. انسخ مجلد `saira-api` بأكمله إلى داخل `C:\Users\Mahdy\Saira-Trading\`
   (هذا مهم — الجسر يبحث عن `committee_signals.py` و`gann_square9.py` في المجلد الأب تلقائيًا).
2. ضع ملفات Stooq النصية (`aal_us.txt` وأخواتها) في `Saira-Trading\market_data\`
   أو غيّر المسار بمتغير البيئة `SAIRA_DATA`.
3. شغّل `run.bat` (يثبّت المتطلبات ثم يقلع الخادم على المنفذ 8787).
4. افتح `saira-terminal.html` مباشرة في المتصفح — يتصل بالخادم تلقائيًا.
5. أول مرة فقط: نفّذ `POST /import/stooq` (من `http://127.0.0.1:8787/docs`) لاستيراد
   كل ملفات Stooq دفعة واحدة إلى DuckDB.

## التشغيل كتطبيق سطح مكتب (المرحلة 3، Tauri)

يغلّف نفس الواجهة والخادم في نافذة أصلية (لا حاجة لفتح متصفح يدويًا، ولا تشغيل
`run.bat` قبلها — الخادم يُشغَّل تلقائيًا عند فتح التطبيق ويُغلَق معه):

```
cd src-tauri
cargo tauri dev      # تشغيل تطويري (يعيد البناء عند أي تعديل)
cargo tauri build    # حزمة تثبيت نهائية (.exe/.msi) في src-tauri/target/release/bundle
```

**المتطلبات لمرة واحدة فقط:**

- Rust (`rustup`) + MSVC Build Tools (نفس متطلبات Tauri على ويندوز).
- `npm install` داخل `saira-api/` (يثبّت `@tauri-apps/cli` فقط، بلا خطوة بناء JS).
- **ملاحظة شبكة محتملة:** لو `cargo build` فشل بخطأ
  `CRYPT_E_NO_REVOCATION_CHECK` (شبكات معينة بتفشل في فحص إلغاء شهادات
  TLS)، أضف `check-revoke = false` تحت `[http]` في
  `%USERPROFILE%\.cargo\config.toml`.

**ملاحظة صيانة مهمة:** `src-tauri/frontend/` نسخة مُولَّدة تلقائيًا من
`saira-terminal.html` + مكتبة الشارت (عبر `build.rs`، يعمل قبل كل بناء) —
**لا تعدّل الملفات جوه `src-tauri/frontend/` مباشرة**، أي تعديل على الواجهة
لازم يبقى في `saira-terminal.html` نفسه في جذر `saira-api/`.

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
| `GET /gann/star?price=X&kind=hexagram` | نجمة جان (خماسية 72° أو سداسية 60°) |
| `GET /gann/sq144/{symbol}` | حاسبة مربع 144 من آخر ارتكاز سوينج |
| `GET /gann/confluence/{symbol}` | درجة الالتقاء: عنقدة كل الأدوات مرجّحة |
| `GET /gann/squaring/{symbol}` | موازنة السعر والزمن (جوهر منهج جان) |
| `GET /gann/master_time/{symbol}` | حاسبة الزمن الرئيسية: مواعيد استحقاق 30-360 يومًا |
| `GET /astro/planets` | قائمة الكواكب المدعومة |
| `GET /astro/longitudes/{planet}` | سلسلة خطوط طول عبر مدى زمني + علم التراجع |
| `GET /astro/snapshot?t=EPOCH` | خطوط طول كل الكواكب لحظة معينة |
| `GET /astro/eclipses` | جدول الكسوف/الخسوف بين تاريخين |
| `GET /scan/planets/{symbol}` | الماسح الكوكبي: أفضل الكواكب حسب اختباري الانعكاس/المحاذاة |
| `GET /scan/grid/{symbol}` | شبكة خط كوكب واحد (تكرارات دورية) |
| `GET /scan/connected/{symbol}` | الشبكة المترابطة: قِران/سداسي/تربيع/تثليث/مقابلة معًا |
| `GET /committee/{symbol}` | تشغيل لجنة الإشارات الحالية عبر الجسر |

القائمة الكاملة والتفاعلية دومًا على `http://127.0.0.1:8787/docs`.

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
├─ run.bat                          ← التشغيل بنقرة (وضع الويب)
├─ requirements.txt
├─ tickers_allowlist.txt            ← القائمة الأخلاقية
├─ saira-terminal.html              ← الواجهة (المصدر الوحيد الحقيقي، عربي/إنجليزي)
├─ lightweight-charts.standalone.production.js
├─ app/
│  ├─ main.py                       ← نقاط النهاية
│  ├─ config.py                     ← المسارات (متغيرات بيئة)
│  ├─ pipeline_bridge.py           ← جسر committee_signals
│  ├─ data/store.py                 ← DuckDB: استيراد Stooq + استعلام أي فريم
│  └─ analysis/
│     ├─ indicators.py             ← RSI/MACD/SMA/EMA/BB/ADX/ATR بضمانات الحواف
│     ├─ gann.py                    ← مربع 9/144، نجمة، سوينج، دورات، موازنة سعر/زمن، حاسبة الزمن الرئيسية
│     ├─ astro.py                   ← pyswisseph: خطوط طول الكواكب + كسوف/خسوف
│     └─ scanner.py                 ← الماسح الكوكبي + الشبكة المترابطة
└─ src-tauri/                       ← المرحلة 3: تغليف سطح المكتب (Tauri)
   ├─ tauri.conf.json
   ├─ build.rs                      ← يزامن frontend/ من saira-terminal.html تلقائيًا
   ├─ src/lib.rs                    ← يشغّل خادم FastAPI كعملية فرعية عند الإقلاع
   └─ frontend/                     ← نسخة مُولَّدة، غير موجودة في git (.gitignore)
```

## ملاحظات تقنية

- الطوابع الزمنية بالثواني (epoch) في جدول واحد — نفس المخطط سيستقبل شموع
  الـ 30 ثانية من مُجمِّع Alpaca في المرحلة 4 دون أي تعديل.
- إعادة التجميع تتم في DuckDB عند الاستعلام (`arg_min/arg_max`) لا في بايثون — سريعة لأي حجم.
- متوافق مع pandas 2 و3 (معالجة صريحة لدقة التواريخ).
- CORS مفتوح محليًا كي يتصل النموذج `saira-terminal-prototype.html` بالخادم مباشرة في المرحلة 1.
