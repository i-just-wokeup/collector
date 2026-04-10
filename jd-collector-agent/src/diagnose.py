"""
diagnose.py — Gemini API 호출 없이 raw_captures 폴더를 분석하여
결과를 HTML 리포트로 저장하고 브라우저에서 자동으로 연다.

실행: python src/diagnose.py
"""

import json
import webbrowser
from pathlib import Path

from utils import assess_capture_failed

RAW_CAPTURES_DIR = Path(__file__).parent.parent / "output" / "raw_captures"
REPORT_PATH = Path(__file__).parent.parent / "output" / "diagnose_report.html"

stats = {
    "total": 0,
    "no_png": 0,
    "capture_failed": 0,
    "has_jd_result": 0,
    "unknown": 0,
}

rows: list[dict] = []


def diagnose_folder(folder: Path) -> None:
    stats["total"] += 1

    png_files = sorted(folder.glob("*.png"))
    capture_count = len(png_files)
    jd_result_path = folder / "jd_result.json"

    if capture_count == 0:
        stats["no_png"] += 1
        rows.append({
            "name": folder.name,
            "png_count": capture_count,
            "status": "PNG 없음",
            "status_class": "gray",
            "reasons": "",
        })
        return

    if jd_result_path.exists():
        stats["has_jd_result"] += 1
        try:
            payload = json.loads(jd_result_path.read_text(encoding="utf-8"))
            raw_text = payload.get("raw_text", "") or ""
        except Exception:
            raw_text = ""

        failed, reasons, _ = assess_capture_failed(raw_text, capture_count)
        rows.append({
            "name": folder.name,
            "png_count": capture_count,
            "status": "jd_result 있음",
            "status_class": "green",
            "reasons": ", ".join(reasons) if reasons else "",
        })
        return

    failed, reasons, _ = assess_capture_failed("", capture_count)

    if failed:
        stats["capture_failed"] += 1
        rows.append({
            "name": folder.name,
            "png_count": capture_count,
            "status": "capture_failed",
            "status_class": "red",
            "reasons": ", ".join(reasons),
        })
    else:
        stats["unknown"] += 1
        rows.append({
            "name": folder.name,
            "png_count": capture_count,
            "status": "이유 불명",
            "status_class": "yellow",
            "reasons": ", ".join(reasons) if reasons else "",
        })


def build_html() -> str:
    summary_cards = f"""
    <div class="summary">
      <div class="card">전체<br><span>{stats['total']}</span></div>
      <div class="card gray">PNG 없음<br><span>{stats['no_png']}</span></div>
      <div class="card red">capture_failed<br><span>{stats['capture_failed']}</span></div>
      <div class="card green">jd_result 있음<br><span>{stats['has_jd_result']}</span></div>
      <div class="card yellow">이유 불명<br><span>{stats['unknown']}</span></div>
    </div>
    """

    table_rows = ""
    for row in rows:
        table_rows += (
            f'<tr class="{row["status_class"]}">'
            f'<td>{row["name"]}</td>'
            f'<td>{row["png_count"]}</td>'
            f'<td>{row["status"]}</td>'
            f'<td>{row["reasons"]}</td>'
            f"</tr>\n"
        )

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <title>Diagnose Report</title>
  <style>
    body {{ font-family: sans-serif; padding: 24px; background: #f5f5f5; }}
    h1 {{ margin-bottom: 16px; }}
    .summary {{ display: flex; gap: 12px; margin-bottom: 32px; flex-wrap: wrap; }}
    .card {{
      padding: 16px 24px; border-radius: 8px; background: #e0e0e0;
      font-size: 14px; font-weight: bold; text-align: center; min-width: 100px;
    }}
    .card span {{ display: block; font-size: 28px; margin-top: 4px; }}
    .card.gray  {{ background: #bdbdbd; color: #333; }}
    .card.red   {{ background: #ef9a9a; color: #b71c1c; }}
    .card.green {{ background: #a5d6a7; color: #1b5e20; }}
    .card.yellow{{ background: #fff59d; color: #f57f17; }}
    table {{ width: 100%; border-collapse: collapse; background: #fff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 4px rgba(0,0,0,0.1); }}
    th {{ background: #424242; color: #fff; padding: 10px 14px; text-align: left; font-size: 13px; }}
    td {{ padding: 9px 14px; font-size: 13px; border-bottom: 1px solid #eee; word-break: break-all; }}
    tr.gray   td {{ background: #f5f5f5; color: #616161; }}
    tr.red    td {{ background: #ffebee; color: #b71c1c; }}
    tr.green  td {{ background: #f1f8e9; color: #2e7d32; }}
    tr.yellow td {{ background: #fffde7; color: #f57f17; }}
    tr:hover td  {{ filter: brightness(0.96); }}
  </style>
</head>
<body>
  <h1>Diagnose Report</h1>
  {summary_cards}
  <table>
    <thead>
      <tr>
        <th>폴더명</th>
        <th>PNG 수</th>
        <th>상태</th>
        <th>이유</th>
      </tr>
    </thead>
    <tbody>
      {table_rows}
    </tbody>
  </table>
</body>
</html>"""


def main() -> None:
    if not RAW_CAPTURES_DIR.exists():
        print(f"raw_captures 폴더를 찾을 수 없습니다: {RAW_CAPTURES_DIR}")
        return

    job_folders = sorted(p for p in RAW_CAPTURES_DIR.iterdir() if p.is_dir())

    if not job_folders:
        print("raw_captures 하위에 폴더가 없습니다.")
        return

    for folder in job_folders:
        diagnose_folder(folder)

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(build_html(), encoding="utf-8")

    print(f"[DONE] 리포트 저장: {REPORT_PATH}")
    webbrowser.open(REPORT_PATH.as_uri())


if __name__ == "__main__":
    main()
