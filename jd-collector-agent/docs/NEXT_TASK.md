# NEXT TASK

Last updated: 2026-04-22
Owner: team
Status: active

## 1) 다음 세션의 최우선 목표
- role 단위 분류를 계속 진행해서 family별 **posting_count가 최소 5개 이상** 쌓이게 한다.
- 그 다음에만 `python src/analyze.py` (roles 모드)를 실행한다.
- 현재 결정: OCR 메인 경로는 PaddleOCR로 바꾸지 않고 **image-based Gemini Vision 유지**

## 2) 바로 해야 할 일
1. `python src/classify.py` 실행
   - 현재 230개 role이 `pending` 상태 — 배치 단위로 분류 계속 실행
   - 분류 후 `job_posting_role_tags` row 수와 `classified_roles` 증가 확인
   - `role_classification`에서 `pending`이 아닌 행만 필터해서 육안 검수
2. `python src/export_csv.py --db-roles` 실행
   - role별 분류 결과 육안 검수
   - `company`, `posting_title`, `role_name`, `role_classification` 중심으로 확인
   - 필요한 샘플만 `raw_captures/<job_id>/jd_result.json`과 대조
3. family별 posting_count가 5 이상 쌓인 뒤 `python src/analyze.py` (roles 모드) 실행
   - 현재는 `sales=2`, 나머지 family는 1개 공고 수준이라 바로 돌려도 대부분 스킵 가능성이 높음
4. low_quality 동작 재확인
   - 최근 planning_strategy 테스트에서 `한국선급` 얕은 복합공고가 low_quality로 격리된 흐름이 다시 재현되는지 확인

## 3) 검증해야 할 것
- `classify.py` role 모드가 `extracted_role` 없이 계속 안정적으로 동작하는지
- 재분류 시 동일 role에 태그 찌꺼기가 남지 않는지
- 복합공고(써브웨이/우아한형제들/동국제약/쿠쿠 등)가 role-level로 usable한지
- shallow aggregate가 low quality로 계속 걸러지는지
- `analyze.py`는 posting_count 기준으로 샘플 수를 계산하므로, family별 공고 수가 충분해질 때까지 보류하는 것이 맞는지

## 4) 선택적 작업
- `job_families_top8.json` 기준으로 classify 실행하려면:
  ```
  python src/classify.py --mode roles  # 그 다음 대화형에서 families path 입력
  ```
  또는 classify.py에 `--families-path` argparse 인자를 추가하면 편하다.
- `export_db_roles_*.csv` 검수용 뷰 개선은 선택 과제다.
  - 현재 CSV는 사람 검수용 가독성이 낮지만, 기능 자체는 동작 중이다.
- `ensure_enriched_schema()` payload 흐름 통합 (기술 부채)
  - 현재 normalized/structured 두 payload 병렬 흐름은 임시 우회 구조
  - 언제든 리팩토링 가능하지만 당장은 blocking 이슈가 아님

## 5) 지금 유지해야 할 것
- `job_families_top8.json` 기반 카테고리 진입 방식
- GUI의 카테고리 드롭다운 + 로그인 버튼 흐름
- GUI 상단 DB 현황 role 기준 표시
- JobKorea iframe/body 우선 캡처 흐름
- OCR 전처리 (PNG 유지, 그레이스케일/리사이즈/대비 강화)
- `job_posting_roles` 안전장치 (blank skip, unique, partial 복구)
- `raw_text` 원본 보존 원칙

## 6) 지금 바뀔 가능성이 큰 것
- `classify.py` families_path 기본값 (job_families.json → job_families_top8.json 전환 시점)
- `analyze.py` min_sample_count 적정값 (role 단위로 바뀌면 더 작은 값이 필요할 수 있음)
- `assess_low_quality_job()` shallow aggregate 기준 수치 (0.3, 0.5 등 임의값 조정 필요)
- role 검수 CSV 포맷 (preview 위주로 줄일지 여부)

## 7) 보류 항목
- PaddleOCR 도입
  - 텍스트 추출 실험은 했지만, 메인 수집 경로로는 채택하지 않음
  - 복합공고에서 role/요건 매칭 안정성이 핵심이라 image-based Gemini Vision 유지
- Supabase 적재
- RAG / 임베딩 연결
- 잡코리아 외 타 사이트 카테고리 수집
- `경기청년 일자리 매치업` 유형 특이케이스 일반화

## 8) 다음 세션에서 꼭 볼 것
- `docs/SAVE_STATE.md`
- `output/export_db_roles_*.csv` (role 단위 검수)
- `output/low_quality/` (shallow aggregate가 걸러지는지)
- GUI 상단 DB 현황 숫자 (role 기준)
- `docs/IMPLEMENTATION_PLAN.md` 워크로그 최신 항목
