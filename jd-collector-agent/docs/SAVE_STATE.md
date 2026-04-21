# SAVE STATE

Last updated: 2026-04-21
Owner: team
Status: active

## 1) 현재 실제 구현 상태
- 수집 진입은 `검색어`와 `카테고리`를 둘 다 지원한다.
  - 검색어 기반 기존 흐름은 유지됨
  - 새 카테고리 기반 흐름은 `jobkorea` 전용으로 추가됨
- GUI는 `검색어 입력` 대신 `대분류 카테고리 드롭다운`을 기본으로 보여준다.
- GUI에는 `로그인` 버튼이 추가되어 있다.
  - 수집과 로그인 과정을 분리했다.
  - 먼저 로그인 버튼으로 collector 전용 브라우저 프로필 창을 열고,
    그 창에서 사용자가 직접 로그인한 뒤 닫으면 된다.
  - 이후 수집은 같은 프로필을 재사용한다.
- `src/collect.py`는 `--category`, `--target-count`, `--site`, `--login-only` CLI 인수를 지원한다.
- `src/sites/jobkorea.py`는 JobKorea Top100 카테고리 URL을 `BizJobtype_Bctgr_Code` 기준으로 생성한다.
- JobKorea 공고 링크는 `/Recruit/GI_Read/{id}` 기준으로 정규화하여 중복을 줄인다.
- `job_postings`에는 `source_category` 컬럼이 추가되어 수집 카테고리를 저장한다.
- 새 대분류 정의 파일이 존재한다.
  - `job_families_top8.json`
- 새 실험용 DB 초기화 경로가 존재한다.
  - `jd_data_top8.db`

## 2) JobKorea Top100 카테고리 매핑 (확정)
- `software` -> `10031` (`AI·개발·데이터`)
- `engineering` -> `10040`, `10041` (`엔지니어링·설계`, `제조·생산`)
- `planning_strategy` -> `10026` (`기획·전략`)
- `marketing` -> `10030` (`마케팅·광고·MD`)
- `design` -> `10032` (`디자인`)
- `sales` -> `10035` (`영업`)
- `business_support` -> `10028`, `10029`, `10027` (`인사·HR`, `회계·세무`, `법무·사무·총무`)
- `operations_service` -> `10036`, `10039`, `10033` (`고객상담·TM`, `고객서비스·리테일`, `물류·무역`)

## 3) 수집 품질 개선 현재 상태
- JobKorea 상세 페이지는 본문 중심 캡처 방식으로 개선되었다.
- 현재 JobKorea 캡처 우선순위:
  1. `GI_Read_Comt_Ifrm` iframe body
  2. `.artRead`
  3. `.detail`
  4. `#container`
  5. `main` (StrategyWrapper 이후 숨김)
  6. 기존 스크롤 fallback
- OCR 입력 이미지는 전처리된다.
  - 그레이스케일
  - 너비 800px 리사이즈
  - 대비 1.3배 강화
  - PNG 유지
- `one_image_short_text`는 더 이상 즉시 실패가 아니다.
  - iframe/body locator처럼 정상 본문 캡처인 경우에는 bypass된다.
  - 따라서 본문 1장 캡처 공고도 저장 통과 가능하다.
- 현재 남아 있는 품질 문제는 캡처 자체보다 구조화 결과 쪽이다.
  - 공고가 너무 얕거나
  - 역할 수만 많고 role별 상세 정보가 비어 있으면
  - DB에는 저장돼도 분석용 기준 데이터로는 가치가 낮을 수 있다.

## 4) 구조화(JSON)와 DB 저장 현재 상태
- `jd-research-tool`은 `roles[]` 배열 구조를 지원한다.
- collector는 현재 payload를 두 갈래로 사용한다.
  - `job_postings` / `job_sections` / 품질 판정: normalized payload
  - `job_posting_roles`: 원본 structured payload
- 이유:
  - `ensure_enriched_schema()`가 `roles[]`, `common_requirements`, `common_preferred`를 완전히 보존하지 못한다.
  - 그래서 JSON 생성 직후 원본 structured payload를 따로 복사해 role 저장에만 사용하도록 우회했다.
- 결과적으로 예전처럼 `roles[0]`만 완전히 남는 상태는 아니다.
  - `job_posting_roles`에는 전체 `roles[]` 저장이 가능하다.
  - 다만 `job_sections`는 여전히 단일 role 호환 흐름에 기대고 있어, 두 저장 흐름이 공존한다.
