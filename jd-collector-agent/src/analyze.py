import json
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path, PureWindowsPath

from dotenv import load_dotenv
import google.generativeai as genai

from db import get_db_connection
from utils import GeminiQuotaExceededError, is_gemini_quota_error


DEFAULT_DB_PATH = r"C:\dev\jd_data.db"
DEFAULT_JOB_FAMILIES_PATH = r"C:\dev\job_families.json"
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
MAX_GEMINI_SECTIONS = 100
MAX_CRITERIA_PER_CATEGORY = 5
MAX_CRITERIA_TOTAL = 10
ANALYSIS_SECTION_TYPES = ("requirements", "main_tasks", "preferred")
_LAST_TOTAL_JOBS_BY_FAMILY: dict[str, int] = {}


def _resolve_path(raw_path: str) -> Path:
    windows_path = PureWindowsPath(raw_path)
    if windows_path.drive.lower() == "c:":
        if Path("C:/").exists():
            return Path(windows_path)
        return Path("/mnt/c", *windows_path.parts[1:])
    return Path(raw_path)


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _load_job_families(json_path: str = DEFAULT_JOB_FAMILIES_PATH) -> list[dict]:
    resolved_path = _resolve_path(json_path)
    with resolved_path.open("r", encoding="utf-8") as file:
        payload = json.load(file)

    families: list[dict] = []
    for item in payload:
        aliases = item.get("aliases", [])
        families.append(
            {
                "id": str(item.get("id", "")).strip(),
                "display_name": str(item.get("display_name", "")).strip(),
                "aliases": aliases if isinstance(aliases, list) else [],
            }
        )
    return families


def _extract_json_array(raw_text: str) -> list:
    text = (raw_text or "").strip()
    if not text:
        return []

    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
    except Exception:
        pass

    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or start >= end:
        return []

    try:
        parsed = json.loads(text[start : end + 1])
    except Exception:
        return []

    return parsed if isinstance(parsed, list) else []


def _contains_korean(text: str) -> bool:
    return bool(re.search(r"[가-힣]", text))


def _contains_keyword(section_text: str, keyword: str) -> bool:
    section = (section_text or "").strip()
    token = (keyword or "").strip()
    if not section or not token:
        return False

    if _contains_korean(token):
        return token.lower() in section.lower()

    pattern = re.compile(
        rf"(?<![0-9A-Za-z가-힣]){re.escape(token)}(?![0-9A-Za-z가-힣])",
        re.IGNORECASE,
    )
    return pattern.search(section) is not None


def _normalize_category(raw_value: str) -> str:
    text = str(raw_value or "").strip()
    lowered = text.lower()
    if text == "직무역량" or "역량" in text or "skill" in lowered or "competenc" in lowered:
        return "직무역량"
    if text == "직무경험" or "경험" in text or "experience" in lowered:
        return "직무경험"
    return ""


def _normalize_criteria_list(parsed_items: list) -> list[dict]:
    category_counts = {"직무역량": 0, "직무경험": 0}
    seen_names: set[str] = set()
    normalized: list[dict] = []

    for item in parsed_items:
        if len(normalized) >= MAX_CRITERIA_TOTAL:
            break
        if not isinstance(item, dict):
            continue

        category = _normalize_category(str(item.get("category", "")))
        criteria_name = str(item.get("criteria_name", "")).strip()
        description = str(item.get("description", "")).strip()
        if not category or not criteria_name:
            continue
        if category_counts[category] >= MAX_CRITERIA_PER_CATEGORY:
            continue

        dedup_key = criteria_name.casefold()
        if dedup_key in seen_names:
            continue

        seen_names.add(dedup_key)
        category_counts[category] += 1
        normalized.append(
            {
                "category": category,
                "criteria_name": criteria_name,
                "description": description,
            }
        )

    return normalized


def get_classified_families(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        """
        SELECT DISTINCT jt.job_family
        FROM job_tags jt
        JOIN job_postings jp
          ON jp.id = jt.job_id
        WHERE jp.classification_status = 'classified'
        ORDER BY jt.job_family ASC
        """
    ).fetchall()
    return [str(row[0]).strip() for row in rows if str(row[0]).strip()]


