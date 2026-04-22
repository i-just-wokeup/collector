"""
export_csv.py
검수용 CSV 내보내기 스크립트

모드 1 (기본, 레거시): output/classified/ 아래 JSON 파일 기반
모드 2 (--db-roles):  DB job_posting_roles 기반 — role 단위 검수용

저장 경로: output/export_{범위}_{타임스탬프}.csv
UTF-8 BOM(utf-8-sig) 저장 → Excel에서 한글 정상 표시

사용:
  python src/export_csv.py --db-roles            # role 단위 DB export (권장)
  python src/export_csv.py --all                 # 레거시 JSON 기반 전체 export
  python src/export_csv.py --not_match
  python src/export_csv.py --unknown
"""

import argparse
import csv
import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path, PureWindowsPath
from typing import Optional


BASE_DIR = Path(__file__).resolve().parent.parent
CLASSIFIED_DIR = BASE_DIR / "output" / "classified"
EXPORT_DIR = BASE_DIR / "output"
DEFAULT_DB_PATH = r"C:\dev\jd_data.db"

RAW_TEXT_PREVIEW_LEN = 250
SECTION_JOIN_SEP = " / "
SECTION_MAX_LEN = 400

# 레거시 JSON 기반 export 필드
FIELDNAMES = [
    "id",
    "company",
    "title",
    "source_site",
    "source_url",
    "career",
    "auto_job_family",
    "main_tasks",
    "requirements",
    "preferred",
    "raw_text_preview",
]

# role 단위 DB export 필드
ROLE_FIELDNAMES = [
    "job_id",
    "role_id",
    "company",
    "posting_title",
    "source_category",
    "role_name",
    "role_classification",
    "role_main_tasks",
    "role_requirements",
    "role_preferred",
    "common_requirements",
    "common_preferred",
    "raw_text_preview",
]


def _join_list(items: object) -> str:
    if not isinstance(items, list):
        return ""
    parts = [str(x).strip() for x in items if str(x).strip()]
    joined = SECTION_JOIN_SEP.join(parts)
    if len(joined) > SECTION_MAX_LEN:
        return joined[: SECTION_MAX_LEN - 3] + "..."
    return joined


def _raw_preview(raw_text: object) -> str:
    text = str(raw_text or "").strip()
    if len(text) > RAW_TEXT_PREVIEW_LEN:
        return text[:RAW_TEXT_PREVIEW_LEN] + "..."
    return text


def _load_json_safe(path: Path) -> Optional[dict]:
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception as e:
        print(f"[WARN] 파싱 실패 ({type(e).__name__}): {path}")
    return None


def _extract_row(data: dict, json_path: Path) -> dict:
    meta = data.get("collector_meta", {})
    if not isinstance(meta, dict):
        meta = {}

    job_id = str(meta.get("job_id", "") or "").strip() or json_path.stem

    return {
        "id": job_id,
        "company": str(data.get("company", "") or ""),
        "title": str(data.get("posting_title", "") or data.get("role", "") or ""),
        "source_site": str(data.get("source_site", "") or ""),
        "source_url": str(data.get("source_url", "") or ""),
        "career": str(data.get("seniority_text", "") or ""),
        "auto_job_family": str(data.get("job_family_guess", "") or ""),
        "main_tasks": _join_list(data.get("main_tasks")),
        "requirements": _join_list(data.get("requirements")),
        "preferred": _join_list(data.get("preferred")),
        "raw_text_preview": _raw_preview(data.get("raw_text", "")),
    }


def collect_json_paths(subfolders: list[str]) -> list[Path]:
    paths: list[Path] = []
    for sub in subfolders:
        target_dir = CLASSIFIED_DIR / sub
        if target_dir.exists():
            paths.extend(sorted(target_dir.rglob("*.json")))
    return paths


def export_csv(subfolders: list[str]) -> Path:
    json_paths = collect_json_paths(subfolders)
    if not json_paths:
        print(
            "[WARN] JSON 파일 없음: "
            + str([str(CLASSIFIED_DIR / s) for s in subfolders])
        )
        sys.exit(1)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    label = "_".join(subfolders)
    output_path = EXPORT_DIR / f"export_{label}_{timestamp}.csv"

    rows: list[dict] = []
    skip_count = 0
    for path in json_paths:
        data = _load_json_safe(path)
        if data is None:
            skip_count += 1
            continue
        rows.append(_extract_row(data, path))

    # utf-8-sig: Excel에서 한글 깨짐 방지 (BOM 포함)
    with output_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    print(f"[INFO] exported={len(rows)} 행  skipped={skip_count}")
    print(f"[INFO] output_path={output_path}")
    return output_path


