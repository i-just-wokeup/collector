# SAVE STATE

Last updated: 2026-04-22
Owner: team
Status: active

## 1) 현재 실제 구현 상태

### 수집 진입
- 수집 진입은 `검색어`와 `카테고리`를 둘 다 지원한다.
- GUI는 `대분류 카테고리 드롭다운`을 기본으로 보여준다.
- GUI에 `로그인` 버튼이 있어 collector 전용 브라우저 프로필로 수집 세션을 분리한다.
- GUI 상단 DB 현황은 이제 **role 기준 상태**를 보여준다.
  - `전체 공고 수`, `전체 role 수`, `classified role 수`, `pending role 수`, `failed role 수`, `job_criteria 수`
  - 직무별 분류도 `job_posting_role_tags` 기준 role 수로 집계한다.
- `src/sites/jobkorea.py`는 JobKorea Top100 카테고리 URL을 `BizJobtype_Bctgr_Code` 기준으로 생성한다.
- JobKorea 공고 링크는 `/Recruit/GI_Read/{id}` 기준으로 정규화한다.

### 파이프라인 기본 전제 변경 (2026-04-22)
- **공고 1개 = 직무(role) 여러 개** 가능하도록 파이프라인이 전환됐다.
- `job_postings`는 공고 컨테이너 역할만 한다.
- `job_posting_roles`가 실제 분석 단위다.
- `extracted_role` / posting-level `role` 필드는 레거시 하위호환용으로만 남아 있다.
  - 새 로직(classify, analyze)은 이 필드에 의존하지 않는다.
- 분류 결과는 `job_posting_role_tags`에 role 단위로 저장된다.

### DB 스키마 현재 상태
- `job_postings`: 공고 컨테이너
  - `extracted_role`: 레거시 shim (분류/분석에서 참조 안 함)
  - `common_requirements_json`: 공통 지원자격 (JSON 배열)
  - `common_preferred_json`: 공통 우대사항 (JSON 배열)
  - `source_category`: 수집 카테고리 힌트
  - `classification_status`: posting-level (레거시, 현재는 role-level이 주)
- `job_posting_roles`: 역할 단위 실제 분석 데이터
  - `role_name`, `main_tasks_json`, `requirements_json`, `preferred_json`
  - `classification_status`: role 단위 분류 상태 (`pending` / `classified` / `failed`)
  - `UNIQUE(job_id, display_order)` 중복 방지
- `job_posting_role_tags`: role 단위 직무 분류 결과 (신규)
  - `role_id` → `job_posting_roles.id`
  - `job_family`, `is_primary`
  - `UNIQUE(role_id, job_family)`
- `job_tags`: posting-level 레거시 (기존 데이터 보존, 새 로직에서 쓰지 않음)
- `job_sections`: shim 기반 단일 role 정보 (기존 데이터 보존, 새 로직에서 쓰지 않음)

### 분류 (classify.py)
- 기본 모드: `run_classify_roles()` — role 단위 Gemini 분류
  - 입력: company, posting_title, source_category, role_name, role main_tasks/requirements/preferred, common_requirements
  - `filter_generic_analysis_lines()` 적용 후 Gemini에 전달
  - 결과: `job_posting_role_tags` 저장 + `job_posting_roles.classification_status = 'classified'`
- 실제 테스트:
  - GUI `직무 분류` 버튼으로 role 분류 1회 실행 확인
  - **20개 role 분류 성공 / failed 0**
  - `job_posting_role_tags = 20`, `classified_roles = 20`
  - 같은 role에 다중 태그가 남는 케이스는 이번 테스트에서 확인되지 않음
- 레거시 모드: `run_classify()` — posting 레벨 (기존 유지)
- `main()`: `--mode roles`(기본) / `--mode postings`(레거시)

### 분석 (analyze.py)
- 기본 모드: `run_analyze_roles()` — role 단위 분석
  - `job_posting_role_tags` JOIN `job_posting_roles`에서 섹션 텍스트 수집
  - `filter_generic_analysis_lines()` + `filter_low_value_lines()` 적용 후 Gemini 투입
  - `job_criteria`, `criteria_stats` 저장 (테이블 공유, 분석 단위만 role로 전환)
- 레거시 모드: `run_analyze()` — posting/job_sections 레벨 (기존 유지)
- `main()`: `--mode roles`(기본) / `--mode postings`(레거시)
- 현재는 role 분류 샘플 수가 부족해서 의미 있는 분석 실행 전 단계다.
  - 현재 role tag 기준 posting_count 분포:
    - `sales` 2개 공고
    - 나머지 family는 1개 공고 수준
  - 기본 `min_sample_count=5` 기준으로는 대부분 스킵될 가능성이 높다.

