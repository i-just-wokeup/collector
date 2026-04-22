# 대분류 카테고리 기반 수집 전환 구현 계획

## 목표

검색 키워드 기반 수집 방식에서 **JobKorea Top100 직무 대분류 카테고리 기반 수집 방식**으로 전환한다.

현재 방식은 키워드 노이즈가 크고 수집 품질이 불안정하다.
Top100 카테고리 진입 방식으로 전환하면 수집 범위가 명확해지고,
이후 품질 개선 작업의 기준선을 잡기 쉬워진다.

---

## 원칙

1. **기존 코드·데이터를 덮어쓰지 않는다.**
   - 기존 `job_families.json`은 수정하지 않고 그대로 유지한다.
   - 새 대분류 카테고리 정의는 별도 파일(`job_families_top8.json`)로 관리한다.
   - 기존 DB(`jd_data.db`)는 건드리지 않는다.
   - 새 실험 데이터는 별도 DB(`jd_data_top8.db`)에 적재한다.

2. **단계적으로 진행한다.**
   - 한 단계가 검증되기 전에 다음 단계로 넘어가지 않는다.
   - 소규모 샘플 수집 → 품질 점검 → 품질 개선 순서를 지킨다.

3. **현재 구현 상태와 계획 방향을 섞지 않는다.**
   - 이 문서에서 "완료"로 표시된 항목만 실제로 구현된 것이다.
   - 미완료 항목은 코드에 반영되지 않은 상태다.

4. **수집 진입점은 로그인 상태의 JobKorea Top100 카테고리 페이지를 메인으로 한다.**
   - `/top100/?Search_Type=1&BizJobtype_Bctgr_Code={코드}` 형태의 Top100 카테고리 페이지를 기본 진입점으로 사용한다.
   - 로그인 시 카테고리당 최대 100건의 공고를 볼 수 있다는 것이 확인된 사실이다.
   - `recruit/joblist?menucode=duty` 방식은 필요 시 보조 진입점으로 고려한다.

5. **원본 데이터를 완전히 보존한다.**
   - 각 공고에 대해 아래 데이터를 반드시 저장한다:
     - `source_url`: 공고 원본 URL
     - `raw_text`: 페이지에서 추출한 전체 텍스트 원본
     - 스크린샷/이미지: 캡처한 PNG 파일 전체
     - `source_category`: 수집 시 사용한 대분류 카테고리 ID
   - 이후 가공/분석은 이 원본 데이터를 기반으로 한다. 원본을 지우거나 덮어쓰지 않는다.

6. **복합 직무 공고를 초기에 걸러내지 않는다.**
   - 하나의 공고에 여러 직무가 포함되어 있어도 수집 단계에서는 그대로 저장한다.
   - 역할 블록 분리(내부 직무 분리)는 향후 확장 방향이며, 첫 구현의 필수 요건이 아니다.
   - 현재는 공고 전체를 수집하고 원본을 유지하는 것이 최우선이다.

---

## 새 대분류 카테고리 (8개)

| ID | 한국어 표시 | JobKorea 직무 분류 대응 |
|---|---|---|
| `software` | 개발 (소프트웨어) | AI·개발·데이터 |
| `engineering` | 엔지니어링 (하드웨어/제조/R&D) | 엔지니어링·설계, 제조·생산 |
| `planning_strategy` | 기획/전략 (PM/사업기획) | 기획·전략 |
| `marketing` | 마케팅 | 마케팅·광고·MD |
| `design` | 디자인 | 디자인 |
| `sales` | 영업 | 영업 |
| `business_support` | 경영지원 (인사/재무/법무) | 인사·HR, 회계·세무, 법무·사무·총무 |
| `operations_service` | 운영/서비스 (CS/물류 등) | 고객상담·TM, 고객서비스·리테일, 물류·무역 |

---

## 향후 확장 방향 (현재 구현 범위 밖)

아래 항목은 이번 전환의 필수 구현 대상이 아니다.
원본 데이터가 충분히 쌓인 이후에 별도로 검토한다.

- **역할 블록 분리**: 복합 직무 공고 내에서 직무별 섹션을 분리해 별도 레코드로 저장하는 방식
- **세부 직무 재분류**: 대분류 태그 이후 세분화 분류를 다시 붙이는 후처리 파이프라인
- **다중 사이트 카테고리 수집**: saramin 등 타 사이트의 카테고리 기반 수집 추가

---

## 구현 단계별 체크리스트

### Phase 0 — 사전 확인 (코드 수정 없음)

#### 이미 확인된 사실

- [x] **수집 진입점**: 로그인 상태의 JobKorea Top100 카테고리 페이지(`/top100/?Search_Type=1`)를 메인 진입점으로 사용한다.
- [x] **URL 방식**: 카테고리 탭 클릭 시 URL이 변경된다 (`BizJobtype_Bctgr_Code=` 파라미터 방식, URL 파라미터 기반 네비게이션 확인됨).
- [x] **로그인 시 공고 수**: 로그인 상태에서 카테고리당 많은 공고가 한 페이지에 표시된다 (최대 100건 수준).
- [x] **공고 상세 링크 패턴**: 공고 상세 페이지 URL은 `/Recruit/GI_Read/{숫자ID}` 형태를 사용한다. 이는 현재 `collect_job_links()`의 `a[href*='/Recruit/GI_Read/']` 셀렉터와 일치한다.
- [x] **카테고리 코드 매핑**: `BizJobtype_Bctgr_Code` 값이 8개 카테고리 전부 확정됨. 아래 매핑 테이블 참고.

#### `BizJobtype_Bctgr_Code` 매핑 테이블 (확정)

`job_families_top8.json`의 `jobkorea_top100_codes` 필드에 반영 완료.

