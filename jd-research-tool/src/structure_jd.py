import json
import os
import re

from dotenv import load_dotenv
from google import genai


def _strip_json_code_fence(content: str) -> str:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _escape_invalid_backslashes(content: str) -> str:
    # Escape only backslashes that are not valid JSON escape starters.
    return re.sub(r'\\(?!["\\/bfnrtu])', r"\\\\", content)


def _as_string(value, default: str = "") -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return default
    return str(value)


def _as_list(value) -> list:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    return [value]


def _normalize_schema(data: dict, raw_text: str) -> dict:
    return {
        "company": _as_string(data.get("company", "")),
        "role": _as_string(data.get("role", "")),
        "main_tasks": _as_list(data.get("main_tasks", [])),
        "requirements": _as_list(data.get("requirements", [])),
        "preferred": _as_list(data.get("preferred", [])),
        "raw_text": _as_string(data.get("raw_text", raw_text), raw_text),
        "source_images": _as_list(data.get("source_images", [])),
    }


def structure_jd_text(raw_text: str) -> dict:
    """
    Convert OCR text to structured JD JSON using Gemini.
    """
    load_dotenv()

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not set. Please check your .env file.")

    client = genai.Client(api_key=api_key)

    prompt = f"""
아래 채용공고 텍스트를 다음 JSON 스키마로 구조화해 주세요.
반드시 JSON 객체만 출력하세요. 코드블록은 사용하지 마세요.
누락된 정보는 빈 문자열 또는 빈 배열로 채우세요.

스키마:
{{
  "company": "",
  "role": "",
  "main_tasks": [],
  "requirements": [],
  "preferred": [],
  "raw_text": "",
  "source_images": []
}}

채용공고 원문:
{raw_text}
"""

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
    )
    raw_response = response.text or ""
    content = _strip_json_code_fence(raw_response)

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        safe_content = _escape_invalid_backslashes(content)
        try:
            data = json.loads(safe_content)
        except json.JSONDecodeError as second_error:
            print("[DEBUG] Failed to parse Gemini JSON response.")
            print(f"[DEBUG] Response preview: {raw_response[:500]!r}")
            raise second_error

    if not isinstance(data, dict):
        raise ValueError("Gemini response is not a JSON object.")

    return _normalize_schema(data, raw_text)
