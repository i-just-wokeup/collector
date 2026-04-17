# jd-collector-agent

`jd-collector-agent`는 채용공고를 수집하고 구조화한 뒤 SQLite DB에 적재하고,
Gemini 기반 후처리로 직무 분류와 역량 기준 추출까지 이어지는 로컬 GUI/CLI 도구입니다.

현재 기준으로 이 저장소의 메인 흐름은 아래 3단계입니다.

1. 수집: `jobkorea`, `saramin` 검색 결과를 순회하며 공고 상세를 캡처하고 구조화
2. 직무 분류: 저장된 공고를 `job_family` 기준으로 분류
3. 역량 분석: 분류된 공고를 바탕으로 직무별 핵심 기준과 빈도 통계를 추출

`jd-research-tool`의 `src/structure_jd.py`, `src/vision_structure_jd.py`를 재사용해
공고 이미지를 구조화 JSON으로 바꾸며, 결과는 파일 분류 폴더보다 DB 적재가 중심입니다.

## 현재 권장 실행 방식

GUI 실행:

```bash
python gui.py
```

GUI에서 제공하는 버튼:

- `수집 시작`: `src/collect.py` 실행
- `직무 분류`: `src/classify.py` 실행
- `역량 분석`: `src/analyze.py` 실행

GUI는 현재 DB 현황을 보여주고, 각 단계 실행 후 로그를 수집하며,
환경변수가 설정되어 있으면 Telegram 알림도 전송합니다.

## 지원 사이트

현재 메인 수집 흐름(`gui.py`, `src/collect.py`) 기준 지원 사이트:

- `jobkorea`
- `saramin`

참고:
- `wanted` 어댑터와 레거시 파이프라인 코드는 저장소에 남아 있습니다.
- 하지만 현재 GUI 기반 수집 플로우에서는 `wanted`를 입력값으로 받지 않습니다.

## 준비물

- Python 3.10+
- Playwright Chromium 브라우저
- Gemini API 키
- `jd-research-tool` 프로젝트
- SQLite DB 파일
- `jd-collector-agent/job_families.json` 파일

## 설치

```bash
cd jd-collector-agent
pip install -r requirements.txt
playwright install chromium
```

## 환경 변수

`.env` 예시:

```env
GEMINI_API_KEY=your_real_api_key
JD_DB_PATH=C:\dev\jd_data.db
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
GEMINI_MODEL=gemini-2.5-flash
```

기본 경로 동작:

- DB 경로 기본값: `C:\dev\jd_data.db`
- `jd-research-tool` 기본 경로: `C:\dev\jd-research-tool`
- 직무군 정의 파일 기본 경로: `jd-collector-agent/job_families.json`

DB 초기화:

```bash
cd jd-collector-agent
python init_db.py
```

권장 시작 순서:

```bash
cd jd-collector-agent
python init_db.py
python gui.py
```

WSL/Linux 환경에서는 Windows 경로를 `/mnt/c/...`로 변환해 사용할 수 있도록 구현되어 있습니다.

## 단계별 CLI 실행

### 1) 수집

```bash
python src/collect.py
```

입력값:

- `site_name` (`jobkorea` 또는 `saramin`)
- `search_keyword`
- `target_count`
- `jd_research_tool_path` (엔터 시 기본 경로 사용)

동작 요약:

- 검색 결과에서 공고 링크 수집
- 공고 상세 페이지 캡처
- 캡처 이미지 일부를 `jd-research-tool`로 구조화
- 저품질 공고/캡처 실패 공고 분리
- 정상 공고를 SQLite DB에 저장

### 2) 직무 분류

```bash
python src/classify.py
```

입력값:

- `batch_size`
- `db_path`

동작 요약:

- `classification_status = 'pending'` 공고 조회
- Gemini로 `job_family` 최대 3개까지 판정
- `job_tags` 저장
- 분류 완료 시 `classification_status = 'classified'`

### 3) 역량 분석

```bash
python src/analyze.py
```

입력값:

- `min_sample_count`
- `db_path`

동작 요약:

- 분류 완료된 공고를 직무군별로 집계
- 섹션 텍스트에서 빈도 높은 키워드 통계 저장
- Gemini로 `직무역량` / `직무경험` 기준 추출
- `job_criteria`, `criteria_stats` 저장

### 4) 검수용 CSV 내보내기

```bash
python src/export_csv.py
python src/export_csv.py --all
```

동작 요약:

- 분류 결과 JSON을 읽어 공고 1개당 1행 CSV 생성
- 저장 경로: `output/export_{범위}_{타임스탬프}.csv`
- 인코딩: `utf-8-sig` (Excel에서 한글 바로 열기 용도)

## 저장 결과

### 파일 출력

- 원본 캡처: `output/raw_captures/{job_id}/`
- OCR 입력용 복사본: `output/raw_captures/{job_id}/ocr_input/`
- 임시 구조화 JSON: `output/raw_captures/{job_id}/jd_result.json`
- 캡처 실패 메타: `output/failed_capture/{site}_{keyword_slug}/`
- 저품질 공고 JSON: `output/low_quality/{site}_{keyword_slug}/`
- Gemini quota 중단 기록: `output/quota_stop/`
- URL 중복 방지 기록: `output/seen_urls.txt`

### DB 저장

주요 테이블:

- `job_postings`: 공고 메타, 원문 텍스트, 분류 상태
- `job_sections`: `main_tasks`, `requirements`, `preferred`
- `job_tags`: 직무군 분류 결과
- `job_criteria`: 직무별 핵심 기준
- `criteria_stats`: 직무별 키워드 빈도 통계

## 수집 JSON/DB에 들어가는 주요 필드

`jd-research-tool`에서 생성한 기본 스키마:

- `company`
- `role`
- `main_tasks`
- `requirements`
- `preferred`
- `raw_text`
- `source_images`

수집기에서 보강하는 메타데이터:

- `posting_title`
- `source_site`
- `source_url`
- `seniority_text`
- `employment_type`
- `job_family_guess`
- `classification_result`
- `collector_meta`

참고:
- 현재 DB 중심 수집 경로에서는 `classification_result`를 파일 분류 기준으로 쓰지 않습니다.
- 직무 분류는 별도 단계인 `src/classify.py`에서 `job_tags`와 `classification_status`로 관리합니다.

## 구조화 방식

수집 시 구조화 우선순위:

1. 상세 페이지에서 추출한 `raw_text`가 충분히 길고 핵심 섹션 키워드가 있으면 텍스트 기반 구조화
2. 그렇지 않으면 캡처 PNG를 최대 3장 선택해 이미지 기반 구조화

이 과정에서 `jd-research-tool`의 아래 모듈을 동적으로 import 합니다.

- `structure_jd.py`
- `vision_structure_jd.py`

## 레거시 파이프라인

아래 명령도 여전히 존재합니다.

```bash
python src/main.py
```

이 경로는 `target_role`, `output_job_folder_name`, `match/not_match/unknown` 파일 분류를 사용하는
초기 MVP 파이프라인입니다.

현재 저장소의 주력 사용 방식은 아니며, 최신 운영 흐름은 `gui.py` + `src/collect.py` + `src/classify.py` + `src/analyze.py` 조합입니다.

## 요구 패키지

`requirements.txt`

- `playwright`
- `python-dotenv`
- `google-genai`

추가로 Playwright Chromium 설치가 필요합니다.
