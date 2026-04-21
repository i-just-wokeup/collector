"""
verify_filter.py
filter 적용 전후 비교 검증 스크립트 (수집 완료 후 안정된 파일 대상)
사용: python scripts/verify_filter.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from utils import (
    clean_job_posting_text,
    detect_core_sections,
    filter_low_value_lines,
)

SEP = "=" * 60

# ── 샘플 1: 섹션 라인 필터 -백엔드 JD (넥슨) ────────────────────
SAMPLE_NEXON_PREFERRED = [
    "대규모 트래픽 처리 시스템 개발 경험 이 있으신 분",
    "클린 아키텍처, DDD 기반 설계 경험 이 있으신 분",
    "Redis, Kafka 등 캐시 / 메시징 시스템 활용 경험 이 있으신 분",
    "모니터링 / 로그 / 트레이싱 (Grafana, Prometheus, ELK) 구축 경험 이 있으신 분",
    "자기 주도적 업무 수행 및 협업 능력을 보유하신 분",
    "게임 서비스 백엔드 개발 경험 또는 게임 도메인 이해도가 높으신 분",
    "국가 보훈 대상자 및 장애인은 관련 법령에 의거하여 우대합니다.",
    "입사 후 3개월간 수습 기간이 적용되며, 급여 인사제도는 동일하게 제공됩니다.",
]

# ── 샘플 2: 섹션 라인 필터 -항공/방산 기계설계 JD ───────────────
SAMPLE_AEROSPACE_REQUIREMENTS = [
    "Abaqus 또는 ANSYS를 이용한 구조해석 경험 3년 이상",
    "유한요소해석(FEM) 기반 피로/응력 해석 가능자",
    "CATIA V5 기반 3D 모델링 가능자",
    "해외여행 결격사유가 없는 자",
    "학력무관",
    "남자의 경우 군필 또는 면제자",
    "보훈대상자 우대",
    "성실하고 책임감 있는 자",
]

# ── 샘플 3: raw_text 정제 + detect_core_sections 비교 ─────────────
# 잡코리아 OCR 패턴: 상단 네비 노이즈 + 실제 공고 본문 + 하단 컷오프 구조
SAMPLE_RAW_NOISY = """\
[PAGE 1]
회 원 가 입 / 로 그 인 ㅣ 기 업 서비스 ~
합격확률 기업·연봉 콘텐츠 취업톡톡

[플 랫 폼 본부] 백 엔 드 엔지니어
직무 백 엔 드 개발자

주요 업무
플랫폼 백엔드 서비스 개발 및 운영
자격 요건
Java 기반 백엔드 시스템 개발 경력 5년 이상
우대 사항
Redis, Kafka 활용 경험

지원자 현황 통계
즉시지원 관련 태그

[PAGE 2]
이 기업의 취업전략
합격자소서 인적성 면접후기
그동안 본인의 삶에서 가장 기억에 남는 일을 적어주세요...\
"""

# ── 샘플 4: missing_core_sections 오판 케이스 시뮬레이션 ──────────
# 짧은 텍스트에 UI 노이즈가 많이 섞여 detect_core_sections 오판 가능성
SAMPLE_RAW_UI_HEAVY = """\
[PAGE 1]
원서접수 신입사원 채용 즉시지원
기업정보 오늘 본 공고

[담당업무]
기구설계 및 도면 작성
응력해석 / 구조해석 수행

[자격요건]
CATIA 또는 SolidWorks 사용 가능자
피로수명 해석 경험 우대

비슷한 조건의 AI 추천공고
관련 태그 지원자 현황 통계\
"""


def check_line_filter(title: str, before: list[str], source: str = "") -> None:
    after = filter_low_value_lines(before)
    removed = [l for l in before if l not in after]
    print(f"\n{SEP}")
    print(f"[라인 필터] {title}")
    print(f"  before {len(before)}줄 → after {len(after)}줄  (제거 {len(removed)}줄)")
    if removed:
        for r in removed:
            print(f"    X {r[:80]}")
    for k in after:
        print(f"    O {k[:80]}")


def check_raw_text(title: str, raw: str, site: str = "jobkorea") -> None:
    cleaned = clean_job_posting_text(raw, site)
    before_lines = [l for l in raw.splitlines() if l.strip()]
    after_lines = [l for l in cleaned.splitlines() if l.strip()]

    sections_before = detect_core_sections(raw)
    sections_after = detect_core_sections(cleaned)

    # assess_capture_failed 기준 (텍스트 길이 + 섹션 존재)
    has_sections_before = bool(sections_before)
    has_sections_after = bool(sections_after)
    text_ok_before = len(raw) >= 300
    text_ok_after = len(cleaned) >= 300

    print(f"\n{SEP}")
    print(f"[raw_text 정제] {title}")
    print(f"  raw_text:     {len(raw)}자  →  cleaned: {len(cleaned)}자  (감소 {len(raw)-len(cleaned)}자)")
    print(f"  줄 수:        {len(before_lines)}줄  →  {len(after_lines)}줄  (제거 {len(before_lines)-len(after_lines)}줄)")
    print(f"  detect_core_sections (raw):     {sections_before}")
    print(f"  detect_core_sections (cleaned): {sections_after}")
    improved = (not has_sections_before) and has_sections_after
    print(f"  섹션 탐지 개선: {'[개선] raw=미탐지->cleaned=탐지' if improved else '[변화없음]'}")
    print(f"  텍스트 길이 충분 (raw/cleaned): {text_ok_before} / {text_ok_after}")
    print(f"  정제 후 텍스트:")
    for line in after_lines:
        print(f"    {line[:80]}")


def main() -> None:
    print(f"\n{SEP}")
    print("verify_filter.py -- 필터/정제 before/after 검증")
    print(SEP)

    # 섹션 라인 필터
    check_line_filter("넥슨 preferred (백엔드)", SAMPLE_NEXON_PREFERRED)
    check_line_filter("항공/방산 requirements (기계설계)", SAMPLE_AEROSPACE_REQUIREMENTS)

    # raw_text 정제 + detect_core_sections 비교
    check_raw_text("잡코리아 OCR -UI 노이즈 혼재 케이스", SAMPLE_RAW_NOISY, "jobkorea")
    check_raw_text("잡코리아 -missing_core_sections 오판 시뮬레이션", SAMPLE_RAW_UI_HEAVY, "jobkorea")


if __name__ == "__main__":
    main()
