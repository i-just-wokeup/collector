import json
import sqlite3
from datetime import datetime
from pathlib import Path, PureWindowsPath


def _resolve_path(raw_path: str) -> Path:
    windows_path = PureWindowsPath(raw_path)
    if windows_path.drive.lower() == "c:":
        if Path("C:/").exists():
            return Path(windows_path)
        return Path("/mnt/c", *windows_path.parts[1:])
    return Path(raw_path)


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def get_db_connection(db_path: str) -> sqlite3.Connection:
    resolved_path = _resolve_path(db_path)
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(resolved_path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def is_seen_url(conn: sqlite3.Connection, source_url: str) -> bool:
    cursor = conn.execute(
        "SELECT 1 FROM job_postings WHERE source_url = ? LIMIT 1",
        (source_url,),
    )
    return cursor.fetchone() is not None


def save_job_posting(conn: sqlite3.Connection, posting: dict) -> None:
    captured_at = str(posting.get("captured_at", "") or _now_iso())
    created_at = str(posting.get("created_at", "") or _now_iso())

    conn.execute(
        """
        INSERT OR IGNORE INTO job_postings (
          id,
          company,
          posting_title,
          extracted_role,
          source_site,
          source_url,
          seniority_text,
          employment_type,
          raw_text,
          source_category,
          captured_at,
          classification_status,
          created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(posting.get("id", "") or ""),
            str(posting.get("company", "") or ""),
            str(posting.get("posting_title", "") or ""),
            str(posting.get("extracted_role", "") or ""),
            str(posting.get("source_site", "") or ""),
            str(posting.get("source_url", "") or ""),
            str(posting.get("seniority_text", "") or ""),
            str(posting.get("employment_type", "") or ""),
            str(posting.get("raw_text", "") or ""),
            str(posting.get("source_category", "") or ""),
            captured_at,
            str(posting.get("classification_status", "") or "pending"),
            created_at,
        ),
    )


def save_job_sections(conn: sqlite3.Connection, job_id: str, jd_payload: dict) -> None:
    section_map = {
        "main_tasks": jd_payload.get("main_tasks", []),
        "requirements": jd_payload.get("requirements", []),
        "preferred": jd_payload.get("preferred", []),
    }

    rows: list[tuple[str, str, str, int]] = []
    for section_type, items in section_map.items():
        if not isinstance(items, list):
            continue
        for display_order, content in enumerate(items):
            text = str(content or "").strip()
            if not text:
                continue
            rows.append((job_id, section_type, text, display_order))

    if not rows:
        return

    conn.executemany(
        """
        INSERT INTO job_sections (
          job_id,
          section_type,
          content,
          display_order
        ) VALUES (?, ?, ?, ?)
        """,
        rows,
    )


def save_job_posting_roles(conn: sqlite3.Connection, job_id: str, jd_payload: dict) -> int:
    """roles[] 배열을 job_posting_roles 테이블에 저장한다.

    Returns:
        저장된 row 수. 0이면 저장 불필요(이미 완전 저장) 또는 유효 role 없음.

    안전장치:
        - role_name이 비어 있는 role은 저장 skip (skipped_empty_role_name)
        - 이미 기대 개수만큼 저장된 경우 → already_complete, skip
        - 기대 개수와 실제 DB row 수가 다른 경우(partial) → DELETE + full reinsert
        - UNIQUE(job_id, display_order) 제약으로 DB 레벨 중복 차단 (INSERT OR IGNORE)
    """
    roles = jd_payload.get("roles")
    if not isinstance(roles, list) or not roles:
        return 0

    now = _now_iso()
    valid_rows = []
    skipped_empty = 0
    for order, role in enumerate(roles):
        if not isinstance(role, dict):
            continue
        role_name = str(role.get("role_name", "") or "").strip()
        if not role_name:
            skipped_empty += 1
            continue
        valid_rows.append((
            job_id,
            role_name,
            order,
            json.dumps(role.get("main_tasks", []) or [], ensure_ascii=False),
            json.dumps(role.get("requirements", []) or [], ensure_ascii=False),
            json.dumps(role.get("preferred", []) or [], ensure_ascii=False),
            now,
        ))

    if not valid_rows:
        return 0

    if skipped_empty:
        import sys
        print(f"[WARN] skipped_empty_role_name={skipped_empty} job_id={job_id}", file=sys.stderr)

    expected = len(valid_rows)
    existing = conn.execute(
        "SELECT COUNT(*) FROM job_posting_roles WHERE job_id = ?", (job_id,)
    ).fetchone()[0]

    if existing == expected:
        return 0  # already_complete

    if existing > 0:
        # partial 상태: 기존 rows 삭제 후 전체 재삽입
        conn.execute("DELETE FROM job_posting_roles WHERE job_id = ?", (job_id,))

    conn.executemany(
        """
        INSERT OR IGNORE INTO job_posting_roles (
          job_id, role_name, display_order,
          main_tasks_json, requirements_json, preferred_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        valid_rows,
    )

    # common_requirements / common_preferred를 job_postings에 UPDATE
    common_req = jd_payload.get("common_requirements")
    common_pref = jd_payload.get("common_preferred")
    if isinstance(common_req, list) or isinstance(common_pref, list):
        conn.execute(
            """
            UPDATE job_postings
            SET common_requirements_json = ?,
                common_preferred_json    = ?
            WHERE id = ?
            """,
            (
                json.dumps(common_req or [], ensure_ascii=False),
                json.dumps(common_pref or [], ensure_ascii=False),
                job_id,
            ),
        )

    return len(valid_rows)


def get_posting_count(conn: sqlite3.Connection) -> int:
    cursor = conn.execute("SELECT COUNT(*) FROM job_postings")
    return int(cursor.fetchone()[0])
