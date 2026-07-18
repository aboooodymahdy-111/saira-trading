"""إعدادات Saira API — كل المسارات قابلة للتغيير عبر متغيرات البيئة."""
import os
from pathlib import Path

# جذر المشروع: saira-api يعيش الآن داخل Saira-Trading نفسه، لكن committee_signals.py
# وباقي أدوات جان الحقيقية موجودة تحت src/ وليس الجذر مباشرة.
API_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = Path(os.getenv("SAIRA_ROOT", API_ROOT.parent / "src"))

# مجلد بيانات Stooq الحقيقي (نفس LOCAL_MARKET_DATA_DIR في full_universe_analysis.py) —
# ملفات .us.txt مبعثرة داخل مجلدات فرعية بالبورصة (nasdaq stocks / nyse stocks)، وليست
# ملفات مسطّحة في مجلد واحد كما افترض النموذج الأولي.
DATA_DIR = Path(os.getenv("SAIRA_DATA", r"D:\EGX.Daily.2000-2023\data\daily\data\daily\us"))
DATA_SUBFOLDERS = ("nasdaq stocks", "nyse stocks")

# قاعدة DuckDB للشموع التاريخية
DB_PATH = Path(os.getenv("SAIRA_DB", API_ROOT / "saira.duckdb"))

# قائمة الرموز الكاملة الممسوحة (data/ticker_universe.csv الحقيقية — 6000+ رمز NASDAQ/NYSE،
# نفس ما يقرأه full_universe_analysis.load_ticker_universe()). تنبيه هام: هذه قائمة
# التغطية فقط، وليست الفلترة الأخلاقية — الفلترة الأخلاقية الحقيقية (ethical_screen.py)
# ديناميكية (فحص قطاع كل شركة + قائمة استبعاد مقاطعة عبر yfinance لكل رمز على حدة)
# ولا يمكن اختزالها في ملف ثابت هنا. حتى تُدمج هذه الفلترة في /symbols، أي رمز يظهر
# "allowed: true" هنا يعني فقط أنه ضمن الكون الممسوح، لا أنه اجتاز الفلتر الأخلاقي.
ALLOWLIST_PATH = Path(os.getenv("SAIRA_ALLOWLIST", API_ROOT.parent / "data" / "ticker_universe.csv"))

# كاش الأهلية الأخلاقية الحقيقي (مُحسوَب سلفًا بواسطة full_universe_analysis.py
# اليومي — فحص قطاع فعلي عبر yfinance + استبعاد بنوك/دفاع/BDS، وليس مجرد
# قائمة تغطية). استيراد Stooq الافتراضي (بلا all_symbols=true أو symbols=
# صريح) يستخدم هذا الكاش تحديدًا (status=="eligible" فقط) بدل ALLOWLIST_PATH
# الخام — راجع 2026-07: كان الاستيراد الافتراضي يجلب كل كون التغطية (6000+
# رمز) بلا أي فلترة أخلاقية فعلية، رغم وجود الفحص الحقيقي جاهزًا في هذا الملف.
ELIGIBILITY_CACHE_PATH = Path(os.getenv("SAIRA_ELIGIBILITY_CACHE",
                                        API_ROOT.parent / "runs" / "ticker_eligibility_cache.json"))

# كاش تواريخ أول تداول (لا تأسيس الشركة) لكل رمز — يتراكم تدريجيًا في هذا
# الملف مع كل استدعاء لـ /first_trade جديد، فيقلّل الاعتماد المتكرر على
# yfinance لنفس الرمز (استعلام .info بطيء نسبيًا، ~1-2 ثانية لكل رمز).
FIRST_TRADE_CACHE_PATH = Path(os.getenv("SAIRA_FIRST_TRADE_CACHE",
                                        API_ROOT.parent / "runs" / "first_trade_cache.json"))

HOST = os.getenv("SAIRA_HOST", "127.0.0.1")
PORT = int(os.getenv("SAIRA_PORT", "8787"))

# المرحلة 4: مُجمِّع Alpaca WebSocket (خطة Basic المجانية — تغذية IEX، لا تتطلب
# تمويل حساب). المفاتيح فارغة افتراضيًا بالتصميم — aggregator.py يرفض العمل
# صراحة لو غير موجودة بدل محاولة اتصال هيفشل بصمت أو بخطأ مبهم.
ALPACA_KEY_ID = os.getenv("ALPACA_KEY_ID", "")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")
ALPACA_FEED = os.getenv("ALPACA_FEED", "iex")  # iex = مجاني على الخطة الأساسية؛ sip يتطلب اشتراك مدفوع
ALPACA_STREAM_URL = f"wss://stream.data.alpaca.markets/v2/{ALPACA_FEED}"


def load_allowlist() -> set[str]:
    if not ALLOWLIST_PATH.exists():
        return set()
    return {
        line.strip().upper()
        for line in ALLOWLIST_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#") and line.strip().upper() != "TICKER"
    }


def load_eligible_tickers() -> set[str] | None:
    """رموز اجتازت الفلتر الأخلاقي الحقيقي فعليًا (status=="eligible" في
    كاش full_universe_analysis.py) — None لو الكاش غير موجود بعد (لم يُشغَّل
    full_universe_analysis.py على هذا الجهاز ولو مرة)، ليتعامل المستدعي مع
    غياب الفلترة صراحة بدل الرجوع الصامت لكل كون التغطية غير المفلتر."""
    import json
    if not ELIGIBILITY_CACHE_PATH.exists():
        return None
    try:
        cache = json.loads(ELIGIBILITY_CACHE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return {t.upper() for t, entry in cache.items() if entry.get("status") == "eligible"}


def load_first_trade_cache() -> dict[str, int]:
    """{symbol: epoch_seconds} — فارغ لو الملف غير موجود بعد أو تالف."""
    import json
    if not FIRST_TRADE_CACHE_PATH.exists():
        return {}
    try:
        return json.loads(FIRST_TRADE_CACHE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_first_trade(symbol: str, epoch_seconds: int) -> None:
    """يضيف/يحدّث رمزًا واحدًا في الكاش ويحفظه — عملية قراءة-تعديل-كتابة
    بسيطة (الملف صغير، لا حاجة لقفل ملفات عبر عمليات متعددة هنا)."""
    import json
    cache = load_first_trade_cache()
    cache[symbol.upper()] = int(epoch_seconds)
    FIRST_TRADE_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    FIRST_TRADE_CACHE_PATH.write_text(
        json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
