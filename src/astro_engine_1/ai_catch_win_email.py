"""
astro_engine_1/ai_catch_win_email.py — يبني ملخّص HTML بسيط من نتيجة
ai_catch_win.py (ai_catch_win_latest.csv) لإرساله بالإيميل عبر Resend —
راجع .github/workflows/ai-catch-win.yml. جدول واحد: أعلى 15 سهم بربح معايَر
موثوق (direction_accuracy >= DIRECTION_TRUST_THRESHOLD)، مع خطة الصفقة
(دخول/وقف/T1-T3) لكل واحد.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, ".")

RESULTS_CSV = Path("../runs/astro_engine_1/ai_catch_win_latest.csv")
OUTPUT_HTML = Path("../runs/astro_engine_1/ai_catch_win_email.html")

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
        للمراجعة اليدوية فقط — لا تنفيذ آلي لأي صفقة. الملف الكامل في الريبو
        (runs/astro_engine_1/ai_catch_win_latest.csv).
      </p>
    </div>
    """


if __name__ == "__main__":
    html = build_html()
    OUTPUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_HTML.write_text(html, encoding="utf-8")
    print(f"Wrote email HTML -> {OUTPUT_HTML.resolve()}")