def _resolve_db_path(raw_path: str) -> Path:
    windows_path = PureWindowsPath(raw_path)
    if windows_path.drive.lower() == "c:":
        if Path("C:/").exists():
            return Path(windows_path)
        return Path("/mnt/c", *windows_path.parts[1:])
    return Path(raw_path)


def export_db_roles(db_path: str) -> Path:
    """DB job_posting_roles 기준 role 단위 검수용 CSV를 생성한다."""
    resolved = _resolve_db_path(db_path)
    conn = sqlite3.connect(resolved)
    conn.row_factory = sqlite3.Row

    rows_data = conn.execute(
        """
        SELECT
            jpr.id            AS role_id,
            jpr.job_id,
            jpr.role_name,
            jpr.main_tasks_json,
            jpr.requirements_json,
            jpr.preferred_json,
            jpr.classification_status,
            jp.company,
            jp.posting_title,
            jp.source_category,
            jp.common_requirements_json,
            jp.common_preferred_json,
            jp.raw_text,
            jp.source_site,
            jp.source_url,
            GROUP_CONCAT(jrt.job_family, ', ') AS role_families
        FROM job_posting_roles jpr
        JOIN job_postings jp ON jp.id = jpr.job_id
        LEFT JOIN job_posting_role_tags jrt ON jrt.role_id = jpr.id
        GROUP BY jpr.id
        ORDER BY jpr.job_id ASC, jpr.display_order ASC
        """
    ).fetchall()
    conn.close()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = EXPORT_DIR / f"export_db_roles_{timestamp}.csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    for row in rows_data:
        main_tasks = json.loads(row["main_tasks_json"] or "[]")
        requirements = json.loads(row["requirements_json"] or "[]")
        preferred = json.loads(row["preferred_json"] or "[]")
        common_req = json.loads(row["common_requirements_json"] or "[]")
        common_pref = json.loads(row["common_preferred_json"] or "[]")

        rows.append({
            "job_id": str(row["job_id"] or ""),
            "role_id": str(row["role_id"] or ""),
            "company": str(row["company"] or ""),
            "posting_title": str(row["posting_title"] or ""),
            "source_category": str(row["source_category"] or ""),
            "role_name": str(row["role_name"] or ""),
            "role_classification": str(row["role_families"] or row["classification_status"] or ""),
            "role_main_tasks": _join_list(main_tasks),
            "role_requirements": _join_list(requirements),
            "role_preferred": _join_list(preferred),
            "common_requirements": _join_list(common_req),
            "common_preferred": _join_list(common_pref),
            "raw_text_preview": _raw_preview(row["raw_text"]),
        })

    with output_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=ROLE_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    print(f"[INFO] exported={len(rows)} roles")
    print(f"[INFO] output_path={output_path}")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="검수용 CSV 내보내기")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--db-roles", action="store_true",
                       help="DB job_posting_roles 기반 role 단위 export (권장)")
    group.add_argument("--match", action="store_true", help="match 공고만 (기본값)")
    group.add_argument("--not_match", action="store_true", help="not_match 공고만")
    group.add_argument("--unknown", action="store_true", help="unknown 공고만")
    group.add_argument("--all", action="store_true", help="전체 (match + not_match + unknown)")
    parser.add_argument("--db-path", default="", help="DB 경로 (--db-roles 모드에서 사용)")
    args = parser.parse_args()

    if args.db_roles:
        db_path = args.db_path or os.getenv("JD_DB_PATH", DEFAULT_DB_PATH)
        export_db_roles(db_path)
        return

    if args.all:
        subfolders = ["match", "not_match", "unknown"]
    elif args.not_match:
        subfolders = ["not_match"]
    elif args.unknown:
        subfolders = ["unknown"]
    else:
        subfolders = ["match"]

    export_csv(subfolders)


if __name__ == "__main__":
    main()
