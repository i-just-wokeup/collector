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
          captured_at,
          classification_status,
          created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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


def get_posting_count(conn: sqlite3.Connection) -> int:
    cursor = conn.execute("SELECT COUNT(*) FROM job_postings")
    return int(cursor.fetchone()[0])