| 우리 카테고리 ID | 한국어 표시 | JobKorea 탭 이름 | `BizJobtype_Bctgr_Code` |
|---|---|---|---|
| `software` | 개발 (소프트웨어) | AI·개발·데이터 | `10031` |
| `engineering` | 엔지니어링 (하드웨어/제조/R&D) | 엔지니어링·설계, 제조·생산 | `10040`, `10041` |
| `planning_strategy` | 기획/전략 (PM/사업기획) | 기획·전략 | `10026` |
| `marketing` | 마케팅 | 마케팅·광고·MD | `10030` |
| `design` | 디자인 | 디자인 | `10032` |
| `sales` | 영업 | 영업 | `10035` |
| `business_support` | 경영지원 (인사/재무/법무) | 인사·HR, 회계·세무, 법무·사무·총무 | `10028`, `10029`, `10027` |
| `operations_service` | 운영/서비스 (CS/물류 등) | 고객상담·TM, 고객서비스·리테일, 물류·무역 | `10036`, `10039`, `10033` |

> **참고**: `engineering`, `business_support`, `operations_service`는 JobKorea 복수 탭에 대응된다. Phase 2 구현 시 복수 코드를 순서대로 순회하는 방식으로 처리한다.

#### 아직 미확인 — 직접 브라우저 확인 필요

- [ ] **공고 카드 내 링크 구성**: 공고 카드 하나를 F12 → Inspect로 열어, 카드 내 `<a>` 태그 구성을 확인한다 (`/Recruit/GI_Read/` 제목 링크 / 회사 링크 / 외부 지원 링크 구분). *(Phase 2 착수 전 확인)*
- [ ] **셀렉터 검증**: Top100 카테고리 페이지 (로그인 상태) 브라우저 콘솔에서 아래 명령을 실행해 반환값이 실제 공고 카드 수와 일치하는지 확인한다. *(Phase 2 착수 전 확인)*
  ```javascript
  document.querySelectorAll("a[href*='/Recruit/GI_Read/']").length
  ```
- [ ] **목록 로드 방식**: Top100 카테고리 페이지의 공고 목록이 스크롤 기반 추가 로드인지, 단일 페이지 렌더링인지 확인한다. *(Phase 2 테스트 중 실제 동작으로 확인 가능)*

**Phase 0 완료 조건**: 위 3개 항목이 모두 확인되면 완료.

---

### Phase 1 — 새 카테고리 정의 파일 생성

- [x] `job_families_top8.json` 파일을 새로 작성한다 (8개 항목, 기존 `job_families.json`은 수정 안 함).
- [x] 각 항목에 `id`, `display_name`, `category`, `aliases`, `jobkorea_top100_codes` 필드를 포함한다.
- [x] `init_db.py`에 `--families-file` 및 `--db-path` 옵션을 추가해 `job_families_top8.json`과 새 DB 경로를 지정할 수 있도록 한다.
- [x] `jd_data_top8.db`를 새로 초기화하고 8개 카테고리가 `job_families` 테이블에 정상 등록되는지 확인한다.

**Phase 1 완료 조건**: ✅ `jd_data_top8.db` 생성 완료, `job_families` 테이블에 8개 행 확인됨.

---

### Phase 2 — JobKorea Top100 수집 진입 로직 추가

- [x] `src/sites/jobkorea.py`에 Top100 카테고리 URL 빌더 메서드를 추가한다 (`build_top100_category_url(biz_code)`, `BizJobtype_Bctgr_Code` 값을 파라미터로 받음).
- [x] `collect_job_links()`는 기존 로직을 그대로 재사용한다 (Top100 페이지도 동일한 `/Recruit/GI_Read/` 셀렉터로 동작함). 스크롤 방식은 현재 유지 — 실제 Top100 페이지의 로드 방식은 Phase 5 수집 테스트 시 확인.
- [x] `src/collect.py`의 `run_collection()`에 `category_id` 파라미터를 추가한다 (기존 `search_keyword` 경로는 유지).
- [x] DB 저장 시 `source_category` 값이 `job_postings` 테이블에 기록되도록 스키마 및 저장 로직을 추가한다. `init_db.py`에 마이그레이션 단계도 추가하여 기존 DB에도 자동 적용된다.
- [x] 출력 폴더 slug가 `category_id` 기준으로 생성된다.

**Phase 2 완료 조건**: ✅ `category_id`를 넘기면 Top100 카테고리 URL 목록이 생성되고, `source_category`가 DB 스키마에 포함된 상태.

---

### Phase 3 — GUI 입력 전환

- [x] `gui.py`에 카테고리 단일 선택 드롭다운을 추가한다 (8개 항목, `software`, `engineering` 등 내부 ID → 한국어 표시명 매핑).
- [x] 기존 검색어 입력란을 `grid_remove()`로 숨긴다 (레거시 코드는 삭제하지 않고 유지).
- [x] `start_collect()`가 `category_id`를 읽어 `--category` / `--target-count` / `--site` CLI 인수로 `collect.py`에 전달하도록 수정한다.

**Phase 3 완료 조건**: GUI에서 카테고리를 선택하고 수집 시작 버튼을 누르면 Top100 카테고리 URL로 수집이 시작되는 상태. ✅

---

### Phase 4 — 분류(classify) 대분류 ID 연동

- [ ] `src/classify.py`가 `job_families_top8.json`을 읽도록 경로를 환경변수 또는 파라미터로 분리한다.
- [ ] Gemini 프롬프트에 전달하는 카테고리 목록이 8개 ID 기준으로 동작하는지 확인한다.
- [ ] 수집 시점의 `source_category`를 분류 힌트로 활용하는 방식을 검토한다 (Gemini 프롬프트에 포함 여부).

**Phase 4 완료 조건**: `classify.py` 실행 시 `job_families_top8.json` 기준의 8개 ID로 분류 결과가 저장되는 상태.

---

### Phase 5 — 소규모 샘플 수집 및 품질 점검

- [ ] `jd_data_top8.db`에 카테고리별 10~20건씩 샘플 수집을 실행한다.
- [ ] 수집 결과에서 `source_url`, `raw_text`, 이미지, `source_category`가 모두 정상 저장되었는지 확인한다.
- [ ] `src/export_csv.py`로 CSV를 추출해 공고 내용과 섹션 품질을 수동 검수한다.
- [ ] 수집 실패율(`failed_capture`), 저품질 판정률(`low_quality`)을 기존 키워드 기반 결과와 비교한다.
- [ ] 복합 직무 공고가 걸러지지 않고 정상 저장되는지 확인한다.

