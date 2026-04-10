# Python CLI JD Research Tool (Minimal)

PNG 채용공고 이미지를 입력받아 OCR로 텍스트를 추출하고, Gemini로 JD를 구조화한 뒤 JSON으로 저장하는 도구입니다.

## 폴더 구조

```
.
├── input/
├── output/
├── src/
│   ├── main.py
│   ├── ocr.py
│   └── structure_jd.py
├── .env.example
├── requirements.txt
└── README.md
```

## 1) 설치

```bash
python -m venv .venv
source .venv/bin/activate  # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

추가로 로컬에 Tesseract OCR 엔진이 설치되어 있어야 합니다.
이 프로젝트는 `src/ocr.py`에서 기본 경로 `C:\Program Files\Tesseract-OCR\tesseract.exe`를 사용합니다.

## 2) 환경 변수 설정

`.env.example`를 복사해 `.env`를 만들고 API 키를 입력하세요.

```bash
cp .env.example .env
```

`.env`:

```env
GEMINI_API_KEY=your_real_api_key
```

## 3) 실행

아래처럼 실행하면 파일 선택 창이 열립니다.

```bash
python src/main.py
```

PNG 여러 장을 선택하고 순서를 확인하면, OCR + 구조화 후 `output/jd_YYYYMMDD_HHMMSS.json` 형식으로 저장됩니다.

## 출력 JSON 형식

```json
{
  "company": "",
  "role": "",
  "main_tasks": [],
  "requirements": [],
  "preferred": [],
  "raw_text": "",
  "source_images": []
}
```

## 범위

- 포함: PNG -> OCR -> Gemini 구조화 -> JSON 저장
- 제외: 웹 UI, DB, 크롤링, 클러스터링

## Windows 실행파일(.exe) 빌드

친구 PC에 Python이 없어도 실행할 수 있도록 `PyInstaller`로 `jd-tool.exe`를 만들 수 있습니다.

중요:
- `.exe`로 패키징해도 Tesseract OCR은 별도 설치가 필요합니다.
- 기본 설치 경로는 `C:\Program Files\Tesseract-OCR\tesseract.exe` 기준입니다.

### 1) 빌드 준비 (Windows PowerShell)

```powershell
cd C:\path\to\jd-research-tool
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install pyinstaller
```

### 2) PyInstaller 빌드

아래 명령으로 `src/main.py`를 기준으로 실행파일 이름을 `jd-tool.exe`로 만듭니다.

```powershell
pyinstaller --name jd-tool --onefile --windowed --distpath .\dist --workpath .\build src\main.py
```

빌드 결과:
- `dist\jd-tool.exe` 생성
- `build\`, `jd-tool.spec` 생성

### 3) 실행파일 사용 방법

1. `.env` 파일에 `GEMINI_API_KEY`를 설정합니다.
2. `jd-tool.exe`를 실행합니다.
3. 파일 선택 창에서 PNG 여러 장을 선택합니다.
4. 결과 JSON은 실행 위치 기준 `output\` 폴더에 저장됩니다.

### 4) 친구에게 전달할 파일

최소 전달 권장:
- `jd-tool.exe` (`dist\jd-tool.exe`)
- `.env` (API 키 포함)
- `output\` 폴더(없으면 생성 가능하지만 같이 주는 것을 권장)
- 사용 안내 문서(README 일부 또는 별도 txt)

필수 안내:
- 친구 PC에 Tesseract OCR 설치 필요
- 설치 경로는 `C:\Program Files\Tesseract-OCR\` 권장