def get_sections_by_family(
    conn: sqlite3.Connection,
    job_family: str,
) -> tuple[list[str], int]:
    total_jobs_row = conn.execute(
        """
        SELECT COUNT(DISTINCT jt.job_id)
        FROM job_tags jt
        JOIN job_postings jp
          ON jp.id = jt.job_id
        WHERE jt.job_family = ?
          AND jp.classification_status = 'classified'
        """,
        (job_family,),
    ).fetchone()
    total_jobs = int(total_jobs_row[0]) if total_jobs_row else 0

    rows = conn.execute(
        """
        SELECT DISTINCT js.job_id, js.section_type, js.display_order, js.content
        FROM job_tags jt
        JOIN job_postings jp
          ON jp.id = jt.job_id
        JOIN job_sections js
          ON js.job_id = jt.job_id
        WHERE jt.job_family = ?
          AND jp.classification_status = 'classified'
          AND js.section_type IN (?, ?, ?)
        ORDER BY js.job_id ASC, js.section_type ASC, js.display_order ASC
        """,
        (job_family, *ANALYSIS_SECTION_TYPES),
    ).fetchall()

    sections: list[str] = []
    for row in rows:
        text = str(row[3] or "").strip()
        if text:
            sections.append(text)

    _LAST_TOTAL_JOBS_BY_FAMILY[job_family] = total_jobs
    return sections, total_jobs


def count_keywords(
    sections: list[str],
    job_family: str,
    job_families: list[dict],
) -> list[dict]:
    if not sections:
        return []

    family_info = next((item for item in job_families if item.get("id") == job_family), None)
    if not family_info:
        return []

    raw_aliases = family_info.get("aliases", [])
    if not isinstance(raw_aliases, list):
        return []

    total_jobs = _LAST_TOTAL_JOBS_BY_FAMILY.get(job_family, 0)
    if total_jobs <= 0:
        return []

    aliases: list[str] = []
    seen_aliases: set[str] = set()
    for alias in raw_aliases:
        keyword = str(alias or "").strip()
        if not keyword:
            continue
        dedup_key = keyword.casefold()
        if dedup_key in seen_aliases:
            continue
        seen_aliases.add(dedup_key)
        aliases.append(keyword)

    stats: list[dict] = []
    for keyword in aliases:
        count = 0
        for section in sections:
            if _contains_keyword(section, keyword):
                count += 1

        ratio = count / total_jobs if total_jobs else 0.0
        if ratio < 0.1:
            continue

        stats.append(
            {
                "keyword": keyword,
                "count": count,
                "total_jobs": total_jobs,
                "ratio": round(ratio, 4),
            }
        )

    stats.sort(key=lambda item: (-int(item["count"]), str(item["keyword"]).lower()))
    return stats


