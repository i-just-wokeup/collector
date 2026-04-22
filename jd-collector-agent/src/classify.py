import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path, PureWindowsPath

from dotenv import load_dotenv
import google.generativeai as genai

from db import (
    get_db_connection,
    get_pending_roles_for_classify,
    save_job_posting_role_tags,
    update_role_classification_status,
)
from utils import (
    GeminiQuotaExceededError,
    filter_generic_analysis_lines,
    is_gemini_quota_error,
)


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = r"C:\dev\jd_data.db"
DEFAULT_JOB_FAMILIES_PATH = str((BASE_DIR / "job_families.json").resolve())
DEFAULT_BATCH_SIZE = 20
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"


def _resolve_path(raw_path: str) -> Path:
    windows_path = PureWindowsPath(raw_path)
    if windows_path.drive.lower() == "c:":
        if Path("C:/").exists():
            return Path(windows_path)
        return Path("/mnt/c", *windows_path.parts[1:])
    return Path(raw_path)


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _extract_json_array(raw_text: str) -> list[str]:
    text = (raw_text or "").strip()
    if not text:
        return []

    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
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

    if not isinstance(parsed, list):
        return []
    return [str(item).strip() for item in parsed if str(item).strip()]


def _normalize_families(detected_ids: list[str], job_families: list[dict]) -> list[dict]:
    allowed_ids = {str(item.get("id", "")).strip() for item in job_families}
    normalized_ids: list[str] = []

    for family_id in detected_ids:
        candidate = str(family_id or "").strip()
        if not candidate or candidate not in allowed_ids:
            continue
        if candidate in normalized_ids:
            continue
        normalized_ids.append(candidate)
        if len(normalized_ids) >= 3:
            break

    if not normalized_ids:
        normalized_ids = ["unknown"]

    if normalized_ids[0] == "unknown":
        return [{"id": "unknown", "is_primary": 1}]

    families: list[dict] = []
    for index, family_id in enumerate(normalized_ids):
        if family_id == "unknown":
            continue
        families.append({"id": family_id, "is_primary": 1 if index == 0 else 0})

    return families or [{"id": "unknown", "is_primary": 1}]


def load_job_families(json_path: Path) -> list[dict]:
    resolved_path = _resolve_path(str(json_path))
    with resolved_path.open("r", encoding="utf-8") as file:
        payload = json.load(file)

    families: list[dict] = []
    for item in payload:
        families.append(
            {
                "id": str(item.get("id", "")).strip(),
                "display_name": str(item.get("display_name", "")).strip(),
                "aliases": item.get("aliases", []) if isinstance(item.get("aliases", []), list) else [],
            }
        )
    return families


