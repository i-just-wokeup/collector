# jd-collector-agent

`jd-collector-agent`는 반자동 JD 수집 파이프라인 MVP입니다.
선택한 사이트 검색 결과를 순회하고 공고 상세를 스크롤 캡처한 뒤,
기존 `jd-research-tool`을 재사용해 공고 1개당 JSON 1개를 생성하고,
Gemini로 `target_role` 적합도를 `match | not_match | unknown`으로 분류 저장합니다.

## 지원 사이트
- `wanted`
- `saramin`
- `jobkorea`

## site_name 사용법
실행 시 `site_name`은 아래 값만 허용합니다.
- `wanted`
- `saramin`
- `jobkorea`

## 준비물
- Python 3.10+
- Playwright 브라우저 설치
- Gemini API 키 (`.env`)
- 기존 `jd-research-tool` 프로젝트 (필수)

## 설치
```bash
pip install -r requirements.txt
playwright install chromium
```

## 실행
```bash
python src/main.py
```

실행 입력값:
- `target_role`
- `site_name`
- `search_keyword`
- `target_count` (`match` JSON 개수 기준)
- `output_job_folder_name`
- `jd_research_tool_path`

## 결과 저장 경로
- 캡처 원본: `output/raw_captures/{job_id}/page_001.png`
- 분류 JSON:
  - `output/classified/match/{output_job_folder_name}/`
  - `output/classified/not_match/{output_job_folder_name}/`
  - `output/classified/unknown/{output_job_folder_name}/`

## JSON 필드(보강)
기존 JD 구조 필드에 아래 메타데이터가 추가됩니다.
- `posting_title`: 공고 제목 원문
- `source_site`: 수집 사이트명 (`wanted/saramin/jobkorea`)
- `source_url`: 공고 상세 URL
- `seniority_text`: 경력 조건 원문(신입/경력무관/3년 이상 등)
- `employment_type`: 고용형태(정규직/인턴/계약직 등)
- `job_family_guess`: 수집기 추정 직무군
- `classification_result`: Gemini 판정 결과 (`match/not_match/unknown`)
- `collector_meta`: 수집 시점/검색어/타겟직무/수집단위(job_id) 등

왜 필요한가:
- `source_site`, `source_url`: 출처 추적 및 중복 검증
- `seniority_text`: 이후 junior/senior 수동 필터링 근거
- `classification_result`: 분류 결과 재검수 및 품질 점검

## 주의
- `target_count`는 `match/{output_job_folder_name}` 폴더 JSON 개수 기준입니다.
- `jd-analyzer` 자동 실행은 포함하지 않습니다. 분석은 여전히 수동 실행입니다.