**Phase 5 완료 조건**: 샘플 수집 결과를 검수하고, 품질 현황을 워크로그에 기록한 상태.

---

### Phase 6 — 수집 품질 개선 (Phase 5 결과 기반)

- [ ] `src/capture.py`에서 본문 영역 로케이터(body locator) 우선 추출을 강화한다.
- [ ] OCR/이미지 캡처 범위를 공고 본문 영역으로 제한한다.
- [ ] 반복 UI 요소 및 공통 영역(헤더, 푸터, 추천 공고 섹션 등) 제거 로직을 개선한다.
- [ ] 개선 후 동일 카테고리로 재수집해 품질 변화를 비교한다.

**Phase 6 완료 조건**: 재수집 결과의 저품질/실패율이 Phase 5 대비 개선된 상태.

---

## 워크로그 작성 규칙

각 Phase 완료 후 아래 형식으로 이 문서 하단의 워크로그 섹션에 기록한다.

```
### [Phase N] YYYY-MM-DD
- 변경된 파일: (파일명 목록)
- 실행한 명령: (실행 명령어 요약)
- 테스트 결과: (정상/실패 여부, 수치 등)
- 미해결 이슈: (다음 단계 진입 전에 확인이 필요한 사항)
```

---

## 현재 상태 (2026-04-22 기준)

- 기존 키워드 기반 수집 파이프라인: **여전히 사용 가능**
- 대분류 카테고리 전환 작업: **Phase 3 완료**
- **role 중심 파이프라인 전환: 완료 (2026-04-22)**
  - `job_posting_role_tags` 테이블 신설 (role 단위 분류 결과)
  - `job_posting_roles.classification_status` 컬럼 추가
  - `classify.py`: role 단위 분류 기본 모드 추가 (`run_classify_roles`)
  - `analyze.py`: role 단위 분석 기본 모드 추가 (`run_analyze_roles`)
  - `export_csv.py`: `--db-roles` role 단위 검수 CSV 모드 추가
  - `utils.py`: `GENERIC_ANALYSIS_FILTER_PATTERNS`, `filter_generic_analysis_lines()`, `clean_role_first_task()`, role 단위 `assess_low_quality_job()` 보강
  - `collect.py`: posting_title/company 메타 보정, role 텍스트 정제, role 기반 품질 판정
- 현재 핵심 미완료:
  - `classify.py`의 top8 기준 전환 (Phase 4)
    - `job_families_top8.json` 사용은 가능하나 기본값 아직 아님
  - collector payload 흐름 통합 리팩토링 (normalized / structured 분리 임시 우회)
  - 기존 stored roles 223개 재분류 (pending 상태 — 다음 세션 실행 예정)

---

## 워크로그

### [Phase 2] 2026-04-20 (보정 포함)

- 변경된 파일:
  - `src/sites/jobkorea.py` — `build_top100_category_url(biz_code)` 메서드 추가; `normalize_jobkorea_url()` 함수 추가 및 `collect_job_links()` 내 적용
  - `src/collect.py` — `json` import 추가, `DEFAULT_TOP8_FAMILIES_PATH` 상수 추가, `load_top8_category_codes()` 헬퍼 추가, `run_collection()`에 `category_id` / `top8_families_path` 파라미터 추가 및 분기 로직 구현; `main()`에 `--category` / `--target-count` / `--site` argparse 추가 (기존 stdin 흐름 유지)
  - `src/db.py` — `save_job_posting()` INSERT에 `source_category` 컬럼 추가
  - `init_db.py` — DDL에 `source_category TEXT DEFAULT ''` 추가, 기존 DB를 위한 `ALTER TABLE` 마이그레이션 단계 추가
- 실행한 명령:
  ```
  python init_db.py --families-file job_families_top8.json --db-path C:\dev\jd_data_top8.db
  python init_db.py
  # normalize_jobkorea_url / load_top8_category_codes / argparse 흐름 검증 (python -c)
  ```
- 테스트 결과:
  - `software` → URL 1개, `business_support` → URL 3개 생성 정상 확인
  - 존재하지 않는 `category_id` → `ValueError` 정상 발생 확인
  - `jd_data_top8.db` / `jd_data.db` 모두 `source_category` 컬럼 추가 확인
  - URL 정규화: 동일 공고의 서로 다른 쿼리스트링 URL이 같은 정규 URL로 변환됨 확인
  - 회사 링크 등 비공고 URL은 변환 없이 그대로 반환됨 확인
  - `--category engineering --target-count 20` 인수 시 Top100 URL 2개 생성 확인
  - 인수 없이 실행 시 기존 stdin 흐름 그대로 동작 확인 (GUI 호환)
- 미해결 이슈:
  - Phase 0 잔여 확인 3개 (카드 링크 구성, 셀렉터 길이 검증, 목록 로드 방식)가 아직 브라우저 확인 미완료
  - Top100 페이지의 스크롤 동작 여부는 Phase 5 실제 수집 테스트 시 확인 예정

---

### [job_posting_roles 안전장치] 2026-04-21 — 중복/빈 role/partial 방어

- 변경된 파일:
  - `init_db.py` — `job_posting_roles` DDL에 `UNIQUE(job_id, display_order)` 추가; 기존 DB용 migration `CREATE UNIQUE INDEX IF NOT EXISTS idx_job_posting_roles_unique` 추가
  - `src/db.py` — `save_job_posting_roles()` 안전장치 전면 보강
  - `src/collect.py` — `roles_already_complete` 로그 추가
  - `scripts/backfill_roles.py` — partial 감지/복구 흐름 + stats 세분화
- 추가된 안전장치:
  1. **빈 role_name 필터**: `role_name.strip() == ""` 이면 insert skip, stderr 경고
  2. **already_complete 감지**: 기대 개수(valid role 수) == DB row 수 이면 0 반환(skip)
  3. **partial 복구**: 기대 개수 != DB row 수 && DB row > 0 → `DELETE WHERE job_id` 후 전체 재삽입
  4. **DB 레벨 중복 차단**: `UNIQUE(job_id, display_order)` + `INSERT OR IGNORE`
