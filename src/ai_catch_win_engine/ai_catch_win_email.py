"""
ai_catch_win_engine/ai_catch_win_email.py — يبني ملخّص HTML بسيط (أعلى 15 سهم،
داخل الإيميل نفسه) + ملف Excel كامل (كل الـ200 سهم، مرفَق) من نتيجة
ai_catch_win.py (ai_catch_win_latest.csv) — راجع .github/workflows/
ai-catch-win.yml. الأرشيف: نسخة بتاريخ التشغيلة تُحفَظ في
runs/ai_catch_win_engine/archive/ (طلب عبده 2026-07-18: "نحتفظ بأرشيف في مكان ما
زي ما عملنا في التقرير اليومي الآخر") — نفس مبدأ full_universe_analysis.py's
ARCHIVE_DIR بالضبط، مجلد منفصل هنا فقط لعدم الخلط مع أرشيف التقرير القديم.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

RESULTS_CSV = Path("../runs/ai_catch_win_engine/ai_catch_win_latest.csv")
OUTPUT_HTML = Path("../runs/ai_catch_win_engine/ai_catch_win_email.html")
OUTPUT_XLSX = Path("../runs/ai_catch_win_engine/ai_catch_win_latest.xlsx")
ARCHIVE_DIR = Path("../runs/ai_catch_win_engine/archive")

DIRECTION_TRUST_THRESHOLD = 55.0

# نفس الـ10 أعمدة المعروضة في جدول الإيميل بالظبط — طلب عبده صريح 2026-07-21:
# "مش حابب اخلص المساحة المتاحة على GitHub" + "التقرير بيبعت تفاصيل ما تهمنيش"
# — الملف الكامل (كل الـ36 عمود من ai_catch_win_latest.csv) كان بيتكرر في كل
# صف من الـ200 سهم × الأرشيف اليومي، بلا داعي. Excel المرفَق والأرشيف دلوقتي
# بنفس أعمدة HTML بالضبط، لا أكتر.
REPORT_COLUMNS = ["ticker", "current_price", "h1_calibrated_pct_change", "h1_direction_accuracy",
                   "entry_price", "stop_loss_price", "ai_t_price", "t1_price",
                   "t2_price", "target3_plus_price"]


def _fmt(value) -> str:
    if pd.isna(value):
        return None
    return f"{value:g}"


def _fmt_dollar(value) -> str:
    formatted = _fmt(value)
    return "—" if formatted is None else f"${formatted}"


def build_html(top_n: int = 15) -> str:
    if not RESULTS_CSV.exists():
        return "<p>لا توجد نتائج AI Catch & Win بعد.</p>"

    df = pd.read_csv(RESULTS_CSV)
    trusted = df[df["h1_direction_accuracy"] >= DIRECTION_TRUST_THRESHOLD].copy()
    trusted = trusted.sort_values("h1_calibrated_pct_change", ascending=False).head(top_n)

    rows_html = []
    for _, r in trusted.iterrows():
        pct_change = _fmt(r.get("h1_calibrated_pct_change"))
        direction_acc = _fmt(r.get("h1_direction_accuracy"))
        rows_html.append(f"""
        <tr>
          <td><b>{r['ticker']}</b></td>
          <td>{_fmt_dollar(r.get('current_price'))}</td>
          <td>{pct_change if pct_change is not None else '—'}%</td>
          <td>{direction_acc if direction_acc is not None else '—'}%</td>
          <td>{_fmt_dollar(r.get('entry_price'))}</td>
          <td>{_fmt_dollar(r.get('stop_loss_price'))}</td>
          <td>{_fmt_dollar(r.get('ai_t_price'))}</td>
          <td>{_fmt_dollar(r.get('t1_price'))}</td>
          <td>{_fmt_dollar(r.get('t2_price'))}</td>
          <td>{_fmt_dollar(r.get('target3_plus_price'))}</td>
        </tr>""")

    table_rows = "".join(rows_html) if rows_html else "<tr><td colspan='10'>لا إشارات بثقة كافية اليوم.</td></tr>"

    return f"""
    <div style="font-family: Arial, sans-serif;">
      <h2>AI Catch & Win — أعلى الفرص اليوم</h2>
      <table border="1" cellpadding="6" cellspacing="0" style="border-collapse: collapse; font-size: 13px;">
        <tr style="background:#f0f0f0;">
          <th>السهم</th><th>السعر الحالي</th><th>ربح AI معايَر</th><th>ثقة الاتجاه</th>
          <th>دخول</th><th>وقف خسارة</th><th>AI T</th><th>T1</th><th>T2</th><th>ممتد</th>
        </tr>
        {table_rows}
      </table>
      <p style="color:#888; font-size:12px;">
        للمراجعة اليدوية فقط — لا تنفيذ آلي لأي صفقة. الملف الكامل (كل
        الأسهم) مرفَق في هذا الإيميل كـExcel، ومحفوظ في أرشيف الريبو أيضًا.
      </p>
    </div>
    """


def build_excel() -> Path:
    """
    ملف Excel لكل الـ200 سهم (لا أعلى 15 بس زي HTML الإيميل) — طلب عبده
    2026-07-18: "لو حبيت أدور على توقع بخصوص سهم" — بحث/فلترة سهلة في Excel
    عادي بدل الرجوع لملف CSV خام. يُكتَب كنسخة "أحدث" + نسخة أرشيفية بالتاريخ.

    **الأعمدة (تحديث 2026-07-21)**: نفس REPORT_COLUMNS بالظبط (10 أعمدة، مطابقة
    لجدول HTML) — لا كل الـ36 عمود الخام. طلب عبده الصريح: تفاصيل زيادة
    (RMSE-جانبية، أعمدة h5/h10/h20 غير المستخدَمة في القرار، إلخ) "ما تهمنيش"،
    وبيضخّم حجم الأرشيف اليومي على GitHub بلا داعي حقيقي.
    """
    if not RESULTS_CSV.exists():
        raise FileNotFoundError(f"{RESULTS_CSV} غير موجود — شغّل ai_catch_win.py أولاً.")

    df = pd.read_csv(RESULTS_CSV)
    df = df.sort_values("h1_calibrated_pct_change", ascending=False, na_position="last")
    df = df[[c for c in REPORT_COLUMNS if c in df.columns]]

    OUTPUT_XLSX.parent.mkdir(parents=True, exist_ok=True)
    _write_excel_with_autofilter(df, OUTPUT_XLSX)

    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    archive_path = ARCHIVE_DIR / f"ai_catch_win_{date.today().isoformat()}.xlsx"
    _write_excel_with_autofilter(df, archive_path)

    return OUTPUT_XLSX


def _write_excel_with_autofilter(df: pd.DataFrame, path: Path) -> None:
    """
    نفس df.to_excel العادي، لكن بإضافة AutoFilter (قوائم الفلترة/الفرز
    المدمجة في Excel نفسه على كل عمود) — طلب عبده 2026-07-22: الصفوف بعد أي
    فلترة يدوية في Excel كانت بتحافظ على ترتيبها الأصلي في الملف (الربح
    تنازليًا، مضمون من sort_values فوق) لكن من غير أزرار فلترة/فرز جاهزة،
    فالمستخدم كان مضطر يفتح "تصفية تلقائية مخصصة" يدويًا في كل مرة. AutoFilter
    الرسمي بيدّي نفس القوائم المنسدلة القياسية (فرز تصاعدي/تنازلي + فلترة)
    اللي أي مستخدم Excel متعوّد عليها، من غير ما يغيّر ترتيب الصفوف نفسه فعليًا
    (يفضل الربح تنازليًا زي ما هو، الفلتر/الفرز اللي يطبّقه المستخدم لاحقًا
    فوقه اختياري).
    """
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="AI Catch & Win")
        worksheet = writer.sheets["AI Catch & Win"]
        worksheet.auto_filter.ref = worksheet.dimensions


if __name__ == "__main__":
    html = build_html()
    OUTPUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_HTML.write_text(html, encoding="utf-8")
    print(f"Wrote email HTML -> {OUTPUT_HTML.resolve()}")

    xlsx_path = build_excel()
    print(f"Wrote Excel report -> {xlsx_path.resolve()}")