### 수집 품질 (collect.py)
- `posting_title` 보정: capture meta가 generic("채용공고", "공고" 등)이면 LLM 결과로 fallback
- `company` 보정: capture meta 없으면 LLM 결과 fallback
- role 저장 전 텍스트 정제:
  - `clean_role_first_task()`: main_tasks 첫 줄이 role_name 반복이면 제거
  - `filter_low_value_lines()`: requirements/preferred에 LOW_VALUE_LINE_PATTERNS 적용
- `assess_low_quality_job()`: `roles` + `structured_payload` 인자 추가
  - `shallow_aggregate_empty_tasks`: 3+ roles인데 main_tasks 있는 비율 30% 미만
  - `common_only_no_role_detail`: role별 콘텐츠 합계 < common_* 합계
- 실제 테스트:
  - `planning_strategy` 카테고리 5건 수집 테스트 실행
  - `jobkorea_20260422_142505_016` 써브웨이 공고: `roles_count=9`, `low_quality=false`, DB 저장 확인
  - `jobkorea_20260422_142336_015` 한국선급 공고: `roles_count=14`, `shallow_aggregate_empty_tasks`로 `output/low_quality/` 격리 확인
  - 즉 “상세 role이 채워진 복합공고는 저장, 얕은 집계형 공고는 low_quality 격리”가 실제로 동작했다.

### 필터 구조
- `LOW_VALUE_LINE_PATTERNS`: DB 저장 전 단계에서 적용 (법정/보훈 등)
- `GENERIC_ANALYSIS_FILTER_PATTERNS`: 분류/분석 단계에서만 적용
  - 범용 학력 문구, 추상 소프트스킬, 법정 문구 포함
  - raw_text나 DB 저장 단계에는 절대 적용하지 않음

### 검수용 CSV export (export_csv.py)
- `--db-roles`: DB 기반 role 단위 검수 CSV (권장)
  - 열: job_id, role_id, company, posting_title, source_category, role_name, role_classification, role_main_tasks, role_requirements, role_preferred, common_requirements, common_preferred, raw_text_preview
- 레거시: match/not_match/unknown JSON 파일 기반 (기존 유지)

## 2) JobKorea Top100 카테고리 매핑 (확정)
- `software` → `10031`
- `engineering` → `10040`, `10041`
- `planning_strategy` → `10026`
- `marketing` → `10030`
- `design` → `10032`
- `sales` → `10035`
- `business_support` → `10028`, `10029`, `10027`
- `operations_service` → `10036`, `10039`, `10033`

## 3) 수집 품질 개선 현재 상태
- JobKorea 상세 페이지는 본문 중심 캡처 방식으로 개선됐다.
- 캡처 우선순위: iframe body → .artRead → .detail → #container → main → scroll fallback
- OCR 전처리: 그레이스케일 + 800px 리사이즈 + 대비 1.3배 강화 + PNG 유지
- `one_image_short_text`는 더 이상 즉시 실패가 아니다 (소프트 경고로 전환).

## 4) 구조화(JSON)와 DB 저장 현재 상태
- `jd-research-tool`은 `roles[]` 배열 구조를 반환한다.
- collector는 `structured_jd_payload`(원본)와 normalized payload를 분리해서 사용한다:
  - `job_postings` / `job_sections` / 품질 판정: normalized payload (shim 기반)
  - `job_posting_roles`: structured_jd_payload (원본 roles[] 기준)
- `save_job_posting_roles()` 안전장치:
  - 빈 role_name 저장 방지
  - UNIQUE(job_id, display_order) 중복 방지
  - partial 저장 시 DELETE + 전체 재삽입
  - already_complete이면 skip

## 5) low_quality / 중복 방지 현재 동작
- `assess_low_quality_job()`에 걸린 공고는 DB 저장 안 됨
- 대신 `output/low_quality/` 아래 JSON으로 격리 저장
- 해당 URL은 `output/seen_urls.txt`에도 추가
- low quality로 빠진 공고는 다음 수집에서 보통 다시 안 잡힘 (seen_urls 때문)

## 6) aggregate(집계형) 공고 현재 상태
- `is_aggregate_posting()` 탐지 함수 존재 — 저장 차단은 안 하고 태그만 붙임
- 얕은 aggregate 판정: `shallow_aggregate_empty_tasks`, `common_only_no_role_detail` 기준 추가됨
- 역할 수 >= 15이고 main_tasks 채워진 비율 30% 미만 → low quality 판정 가능

## 7) 아직 구현되지 않은 것
- `classify.py` top8 기준 전환 (현재는 job_families.json 기본 경로 사용)
  - `--families-path` 인자로 job_families_top8.json 지정 가능하나 기본값은 아님
