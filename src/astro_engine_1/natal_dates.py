"""
astro_engine_1/natal_dates.py — قاعدة بيانات تواريخ الميلاد الحقيقية للأسهم
(natal dates)، منفصلة تمامًا عن أي تقريب من ملفات الأرشيف المحلي.

**لماذا هذا الملف ضروري (2026-07-18، بتوجيه عبده الصريح)**: النظام بأكمله مبني
على فرضية "السهم/الكيان يحمل بصمة لحظة ولادته الكونية (screenshot)، وكل التفاعل
اللاحق يُقاس نسبة لتلك اللحظة" — دقة تلك اللحظة نفسها هي **ركن الاختبار
الأول**، لا تفصيلاً هامشيًا. فحص فعلي (2026-07-18) على 2000 سهم عشوائي من
الفهرس المحلي (`build_local_ticker_index`) كشف أن:
  - 17.3% من الأسهم (344/1992) لها نفس "أول تاريخ متوفر محليًا" بالضبط:
    2005-02-25 — حد أرشيف تقني لمزوّد البيانات، لا تاريخ IPO حقيقي.
  - 0.4% أخرى لها 1970-01-02 — نفس الظاهرة، حد أرشيف تقني مختلف.
  - عشرات التواريخ الأخرى تتكرر بمعدلات أقل لكن مريبة (0.3-0.6%).

كان `planet_isolation._natal_ascendant_for_ticker` (قبل هذا الملف) يأخذ ببساطة
`hist.index[0].date()` من البيانات المحلية كـ"تاريخ ميلاد" — ما يعني أن عشرات
الشركات المختلفة تمامًا (IBM، XOM، PG، CAT، MMM، JNJ، MRK...) كانت تُحسَب لها
نفس الطالع تقريبًا لأنها "وُلدت" جميعًا في نفس اللحظة الوهمية. أي نتيجة مبنية
على هذا التقريب **لا قيمة فلكية لها إطلاقًا** — لا نقيس خريطة ميلاد السهم
الحقيقية، بل خريطة ميلاد تاريخ أرشيف عشوائي.

**المصدر الوحيد الموثوق لتاريخ الميلاد هنا**: `firstTradeDateMilliseconds` من
yfinance's `.info` — نفس الحقل المستخدم فعليًا في `saira-api/app/main.py`
(`/first_trade/{symbol}` endpoint، commit 94e49de) — أول يوم تداول فعلي لهذا
الرمز تحديدًا (يبقى صحيحًا عبر الاندماج/الانفصال/إعادة الإدراج)، لا تاريخ
تأسيس الشركة ولا حد أرشيف بيانات محلي. يُعاد استخدام **نفس ملف الكاش**
(`runs/first_trade_cache.json`، بنفس الصيغة {symbol: epoch_seconds}) بدل بناء
كاش مواز — مصدر حقيقة واحد للمشروع كله، سواء استُدعي من الواجهة (saira-api)
أو من هذه الحزمة التجريبية.

**fail loud، لا تسامح صامت**: `get_natal_date` ترفع `NatalDateUnavailable`
صراحةً لو تعذّر جلب تاريخ حقيقي (بدل الرجوع الصامت لتاريخ الأرشيف المحلي) —
أي سهم بلا تاريخ ميلاد موثوق **يُستبعد من التحليل**، لا يُحسب بتاريخ تقريبي.

**اكتشاف حرج ثانٍ (2026-07-18، بعد بناء هذا الملف مباشرة)**: حتى
`firstTradeDateMilliseconds` من yfinance نفسه — رغم كونه "المصدر الموثوق"
المُعتمَد فوق — له **نفس عيب حدود الأرشيف** لأسهم قديمة بما يكفي: تحقق فعلي
مباشر أظهر IBM وXOM وGE وKO (شركات مختلفة تمامًا، تواريخ تأسيس/إدراج حقيقية
مختلفة تمامًا) **تُرجع القيمة نفسها بالضبط**
(-252322200000ms = 1962-01-02) — وهذا حد بداية أرشيف Yahoo الرقمي لبيانات
NYSE، لا تاريخ إدراج فعلي لهذه الشركات (المُدرَجة فعليًا قبل ذلك بعقود).
`is_suspicious_natal_date` تحت تكتشف هذا النمط عبر فحص التكرار على دفعة من
الأسهم قبل الوثوق بأي تاريخ فردي.

**فجوة معروفة مسجَّلة (لم تُحَل بعد)**: لا يوجد حاليًا مصدر مجاني موثوق
لتاريخ الإدراج الفعلي للأسهم الأقدم من ~1962 (حد أرشيف كل من البيانات
المحلية وyfinance معًا) — قرار عبده الصريح: استبعاد هذه الأسهم بالكامل من أي
عيّنة اختبار حاليًا (`filter_suspicious_natal_dates` تحت)، بدل تقريبها. حل
مستقبلي محتمل غير مُنفَّذ: Wikipedia infobox (حقل "Traded as" غالبًا يذكر
تاريخ الإدراج) أو SEC EDGAR (نموذج S-1/424B الأصلي) لكل شركة قديمة على حدة —
يتطلب جلبًا يدويًا/شبه-يدوي لكل رمز، لا API واحد شامل معروف حتى الآن.
"""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, ".")

from yf_retry import call_with_retry

FIRST_TRADE_CACHE_PATH = Path("../runs/first_trade_cache.json")

_EPOCH = date(1970, 1, 1)