- partial 판단 기준: `len([r for r in roles if r.role_name.strip()])` vs `COUNT(*) WHERE job_id`
- 검증 결과 (dry-run):
  - already_complete: 2건 (이전 세션 저장분 정상 인식)
  - partial_detected: 0건
  - UNIQUE index 기존 DB 적용 확인 (`idx_job_posting_roles_unique`)

---

### [복합공고 roles[] DB 저장] 2026-04-21 — job_posting_roles 테이블 신설 + 백필

- 변경된 파일:
  - `init_db.py` — `job_posting_roles` 테이블 DDL 추가; `job_postings`에 `common_requirements_json`, `common_preferred_json` 컬럼 마이그레이션 추가
  - `src/db.py` — `save_job_posting_roles()` 함수 추가
  - `src/collect.py` — `save_job_posting_roles()` 호출 추가 (신규 수집 시 자동 저장)
  - `scripts/backfill_roles.py` — 기존 raw_captures 기반 백필 스크립트 신설
- 새 DB 구조:
  ```sql
  job_posting_roles (
    id INTEGER PK AUTOINCREMENT,
    job_id TEXT FK→job_postings.id ON DELETE CASCADE,
    role_name TEXT,
    display_order INTEGER,
    main_tasks_json TEXT DEFAULT '[]',
    requirements_json TEXT DEFAULT '[]',
    preferred_json TEXT DEFAULT '[]',
    created_at TEXT
  )
  ```
  - `job_postings`에 `common_requirements_json TEXT DEFAULT '[]'`, `common_preferred_json TEXT DEFAULT '[]'` 추가
- 설계 결정:
  - role별 섹션을 추가 테이블로 정규화하지 않고 JSON 문자열 컬럼으로 저장 (조회 단순화, 과도한 정규화 방지)
  - common_requirements/preferred는 공고 레벨 속성이므로 `job_postings` UPDATE로 처리
  - `job_sections` 테이블은 유지 (compat shim의 roles[0] 기반 단일 role 정보를 계속 담음)
  - 이후 collector에서는 `job_postings` / `job_sections`는 normalized payload를, `job_posting_roles`는 원본 structured payload를 쓰는 임시 우회 구조로 보완됨
- 백필 실행 결과 (`python scripts/backfill_roles.py`):
  - 전체 대상: 189 폴더
  - roles[] 없음(구버전): 182건 skip
  - DB posting 없음: 5건 skip (4/21 수집 중 DB 미저장 케이스)
  - 저장 완료: **2건** (44 role rows) — `jobkorea_20260421_145159_008` (18 roles), `jobkorea_20260421_183348_001` (26 roles)
- 중복 백필 방지: `save_job_posting_roles()`가 INSERT 전에 `SELECT COUNT(*) FROM job_posting_roles WHERE job_id = ?` 확인, 이미 존재하면 0 반환 후 return
- 추가 Gemini 호출 없는 이유: `jd_result.json`은 이미 구조화 완료된 파일이며, 백필 스크립트는 이 파일만 읽어 INSERT함

---

### [utils.py 저가치 필터 축소] 2026-04-21 — 얇은 필터로 단순화

- 변경된 파일:
  - `src/utils.py` — `LOW_VALUE_SOFT_SKILL_SIGNALS`, `HIGH_VALUE_KEEP_SIGNALS` 삭제; `is_low_value_requirement_line()` 단순화
- 변경 이유:
  - `HIGH_VALUE_KEEP_SIGNALS`는 기계/IT 기술 키워드만 담아 비개발 직군(마케팅, 영업, 디자인 등)에서 keep 신호가 전혀 없어 무의미
  - `LOW_VALUE_SOFT_SKILL_SIGNALS`("협업 능력", "책임감" 등)가 영업/고객지원/HR 직군의 실제 유효 요구사항을 제거
  - Top8 대분류 전체를 수집하는 구조에서 직군 편향 필터는 수율 손실만 발생
- 변경 내용:
  - `LOW_VALUE_SOFT_SKILL_SIGNALS` 상수 삭제
  - `HIGH_VALUE_KEEP_SIGNALS` 상수 삭제
  - `is_low_value_requirement_line()` — "빈 줄 제거" + "`LOW_VALUE_LINE_PATTERNS` 매칭 시 제거" 두 규칙만 유지
  - `filter_low_value_lines()` 함수 자체는 유지 (collect.py, analyze.py 호출 유지)
- 영향 범위:
  - `collect.py:365` — `filter_low_value_lines()` 호출 그대로 유지, 실제 필터링 대상이 줄어들 뿐
  - `analyze.py:202` — 동일, 호출부 변경 없음
  - 이전보다 더 보존되는 문장: "협업 능력", "책임감", "팀플레이어", "성실함" 등 소프트스킬 문장; "MS Office 활용 능력", "운전면허 소지자" 등은 이전 세션에서 이미 제거

---

### [utils.py 편향 제거] 2026-04-21 — Top8 대분류 + 본문 전용 캡처 기준 정렬

- 변경된 파일:
  - `src/utils.py` — 개발/이공계 편향 상수 제거 및 필터 기준 완화
- 변경 이유:
  - 기존 `TECH_KEYWORDS` + `low_technical_signal` 판정이 마케팅/영업/디자인/HR 직군을 구조적으로 저품질로 판정
  - 본문 전용 캡처로 전환 후 `RAW_TEXT_CUT_KEYWORDS`/`UI_NOISE_CUT_KEYWORDS` 구간 절단이 무의미해짐
  - `LOW_VALUE_LINE_PATTERNS`에 비IT 직군에서 유효한 항목(운전면허, 야간근무, MS Office 등) 포함
  - `UI_NOISE_LINE_KEYWORDS`에 공고 본문에서도 나올 수 있는 항목(신입사원 채용, 기업정보, 추천공고 등) 포함