- `job_posting_roles`에는 안전장치가 추가되었다.
  - 빈 `role_name` 저장 방지
  - `UNIQUE(job_id, display_order)` 중복 방지
  - partial 저장 시 해당 `job_id` role rows 삭제 후 전체 재삽입
  - already_complete면 skip

## 5) low_quality / 중복 방지 현재 동작
- `assess_low_quality_job()`에 걸린 공고는 DB에 저장되지 않는다.
- 대신 `output/low_quality/...` 아래 JSON으로 격리 저장된다.
- 그리고 그 URL은 `output/seen_urls.txt`에도 추가된다.
- 의미:
  - low quality로 판정된 공고는 다음 수집 때 보통 다시 안 잡힌다.
  - DB 중복 방지 이전에 `seen_urls` 단계에서 먼저 걸러진다.
- 예외:
  - `seen_urls.txt`를 지우거나 초기화하면 다시 수집될 수 있다.

## 6) aggregate(집계형) 공고 현재 상태
- 집계형 공고 탐지 함수(`is_aggregate_posting`)는 들어가 있다.
- 하지만 현재는 **탐지만 하고 저장 차단은 하지 않는다.**
  - 로그: `[WARN] aggregate_posting_detected=true reasons=...`
  - payload에도 `aggregate_candidate`, `aggregate_reasons`가 붙는다.
- 이유:
  - 사용자 의도는 “복합공고라도 일단 넓게 모으기” 쪽이기 때문
  - 그래서 지금은 집계형 여부를 표시만 하고 저장은 유지한다.
- 다만 최근 테스트에서 확인된 문제:
  - 역할 수가 20개 이상으로 많이 잡히는 공고 중 일부는
    role명만 많고 `main_tasks`, `requirements`, `preferred`가 거의 비어 있다.
  - 이런 공고는 “저장 성공”이어도 실제 분석 가치가 낮다.
  - 즉 다음 품질 개선의 핵심은 aggregate 자체를 무조건 버릴지 여부가 아니라,
    “얕은 aggregate 공고를 어떻게 low quality로 보낼지”다.

## 7) 최근 실제 테스트에서 확인된 것
- 로그인 버튼 + collector 전용 프로필 방식은 실제로 동작 확인했다.
- 영업 카테고리 1건 수집 테스트에서:
  - 로그인 프로필 재사용 경로 동작 확인
  - iframe/body 캡처 성공
  - `saved_count=1/1` 확인
- 다만 성공 저장된 공고 중에도 품질 차이가 컸다.
  - 어떤 공고는 role별 요구사항/우대사항이 충분히 나옴
  - 어떤 공고는 role 수는 많지만 공통 문구만 있고 상세 기준이 거의 없음
- 즉 현재 병목은 “저장 성공 여부”보다 “저장된 공고를 기준 DB로 써도 되는지” 판단하는 단계다.

## 8) 지금 가장 중요한 문제
- 더 이상 1순위는 캡처 안정화가 아니다.
- 현재 핵심 병목은 두 가지다.
  1. 얕은 집계형/복합공고를 low quality로 보낼 기준 설계
  2. normalized payload와 structured payload가 갈라진 임시 저장 구조를 나중에 어떻게 정리할지 결정

## 9) 아직 구현되지 않은 것
- `classify.py`의 top8 기준 전환 (Phase 4)
- aggregate 공고 중 “얕은 공고”를 자동 격리하는 품질 기준
- `job_sections`까지 role 중심 구조로 완전히 재설계하는 작업
- PaddleOCR 기반 로컬 OCR 대체 실험
- Supabase 적재 / RAG / 임베딩 연동

## 10) 다음 세션에서 꼭 기억할 점
- 로그인은 자동이 아니다.
  - collector 전용 프로필 창을 먼저 열고 사용자가 직접 로그인해야 한다.
  - 로그인 후에는 같은 프로필을 재사용하므로 매번 처음부터 할 필요는 없다.
- 현재 저장 구조는 임시 우회지만 실제 동작은 한다.
  - `job_posting_roles` 전체 저장은 가능
  - 다만 payload 흐름이 둘로 나뉘어 있어 추후 정리가 필요
- low quality로 빠진 공고는 `seen_urls` 때문에 보통 다시 안 잡힌다.
- aggregate 공고는 지금 저장 차단하지 않는다.
  - 대신 로그와 payload에 표시만 붙는다.
- 다음 우선순위는 `classify.py`보다도
  - “얕은 공고를 어떻게 걸러낼지”
  - “지금 저장된 공고 중 분석용으로 쓸만한 것과 아닌 것을 어떻게 나눌지” 쪽에 더 가깝다.
