import argparse
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path, PureWindowsPath

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = r"C:\dev\jd_data.db"
DEFAULT_JOB_FAMILIES_PATH = str((BASE_DIR / "job_families.json").resolve())


DDL = """
CREATE TABLE IF NOT EXISTS job_families (
  id            TEXT PRIMARY KEY,
  display_name  TEXT NOT NULL,
  category      TEXT NOT NULL,
  aliases       TEXT NOT NULL,
  is_active     INTEGER NOT NULL DEFAULT 1,
  created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job_postings (
  id                    TEXT PRIMARY KEY,
  company               TEXT NOT NULL,
  posting_title         TEXT NOT NULL,
  extracted_role        TEXT NOT NULL,
  source_site           TEXT NOT NULL,
  source_url            TEXT NOT NULL,
  seniority_text        TEXT DEFAULT '',
  employment_type       TEXT DEFAULT '',
  raw_text              TEXT DEFAULT '',
  source_category       TEXT DEFAULT '',
  captured_at           TEXT NOT NULL,
  classification_status TEXT NOT NULL DEFAULT 'pending',
  created_at            TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job_tags (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id      TEXT NOT NULL REFERENCES job_postings(id) ON DELETE CASCADE,
  job_family  TEXT NOT NULL REFERENCES job_families(id),
  is_primary  INTEGER NOT NULL DEFAULT 0,
  created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_job_tags_job_id     ON job_tags(job_id);
CREATE INDEX IF NOT EXISTS idx_job_tags_job_family ON job_tags(job_family);

CREATE TABLE IF NOT EXISTS job_sections (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id        TEXT NOT NULL REFERENCES job_postings(id) ON DELETE CASCADE,
  section_type  TEXT NOT NULL,
  content       TEXT NOT NULL,
  display_order INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_job_sections_job_id ON job_sections(job_id);

CREATE TABLE IF NOT EXISTS job_criteria (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  job_family      TEXT NOT NULL REFERENCES job_families(id),
  category        TEXT NOT NULL,
  criteria_name   TEXT NOT NULL,
  description     TEXT DEFAULT '',
  frequency_rank  INTEGER DEFAULT 0,
  sample_count    INTEGER DEFAULT 0,
  extracted_at    TEXT NOT NULL,
  UNIQUE(job_family, criteria_name)
);
CREATE INDEX IF NOT EXISTS idx_job_criteria_job_family ON job_criteria(job_family);

CREATE TABLE IF NOT EXISTS criteria_stats (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  job_family  TEXT NOT NULL REFERENCES job_families(id),
  keyword     TEXT NOT NULL,
  count       INTEGER DEFAULT 0,
  total_jobs  INTEGER DEFAULT 0,
  ratio       REAL DEFAULT 0.0,
  updated_at  TEXT NOT NULL,
  UNIQUE(job_family, keyword)
);
CREATE INDEX IF NOT EXISTS idx_criteria_stats_job_family ON criteria_stats(job_family);

CREATE TABLE IF NOT EXISTS job_posting_roles (
  id                    INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id                TEXT NOT NULL REFERENCES job_postings(id) ON DELETE CASCADE,
  role_name             TEXT NOT NULL,
  display_order         INTEGER NOT NULL DEFAULT 0,
  main_tasks_json       TEXT NOT NULL DEFAULT '[]',
  requirements_json     TEXT NOT NULL DEFAULT '[]',
  preferred_json        TEXT NOT NULL DEFAULT '[]',
  classification_status TEXT NOT NULL DEFAULT 'pending',
  created_at            TEXT NOT NULL,
  UNIQUE(job_id, display_order)
);
CREATE INDEX IF NOT EXISTS idx_job_posting_roles_job_id ON job_posting_roles(job_id);

CREATE TABLE IF NOT EXISTS job_posting_role_tags (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  role_id     INTEGER NOT NULL REFERENCES job_posting_roles(id) ON DELETE CASCADE,
  job_family  TEXT NOT NULL,
  is_primary  INTEGER NOT NULL DEFAULT 0,
  created_at  TEXT NOT NULL,
  UNIQUE(role_id, job_family)
);
CREATE INDEX IF NOT EXISTS idx_job_posting_role_tags_role_id    ON job_posting_role_tags(role_id);
CREATE INDEX IF NOT EXISTS idx_job_posting_role_tags_job_family ON job_posting_role_tags(job_family);
"""