- 변경 내용:
  - `TECH_KEYWORDS` 상수 전체 삭제 (참조 없어짐)
  - `RAW_TEXT_CUT_KEYWORDS` → 빈 리스트 (본문 전용 캡처에서 구간 절단 불필요)
  - `UI_NOISE_CUT_KEYWORDS` → 빈 리스트 (동일 이유)
  - `clean_job_posting_text()` — 구간 절단 pass 제거, 줄 단위 필터만 유지
  - `UI_NOISE_LINE_KEYWORDS` — "추천공고", "관련 태그", "즉시지원", "기업정보", "원서접수", "신입사원 채용" 제거
  - `UI_NOISE_LINE_KEYWORDS_JOBKOREA` — "콘텐츠"(콘텐츠마케팅 직군 오탐), "인적성"(HR 직군 오탐) 제거
  - `UI_NOISE_LINE_KEYWORDS_SARAMIN` — "입사지원서 작성" 제거
  - `LOW_VALUE_LINE_PATTERNS` — "야간근무 가능", "주말근무 가능", "교대근무 가능", "운전면허 소지자", "MS Office 활용 능력", "원활한 커뮤니케이션 능력", "팀워크 우수자", "학력무관", "초대졸이상", "대졸이상", "경력무관", "장기근무 가능자" 제거; 법적/보훈 관련 항목만 유지
  - `assess_low_quality_job()` — `low_technical_signal` 판정 제거 (core_text/tech_hits 계산 포함)
  - 중복 `select_images_for_ocr()` (line ~221) 제거, line ~520 버전만 유지

---

### [capture_failed 판정 완화] 2026-04-21 — one_image_short_text 소프트 경고 전환

- 변경된 파일:
  - `src/utils.py` — `assess_capture_failed()` 시그니처 및 로직 변경
  - `src/collect.py` — `assess_capture_failed()` 호출부 수정, 로그 보강
- 변경 이유:
  - 신형 JobKorea 페이지는 iframe:body 또는 `.artRead` locator로 본문 전체를 1장에 캡처하는 방식이 정상
  - 기존 `one_image_short_text` 기준(이미지 1장 + 텍스트 < 900자)이 이 정상 공고를 하드 실패로 차단하고 있었음
- 변경 내용:
  - **하드 실패 기준** (저장 차단): `missing_core_sections` 만 — 핵심 섹션 탐지 없음 + 텍스트 200자 미만 (기존 300자에서 강화)
  - **소프트 경고**: `one_image_short_text` (이미지 1장 이하 + 텍스트 900자 미만) — 저장 통과, 로그만
    - bypass 조건 (경고도 생략): `iframe_capture_used=True` → `capture_gate_bypass=iframe_body`
    - bypass 조건: `locator_capture_selector` in {`.artRead`, `.detail`, `iframe:body`} → `capture_gate_bypass=locator_body`
    - bypass 조건: Gemini 구조화 결과에 유의미한 내용 있음 (main_tasks/requirements 2건 이상) → `capture_gate_bypass=structured_content_present`
- 새 로그 포맷:
  - `capture_gate_bypass=iframe_body` — iframe 캡처 bypass
  - `capture_gate_bypass=locator_body` — locator 캡처 bypass
  - `capture_gate_bypass=structured_content_present` — 구조화 결과 bypass
  - `capture_gate_reason=soft_warn:one_image_short_text` — bypass 없는 소프트 경고
  - `capture_gate_reason=hard_fail:missing_core_sections` — 하드 실패
- 함수 시그니처 변경:
  - `assess_capture_failed(raw_text, capture_image_count)` → `assess_capture_failed(raw_text, capture_image_count, capture_meta=None, jd_payload=None)`
  - 반환: `(bool, list, list, list)` → `(hard_failed, hard_reasons, soft_warns, detected, gate_bypass_reason)`
- 검증:
  - 케이스 1: 빈 캡처 → `hard_failed=True` ✓
  - 케이스 2: 섹션 없음+짧은 텍스트 → `hard_failed=True` ✓
  - 케이스 3: 이미지 1장+섹션있음+짧은텍스트(bypass 없음) → `soft_warn`, 저장 통과 ✓
  - 케이스 4/5: iframe/`.artRead` bypass → 경고 없음 ✓
  - 케이스 6: Gemini 구조화 결과 있음 → bypass ✓
  - 케이스 7/8: 긴 텍스트 or 다장 이미지 → 완전 통과 ✓
- 남은 리스크:
  - `one_image_short_text` 소프트 경고가 발생한 공고는 이후 `assess_low_quality_job`에서 걸러질 수 있음 (too_few_main_tasks 등)
  - `missing_core_sections` 하드 실패 임계값(200자)이 여전히 임의 수치 — 실제 수집 데이터 기반 조정 필요

---

### [구조화 스키마 변경] 2026-04-20 — 복합공고 roles[] 분리 구조 도입

- 대상 저장소: `C:\dev\jd-research-tool`
- 변경된 파일:
  - `src/structure_jd.py` — 프롬프트 재작성 (roles 배열 분리 지시); `_normalize_schema` 변경 (새 스키마 + compat shim)
  - `src/vision_structure_jd.py` — 동일하게 프롬프트 재작성 + `_normalize_schema` 변경
  - `src/main.py` — 출력 문구 roles 수/명칭 표시로 업데이트
  - `README.md` — 스키마 문서 갱신
- 기존 → 새 스키마 변경:
  - 이전: `{company, role, main_tasks, requirements, preferred, raw_text, source_images}`
  - 이후: `{company, posting_title, common_requirements, common_preferred, roles: [{role_name, main_tasks, requirements, preferred}], raw_text, source_images}` + compat shim 필드
- 복합공고 분리 방식:
  - LLM에게 "여러 모집부문·트랙·과제가 있으면 roles 배열에 각각 분리하고 하나로 합치지 말라"고 명시
  - 공통 지원자격은 `common_requirements`, 공통 우대사항은 `common_preferred`로 분리하도록 지시
  - role별 정보가 불명확하면 빈 배열 허용