def _epoch_seconds_to_date(epoch_seconds: int) -> date:
    """
    تحويل epoch يدوي (بدل datetime.fromtimestamp) — Windows يرفض
    fromtimestamp لقيم سالبة (تواريخ قبل 1970)، وهذا شائع هنا: أسهم مُدرَجة
    قبل 1970 (IBM مثلاً) لها firstTradeDateMilliseconds سالب فعليًا. الجمع
    اليدوي على date(1970,1,1) يعمل مع القيم السالبة والموجبة معًا بلا فرق.
    """
    return _EPOCH + timedelta(seconds=epoch_seconds)


class NatalDateUnavailable(Exception):
    """يُرفع صراحة لو تعذّر الحصول على تاريخ ميلاد حقيقي (لا تقريب صامت)."""


def _load_cache() -> dict[str, int]:
    if not FIRST_TRADE_CACHE_PATH.exists():
        return {}
    try:
        return json.loads(FIRST_TRADE_CACHE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_cache_entry(ticker: str, epoch_seconds: int) -> None:
    cache = _load_cache()
    cache[ticker.upper()] = int(epoch_seconds)
    FIRST_TRADE_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    FIRST_TRADE_CACHE_PATH.write_text(
        json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")


def get_natal_date(ticker: str) -> date:
    """
    تاريخ الميلاد الحقيقي (أول يوم تداول فعلي) لـ`ticker` — عبر الكاش
    المشترك أولاً، وإلا نداء yfinance (بإعادة المحاولة عبر yf_retry، نفس
    سياسة المشروع لأي نداء yfinance جديد).

    يرفع NatalDateUnavailable صراحة لو: (أ) فشل النداء لسبب غير rate-limit
    (سهم غير موجود على yfinance)، أو (ب) نجح النداء لكن الحقل
    firstTradeDateMilliseconds غائب (بعض الرموز القديمة/المُدرجة عبر مسارات
    غير قياسية لا يوفره yfinance لها) — لا حالة ثالثة صامتة.
    """
    ticker_upper = ticker.upper()
    cache = _load_cache()
    if ticker_upper in cache:
        return _epoch_seconds_to_date(cache[ticker_upper])

    try:
        import yfinance as yf
    except ImportError as exc:
        raise NatalDateUnavailable(f"{ticker}: yfinance غير مثبّت") from exc

    try:
        info = call_with_retry(lambda: yf.Ticker(ticker_upper).info)
    except Exception as exc:  # noqa: BLE001 - يُلَفّ في استثناء صريح موحّد
        raise NatalDateUnavailable(f"{ticker}: فشل جلب yfinance .info ({exc})") from exc

    ms = info.get("firstTradeDateMilliseconds")
    if ms is None:
        raise NatalDateUnavailable(f"{ticker}: firstTradeDateMilliseconds غير متوفر عبر yfinance")

    epoch_seconds = int(ms // 1000)
    _save_cache_entry(ticker_upper, epoch_seconds)
    return _epoch_seconds_to_date(epoch_seconds)


# عتبة اكتشاف "حد أرشيف" مشبوه: أي تاريخ ميلاد يتكرر بالضبط عند 3+ أسهم أو
# أكثر ضمن نفس الدفعة يُعتبر مشبوهًا — شركات حقيقية مختلفة تمامًا لا يُفترض
# أن "تُولد" (تُدرَج) في نفس اليوم بالضبط إلا بالمصادفة النادرة جدًا؛ 3+
# تكرارات في دفعة صغيرة (عشرات لا آلاف الأسهم) يتجاوز أي مصادفة معقولة.
SUSPICIOUS_REPEAT_THRESHOLD = 3


def filter_suspicious_natal_dates(tickers: list[str]) -> tuple[dict[str, date], dict[str, str]]:
    """
    يجلب تاريخ الميلاد الحقيقي لكل تيكر في `tickers`، ثم يستبعد أي تاريخ
    يتكرر بالضبط SUSPICIOUS_REPEAT_THRESHOLD مرة أو أكثر (حد أرشيف تقني، لا
    IPO حقيقي متزامن) — راجع docstring الملف: هذا يحدث فعليًا حتى مع
    firstTradeDateMilliseconds من yfinance نفسه لأسهم أقدم من ~1962.

    يرجّع (clean, excluded): clean = {ticker: natal_date} للأسهم ذات تاريخ
    موثوق فرديًا، excluded = {ticker: سبب الاستبعاد} لكل ما استُبعد (تاريخ
    مشبوه أو NatalDateUnavailable) — لا استبعاد صامت، السبب دائمًا مسجَّل.
    """
    from collections import Counter

    raw: dict[str, date] = {}
    excluded: dict[str, str] = {}
    for t in tickers:
        try:
            raw[t] = get_natal_date(t)
        except NatalDateUnavailable as exc:
            excluded[t] = str(exc)

    date_counts = Counter(raw.values())
    clean: dict[str, date] = {}
    for t, d in raw.items():
        if date_counts[d] >= SUSPICIOUS_REPEAT_THRESHOLD:
            excluded[t] = (f"تاريخ ميلاد مشبوه ({d}) — يتكرر عند {date_counts[d]} "
                            f"أسهم مختلفة في نفس الدفعة، على الأرجح حد أرشيف تقني لا IPO حقيقي")
        else:
            clean[t] = d

    return clean, excluded


if __name__ == "__main__":
    for t in (sys.argv[1:] or ["AAPL", "IBM", "XOM"]):
        try:
            d = get_natal_date(t)
            print(f"{t}: {d}")
        except NatalDateUnavailable as exc:
            print(f"{t}: UNAVAILABLE — {exc}")