def detect_job_families(
    posting_title: str,
    extracted_role: str,
    raw_text: str,
    job_families: list[dict],
    api_key: str,
) -> list[dict]:
    model_name = os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
    payload_preview = {
        "posting_title": posting_title,
        "extracted_role": extracted_role,
        "raw_text_preview": (raw_text or "")[:500],
        "job_families": job_families,
    }

    prompt = f"""
당신은 채용공고를 직무 대분류로 매핑하는 분류기다.

아래 공고를 보고 가장 적절한 job_family id를 판정하라.
- 단일 공고면 1개만 반환
- 복합 공고면 최대 3개까지 반환
- 첫 번째 항목이 주 직무다
- 명확하지 않으면 "unknown"만 반환
- 출력은 반드시 JSON 배열만 반환하라

예시:
["backend"]
["backend", "devops"]
["unknown"]

입력 데이터:
{json.dumps(payload_preview, ensure_ascii=False, indent=2)}
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
    detected_ids = _extract_json_array(raw_response)
    return _normalize_families(detected_ids, job_families)


def save_job_tags(
    conn: sqlite3.Connection,
    job_id: str,
    families: list[dict],
) -> None:
    created_at = _now_iso()
    rows = []
    for family in families:
        rows.append(
            (
                job_id,
                str(family.get("id", "") or ""),
                int(family.get("is_primary", 0) or 0),
                created_at,
            )
        )

    conn.executemany(
        """
        INSERT OR IGNORE INTO job_tags (
          job_id,
          job_family,
          is_primary,
          created_at
        ) VALUES (?, ?, ?, ?)
        """,
        rows,
    )


def update_classification_status(
    conn: sqlite3.Connection,
    job_id: str,
    status: str,
) -> None:
    conn.execute(
        "UPDATE job_postings SET classification_status = ? WHERE id = ?",
        (status, job_id),
    )


def run_classify(
    batch_size: int = DEFAULT_BATCH_SIZE,
    db_path: str = DEFAULT_DB_PATH,
) -> None:
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise ValueError("GEMINI_API_KEY is required")

    effective_db_path = os.getenv("JD_DB_PATH", db_path)
    job_families = load_job_families(_resolve_path(DEFAULT_JOB_FAMILIES_PATH))
    conn = get_db_connection(effective_db_path)
    conn.row_factory = sqlite3.Row

    success_count = 0
    failed_count = 0

    print(f"[INFO] batch_size={batch_size}")
    print(f"[INFO] db_path={effective_db_path}")
    print(f"[INFO] gemini_model={os.getenv('GEMINI_MODEL', DEFAULT_GEMINI_MODEL)}")

    try:
        rows = conn.execute(
            """
            SELECT id, posting_title, extracted_role, raw_text
            FROM job_postings
            WHERE classification_status = 'pending'
            ORDER BY created_at ASC, id ASC
            LIMIT ?
            """,
            (batch_size,),
        ).fetchall()

        print(f"[INFO] pending_rows={len(rows)}")
        if not rows:
            print("[DONE] no pending postings.")
            return

        for row in rows:
            job_id = str(row["id"])
            posting_title = str(row["posting_title"] or "")
            extracted_role = str(row["extracted_role"] or "")
            raw_text = str(row["raw_text"] or "")

            print(f"[INFO] classify_job_id={job_id}")

            try:
                families = detect_job_families(
                    posting_title=posting_title,
                    extracted_role=extracted_role,
                    raw_text=raw_text,
                    job_families=job_families,
                    api_key=api_key,
                )
                save_job_tags(conn, job_id, families)
                update_classification_status(conn, job_id, "classified")
                conn.commit()
                success_count += 1
                print(f"[INFO] classified_families={families}")
            except GeminiQuotaExceededError as err:
                conn.rollback()
                update_classification_status(conn, job_id, "failed")
                conn.commit()
                failed_count += 1
                print(f"[ERROR] Gemini quota exceeded: {err}")
                print("[DONE] stop classify due to quota error.")
                break
            except Exception as err:
                conn.rollback()
                update_classification_status(conn, job_id, "failed")
                conn.commit()
                failed_count += 1
                print(f"[WARN] classify failed for {job_id}: {err}")
    finally:
        conn.close()

    print(f"[DONE] success_count={success_count} failed_count={failed_count}")


def detect_job_family_for_role(
    company: str,
    posting_title: str,
    source_category: str,
    role_name: str,
    main_tasks: list[str],
    requirements: list[str],
    preferred: list[str],
    common_requirements: list[str],
    job_families: list[dict],
    api_key: str,
) -> list[dict]:
    """단일 role 단위 직무 대분류 판정 (Gemini 호출).

    분류 입력은 role 단위 텍스트를 우선으로 하고,
    common_requirements는 context 참고용으로만 포함한다.
    """
    model_name = os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)

    # 분석용 필터 적용 — Gemini에 전달하기 전에 저직무구분력 문구 제거
    filtered_tasks = filter_generic_analysis_lines(main_tasks[:12])
    filtered_req = filter_generic_analysis_lines(requirements[:12])
    filtered_pref = filter_generic_analysis_lines(preferred[:6])
    filtered_common = filter_generic_analysis_lines(common_requirements[:6])

    payload_preview = {
        "company": company,
        "posting_title": posting_title,
        "source_category": source_category,
        "role_name": role_name,
        "main_tasks": filtered_tasks,
        "requirements": filtered_req,
        "preferred": filtered_pref,
        "common_requirements_context": filtered_common,
        "job_families": [{"id": f["id"], "display_name": f["display_name"]} for f in job_families],
    }

    prompt = f"""
당신은 채용공고의 개별 직무(role)를 직무 대분류로 매핑하는 분류기다.

아래는 복합공고 내 하나의 직무(role) 단위 정보다.
가장 적절한 job_family id를 1개만 판정하라.

- 단일 role 분류이므로 반드시 1개만 반환한다
- role_name, main_tasks, requirements를 우선 판단 근거로 사용한다
- common_requirements_context는 공통 자격요건 참고용이며 분류 기준으로 쓰지 마라
- 명확하지 않으면 "unknown"만 반환한다
- 출력은 반드시 JSON 배열만 반환한다 (마크다운 금지)

예시:
["backend"]
["marketing"]
["unknown"]