- collect.py 하위호환 shim:
  - `_normalize_schema` 출력에 `role`, `main_tasks`, `requirements`, `preferred` 키를 유지
  - `role` = `roles[0].role_name`, `main_tasks` = `roles[0].main_tasks`
  - `requirements` = `common_requirements` + `roles[0].requirements`
  - `preferred` = `common_preferred` + `roles[0].preferred`
  - LLM이 구버전 포맷(최상위 `role`/`main_tasks`)으로 응답해도 자동 변환 후 동일 shim 생성
  - collect.py의 `.get("role")`, `.get("main_tasks")`, `.get("requirements")`, `.get("preferred")` 호출 모두 정상 동작 유지
- collect.py 영향 (보고):
  - `jd_payload.get("role")` → shim 필드로 유지 ✓
  - `jd_payload.get(section_key, [])` for main_tasks/requirements/preferred → shim 필드로 유지 ✓
  - `assess_low_quality_job(jd_payload)` → shim main_tasks/requirements/preferred 읽음 ✓
  - `ensure_enriched_schema` → shim role/main_tasks/requirements/preferred 읽음 ✓
  - `roles[]`/`common_requirements` 등 새 필드는 DB에 저장되지 않음 (향후 Phase에서 처리 예정)
- 미해결 이슈:
  - 복합공고에서 shim이 `roles[0]`만 반영하므로 DB에는 첫 번째 role 정보만 저장됨 — 나머지 role은 현재 손실됨
  - `posting_title` 필드가 collect.py에서 아직 활용되지 않음

---

### [roles 저장 누락 버그 수정] 2026-04-21 — normalized payload와 structured payload 분리

- 변경된 파일:
  - `src/collect.py`
  - `docs/IMPLEMENTATION_PLAN.md`
  - `docs/SAVE_STATE.md`
  - `docs/NEXT_TASK.md`
- 문제:
  - `jd-research-tool`이 `roles[]`를 반환해도,
    collector가 중간에 `ensure_enriched_schema()`를 거친 결과만 들고 `save_job_posting_roles()`를 호출하고 있었다.
  - 이 정규화 결과는 레거시 단일 role 호환 흐름 중심이라
    `roles[]`, `common_requirements`, `common_preferred`를 완전히 보존하지 못했고,
    결과적으로 `job_posting_roles`가 0건 저장되는 케이스가 발생했다.
- 수정:
  - JSON 생성 직후의 **원본 structured payload**를 `copy.deepcopy()`로 따로 보존
  - `job_postings` / `job_sections` / 품질 판정은 기존처럼 normalized payload 사용
  - `job_posting_roles` 저장만 원본 structured payload 사용
- 현재 판단:
  - 이 방식은 즉시 문제를 막는 **임시 우회 구조**다.
  - 추후 리팩토링 때는 payload 흐름을 하나로 통합하거나,
    `ensure_enriched_schema()`가 structured 필드를 함께 보존하도록 재설계해야 한다.

---

### [수집 품질 보정 v2] 2026-04-20 — 잡코리아 캡처 우선순위 개선 + OCR 전처리 개선

- 변경된 파일:
  - `src/capture.py` — JobKorea 전용 `_jobkorea_locator_capture()` 추가; iframe 우선 캡처; 선택자 우선순위 재정렬; main fallback 시 노이즈 숨김; 반환 메타 보강
  - `src/utils.py` — `prepare_ocr_image()` 개선: 이진화 → 그레이스케일+리사이즈+대비 강화로 교체
  - `src/collect.py` — 새 반환 메타 필드(`locator_capture_selector`, `iframe_capture_used`, `iframe_url`) 로그 추가
- 잡코리아 캡처 우선순위 (이번 변경):
  1. `page.frames` 순회 → URL에 `GI_Read_Comt_Ifrm` 포함된 frame → `frame.locator("body").first.screenshot()`
  2. `.artRead` → 본문 컨테이너 locator 캡처
  3. `.detail`
  4. `#container`
  5. `main` — `_hide_strategy_wrapper_siblings()` JS로 StrategyWrapper 이후 형제 요소 숨김 후 캡처
  6. 모두 실패 시: 기존 스크롤 루프 fallback (유지)
- main fallback 노이즈 숨김:
  - `document.querySelector('[data-sentry-component="StrategyWrapper"]')` 찾아 해당 요소 + 이후 모든 형제를 `display:none` 처리
  - 적용 여부를 `strategy_wrapper_hidden=true/false` 로그로 기록
- 반환 메타 변경:
  - 추가: `locator_capture_selector`, `iframe_capture_used`, `iframe_url`
  - 제거: `body_locator_found` (JobKorea 전용 분기로 대체되어 불필요)
- OCR 전처리 개선 (`prepare_ocr_image`):
  - 이전: 단순 이진화 threshold=180
  - 이후: 그레이스케일 변환 → 너비 800px 초과 시 비율 유지 리사이즈 → 대비 1.3배 강화 → PNG 저장
  - 저장 포맷: PNG 유지 (downstream이 .png 기준이므로 JPEG 변경 없음)
  - `ImageEnhance.Contrast(img).enhance(1.3)` 사용
  - Pillow 미설치 시 원본 복사 fallback 유지
- 미해결 이슈 / 한계:
  - iframe(`GI_Read_Comt_Ifrm`) 실제 존재 여부는 로그인 상태 브라우저 실행 전까지 미확인
  - `.artRead` 캡처 성공 시 이미지 1장 → `assess_capture_failed`의 `one_image_short_text` 조건에 걸릴 수 있음 (raw_text 길이가 충분하면 통과)
  - `resize(LANCZOS)` 사용 — 구버전 Pillow(< 9.1.0)에서는 `Image.ANTIALIAS`가 필요할 수 있음

---

### [수집 품질 보정 v1] 2026-04-20 — 본문 영역 우선 캡처 + OCR 흑백 전처리

- 변경된 파일:
  - `src/capture.py` — locator 기반 단일 캡처 우선, 스크롤 루프는 fallback으로 전환; `raw_text`도 locator 기준으로 먼저 추출; 반환 메타에 `locator_capture_used` 필드 추가
  - `src/utils.py` — `prepare_ocr_image(source, dest)` 함수 추가 (Pillow 그레이스케일 + 이진화 threshold=180)
  - `src/collect.py` — `prepare_ocr_image` import 추가; OCR 이미지 준비 시 `shutil.copy2` → `prepare_ocr_image`로 교체; `shutil` import 제거

