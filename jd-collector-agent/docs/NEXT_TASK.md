# NEXT TASK

Last updated: 2026-04-21
Owner: team
Status: active

## 1) 다음 세션의 최우선 목표
- 얕은 aggregate/복합공고를 low quality로 보낼 기준을 정한다.
- 현재 저장된 샘플 2~3건을 직접 확인해 “쓸만한 공고”와 “얕은 공고” 차이를 기준으로 정리한다.
- `classify.py` top8 전환은 일단 보류하고, 수집된 데이터 품질 안정화 쪽을 먼저 본다.

## 2) 바로 해야 할 일
1. 최근 저장된 공고 중 아래 두 종류를 비교한다.
   - role별 `main_tasks`, `requirements`, `preferred`가 실제로 채워진 공고
   - role 수만 많고 상세 정보가 거의 비어 있는 공고
2. 얕은 공고 기준 초안을 정한다.
   - 예: `roles_count`는 많은데
   - role별 상세 배열이 대부분 빈 값이고
   - 공통 요구사항만 반복되는 경우
3. 위 기준을 어디에 반영할지 결정한다.
   - `assess_low_quality_job()`에 넣을지
   - 별도 `aggregate_shallow` 판정으로 둘지
4. low quality로 보낸 공고를 `seen_urls`에 계속 넣을지 정책을 유지할지 확인한다.
   - 현재는 넣고 있음
   - 즉 한 번 low quality로 빠지면 다음 수집에서 다시 잘 안 잡힘
5. 최근 저장 샘플을 기준으로 `job_posting_roles` 저장 품질을 재확인한다.
   - role rows 수
   - 빈 role_name skip 여부
   - partial 복구가 필요 없는지

## 3) 현재 기준 권장 순서
1. 저장된 샘플 공고 2~3건 품질 확인
2. 얕은 aggregate 공고 기준 정의
3. low quality 판정 로직 반영
4. 그 다음 `classify.py` top8 전환 검토
5. 이후 PaddleOCR / Supabase / RAG 같은 확장 과제 검토

## 4) 지금 유지해야 할 것
- `job_families_top8.json` 기반 카테고리 진입 방식
- GUI의 카테고리 드롭다운 흐름
- GUI의 `로그인` 버튼 + collector 전용 브라우저 프로필 방식
- JobKorea iframe/body 우선 캡처 흐름
- OCR 전처리(PNG 유지, 그레이스케일/리사이즈/대비 강화)
- `job_posting_roles` 안전장치
  - blank role skip
  - unique(job_id, display_order)
  - partial 복구

## 5) 지금 바뀔 가능성이 큰 것
- `assess_low_quality_job()` 기준
- aggregate 공고 후처리 정책
- normalized payload / structured payload 흐름 통합 여부
- `classify.py`의 top8 전환 시점

## 6) 설계 메모
- 현재 aggregate 탐지는 저장 차단용이 아니라 “표시용”이다.
  - 로그만 찍고 저장은 진행한다.
- 이 상태는 의도적이다.
  - 사용자가 복합공고도 일단 넓게 모으는 방향을 원했기 때문
- 대신 앞으로는 aggregate 자체를 막는 게 아니라,
  “정보가 너무 얕아서 기준 DB로 쓸 가치가 낮은 공고”를 low quality로 보내는 쪽이 더 맞다.
- 지금 구조는 추후 RAG/임베딩을 붙이더라도 크게 막히는 구조는 아니다.
  - role 중심 조회는 `job_posting_roles` 기준으로 가능
  - 다만 아직은 품질 안정화가 우선이다.

## 7) 보류 항목
- `classify.py` top8 전환
- PaddleOCR 도입
- Supabase 적재
- RAG / 임베딩 연결
- role 중심 조회 구조 재정리 문서화
- 잡코리아 외 타 사이트 카테고리 수집

## 8) 다음 세션에서 꼭 볼 것
- `docs/SAVE_STATE.md`
- 최근 저장된 `jd_result.json` 2~3개
- `output/low_quality/`에 빠진 최근 JSON
- `output/seen_urls.txt`
- `docs/IMPLEMENTATION_PLAN.md`의 최근 워크로그
