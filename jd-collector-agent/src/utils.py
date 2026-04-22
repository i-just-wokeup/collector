import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, List

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

RAW_TEXT_CUT_KEYWORDS: list[str] = []

# ──────────────────────────────────────────────
# UI 노이즈 제거 상수
# ──────────────────────────────────────────────

# 이 키워드 이후 텍스트를 잘라낸다 (구간 절단)
# 주의: 공고 본문 이후 하단에만 등장하는 키워드만 넣어야 한다.
# 상단 네비게이션에도 나올 수 있는 키워드는 UI_NOISE_LINE_KEYWORDS(줄 단위 제거)로 처리한다.
UI_NOISE_CUT_KEYWORDS: list[str] = []

# 줄 단위로 제거할 공통 노이즈 문구
UI_NOISE_LINE_KEYWORDS: list[str] = [
    "합격확률",
    "공채정보",
    "신입·인턴",
    "기업·연봉",
    "취업톡톡",
    "취업특강",
    "기업 서비스",
    "지원자 현황 통계",
    "이 공고에 지원할까",
    "로그인하면",
    "본 채용정보는",
    "무단전재",
    "재배포",
    "채용정보에 잘못된 내용이 있을 경우",
    "맨 위로",
    "오늘 본 공고",
    "비슷한 조건의 AI 추천공고",
    "지도보기",
    "희망기업",
    "JOB 접기",
    "JOB 정기",
    "가족친화인증기업 채용관",
    "적합도 체크",
    "AI 추천공고",
    "제공된 정보는 업무 외 다른 용도로 사용되지 않습니다",
]

# 잡코리아 전용 노이즈 줄 키워드
UI_NOISE_LINE_KEYWORDS_JOBKOREA: list[str] = [
    "기업정보 더보기",
    "합격 자소서",
    "면접후기",
    "이 기업의 취업전략",
    "다른공고",
]

# 사람인 전용 노이즈 줄 키워드
UI_NOISE_LINE_KEYWORDS_SARAMIN: list[str] = [
    "채용중인 기업",
    "지원현황",
]

# ──────────────────────────────────────────────
# 저가치 문장 필터 상수
# ──────────────────────────────────────────────

# 분류/분석 단계에서만 적용하는 저직무구분력 필터 패턴
# DB 저장 전에는 사용하지 않는다 — raw_text/role 원본을 오염시키지 않기 위해.
# classify.py / analyze.py에서 Gemini에 보내기 전 텍스트 정제에 사용한다.
GENERIC_ANALYSIS_FILTER_PATTERNS: list[str] = [
    # 범용 학력 (직무 구분력 없음)
    "학사 이상", "학사이상", "대졸 이상", "대졸이상",
    "고졸 이상", "고졸이상", "전공 무관", "전공무관",
    "초대졸 이상", "초대졸이상", "학력 무관", "학력무관",
    "4년제 이상", "2,3년제 이상",
    # 추상 소프트스킬 (직무 구분력 낮음)
    "긍정적인 마인드", "긍정적 마인드", "긍정적인 태도",
    "적극적인 자세", "적극적인 성격",
    "팀워크 우수자", "팀플레이어",
    "원활한 소통 능력", "원활한 커뮤니케이션",
    "능동적인 자세",
    # 법정/형식 공통 문구 (이미 LOW_VALUE_LINE_PATTERNS에서 storage 단계에 제거되므로 중복 무방)
    "해외여행 결격사유", "병역필 또는 면제", "보훈대상자",
    "장애인 우대", "국가보훈", "취업보호대상자",
    "즉시출근 가능자",
]

