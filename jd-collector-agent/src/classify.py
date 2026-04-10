import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path, PureWindowsPath

from dotenv import load_dotenv
import google.generativeai as genai

from db import get_db_connection
from utils import GeminiQuotaExceededError, is_gemini_quota_error


DEFAULT_DB_PATH = r"C:\dev\jd_data.db"
DEFAULT_JOB_FAMILIES_PATH = r"C:\dev\job_families.json"
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


def prompt_with_default(message: str, default: str) -> str:
    value = input(f"{message} [{default}]: ").strip()
    return value or default


def main() -> None:
    load_dotenv()
    batch_size_text = prompt_with_default("batch_size", str(DEFAULT_BATCH_SIZE))
    if not batch_size_text.isdigit() or int(batch_size_text) <= 0:
        raise ValueError("batch_size must be a positive integer")

    default_db_path = os.getenv("JD_DB_PATH", DEFAULT_DB_PATH)
    db_path = prompt_with_default("db_path", default_db_path)

    run_classify(
        batch_size=int(batch_size_text),
        db_path=db_path,
    )


if __name__ == "__main__":
    main()
