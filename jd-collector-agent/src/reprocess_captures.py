"""
output/raw_captures/ 에 이미 캡처된 폴더들을 대상으로
구조화(jd_result.json) → DB 저장까지 재처리하는 스크립트.
"""
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_CAPTURES_DIR = BASE_DIR / "output" / "raw_captures"
DEFAULT_DB_PATH = os.getenv("JD_DB_PATH", r"C:\dev\jd_data.db")
DEFAULT_JD_RESEARCH_TOOL_PATH = os.getenv(
    "JD_RESEARCH_TOOL_PATH", r"C:\dev\jd-research-tool"
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import get_db_connection, save_job_posting, save_job_sections
from runner import generate_jd_json_from_png_folder


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def main() -> None:
    db_path = DEFAULT_DB_PATH
    jd_research_tool_root = Path(DEFAULT_JD_RESEARCH_TOOL_PATH)

    if not jd_research_tool_root.exists():
        print(f"[ERROR] jd-research-tool 경로를 찾을 수 없습니다: {jd_research_tool_root}")
        sys.exit(1)

    capture_dirs = sorted(
        d for d in RAW_CAPTURES_DIR.iterdir() if d.is_dir()
    )
    total = len(capture_dirs)
    print(f"[INFO] 처리할 캡처 폴더 수: {total}")

    conn = get_db_connection(db_path)

    success = 0
    skipped = 0
    failed = 0

    for idx, capture_dir in enumerate(capture_dirs, 1):
        job_id = capture_dir.name
        print(f"\n[{idx}/{total}] job_id={job_id}")

        cur = conn.execute("SELECT 1 FROM job_postings WHERE id = ? LIMIT 1", (job_id,))
        if cur.fetchone():
            print(f"  [SKIP] 이미 DB에 존재")
            skipped += 1
            continue

        json_path = capture_dir / "jd_result.json"
        ocr_input_dir = capture_dir / "ocr_input"

        def _has_images(d: Path) -> bool:
            return d.exists() and any(
                p.suffix.lower() in (".png", ".jpg") for p in d.iterdir()
            )

        if json_path.exists():
            import json
            with json_path.open(encoding="utf-8") as f:
                jd_payload = json.load(f)
            print(f"  [INFO] 기존 jd_result.json 사용")
        else:
            image_folder = ocr_input_dir if _has_images(ocr_input_dir) else capture_dir if _has_images(capture_dir) else None
            if image_folder is None:
                print(f"  [WARN] 이미지 없음, 건너뜀")
                skipped += 1
                continue

            jd_payload = None
            for attempt in range(3):
                try:
                    jd_payload = generate_jd_json_from_png_folder(
                        png_folder=image_folder,
                        output_json_path=json_path,
                        jd_research_tool_root=jd_research_tool_root,
                    )
                    print(f"  [INFO] 구조화 완료 → {json_path.name}")
                    break
                except Exception as e:
                    if "503" in str(e) or "service unavailable" in str(e).lower():
                        wait = 60 * (attempt + 1)
                        print(f"  [WARN] 503 에러, {wait}s 후 재시도 ({attempt + 1}/3)")
                        time.sleep(wait)
                    else:
                        print(f"  [ERROR] 구조화 실패: {e}")
                        break
            if jd_payload is None:
                failed += 1
                continue
        # job_id 기준으로 site/날짜 추출 (예: jobkorea_20260417_151715_001)
        parts = job_id.split("_")
        source_site = parts[0] if parts else "unknown"

        posting = {
            "id": job_id,
            "company": str(jd_payload.get("company", "") or ""),
            "posting_title": str(jd_payload.get("role", "") or job_id),
            "extracted_role": str(jd_payload.get("role", "") or ""),
            "source_site": source_site,
            "source_url": "",
            "seniority_text": "",
            "employment_type": "",
            "raw_text": str(jd_payload.get("raw_text", "") or ""),
            "captured_at": now_iso(),
            "classification_status": "pending",
        }

        try:
            save_job_posting(conn, posting)
            save_job_sections(conn, job_id, jd_payload)
            conn.commit()
            print(f"  [INFO] DB 저장 완료")
            success += 1
        except Exception as e:
            conn.rollback()
            print(f"  [ERROR] DB 저장 실패: {e}")
            failed += 1

    conn.close()
    print(f"\n[완료] 성공={success} / 스킵={skipped} / 실패={failed} / 전체={total}")


if __name__ == "__main__":
    main()
