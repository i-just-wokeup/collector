import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types


def _strip_json_code_fence(content: str) -> str:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _escape_invalid_backslashes(content: str) -> str:
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


def _normalize_schema(data: dict, raw_text: str = "") -> dict:
    return {
        "company": _as_string(data.get("company", "")),
        "role": _as_string(data.get("role", "")),
        "main_tasks": _as_list(data.get("main_tasks", [])),
        "requirements": _as_list(data.get("requirements", [])),
        "preferred": _as_list(data.get("preferred", [])),
        "raw_text": _as_string(data.get("raw_text", raw_text), raw_text),
        "source_images": _as_list(data.get("source_images", [])),
    }


def structure_jd_images(image_paths: list[str]) -> dict:
    """
    Convert job description images directly to structured JD JSON using Gemini Vision.

    Args:
        image_paths: List of file paths to PNG images

    Returns:
        Structured JD data dict with schema:
        {
            "company": str,
            "role": str,
            "main_tasks": list[str],
            "requirements": list[str],
            "preferred": list[str],
            "raw_text": str,
            "source_images": list[str]
        }
    """
    load_dotenv()

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not set. Please check your .env file.")

    client = genai.Client(api_key=api_key)

    # Prepare image parts for Gemini Vision
    image_parts = []
    for idx, image_path in enumerate(image_paths, start=1):
        path_obj = Path(image_path)
        if not path_obj.exists():
            raise FileNotFoundError(f"Image file not found: {image_path}")

        with open(image_path, "rb") as f:
            image_data = f.read()

        image_parts.append(
            types.Part.from_bytes(
                data=image_data,
                mime_type="image/png",
            )
        )

    # Build prompt
    prompt = """아래 채용공고 이미지들을 분석하여 다음 JSON 스키마로 구조화해 주세요.
반드시 JSON 객체만 출력하세요. 코드블록은 사용하지 마세요.
누락된 정보는 빈 문자열 또는 빈 배열로 채우세요.

스키마:
{
  "company": "회사명",
  "role": "직책/직급",
  "main_tasks": ["주요업무1", "주요업무2"],
  "requirements": ["필수요건1", "필수요건2"],
  "preferred": ["우대사항1", "우대사항2"],
  "raw_text": "이미지에서 추출한 전체 텍스트",
  "source_images": []
}

주의사항:
- 이미지가 여러 페이지로 나뉘면 모든 페이지를 종합하여 정보를 추출하세요.
- main_tasks, requirements, preferred는 각 항목을 별도 배열 요소로 구분하세요.
- requirements는 이미지에 보이는 자격요건/지원자격/응시자격 항목을 하나도 빠짐없이 모두 추출하세요. 요약하거나 합치지 마세요.
- main_tasks는 주요업무/담당업무 항목을 모두 추출하세요.
- preferred는 우대사항 항목을 모두 추출하세요.
- 항목이 10개 이상이어도 전부 배열에 넣으세요. 개수 제한 없음.
- 이미지가 여러 장이면 모든 이미지를 빠짐없이 읽고 종합하세요.
- raw_text에는 이미지에서 추출한 실제 텍스트를 최대한 정확히 기입하세요.
- source_images 필드는 빈 배열로 두세요. (나중에 파일명으로 채워집니다)"""

    # Combine text prompt and image parts
    prompt_part = types.Part.from_text(text = prompt)
    contents = [prompt_part] + image_parts

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=contents,
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

    # Add source image filenames
    source_image_names = [Path(img_path).name for img_path in image_paths]
    data["source_images"] = source_image_names

    return _normalize_schema(data)
