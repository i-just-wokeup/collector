# AGENTS

이 저장소에서 Claude Code 또는 다른 에이전트는 아래 규칙을 기본으로 따른다.

## 1) 목적
- 이 저장소의 목적은 채용공고를 수집하고 구조화한 뒤 SQLite DB에 적재하고,
  직무 분류 및 역량 분석까지 수행하는 것이다.
- 이 저장소는 `my-app`의 평가 기준 참고 DB를 만드는 보조 도구다.

## 2) 작업 시작 전 확인
1. `README.md`
2. `init_db.py`
3. `gui.py`
4. `src/collect.py`
5. `src/classify.py`
6. `src/analyze.py`
7. `src/export_csv.py`

## 3) 이 저장소에서 중요한 경로
- 프로젝트 루트: `jd-collector-agent/`
- DB 초기화 스크립트: `jd-collector-agent/init_db.py`
- 직무군 시드 파일: `jd-collector-agent/job_families.json`
- GUI 실행 파일: `jd-collector-agent/gui.py`
- 검수용 CSV export: `jd-collector-agent/src/export_csv.py`
- 출력 폴더: `jd-collector-agent/output/`

## 4) 환경 준비 규칙
- Python 3.10+ 권장
- 패키지 설치:
  - `pip install -r requirements.txt`
  - `playwright install chromium`
- `.env`는 로컬에만 생성하고 절대 커밋하지 않는다.

`.env` 예시:

```env
GEMINI_API_KEY=your_real_api_key
JD_DB_PATH=C:\dev\jd_data_friend.db
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
GEMINI_MODEL=gemini-2.5-flash
```

## 5) 실행 순서
1. `python init_db.py`
2. `python gui.py`
3. GUI에서 `수집 시작`
4. 수집 완료 후 `직무 분류`
5. 분류 완료 후 `역량 분석`
6. 필요 시 `python src/export_csv.py` 또는 `python src/export_csv.py --all`

## 6) Claude Code가 자동으로 해도 되는 일
- 코드/문서 읽기
- `requirements.txt` 설치 명령 안내
- `init_db.py`, `src/export_csv.py --help` 같은 비파괴성 확인 실행
- `.env` 템플릿 작성 안내
- GUI 실행 전후 로그 해석
- 수집 완료 후 CSV export 실행
- README/AGENTS.md 같은 문서 수정

## 7) Claude Code가 혼자 하면 안 되는 일
- 실제 Gemini API 키를 임의로 입력
- 사용자의 계정 로그인/지원 버튼 클릭이 필요한 단계 강행
- `.env`, `.db`, `output/` 결과물을 Git에 커밋
- 수집 결과 DB를 삭제하거나 초기화
- 사용자가 돌리고 있는 GUI를 임의로 종료

## 8) 사람이 직접 해야 하는 일
- 본인 API 키 준비
- `.env`에 본인 DB 경로 입력
- 필요한 경우 사이트 로그인
- 수집 키워드/목표 수 결정
- 결과 DB/CSV를 상대방에게 전달

## 9) 결과물 관리 규칙
- 코드와 문서만 Git으로 공유한다.
- 아래 결과물은 로컬에서만 관리한다.
  - `.env`
  - `*.db`
  - `output/raw_captures/`
  - `output/failed_capture/`
  - `output/low_quality/`
  - `output/export_*.csv`
- 친구와 공유할 때는 보통 아래 두 개만 전달한다.
  - DB 파일 (`jd_data_friend.db` 등)
  - CSV 파일 (`output/export_*.csv`)

## 10) 친구 PC에서 실행할 때 권장 DB 파일명
- 본인: `C:\dev\jd_data_me.db`
- 친구: `C:\dev\jd_data_friend.db`

같은 DB 파일을 같이 쓰지 말고, 각자 따로 만든 뒤 결과 파일만 교환한다.

## 11) 커밋 규칙
- 커밋 대상:
  - `init_db.py`
  - `job_families.json`
  - `src/*.py`
  - `README.md`
  - `AGENTS.md`
- 커밋 제외:
  - `.env`
  - `*.db`
  - `output/`
  - `.codex/`

## 12) Claude Code에게 바로 줄 수 있는 작업 지시 예시
- "README.md와 AGENTS.md를 읽고 친구 PC 실행 준비가 끝났는지 체크해줘."
- "현재 `.env` 없이 실행 가능한 단계와 사람이 직접 해야 하는 단계를 분리해서 알려줘."
- "수집 완료 후 `python src/export_csv.py --all` 실행 전에 필요한 확인 사항만 점검해줘."

