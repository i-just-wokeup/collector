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
    load_dotenv(BASE_DIR / ".env")

    db_path = resolve_path(os.getenv("JD_DB_PATH", DEFAULT_DB_PATH))
    json_path = resolve_path(DEFAULT_JOB_FAMILIES_PATH)

    db_path.parent.mkdir(parents=True, exist_ok=True)
    families = load_job_families(json_path)

    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(DDL)
        seed_job_families(connection, families)
        connection.commit()

        table_names = fetch_table_names(connection)
        family_count = fetch_job_family_count(connection)

    print(f"DB path: {db_path}")
    print("Tables:")
    for table_name in table_names:
        print(f"- {table_name}")
    print(f"job_families rows: {family_count}")


if __name__ == "__main__":
    main()