- 기존 저장된 공고의 role 단위 재분류 (현재 pending 상태 230개)
- `job_sections` + posting-level `job_tags` 완전 제거 (당장은 레거시 보존)
- `ensure_enriched_schema()` 내 payload 흐름 통합 리팩토링
- PaddleOCR 기반 로컬 OCR 대체
  - **현재는 보류**
  - 최근 잘 나온 복합공고 다수가 image-based Gemini Vision 경로일 가능성이 높다.
  - PaddleOCR 자체 텍스트 추출은 가능성을 보였지만, 복합공고 role/요건 매칭 안정성이 검증되지 않았고 런타임/환경 이슈도 있었다.
  - 현 시점 의사결정: 메인 파이프라인은 **이미지 기반 Gemini Vision 유지**
- Supabase 적재 / RAG / 임베딩 연동
- `경기청년 일자리 매치업` 유형 특이케이스 일반화

## 8) 현재 기준 데이터 상황
- `job_postings`: 69건
- `job_posting_roles`: 250개
- `job_posting_role_tags`: 20건
- `classified_roles`: 20개
- `pending_roles`: 230개
- `failed_roles`: 0개
- role tag 분포:
  - `sales` 5
  - `medical` 4
  - `marketing` 3
  - `design` 2
  - `finance` 2
  - `backend` 1 / `devops` 1 / `pm` 1 / `strategy` 1
- `job_sections`: 기존 데이터 그대로 (레거시)
- `job_tags`: 기존 데이터 그대로 (레거시)

## 9) 캡처 이미지 전처리 및 버그 수정 (2026-04-27)

### 이미지 전처리 (collector-main capture.py 기준)
- Playwright 스크린샷 후 PIL로 전처리: 그레이스케일 + 800px 리사이즈 + 대비 1.3배 + JPEG 85% 압축
- Gemini 타일 수 ~68% 절감 효과

### 잡코리아 iframe 테이블 잘림 수정
- `capture.py` iframe 캡처 전 CSS 주입 추가:
  - `document.body.style.minWidth = 'unset'`
  - `document.body.style.overflowX = 'visible'`
  - 모든 table에 `tableLayout = 'auto'`, `width = '100%'` 적용
- 대상: `jd-collector-agent/src/capture.py` (외부 버전)

### Gemini 모델 및 503 대응
- `vision_structure_jd.py`: `gemini-2.5-flash` 유지 (1.5/2.0 계열은 404 또는 종료됨)
- `pipeline.py`: 503 재시도 대기 60s × (attempt+1) 지수 백오프

### classify.py 배치 제한 제거
- 기존 `LIMIT 20` 제거 → 직무 분류 버튼 1회로 pending 전체 처리

### collect.py dotenv 누락 수정
- `load_dotenv()` 추가 → `JD_RESEARCH_TOOL_PATH` 환경변수 정상 로드

### reprocess_captures.py 복사
- `collector-main` 버전을 외부 `jd-collector-agent/src/`로 복사
- JSON 없는 캡처 폴더 재처리용

## 10) 캡처 품질 추가 개선 (2026-04-27 2차)

### 외부 jd-collector-agent capture.py 전처리 적용
- `_preprocess_image()` 추가: 그레이스케일 + 800px 리사이즈 + 대비 1.3배 + JPEG 85%
- 모든 스크린샷 저장을 `.png` → `.jpg` + 전처리 적용으로 전환
- iframe, locator, 스크롤 fallback 3가지 경로 모두 적용

### saramin/wanted 노이즈 제거 스크립트 추가
- `sites/base.py`: `get_noise_hide_script()` 기본 메서드 추가
- `sites/saramin.py`: `section.store_recommend_section` 이후 숨김
- `sites/wanted.py`: `article[class*="JobAssociated_JobAssociated"]` 이후 숨김
- `capture.py`: 비-JobKorea 캡처 전 `adapter.get_noise_hide_script()` 호출

### reprocess_captures.py 503 재시도 로직 추가
- 503 에러 시 60s → 120s → 180s 대기 후 재시도 (최대 3회)

## 11) 다음 세션에서 꼭 기억할 점
- `classify.py`를 실행하면 role 단위 분류가 기본으로 실행된다.
  - `--mode roles` 기본 / `--mode postings` 레거시
- GUI 상단 DB 현황은 이제 role 기준이므로, 진행률 확인은 GUI 숫자를 그대로 봐도 된다.
- 로그인은 자동이 아니다.
  - collector 전용 프로필 창을 먼저 열고 사용자가 직접 로그인해야 한다.
- raw_text 원본은 항상 보존된다.
  - role 저장 전 정제는 roles[] 내부 텍스트에만 적용된다.
- `filter_generic_analysis_lines()`는 분류/분석 단계에서만 쓴다 (저장 단계 금지).
- 새 분류/분석 로직은 `extracted_role` / `posting-level role` 필드에 의존하지 않는다.
- 복합공고 품질이 좋았던 최근 샘플은 image-based Gemini Vision 경로일 가능성이 높다.
  - 텍스트 기반 전환은 아직 확정하지 않는다.
