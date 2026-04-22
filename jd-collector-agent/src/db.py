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


def save_job_posting_role_tags(
    conn: sqlite3.Connection,
    role_id: int,
    families: list[dict],
) -> None:
    """role_id에 대한 job_family 태그를 교체(replace) 저장한다.

    기존 태그를 먼저 삭제한 뒤 새 결과를 삽입하므로 재분류 시 구태 태그가 남지 않는다.
    이 함수는 분류 성공 시에만 호출해야 한다. 실패 시에는 호출하지 않으면 기존 태그가 보존된다.
    """
    created_at = _now_iso()
    rows = [
        (
            int(role_id),
            str(f.get("id", "") or "").strip(),
            int(f.get("is_primary", 0) or 0),
            created_at,
        )
        for f in families
        if str(f.get("id", "") or "").strip()
    ]
    # 기존 태그 삭제 (replace 동작 — 재분류 시 이전 결과 제거)
    conn.execute("DELETE FROM job_posting_role_tags WHERE role_id = ?", (int(role_id),))
    if rows:
        conn.executemany(
            """
            INSERT INTO job_posting_role_tags (role_id, job_family, is_primary, created_at)
            VALUES (?, ?, ?, ?)
            """,
            rows,
        )


def update_role_classification_status(
    conn: sqlite3.Connection,
    role_id: int,
    status: str,
) -> None:
    conn.execute(
        "UPDATE job_posting_roles SET classification_status = ? WHERE id = ?",
        (status, int(role_id)),
    )


def get_pending_roles_for_classify(
    conn: sqlite3.Connection,
    batch_size: int,
) -> list:
    conn.row_factory = sqlite3.Row
    return conn.execute(
        """
        SELECT jpr.id,
               jpr.job_id,
               jpr.role_name,
               jpr.main_tasks_json,
               jpr.requirements_json,
               jpr.preferred_json,
               jp.company,
               jp.posting_title,
               jp.source_category,
               jp.common_requirements_json,
               jp.common_preferred_json
        FROM job_posting_roles jpr
        JOIN job_postings jp ON jp.id = jpr.job_id
        WHERE jpr.classification_status = 'pending'
        ORDER BY jpr.created_at ASC, jpr.id ASC
        LIMIT ?
        """,
        (batch_size,),
    ).fetchall()


def get_roles_by_family_for_analyze(
    conn: sqlite3.Connection,
    job_family: str,
) -> tuple[list[dict], int, int]:
    """job_family로 분류된 role들의 텍스트, 공고 수(posting_count), role 수(role_count)를 반환한다.

    Returns:
        roles: role별 텍스트 dict 목록
        posting_count: DISTINCT job_id 기준 공고 수 (sample_count로 사용)
        role_count: 실제 role 개수
    """
    # 공고 수 (DISTINCT job_id) — 복합공고에서 role 여러 개가 같은 job_id를 가져도 1로 집계
    posting_row = conn.execute(
        """
        SELECT COUNT(DISTINCT jpr.job_id)
        FROM job_posting_role_tags jrt
        JOIN job_posting_roles jpr ON jpr.id = jrt.role_id
        WHERE jrt.job_family = ?
          AND jpr.classification_status = 'classified'
        """,
        (job_family,),
    ).fetchone()
    posting_count = int(posting_row[0]) if posting_row else 0

    rows = conn.execute(
        """
        SELECT jpr.id,
               jpr.role_name,
               jpr.main_tasks_json,
               jpr.requirements_json,
               jpr.preferred_json,
               jp.common_requirements_json,
               jp.common_preferred_json
        FROM job_posting_role_tags jrt
        JOIN job_posting_roles jpr ON jpr.id = jrt.role_id
        JOIN job_postings jp ON jp.id = jpr.job_id
        WHERE jrt.job_family = ?
          AND jpr.classification_status = 'classified'
        ORDER BY jpr.id ASC
        """,
        (job_family,),
    ).fetchall()

    roles = []
    for row in rows:
        roles.append({
            "role_id": int(row[0]),
            "role_name": str(row[1] or ""),
            "main_tasks": json.loads(row[2] or "[]"),
            "requirements": json.loads(row[3] or "[]"),
            "preferred": json.loads(row[4] or "[]"),
            "common_requirements": json.loads(row[5] or "[]"),
            "common_preferred": json.loads(row[6] or "[]"),
        })

    role_count = len(roles)
    return roles, posting_count, role_count


def get_classified_families_from_roles(conn: sqlite3.Connection) -> list[str]:
    """job_posting_role_tags 기준으로 classified된 job_family 목록을 반환한다."""
    rows = conn.execute(
        """
        SELECT DISTINCT jrt.job_family
        FROM job_posting_role_tags jrt
        JOIN job_posting_roles jpr ON jpr.id = jrt.role_id
        WHERE jpr.classification_status = 'classified'
        ORDER BY jrt.job_family ASC
        """
    ).fetchall()
    return [str(row[0]).strip() for row in rows if str(row[0]).strip()]
