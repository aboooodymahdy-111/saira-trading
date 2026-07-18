"""
astro_engine_1/ai_catch_win_email.py — يبني ملخّص HTML بسيط (أعلى 15 سهم،
داخل الإيميل نفسه) + ملف Excel كامل (كل الـ200 سهم، مرفَق) من نتيجة
ai_catch_win.py (ai_catch_win_latest.csv) — راجع .github/workflows/
ai-catch-win.yml. الأرشيف: نسخة بتاريخ التشغيلة تُحفَظ في
runs/astro_engine_1/archive/ (طلب عبده 2026-07-18: "نحتفظ بأرشيف في مكان ما
زي ما عملنا في التقرير اليومي الآخر") — نفس مبدأ full_universe_analysis.py's
ARCHIVE_DIR بالضبط، مجلد منفصل هنا فقط لعدم الخلط مع أرشيف التقرير القديم.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

RESULTS_CSV = Path("../runs/astro_engine_1/ai_catch_win_latest.csv")
OUTPUT_HTML = Path("../runs/astro_engine_1/ai_catch_win_email.html")
OUTPUT_XLSX = Path("../runs/astro_engine_1/ai_catch_win_latest.xlsx")
ARCHIVE_DIR = Path("../runs/astro_engine_1/archive")

DIRECTION_TRUST_THRESHOLD = 55.0


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
          <td>{_fmt_dollar(r.get('exit_price'))}</td>
          <td>{_fmt_dollar(r.get('target2_price'))}</td>
          <td>{_fmt_dollar(r.get('target3_price'))}</td>
          <td>{_fmt_dollar(r.get('target3_plus_price'))}</td>
        </tr>""")

    table_rows = "".join(rows_html) if rows_html else "<tr><td colspan='10'>لا إشارات بثقة كافية اليوم.</td></tr>"

    return f"""
    <div style="font-family: Arial, sans-serif;">
      <h2>AI Catch & Win — أعلى الفرص اليوم</h2>
      <table border="1" cellpadding="6" cellspacing="0" style="border-collapse: collapse; font-size: 13px;">
        <tr style="background:#f0f0f0;">
          <th>السهم</th><th>السعر الحالي</th><th>ربح AI معايَر</th><th>ثقة الاتجاه</th>
          <th>دخول</th><th>وقف خسارة</th><th>T1</th><th>T2</th><th>T3</th><th>T3+</th>
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
    ملف Excel كامل (كل الـ200 سهم، لا أعلى 15 بس زي HTML الإيميل) — طلب عبده
    2026-07-18: "لو حبيت أدور على توقع بخصوص سهم" — بحث/فلترة سهلة في Excel
    عادي بدل الرجوع لملف CSV خام. يُكتَب كنسخة "أحدث" + نسخة أرشيفية بالتاريخ.
    """
    if not RESULTS_CSV.exists():
        raise FileNotFoundError(f"{RESULTS_CSV} غير موجود — شغّل ai_catch_win.py أولاً.")

    df = pd.read_csv(RESULTS_CSV)
    df = df.sort_values("h1_calibrated_pct_change", ascending=False, na_position="last")

    OUTPUT_XLSX.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(OUTPUT_XLSX, index=False, sheet_name="AI Catch & Win")

    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    archive_path = ARCHIVE_DIR / f"ai_catch_win_{date.today().isoformat()}.xlsx"
    df.to_excel(archive_path, index=False, sheet_name="AI Catch & Win")

    return OUTPUT_XLSX


if __name__ == "__main__":
    html = build_html()
    OUTPUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_HTML.write_text(html, encoding="utf-8")
    print(f"Wrote email HTML -> {OUTPUT_HTML.resolve()}")

    xlsx_path = build_excel()
    print(f"Wrote Excel report -> {xlsx_path.resolve()}")