입력 데이터:
{json.dumps(payload_preview, ensure_ascii=False, indent=2)}
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
    detected_ids = _extract_json_array(raw_response)
    # role 단위는 1개만 허용
    if len(detected_ids) > 1:
        detected_ids = detected_ids[:1]
    return _normalize_families(detected_ids, job_families)


def run_classify_roles(
    batch_size: int = DEFAULT_BATCH_SIZE,
    db_path: str = DEFAULT_DB_PATH,
    families_path: str = DEFAULT_JOB_FAMILIES_PATH,
) -> None:
    """role 단위 직무 분류 실행.

    job_posting_roles 테이블에서 classification_status='pending'인 rows를 읽어
    role 단위로 Gemini 분류를 수행하고 job_posting_role_tags에 저장한다.
    새 로직은 extracted_role / posting-level job_tags에 의존하지 않는다.
    """
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise ValueError("GEMINI_API_KEY is required")

    effective_db_path = os.getenv("JD_DB_PATH", db_path)
    job_families = load_job_families(_resolve_path(families_path))
    conn = get_db_connection(effective_db_path)
    conn.row_factory = __import__("sqlite3").Row

    success_count = 0
    failed_count = 0

    print(f"[INFO] classify_mode=role_centric")
    print(f"[INFO] batch_size={batch_size}")
    print(f"[INFO] db_path={effective_db_path}")
    print(f"[INFO] gemini_model={os.getenv('GEMINI_MODEL', DEFAULT_GEMINI_MODEL)}")

    try:
        rows = get_pending_roles_for_classify(conn, batch_size)
        print(f"[INFO] pending_role_rows={len(rows)}")
        if not rows:
            print("[DONE] no pending roles.")
            return

        for row in rows:
            role_id = int(row["id"])
            role_name = str(row["role_name"] or "")
            company = str(row["company"] or "")
            posting_title = str(row["posting_title"] or "")
            source_category = str(row["source_category"] or "")

            main_tasks = json.loads(row["main_tasks_json"] or "[]")
            requirements = json.loads(row["requirements_json"] or "[]")
            preferred = json.loads(row["preferred_json"] or "[]")
            common_req = json.loads(row["common_requirements_json"] or "[]")

            print(f"[INFO] classify_role_id={role_id} role_name={role_name}")

            try:
                families = detect_job_family_for_role(
                    company=company,
                    posting_title=posting_title,
                    source_category=source_category,
                    role_name=role_name,
                    main_tasks=main_tasks if isinstance(main_tasks, list) else [],
                    requirements=requirements if isinstance(requirements, list) else [],
                    preferred=preferred if isinstance(preferred, list) else [],
                    common_requirements=common_req if isinstance(common_req, list) else [],
                    job_families=job_families,
                    api_key=api_key,
                )
                save_job_posting_role_tags(conn, role_id, families)
                update_role_classification_status(conn, role_id, "classified")
                conn.commit()
                success_count += 1
                print(f"[INFO] classified_role_families={families}")
            except GeminiQuotaExceededError as err:
                conn.rollback()
                update_role_classification_status(conn, role_id, "failed")
                conn.commit()
                failed_count += 1
                print(f"[ERROR] Gemini quota exceeded: {err}")
                print("[DONE] stop classify due to quota error.")
                break
            except Exception as err:
                conn.rollback()
                update_role_classification_status(conn, role_id, "failed")
                conn.commit()
                failed_count += 1
                print(f"[WARN] classify failed for role_id={role_id}: {err}")
    finally:
        conn.close()

    print(f"[DONE] success_count={success_count} failed_count={failed_count}")


def main() -> None:
    import argparse

    load_dotenv()
    default_db_path = os.getenv("JD_DB_PATH", DEFAULT_DB_PATH)

    parser = argparse.ArgumentParser(description="JD 직무 분류")
    parser.add_argument("--mode", choices=["roles", "postings"], default="roles",
                        help="분류 모드: roles(role 중심, 기본값) / postings(공고 레벨 레거시)")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE,
                        help=f"배치 크기 (기본값: {DEFAULT_BATCH_SIZE})")
    parser.add_argument("--db-path", default=default_db_path,
                        help=f"DB 경로 (기본값: JD_DB_PATH 환경변수 또는 {DEFAULT_DB_PATH})")
    args = parser.parse_args()

    if args.mode == "roles":
        run_classify_roles(batch_size=args.batch_size, db_path=args.db_path)
    else:
        run_classify(batch_size=args.batch_size, db_path=args.db_path)


if __name__ == "__main__":
    main()