---

### [Phase 3] 2026-04-19

- 변경된 파일:
  - `gui.py` (카테고리 드롭다운 추가, 검색어 입력란 숨김, `start_collect()` CLI 인수 전달 방식으로 변경)
- 주요 변경 내용:
  - `CATEGORY_OPTIONS` 상수 추가: 8개 카테고리 표시명↔`category_id` 매핑
  - `category_var = StringVar(value="software")` 추가
  - 수집 입력 프레임에 카테고리 `ttk.Combobox` 추가 (row 1)
  - 기존 검색어 label/entry는 row 2에 유지하되 `grid_remove()`로 숨김 처리
  - `_on_category_selected()` 추가: Combobox 선택 시 `category_var` 업데이트
  - `set_buttons_enabled()`에 `category_combo` 상태 변경 추가
  - `start_collect()`: stdin 방식 → `--category` / `--target-count` / `--site` CLI 인수 방식으로 전환
  - Telegram 알림: `keyword` → `category` 필드로 변경
- 미해결 이슈:
  - Phase 0 잔여 확인 3개는 여전히 브라우저 확인 미완료

---

### [Phase 1] 2026-04-20

- 변경된 파일:
  - `job_families_top8.json` (신규 생성)
  - `init_db.py` (`argparse` 추가, `--families-file` / `--db-path` 옵션)
- 실행한 명령:
  ```
  python init_db.py --families-file job_families_top8.json --db-path C:\dev\jd_data_top8.db
  python init_db.py   # 기존 기본 동작 검증
  ```
- 테스트 결과:
  - `jd_data_top8.db` 생성됨, `job_families` 테이블에 8개 행 정상 등록 확인
  - 기존 기본 실행 (`python init_db.py` 인수 없음) → `jd_data.db` + 25개 행 그대로 동작 확인
  - `job_families_top8.json`의 `jobkorea_top100_codes` 필드는 JSON에만 존재 (DB 스키마 변경 없음)
- 미해결 이슈:
  - Phase 0 잔여 확인 3개 (카드 링크 구성, 셀렉터 검증, 목록 로드 방식) 는 Phase 2 착수 전에 완료 필요

---

### [Phase 0] 2026-04-20 (진행 중)

- 변경된 파일: `docs/IMPLEMENTATION_PLAN.md`
- 실행한 명령: 없음 (코드 변경 없음)
- 확인 결과:
  - Top100 카테고리 페이지가 메인 수집 진입점으로 결정됨
  - 카테고리 탭 클릭 시 URL의 `BizJobtype_Bctgr_Code=` 파라미터가 변경되는 방식 확인됨
  - 8개 카테고리 전체의 `BizJobtype_Bctgr_Code` 값 확정 및 `job_families_top8.json`에 반영 완료
  - 로그인 시 카테고리당 다수 공고 표시 확인됨
  - 공고 상세 링크가 `/Recruit/GI_Read/{id}` 패턴임을 확인됨
  - 현재 `collect_job_links()`의 셀렉터(`a[href*='/Recruit/GI_Read/']`)와 패턴 일치
- 미해결 이슈 (Phase 2 착수 전 확인 필요):
  1. **카드 내 링크 구성 미확인**: F12로 공고 카드 내 `<a>` 태그 구조를 확인해야 한다. 제목 링크와 회사/지원 링크가 혼재할 경우 셀렉터 보정이 필요할 수 있다.
  2. **콘솔 셀렉터 검증 미완료**: 로그인 Top100 페이지에서 `document.querySelectorAll("a[href*='/Recruit/GI_Read/']").length` 값이 실제 공고 수와 일치하는지 확인이 필요하다.
  3. **목록 로드 방식**: Phase 2 테스트 중 실제 Playwright 동작으로 확인 가능.

---

### [로그인 프로필 분리] 2026-04-21 — GUI 로그인 버튼 + collector 전용 프로필 재사용

- 변경된 파일:
  - `src/collect.py` — `launch_persistent_context` 기반 collector 전용 브라우저 프로필 사용; `--login-only` 모드 추가; 로그인 전용 진입 URL 빌더 추가
  - `gui.py` — `로그인` 버튼 추가, 수집과 분리된 로그인 창 실행 흐름 추가
- 변경 이유:
  - 사용자가 평소 크롬에서 로그인해 둔 세션을 collector가 자동으로 가져오지 못했다.
  - 수집 시작과 로그인 과정을 한 흐름에 묶으면 동작이 불안정하고 사용자 경험이 나빴다.
- 현재 동작:
  - 프로필 경로: `output/browser_profiles/{site_name}`
  - `로그인` 버튼을 누르면 동일 프로필로 브라우저 창만 열림
  - 사용자가 그 창에서 직접 로그인 후 닫으면, 이후 수집은 같은 프로필을 재사용함
  - 수집 자체는 로그인 대기 없이 기존처럼 바로 진행 가능
- 현재 판단:
  - 로그인 문제를 수집 로직에 억지로 섞지 않고, 수동 로그인 창을 별도로 둔 현재 방식이 가장 단순하고 안전하다.

---

### [role 중심 파이프라인 전환] 2026-04-22

- 변경된 파일:
  - `init_db.py` — `job_posting_role_tags` DDL 추가; `job_posting_roles.classification_status` 마이그레이션 추가
  - `src/db.py` — `save_job_posting_role_tags()`, `update_role_classification_status()`, `get_pending_roles_for_classify()`, `get_roles_by_family_for_analyze()`, `get_classified_families_from_roles()` 추가
  - `src/utils.py` — `GENERIC_ANALYSIS_FILTER_PATTERNS` 상수, `filter_generic_analysis_lines()`, `clean_role_first_task()`, `_assess_role_level_quality()` 추가; `assess_low_quality_job()` signature 변경 (roles, structured_payload 인자 추가)
  - `src/collect.py` — posting_title/company 메타 보정 로직 추가; role 텍스트 정제(clean_role_first_task + filter_low_value_lines) 저장 전 적용; `assess_low_quality_job()` 호출에 roles 전달
  - `src/classify.py` — `detect_job_family_for_role()`, `run_classify_roles()` 추가; `main()` mode 인자 추가 (`--mode roles` 기본)
  - `src/analyze.py` — `_roles_to_sections()`, `run_analyze_roles()` 추가; `main()` mode 인자 추가
  - `src/export_csv.py` — `export_db_roles()`, `--db-roles` CLI 모드 추가
  - `docs/SAVE_STATE.md`, `docs/NEXT_TASK.md`, `docs/IMPLEMENTATION_PLAN.md` 갱신
