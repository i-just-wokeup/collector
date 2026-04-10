import json
import re
from datetime import datetime
from pathlib import Path

CORE_SECTION_KEYWORDS = [
    "주요 업무", "주요업무",
    "담당 업무", "담당업무",
    "자격 요건", "자격요건",
    "지원 자격", "지원자격",
    "우대 사항", "우대사항",
    "요구 사항", "요구사항",
    "주요 직무", "주요직무",
    "필수 자격", "필수자격",
    "requirements",
    "responsibilities",
    "preferred",
    "qualifications",
]

TECH_KEYWORDS = [
    "api",
    "백엔드",
    "backend",
    "서버",
    "db",
    "sql",
    "nosql",
    "aws",
    "docker",
    "kubernetes",
    "spring",
    "java",
    "kotlin",
    "python",
    "django",
    "fastapi",
    "node.js",
    "react",
    "typescript",
    "linux",
    "redis",
    "kafka",
    "orm",
    "query",
    "인프라",
    "클라우드",
    "배포",
    "최적화",
    "설계",
    "개발",
    "운영",
]

SOFT_SKILL_KEYWORDS = [
    "성실",
    "책임감",
    "소통",
    "협업",
    "협업 능력",
    "성장 지향",
    "긍정적 태도",
    "고객 만족",
    "진취적",
    "주도적",
]

QUOTA_ERROR_KEYWORDS = [
    "rate limit",
    "quota",
    "resourceexhausted",
    "429",
]

RAW_TEXT_CUT_KEYWORDS = [
    "기업 정보",
    "복지",
    "리뷰",
    "추천 공고",
    "다른 공고",
]


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def slugify(text: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9가-힣_-]+", "_", text.strip())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned or "job"


def extract_job_id(url: str) -> str:
    """
    Extract job ID from URL regardless of parameters.
    Deduplicates URLs that differ only in view_type or other params.

    Patterns:
    - 사람인: rec_idx=숫자
    - 원티드: /wd/숫자
    - 잡코리아: GI_Read/숫자
    """
    # 사람인
    match = re.search(r'rec_idx=(\d+)', url)
    if match:
        return f"saramin_{match.group(1)}"

    # 원티드
    match = re.search(r'/wd/(\d+)', url)
    if match:
        return f"wanted_{match.group(1)}"

    # 잡코리아
    match = re.search(r'GI_Read/(\d+)', url)
    if match:
        return f"jobkorea_{match.group(1)}"

    # ID를 찾지 못하면 전체 URL 반환
    return url


def load_seen_urls(path: Path) -> set[str]:
    if not path.exists():
        return set()
    seen = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            job_id = extract_job_id(line)
            seen.add(job_id)
    return seen


