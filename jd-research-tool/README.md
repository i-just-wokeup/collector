# jd-research-tool

`jd-research-tool`은 채용공고 이미지나 텍스트를 Gemini로 구조화해
표준 JSON 스키마로 저장하는 로컬 도구입니다.

현재 기본 실행 경로는 OCR 파이프라인이 아니라
`Gemini Vision`으로 PNG 여러 장을 직접 읽어 구조화하는 방식입니다.

## 현재 동작 방식

메인 엔트리포인트:

```bash
python src/main.py
```

실행하면 파일 선택 창이 열리고 PNG 여러 장을 고를 수 있습니다.
사용자가 이미지 순서를 확인한 뒤, `vision_structure_jd.py`의
`structure_jd_images()`를 호출해 결과를 `output/jd_YYYYMMDD_HHMMSS.json`으로 저장합니다.

즉, 현재 기본 경로는 아래와 같습니다.

- PNG 선택
- Gemini Vision으로 이미지 직접 분석
- 구조화 JSON 저장

## 지원 입력

- PNG 이미지 여러 장
- 이미지 순서는 사용자가 직접 확인

현재 `src/main.py`는 PNG만 허용합니다.

## 출력 JSON 스키마

복합공고(여러 모집부문·트랙·과제가 있는 공고)를 role별로 분리하는 구조입니다.

```json
{
  "company": "회사명",
  "posting_title": "공고 제목",
  "common_requirements": ["공통 지원자격1"],
  "common_preferred": ["공통 우대사항1"],
  "roles": [
    {
      "role_name": "직무/모집부문 명칭",
      "main_tasks": ["담당업무1"],
      "requirements": ["이 직무 전용 자격요건1"],
      "preferred": ["이 직무 전용 우대사항1"]
    }
  ],
  "raw_text": "",
  "source_images": [],
  "role": "(compat shim: roles[0].role_name)",
  "main_tasks": "(compat shim: roles[0].main_tasks)",
  "requirements": "(compat shim: common_requirements + roles[0].requirements)",
  "preferred": "(compat shim: common_preferred + roles[0].preferred)"
}
```

필드 설명:

- `company`: 회사명
- `posting_title`: 공고 제목
- `common_requirements`: 모든 지원자에게 공통으로 적용되는 지원자격
- `common_preferred`: 모든 지원자에게 공통으로 적용되는 우대사항
- `roles`: 모집부문별 역할 블록 배열 (단일 직무도 1개 요소로 포함)
  - `role_name`: 직무/모집부문 명칭
  - `main_tasks`: 해당 role 담당업무
  - `requirements`: 해당 role 전용 자격요건
  - `preferred`: 해당 role 전용 우대사항
- `raw_text`: 원문 전체 텍스트
- `source_images`: 입력 이미지 파일명 목록
- `role`, `main_tasks`, `requirements`, `preferred`: **하위호환 shim** — jd-collector-agent가 기존 단일 role 읽기 경로를 유지할 수 있도록 `roles[0]` + `common_*`를 조합해 자동 생성

## 폴더 구조

현재 저장소 기준 주요 파일:

```text
.
├── input/
├── output/
├── src/
│   ├── main.py
│   ├── ocr.py
│   ├── structure_jd.py
│   └── vision_structure_jd.py
├── build/
├── dist/
├── jd-tool.spec
├── requirements.txt
└── README.md
```

참고:

- README 작성 시점 기준 `.env.example` 파일은 저장소에 없습니다.
- `build/`, `dist/`, `jd-tool.spec`는 Windows 실행파일 빌드 결과와 설정 파일입니다.

## 설치

```bash
python -m venv .venv
source .venv/bin/activate  # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

`requirements.txt`:

- `opencv-python`
- `pillow`
- `pytesseract`
- `python-dotenv`
- `google-genai`

## 환경 변수

`.env` 파일에 최소한 아래 키가 필요합니다.

```env
GEMINI_API_KEY=your_real_api_key
```

## 실행

```bash
python src/main.py
```

실행 흐름:

1. PNG 파일 선택 창이 열림
2. 선택한 이미지 목록과 순서를 콘솔에 출력
3. 사용자가 `y` 입력 시 계속 진행
4. Gemini Vision으로 구조화 수행
5. `output/jd_YYYYMMDD_HHMMSS.json` 저장

## 모듈 설명

### `src/main.py`

- GUI 파일 선택 창 제공
- PNG 확장자 검증
- `vision_structure_jd.py` 호출
- 최종 JSON 저장

### `src/vision_structure_jd.py`

- PNG 파일들을 Gemini 멀티모달 입력으로 전달
- 공고 전체를 읽어 구조화 JSON으로 반환
- 반환 후 `source_images`에 파일명을 채움

현재 메인 플로우에서 가장 중요한 모듈입니다.

### `src/structure_jd.py`

- 이미 OCR이나 DOM 추출 등으로 얻은 `raw_text`를 입력받아
  텍스트 기반 구조화 JSON으로 변환합니다.
- 다른 프로젝트에서 재사용하기 좋은 텍스트 구조화용 모듈입니다.

### `src/ocr.py`

- Tesseract OCR 유틸리티가 들어 있습니다.
- 현재 `src/main.py` 기본 실행 흐름에서는 직접 호출하지 않습니다.
- 필요 시 이미지 OCR 전처리 또는 별도 실험용으로 사용할 수 있습니다.

## Tesseract OCR에 대해

이 저장소에는 `pytesseract` 기반 `ocr.py`가 포함되어 있지만,
현재 기본 사용 경로는 `Gemini Vision`이므로 Tesseract가 필수는 아닙니다.

다만 `ocr.py`를 직접 사용하거나 별도 스크립트에서 재활용할 경우에는
로컬에 Tesseract OCR 엔진이 설치되어 있어야 합니다.

`ocr.py`의 탐색 순서:

1. 시스템 `PATH`의 `tesseract`
2. `C:\Program Files\Tesseract-OCR\tesseract.exe`
3. `C:\Program Files (x86)\Tesseract-OCR\tesseract.exe`

## jd-collector-agent와의 관계

`jd-collector-agent`는 이 프로젝트의 모듈을 직접 import 해서 사용합니다.

재사용되는 핵심 함수:

- `vision_structure_jd.structure_jd_images`
- `structure_jd.structure_jd_text`

즉 이 프로젝트는 독립 실행 도구이면서, 동시에
상위 수집 파이프라인에서 호출되는 구조화 엔진 역할도 합니다.

## Windows 실행파일(.exe) 빌드

`PyInstaller`로 `jd-tool.exe`를 만들 수 있습니다.

### 1) 준비

```powershell
cd C:\path\to\jd-research-tool
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install pyinstaller
```

### 2) 빌드

```powershell
pyinstaller --name jd-tool --onefile --windowed --distpath .\dist --workpath .\build src\main.py
```

빌드 결과:

- `dist\jd-tool.exe`
- `build\`
- `jd-tool.spec`

### 3) 사용

1. `.env`에 `GEMINI_API_KEY` 설정
2. `jd-tool.exe` 실행
3. PNG 파일 선택
4. 결과 JSON 확인

## 범위

포함:

- PNG 여러 장 선택
- Gemini Vision 기반 구조화
- 텍스트 기반 구조화 모듈 제공
- JSON 저장

비포함:

- 웹 크롤링
- DB 저장
- 분류/클러스터링
- 완성형 GUI 워크플로우