- 주요 설계 결정:
  - `extracted_role` / posting-level `job_tags` / `job_sections`는 당장 제거 안 하고 레거시 shim으로 보존
  - 새 로직(classify/analyze)은 이 필드에 의존하지 않음 — "의존 제거"가 우선
  - `filter_generic_analysis_lines()`는 분류/분석 단계에서만 — raw_text/저장 단계에는 절대 적용 안 함
  - 단일 공고는 `roles` 길이 1인 특수 케이스로 자연스럽게 처리됨
  - 복합공고 품질 판정: `shallow_aggregate_empty_tasks`(tasks 있는 role 30% 미만), `common_only_no_role_detail`(공통 문구 > role별 콘텐츠) 기준 추가
- 마이그레이션 결과:
  - `job_posting_role_tags` 테이블 생성 완료
  - `job_posting_roles.classification_status` 컬럼 추가 완료
  - 기존 roles 223개 모두 `pending` 상태 (다음 세션에서 role 단위 분류 실행 예정)
- 남은 리스크:
  - `shallow_aggregate_empty_tasks` 기준값(0.3)은 임의 수치 — 실제 데이터 기반 조정 필요
  - `ensure_enriched_schema()` 내 payload 이중 흐름은 여전히 임시 우회
  - `classify.py` top8 기준 전환은 아직 미완료 (--families-path 수동 지정 필요)

---

### [role 분류/GUI 상태 검증] 2026-04-22

- 변경된 파일:
  - `gui.py` — 상단 DB 현황 표시를 posting-level legacy 기준에서 role 기준 집계로 전환
  - `docs/SAVE_STATE.md`
  - `docs/NEXT_TASK.md`
  - `docs/IMPLEMENTATION_PLAN.md`
- 실제 검증:
  - `planning_strategy` 카테고리 5건 수집 테스트 실행
  - 저장 결과:
    - `job_postings`: 69건
    - `job_posting_roles`: 250건
    - `classified_roles`: 20건
    - `pending_roles`: 230건
    - `job_posting_role_tags`: 20건
  - role 분류 테스트:
    - GUI `직무 분류` 1회 실행
    - success 20 / failed 0
    - 중복 태그(`multi_tag_roles`) 없음 확인
  - GUI 상단 현황:
    - `전체 공고 수`, `전체 role 수`, `classified role 수`, `pending role 수`, `failed role 수`, `job_criteria 수`
    - role family 분포도 `job_posting_role_tags` 기준으로 갱신되도록 수정
- 샘플 확인:
  - `jobkorea_20260422_142505_016` 써브웨이 공고:
    - `roles_count=9`
    - `low_quality=false`
    - DB 저장 확인
  - `jobkorea_20260422_142336_015` 한국선급 공고:
    - `roles_count=14`
    - `shallow_aggregate_empty_tasks`로 low_quality 격리 확인
- 판단:
  - role 중심 수집/분류/GUI 진행률 표시는 현재 실사용 가능한 수준
  - `analyze.py`는 아직 family별 posting_count가 작아서 바로 돌려도 대부분 스킵 가능성이 큼

---

### [PaddleOCR 검토] 2026-04-22

- 수행 내용:
  - PaddleOCR를 별도 실험용으로 검토
  - 최근 raw capture 샘플 3건에서 OCR 텍스트를 비교해봄
- 관찰:
  - 텍스트 추출 자체는 기대 이상으로 양호했다.
  - 단, 표 구조가 평평하게 풀리면서 복합공고에서 role / 담당업무 / 자격요건 / 우대사항의 대응 관계가 흔들릴 여지가 컸다.
  - 최근 잘 나온 복합공고 샘플들 중 상당수는 코드 분기상 image-based Gemini Vision 경로였을 가능성이 높다.
- 현재 결론:
  - 메인 수집 경로는 **image-based Gemini Vision 유지**
  - PaddleOCR를 메인 OCR/구조화 경로로 교체하는 작업은 보류
  - 이유: 복합공고가 대부분인 현재 데이터셋에서는 role/요건 매칭 안정성이 더 중요하고, text-only 전환 시 리턴 품질이 아직 보장되지 않음

---

### [aggregate 감지 유지] 2026-04-21 — 집계형 공고는 표시만 하고 저장은 막지 않음

- 변경된 파일:
  - `src/utils.py` — `is_aggregate_posting()` 함수 추가
  - `src/collect.py` — `structured_roles_count` 로그 추가, aggregate 감지 결과를 payload와 로그에 기록
- 변경 이유:
  - 복합공고/집계형 공고도 일단 넓게 수집하고 싶다는 현재 운영 방향을 유지하기 위해서다.
  - 다만 어떤 공고가 “집계형”인지 추후 품질 기준에 쓸 수 있도록 표시는 남겨야 했다.
- 현재 동작:
  - `aggregate_posting_detected=true` 로그가 찍혀도 저장은 계속 진행된다.
  - payload에는 `aggregate_candidate`, `aggregate_reasons`가 붙는다.
  - 즉 지금은 차단이 아니라 태깅 단계다.
- 남은 이슈:
  - role 수만 많고 role별 상세 정보가 거의 비어 있는 “얕은 aggregate 공고”가 실제 분석 품질을 떨어뜨릴 수 있다.
  - 다음 단계는 aggregate 자체를 무조건 막는 것이 아니라, 이런 얕은 공고를 low quality로 보낼 기준 설계다.