def append_seen_url(path: Path, url: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    job_id = extract_job_id(url)
    with path.open("a", encoding="utf-8") as f:
        f.write(job_id + "\n")


def count_json_files(path: Path) -> int:
    if not path.exists():
        return 0
    return len(list(path.glob("*.json")))


def save_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def select_images_for_ocr(source_images: list[Path], max_images: int = 3) -> list[Path]:
    if len(source_images) <= max_images:
        return source_images
    return source_images[:max_images]


def trim_raw_text_noise(raw_text: str) -> str:
    text = (raw_text or "").strip()
    if not text:
        return ""
    cut_idx = len(text)
    lowered = text.lower()
    for keyword in RAW_TEXT_CUT_KEYWORDS:
        idx = lowered.find(keyword.lower())
        if idx != -1 and idx < cut_idx:
            cut_idx = idx
    return text[:cut_idx].strip()


class GeminiQuotaExceededError(RuntimeError):
    pass


def is_gemini_quota_error(error: object) -> bool:
    message = str(error).lower()
    return any(keyword in message for keyword in QUOTA_ERROR_KEYWORDS)


def guess_job_family(role_text: str, fallback_target_role: str) -> str:
    text = (role_text or "").lower()
    rules = {
        "backend": ["backend", "백엔드", "서버", "api"],
        "frontend": ["frontend", "프론트", "react", "vue"],
        "data": ["data", "데이터", "analytics", "분석", "ml", "ai"],
        "marketing": ["marketing", "마케팅", "퍼포먼스", "그로스"],
        "pm": ["pm", "product manager", "프로덕트 매니저", "기획"],
    }
    for family, keywords in rules.items():
        if any(keyword in text for keyword in keywords):
            return family
    return fallback_target_role


def ensure_enriched_schema(
    payload: dict,
    *,
    company: str,
    posting_title: str,
    source_site: str,
    source_url: str,
    seniority_text: str,
    employment_type: str,
    target_role: str,
    classification_result: str,
    source_images: list[str],
    captured_at: str,
    search_keyword: str,
    output_job_folder_name: str,
    site_name: str,
    job_id: str,
) -> dict:
    data = payload if isinstance(payload, dict) else {}

    role_text = str(data.get("role", "") or "")
    company_text = str(company or data.get("company", "") or "")
    job_family_guess = guess_job_family(role_text, target_role)

    def _as_str(value: object, default: str = "") -> str:
        if value is None:
            return default
        return str(value)

    def _as_str_list(value: object, fallback: list[str] | None = None) -> list[str]:
        if isinstance(value, list):
            return [_as_str(v).strip() for v in value if _as_str(v).strip()]
        if fallback is not None:
            return [_as_str(v).strip() for v in fallback if _as_str(v).strip()]
        return []

    normalized = {
        "company": company_text,
        "role": role_text,
        "posting_title": _as_str(posting_title or data.get("posting_title", "") or ""),
        "source_site": _as_str(data.get("source_site", "") or source_site or ""),
        "source_url": _as_str(data.get("source_url", "") or source_url or ""),
        "main_tasks": _as_str_list(data.get("main_tasks", [])),
        "requirements": _as_str_list(data.get("requirements", [])),
        "preferred": _as_str_list(data.get("preferred", [])),
        "seniority_text": _as_str(seniority_text or data.get("seniority_text", "") or ""),
        "employment_type": _as_str(employment_type or data.get("employment_type", "") or ""),
        "job_family_guess": _as_str(data.get("job_family_guess", "") or job_family_guess or ""),
        "classification_result": _as_str(data.get("classification_result", "") or classification_result or ""),
        "raw_text": _as_str(data.get("raw_text", "") or ""),
        "source_images": _as_str_list(data.get("source_images", []), fallback=source_images),
        "collector_meta": data.get("collector_meta", {}) if isinstance(data.get("collector_meta", {}), dict) else {},
    }

    meta = normalized["collector_meta"]
    meta_defaults = {
        "captured_at": captured_at or "",
        "search_keyword": search_keyword or "",
        "target_role": target_role or "",
        "output_job_folder_name": output_job_folder_name or "",
        "site_name": site_name or "",
        "job_id": job_id or "",
    }
    for key, value in meta_defaults.items():
        meta[key] = _as_str(meta.get(key, "") or value)

    normalized["collector_meta"] = meta
    return normalized


def detect_core_sections(raw_text: str) -> list[str]:
    text = (raw_text or "").lower()
    detected = []
    for keyword in CORE_SECTION_KEYWORDS:
        if keyword.lower() in text:
            detected.append(keyword)
    return detected


def assess_capture_failed(raw_text: str, capture_image_count: int) -> tuple[bool, list[str], list[str]]:
    text = (raw_text or "").strip()
    text_len = len(text)
    detected = detect_core_sections(text)
    reasons: list[str] = []

    if not detected and text_len < 300:
        reasons.append("missing_core_sections")

    if capture_image_count <= 1 and text_len < 900:
        reasons.append("one_image_short_text")

    return (len(reasons) > 0), reasons, detected


def _keyword_hit_count(text: str, keywords: list[str]) -> int:
    lowered = (text or "").lower()
    return sum(1 for keyword in keywords if keyword.lower() in lowered)


def assess_low_quality_job(payload: dict) -> tuple[bool, list[str]]:
    main_tasks = payload.get("main_tasks", []) if isinstance(payload.get("main_tasks", []), list) else []
    requirements = payload.get("requirements", []) if isinstance(payload.get("requirements", []), list) else []
    preferred = payload.get("preferred", []) if isinstance(payload.get("preferred", []), list) else []

    reasons: list[str] = []

    if len(main_tasks) <= 1:
        reasons.append("too_few_main_tasks")
    if len(requirements) <= 1:
        reasons.append("too_few_requirements")

    core_text = " ".join([str(x) for x in (main_tasks + requirements)])
    tech_hits = _keyword_hit_count(core_text, TECH_KEYWORDS)
    if tech_hits <= 1:
        reasons.append("low_technical_signal")

    if len(preferred) >= 4 and len(main_tasks) <= 2 and len(requirements) <= 2:
        reasons.append("preferred_overweight")

    preferred_texts = [str(x) for x in preferred]
    if preferred_texts:
        soft_lines = sum(1 for line in preferred_texts if _keyword_hit_count(line, SOFT_SKILL_KEYWORDS) > 0)
        if len(preferred_texts) >= 3 and (soft_lines / len(preferred_texts)) >= 0.7:
            reasons.append("mostly_soft_skills")

    return (len(reasons) >= 2), reasons


def select_images_for_ocr(source_images: list[Path], max_images: int = 3) -> list[Path]:
    if len(source_images) <= max_images:
        return source_images
    return source_images[:max_images]