# 이 패턴이 포함된 문장은 직무 기준 생성에 무가치하다
LOW_VALUE_LINE_PATTERNS: list[str] = [
    "해외여행 결격사유",
    "해외영업에 결격",
    "해외여행에 결격",
    "남자의 경우 군필",
    "병역필 또는 면제",
    "보훈대상자 우대",
    "취업보호대상자",
    "장애인 우대",
    "즉시출근",
    "근무지 인근 거주자",
    "채용 시 마감",
    "이력(경력) 능력 보유자",
    "보훈 대상자",
    "국가 보훈",
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


def _compact(text: str) -> str:
    """공백 제거 정규화 — OCR 자간 노이즈 대응용 (매칭 전용, 원문 수정 아님)"""
    return re.sub(r"\s+", "", text)


def clean_job_posting_text(raw_text: str, source_site: str = "") -> str:
    """
    raw_text에서 UI 노이즈를 제거한 정제본을 반환한다.
    raw_text 원본은 수정하지 않는다 — 이 함수의 반환값만 분석/판정에 활용해라.
    """
    text = (raw_text or "").strip()
    if not text:
        return ""

    site = (source_site or "").lower()

    site_specific: list[str] = []
    if site == "jobkorea":
        site_specific = UI_NOISE_LINE_KEYWORDS_JOBKOREA
    elif site == "saramin":
        site_specific = UI_NOISE_LINE_KEYWORDS_SARAMIN
    all_line_noise = UI_NOISE_LINE_KEYWORDS + site_specific
    compact_noise = [_compact(kw.lower()) for kw in all_line_noise]

    clean_lines = []
    for line in text.splitlines():
        line_lower = line.lower()
        compact_line = _compact(line_lower)
        if any(kw.lower() in line_lower for kw in all_line_noise):
            continue
        if any(cnoise in compact_line for cnoise in compact_noise):
            continue
        clean_lines.append(line)

    return "\n".join(clean_lines).strip()


def is_low_value_requirement_line(text: str) -> bool:
    """
    requirements / preferred / main_tasks 한 줄이 직무 기준 생성에 무가치한지 판정한다.
    빈 줄 또는 LOW_VALUE_LINE_PATTERNS 해당 시에만 제거한다.
    """
    line = (text or "").strip()
    if not line:
        return True

    line_lower = line.lower()
    return any(pattern.lower() in line_lower for pattern in LOW_VALUE_LINE_PATTERNS)


def filter_low_value_lines(lines: list[str]) -> list[str]:
    """
    requirements / preferred / main_tasks 리스트에서 저가치 문장을 제거한 리스트를 반환한다.
    원본 리스트는 수정하지 않는다.
    DB 저장 전 단계에서 사용한다.
    """
    if not isinstance(lines, list):
        return []
    return [line for line in lines if not is_low_value_requirement_line(line)]


def filter_generic_analysis_lines(lines: list[str]) -> list[str]:
    """분류/분석 단계에서만 적용하는 저직무구분력 문장 제거 필터.

    classify.py / analyze.py에서 Gemini에 전달하기 전 텍스트 정제에 사용한다.
    DB 저장 전이나 raw_text에는 절대 사용하지 말 것.
    """
    if not isinstance(lines, list):
        return []
    result = []
    for line in lines:
        text = str(line or "").strip()
        if not text:
            continue
        text_lower = text.lower()
        if any(p.lower() in text_lower for p in GENERIC_ANALYSIS_FILTER_PATTERNS):
            continue
        result.append(text)
    return result


def clean_role_first_task(role_name: str, main_tasks: list[str]) -> list[str]:
    """main_tasks 첫 줄이 role_name과 사실상 동일한 직무명 반복이면 제거한다.

    DB 저장 전 role 텍스트 정제 단계에서 사용한다.
    """
    if not main_tasks or not role_name:
        return main_tasks
    first = str(main_tasks[0] or "").strip()
    if not first:
        return main_tasks
    role = role_name.strip()
    first_compact = re.sub(r"\s+", "", first.lower())
    role_compact = re.sub(r"\s+", "", role.lower())
    # 첫 항목이 role_name 자체이거나 role_name을 포함하면서 짧은 경우
    if first_compact == role_compact:
        return main_tasks[1:]
    if role_compact and role_compact in first_compact and len(first_compact) <= len(role_compact) + 8:
        return main_tasks[1:]
    return main_tasks


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


# 소프트 경고를 bypass할 수 있는 본문 전용 locator 선택자
_BODY_LOCATOR_SELECTORS = {".artRead", ".detail", "iframe:body"}


def _is_body_locator_capture(capture_meta: dict) -> tuple[bool, str]:
    """iframe/본문 locator 캡처가 사용됐는지 확인. (bypass 여부, bypass 사유) 반환."""
    if capture_meta.get("iframe_capture_used"):
        return True, "iframe_body"
    selector = str(capture_meta.get("locator_capture_selector", "") or "")
    if selector in _BODY_LOCATOR_SELECTORS:
        return True, "locator_body"
    return False, ""


def _has_structured_content(jd_payload: dict) -> bool:
    """Gemini 구조화 결과에 유의미한 내용이 있는지 확인."""
    for key in ("main_tasks", "requirements", "preferred"):
        val = jd_payload.get(key, [])
        if isinstance(val, list) and len(val) >= 2:
            return True
    return bool(str(jd_payload.get("role", "") or "").strip())


def assess_capture_failed(
    raw_text: str,
    capture_image_count: int,
    capture_meta: Optional[dict] = None,
    jd_payload: Optional[dict] = None,
) -> tuple[bool, list[str], list[str], list[str], str]:
    """캡처 품질을 평가한다.

    Returns:
        hard_failed: True이면 저장 차단 (failed_capture)
        hard_reasons: 하드 실패 사유 목록
        soft_warns: 경고만, 저장 차단 안 함
        detected_sections: 탐지된 핵심 섹션 키워드
        gate_bypass_reason: one_image_short_text 조건이 bypass된 경우 그 사유 (없으면 "")

    하드 실패 기준 (저장 차단):
        - missing_core_sections: 핵심 섹션 탐지 없음 + 텍스트 200자 미만

    소프트 경고 기준 (저장 통과, 로그만):
        - one_image_short_text: 이미지 1장 이하 + 텍스트 900자 미만
          단, iframe/본문 locator 캡처 사용 시 또는 Gemini 구조화 결과 유효 시 bypass
    """
    text = (raw_text or "").strip()
    text_len = len(text)
    detected = detect_core_sections(text)
    hard_reasons: list[str] = []
    soft_warns: list[str] = []
    gate_bypass_reason = ""

    # 하드 실패: 핵심 섹션 전혀 없고 텍스트도 거의 비어 있음
    if not detected and text_len < 200:
        hard_reasons.append("missing_core_sections")

    # 소프트 경고 후보: 이미지 1장 이하 + 짧은 텍스트
    if capture_image_count <= 1 and text_len < 900:
        _meta = capture_meta or {}
        _payload = jd_payload or {}

        bypassed, bypass_reason = _is_body_locator_capture(_meta)
        if not bypassed and _has_structured_content(_payload):
            bypassed, bypass_reason = True, "structured_content_present"

        if bypassed:
            gate_bypass_reason = bypass_reason
        else:
            soft_warns.append("one_image_short_text")

    return (len(hard_reasons) > 0), hard_reasons, soft_warns, detected, gate_bypass_reason


def _keyword_hit_count(text: str, keywords: list[str]) -> int:
    lowered = (text or "").lower()
    return sum(1 for keyword in keywords if keyword.lower() in lowered)


def _assess_role_level_quality(roles: list, structured_payload: dict) -> list[str]:
    """복합공고 role 배열 기준 품질 문제를 판정한다. role 수 >= 3일 때만 적용."""
    reasons: list[str] = []
    if not isinstance(roles, list) or len(roles) < 3:
        return reasons

    roles_count = len(roles)

    # 많은 role인데 main_tasks가 있는 role이 30% 미만
    roles_with_tasks = sum(
        1 for r in roles
        if isinstance(r, dict) and len(r.get("main_tasks", []) or []) >= 2
    )
    if roles_with_tasks / roles_count < 0.3:
        reasons.append("shallow_aggregate_empty_tasks")

    # role별 총 콘텐츠보다 common_* 가 많음 (공통 문구만 남은 패턴)
    common_req = structured_payload.get("common_requirements") or []
    common_pref = structured_payload.get("common_preferred") or []
    common_total = len(common_req if isinstance(common_req, list) else []) + \
                   len(common_pref if isinstance(common_pref, list) else [])
    role_specific_total = sum(
        len(r.get("main_tasks", []) or [])
        + len(r.get("requirements", []) or [])
        + len(r.get("preferred", []) or [])
        for r in roles if isinstance(r, dict)
    )
    if common_total >= 3 and role_specific_total < common_total:
        reasons.append("common_only_no_role_detail")

    return reasons


def assess_low_quality_job(
    payload: dict,
    roles: Optional[list] = None,
    structured_payload: Optional[dict] = None,
) -> tuple[bool, list[str]]:
    """공고 품질을 판정한다.

    Args:
        payload: ensure_enriched_schema 이후의 normalized payload (shim 필드 포함).
        roles: structured_jd_payload의 roles[] 배열 (복합공고 role 단위 품질 판정에 사용).
        structured_payload: structured_jd_payload 전체 (common_requirements 접근에 사용).

    Returns:
        (is_low_quality, reasons)
    """
    main_tasks = payload.get("main_tasks", []) if isinstance(payload.get("main_tasks", []), list) else []
    requirements = payload.get("requirements", []) if isinstance(payload.get("requirements", []), list) else []
    preferred = payload.get("preferred", []) if isinstance(payload.get("preferred", []), list) else []

    reasons: list[str] = []

    # 단일 role 기준 체크 (shim 기반 — roles 없거나 1개짜리 공고에서 주로 적용)
    if len(main_tasks) <= 1:
        reasons.append("too_few_main_tasks")
    if len(requirements) <= 1:
        reasons.append("too_few_requirements")

    if len(preferred) >= 4 and len(main_tasks) <= 2 and len(requirements) <= 2:
        reasons.append("preferred_overweight")

    preferred_texts = [str(x) for x in preferred]
    if preferred_texts:
        soft_lines = sum(1 for line in preferred_texts if _keyword_hit_count(line, SOFT_SKILL_KEYWORDS) > 0)
        if len(preferred_texts) >= 3 and (soft_lines / len(preferred_texts)) >= 0.7:
            reasons.append("mostly_soft_skills")

    # role 단위 품질 체크 (복합공고 — roles[]가 있을 때만)
    if roles is not None:
        role_reasons = _assess_role_level_quality(roles, structured_payload or {})
        reasons.extend(role_reasons)

    return (len(reasons) >= 2), reasons


def is_aggregate_posting(raw_text: str, structured_roles_count: int = 0) -> tuple[bool, list[str]]:
    """집계형 공고(여러 회사/직무를 한 페이지에 모은 공고)를 휴리스틱으로 판별한다.

    false positive를 최소화하기 위해 복수 신호가 동시에 발생할 때만 true 반환.
    단, roles 수가 극단적으로 많은 경우에는 단독 신호로도 판정.
    """
    text = raw_text or ""
    reasons: list[str] = []

    apply_link_count = text.count("접수바로가기")
    if apply_link_count >= 5:
        reasons.append(f"접수바로가기_count={apply_link_count}")

    # 일반 공고에도 등장할 수 있어 기준을 높게 설정
    apply_btn_count = text.count("지원하기")
    if apply_btn_count >= 10:
        reasons.append(f"지원하기_count={apply_btn_count}")

    if structured_roles_count >= 15:
        reasons.append(f"roles_count={structured_roles_count}")

    # 극단적인 경우 단독 신호로도 판정 (roles >= 30)
    if structured_roles_count >= 30:
        return True, reasons

    return (len(reasons) >= 2), reasons


def select_images_for_ocr(source_images: list[Path], max_images: int = 3) -> list[Path]:
    if len(source_images) <= max_images:
        return source_images
    return source_images[:max_images]


def prepare_ocr_image(source: Path, dest: Path, max_width: int = 800) -> None:
    """OCR용 이미지를 전처리하여 PNG로 저장한다.
    처리 순서: 그레이스케일 → 너비 max_width 초과 시 비율 유지 리사이즈 → 대비 1.3배 강화
    Pillow 미설치 또는 변환 실패 시 원본을 그대로 복사한다.
    downstream이 PNG 기준이므로 저장 포맷은 PNG로 유지한다.
    """
    try:
        from PIL import Image, ImageEnhance  # type: ignore[import]
        img = Image.open(source).convert("L")
        w, h = img.size
        if w > max_width:
            new_h = int(h * max_width / w)
            img = img.resize((max_width, new_h), Image.LANCZOS)
        img = ImageEnhance.Contrast(img).enhance(1.3)
        dest_png = dest.with_suffix(".png")
        img.save(dest_png, format="PNG")
        if dest_png != dest:
            dest_png.rename(dest)
    except Exception:
        import shutil
        shutil.copy2(source, dest)