def resolve_path(raw_path: str) -> Path:
    windows_path = PureWindowsPath(raw_path)
    if windows_path.drive.lower() == "c:":
        if Path("C:/").exists():
            return Path(windows_path)
        return Path("/mnt/c", *windows_path.parts[1:])
    return Path(raw_path)


def load_job_families(json_path: Path) -> list[dict[str, object]]:
    with json_path.open("r", encoding="utf-8") as file:
        return json.load(file)


def seed_job_families(connection: sqlite3.Connection, families: list[dict[str, object]]) -> None:
    created_at = datetime.now().isoformat(timespec="seconds")
    rows = []

    for family in families:
        rows.append(
            (
                family["id"],
                family["display_name"],
                family["category"],
                json.dumps(family["aliases"], ensure_ascii=False),
                1,
                created_at,
            )
        )

    connection.executemany(
        """
        INSERT OR IGNORE INTO job_families (
          id,
          display_name,
          category,
          aliases,
          is_active,
          created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def fetch_table_names(connection: sqlite3.Connection) -> list[str]:
    cursor = connection.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
        ORDER BY name
        """
    )
    return [row[0] for row in cursor.fetchall()]


def fetch_job_family_count(connection: sqlite3.Connection) -> int:
    cursor = connection.execute("SELECT COUNT(*) FROM job_families")
    return int(cursor.fetchone()[0])


def main() -> None:
    parser = argparse.ArgumentParser(description="JD collector DB 초기화")
    parser.add_argument(
        "--families-file",
        default=None,
        help="직무군 정의 JSON 파일 경로 (기본값: job_families.json)",
    )
    parser.add_argument(
        "--db-path",
        default=None,
        help="DB 파일 경로 (기본값: 환경변수 JD_DB_PATH 또는 C:\\dev\\jd_data.db)",
    )
    args = parser.parse_args()

    load_dotenv(BASE_DIR / ".env")

    raw_db_path = args.db_path or os.getenv("JD_DB_PATH", DEFAULT_DB_PATH)
    db_path = resolve_path(raw_db_path)

    raw_families_path = args.families_file or DEFAULT_JOB_FAMILIES_PATH
    json_path = resolve_path(raw_families_path)

    db_path.parent.mkdir(parents=True, exist_ok=True)
    families = load_job_families(json_path)

    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(DDL)
        # 기존 DB 마이그레이션 (이미 컬럼/인덱스가 존재하면 무시)
        for alter_sql in [
            "ALTER TABLE job_postings ADD COLUMN source_category TEXT DEFAULT ''",
            "ALTER TABLE job_postings ADD COLUMN common_requirements_json TEXT DEFAULT '[]'",
            "ALTER TABLE job_postings ADD COLUMN common_preferred_json TEXT DEFAULT '[]'",
            # job_posting_roles 중복 방지 UNIQUE index (기존 DB용)
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_job_posting_roles_unique ON job_posting_roles(job_id, display_order)",
            # role 단위 분류 상태 컬럼 (기존 DB용)
            "ALTER TABLE job_posting_roles ADD COLUMN classification_status TEXT DEFAULT 'pending'",
            # role 단위 태그 테이블 (기존 DB용 — DDL과 동일 구조)
            """CREATE TABLE IF NOT EXISTS job_posting_role_tags (
              id          INTEGER PRIMARY KEY AUTOINCREMENT,
              role_id     INTEGER NOT NULL REFERENCES job_posting_roles(id) ON DELETE CASCADE,
              job_family  TEXT NOT NULL,
              is_primary  INTEGER NOT NULL DEFAULT 0,
              created_at  TEXT NOT NULL,
              UNIQUE(role_id, job_family)
            )""",
            "CREATE INDEX IF NOT EXISTS idx_job_posting_role_tags_role_id    ON job_posting_role_tags(role_id)",
            "CREATE INDEX IF NOT EXISTS idx_job_posting_role_tags_job_family ON job_posting_role_tags(job_family)",
        ]:
            try:
                connection.execute(alter_sql)
            except Exception:
                pass
        seed_job_families(connection, families)
        connection.commit()

        table_names = fetch_table_names(connection)
        family_count = fetch_job_family_count(connection)

    print(f"DB path: {db_path}")
    print(f"families file: {json_path}")
    print("Tables:")
    for table_name in table_names:
        print(f"- {table_name}")
    print(f"job_families rows: {family_count}")


if __name__ == "__main__":
    main()
