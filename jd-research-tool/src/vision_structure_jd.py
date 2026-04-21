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
    # 새 스키마: roles 배열 정규화
    roles_raw = data.get("roles", [])
    if not isinstance(roles_raw, list):
        roles_raw = []

    roles = []
    for r in roles_raw:
        if not isinstance(r, dict):
            continue
        roles.append({
            "role_name": _as_string(r.get("role_name", "")),
            "main_tasks": _as_list(r.get("main_tasks", [])),
            "requirements": _as_list(r.get("requirements", [])),
            "preferred": _as_list(r.get("preferred", [])),
        })

    # LLM이 구버전 스키마(role/main_tasks 최상위)로 응답한 경우 roles로 변환
    if not roles and (data.get("role") or data.get("main_tasks")):
        roles = [{
            "role_name": _as_string(data.get("role", "")),
            "main_tasks": _as_list(data.get("main_tasks", [])),
            "requirements": _as_list(data.get("requirements", [])),
            "preferred": _as_list(data.get("preferred", [])),
        }]

    common_requirements = _as_list(data.get("common_requirements", []))
    common_preferred = _as_list(data.get("common_preferred", []))

    # collect.py 연결 유지용 shim — 첫 번째 role + common 정보를 기존 키에 매핑
    first_role = roles[0] if roles else {}
    shim_role = _as_string(first_role.get("role_name", ""))
    shim_main_tasks = _as_list(first_role.get("main_tasks", []))
    shim_requirements = common_requirements + _as_list(first_role.get("requirements", []))
    shim_preferred = common_preferred + _as_list(first_role.get("preferred", []))

    return {
        "company": _as_string(data.get("company", "")),
        "posting_title": _as_string(data.get("posting_title", "")),
        "common_requirements": common_requirements,
        "common_preferred": common_preferred,
        "roles": roles,
        "raw_text": _as_string(data.get("raw_text", raw_text), raw_text),
        "source_images": _as_list(data.get("source_images", [])),
        # collect.py 호환 shim (기존 단일 role 읽기 경로 유지)
        "role": shim_role,
        "main_tasks": shim_main_tasks,
        "requirements": shim_requirements,
        "preferred": shim_preferred,
    }


def structure_jd_images(image_paths: list[str]) -> dict:
    """
    Convert job description images directly to structured JD JSON using Gemini Vision.
    복합공고는 roles 배열로 분리, 공통 자격요건은 common_requirements로 추출.

    Args:
        image_paths: List of file paths to PNG images

    Returns:
        Structured JD data dict with schema:
        {
            "company": str,
            "posting_title": str,
            "common_requirements": list[str],
            "common_preferred": list[str],
            "roles": [{"role_name": str, "main_tasks": list, "requirements": list, "preferred": list}],
            "raw_text": str,
            "source_images": list[str],
            # collect.py compat shim:
            "role": str,
            "main_tasks": list[str],
            "requirements": list[str],
            "preferred": list[str],
        }
    """
    load_dotenv()

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not set. Please check your .env file.")

    client = genai.Client(api_key=api_key)

    image_parts = []
    for image_path in image_paths:
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

    prompt = """아래 채용공고 이미지들을 분석하여 다음 JSON 스키마로 구조화해 주세요.
반드시 JSON 객체만 출력하세요. 코드블록은 사용하지 마세요.
누락된 정보는 빈 문자열 또는 빈 배열로 채우세요.

[구조화 규칙]
1. 공고에 여러 모집부문·과제·트랙·직무 블록이 있으면 roles 배열에 각각 분리하세요. 절대 하나로 합치지 마세요.
2. 단일 직무 공고라도 roles 배열에 1개 요소로 넣으세요.
3. 모든 지원자에게 공통으로 적용되는 지원자격은 common_requirements에 넣으세요.
4. 모든 지원자에게 공통으로 적용되는 우대사항은 common_preferred에 넣으세요.
5. 특정 role에만 해당하는 자격요건·우대사항은 해당 role의 requirements·preferred에 넣으세요.
6. role별 정보가 불명확하면 빈 배열을 허용합니다. 억지로 채우지 마세요.
7. 이미지가 여러 장이면 모든 이미지를 빠짐없이 읽고 종합하세요.
8. main_tasks, requirements, preferred는 각 항목을 별도 배열 요소로 구분하세요. 항목이 10개 이상이어도 전부 배열에 넣으세요.
9. raw_text에는 이미지에서 추출한 실제 텍스트를 최대한 정확히 기입하세요.
10. source_images 필드는 빈 배열로 두세요.

스키마:
{
  "company": "회사명",
  "posting_title": "공고 제목",
  "common_requirements": ["공통 지원자격1", "공통 지원자격2"],
  "common_preferred": ["공통 우대사항1"],
  "roles": [
    {
      "role_name": "직무/모집부문 명칭",
      "main_tasks": ["담당업무1", "담당업무2"],
      "requirements": ["이 직무 전용 자격요건1"],
      "preferred": ["이 직무 전용 우대사항1"]
    }
  ],
  "raw_text": "이미지에서 추출한 전체 텍스트",
  "source_images": []
}"""

    prompt_part = types.Part.from_text(text=prompt)
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

    source_image_names = [Path(img_path).name for img_path in image_paths]
    data["source_images"] = source_image_names

    return _normalize_schema(data)
