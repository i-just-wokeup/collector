"""
export_csv.py
검수용 CSV 내보내기 스크립트

output/classified/ 아래 JSON 파일을 읽어
공고 1개당 1행 형식의 CSV로 저장한다.

저장 경로: output/export_{범위}_{타임스탬프}.csv
UTF-8 BOM(utf-8-sig) 저장 → Excel에서 한글 정상 표시

사용:
  python src/export_csv.py            # match 공고만 (기본값)
  python src/export_csv.py --all      # match + not_match + unknown
  python src/export_csv.py --not_match
  python src/export_csv.py --unknown
"""

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional


BASE_DIR = Path(__file__).resolve().parent.parent
CLASSIFIED_DIR = BASE_DIR / "output" / "classified"
EXPORT_DIR = BASE_DIR / "output"

RAW_TEXT_PREVIEW_LEN = 250
SECTION_JOIN_SEP = " / "
SECTION_MAX_LEN = 300

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


def main() -> None:
    parser = argparse.ArgumentParser(description="검수용 CSV 내보내기")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--match", action="store_true", help="match 공고만 (기본값)")
    group.add_argument("--not_match", action="store_true", help="not_match 공고만")
    group.add_argument("--unknown", action="store_true", help="unknown 공고만")
    group.add_argument(
        "--all", action="store_true", help="전체 (match + not_match + unknown)"
    )
    args = parser.parse_args()

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
