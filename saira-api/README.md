# Saira Trading API — المراحل 0-4

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

## البيانات اللحظية (المرحلة 4، مُجمِّع Alpaca)

`app/aggregator.py` يستمع لصفقات لحظية عبر Alpaca (خطة Basic **المجانية**،
تغذية IEX، بلا تمويل حساب) ويجمّعها بنفسه إلى شموع 30 ثانية في نفس جدول
DuckDB — لا حاجة لأي تعديل في `store.py`/`main.py` لدعم هذه الفريمات، كانت
جاهزة من المرحلة 0.

1. سجّل حساب مجاني على [alpaca.markets](https://alpaca.markets) (Basic plan).
2. اضبط متغيري البيئة: `ALPACA_KEY_ID` و`ALPACA_SECRET_KEY` (من لوحة تحكم Alpaca).
3. شغّل: `python -m app.aggregator AAPL MSFT GOOG` (أي قائمة رموز مفصولة بمسافة).
4. الشموع الجديدة تظهر فورًا عند `/candles/{symbol}?tf=30` — بدون إعادة تشغيل الخادم.

**بدون المفتاحين، الأمر يرفض العمل صراحة برسالة خطأ واضحة** — لا محاولة
اتصال ستفشل بصمت. IEX feed ~15 دقيقة تأخير على شموع Alpaca الجاهزة، فالتجميع
الذاتي من الصفقات اللحظية هنا هو الطريق المجاني الوحيد لشموع شبه-فورية فعليًا.

## تطبيق ويب مثبَّت — PWA (المرحلة 5)

`manifest.webmanifest` + `service-worker.js` يجعلان الصفحة قابلة للتثبيت من
المتصفح (أيقونة على الشاشة الرئيسية/سطح المكتب، تفتح في نافذتها الخاصة بلا
شريط عنوان متصفح) — نفس كود الويب دون أي تعديل، طبقًا للمبدأ المعماري
الحاكم في الخطة (نواة ويب واحدة).

**شرط أساسي:** Service Workers تتطلب سياقًا آمنًا (`https://` أو
`http://localhost`) — **لا تعمل مع فتح الملف مباشرة (`file://`)**. لتجربتها
محليًا، قدّم `saira-api/` عبر أي خادم استاتيكي بسيط أولًا، مثلًا:
`python -m http.server 8080` من داخل `saira-api/`، ثم افتح
`http://127.0.0.1:8080/saira-terminal.html`.

**ما الذي يُخزَّن Offline وما لا يُخزَّن (مقصود):** الصدفة الثابتة فقط
(HTML/مكتبة الشارت/الأيقونات) — **وليس** أي استجابة من `/candles` أو
`/gann/*` أو أي نقطة نهاية API. البيانات كلها حية من خادم محلي أو نطاق
منشور، وتخزينها offline يعني عرض بيانات قديمة بصمت بدل رسالة واضحة أن
الخادم غير متاح — عكس مبدأ المشروع ("fail loud"، راجع الشارت نفسه بيتعامل
مع فقد الاتصال أصلًا عبر `setSrv(false)`).

**النشر العام + أندرويد:** بمجرد نشر `saira-api/` على استضافة حقيقية
(Cloudflare Pages/Render — قرار نطاق واستضافة متروك لك)، هذا الـ PWA نفسه
قابل للتثبيت على أندرويد من المتصفح مباشرة (بلا أي كود إضافي) — خطوة
Capacitor/Google Play (25$ لمرة واحدة) اختيارية ولاحقة فقط لو احتجت نشرًا
رسميًا على المتجر.

## النشر العام المجاني (Fly.io + Cloudflare Pages)

القرار المتخذ: **Fly.io** للباك-إند الحي (يعمل 24/7 على سحابتهم — جهازك لا
يحتاج يبقى مفتوحًا) و**Cloudflare Pages** للواجهة الثابتة (CDN عالمي مجاني).

### أ) الباك-إند على Fly.io

1. ثبّت `flyctl` (مرة واحدة فقط): [fly.io/docs/flyctl/install](https://fly.io/docs/flyctl/install/)
   على ويندوز عبر PowerShell:

   ```powershell
   pwsh -Command "iwr https://fly.io/install.ps1 -useb | iex"
   ```

2. سجّل/ادخل: `fly auth signup` (أو `fly auth login` لو عندك حساب). **Fly.io
   يطلب بطاقة ائتمانية للتحقق حتى ضمن الحد المجاني** (بلا محاولة تحاسب طالما
   بقيت ضمنه) — أضفها من لوحة تحكم الحساب لو ظهر لك خطأ
   `requested machine count exceeds organization limit` عند `fly launch`.
3. **مهم:** `fly.toml` موجود في **جذر المستودع** (`Saira-Trading/fly.toml`)
   وليس داخل `saira-api/` — لأن `dockerfile` بداخله يشير لـ
   `saira-api/Dockerfile` بينما سياق البناء (build context) لازم يكون جذر
   المستودع كله (`Dockerfile` يحتاج `src/` و`data/` بجانب `saira-api/`).
   نفّذ من جذر المستودع مباشرة، بلا أي `--config`/`--dockerfile` إضافية:

   ```powershell
   cd C:\Users\Mahdy\Saira-Trading
   fly launch --no-deploy
   ```

   وافق على اسم التطبيق (أو اتركه `saira-api` كما في `fly.toml`) وعلى المنطقة، وارفض
   إنشاء أي قاعدة بيانات/Redis إضافية يقترحها (غير مطلوبة هنا).
4. انشر فعليًا:

   ```powershell
   fly deploy
   ```

5. تأكد أنه يعمل: `fly status` ثم افتح `https://<اسم-تطبيقك>.fly.dev/health`
   في المتصفح — يجب أن يظهر `{"ok":true,...}`.
6. لو اسم التطبيق مختلف عن `saira-api`، حدّث `DEFAULT_REMOTE_API` في
   `saira-terminal.html` (بحث عن `fly.dev`) بعنوانك الفعلي قبل نشر الواجهة.

**ملاحظة الخطة المجانية:** Fly.io يوقف الآلة تلقائيًا بلا طلبات (`auto_stop_machines`)
ويعيد تشغيلها عند أول طلب جديد (`auto_start_machines`) — أول طلب بعد فترة خمول
قد يستغرق بضع ثوانٍ إضافية، وهذا طبيعي وليس عطلًا.

**بديل بلا بطاقة ائتمانية إطلاقًا:** `render.yaml` في جذر المستودع جاهز
لنفس النشر على [Render](https://render.com) (خطة Free، بلا أي بطاقة) — الوحيد
اللي يفرق إن أول طلب بعد 15 دقيقة خمول ياخد ~30-60 ثانية ليستيقظ. من
Render Dashboard: **New** → **Blueprint** → اختر مستودع `saira-trading` —
هيقرأ `render.yaml` تلقائيًا.

### ب) الواجهة على Cloudflare Pages

1. ادفع المستودع لو لسه مش مدفوع: `git push`.
2. من [dash.cloudflare.com](https://dash.cloudflare.com) → **Workers & Pages**
   → **Create application** → لو فتحت صفحة "Create a Worker" (الافتراضي
   الجديد)، دوّر تحت الصفحة على رابط **"Looking to deploy Pages? Get
   started"** واضغطه — **لا تكمل من مسار Worker العادي**، لازم Pages تحديدًا
   (Worker بيحتاج `wrangler deploy` ومش مناسب لموقع ثابت).
3. من شاشة "Get started" اختار **"Import an existing Git repository"** →
   **Get started** → اختر مستودع `saira-trading` → **Begin setup**.
4. إعدادات البناء:
   - **Production branch:** `main`
   - **Framework preset:** `None`
   - **Build command:** `npm install --omit=dev && npm run sync-web`
   - **Build output directory:** `web`
   - **Root directory (Path)** (تحت "Root directory (advanced)"): `saira-api`
5. اضغط **Save and Deploy** — كلاودفلير هيدّيك رابط `https://<اسم>.pages.dev`
   يعمل فورًا، ويعيد النشر تلقائيًا مع كل `git push` جديد.
6. (اختياري) دومين مخصص لاحقًا من نفس لوحة المشروع → **Custom domains**.

**ملاحظة مهمة:** Cloudflare Pages يشغّل `npm ci` تلقائيًا **قبل** أمر البناء
المذكور أعلاه — لازم `saira-api/package-lock.json` متزامن تمامًا مع
`package.json` (شغّل `npm install` محليًا فيه بعد أي تعديل على devDependencies
وارفع الملفين معًا)، وإلا يفشل البناء برسالة
`npm ci can only install packages when your package.json and package-lock.json ... are in sync`.

بعد الخطوتين، الموقع بيشتغل بالكامل من أي جهاز/متصفح بدون تشغيل أي حاجة على
جهازك — الواجهة على Cloudflare والباك-إند على Fly.io، وكلاهما مجاني ويعمل 24/7.

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
├─ manifest.webmanifest             ← المرحلة 5: PWA (تثبيت من المتصفح)
├─ service-worker.js                ← يخزّن الصدفة الثابتة فقط، لا بيانات API
├─ icons/                           ← أيقونات PWA (32/128/256/512)
├─ app/
│  ├─ main.py                       ← نقاط النهاية
│  ├─ config.py                     ← المسارات (متغيرات بيئة)
│  ├─ aggregator.py                 ← المرحلة 4: مُجمِّع Alpaca WebSocket → شموع 30 ثانية
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
