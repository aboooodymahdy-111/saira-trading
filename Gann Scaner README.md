# Gann Penny Stock Scanner - دليل التشغيل الكامل

نظام سكانر يفحص أسهم البيني ستوكس كل 5 دقايق خلال أوقات التداول الأمريكية
(بريما ركت + الجلسة الرسمية)، وبيبعت تنبيه تيليجرام لأي سهم عليه توافق قوي
بين الكواكب / مربع التسعة / فيبوناتشي / الفوليوم / الأخبار.

---

## الخطوة 1: عمل بوت تيليجرام

1. افتح تيليجرام وابحث عن `@BotFather` (البوت الرسمي، هتلاقيه بعلامة ✔️ زرقاء).
2. ابعتله `/newbot` واتبع التعليمات (اسم البوت + username ينتهي بـ `bot`).
3. هيديك **Token** شكله: `123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ` — احفظه.
4. ابعت أي رسالة للبوت اللي عملته (مثلاً "hi").
5. افتح في المتصفح (حط التوكن بتاعك):
   `https://api.telegram.org/bot<TOKEN>/getUpdates`
6. هتلاقي `"chat":{"id": 123456789}` — الرقم ده هو الـ Chat ID بتاعك.

---

## الخطوة 2: رفع المشروع على GitHub

1. اعمل حساب على [github.com](https://github.com) لو مفيش عندك.
2. اعمل Repository جديد (خليه **Private** عشان قائمة أسهمك تفضل خاصة).
3. ارفع الملفات دي بالظبط بنفس الهيكل:
   ```
   your-repo/
   ├── gann_penny_scanner.py
   └── .github/
       └── workflows/
           └── scanner.yml
   ```

---

## الخطوة 3: ضبط الـ Secrets (بيانات سرية آمنة)

1. جوه الـ Repository: **Settings** → **Secrets and variables** → **Actions**.
2. دوس **New repository secret** واضف:
   - `TELEGRAM_BOT_TOKEN` = التوكن اللي أخدته من BotFather
   - `TELEGRAM_CHAT_ID` = رقم الشات بتاعك

هيك الكود مش هيحتاج تكتب التوكن جوه الملف نفسه أبداً - ده أأمن طريقة.

---

## الخطوة 4: التشغيل

- الملف `.github/workflows/scanner.yml` هيخلي GitHub يشغل السكانر تلقائياً
  **كل 5 دقايق** طول اليوم. الكود نفسه بيتأكد جوه إننا فعلاً في أوقات
  التداول الأمريكية (بريما ركت + الجلسة الرسمية) وبيتخطى أي تشغيل خارج
  الفترة دي بدون ما يبعت أي تنبيه أو يستهلك حصتك المجانية بلا داعي.
- تقدر كمان تشغله يدوياً فوراً للتجربة: من تبويب **Actions** في الريبو
  اختار **Gann Penny Stock Scanner** ثم **Run workflow**.

---

## تخصيص قائمة الأسهم

في نهاية ملف `gann_penny_scanner.py`:

```python
penny_watchlist = ["SIRI", "NOK", "SNDL", "GEVO", "CTRM", "MULN", "NKLA"]
```

غيّرها لأي قائمة أسهم بيني ستوكس تحب تراقبها.

---

## مهم جداً: حساب درجات الكواكب الحقيقية (الإفميرس)

الكود حالياً فيه:

```python
PLANETS_LONGITUDES = {
    "Sun": 0.0,
    "Moon": 0.0,
    ...
}
```

القيم دي **Placeholder** بس - لازم تتحدث بدرجات الكواكب الفلكية الحقيقية
في نفس لحظة التشغيل. عندك خيارين:

### الخيار أ (موصى به): مكتبة `pyswisseph`
```bash
pip install pyswisseph
```
```python
import swisseph as swe
from datetime import datetime, timezone

def get_planet_longitudes():
    now = datetime.now(timezone.utc)
    jd = swe.julday(now.year, now.month, now.day, now.hour + now.minute/60)
    planets = {
        "Sun": swe.SUN, "Moon": swe.MOON, "Mercury": swe.MERCURY,
        "Venus": swe.VENUS, "Mars": swe.MARS, "Jupiter": swe.JUPITER,
        "Saturn": swe.SATURN,
    }
    result = {}
    for name, code in planets.items():
        pos, _ = swe.calc_ut(jd, code)
        result[name] = pos[0]  # الدرجة الطولية (0-360)
    return result
```
بعدين في `run_scan_once` حط:
```python
planets = get_planet_longitudes()
```
بدل الـ `PLANETS_LONGITUDES` الثابتة.

### الخيار ب: أي API فلكي خارجي بترجعلك الدرجات وتحطها في نفس الفورمات.

---

## تعديل الحساسية

كل الإعدادات في `CONFIG` أعلى الملف:

| الإعداد | الوظيفة | القيمة الافتراضية |
|---|---|---|
| `tolerance_pct` | هامش خطأ التوافق بين المستويات | 1.5% |
| `volume_spike_ratio` | كام ضعف الفوليوم المطلوب | x3 |
| `min_breakout_pct` | أقل نسبة طفرة سعرية تتحسب | 50% |
| `breakout_lookback_days` | المدى الزمني لقياس الطفرة | 5 أيام |

في `run_scan_once`:
```python
min_votes_to_alert = 2
```
ده أقل عدد أصوات عشان يتبعت تنبيه - قلله لو عايز حساسية أعلى، زوّده لو عايز
تنبيهات أقل وأقوى بس.
