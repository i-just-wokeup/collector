import os
import re

from dotenv import load_dotenv
import google.generativeai as genai
from utils import GeminiQuotaExceededError, is_gemini_quota_error


VALID_LABELS = {"match", "not_match", "unknown"}


def classify_target_role(target_role: str, jd_payload: dict) -> str:
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("[WARN] GEMINI_API_KEY is missing. classify -> unknown")
        return "unknown"

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.5-flash")

    prompt = f"""
당신은 채용공고 직무 적합도 판정기다.

목표 직무(target_role): {target_role}

아래 공고 정보가 target_role 수집 대상인지 판정하라.
출력은 반드시 아래 셋 중 하나의 문자열만 출력하라.
- match
- not_match
- unknown

판정 기준:
- match: target_role 중심 공고
- not_match: target_role이 아님
- unknown: 혼합 직무 / 애매함 / 중심 직무 불명확

공고 정보:
- posting_title: {jd_payload.get('posting_title', '')}
- company: {jd_payload.get('company', '')}
- role: {jd_payload.get('role', '')}
- main_tasks: {jd_payload.get('main_tasks', [])}
- requirements: {jd_payload.get('requirements', [])}
- preferred: {jd_payload.get('preferred', [])}
- seniority_text: {jd_payload.get('seniority_text', '')}
- employment_type: {jd_payload.get('employment_type', '')}
"""

    try:
        response = model.generate_content(prompt)
        raw = (response.text or "").strip().lower()
        label = re.sub(r"[^a-z_]", "", raw.splitlines()[0]) if raw else ""
        if label in VALID_LABELS:
            return label
    except Exception as err:
        if is_gemini_quota_error(err):
            raise GeminiQuotaExceededError(str(err)) from err
        print(f"[WARN] Gemini classify failed: {err}")

    return "unknown"
