"""
백필 스크립트: raw_captures 폴더의 jd_result.json에서 roles[]를 읽어 DB에 저장한다.
추가 Gemini 호출 없이 로컬 파일만 사용한다.

사용법:
    python scripts/backfill_roles.py
    python scripts/backfill_roles.py --db-path C:\\dev\\jd_data_top8.db
    python scripts/backfill_roles.py --raw-dir output\\raw_captures --dry-run

대상 조건:
    1. raw_captures/{job_id}/jd_result.json 파일이 존재
    2. jd_result.json에 roles[] 배열이 있고 비어 있지 않음
    3. DB에 해당 job_id의 job_postings 레코드가 존재 (없으면 skip)
    4-a. DB role rows == 기대 개수 → already_complete, skip
    4-b. DB role rows > 0 but != 기대 개수 → partial_detected, 복구
    4-c. DB role rows == 0 → fresh insert
"""
import argparse
import json
import os
import sys
from pathlib import Path, PureWindowsPath


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = r"C:\dev\jd_data.db"
DEFAULT_RAW_DIR = str(BASE_DIR / "output" / "raw_captures")

sys.path.insert(0, str(BASE_DIR / "src"))
from db import get_db_connection, save_job_posting_roles  # noqa: E402


def resolve_path(raw_path: str) -> Path:
    windows_path = PureWindowsPath(raw_path)
    if windows_path.drive.lower() == "c:":
        if Path("C:/").exists():
            return Path(windows_path)
        return Path("/mnt/c", *windows_path.parts[1:])
    return Path(raw_path)


def _count_valid_roles(roles: list) -> int:
    return sum(
        1 for r in roles
        if isinstance(r, dict) and str(r.get("role_name", "") or "").strip()
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="roles[] 백필 스크립트")
    parser.add_argument("--db-path", default=None, help="DB 파일 경로")
    parser.add_argument("--raw-dir", default=None, help="raw_captures 디렉토리 경로")
    parser.add_argument("--dry-run", action="store_true", help="실제 저장 없이 대상만 출력")
    args = parser.parse_args()

    raw_db_path = args.db_path or os.getenv("JD_DB_PATH", DEFAULT_DB_PATH)
    db_path = resolve_path(raw_db_path)
    raw_dir = resolve_path(args.raw_dir or DEFAULT_RAW_DIR)

    if not raw_dir.exists():
        print(f"[ERROR] raw_dir not found: {raw_dir}")
        sys.exit(1)

    conn = get_db_connection(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")

    stats = {
        "total": 0,
        "no_roles": 0,
        "no_posting": 0,
        "already_complete": 0,
        "partial_detected": 0,
        "fresh": 0,
        "saved": 0,
        "error": 0,
    }

    for capture_dir in sorted(raw_dir.iterdir()):
        if not capture_dir.is_dir():
            continue
        jd_result_path = capture_dir / "jd_result.json"
        if not jd_result_path.exists():
            continue

        job_id = capture_dir.name
        stats["total"] += 1

        try:
            jd_payload = json.loads(jd_result_path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[WARN] json_parse_error job_id={job_id}: {e}")
            stats["error"] += 1
            continue

        roles = jd_payload.get("roles")
        if not isinstance(roles, list) or not roles:
            stats["no_roles"] += 1
            continue

        expected = _count_valid_roles(roles)
        if expected == 0:
            stats["no_roles"] += 1
            continue

        # DB posting 존재 확인
        row = conn.execute(
            "SELECT id FROM job_postings WHERE id = ? LIMIT 1", (job_id,)
        ).fetchone()
        if row is None:
            print(f"[SKIP] no_posting_in_db job_id={job_id}")
            stats["no_posting"] += 1
            continue

        # 현재 DB row 수 확인
        existing = conn.execute(
            "SELECT COUNT(*) FROM job_posting_roles WHERE job_id = ?", (job_id,)
        ).fetchone()[0]

        if existing == expected:
            stats["already_complete"] += 1
            continue
        elif existing > 0:
            print(f"[PARTIAL] job_id={job_id} existing={existing} expected={expected}")
            stats["partial_detected"] += 1
        else:
            stats["fresh"] += 1

        print(f"[TARGET] job_id={job_id} roles={expected} existing_db_rows={existing}")

        if args.dry_run:
            continue

        try:
            saved = save_job_posting_roles(conn, job_id, jd_payload)
            conn.commit()
            action = "deleted_and_reinserted" if existing > 0 else "inserted"
            print(f"[DONE] {action} job_id={job_id} saved_roles={saved}")
            stats["saved"] += 1
        except Exception as e:
            conn.rollback()
            print(f"[ERROR] job_id={job_id}: {e}")
            stats["error"] += 1

    conn.close()

    print()
    print("=== backfill result ===")
    print(f"  total folders checked: {stats['total']}")
    print(f"  no_roles (old format): {stats['no_roles']}")
    print(f"  no_posting_in_db:      {stats['no_posting']}")
    print(f"  already_complete:      {stats['already_complete']}")
    print(f"  partial_detected:      {stats['partial_detected']}")
    print(f"  fresh:                 {stats['fresh']}")
    print(f"  saved:                 {stats['saved']}")
    print(f"  error:                 {stats['error']}")
    if args.dry_run:
        print("  (dry-run mode - no actual writes)")


if __name__ == "__main__":
    main()