def save_criteria_stats(
    conn: sqlite3.Connection,
    job_family: str,
    stats: list[dict],
) -> None:
    if not stats:
        return

    updated_at = _now_iso()
    rows = [
        (
            job_family,
            str(item.get("keyword", "")).strip(),
            int(item.get("count", 0) or 0),
            int(item.get("total_jobs", 0) or 0),
            float(item.get("ratio", 0.0) or 0.0),
            updated_at,
        )
        for item in stats
        if str(item.get("keyword", "")).strip()
    ]

    if not rows:
        return

    conn.executemany(
        """
        INSERT OR REPLACE INTO criteria_stats (
          job_family,
          keyword,
          count,
          total_jobs,
          ratio,
          updated_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def extract_job_criteria(
    sections: list[str],
    job_family: str,
    display_name: str,
    sample_count: int,
    api_key: str,
) -> list[dict]:
    section_samples = [str(item or "").strip() for item in sections if str(item or "").strip()]
    section_samples = section_samples[:MAX_GEMINI_SECTIONS]
    if not section_samples:
        return []

    model_name = os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
    prompt_payload = {
        "job_family": job_family,
        "display_name": display_name,
        "sample_count": sample_count,
        "sections": section_samples,
    }
    prompt = f"""
당신은 채용공고 요구사항을 요약해 직무 기준을 추출하는 분석기다.

아래 입력은 "{display_name}" 직무로 분류된 채용공고 섹션 문장들이다.
이 문장들만 근거로 핵심 기준을 추출하라.

반드시 지킬 조건:
- category는 "직무역량" 또는 "직무경험"만 사용한다.
- "직무역량"은 기술/지식/자격 중심으로 최대 5개까지 추출한다.
- "직무경험"은 실제 해본 경험 중심으로 최대 5개까지 추출한다.
- 전체 항목 수는 최대 10개다.
- 너무 추상적인 항목은 제외한다.
- "성실함", "커뮤니케이션"처럼 단독 소프트스킬은 제외한다.
- criteria_name은 짧고 구체적으로 작성한다.
- description은 왜 중요한지 또는 어떤 경험/기술을 의미하는지 1~2문장으로 설명한다.
- 출력은 반드시 JSON 배열만 반환한다. 마크다운, 설명, 코드펜스를 절대 추가하지 마라.

출력 예시:
[
  {{
    "category": "직무역량",
    "criteria_name": "Java/Spring 백엔드 개발",
    "description": "Java와 Spring 기반 서버 구현 및 운영 경험이 반복적으로 요구된다."
  }},
  {{
    "category": "직무경험",
    "criteria_name": "대용량 트래픽 서비스 운영 경험",
    "description": "실서비스 운영, 장애 대응, 성능 최적화 경험이 요구된다."
  }}
]

입력 데이터:
{json.dumps(prompt_payload, ensure_ascii=False, indent=2)}
"""

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)

    try:
        response = model.generate_content(
            prompt,
            generation_config={
                "response_mime_type": "application/json",
                "temperature": 0,
            },
        )
    except Exception as err:
        if is_gemini_quota_error(err):
            raise GeminiQuotaExceededError(str(err)) from err
        raise

    raw_response = (response.text or "").strip()
    parsed_items = _extract_json_array(raw_response)
    return _normalize_criteria_list(parsed_items)


def save_job_criteria(
    conn: sqlite3.Connection,
    job_family: str,
    criteria_list: list[dict],
    sample_count: int,
) -> None:
    if not criteria_list:
        return

    extracted_at = _now_iso()
    rows = []
    for index, item in enumerate(criteria_list, start=1):
        category = str(item.get("category", "")).strip()
        criteria_name = str(item.get("criteria_name", "")).strip()
        description = str(item.get("description", "")).strip()
        if not category or not criteria_name:
            continue
        rows.append(
            (
                job_family,
                category,
                criteria_name,
                description,
                index,
                sample_count,
                extracted_at,
            )
        )

    if not rows:
        return

    conn.executemany(
        """
        INSERT OR REPLACE INTO job_criteria (
          job_family,
          category,
          criteria_name,
          description,
          frequency_rank,
          sample_count,
          extracted_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def run_analyze(
    min_sample_count: int = 5,
    db_path: str = DEFAULT_DB_PATH,
) -> None:
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise ValueError("GEMINI_API_KEY is required")

    effective_db_path = os.getenv("JD_DB_PATH", db_path)
    job_families = _load_job_families(DEFAULT_JOB_FAMILIES_PATH)
    family_meta = {
        str(item.get("id", "")).strip(): {
            "display_name": str(item.get("display_name", "")).strip() or str(item.get("id", "")).strip(),
        }
        for item in job_families
    }

    conn = get_db_connection(effective_db_path)
    processed_count = 0
    skipped_count = 0

    print(f"[INFO] min_sample_count={min_sample_count}")
    print(f"[INFO] db_path={effective_db_path}")
    print(f"[INFO] gemini_model={os.getenv('GEMINI_MODEL', DEFAULT_GEMINI_MODEL)}")

    try:
        target_families = get_classified_families(conn)
        print(f"[INFO] classified_families={len(target_families)}")

        if not target_families:
            print("[DONE] no classified families.")
            return

        for job_family in target_families:
            display_name = family_meta.get(job_family, {}).get("display_name", job_family)
            sections, sample_count = get_sections_by_family(conn, job_family)
            print(
                f"[INFO] analyze_family={job_family} "
                f"display_name={display_name} sample_count={sample_count} sections={len(sections)}"
            )

            if sample_count < min_sample_count:
                skipped_count += 1
                print(f"[SKIP] insufficient samples: job_family={job_family} sample_count={sample_count}")
                continue

            if not sections:
                skipped_count += 1
                print(f"[SKIP] no sections found: job_family={job_family}")
                continue

            stats = count_keywords(
                sections=sections,
                job_family=job_family,
                job_families=job_families,
            )
            save_criteria_stats(conn, job_family, stats)
            conn.commit()
            print(f"[INFO] criteria_stats_saved={len(stats)}")

            try:
                criteria_list = extract_job_criteria(
                    sections=sections,
                    job_family=job_family,
                    display_name=display_name,
                    sample_count=sample_count,
                    api_key=api_key,
                )
            except GeminiQuotaExceededError as err:
                conn.rollback()
                skipped_count += 1
                print(f"[SKIP] Gemini quota exceeded for {job_family}: {err}")
                continue

            save_job_criteria(
                conn,
                job_family=job_family,
                criteria_list=criteria_list,
                sample_count=sample_count,
            )
            conn.commit()
            processed_count += 1
            print(f"[INFO] job_criteria_saved={len(criteria_list)}")
    finally:
        conn.close()

    print(f"[DONE] processed_count={processed_count} skipped_count={skipped_count}")


def prompt_with_default(message: str, default: str) -> str:
    value = input(f"{message} [{default}]: ").strip()
    return value or default


def main() -> None:
    load_dotenv()
    min_sample_count_text = prompt_with_default("min_sample_count", "5")
    if not min_sample_count_text.isdigit() or int(min_sample_count_text) <= 0:
        raise ValueError("min_sample_count must be a positive integer")

    default_db_path = os.getenv("JD_DB_PATH", DEFAULT_DB_PATH)
    db_path = prompt_with_default("db_path", default_db_path)

    run_analyze(
        min_sample_count=int(min_sample_count_text),
        db_path=db_path,
    )


if __name__ == "__main__":
    main()
